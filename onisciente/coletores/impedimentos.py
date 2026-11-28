"""Impedimentos de contratar: CEPIM e a lista de licitantes inidôneos do TCU, e a leitura unificada
das sanções (CEIS, CNEP, CEPIM, TCU) para as conferências das empresas.

* **CEPIM** (Cadastro de Entidades Privadas sem Fins Lucrativos Impedidas), arquivo diário de dados
  abertos do Portal da Transparência (``download-de-dados/cepim/AAAAMMDD``): zip com um CSV em latin-1,
  separado por ``;``, com cabeçalho. O CEPIM não traz a data do impedimento: o registro vale para a data
  do arquivo, e a conferência diz isso.
* **Inidôneos do TCU** (Lei 8.443/1992, art. 46): a lista pública de certidões do TCU, em JSON
  paginado. O formato da API não está documentado; o leitor aceita as formas mais comuns (lista na raiz
  ou dentro de ``items``, ``content``, ``data``, ``registros``) e acha os campos pelo nome.

O CEIS e o CNEP são coletados por outra frente (``onisciente/coletores/sancoes.py``), na tabela
``sancoes``. Para as conferências tanto faz de onde veio: ``ler_sancoes`` junta a tabela ``sancoes``
(se existir) e a tabela ``impedimentos`` deste módulo num formato só.

Esquema esperado da tabela ``sancoes`` (interface com a coleta do CEIS e do CNEP)::

    sancoes(cnpj_cpf TEXT,   -- CNPJ completo, ou CPF (inteiro ou mascarado como ***.123.456-**)
            cadastro TEXT,   -- 'CEIS', 'CNEP' (ou outro cadastro)
            inicio TEXT,     -- AAAA-MM-DD: início da sanção
            fim TEXT,        -- AAAA-MM-DD: fim da sanção; vazio = sem prazo
            orgao TEXT,      -- órgão sancionador
            tipo TEXT,       -- categoria da sanção (inidoneidade, impedimento, suspensão...)
            nome TEXT)       -- opcional, mas pedido: nome ou razão do sancionado (casa CPF mascarado)
"""

from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from datetime import date, timedelta

from .. import partes as _partes
from .cnpj import cnpj_valido, data_iso, so_cnpj

CEPIM = "https://portaldatransparencia.gov.br/download-de-dados/cepim/"
TCU_INIDONEOS = "https://certidoes.apps.tcu.gov.br/api/publico/responsaveis-inidoneos-com-paginacao"
TCU_LISTA = "https://certidoes.apps.tcu.gov.br/lista-inidoneos"

ESQUEMA = """
CREATE TABLE IF NOT EXISTS impedimentos (cnpj_cpf TEXT, cadastro TEXT, inicio TEXT, fim TEXT, orgao TEXT,
    tipo TEXT, nome TEXT, processo TEXT, fonte TEXT, data_base TEXT);
"""


def _norm(t) -> str:
    t = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t.upper()).strip()


def url_cepim(dia: date) -> str:
    return CEPIM + dia.strftime("%Y%m%d")


def dias_para_tentar(hoje: date, n: int = 7) -> list[date]:
    """O arquivo do dia sai no dia seguinte: tenta de ontem para trás."""
    return [hoje - timedelta(days=i) for i in range(1, n + 1)]


def linhas_cepim(conteudo: bytes, dia: date) -> list[dict]:
    """As linhas do CEPIM. Levanta ``ValueError`` se não é o zip esperado ou se o cabeçalho mudou."""
    try:
        z = zipfile.ZipFile(io.BytesIO(conteudo))
    except zipfile.BadZipFile as e:
        raise ValueError(f"não é zip: {e}") from e
    nomes = [n for n in z.namelist() if n.lower().endswith(".csv")]
    if not nomes:
        raise ValueError("o zip não traz CSV")
    with z.open(nomes[0]) as bruto:
        leitor = csv.reader(io.TextIOWrapper(bruto, encoding="latin-1", newline=""), delimiter=";")
        cab = [_norm(c) for c in next(leitor, [])]
        idx = {c: i for i, c in enumerate(cab)}

        def coluna(*opcoes):
            for o in opcoes:
                for c, i in idx.items():
                    if o in c:
                        return i
            return None
        i_doc = coluna("CNPJ")
        i_nome = coluna("NOME")
        i_conv = coluna("CONVENIO")
        i_org = coluna("ORGAO")
        i_mot = coluna("MOTIVO")
        if i_doc is None or i_nome is None:
            raise ValueError(f"o cabeçalho mudou: {', '.join(cab)}")
        saida = []
        for linha in leitor:
            if len(linha) <= max(i_doc, i_nome):
                continue
            pega = (lambda i: linha[i].strip() if i is not None and i < len(linha) else "")
            saida.append({"cnpj_cpf": so_cnpj(pega(i_doc)), "cadastro": "CEPIM", "inicio": None, "fim": None,
                          "orgao": pega(i_org) or None, "tipo": pega(i_mot) or "impedimento (CEPIM)",
                          "nome": _norm(pega(i_nome)) or None, "processo": pega(i_conv) or None,
                          "fonte": "Portal da Transparência, CEPIM (arquivo diário)", "data_base": dia.isoformat()})
    return saida


def _chave(item: dict, *padroes: str) -> str:
    for k, v in item.items():
        nk = re.sub(r"[^a-z]", "", str(k).lower())
        if any(p in nk for p in padroes) and v not in (None, ""):
            return str(v).strip()
    return ""


def _data(texto: str) -> str | None:
    t = str(texto or "").strip()
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", t)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        return m.group(0)
    return data_iso(t)


