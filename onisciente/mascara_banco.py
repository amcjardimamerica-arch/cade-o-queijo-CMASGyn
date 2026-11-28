"""CPF de pessoa física mascarado no banco da coleta (28/11/2026, o banco vai a um repositório público).

O CPF completo de pessoa física não fica gravado: vira ``***.NNN.NNN-**``, os seis dígitos do meio, como o
Portal da Transparência e o QSA da Receita publicam (``onisciente.mascara_cpf.mascara``). CNPJ fica inteiro.

* Na gravação: ``historico.Banco.inserir`` passa cada linha por ``mascarar_linha``. As colunas tratadas são as
  que a varredura do banco real apontou (``COLUNAS``). Numa coluna de documento (``cnpj_cpf``,
  ``fornecedor_ni``), o CPF de 11 dígitos (ou formatado, ou com ``000`` na frente) é mascarado e o CNPJ fica.
  Num texto livre (nome, objeto, processo, json), só o CPF formatado (``NNN.NNN.NNN-NN``) e o de 11 dígitos
  seguidos com dígito verificador válido, que não esteja colado a letra ou outro dígito (um hash, um
  telefone, um processo com dígito que não confere ficam como estão).
* Nas linhas antigas: ``migrar`` (chamado na abertura do Banco) mascara o que já está gravado, numa rodada do
  rastreio só para isso (modo ``mascara_cpf``). Cada linha mascarada ganha selo novo com a mesma origem do
  selo antigo, e o selo antigo fica descartado por essa rodada.
* A trava: ``varrer`` procura CPF completo válido em todas as tabelas do banco e das partes.

``despesa_eventos`` (a despesa de Goiânia) fica com o coletor dela (``goiania_transweb``), que mascara ao ler
a planilha; ela grava direto pela conexão, sem passar por ``Banco.inserir``.
"""

from __future__ import annotations

import re

from . import mascara_cpf as _mc
from . import partes, rastreio

DOCUMENTO = "documento"
TEXTO = "texto"

# Tabela -> coluna -> como mascarar. As colunas que a varredura de 28/11/2026 achou com CPF completo.
COLUNAS: dict[str, dict[str, str]] = {
    "sancoes": {"cnpj_cpf": DOCUMENTO, "nome": TEXTO, "processo": TEXTO},
    "pncp_itens": {"fornecedor_ni": DOCUMENTO, "fornecedor": TEXTO},
    "contratos_pncp": {"fornecedor_ni": DOCUMENTO, "fornecedor": TEXTO, "objeto": TEXTO},
    "contratacoes_pncp": {"objeto": TEXTO},
    "emendas_municipio": {"nome": TEXTO, "json": TEXTO},
}

MODO = "mascara_cpf"
# Onze dígitos seguidos, sem letra nem dígito colados (um hash hexadecimal tem letras ao lado).
_ONZE = re.compile(r"(?<![0-9A-Za-z])\d{11}(?![0-9A-Za-z])")
_FORMATADO = _mc._FORMATADO
# Coluna que guarda um documento (para a varredura): CPF, CNPJ, documento, NI, favorecido.
_COLUNA_DE_DOCUMENTO = re.compile(r"(?i)(cpf|cnpj|documento|favorecido|(^|_)ni$)")


def mascarar_texto(texto: str) -> str:
    """Texto livre com o CPF formatado e o de 11 dígitos válido trocados pela máscara."""
    if not isinstance(texto, str) or not any(c.isdigit() for c in texto):
        return texto
    texto = _FORMATADO.sub(lambda m: _mc.mascara(m.group(0)), texto)
    return _ONZE.sub(lambda m: _mc.mascara(m.group(0)) if _mc._cpf_valido(m.group(0)) else m.group(0), texto)


def mascarar_documento(valor):
    """Valor de uma coluna de documento: CPF (11 dígitos, formatado ou com ``000`` na frente) vira a
    máscara; CNPJ, valor já mascarado e o que não é documento ficam como estão."""
    if isinstance(valor, int) and not isinstance(valor, bool):
        valor = str(valor)
    if not isinstance(valor, str) or "*" in valor:
        return valor
    bruto = valor.strip()
    if _FORMATADO.fullmatch(bruto):
        return _mc.mascara(bruto)
    cpf = _mc._cpf_da_coluna(bruto)
    return _mc.mascara(cpf) if cpf else valor


def mascarar_valor(tabela: str, coluna: str, valor):
    modo = COLUNAS.get(tabela, {}).get(coluna)
    if modo == DOCUMENTO:
        return mascarar_documento(valor)
    if modo == TEXTO:
        return mascarar_texto(valor)
    return valor


