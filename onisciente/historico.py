"""Coleta histórica: liga os motores de busca para um intervalo de meses.

    python -m onisciente historico --desde 2024-11 --ate 2026-11

Cada motor lê uma fonte pública, mês a mês ou período a período, e tudo vai
para um banco SQLite (``dados/onisciente/historico.db``). Cada chamada fica
registrada na tabela ``coletas``, com o resultado, o código HTTP, as
tentativas e o tempo. No fim, o diagnóstico diz, motor a motor e mês a mês,
onde a coleta alcança, onde falha e o que mudar.

A separação de sempre vale aqui: quando a fonte respondeu e o dado não estava
lá, é lacuna do município (roxo); quando a fonte não respondeu, é falha do
próprio sistema (vermelho). As duas nunca se misturam.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode

from . import RAIZ
from .coletores import base

BANCO = RAIZ / "dados" / "onisciente" / "historico.db"
SAIDA = RAIZ / "relatorios" / "onisciente"

SICONFI = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt/"
SICONFI_ANTIGAS = ("https://apidatatransparencia.tesouro.gov.br/ords/siconfi/tt/",
                   "https://apidados.tesouro.gov.br/ords/siconfi/tt/")
QUERIDO_DIARIO = "https://api.queridodiario.ok.org.br/gazettes"
SILEG_SOLR = "https://sileg.goiania.go.gov.br/solr-4.1.0/select"
PNCP = "https://pncp.gov.br/api/consulta/v1/"
FNAS_PAGINA = "https://fnas.mds.gov.br/extracao-dos-valores-repassados-fundo-a-fundo/"
FNAS_CONHECIDAS = {
    2024: "https://fnas.mds.gov.br/wp-content/uploads/2026/02/REPASSES_ANO_2024.xlsx",
    2025: "https://fnas.mds.gov.br/wp-content/uploads/2026/02/REPASSES_ANO_2025.xlsx",
}
NAVEGADOR = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/120"}

TERMOS = ("Assistência Social", "CMASGyn", "Fundo Municipal de Assistência Social",
          "Índice de Gestão Descentralizada")
TERMOS_PASTA = ("ASSISTENCIA SOCIAL", "SEMAS", "FUNDO MUNICIPAL DE ASSISTENCIA",
                "DIREITOS HUMANOS", "POLITICAS PARA AS MULHERES")

# Anexos do SICONFI cujos itens vão para o banco. Os demais só são contados.
ANEXOS_GUARDADOS = {
    "RREO": re.compile(r"anexo 0?(1|2|3|4|6|8|12|13|14)$"),
    "RGF": re.compile(r"anexo 0?[1-6]$"),
    "DCA": re.compile(r"anexo i-(c|d|e)$"),
}
# Modalidades do PNCP usadas para descobrir os órgãos municipais
# (6 pregão eletrônico, 8 dispensa, 9 inexigibilidade, 4 concorrência eletrônica).
MODALIDADES_DESCOBERTA = (6, 8, 9, 4)


# --- Calendário ---------------------------------------------------------------------

def meses(desde: str, ate: str) -> list[str]:
    """Todos os meses ``AAAA-MM`` de ``desde`` a ``ate``, inclusive."""
    a, m = map(int, desde.split("-"))
    fim = tuple(map(int, ate.split("-")))
    saida = []
    while (a, m) <= fim:
        saida.append(f"{a:04d}-{m:02d}")
        a, m = (a + 1, 1) if m == 12 else (a, m + 1)
    if not saida:
        raise ValueError(f"intervalo vazio: {desde} a {ate}")
    return saida


def fim_do_mes(mes: str) -> date:
    a, m = map(int, mes.split("-"))
    proximo = date(a + 1, 1, 1) if m == 12 else date(a, m + 1, 1)
    return proximo - timedelta(days=1)


@dataclass(frozen=True)
class Periodo:
    """Um período de declaração ao Tesouro: bimestre (RREO), quadrimestre (RGF) ou ano (DCA)."""

    demonstrativo: str
    exercicio: int
    numero: int

    @property
    def tamanho(self) -> int:
        return {"RREO": 2, "RGF": 4, "DCA": 12}[self.demonstrativo]

    @property
    def meses(self) -> list[str]:
        inicio = (self.numero - 1) * self.tamanho + 1
        return [f"{self.exercicio:04d}-{m:02d}" for m in range(inicio, inicio + self.tamanho)]

    @property
    def termina(self) -> date:
        return fim_do_mes(self.meses[-1])

    @property
    def prazo(self) -> date:
        """30 dias após o fim do período (LRF, arts. 52 e 55); a DCA vence em 30 de abril."""
        if self.demonstrativo == "DCA":
            return date(self.exercicio + 1, 4, 30)
        return self.termina + timedelta(days=30)

    @property
    def rotulo(self) -> str:
        if self.demonstrativo == "DCA":
            return f"DCA {self.exercicio}"
        sufixo = {"RREO": "º bimestre", "RGF": "º quadrimestre"}[self.demonstrativo]
        return f"{self.demonstrativo} {self.exercicio}, {self.numero}{sufixo}"


def periodos_do_intervalo(lista_meses: list[str], hoje: date) -> list[Periodo]:
    """Períodos que tocam o intervalo e já terminaram (o que ainda corre não se cobra)."""
    dentro = set(lista_meses)
    anos = sorted({int(m[:4]) for m in lista_meses})
    saida = []
    for dem, quantos in (("RREO", 6), ("RGF", 3), ("DCA", 1)):
        for ano in anos:
            for n in range(1, quantos + 1):
                p = Periodo(dem, ano, n)
                if dentro.intersection(p.meses) and p.termina < hoje:
                    saida.append(p)
    return saida


# --- Banco --------------------------------------------------------------------------

ESQUEMA = """
CREATE TABLE coletas (motor TEXT, alvo TEXT, mes TEXT, url TEXT, ok INTEGER, http INTEGER,
    erro TEXT, tentativas INTEGER, segundos REAL, bytes INTEGER, sha256 TEXT, quando TEXT);