def pagina_tcu(conteudo: bytes | str) -> tuple[list[dict], bool]:
    """Uma página da lista de inidôneos do TCU: (linhas, há mais páginas).
    Levanta ``ValueError`` se a resposta não é a lista."""
    try:
        d = json.loads(conteudo)
    except (TypeError, ValueError) as e:
        raise ValueError(f"não é JSON: {e}") from e
    itens = d if isinstance(d, list) else next(
        (d[k] for k in ("items", "content", "data", "registros", "dados", "resultado", "responsaveis")
         if isinstance(d, dict) and isinstance(d.get(k), list)), None)
    if itens is None:
        raise ValueError("a resposta não traz a lista de inidôneos")
    saida = []
    for it in itens:
        if not isinstance(it, dict):
            continue
        doc = so_cnpj(_chave(it, "cpfcnpj", "cnpjcpf", "cnpj", "cpf", "documento", "nudoc"))
        nome = _norm(_chave(it, "nome", "razao", "responsavel"))
        if not doc and not nome:
            continue
        saida.append({
            "cnpj_cpf": doc or None, "cadastro": "TCU-INIDONEOS",
            "inicio": _data(_chave(it, "transito", "datainicio", "dtinicio", "inicio", "datapublicacao")),
            "fim": _data(_chave(it, "datafinal", "datafim", "dtfim", "fim", "termino", "validade")),
            "orgao": "Tribunal de Contas da União", "tipo": "declaração de inidoneidade (Lei 8.443/1992, art. 46)",
            "nome": nome or None,
            "processo": _chave(it, "processo", "deliberacao", "acordao") or None,
            "fonte": "TCU, lista de licitantes inidôneos", "data_base": date.today().isoformat()})
    mais = False
    if isinstance(d, dict):
        if d.get("hasMore") or d.get("has_more"):
            mais = True
        elif d.get("last") is False:
            mais = True
        else:
            pag, tot = d.get("number", d.get("pagina")), d.get("totalPages", d.get("totalPaginas"))
            if isinstance(pag, int) and isinstance(tot, int):
                mais = pag + 1 < tot
    return saida, mais


def url_tcu(pagina: int, tamanho: int = 500) -> str:
    return f"{TCU_INIDONEOS}?pagina={pagina}&tamanhoPagina={tamanho}&page={pagina}&size={tamanho}"


def preparar(con) -> None:
    con.executescript(ESQUEMA)


def gravar(con, linhas: list[dict], cadastro: str) -> None:
    """Substitui o que havia do cadastro pelas linhas novas (a lista é a fotografia do dia)."""
    preparar(con)
    con.execute("DELETE FROM impedimentos WHERE cadastro = ?", (cadastro,))
    for l in linhas:
        con.execute(f"INSERT INTO impedimentos ({', '.join(l)}) VALUES ({', '.join('?' * len(l))})",
                    list(l.values()))
    con.commit()


# --- Leitura unificada para as conferências -------------------------------------------------------

@dataclass(frozen=True)
class Sancao:
    doc: str                 # CNPJ completo, CPF completo ou os 6 dígitos do meio de um CPF mascarado
    tipo_doc: str            # PJ, PF ou PF6 (CPF mascarado)
    cadastro: str
    inicio: str | None
    fim: str | None
    orgao: str
    tipo: str
    nome: str
    data_base: str | None = None

    def vigente_em(self, dia: str) -> bool:
        """Vigente no dia (AAAA-MM-DD). Sem data de início (CEPIM), vale para a data da fotografia em
        diante: o impedimento consta, e a data incerta é dita na ficha."""
        inicio = self.inicio or self.data_base
        if inicio and dia < inicio:
            return False
        return not (self.fim and dia > self.fim)


def documento(texto) -> tuple[str, str]:
    """('PJ', cnpj), ('PF', cpf inteiro) ou ('PF6', seis dígitos do meio do CPF mascarado)."""
    bruto = str(texto or "")
    c = so_cnpj(bruto)
    if len(c) == 14 and cnpj_valido(c):
        return "PJ", c
    digitos = re.sub(r"\D", "", bruto)
    if len(digitos) == 11 and "*" not in bruto:
        return "PF", digitos
    if len(digitos) == 6:
        return "PF6", digitos
    if len(digitos) == 14:
        return "PJ", digitos
    return "", ""


def miolo_cpf(texto) -> str:
    """Os seis dígitos do meio do CPF (posições 4 a 9), a parte que a Receita e o Portal publicam."""
    tipo, doc = documento(texto)
    if tipo == "PF":
        return doc[3:9]
    if tipo == "PF6":
        return doc
    return ""


def _tabela(con, nome: str) -> bool:
    return _partes.tem_tabela(con, nome)


def ler_sancoes(con) -> list[Sancao]:
    """Todas as sanções do banco: a tabela ``sancoes`` (CEIS, CNEP; outra frente) e a tabela
    ``impedimentos`` (CEPIM, TCU; esta frente)."""
    saida: list[Sancao] = []
    for tabela in ("sancoes", "impedimentos"):
        if not _tabela(con, tabela):
            continue
        cols = {c[1] for c in con.execute(f"PRAGMA table_info({tabela})")}
        nome = "nome" if "nome" in cols else "NULL"
        base = "data_base" if "data_base" in cols else "NULL"
        for doc, cad, ini, fim, org, tipo, nm, db in con.execute(
                f"SELECT cnpj_cpf, cadastro, inicio, fim, orgao, tipo, {nome}, {base} FROM {tabela}"):
            t, d = documento(doc)
            if not t and not nm:
                continue
            saida.append(Sancao(d, t, str(cad or tabela).upper(), _data(ini) if ini else None,
                                _data(fim) if fim else None, str(org or ""), str(tipo or ""), _norm(nm),
                                _data(db) if db else None))
    return saida
