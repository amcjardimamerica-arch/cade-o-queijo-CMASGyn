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
TESOURO_PACOTE = ("https://www.tesourotransparente.gov.br/ckan/api/3/action/package_show"
                  "?id=transferencias-constitucionais-para-municipios")
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
CREATE TABLE IF NOT EXISTS coletas (motor TEXT, alvo TEXT, mes TEXT, url TEXT, ok INTEGER, http INTEGER,
    erro TEXT, tentativas INTEGER, segundos REAL, bytes INTEGER, sha256 TEXT, quando TEXT);
CREATE TABLE IF NOT EXISTS siconfi_periodos (demonstrativo TEXT, exercicio INTEGER, periodo INTEGER,
    rotulo TEXT, termina TEXT, prazo TEXT, situacao TEXT, itens INTEGER, anexos INTEGER, erro TEXT);
CREATE TABLE IF NOT EXISTS siconfi_anexos (demonstrativo TEXT, exercicio INTEGER, periodo INTEGER,
    anexo TEXT, itens INTEGER, guardado INTEGER);
CREATE TABLE IF NOT EXISTS siconfi_itens (demonstrativo TEXT, exercicio INTEGER, periodo INTEGER, anexo TEXT,
    rotulo TEXT, coluna TEXT, cod_conta TEXT, conta TEXT, valor REAL);
CREATE TABLE IF NOT EXISTS siconfi_entregas (exercicio INTEGER, entregavel TEXT, periodo INTEGER,
    periodicidade TEXT, status TEXT, data_status TEXT, forma_envio TEXT, tipo TEXT);
CREATE TABLE IF NOT EXISTS diario_oficial (fonte TEXT, mes TEXT, data TEXT, edicao TEXT, extra INTEGER,
    url TEXT, com_termos INTEGER);
CREATE TABLE IF NOT EXISTS diario_oficial_mes (fonte TEXT, mes TEXT, edicoes INTEGER, com_termos INTEGER,
    erro TEXT);
CREATE TABLE IF NOT EXISTS repasses_fnas (competencia TEXT, tipo TEXT, bloco TEXT, programa TEXT, valor REAL,
    ordem_bancaria TEXT, planilha INTEGER, origem TEXT);
CREATE TABLE IF NOT EXISTS contratacoes_pncp (pncp_id TEXT PRIMARY KEY, mes TEXT, modalidade TEXT,
    orgao_cnpj TEXT, orgao TEXT, esfera TEXT, unidade TEXT, objeto TEXT, valor_estimado REAL,
    valor_homologado REAL, situacao TEXT);
CREATE TABLE IF NOT EXISTS contratos_pncp (pncp_id TEXT PRIMARY KEY, mes TEXT, data_assinatura TEXT,
    orgao_cnpj TEXT, orgao TEXT, unidade TEXT, fornecedor_ni TEXT, fornecedor TEXT, objeto TEXT,
    valor_global REAL, da_pasta INTEGER);
CREATE TABLE IF NOT EXISTS fontes (grupo TEXT, nome TEXT, url TEXT, ok INTEGER, http INTEGER, erro TEXT,
    esperado TEXT);
CREATE TABLE IF NOT EXISTS normas (caminho TEXT, ok INTEGER, revogada INTEGER, erro TEXT);
CREATE TABLE IF NOT EXISTS transferencias_tesouro (mes TEXT, item TEXT, destino TEXT, decendio1 REAL,
    decendio2 REAL, decendio3 REAL, total REAL);