def mascarar_linha(tabela: str, linha: dict) -> dict:
    """A linha com as colunas de CPF mascaradas (a mesma linha, quando a tabela não tem nenhuma)."""
    colunas = COLUNAS.get(tabela)
    if not colunas or not any(c in linha for c in colunas):
        return linha
    return {k: mascarar_valor(tabela, k, v) if k in colunas else v for k, v in linha.items()}


# --- Linhas antigas -------------------------------------------------------------------------------

def pendentes(con) -> dict[str, list[tuple[int, dict]]]:
    """Por tabela, as linhas gravadas com CPF completo: (rowid, {coluna: valor mascarado})."""
    saida: dict[str, list[tuple[int, dict]]] = {}
    for tabela, colunas in COLUNAS.items():
        if not partes.tem_tabela(con, tabela):
            continue
        existentes = [c for c in colunas if c in {x[1] for x in con.execute(f'PRAGMA table_info("{tabela}")')}]
        if not existentes:
            continue
        lista = ", ".join(f'"{c}"' for c in existentes)
        for rowid, *valores in con.execute(f'SELECT rowid, {lista} FROM "{tabela}"'):
            troca = {}
            for c, v in zip(existentes, valores):
                novo = mascarar_valor(tabela, c, v)
                if novo != v and not (isinstance(v, int) and novo == str(v)):
                    troca[c] = novo
            if troca:
                saida.setdefault(tabela, []).append((rowid, troca))
    return saida


def migrar(con) -> dict[str, dict[str, int]]:
    """Mascara as linhas antigas numa rodada do rastreio (modo ``mascara_cpf``) e devolve, por tabela e
    coluna, quantos valores mudaram. Sem nada a mascarar, não abre rodada."""
    trocas = pendentes(con)
    if not trocas:
        return {}
    rastreio.preparar(con)
    total = sum(len(v) for v in trocas.values())
    rid = rastreio.abrir_rodada(con, (), MODO, detalhe={
        "nota": f"CPF de pessoa física mascarado (***.NNN.NNN-**) em {total} linha(s) gravadas antes da máscara; "
                "cada linha mantém a origem do selo anterior, que fica descartado por esta rodada"})
    contagem: dict[str, dict[str, int]] = {}
    for tabela, linhas in trocas.items():
        tid = rastreio._id_tabela(con, tabela)
        for rowid, troca in linhas:
            antes = rastreio.linha(con, tabela, rowid)
            selo = con.execute("SELECT origem FROM rastreio_selos WHERE tabela = ? AND hash = ?",
                               (tid, rastreio._digest(tabela, antes))).fetchone()
            con.execute("INSERT OR REPLACE INTO rastreio_cursor (chave, valor) VALUES ('origem', ?)",
                        (selo[0] if selo else None,))
            sets = ", ".join(f'"{c}" = ?' for c in troca)
            con.execute(f'UPDATE "{tabela}" SET {sets} WHERE rowid = ?', [*troca.values(), rowid])
            for c in troca:
                contagem.setdefault(tabela, {}).setdefault(c, 0)
                contagem[tabela][c] += 1
    rastreio.fechar_rodada(con, rid)
    return contagem


# --- A varredura (a trava) ------------------------------------------------------------------------

def cpfs_no_valor(coluna: str, valor) -> int:
    """Quantos CPFs completos válidos há num valor: formatados ou 11 dígitos seguidos (texto), e, numa
    coluna de documento, também o número inteiro e o CPF com ``000`` na frente."""
    documento = bool(_COLUNA_DE_DOCUMENTO.search(coluna))
    if isinstance(valor, int) and not isinstance(valor, bool):
        if not documento:
            return 0
        valor = str(valor)
    if not isinstance(valor, str) or not any(c.isdigit() for c in valor):
        return 0
    n = sum(1 for m in _FORMATADO.finditer(valor) if _mc._cpf_valido(re.sub(r"\D", "", m.group(0))))
    n += sum(1 for m in _ONZE.finditer(valor) if _mc._cpf_valido(m.group(0)))
    if documento and n == 0:
        bruto = valor.strip()
        if len(bruto) == 14 and _mc._cpf_da_coluna(bruto):
            n = 1
    return n


def varrer(con) -> dict[tuple[str, str], int]:
    """(tabela, coluna) -> CPFs completos válidos, em todas as tabelas do banco e das partes (o rastreio,
    que só guarda hashes, fica de fora). Vazio: o banco está limpo."""
    achados: dict[tuple[str, str], int] = {}
    for tabela, esquema in partes.tabelas(con).items():
        if tabela.startswith(rastreio.PREFIXO):
            continue
        colunas = [c[1] for c in con.execute(f'PRAGMA {esquema}.table_info("{tabela}")')]
        for linha in con.execute(f'SELECT * FROM {esquema}."{tabela}"'):
            for c, v in zip(colunas, linha):
                n = cpfs_no_valor(c, v)
                if n:
                    achados[(tabela, c)] = achados.get((tabela, c), 0) + n
    return achados
