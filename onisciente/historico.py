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
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode

from . import RAIZ
from .coletores import base, msc, siope, siops, transparencia

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
TESOURO_BUSCA = ("https://www.tesourotransparente.gov.br/ckan/api/3/action/package_search"
                 "?fq=name:transferencias-constitucionais-para-municipios")
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
# Nome que a listagem do PNCP devolve → código que ela recebe.
MODALIDADE_CODIGO = {"Pregão - Eletrônico": 6, "Dispensa": 8, "Inexigibilidade": 9,
                     "Concorrência - Eletrônica": 4}


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
CREATE TABLE IF NOT EXISTS transferencias_federais (mes TEXT, tipo TEXT, tipo_favorecido TEXT, orgao TEXT,
    funcao TEXT, programa TEXT, acao TEXT, nome_acao TEXT, favorecido TEXT, nome_favorecido TEXT, valor REAL);
CREATE TABLE IF NOT EXISTS msc_itens (mes TEXT, conta_contabil TEXT, poder_orgao TEXT, ano_fonte_recursos INTEGER,
    fonte_recursos TEXT, funcao TEXT, subfuncao TEXT, natureza_receita TEXT, natureza_despesa TEXT,
    ano_inscricao INTEGER, educacao_saude INTEGER, natureza_conta TEXT, valor REAL);
CREATE TABLE IF NOT EXISTS msc_meses (mes TEXT, situacao TEXT, itens INTEGER, prazo TEXT, erro TEXT);
CREATE TABLE IF NOT EXISTS externos_periodos (fonte TEXT, exercicio INTEGER, periodo INTEGER,
    homologado TEXT, situacao TEXT, linhas INTEGER, erro TEXT);
CREATE TABLE IF NOT EXISTS externos_itens (fonte TEXT, exercicio INTEGER, periodo INTEGER, quadro INTEGER,
    titulo_quadro TEXT, ordem INTEGER, rotulo TEXT, coluna INTEGER, valor REAL);
CREATE TABLE IF NOT EXISTS pncp_amparos (compra_id TEXT PRIMARY KEY, codigo INTEGER, nome TEXT, descricao TEXT,
    srp INTEGER, processo TEXT, modo_disputa TEXT, data_publicacao TEXT, valor_estimado REAL, valor_homologado REAL);
CREATE TABLE IF NOT EXISTS pncp_itens (compra_id TEXT, numero_item INTEGER, orgao_cnpj TEXT, unidade TEXT,
    descricao TEXT, detalhe TEXT, material_servico TEXT, classe INTEGER, grupo INTEGER, catalogo INTEGER, pdm TEXT,
    nome_pdm TEXT, ncm TEXT, unidade_medida TEXT, quantidade REAL, unitario_estimado REAL, total_estimado REAL,
    situacao TEXT, fornecedor_ni TEXT, fornecedor TEXT, quantidade_resultado REAL, unitario_resultado REAL,
    total_resultado REAL, data_inclusao TEXT, data_resultado TEXT, PRIMARY KEY (compra_id, numero_item));
CREATE TABLE IF NOT EXISTS pncp_contratos_detalhe (contrato_id TEXT PRIMARY KEY, compra_id TEXT, valor_inicial REAL,
    valor_global REAL, valor_acumulado REAL, tipo TEXT, categoria TEXT, vigencia_inicio TEXT, vigencia_fim TEXT,
    processo TEXT, retificacoes INTEGER);
CREATE TABLE IF NOT EXISTS pncp_termos (contrato_id TEXT, sequencial INTEGER, numero TEXT, tipo TEXT,
    data_assinatura TEXT, vigencia_inicio TEXT, vigencia_fim TEXT, valor_acrescido REAL, valor_global REAL,
    prazo_aditado_dias INTEGER, acrescimo_supressao INTEGER, qualif_vigencia INTEGER, qualif_reajuste INTEGER,
    qualif_fornecedor INTEGER, fundamento TEXT, objeto TEXT, PRIMARY KEY (contrato_id, sequencial));
CREATE TABLE IF NOT EXISTS pncp_cobrancas (contrato_id TEXT, sequencial INTEGER, tipo TEXT, numero TEXT,
    data_emissao TEXT, chave_nfe TEXT, valor_nf REAL, emitente_ni TEXT, evento TEXT, PRIMARY KEY (contrato_id, sequencial));
CREATE TABLE IF NOT EXISTS pncp_nf_itens (contrato_id TEXT, sequencial INTEGER, numero_item TEXT, descricao TEXT,
    ncm TEXT, quantidade REAL, unidade TEXT, unitario REAL, total REAL,
    PRIMARY KEY (contrato_id, sequencial, numero_item));
CREATE TABLE IF NOT EXISTS precos_referencia (catalogo INTEGER, semestre TEXT, id_item TEXT, material_servico TEXT,
    data_compra TEXT, preco REAL, quantidade REAL, unidade TEXT, uasg TEXT, orgao TEXT, uf TEXT, municipio TEXT,
    esfera TEXT, descricao TEXT, PRIMARY KEY (catalogo, semestre, id_item));
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
    "siope": [("coletas", "motor = 'siope'"), ("externos_periodos", "fonte = 'SIOPE'"),
              ("externos_itens", "fonte = 'SIOPE'")],
    "siops": [("coletas", "motor = 'siops'"), ("externos_periodos", "fonte = 'SIOPS'"),
              ("externos_itens", "fonte = 'SIOPS'")],
    "tesouro": [("coletas", "motor = 'tesouro'"), ("transferencias_tesouro", ""),
                ("meta", "chave = 'tesouro_meses'")],
    "normas": [("coletas", "motor = 'ctresb'"), ("normas", "")],
    "transferencias": [("coletas", "motor = 'transferencias'"), ("transferencias_federais", ""),
                       ("meta", "chave = 'transferencias_meses'")],
    "msc": [("coletas", "motor = 'msc'"), ("msc_itens", ""), ("msc_meses", "")],
    "pncp_detalhe": [("coletas", "motor = 'pncp_detalhe'"), ("pncp_amparos", ""), ("pncp_itens", ""),
                     ("pncp_contratos_detalhe", ""), ("pncp_termos", ""), ("pncp_cobrancas", ""),
                     ("pncp_nf_itens", ""), ("precos_referencia", ""), ("meta", "chave = 'pncp_detalhe_lidos'")],
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

def _ftp_sem_arquivo(url: str, leitura: base.Leitura) -> bool:
    """FTP respondeu 550 (arquivo inexistente): resposta definitiva, não falha de rede."""
    return url.startswith("ftp://") and not leitura.ok and " 550" in (leitura.erro or "")