CREATE TABLE siconfi_periodos (demonstrativo TEXT, exercicio INTEGER, periodo INTEGER,
    rotulo TEXT, termina TEXT, prazo TEXT, situacao TEXT, itens INTEGER, anexos INTEGER, erro TEXT);
CREATE TABLE siconfi_anexos (demonstrativo TEXT, exercicio INTEGER, periodo INTEGER,
    anexo TEXT, itens INTEGER, guardado INTEGER);
CREATE TABLE siconfi_itens (demonstrativo TEXT, exercicio INTEGER, periodo INTEGER, anexo TEXT,
    rotulo TEXT, coluna TEXT, cod_conta TEXT, conta TEXT, valor REAL);
CREATE TABLE siconfi_entregas (exercicio INTEGER, entregavel TEXT, periodo INTEGER,
    periodicidade TEXT, status TEXT, data_status TEXT, forma_envio TEXT, tipo TEXT);
CREATE TABLE diario_oficial (fonte TEXT, mes TEXT, data TEXT, edicao TEXT, extra INTEGER,
    url TEXT, com_termos INTEGER);
CREATE TABLE diario_oficial_mes (fonte TEXT, mes TEXT, edicoes INTEGER, com_termos INTEGER,
    erro TEXT);
CREATE TABLE repasses_fnas (competencia TEXT, tipo TEXT, bloco TEXT, programa TEXT, valor REAL,
    ordem_bancaria TEXT, planilha INTEGER);
CREATE TABLE contratacoes_pncp (pncp_id TEXT PRIMARY KEY, mes TEXT, modalidade TEXT,
    orgao_cnpj TEXT, orgao TEXT, esfera TEXT, unidade TEXT, objeto TEXT, valor_estimado REAL,
    valor_homologado REAL, situacao TEXT);
CREATE TABLE contratos_pncp (pncp_id TEXT PRIMARY KEY, mes TEXT, data_assinatura TEXT,
    orgao_cnpj TEXT, orgao TEXT, unidade TEXT, fornecedor_ni TEXT, fornecedor TEXT, objeto TEXT,
    valor_global REAL, da_pasta INTEGER);
