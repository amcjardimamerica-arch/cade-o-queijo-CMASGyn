"""A máscara de CPF que o banco aplicava de 28/11/2026 (ee68c14) até a decisão do usuário do mesmo dia, às
11:18Z (config/decisoes_usuario.yml, P-01: "Os dados devem ser públicos e não mascarar").

Revogada na gravação: ``historico.Banco.inserir`` grava a linha como veio, ``Banco.abrir`` não muda nenhuma
linha e ``impedimentos.gravar`` também. O módulo fica, só com funções que não gravam nada, para reconhecer o
que o sistema mascarou e devolver o dado da fonte (``onisciente.restauracao_fonte``):

* ``mascarar_linha`` (e ``mascarar_valor``, ``mascarar_documento``, ``mascarar_texto``): a linha como a
  máscara a deixava. A restauração casa a linha mascarada do banco com a linha antiga cuja máscara dá ela.
* ``COLUNAS``: as tabelas e as colunas que a máscara tocava.
* ``varrer``: quantos CPFs inteiros válidos há em cada tabela e coluna (só lê).
"""

from __future__ import annotations

import re

from . import mascara_cpf as _mc
from . import partes, rastreio  # noqa: F401 (rastreio: PREFIXO na varredura)

DOCUMENTO = "documento"
TEXTO = "texto"

# Tabela -> coluna -> como mascarar. As colunas que a varredura de 28/11/2026 achou com CPF completo.
COLUNAS: dict[str, dict[str, str]] = {
    "sancoes": {"cnpj_cpf": DOCUMENTO, "nome": TEXTO, "processo": TEXTO},
    "pncp_itens": {"fornecedor_ni": DOCUMENTO, "fornecedor": TEXTO},
    "contratos_pncp": {"fornecedor_ni": DOCUMENTO, "fornecedor": TEXTO, "objeto": TEXTO},
    "contratacoes_pncp": {"objeto": TEXTO},
    "emendas_municipio": {"nome": TEXTO, "json": TEXTO},
    # CEPIM e inidôneos do TCU: o coletor grava pela própria função (``impedimentos.gravar``), que passa
    # cada linha por ``mascarar_linha``. A leitura (``impedimentos.documento``) já entende o mascarado.
    "impedimentos": {"cnpj_cpf": DOCUMENTO, "nome": TEXTO, "processo": TEXTO},
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