@dataclass
class Contexto:
    banco: Banco
    meses: list[str]
    hoje: date
    ler_url: Callable[..., base.Leitura] = base.ler
    dormir: Callable[[float], None] = time.sleep
    pausa: float = 1.0                     # entre chamadas à mesma API
    brutos: Path | None = None             # se dado, guarda cada resposta crua aqui
    limites: dict[str, int] = field(default_factory=lambda: {"pncp": 2500, "qd": 400, "pncp_detalhe": 20000})
    gastos: dict[str, int] = field(default_factory=dict)
    # Disjuntor: depois de tantas falhas de rede seguidas, o motor deixa de chamar a fonte
    # (o servidor e o serviço da URL; as outras fontes do mesmo motor seguem)
    # e registra o resto como não tentado. Uma fonte fora do ar não pode prender a rodada.
    disjuntor: int = 6
    seguidas: dict[str, int] = field(default_factory=dict)
    fim_do_motor: float | None = None      # relógio monotônico; depois disso, nada é chamado
    # Leituras simultâneas nas vias que demoram por espera do servidor, não por volume
    # (a consulta de uma compra leva uns 10 s). Só a rede vai para as linhas paralelas:
    # o registro no banco e o tratamento da resposta seguem na ordem, na linha principal.
    paralelo: int = 1
    # A fonte que responde 429 ("devagar") deixa de ser lida em paralelo na rodada; se mesmo
    # lida uma a uma ela recusa ``disjuntor`` vezes seguidas, o resto dela fica para a próxima
    # rodada e as outras fontes do mesmo motor seguem. Nunca mais duas horas batendo na porta.
    _lentas: set = field(default_factory=set, repr=False)
    recusas_fonte: dict[str, int] = field(default_factory=dict)
    _antecipadas: dict = field(default_factory=dict, repr=False)
    _trava: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def ler(self, motor: str, alvo: str, url: str, *, mes: str = "", tentativas: int = 3,
            cabecalhos: dict | None = None, tempo: int = 60,
            disjuntor: bool = True, formulario: dict | None = None) -> base.Leitura:
        """Lê com espera crescente em 429 e 5xx, e registra a chamada no banco."""
        antecipada = self._antecipadas.pop((motor, url), None)
        limite = self.limites.get(motor)
        motivo = None
        if antecipada is not None:
            pass                                # já lida (e contada) por ``antecipar``
        elif limite is not None and self.gastos.get(motor, 0) >= limite:
            motivo = "limite de chamadas da rodada atingido"
        elif disjuntor and self.seguidas.get(_fonte_da_url(url), 0) >= self.disjuntor:
            motivo = f"não tentado: {self.disjuntor} falhas de rede seguidas nesta fonte"
        elif disjuntor and self.recusas_fonte.get(_fonte_da_url(url), 0) >= self.disjuntor:
            motivo = (f"não tentado: a fonte pediu para esperar (HTTP 429) {self.disjuntor} vezes "
                      "seguidas nesta rodada")
        elif self.fim_do_motor is not None and time.monotonic() > self.fim_do_motor:
            motivo = "não tentado: tempo do motor nesta rodada esgotado"
        if motivo:
            leitura = base.Leitura(False, url, erro=motivo)
            self._registrar(motor, alvo, mes, leitura, 0, 0.0)
            return leitura
        if antecipada is not None:
            leitura, feitas, segundos = antecipada
        else:
            leitura, feitas, segundos = self._buscar(motor, url, tentativas, cabecalhos, tempo, formulario)
        return self._depois(motor, alvo, mes, url, leitura, feitas, segundos,
                            pausar=antecipada is None)

    def _buscar(self, motor, url, tentativas=3, cabecalhos=None, tempo=60, formulario=None):
        """Só a rede, com espera crescente em 429 e 5xx. Pode rodar fora da linha principal."""
        inicio = time.monotonic()
        leitura = base.Leitura(False, url, erro="não tentado")
        feitas = 0
        for n in range(tentativas):
            feitas = n + 1
            with self._trava:
                self.gastos[motor] = self.gastos.get(motor, 0) + 1
            extra = {"formulario": formulario} if formulario else {}
            leitura = self.ler_url(url, tempo=tempo, cabecalhos=cabecalhos, **extra)
            codigo = leitura.http
            if leitura.ok or _ftp_sem_arquivo(url, leitura) or not (
                    codigo == 429 or (codigo and codigo >= 500)
                    or leitura.erro.startswith(("TimeoutError", "URLError"))):
                break
            if codigo == 429:
                with self._trava:
                    self._lentas.add(_fonte_da_url(url))
                pedida = getattr(leitura, "espera", None)
                self.dormir(min(pedida if pedida is not None else 15 * 2 ** n, 120))
            else:
                self.dormir(min(5 * 2 ** n, 60))
        return leitura, feitas, time.monotonic() - inicio

    def antecipar(self, motor: str, urls, *, tempo: int = 60) -> None:
        """Busca de uma vez, em linhas paralelas, as próximas leituras de um motor. Cada uma é
        entregue depois pelo ``ler`` da mesma URL, que a registra como se tivesse lido agora.
        Respeita o limite de chamadas, o disjuntor e o tempo do motor; com ``paralelo`` 1, nada faz."""
        if self.paralelo <= 1:
            return
        pendentes = list(dict.fromkeys(u for u in urls if u and (motor, u) not in self._antecipadas
                                       and _fonte_da_url(u) not in self._lentas))
        limite = self.limites.get(motor)
        if limite is not None:
            pendentes = pendentes[:max(0, limite - self.gastos.get(motor, 0))]
        pendentes = [u for u in pendentes if self.seguidas.get(_fonte_da_url(u), 0) < self.disjuntor]
        if (not pendentes
                or (self.fim_do_motor is not None and time.monotonic() > self.fim_do_motor)):
            return
        with ThreadPoolExecutor(max_workers=self.paralelo) as linhas:
            for url, resultado in zip(pendentes, linhas.map(
                    lambda u: self._buscar(motor, u, 3, None, tempo, None), pendentes)):
                if resultado[0].http == 429:
                    continue                    # recusada por pressa: será lida de novo, uma a uma
                self._antecipadas[(motor, url)] = resultado

    def _depois(self, motor, alvo, mes, url, leitura, feitas, segundos, *, pausar=True):
        rede = (not leitura.ok and (leitura.http is None or leitura.http >= 500)
                and not _ftp_sem_arquivo(url, leitura))
        fonte_url = _fonte_da_url(url)
        self.seguidas[fonte_url] = self.seguidas.get(fonte_url, 0) + 1 if rede else 0
        if leitura.http is not None:
            fonte = _fonte_da_url(url)
            self.recusas_fonte[fonte] = self.recusas_fonte.get(fonte, 0) + 1 if leitura.http == 429 else 0
        self._registrar(motor, alvo, mes, leitura, feitas, segundos)
        if self.pausa and pausar:
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