CREATE TABLE fontes (grupo TEXT, nome TEXT, url TEXT, ok INTEGER, http INTEGER, erro TEXT,
    esperado TEXT);
CREATE TABLE normas (caminho TEXT, ok INTEGER, revogada INTEGER, erro TEXT);
CREATE TABLE meta (chave TEXT PRIMARY KEY, valor TEXT);
"""


class Banco:
    def __init__(self, caminho: Path | str):
        self.caminho = Path(caminho) if str(caminho) != ":memory:" else caminho
        if isinstance(self.caminho, Path):
            self.caminho.parent.mkdir(parents=True, exist_ok=True)
            if self.caminho.exists():
                self.caminho.unlink()          # cada rodada refaz o banco do zero
        self.con = sqlite3.connect(str(caminho))
        self.con.executescript(ESQUEMA)

    @classmethod
    def abrir(cls, caminho: Path | str = BANCO) -> "Banco":
        """Abre um banco já coletado, sem apagar nada."""
        banco = cls.__new__(cls)
        banco.caminho = caminho
        banco.con = sqlite3.connect(str(caminho))
        return banco

    def inserir(self, tabela: str, linha: dict) -> None:
        colunas = ", ".join(linha)
        marcas = ", ".join("?" for _ in linha)
        self.con.execute(f"INSERT OR REPLACE INTO {tabela} ({colunas}) VALUES ({marcas})",
                         list(linha.values()))

    def consultar(self, sql: str, *args) -> list[tuple]:
        return self.con.execute(sql, args).fetchall()

    def fechar(self) -> None:
        self.con.commit()
        self.con.execute("VACUUM")
        self.con.close()


# --- Leitura com paciência ------------------------------------------------------------

@dataclass
class Contexto:
    banco: Banco
    meses: list[str]
    hoje: date
    ler_url: Callable[..., base.Leitura] = base.ler
    dormir: Callable[[float], None] = time.sleep
    pausa: float = 1.0                     # entre chamadas à mesma API
    brutos: Path | None = None             # se dado, guarda cada resposta crua aqui
    limites: dict[str, int] = field(default_factory=lambda: {"pncp": 1500, "qd": 400})
    gastos: dict[str, int] = field(default_factory=dict)

    def ler(self, motor: str, alvo: str, url: str, *, mes: str = "", tentativas: int = 4,
            cabecalhos: dict | None = None, tempo: int = 90) -> base.Leitura:
        """Lê com espera crescente em 429 e 5xx, e registra a chamada no banco."""
        limite = self.limites.get(motor)
        if limite is not None and self.gastos.get(motor, 0) >= limite:
            leitura = base.Leitura(False, url, erro="limite de chamadas da rodada atingido")
            self._registrar(motor, alvo, mes, leitura, 0, 0.0)
            return leitura
        inicio = time.monotonic()
        leitura = base.Leitura(False, url, erro="não tentado")
        feitas = 0
        for n in range(tentativas):
            feitas = n + 1
            self.gastos[motor] = self.gastos.get(motor, 0) + 1
            leitura = self.ler_url(url, tempo=tempo, cabecalhos=cabecalhos)
            codigo = leitura.http
            if leitura.ok or not (codigo == 429 or (codigo and codigo >= 500)
                                  or leitura.erro.startswith(("TimeoutError", "URLError"))):
                break
            self.dormir(min(5 * 2 ** n, 60))
        self._registrar(motor, alvo, mes, leitura, feitas, time.monotonic() - inicio)
        if self.pausa:
            self.dormir(self.pausa)
        if leitura.ok and self.brutos is not None:
            nome = re.sub(r"[^A-Za-z0-9._-]+", "_", f"{motor}_{alvo}_{mes}")[:150]
            self.brutos.mkdir(parents=True, exist_ok=True)
            (self.brutos / nome).write_bytes(leitura.conteudo)
        return leitura

    def _registrar(self, motor, alvo, mes, leitura, tentativas, segundos):
        self.banco.inserir("coletas", {
            "motor": motor, "alvo": alvo, "mes": mes, "url": leitura.url, "ok": int(leitura.ok),
            "http": leitura.http, "erro": leitura.erro or None, "tentativas": tentativas,
            "segundos": round(segundos, 2), "bytes": len(leitura.conteudo),
            "sha256": leitura.original.sha256 if leitura.original else None,
            "quando": datetime.now(timezone.utc).isoformat(timespec="seconds")})


def _json(leitura: base.Leitura):
    try:
        return json.loads(leitura.texto)
    except (json.JSONDecodeError, ValueError):
        return None


def _norm(t) -> str:
    t = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode()
    return " ".join(t.upper().split())


# --- Motor 1: SICONFI (Tesouro Nacional) ------------------------------------------------

def _anexo_guardado(demonstrativo: str, anexo: str) -> bool:
    nome = _norm(anexo).lower().split("-", 1)[-1].strip()
    padrao = ANEXOS_GUARDADOS.get(demonstrativo)
    return bool(padrao and padrao.search(nome))


def _siconfi_url(recurso: str, **params) -> str:
    return SICONFI + recurso + "?" + urlencode(params)


def _siconfi_paginas(ctx: Contexto, recurso: str, alvo: str, mes: str, **params):
    """Todos os itens de uma consulta do SICONFI, seguindo a paginação (``hasMore``)."""
    itens, offset, erro = [], 0, None
    for _ in range(60):
        leitura = ctx.ler("siconfi", alvo, _siconfi_url(recurso, offset=offset, **params), mes=mes)
        dados = _json(leitura) if leitura.ok else None
        if dados is None:
            erro = leitura.erro or "resposta não é JSON"
            break
        pagina = dados.get("items") or []
        itens += pagina
        if not dados.get("hasMore") or not pagina:
            break
        offset += len(pagina)
    return itens, erro


def motor_siconfi(ctx: Contexto, ente: int) -> None:
    anos = sorted({int(m[:4]) for m in ctx.meses})
    for ano in anos:
        itens, erro = _siconfi_paginas(ctx, "extrato_entregas", f"extrato {ano}", f"{ano}-12",
                                       id_ente=ente, an_referencia=ano)
        for it in itens:
            ctx.banco.inserir("siconfi_entregas", {
                "exercicio": it.get("exercicio", ano), "entregavel": it.get("entregavel"),
                "periodo": it.get("periodo"), "periodicidade": it.get("periodicidade"),
                "status": it.get("status_relatorio"), "data_status": it.get("data_status"),
                "forma_envio": it.get("forma_envio"), "tipo": it.get("tipo_relatorio")})
    for p in periodos_do_intervalo(ctx.meses, ctx.hoje):
        params = {"an_exercicio": p.exercicio, "id_ente": ente}
        if p.demonstrativo == "RREO":
            params.update(nr_periodo=p.numero, co_tipo_demonstrativo="RREO")
            recurso = "rreo"
        elif p.demonstrativo == "RGF":
            params.update(nr_periodo=p.numero, in_periodicidade="Q", co_tipo_demonstrativo="RGF",
                          co_poder="E")
            recurso = "rgf"
        else:
            recurso = "dca"
        itens, erro = _siconfi_paginas(ctx, recurso, p.rotulo, p.meses[-1], **params)
        anexos: dict[str, int] = {}
        for it in itens:
            anexo = str(it.get("anexo") or "")
            anexos[anexo] = anexos.get(anexo, 0) + 1
            if _anexo_guardado(p.demonstrativo, anexo):
                try:
                    valor = float(it.get("valor"))
                except (TypeError, ValueError):
                    valor = None
                ctx.banco.inserir("siconfi_itens", {
                    "demonstrativo": p.demonstrativo, "exercicio": p.exercicio,
                    "periodo": p.numero, "anexo": anexo, "rotulo": it.get("rotulo"),
                    "coluna": it.get("coluna"), "cod_conta": it.get("cod_conta"),
                    "conta": it.get("conta"), "valor": valor})
        for anexo, n in anexos.items():
            ctx.banco.inserir("siconfi_anexos", {
                "demonstrativo": p.demonstrativo, "exercicio": p.exercicio, "periodo": p.numero,
                "anexo": anexo, "itens": n, "guardado": int(_anexo_guardado(p.demonstrativo, anexo))})
        if erro and not itens:
            situacao = "falha"
        elif itens:
            situacao = "entregue"
        else:
            situacao = "no prazo" if ctx.hoje <= p.prazo else "ausente"
        ctx.banco.inserir("siconfi_periodos", {
            "demonstrativo": p.demonstrativo, "exercicio": p.exercicio, "periodo": p.numero,
            "rotulo": p.rotulo, "termina": p.termina.isoformat(), "prazo": p.prazo.isoformat(),
            "situacao": situacao, "itens": len(itens), "anexos": len(anexos), "erro": erro})
    # as bases que o coletor antigo (cadeoqueijo/coleta_siconfi.py) ainda usa
    for antiga in SICONFI_ANTIGAS:
        url = antiga + "extrato_entregas?" + urlencode({"id_ente": ente, "an_referencia": anos[-1]})
        ctx.ler("siconfi-antiga", antiga.split("/")[2], url, tentativas=1)


# --- Motor 2: Diário Oficial (Querido Diário e índice do SILEG) -------------------------

def motor_querido_diario(ctx: Contexto, ibge: int) -> None:
    for mes in ctx.meses:
        inicio, fim = f"{mes}-01", fim_do_mes(mes).isoformat()
        edicoes: dict[tuple, dict] = {}
        erro = None
        for com_termos in (False, True):
            offset = 0
            while True:
                params = {"territory_ids": ibge, "published_since": inicio,
                          "published_until": fim, "size": 100, "offset": offset}
                if com_termos:
                    params["querystring"] = " | ".join(f'"{t}"' for t in TERMOS)
                leitura = ctx.ler("qd", f"{'termos' if com_termos else 'edicoes'}",
                                  QUERIDO_DIARIO + "?" + urlencode(params), mes=mes)
                dados = _json(leitura) if leitura.ok else None
                if dados is None:
                    erro = leitura.erro or "resposta não é JSON"
                    break
                pagina = dados.get("gazettes") or []
                for g in pagina:
                    chave = (g.get("date"), str(g.get("edition") or ""), bool(g.get("is_extra_edition")))
                    item = edicoes.setdefault(chave, {"url": g.get("url"), "com_termos": 0})
                    if com_termos:
                        item["com_termos"] = 1
                offset += len(pagina)
                if not pagina or offset >= int(dados.get("total_gazettes") or 0):
                    break
        for (dia, edicao, extra), item in sorted(edicoes.items()):
            ctx.banco.inserir("diario_oficial", {
                "fonte": "querido_diario", "mes": mes, "data": dia, "edicao": edicao,
                "extra": int(extra), "url": item["url"], "com_termos": item["com_termos"]})
        ctx.banco.inserir("diario_oficial_mes", {
            "fonte": "querido_diario", "mes": mes, "edicoes": len(edicoes),
            "com_termos": sum(i["com_termos"] for i in edicoes.values()), "erro": erro})


def motor_sileg(ctx: Contexto) -> None:
    clausula = " OR ".join(f'attr_content:"{t}"' for t in TERMOS)
    for mes in ctx.meses:
        prefixo = mes.replace("-", "")
        contagem, erro = {}, None
        for chave, q in (("edicoes", f"id:*do_{prefixo}*"),
                         ("com_termos", f"id:*do_{prefixo}* AND ({clausula})")):
            url = SILEG_SOLR + "?" + urlencode({"q": q, "rows": 0, "wt": "json"})
            leitura = ctx.ler("sileg", chave, url, mes=mes, tentativas=2)
            dados = _json(leitura) if leitura.ok else None
            if dados is None:
                erro = leitura.erro or "resposta não é JSON"
                break
            contagem[chave] = int(dados.get("response", {}).get("numFound", 0))
        ctx.banco.inserir("diario_oficial_mes", {
            "fonte": "sileg", "mes": mes, "edicoes": contagem.get("edicoes"),
            "com_termos": contagem.get("com_termos"), "erro": erro})


# --- Motor 3: repasses federais (FNAS) -------------------------------------------------

def planilhas_fnas(pagina_html: str) -> dict[int, str]:
    """Endereços das planilhas ``REPASSES_ANO_AAAA.xlsx`` na página do FNAS."""
    achadas = {}
    for m in re.finditer(r'(https?://[^"\'\s<>]+REPASSES_ANO_(\d{4})\.xlsx)', pagina_html):
        achadas[int(m.group(2))] = m.group(1)
    return achadas


def linhas_fnas(conteudo: bytes, ibge6: str) -> list[dict]:
    """Linhas do município (esfera municipal) numa planilha de repasses do FNAS."""
    import io

    import openpyxl
    livro = openpyxl.load_workbook(io.BytesIO(conteudo), read_only=True)
    folha = livro[livro.sheetnames[0]]
    saida = []
    for i, r in enumerate(folha.iter_rows(values_only=True)):
        if i == 0 or not r or str(r[0]) != ibge6 or str(r[2]).upper() != "MUNICIPAL":
            continue
        try:
            valor = float(r[9])
        except (TypeError, ValueError):
            continue
        saida.append({"competencia": f"{r[7]}-{str(r[8]).zfill(2)}", "tipo": r[4], "bloco": r[5],
                      "programa": r[6], "valor": valor, "ordem_bancaria": str(r[11])})
    livro.close()
    return saida


def motor_fnas(ctx: Contexto, ibge: int) -> None:
    pagina = ctx.ler("fnas", "pagina", FNAS_PAGINA, cabecalhos=NAVEGADOR)
    achadas = planilhas_fnas(pagina.texto) if pagina.ok else {}
    anos_do_intervalo = sorted({int(m[:4]) for m in ctx.meses})
    # a planilha de um ano pode trazer competências do ano anterior: lê-se a partir do primeiro
    desejadas = {a: achadas.get(a) or FNAS_CONHECIDAS.get(a) for a in anos_do_intervalo}
    dentro = set(ctx.meses)
    for ano, url in desejadas.items():
        if not url:
            erro = ("planilha do ano não publicada na página do FNAS" if pagina.ok else
                    "a página do FNAS não abriu; não se sabe se a planilha do ano saiu")
            ctx.banco.inserir("coletas", {
                "motor": "fnas", "alvo": f"planilha {ano}", "mes": f"{ano}-12", "url": FNAS_PAGINA,
                "ok": 0, "http": None, "erro": erro,
                "tentativas": 0, "segundos": 0, "bytes": 0, "sha256": None,
                "quando": datetime.now(timezone.utc).isoformat(timespec="seconds")})
            continue
        leitura = ctx.ler("fnas", f"planilha {ano}", url, mes=f"{ano}-12", cabecalhos=NAVEGADOR,
                          tempo=300)
        if not leitura.ok:
            continue
        try:
            linhas = linhas_fnas(leitura.conteudo, str(ibge)[:6])
        except Exception as e:  # planilha com formato novo: falha às claras
            ctx.banco.inserir("coletas", {
                "motor": "fnas", "alvo": f"leitura {ano}", "mes": f"{ano}-12", "url": url, "ok": 0,
                "http": None, "erro": f"{type(e).__name__}: {e}"[:200], "tentativas": 1,
                "segundos": 0, "bytes": 0, "sha256": None,
                "quando": datetime.now(timezone.utc).isoformat(timespec="seconds")})
            continue
        for linha in linhas:
            if linha["competencia"] in dentro:
                ctx.banco.inserir("repasses_fnas", {**linha, "planilha": ano})


# --- Motor 4: contratações (PNCP) ------------------------------------------------------

def _e_municipal(orgao: dict, municipio: str) -> bool:
    nome = _norm(orgao.get("razaoSocial"))
    esfera = str(orgao.get("esferaId") or "").upper()
    return esfera == "M" or ("MUNICIPIO DE " + _norm(municipio)) in nome or \
        ("MUNICIPAL" in nome and _norm(municipio) in nome)


def motor_pncp(ctx: Contexto, ibge: int, municipio: str, cnpjs_conhecidos: tuple = ()) -> None:
    orgaos: dict[str, str] = {c: "" for c in cnpjs_conhecidos}
    for mes in ctx.meses:
        d1, d2 = f"{mes.replace('-', '')}01", fim_do_mes(mes).strftime("%Y%m%d")
        for modalidade in MODALIDADES_DESCOBERTA:
            for pagina in range(1, 21):
                params = {"dataInicial": d1, "dataFinal": d2, "codigoModalidadeContratacao": modalidade,
                          "codigoMunicipioIbge": ibge, "pagina": pagina, "tamanhoPagina": 50}
                leitura = ctx.ler("pncp", f"contratacoes m{modalidade}",
                                  PNCP + "contratacoes/publicacao?" + urlencode(params), mes=mes)
                if leitura.http == 204:
                    break
                dados = _json(leitura) if leitura.ok else None
                if not dados:
                    break
                for c in dados.get("data") or []:
                    org = c.get("orgaoEntidade") or {}
                    if not _e_municipal(org, municipio):
                        continue
                    cnpj = str(org.get("cnpj") or "")
                    orgaos.setdefault(cnpj, org.get("razaoSocial") or "")
                    ctx.banco.inserir("contratacoes_pncp", {
                        "pncp_id": c.get("numeroControlePNCP"), "mes": mes,
                        "modalidade": c.get("modalidadeNome"), "orgao_cnpj": cnpj,
                        "orgao": org.get("razaoSocial"), "esfera": org.get("esferaId"),
                        "unidade": (c.get("unidadeOrgao") or {}).get("nomeUnidade"),
                        "objeto": (c.get("objetoCompra") or "")[:500],
                        "valor_estimado": c.get("valorTotalEstimado"),
                        "valor_homologado": c.get("valorTotalHomologado"),
                        "situacao": c.get("situacaoCompraNome")})
                if pagina >= int(dados.get("totalPaginas") or 1):
                    break
    for cnpj in sorted(orgaos):
        for mes in ctx.meses:
            d1, d2 = f"{mes.replace('-', '')}01", fim_do_mes(mes).strftime("%Y%m%d")
            for pagina in range(1, 21):
                params = {"dataInicial": d1, "dataFinal": d2, "cnpjOrgao": cnpj, "pagina": pagina,
                          "tamanhoPagina": 100}
                leitura = ctx.ler("pncp", f"contratos {cnpj}",
                                  PNCP + "contratos?" + urlencode(params), mes=mes)
                if leitura.http == 204:
                    break
                dados = _json(leitura) if leitura.ok else None
                if not dados:
                    break
                for c in dados.get("data") or []:
                    org = c.get("orgaoEntidade") or {}
                    tudo = _norm(json.dumps(c, ensure_ascii=False))
                    ctx.banco.inserir("contratos_pncp", {
                        "pncp_id": c.get("numeroControlePNCP"), "mes": mes,
                        "data_assinatura": c.get("dataAssinatura"), "orgao_cnpj": cnpj,
                        "orgao": org.get("razaoSocial") or orgaos.get(cnpj),
                        "unidade": (c.get("unidadeOrgao") or {}).get("nomeUnidade"),
                        "fornecedor_ni": c.get("niFornecedor"),
                        "fornecedor": c.get("nomeRazaoSocialFornecedor"),
                        "objeto": (c.get("objetoContrato") or "")[:500],
                        "valor_global": c.get("valorGlobal"),
                        "da_pasta": int(any(t in tudo for t in TERMOS_PASTA))})
                if pagina >= int(dados.get("totalPaginas") or 1):
                    break
    ctx.banco.inserir("meta", {"chave": "pncp_orgaos",
                               "valor": json.dumps(orgaos, ensure_ascii=False)})


# --- Motor 5: portais e endereços do sistema ------------------------------------------

def enderecos_configurados(raiz: Path = RAIZ) -> list[tuple[str, str, str, str]]:
    """(grupo, nome, url, esperado) de cada endereço nos arquivos de fontes do sistema."""
    import yaml
    saida, vistos = [], set()

    def andar(no, grupo, nome, esperado=""):
        if isinstance(no, dict):
            esperado = str(no.get("status") or esperado)
            for k, v in no.items():
                if k in ("url", "base", "portal_consulta", "pagina_institucional") and isinstance(v, str):
                    if v.startswith("http") and "{" not in v and "AAAA" not in v and v not in vistos:
                        vistos.add(v)
                        saida.append((grupo, str(no.get("nome") or nome), v, esperado))
                else:
                    andar(v, grupo, k if isinstance(k, str) else nome, esperado)
        elif isinstance(no, list):
            for item in no:
                andar(item, grupo, nome, "MORTO" if nome == "mortos" else esperado)

    for arquivo in ("config/portais.yml", "config/fontes.yml"):
        caminho = raiz / arquivo
        if caminho.exists():
            andar(yaml.safe_load(caminho.read_text(encoding="utf-8")), arquivo, "")
    return saida


def motor_fontes(ctx: Contexto) -> None:
    for grupo, nome, url, esperado in enderecos_configurados():
        leitura = ctx.ler("fontes", nome[:80], url, tentativas=2, tempo=45, cabecalhos=NAVEGADOR)
        ctx.banco.inserir("fontes", {"grupo": grupo, "nome": nome, "url": url, "ok": int(leitura.ok),
                                     "http": leitura.http, "erro": leitura.erro or None,
                                     "esperado": esperado})


def motor_normas(ctx: Contexto) -> None:
    from .coletores.leis import conferir_ctresb

    def ler(url, **kw):
        return ctx.ler("ctresb", url.rsplit("/", 1)[-1], url, tentativas=2)
    for r in conferir_ctresb(ler_url=ler):
        ctx.banco.inserir("normas", {"caminho": r["caminho"], "ok": int(r["ok"]),
                                     "revogada": int(bool(r.get("revogada"))),
                                     "erro": r.get("erro")})


MOTORES = ("siconfi", "querido_diario", "sileg", "fnas", "pncp", "fontes", "normas")


def rodar(desde: str, ate: str, *, motores=MOTORES, caminho=BANCO, hoje: date | None = None,
          brutos: Path | None = None, **kw) -> Banco:
    from .config import carregar_alvo
    alvo = carregar_alvo()
    banco = Banco(caminho)
    ctx = Contexto(banco, meses(desde, ate), hoje or date.today(), brutos=brutos, **kw)
    banco.inserir("meta", {"chave": "intervalo", "valor": f"{desde} a {ate}"})
    banco.inserir("meta", {"chave": "rodada", "valor": datetime.now(timezone.utc).isoformat(
        timespec="seconds")})
    banco.inserir("meta", {"chave": "hoje", "valor": ctx.hoje.isoformat()})
    chamadas = {
        "siconfi": lambda: motor_siconfi(ctx, alvo.siconfi_id_ente),
        "querido_diario": lambda: motor_querido_diario(ctx, alvo.ibge),
        "sileg": lambda: motor_sileg(ctx),
        "fnas": lambda: motor_fnas(ctx, alvo.ibge),
        "pncp": lambda: motor_pncp(ctx, alvo.ibge, alvo.municipio, alvo.pncp_cnpjs),
        "fontes": lambda: motor_fontes(ctx),
        "normas": lambda: motor_normas(ctx),
    }
    for nome in motores:
        inicio = time.monotonic()
        try:
            chamadas[nome]()
            erro = None
        except Exception as e:  # um motor quebrado não derruba os outros: vira achado
            erro = f"{type(e).__name__}: {e}"[:300]
        banco.inserir("meta", {"chave": f"motor:{nome}", "valor": json.dumps(
            {"segundos": round(time.monotonic() - inicio, 1), "erro": erro}, ensure_ascii=False)})
        banco.con.commit()
        print(f"motor {nome}: {'ok' if not erro else 'QUEBROU: ' + erro}", flush=True)
    return banco