CREATE TABLE IF NOT EXISTS meta (chave TEXT PRIMARY KEY, valor TEXT);
"""


# O que cada motor grava, para refazer um motor sem perder os outros.
TABELAS_DO_MOTOR = {
    "siconfi": [("coletas", "motor IN ('siconfi', 'siconfi-antiga')"), ("siconfi_periodos", ""),
                ("siconfi_anexos", ""), ("siconfi_itens", ""), ("siconfi_entregas", "")],
    "querido_diario": [("coletas", "motor = 'qd'"), ("diario_oficial", "fonte = 'querido_diario'"),
                       ("diario_oficial_mes", "fonte = 'querido_diario'")],
    "sileg": [("coletas", "motor = 'sileg'"), ("diario_oficial_mes", "fonte = 'sileg'")],
    "fnas": [("coletas", "motor = 'fnas'"), ("repasses_fnas", ""), ("meta", "chave = 'fnas_do_arquivo'")],
    "pncp": [("coletas", "motor = 'pncp'"), ("contratacoes_pncp", ""), ("contratos_pncp", ""),
             ("meta", "chave IN ('pncp_orgaos', 'pncp_janelas', 'pncp_procura')")],
    "fontes": [("coletas", "motor = 'fontes'"), ("fontes", "")],
    "tesouro": [("coletas", "motor = 'tesouro'"), ("transferencias_tesouro", ""),
                ("meta", "chave = 'tesouro_meses'")],
    "normas": [("coletas", "motor = 'ctresb'"), ("normas", "")],
}


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
        banco.con.executescript(ESQUEMA)
        banco._atualizar_colunas()
        return banco

    def _atualizar_colunas(self) -> None:
        """Bancos de rodadas antigas ganham as colunas novas sem perder o que já têm."""
        novas = {"repasses_fnas": {"origem": "TEXT"}}
        for tabela, colunas in novas.items():
            existentes = {c[1] for c in self.con.execute(f"PRAGMA table_info({tabela})")}
            for coluna, tipo in colunas.items():
                if coluna not in existentes:
                    self.con.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {tipo}")

    def apagar_motor(self, motor: str) -> None:
        """Tira do banco tudo o que um motor gravou, para ele coletar de novo."""
        for tabela, filtro in TABELAS_DO_MOTOR[motor]:
            self.con.execute(f"DELETE FROM {tabela}" + (f" WHERE {filtro}" if filtro else ""))
        self.con.execute("DELETE FROM meta WHERE chave = ?", (f"motor:{motor}",))

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
    limites: dict[str, int] = field(default_factory=lambda: {"pncp": 2500, "qd": 400})
    gastos: dict[str, int] = field(default_factory=dict)
    # Disjuntor: depois de tantas falhas de rede seguidas, o motor deixa de chamar a fonte
    # e registra o resto como não tentado. Uma fonte fora do ar não pode prender a rodada.
    disjuntor: int = 6
    seguidas: dict[str, int] = field(default_factory=dict)
    fim_do_motor: float | None = None      # relógio monotônico; depois disso, nada é chamado

    def ler(self, motor: str, alvo: str, url: str, *, mes: str = "", tentativas: int = 3,
            cabecalhos: dict | None = None, tempo: int = 60,
            disjuntor: bool = True, formulario: dict | None = None) -> base.Leitura:
        """Lê com espera crescente em 429 e 5xx, e registra a chamada no banco."""
        limite = self.limites.get(motor)
        motivo = None
        if limite is not None and self.gastos.get(motor, 0) >= limite:
            motivo = "limite de chamadas da rodada atingido"
        elif disjuntor and self.seguidas.get(motor, 0) >= self.disjuntor:
            motivo = f"não tentado: {self.disjuntor} falhas de rede seguidas nesta fonte"
        elif self.fim_do_motor is not None and time.monotonic() > self.fim_do_motor:
            motivo = "não tentado: tempo do motor nesta rodada esgotado"
        if motivo:
            leitura = base.Leitura(False, url, erro=motivo)
            self._registrar(motor, alvo, mes, leitura, 0, 0.0)
            return leitura
        inicio = time.monotonic()
        leitura = base.Leitura(False, url, erro="não tentado")
        feitas = 0
        for n in range(tentativas):
            feitas = n + 1
            self.gastos[motor] = self.gastos.get(motor, 0) + 1
            extra = {"formulario": formulario} if formulario else {}
            leitura = self.ler_url(url, tempo=tempo, cabecalhos=cabecalhos, **extra)
            codigo = leitura.http
            if leitura.ok or not (codigo == 429 or (codigo and codigo >= 500)
                                  or leitura.erro.startswith(("TimeoutError", "URLError"))):
                break
            self.dormir(min(5 * 2 ** n, 60))
        rede = not leitura.ok and (leitura.http is None or leitura.http >= 500)
        self.seguidas[motor] = self.seguidas.get(motor, 0) + 1 if rede else 0
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


def _anotar(ctx: Contexto, motor: str, alvo: str, mes: str, url: str, erro: str) -> None:
    """Registra uma falha que não é de rede (formato, conteúdo errado) junto das chamadas."""
    ctx.banco.inserir("coletas", {
        "motor": motor, "alvo": alvo, "mes": mes, "url": url, "ok": 0, "http": None,
        "erro": erro[:300], "tentativas": 0, "segundos": 0, "bytes": 0, "sha256": None,
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
            leitura = ctx.ler("sileg", chave, url, mes=mes, tentativas=2, tempo=45)
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


PAGINA_MINIMA = 2000      # bytes: menos que isso é página de bloqueio, não a página do FNAS
REPASSES_DO_REPOSITORIO = RAIZ / "dados" / "repasses_federais.json"
ORIGEM_FNAS = "planilha do FNAS"
ORIGEM_ARQUIVO = "arquivo do repositório (dados/repasses_federais.json), coletado antes"


def _e_planilha(conteudo: bytes) -> bool:
    return conteudo[:2] == b"PK"          # todo .xlsx é um zip


def _repasses_do_repositorio(caminho: Path = REPASSES_DO_REPOSITORIO) -> dict[int, list[dict]]:
    """Repasses já guardados pelo coletor antigo, por ano da planilha de origem."""
    if not caminho.exists():
        return {}
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    por_ano: dict[int, list[dict]] = {}
    for r in dados.get("detalhe") or []:
        try:
            ano, valor = int(r["ano"]), float(r["valor"])
        except (KeyError, TypeError, ValueError):
            continue
        por_ano.setdefault(ano, []).append({
            "competencia": r.get("competencia"), "tipo": r.get("tipo"), "bloco": r.get("bloco"),
            "programa": r.get("programa"), "valor": valor,
            "ordem_bancaria": str(r.get("ordem_bancaria") or "")})
    return por_ano


def motor_fnas(ctx: Contexto, ibge: int) -> None:
    pagina = ctx.ler("fnas", "pagina", FNAS_PAGINA, cabecalhos=NAVEGADOR)
    pagina_ok = pagina.ok and len(pagina.conteudo) >= PAGINA_MINIMA
    if pagina.ok and not pagina_ok:
        _anotar(ctx, "fnas", "pagina (conteúdo)", "", FNAS_PAGINA,
                f"a fonte devolveu uma página de {len(pagina.conteudo)} bytes, não a página "
                "do FNAS (provável bloqueio do servidor a robôs)")
    achadas = planilhas_fnas(pagina.texto) if pagina_ok else {}
    anos_do_intervalo = sorted({int(m[:4]) for m in ctx.meses})
    # a planilha de um ano pode trazer competências do ano anterior: lê-se a partir do primeiro
    desejadas = {a: achadas.get(a) or FNAS_CONHECIDAS.get(a) for a in anos_do_intervalo}
    dentro = set(ctx.meses)
    sem_planilha = []
    for ano, url in desejadas.items():
        if not url:
            erro = ("planilha do ano não publicada na página do FNAS" if pagina_ok else
                    "a página do FNAS não abriu; não se sabe se a planilha do ano saiu")
            _anotar(ctx, "fnas", f"planilha {ano}", f"{ano}-12", FNAS_PAGINA, erro)
            sem_planilha.append(ano)
            continue
        leitura = None
        for cabecalhos in (NAVEGADOR, None):        # se o disfarce de navegador for barrado
            leitura = ctx.ler("fnas", f"planilha {ano}", url, mes=f"{ano}-12",
                              cabecalhos=cabecalhos, tempo=300)
            if leitura.ok and _e_planilha(leitura.conteudo):
                break
        if not leitura.ok:
            sem_planilha.append(ano)
            continue
        if not _e_planilha(leitura.conteudo):
            _anotar(ctx, "fnas", f"leitura {ano}", f"{ano}-12", url,
                    f"a fonte devolveu uma página de {len(leitura.conteudo)} bytes em vez da "
                    "planilha (provável bloqueio do servidor a robôs)")
            sem_planilha.append(ano)
            continue
        try:
            linhas = linhas_fnas(leitura.conteudo, str(ibge)[:6])
        except Exception as e:  # planilha com formato novo: falha às claras
            _anotar(ctx, "fnas", f"leitura {ano}", f"{ano}-12", url, f"{type(e).__name__}: {e}")
            sem_planilha.append(ano)
            continue
        for linha in linhas:
            if linha["competencia"] in dentro:
                ctx.banco.inserir("repasses_fnas", {**linha, "planilha": ano, "origem": ORIGEM_FNAS})
    # O que a fonte não deu agora vem do que o sistema já guardou, marcado como tal.
    if sem_planilha:
        guardados = _repasses_do_repositorio()
        usados = []
        for ano in sem_planilha:
            for linha in guardados.get(ano, []):
                if linha["competencia"] in dentro:
                    ctx.banco.inserir("repasses_fnas", {**linha, "planilha": ano,
                                                        "origem": ORIGEM_ARQUIVO})
            if guardados.get(ano):
                usados.append(ano)
        ctx.banco.inserir("meta", {"chave": "fnas_do_arquivo", "valor": json.dumps(usados)})


# --- Motor 4: contratações (PNCP) ------------------------------------------------------

def _e_municipal(orgao: dict, municipio: str) -> bool:
    nome = _norm(orgao.get("razaoSocial"))
    esfera = str(orgao.get("esferaId") or "").upper()
    return esfera == "M" or ("MUNICIPIO DE " + _norm(municipio)) in nome or \
        ("MUNICIPAL" in nome and _norm(municipio) in nome)


def _da_pasta(nome: str) -> bool:
    return any(t in _norm(nome) for t in TERMOS_PASTA)


def _janelas_anuais(lista_meses: list[str]) -> list[list[str]]:
    """Os meses do intervalo agrupados por ano civil (a API aceita até um ano por consulta)."""
    janelas: dict[str, list[str]] = {}
    for mes in lista_meses:
        janelas.setdefault(mes[:4], []).append(mes)
    return list(janelas.values())


def _pncp_contratos(ctx: Contexto, cnpj: str, nome: str, janela: list[str]) -> bool:
    """Lê os contratos de um órgão numa janela de meses; devolve se a janela foi lida inteira."""
    d1 = f"{janela[0].replace('-', '')}01"
    d2 = fim_do_mes(janela[-1]).strftime("%Y%m%d")
    rotulo = janela[0] if len(janela) == 1 else f"{janela[0]} a {janela[-1]}"
    for pagina in range(1, 51):
        params = {"dataInicial": d1, "dataFinal": d2, "cnpjOrgao": cnpj, "pagina": pagina,
                  "tamanhoPagina": 100}
        leitura = ctx.ler("pncp", f"contratos {cnpj} {rotulo}",
                          PNCP + "contratos?" + urlencode(params), mes=janela[0])
        if leitura.http == 204:
            return True                       # a API respondeu: nenhum contrato na janela
        dados = _json(leitura) if leitura.ok else None
        if not dados:
            return False
        for c in dados.get("data") or []:
            org = c.get("orgaoEntidade") or {}
            tudo = _norm(json.dumps(c, ensure_ascii=False))
            quando = str(c.get("dataPublicacaoPncp") or c.get("dataAssinatura") or "")[:7]
            ctx.banco.inserir("contratos_pncp", {
                "pncp_id": c.get("numeroControlePNCP"),
                "mes": quando if re.fullmatch(r"\d{4}-\d{2}", quando) else janela[0],
                "data_assinatura": c.get("dataAssinatura"), "orgao_cnpj": cnpj,
                "orgao": org.get("razaoSocial") or nome,
                "unidade": (c.get("unidadeOrgao") or {}).get("nomeUnidade"),
                "fornecedor_ni": c.get("niFornecedor"),
                "fornecedor": c.get("nomeRazaoSocialFornecedor"),
                "objeto": (c.get("objetoContrato") or "")[:500],
                "valor_global": c.get("valorGlobal"),
                "da_pasta": int(any(t in tudo for t in TERMOS_PASTA))})
        if pagina >= int(dados.get("totalPaginas") or 1):
            return True
    return False                              # mais de 50 páginas: a janela ficou incompleta


def _pncp_descobrir(ctx: Contexto, ibge: int, municipio: str, orgaos: dict[str, str],
                    feitos: list[str] | None = None) -> None:
    """Contratações publicadas com o código IBGE: guardadas, e os órgãos novos anotados.

    ``feitos`` recebe os meses procurados por inteiro; os que já estão nela são pulados.
    """
    feitos = feitos if feitos is not None else []
    for mes in ctx.meses:
        if mes in feitos:
            continue
        d1, d2 = f"{mes.replace('-', '')}01", fim_do_mes(mes).strftime("%Y%m%d")
        inteiro = True
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
                    inteiro = False
                    break
                for c in dados.get("data") or []:
                    org = c.get("orgaoEntidade") or {}
                    if not _e_municipal(org, municipio):
                        continue
                    cnpj = str(org.get("cnpj") or "")
                    if not orgaos.get(cnpj):
                        orgaos[cnpj] = org.get("razaoSocial") or ""
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
            else:
                inteiro = False               # mais de 20 páginas: o mês ficou incompleto
        if inteiro:
            feitos.append(mes)


def motor_pncp(ctx: Contexto, ibge: int, municipio: str, cnpjs_conhecidos=(),
               anterior: dict | None = None) -> None:
    """Contratos dos órgãos do Município e as contratações publicadas com o código IBGE.

    Com órgãos já conhecidos (do alvo ou da rodada anterior), os contratos vêm primeiro, os
    da pasta da assistência à frente, um ano por consulta; uma janela anual recusada é refeita
    mês a mês. A procura por órgãos novos usa o tempo que sobrar. Sem nenhum órgão conhecido,
    a procura vem antes, porque sem ela não há a quem perguntar pelos contratos.

    Com ``anterior`` (as janelas e a procura de uma rodada já guardada), continua de onde
    ela parou: o que já foi lido por inteiro não é pedido de novo, salvo o mês corrente,
    que ainda recebe contratos.
    """
    if isinstance(cnpjs_conhecidos, dict):
        orgaos = {str(c): n or "" for c, n in cnpjs_conhecidos.items()}
    else:
        orgaos = {str(c): "" for c in cnpjs_conhecidos}
    corrente = ctx.hoje.strftime("%Y-%m")
    janelas_lidas: list[dict] = []
    for j in (anterior or {}).get("janelas") or []:
        meses_ja = [m for m in j.get("meses") or [] if m != corrente and m in ctx.meses]
        if j.get("lida") and meses_ja:
            janelas_lidas.append({"cnpj": j["cnpj"], "meses": meses_ja, "lida": True})
    ja_lidos = {(j["cnpj"], m) for j in janelas_lidas for m in j["meses"]}
    procura = [m for m in (anterior or {}).get("procura") or [] if m != corrente]

    def guardar():
        ctx.banco.inserir("meta", {"chave": "pncp_orgaos",
                                   "valor": json.dumps(orgaos, ensure_ascii=False)})
        ctx.banco.inserir("meta", {"chave": "pncp_janelas",
                                   "valor": json.dumps(janelas_lidas, ensure_ascii=False)})
        ctx.banco.inserir("meta", {"chave": "pncp_procura", "valor": json.dumps(procura)})

    def contratos(lista: list[str]):
        for cnpj in sorted(lista, key=lambda c: (not _da_pasta(orgaos.get(c, "")), c)):
            for janela in _janelas_anuais(ctx.meses):
                faltam = [m for m in janela if (cnpj, m) not in ja_lidos]
                if not faltam:
                    continue
                if faltam != janela:          # parte do ano já lida: só os meses que faltam
                    for mes in faltam:
                        janelas_lidas.append({"cnpj": cnpj, "meses": [mes],
                                              "lida": _pncp_contratos(ctx, cnpj, "", [mes])})
                    continue
                if _pncp_contratos(ctx, cnpj, orgaos.get(cnpj, ""), janela):
                    janelas_lidas.append({"cnpj": cnpj, "meses": janela, "lida": True})
                    continue
                if len(janela) == 1:
                    janelas_lidas.append({"cnpj": cnpj, "meses": janela, "lida": False})
                    continue
                for mes in janela:            # a janela do ano falhou: tenta mês a mês
                    janelas_lidas.append({"cnpj": cnpj, "meses": [mes],
                                          "lida": _pncp_contratos(ctx, cnpj, "", [mes])})
            guardar()

    conhecidos = list(orgaos)
    if conhecidos:
        contratos(conhecidos)
        _pncp_descobrir(ctx, ibge, municipio, orgaos, procura)
        contratos([c for c in orgaos if c not in conhecidos])
    else:
        _pncp_descobrir(ctx, ibge, municipio, orgaos, procura)
        contratos(list(orgaos))
    guardar()


# --- Motor 5: portais e endereços do sistema ------------------------------------------

# --- Motor: transferências constitucionais do Tesouro (a segunda via do rio) -------------

def recursos_tesouro(pacote: dict) -> dict[str, str]:
    """Do pacote CKAN, o endereço da planilha mensal de cada mês (AAAA-MM)."""
    achados = {}
    for r in (pacote.get("result") or {}).get("resources") or []:
        m = re.search(r"Mensal_Municipios_(\d{4})(\d{2})", r.get("name") or "")
        if m and r.get("url"):
            achados[f"{m.group(1)}-{m.group(2)}"] = r["url"]
    return achados


def _numero_br(texto: str) -> float:
    t = (texto or "").strip()
    if not t:
        return 0.0
    if "," in t:                      # 1.234,56 ou 1234,56
        t = t.replace(".", "").replace(",", ".")
    return float(t)


def linhas_tesouro(conteudo: bytes, municipio: str, uf: str) -> list[dict]:
    """As linhas do município na planilha mensal (separada por ';', em latin-1)."""
    texto = conteudo.decode("latin-1")
    linhas = texto.splitlines()
    if not linhas or "Item transfer" not in linhas[0]:
        raise ValueError("planilha sem o cabeçalho esperado (Item transferência)")
    cab = [_norm(c) for c in linhas[0].split(";")]
    pos = {nome: cab.index(nome) for nome in ("MUNICIPIO", "UF", "ANO", "MES", "ITEM TRANSFERENCIA",
                                                "TRANSFERENCIA")}
    dec = [i for i, c in enumerate(cab) if c.endswith("DECENDIO")]
    alvo, saida = _norm(municipio), []
    for linha in linhas[1:]:
        c = linha.split(";")
        if len(c) < len(cab) - 1 or _norm(c[pos["MUNICIPIO"]]) != alvo or c[pos["UF"]].strip() != uf:
            continue
        valores = [_numero_br(c[i]) for i in dec]
        saida.append({"mes": f"{c[pos['ANO']].strip()}-{c[pos['MES']].strip().zfill(2)}",
                      "item": c[pos["ITEM TRANSFERENCIA"]].strip(),
                      "destino": c[pos["TRANSFERENCIA"]].strip(),
                      "decendio1": valores[0], "decendio2": valores[1], "decendio3": valores[2],
                      "total": round(sum(valores), 2)})
    return saida


def motor_tesouro(ctx: Contexto, municipio: str, uf: str) -> None:
    """Transferências constitucionais (FPM, ITR, ICMS desonerado, IPI-exp...) mês a mês, por
    decêndio, como o Tesouro publica: a via independente das receitas de transferência do RREO."""
    leitura = ctx.ler("tesouro", "pacote", TESOURO_PACOTE)
    pacote = _json(leitura) if leitura.ok else None
    if pacote is None:
        return
    enderecos = recursos_tesouro(pacote)
    lidos, nao_publicados = [], []
    for mes in ctx.meses:
        url = enderecos.get(mes)
        if not url:
            nao_publicados.append(mes)
            continue
        planilha = ctx.ler("tesouro", "planilha", url, mes=mes, tempo=120)
        if not planilha.ok:
            continue
        try:
            linhas = linhas_tesouro(planilha.conteudo, municipio, uf)
        except (ValueError, IndexError) as e:
            _anotar(ctx, "tesouro", "planilha", mes, url, f"formato: {e}")
            continue
        if not linhas:
            _anotar(ctx, "tesouro", "planilha", mes, url, f"{municipio} não está na planilha")
            continue
        for linha in linhas:
            ctx.banco.inserir("transferencias_tesouro", linha)
        lidos.append(mes)
    ctx.banco.inserir("meta", {"chave": "tesouro_meses", "valor": json.dumps(
        {"lidos": lidos, "nao_publicados": nao_publicados})})


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
        leitura = ctx.ler("fontes", nome[:80], url, tentativas=2, tempo=45, cabecalhos=NAVEGADOR,
                          disjuntor=False)              # cada endereço é de um site diferente
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


MOTORES = ("siconfi", "querido_diario", "sileg", "fnas", "pncp", "fontes", "normas", "tesouro")
# Minutos que cada motor pode usar numa rodada (o fluxo do GitHub para em 180).
TEMPO_DO_MOTOR = {"pncp": 75, "siconfi": 20}
TEMPO_PADRAO = 12


def rodar(desde: str, ate: str, *, motores=MOTORES, caminho=BANCO, hoje: date | None = None,
          brutos: Path | None = None, tempo_limitado: bool = True, somar: bool = False,
          **kw) -> Banco:
    """Liga os motores. Com ``somar``, refaz só esses motores num banco já existente do mesmo
    intervalo e mantém o que os outros coletaram."""
    from .config import carregar_alvo
    alvo = carregar_alvo()
    orgaos_pncp: dict[str, str] = {c: "" for c in alvo.pncp_cnpjs}
    pncp_anterior = None
    if somar and Path(caminho).exists():
        banco = Banco.abrir(caminho)
        meta_anterior = dict(banco.consultar("SELECT chave, valor FROM meta"))
        guardados = meta_anterior.get("pncp_orgaos")
        if guardados:                         # o que a rodada anterior descobriu não se perde
            for cnpj, nome in json.loads(guardados).items():
                orgaos_pncp[cnpj] = nome or orgaos_pncp.get(cnpj, "")
        anterior = dict(banco.consultar("SELECT chave, valor FROM meta")).get("intervalo")
        if anterior and anterior != f"{desde} a {ate}":
            banco.con.close()
            raise ValueError(f"o banco é de {anterior}; para somar, use o mesmo intervalo")
        if "pncp" in motores and meta_anterior.get("pncp_janelas"):
            # O PNCP é lento (cerca de 20 s por chamada): continua de onde parou, guardando o
            # que já leu e tirando só as chamadas que falharam, que serão refeitas.
            pncp_anterior = {"janelas": json.loads(meta_anterior["pncp_janelas"]),
                             "procura": json.loads(meta_anterior.get("pncp_procura") or "[]")}
        for nome in motores:
            if nome == "pncp" and pncp_anterior:
                banco.con.execute("DELETE FROM coletas WHERE motor = 'pncp' AND ok = 0")
                banco.con.execute("DELETE FROM meta WHERE chave = 'motor:pncp'")
            else:
                banco.apagar_motor(nome)
    else:
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
        "pncp": lambda: motor_pncp(ctx, alvo.ibge, alvo.municipio, orgaos_pncp, pncp_anterior),
        "fontes": lambda: motor_fontes(ctx),
        "normas": lambda: motor_normas(ctx),
        "tesouro": lambda: motor_tesouro(ctx, alvo.municipio, alvo.uf),
    }
    for nome in motores:
        inicio = time.monotonic()
        if tempo_limitado:
            ctx.fim_do_motor = inicio + 60 * TEMPO_DO_MOTOR.get(nome, TEMPO_PADRAO)
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