def _fonte_da_url(url: str) -> str:
    """O servidor e o serviço de uma URL (pncp.gov.br/api/consulta, pncp.gov.br/api/pncp...):
    a unidade em que uma fonte limita a pressa de quem a lê."""
    resto = url.split("://", 1)[-1]
    partes = resto.split("/")
    return "/".join(partes[:3]) if len(partes) > 2 and partes[1] == "api" else partes[0]


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
                    if c.get("amparoLegal") and c.get("numeroControlePNCP"):
                        _guardar_amparo(ctx, c.get("numeroControlePNCP"), c)   # já vem na listagem
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


# --- Motor 4b: o detalhe das compras e dos contratos (PNCP e Compras.gov.br) -------------

DADOS_ABERTOS = "https://dadosabertos.compras.gov.br/"
PNCP_API = "https://pncp.gov.br/api/pncp/v1/"


def _id_pncp(pncp_id: str) -> tuple[str, int, int] | None:
    """``04973965000111-1-000043/2024`` vira (cnpj, ano, sequencial)."""
    m = re.fullmatch(r"(\d{14})-\d-(\d+)/(\d{4})", str(pncp_id or ""))
    return (m.group(1), int(m.group(3)), int(m.group(2))) if m else None


def _num(v) -> float | None:
    if v in (None, ""):
        return None
    try:
        return float(str(v).replace(",", ".")) if not isinstance(v, (int, float)) else float(v)
    except ValueError:
        return None


def _semestre(data: str) -> str:
    return f"{data[:4]}-{'1' if int(data[5:7]) <= 6 else '2'}"


def _limites_do_semestre(semestre: str) -> tuple[str, str]:
    ano, s = semestre.split("-")
    return (f"{ano}-01-01", f"{ano}-06-30") if s == "1" else (f"{ano}-07-01", f"{ano}-12-31")


class _Lidos:
    """O que o motor já leu por inteiro, para a rodada seguinte continuar de onde parou."""

    def __init__(self, banco: Banco):
        self.banco = banco
        guardado = dict(banco.consultar("SELECT chave, valor FROM meta")).get("pncp_detalhe_lidos")
        self.feitos: set[str] = set(json.loads(guardado)) if guardado else set()

    def __contains__(self, chave: str) -> bool:
        return chave in self.feitos

    def marcar(self, chave: str) -> None:
        self.feitos.add(chave)

    def guardar(self) -> None:
        self.banco.inserir("meta", {"chave": "pncp_detalhe_lidos",
                                    "valor": json.dumps(sorted(self.feitos))})
        self.banco.con.commit()


def _tempo_acabou(ctx: Contexto) -> bool:
    return ctx.fim_do_motor is not None and time.monotonic() > ctx.fim_do_motor


def _itens_do_orgao(ctx: Contexto, cnpj: str, d1: str, d2: str, rotulo: str) -> bool:
    """Itens das contratações de um órgão incluídas no PNCP numa janela, com catálogo e resultado."""
    for pagina in range(1, 201):
        params = {"pagina": pagina, "tamanhoPagina": 100, "orgaoEntidadeCnpj": cnpj,
                  "dataInclusaoPncpInicial": d1, "dataInclusaoPncpFinal": d2}
        leitura = ctx.ler("pncp_detalhe", f"itens {cnpj} {rotulo}", DADOS_ABERTOS
                          + "modulo-contratacoes/2_consultarItensContratacoes_PNCP_14133?" + urlencode(params),
                          mes=rotulo[:7], tempo=120)
        dados = _json(leitura) if leitura.ok else None
        if dados is None:
            return False
        for it in dados.get("resultado") or []:
            ctx.banco.inserir("pncp_itens", {
                "compra_id": it.get("numeroControlePNCPCompra") or it.get("idContratacaoPNCP"),
                "numero_item": it.get("numeroItemPncp") or it.get("numeroItemCompra"),
                "orgao_cnpj": it.get("orgaoEntidadeCnpj") or cnpj,
                "unidade": it.get("unidadeOrgaoCodigoUnidade"),
                "descricao": (it.get("descricaoResumida") or "")[:300],
                "detalhe": (it.get("descricaodetalhada") or "")[:500],
                "material_servico": it.get("materialOuServico"), "classe": it.get("codigoClasse"),
                "grupo": it.get("codigoGrupo"), "catalogo": it.get("codItemCatalogo"),
                "pdm": it.get("codigoPdm"), "nome_pdm": it.get("nomePdm"), "ncm": it.get("codigoNCM"),
                "unidade_medida": (it.get("unidadeMedida") or "").strip(),
                "quantidade": _num(it.get("quantidade")),
                "unitario_estimado": _num(it.get("valorUnitarioEstimado")),
                "total_estimado": _num(it.get("valorTotal")),
                "situacao": it.get("situacaoCompraItemNome"),
                "fornecedor_ni": it.get("codFornecedor"), "fornecedor": it.get("nomeFornecedor"),
                "quantidade_resultado": _num(it.get("quantidadeResultado")),
                "unitario_resultado": _num(it.get("valorUnitarioResultado")),
                "total_resultado": _num(it.get("valorTotalResultado")),
                "data_inclusao": str(it.get("dataInclusaoPncp") or "")[:10],
                "data_resultado": str(it.get("dataResultado") or "")[:10] or None})
        if pagina >= int(dados.get("totalPaginas") or 1):
            return True
    return False


def _url_compra(compra_id: str) -> str | None:
    partes = _id_pncp(compra_id)
    return f"{PNCP}orgaos/{partes[0]}/compras/{partes[1]}/{partes[2]}" if partes else None


def _url_contrato(contrato_id: str, sufixo: str = "") -> str | None:
    partes = _id_pncp(contrato_id)
    return f"{PNCP_API}orgaos/{partes[0]}/contratos/{partes[1]}/{partes[2]}{sufixo}" if partes else None


def _url_itens_da_compra(compra_id: str) -> str | None:
    partes = _id_pncp(compra_id)
    if not partes:
        return None
    return (f"{PNCP_API}orgaos/{partes[0]}/compras/{partes[1]}/{partes[2]}/itens?"
            + urlencode({"pagina": 1, "tamanhoPagina": 500}))


def _url_cobrancas(cnpj: str, mes: str, pagina: int = 1) -> str:
    d1, d2 = f"{mes.replace('-', '')}01", fim_do_mes(mes).strftime("%Y%m%d")
    return PNCP + "instrumentoscobranca/inclusao?" + urlencode(
        {"dataInicial": d1, "dataFinal": d2, "cnpjOrgao": cnpj, "pagina": pagina, "tamanhoPagina": 100})


def _detalhe_da_compra(ctx: Contexto, compra_id: str) -> bool:
    url = _url_compra(compra_id)
    if not url:
        return True
    leitura = ctx.ler("pncp_detalhe", f"compra {compra_id}", url, tempo=60)
    c = _json(leitura) if leitura.ok else None
    if not isinstance(c, dict):
        return leitura.http in (204, 404)
    _guardar_amparo(ctx, compra_id, c)
    return True


def _guardar_amparo(ctx: Contexto, compra_id: str, c: dict) -> None:
    """O amparo legal de uma contratação, venha do detalhe dela ou da listagem do mês (as duas
    respostas do PNCP trazem os mesmos campos)."""
    amparo = c.get("amparoLegal") or {}
    ctx.banco.inserir("pncp_amparos", {
        "compra_id": compra_id, "codigo": amparo.get("codigo"), "nome": amparo.get("nome"),
        "descricao": (amparo.get("descricao") or "")[:400], "srp": int(bool(c.get("srp"))),
        "processo": c.get("processo"), "modo_disputa": c.get("modoDisputaNome"),
        "data_publicacao": str(c.get("dataPublicacaoPncp") or "")[:10],
        "valor_estimado": _num(c.get("valorTotalEstimado")),
        "valor_homologado": _num(c.get("valorTotalHomologado"))})


def _amparos_pela_listagem(ctx: Contexto, ibge: int, modalidade: int, mes: str, faltam: set[str]) -> bool:
    """O amparo legal de todas as contratações de uma modalidade no mês, numa leitura da
    listagem (até 50 por página) em vez de uma consulta de 10 s por contratação. Guarda só as
    que o banco já tem e ainda não têm amparo; diz se o mês foi lido por inteiro."""
    d1, d2 = f"{mes.replace('-', '')}01", fim_do_mes(mes).strftime("%Y%m%d")
    for pagina in range(1, 41):
        params = {"dataInicial": d1, "dataFinal": d2, "codigoModalidadeContratacao": modalidade,
                  "codigoMunicipioIbge": ibge, "pagina": pagina, "tamanhoPagina": 50}
        leitura = ctx.ler("pncp_detalhe", f"amparos m{modalidade}",
                          PNCP + "contratacoes/publicacao?" + urlencode(params), mes=mes)
        if leitura.http == 204:
            return True
        dados = _json(leitura) if leitura.ok else None
        if not isinstance(dados, dict):
            return False
        for c in dados.get("data") or []:
            cid = c.get("numeroControlePNCP")
            if cid in faltam:
                _guardar_amparo(ctx, cid, c)
                faltam.discard(cid)
        if pagina >= int(dados.get("totalPaginas") or 1):
            return True
    return False


def _detalhe_do_contrato(ctx: Contexto, contrato_id: str) -> bool:
    url = _url_contrato(contrato_id)
    if not url:
        return True
    leitura = ctx.ler("pncp_detalhe", f"contrato {contrato_id}", url, tempo=60)
    c = _json(leitura) if leitura.ok else None
    if not isinstance(c, dict):
        return leitura.http in (204, 404)
    ctx.banco.inserir("pncp_contratos_detalhe", {
        "contrato_id": contrato_id, "compra_id": c.get("numeroControlePncpCompra"),
        "valor_inicial": _num(c.get("valorInicial")), "valor_global": _num(c.get("valorGlobal")),
        "valor_acumulado": _num(c.get("valorAcumulado")),
        "tipo": (c.get("tipoContrato") or {}).get("nome"),
        "categoria": (c.get("categoriaProcesso") or {}).get("nome"),
        "vigencia_inicio": c.get("dataVigenciaInicio"), "vigencia_fim": c.get("dataVigenciaFim"),
        "processo": c.get("processo"), "retificacoes": c.get("numeroRetificacao")})
    return True


def _termos_do_contrato(ctx: Contexto, contrato_id: str) -> bool:
    url = _url_contrato(contrato_id, "/termos")
    if not url:
        return True
    leitura = ctx.ler("pncp_detalhe", f"termos {contrato_id}", url, tempo=60)
    if leitura.http == 204:
        return True                            # a API respondeu: nenhum termo publicado
    dados = _json(leitura) if leitura.ok else None
    if not isinstance(dados, list):
        return leitura.http == 404
    for t in dados:
        ctx.banco.inserir("pncp_termos", {
            "contrato_id": contrato_id, "sequencial": t.get("sequencialTermoContrato"),
            "numero": t.get("numeroTermoContrato"), "tipo": t.get("tipoTermoContratoNome"),
            "data_assinatura": t.get("dataAssinatura"), "vigencia_inicio": t.get("dataVigenciaInicio"),
            "vigencia_fim": t.get("dataVigenciaFim"), "valor_acrescido": _num(t.get("valorAcrescido")),
            "valor_global": _num(t.get("valorGlobal")), "prazo_aditado_dias": t.get("prazoAditadoDias"),
            "acrescimo_supressao": int(bool(t.get("qualificacaoAcrescimoSupressao"))),
            "qualif_vigencia": int(bool(t.get("qualificacaoVigencia"))),
            "qualif_reajuste": int(bool(t.get("qualificacaoReajuste"))),
            "qualif_fornecedor": int(bool(t.get("qualificacaoFornecedor"))),
            "fundamento": (t.get("fundamentoLegal") or "")[:300],
            "objeto": (t.get("objetoTermoContrato") or "")[:500]})
    return True


def _precos_nacionais(ctx: Contexto, catalogo: int, servico: bool, semestre: str) -> bool:
    """Até 500 compras do país do mesmo item de catálogo no semestre (painel de preços)."""
    d1, d2 = _limites_do_semestre(semestre)
    if servico:
        url = DADOS_ABERTOS + "modulo-pesquisa-preco/3_consultarServico?" + urlencode(
            {"pagina": 1, "tamanhoPagina": 500, "codigoItemCatalogo": catalogo,
             "dataCompraInicio": d1, "dataCompraFim": d2})
    else:
        url = DADOS_ABERTOS + "modulo-pesquisa-preco/1_consultarMaterial?" + urlencode(
            {"pagina": 1, "tamanhoPagina": 500, "tipo": "codigoItemCatalogo", "codigo": catalogo,
             "dataCompraInicio": d1, "dataCompraFim": d2})
    leitura = ctx.ler("pncp_detalhe", f"preco {catalogo} {semestre}", url, mes=semestre, tempo=120)
    dados = _json(leitura) if leitura.ok else None
    if dados is None:
        return False
    for r in dados.get("resultado") or []:
        ctx.banco.inserir("precos_referencia", {
            "catalogo": catalogo, "semestre": semestre,
            "id_item": str(r.get("idCompraItem") or r.get("idItemCompra")),
            "material_servico": "S" if servico else "M", "data_compra": r.get("dataCompra"),
            "preco": _num(r.get("precoUnitario")), "quantidade": _num(r.get("quantidade")),
            "unidade": r.get("siglaUnidadeFornecimento") or r.get("siglaUnidadeMedida")
            or r.get("nomeUnidadeMedida"),
            "uasg": r.get("codigoUasg"), "orgao": r.get("nomeOrgao"), "uf": r.get("estado"),
            "municipio": r.get("municipio"), "esfera": r.get("esfera"),
            "descricao": (r.get("descricaoItem") or "")[:300]})
    return True


def _nenhum_registro(leitura: base.Leitura) -> bool:
    """O PNCP responde 404 com {"message": "Nenhum ... encontrado"} quando a consulta não acha
    registro. Só esse corpo separa o "não há" de um endereço errado, que continua falha."""
    if leitura.http != 404 or not leitura.conteudo:
        return False
    try:
        mensagem = str((json.loads(leitura.conteudo) or {}).get("message") or "")
    except (ValueError, AttributeError):
        return False
    return _norm(mensagem).lower().startswith("nenhum")


def _cobrancas_do_orgao(ctx: Contexto, cnpj: str, mes: str) -> bool:
    """Instrumentos de cobrança (notas fiscais) que o órgão incluiu no PNCP no mês."""
    for pagina in range(1, 21):
        leitura = ctx.ler("pncp_detalhe", f"cobrancas {cnpj} {mes}", _url_cobrancas(cnpj, mes, pagina),
                          mes=mes)
        if leitura.http == 204 or _nenhum_registro(leitura):
            return True                 # lido: o órgão não publicou nota fiscal no mês
        dados = _json(leitura) if leitura.ok else None
        if not dados:
            return False
        for c in dados.get("data") or []:
            contrato = c.get("recuperarContratoDTO") or {}
            cid = contrato.get("numeroControlePNCP") or (
                f"{c.get('cnpj')}-2-{int(c.get('sequencialContrato') or 0):06d}/{c.get('ano')}")
            nf = c.get("notaFiscalEletronica") or {}
            seq = c.get("sequencialInstrumentoCobranca")
            ctx.banco.inserir("pncp_cobrancas", {
                "contrato_id": cid, "sequencial": seq,
                "tipo": (c.get("tipoInstrumentoCobranca") or {}).get("nome"),
                "numero": c.get("numeroInstrumentoCobranca"), "data_emissao": c.get("dataEmissaoDocumento"),
                "chave_nfe": c.get("chaveNFe"), "valor_nf": _num(nf.get("valorNotaFiscal")),
                "emitente_ni": nf.get("niEmitente"), "evento": nf.get("tipoEventoMaisRecente")})
            for it in nf.get("itens") or []:
                ctx.banco.inserir("pncp_nf_itens", {
                    "contrato_id": cid, "sequencial": seq, "numero_item": it.get("numeroItem"),
                    "descricao": (it.get("descricaoProdutoServico") or "")[:300], "ncm": it.get("codigoNCM"),
                    "quantidade": _num(it.get("quantidade")), "unidade": it.get("unidade"),
                    "unitario": _num(it.get("valorUnitario")), "total": _num(it.get("valorTotal"))})
        if pagina >= int(dados.get("totalPaginas") or 1):
            return True
    return False


def _da_pasta(orgao: str | None) -> bool:
    from .conferencias.compras import da_pasta      # tardio: a conferência lê este módulo
    return da_pasta(orgao or "")


def _itens_da_compra(ctx: Contexto, compra_id: str) -> bool:
    """Itens e resultado de uma contratação pela API do PNCP (via rápida, por compra).

    Não substitui o que a via de dados abertos já guardou (ela traz o código de catálogo
    e a classe); só preenche o que falta.
    """
    partes = _id_pncp(compra_id)
    if not partes:
        return True
    cnpj, ano, seq = partes
    base = f"{PNCP_API}orgaos/{cnpj}/compras/{ano}/{seq}/itens"
    leitura = ctx.ler("pncp_detalhe", f"itens da compra {compra_id}", _url_itens_da_compra(compra_id),
                      tempo=60)
    if leitura.http == 204:
        return True
    dados = _json(leitura) if leitura.ok else None
    if not isinstance(dados, list):
        return leitura.http == 404
    ja = {n for (n,) in ctx.banco.consultar(
        "SELECT numero_item FROM pncp_itens WHERE compra_id = ? AND catalogo IS NOT NULL", compra_id)}
    inteiro = True
    for it in dados:
        numero = it.get("numeroItem")
        if numero is None or numero in ja:
            continue
        resultado: dict = {}
        if it.get("temResultado"):
            r = ctx.ler("pncp_detalhe", f"resultado {compra_id} {numero}", f"{base}/{numero}/resultados",
                        tempo=60)
            lista = _json(r) if r.ok else None
            if isinstance(lista, list) and lista:
                resultado = lista[0]
            elif r.http not in (204, 404):
                inteiro = False
        cat = str(it.get("catalogoCodigoItem") or "").strip()
        ctx.banco.inserir("pncp_itens", {
            "compra_id": compra_id, "numero_item": numero, "orgao_cnpj": cnpj, "unidade": None,
            "descricao": (it.get("descricao") or "")[:300],
            "detalhe": (it.get("informacaoComplementar") or "")[:500],
            "material_servico": it.get("materialOuServico"), "classe": None, "grupo": None,
            "catalogo": int(cat) if cat.isdigit() else None, "pdm": None,
            "nome_pdm": it.get("itemCategoriaNome"), "ncm": it.get("ncmNbsCodigo"),
            "unidade_medida": (it.get("unidadeMedida") or "").strip(),
            "quantidade": _num(it.get("quantidade")),
            "unitario_estimado": _num(it.get("valorUnitarioEstimado")),
            "total_estimado": _num(it.get("valorTotal")),
            "situacao": it.get("situacaoCompraItemNome"),
            "fornecedor_ni": resultado.get("niFornecedor"),
            "fornecedor": resultado.get("nomeRazaoSocialFornecedor"),
            "quantidade_resultado": _num(resultado.get("quantidadeHomologada")),
            "unitario_resultado": _num(resultado.get("valorUnitarioHomologado")),
            "total_resultado": _num(resultado.get("valorTotalHomologado")),
            "data_inclusao": str(it.get("dataInclusao") or "")[:10],
            "data_resultado": str(resultado.get("dataResultado") or "")[:10] or None})
    return inteiro


def motor_pncp_detalhe(ctx: Contexto, ibge: int | None = None) -> None:
    """O detalhe do que o motor do PNCP achou: amparo legal de cada contratação, itens com
    catálogo e preço homologado, valor inicial e aditivos de cada contrato, o preço nacional
    do mesmo item no semestre e as notas fiscais publicadas.

    Lê das contratações e contratos já guardados no banco. A pasta (assistência social e
    direitos humanos) vem sempre primeiro, e as vias rápidas do PNCP antes da via lenta dos
    dados abertos, para o tempo da rodada nunca acabar antes do que o parecer precisa.
    Continua de onde a rodada anterior parou: cada etapa marca o que leu por inteiro, e as
    que falharam são refeitas.
    """
    lidos = _Lidos(ctx.banco)
    pausa, ctx.pausa = ctx.pausa, min(ctx.pausa, 0.3)    # as vias de detalhe respondem em segundos

    def etapa(pedidos) -> None:
        """(chave, url da primeira leitura, leitor): o que falta é lido em blocos, com a rede
        do bloco antecipada em paralelo e o tratamento na ordem."""
        faltam = [p for p in pedidos if p[0] not in lidos]
        bloco = max(1, ctx.paralelo * 4)
        for i in range(0, len(faltam), bloco):
            if _tempo_acabou(ctx):
                break
            parte = faltam[i:i + bloco]
            ctx.antecipar("pncp_detalhe", [url for _, url, _ in parte])
            for chave, _url, ler in parte:
                if ler():
                    lidos.marcar(chave)
            lidos.guardar()
        lidos.guardar()

    compras = sorted(ctx.banco.consultar(
        "SELECT pncp_id, orgao_cnpj, orgao, modalidade, COALESCE(valor_homologado, valor_estimado, 0), mes "
        "FROM contratacoes_pncp"),
        key=lambda c: (not _da_pasta(c[2]), {"Dispensa": 0, "Inexigibilidade": 1}.get(c[3], 2), -c[4]))
    contratos = sorted(ctx.banco.consultar(
        "SELECT pncp_id, orgao, COALESCE(valor_global, 0) FROM contratos_pncp"),
        key=lambda c: (not _da_pasta(c[1]), -c[2]))
    peso: dict[str, tuple] = {}
    for cnpj, orgao, n in ctx.banco.consultar(
            "SELECT orgao_cnpj, MAX(orgao), COUNT(*) FROM (SELECT orgao_cnpj, orgao FROM contratacoes_pncp "
            "UNION ALL SELECT orgao_cnpj, orgao FROM contratos_pncp) WHERE orgao_cnpj IS NOT NULL GROUP BY 1"):
        peso[cnpj] = (not _da_pasta(orgao), -n)
    orgaos = sorted(peso, key=lambda c: (peso[c], c))
    pasta = [c for c in orgaos if not peso[c][0]]
    try:
        def amparos(lista):
            com = {i for (i,) in ctx.banco.consultar("SELECT compra_id FROM pncp_amparos")}
            etapa([(f"compra {c[0]}", _url_compra(c[0]), lambda c=c: _detalhe_da_compra(ctx, c[0]))
                   for c in lista if c[0] not in com])

        # 1. Amparo legal das contratações da pasta e de todas as dispensas (o que a conferência
        #    de dispensas precisa); as demais modalidades ficam para depois dos contratos.
        primeiro = [c for c in compras if _da_pasta(c[2]) or c[3] == "Dispensa"]
        amparos(primeiro)
        # 2. Valor inicial e vínculo com a compra, depois os termos aditivos: a pasta, depois os maiores.
        etapa([(f"contrato {c[0]}", _url_contrato(c[0]), lambda c=c: _detalhe_do_contrato(ctx, c[0]))
               for c in contratos])
        etapa([(f"termos {c[0]}", _url_contrato(c[0], "/termos"), lambda c=c: _termos_do_contrato(ctx, c[0]))
               for c in contratos])
        # 3. Itens e resultado de cada contratação da pasta pela via rápida do PNCP.
        etapa([(f"itens da compra {c[0]}", _url_itens_da_compra(c[0]), lambda c=c: _itens_da_compra(ctx, c[0]))
               for c in compras if _da_pasta(c[2])])
        # 4. Notas fiscais: órgão a órgão (a pasta primeiro), mês a mês; três recusas seguidas param o órgão.
        for cnpj in orgaos:
            if _tempo_acabou(ctx):
                break
            ctx.antecipar("pncp_detalhe", [_url_cobrancas(cnpj, m) for m in ctx.meses
                                           if f"cobrancas {cnpj} {m}" not in lidos])
            recusas = 0
            for mes in ctx.meses:
                chave = f"cobrancas {cnpj} {mes}"
                if chave in lidos:
                    continue
                if _tempo_acabou(ctx) or recusas >= 3:
                    break
                if _cobrancas_do_orgao(ctx, cnpj, mes):
                    lidos.marcar(chave)
                    recusas = 0
                else:
                    recusas += 1
            lidos.guardar()
            ctx._antecipadas.clear()           # meses de um órgão parado por recusas: descartados
        # 4b. Amparo legal das demais contratações (inexigibilidades, pregões, concorrências):
        #     primeiro pela listagem do mês (50 por leitura), depois uma a uma o que ela não trouxe.
        ja = {c[0] for c in primeiro}
        if ibge:
            com = {i for (i,) in ctx.banco.consultar("SELECT compra_id FROM pncp_amparos")}
            faltam = {c[0] for c in compras if c[0] not in com}
            janelas = sorted({(MODALIDADE_CODIGO[c[3]], c[5]) for c in compras
                              if c[0] in faltam and c[3] in MODALIDADE_CODIGO and c[5]})
            for modalidade, mes in janelas:
                chave = f"amparos {modalidade} {mes}"
                if chave in lidos:
                    continue
                if _tempo_acabou(ctx):
                    break
                if _amparos_pela_listagem(ctx, ibge, modalidade, mes, faltam):
                    lidos.marcar(chave)
                lidos.guardar()
        amparos([c for c in compras if c[0] not in ja])
        # 5. Itens com catálogo e classe pela via de dados abertos (lenta): a pasta, depois os órgãos
        #    com mais compras; um ano recusado é refeito mês a mês.
        for cnpj in pasta + [c for c in orgaos if c not in pasta]:
            for janela in _janelas_anuais(ctx.meses):
                chave = f"itens {cnpj} {janela[0][:4]}"
                if chave in lidos or _tempo_acabou(ctx):
                    continue
                d1, d2 = f"{janela[0]}-01", fim_do_mes(janela[-1]).isoformat()
                ja_mes_a_mes = any(f"itens {cnpj} {m}" in lidos for m in janela)   # o ano já foi recusado
                if not ja_mes_a_mes and _itens_do_orgao(ctx, cnpj, d1, d2, f"{janela[0]} a {janela[-1]}"):
                    lidos.marcar(chave)
                    continue
                inteiro = True
                for mes in janela:
                    chave_mes = f"itens {cnpj} {mes}"
                    if chave_mes in lidos:
                        continue
                    if _tempo_acabou(ctx):
                        inteiro = False
                        break
                    if _itens_do_orgao(ctx, cnpj, f"{mes}-01", fim_do_mes(mes).isoformat(), mes):
                        lidos.marcar(chave_mes)
                    else:
                        inteiro = False
                if inteiro:
                    lidos.marcar(chave)
            lidos.guardar()
        # 6. Preço nacional de cada item de catálogo homologado, no semestre da compra (a pasta primeiro).
        alvos = ctx.banco.consultar(
            "SELECT catalogo, material_servico, substr(COALESCE(data_resultado, data_inclusao), 1, 7), "
            "SUM(COALESCE(total_resultado, total_estimado, 0)), MAX(orgao_cnpj IN (%s)) FROM pncp_itens "
            "WHERE catalogo IS NOT NULL AND unitario_resultado IS NOT NULL GROUP BY 1, 2, 3 "
            "ORDER BY 5 DESC, 4 DESC" % (",".join("?" * len(pasta)) or "''"), *pasta)
        feitos: set[tuple] = set()
        for catalogo, ms, mes, _valor, _pasta in alvos:
            if not mes or not re.fullmatch(r"\d{4}-\d{2}", mes):
                continue
            semestre = _semestre(mes + "-01")
            chave = f"preco {catalogo} {semestre}"
            if (catalogo, semestre) in feitos or chave in lidos:
                continue
            feitos.add((catalogo, semestre))
            if _tempo_acabou(ctx):
                break
            if _precos_nacionais(ctx, int(catalogo), ms == "S", semestre):
                lidos.marcar(chave)
            if len(feitos) % 50 == 0:
                lidos.guardar()
        lidos.guardar()
    finally:
        ctx.pausa = pausa
        ctx._antecipadas.clear()
        lidos.guardar()


# --- Motor 5: portais e endereços do sistema ------------------------------------------

# --- Motor: transferências constitucionais do Tesouro (a segunda via do rio) -------------

def recursos_tesouro(pacote: dict) -> dict[str, str]:
    """Do pacote CKAN, o endereço da planilha mensal de cada mês (AAAA-MM)."""
    achados = {}
    resultado = pacote.get("result") or {}
    pacotes = resultado.get("results") if "results" in resultado else [resultado]   # package_search ou _show
    recursos = [r for p in pacotes or [] for r in (p.get("resources") or [])]
    for r in recursos:
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
    pacote = None
    for alvo, url in (("pacote", TESOURO_PACOTE), ("busca", TESOURO_BUSCA)):   # a busca é a 2ª porta do CKAN
        leitura = ctx.ler("tesouro", alvo, url, tentativas=4, tempo=90)
        pacote = _json(leitura) if leitura.ok else None
        if pacote:
            break
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


# --- Motor: transferências federais (Portal da Transparência, base SIAFI) -------------------

def motor_transferencias(ctx: Contexto, municipio: str, uf: str) -> None:
    """O arquivo do mês de cada mês fechado: tudo o que a União transferiu ao Município e às
    entidades com sede nele. Mês sem arquivo ainda é "não publicado"; arquivo ilegível é formato."""
    lidos, nao_publicados = [], []
    for mes in ctx.meses:
        if fim_do_mes(mes) >= ctx.hoje:
            continue
        url = transparencia.url_mes(mes)
        leitura = ctx.ler("transferencias", "mes", url, mes=mes, tempo=180)
        if not leitura.ok:
            if leitura.http in (403, 404):
                nao_publicados.append(mes)
            continue
        try:
            linhas = transparencia.linhas_do_municipio(leitura.conteudo, municipio, uf)
        except ValueError as e:
            if leitura.conteudo[:15].lstrip().lower().startswith((b"<!doctype", b"<html")):
                nao_publicados.append(mes)   # o portal devolve a página, não o arquivo, para mês sem dado
            else:
                _anotar(ctx, "transferencias", "mes", mes, url, f"formato: {e}")
            continue
        if not linhas:
            _anotar(ctx, "transferencias", "mes", mes, url, f"{municipio} não está no arquivo do mês")
            continue
        for linha in linhas:
            if linha["mes"] == mes:
                ctx.banco.inserir("transferencias_federais", linha)
        lidos.append(mes)
    ctx.banco.inserir("meta", {"chave": "transferencias_meses", "valor": json.dumps(
        {"lidos": lidos, "nao_publicados": nao_publicados})})


# --- Motor: MSC (a matriz de saldos contábeis do mês, por fonte e por função) ---------------

def prazo_msc(mes: str) -> date:
    """A MSC do mês se envia até o último dia do mês seguinte."""
    return fim_do_mes(mes_seguinte(mes))


def mes_seguinte(mes: str) -> str:
    a, m = map(int, mes.split("-"))
    return f"{a + (m == 12)}-{1 if m == 12 else m + 1:02d}"


def motor_msc(ctx: Contexto, ibge: int) -> None:
    """A classe 6 da MSC de cada mês fechado, página a página. Mês sem matriz dentro do prazo é
    "no_prazo"; depois do prazo, "nao_entregue", que é lacuna do Município."""
    for mes in ctx.meses:
        if fim_do_mes(mes) >= ctx.hoje:
            continue
        prazo = prazo_msc(mes)
        linha = {"mes": mes, "situacao": None, "itens": 0, "prazo": prazo.isoformat(), "erro": None}
        itens: list[dict] = []
        offset, ok = 0, True
        while True:
            url = msc.url(ibge, mes, offset=offset)
            leitura = ctx.ler("msc", f"classe 6 +{offset}", url, mes=mes, tempo=120)
            if not leitura.ok:
                linha.update(situacao="falha", erro=leitura.erro or f"HTTP {leitura.http}")
                ok = False
                break
            try:
                pagina, mais = msc.pagina(leitura.conteudo)
            except ValueError as e:
                _anotar(ctx, "msc", f"classe 6 +{offset}", mes, url, f"formato: {e}")
                linha.update(situacao="formato", erro=str(e)[:300])
                ok = False
                break
            itens.extend(pagina)
            if not mais or not pagina:
                break
            offset += len(pagina)
        if ok:
            if itens:
                for it in itens:
                    ctx.banco.inserir("msc_itens", {"mes": mes, **it})
                linha.update(situacao="entregue", itens=len(itens))
            else:
                linha["situacao"] = "no_prazo" if ctx.hoje <= prazo else "nao_entregue"
        ctx.banco.inserir("msc_meses", linha)


# --- Motor: SIOPS (o demonstrativo da saúde, RREO Anexo 12, homologado no Ministério) -------

def motor_siops(ctx: Contexto, municipio: str, uf_codigo: str) -> None:
    """Para cada exercício do intervalo, os bimestres já fechados, como o SIOPS os publica."""
    for ano in sorted({int(m[:4]) for m in ctx.meses}):
        escolha = ctx.ler("siops", f"escolha {ano}", siops.url_escolha(uf_codigo, ano))
        if not escolha.ok:
            continue
        pagina = siops.texto(escolha.conteudo)
        codigos = siops.periodos(pagina)
        mun = siops.codigo_municipio(pagina, municipio)
        if not codigos or not mun:
            _anotar(ctx, "siops", f"escolha {ano}", "", escolha.url,
                    "formato: a página de escolha não trouxe os bimestres ou o município")
            continue
        for bim in range(1, 7):
            per = Periodo("RREO", ano, bim)
            # Todos os bimestres fechados de cada exercício tocado: o ritmo do ano anterior é a régua
            # do piso antes do 6º bimestre (fiscal._ritmo).
            if per.termina > ctx.hoje:
                continue
            linha_periodo = {"fonte": "SIOPS", "exercicio": ano, "periodo": bim, "homologado": None,
                             "situacao": None, "linhas": 0, "erro": None}
            codigo = codigos.get(bim)
            if codigo is None:
                linha_periodo.update(situacao="sem_periodo", erro="o SIOPS não oferece o bimestre")
                ctx.banco.inserir("externos_periodos", linha_periodo)
                continue
            leitura = ctx.ler("siops", f"{ano}-{bim}", siops.RELATORIO, mes=per.meses[-1],
                              formulario=siops.formulario(ano, uf_codigo, codigo, mun), tempo=90)
            if not leitura.ok:
                linha_periodo.update(situacao="falha", erro=leitura.erro)
                ctx.banco.inserir("externos_periodos", linha_periodo)
                continue
            texto = siops.texto(leitura.conteudo)
            try:
                d = siops.ler(texto)
            except ValueError as e:
                nao = "NAO TRANSMITIU" in siops._norm(re.sub(r"<[^>]+>", " ", texto))
                ausente = "no_prazo" if ctx.hoje <= per.prazo else "nao_entregue"
                linha_periodo.update(situacao=ausente if nao else "formato", erro=str(e))
                ctx.banco.inserir("externos_periodos", linha_periodo)
                continue
            if (d.exercicio, d.bimestre) != (ano, bim):
                linha_periodo.update(situacao="formato",
                                     erro=f"a página trouxe {d.bimestre}º bimestre de {d.exercicio}")
                ctx.banco.inserir("externos_periodos", linha_periodo)
                continue
            for linha in d.linhas:
                for coluna, valor in enumerate(linha.valores):
                    if valor is None:
                        continue
                    ctx.banco.inserir("externos_itens", {
                        "fonte": "SIOPS", "exercicio": ano, "periodo": bim, "quadro": linha.quadro,
                        "titulo_quadro": linha.titulo_quadro, "ordem": linha.ordem, "rotulo": linha.rotulo,
                        "coluna": coluna, "valor": valor})
            linha_periodo.update(homologado=d.homologado, situacao="homologado", linhas=len(d.linhas))
            ctx.banco.inserir("externos_periodos", linha_periodo)


def motor_siope(ctx: Contexto, ibge6: str) -> None:
    """O RREO Anexo 8 de cada bimestre fechado, pelo PDF que o FNDE publica no FTP do SIOPE.

    Arquivo ausente no FTP (erro 550) é bimestre não transmitido ao SIOPE: lacuna do Município.
    """
    for ano in sorted({int(m[:4]) for m in ctx.meses}):
        for bim in range(1, 7):
            per = Periodo("RREO", ano, bim)
            # Todos os bimestres fechados de cada exercício tocado: o ritmo do ano anterior é a régua
            # do piso antes do 6º bimestre (fiscal._ritmo).
            if per.termina > ctx.hoje:
                continue
            linha_periodo = {"fonte": "SIOPE", "exercicio": ano, "periodo": bim, "homologado": None,
                             "situacao": None, "linhas": 0, "erro": None}
            leitura = ctx.ler("siope", f"{ano}-{bim}", siope.url_pdf(ibge6, bim, ano), mes=per.meses[-1], tempo=90)
            if not leitura.ok:
                nao = "550" in (leitura.erro or "")
                ausente = "no_prazo" if ctx.hoje <= per.prazo else "nao_entregue"   # LRF, art. 52: 30 dias
                linha_periodo.update(situacao=ausente if nao else "falha", erro=leitura.erro)
                ctx.banco.inserir("externos_periodos", linha_periodo)
                continue
            try:
                d = siope.ler(leitura.conteudo)
            except Exception as e:      # PDF ilegível: formato, não lacuna
                linha_periodo.update(situacao="formato", erro=f"{type(e).__name__}: {e}")
                ctx.banco.inserir("externos_periodos", linha_periodo)
                continue
            if (d.exercicio, d.bimestre) != (ano, bim):
                linha_periodo.update(situacao="formato",
                                     erro=f"o PDF traz o {d.bimestre}º bimestre de {d.exercicio}")
                ctx.banco.inserir("externos_periodos", linha_periodo)
                continue
            for item in d.itens:
                for coluna, valor in enumerate(item.valores):
                    ctx.banco.inserir("externos_itens", {
                        "fonte": "SIOPE", "exercicio": ano, "periodo": bim, "quadro": 0, "titulo_quadro": "",
                        "ordem": item.ordem, "rotulo": f"{item.codigo}- {item.rotulo}"[:200],
                        "coluna": coluna, "valor": valor})
            linha_periodo.update(situacao="homologado", linhas=len(d.itens))
            ctx.banco.inserir("externos_periodos", linha_periodo)


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


MOTORES = ("siconfi", "querido_diario", "sileg", "fnas", "pncp", "fontes", "normas", "tesouro", "siops", "siope",
           "transferencias", "msc", "pncp_detalhe")
# Minutos que cada motor pode usar numa rodada (o fluxo do GitHub para em 180).
TEMPO_DO_MOTOR = {"pncp": 75, "siconfi": 20, "transferencias": 30, "msc": 20, "pncp_detalhe": 150}
TEMPO_PADRAO = 12
PARALELO = 6           # leituras simultâneas nas vias de detalhe (só onde o motor antecipa)


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
            if nome == "pncp_detalhe":           # continua de onde parou; só as falhas são refeitas
                banco.con.execute("DELETE FROM coletas WHERE motor = 'pncp_detalhe' AND ok = 0")
                banco.con.execute("DELETE FROM meta WHERE chave = 'motor:pncp_detalhe'")
            elif nome == "pncp" and pncp_anterior:
                banco.con.execute("DELETE FROM coletas WHERE motor = 'pncp' AND ok = 0")
                banco.con.execute("DELETE FROM meta WHERE chave = 'motor:pncp'")
            else:
                banco.apagar_motor(nome)
    else:
        banco = Banco(caminho)
    kw.setdefault("paralelo", PARALELO)
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
        "siops": lambda: motor_siops(ctx, alvo.municipio, str(alvo.ibge)[:2]),
        "siope": lambda: motor_siope(ctx, str(alvo.ibge)[:6]),
        "transferencias": lambda: motor_transferencias(ctx, alvo.municipio, alvo.uf),
        "msc": lambda: motor_msc(ctx, alvo.siconfi_id_ente),
        "pncp_detalhe": lambda: motor_pncp_detalhe(ctx, alvo.ibge),
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
