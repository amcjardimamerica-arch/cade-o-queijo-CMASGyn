"""Provas que o Onisciente já tem, sem rede, para os critérios do selo.

Vêm do banco histórico (``dados/onisciente/historico.db``), do mapa legal e dos relatórios que os
outros motores já gravaram. Cada prova diz o critério, o item, o valor (atendido ou em falta), em que
leitura vale (``ambas``, ``oficial`` ou ``restritiva``), a fonte e o nível de prova. Ausência de dado
é prova de falta na leitura restritiva (premissa do dono); na oficial, só quando a falta é do próprio
portal do ente.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import yaml

from .. import partes as _partes
from .. import RAIZ
from ..conferencias import compras
from ..legal.mapa import MapaLegal
from ..nucleo.provas import Nivel

CNPJ_FMAS = "01393989000103"
CNPJ_CAMARA = "00001727000193"


@dataclass(frozen=True)
class Prova:
    criterio: str
    item: str
    valor: bool
    leituras: str                # ambas, oficial ou restritiva
    descricao: str
    fonte: str
    nivel: Nivel = Nivel.F
    valor_em_jogo: float = 0.0

    def vale(self, leitura: str) -> bool:
        return self.leituras in ("ambas", leitura)

    def como_dict(self) -> dict:
        return {"criterio": self.criterio, "item": self.item, "valor": self.valor, "leituras": self.leituras,
                "descricao": self.descricao, "fonte": self.fonte, "nivel": self.nivel.name,
                "valor_em_jogo": self.valor_em_jogo}


def reais(v: float) -> str:
    """Valor em reais no formato brasileiro: R$ 1.234,56."""
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _tabela(con: sqlite3.Connection, nome: str) -> bool:
    return _partes.tem_tabela(con, nome)


# --- Banco histórico ---------------------------------------------------------------------------

def do_banco(con: sqlite3.Connection) -> list[Prova]:
    provas: list[Prova] = []
    if _tabela(con, "fontes"):
        for nome, url, ok, http in con.execute("select nome, url, ok, http from fontes"):
            if "goiania.go.gov.br/transparencia" in (url or "") and ok:
                provas.append(Prova("1.2", "disponibilidade", True, "ambas",
                                    f"o portal da transparência respondeu HTTP {http} na rodada da coleta",
                                    f"banco, tabela fontes: {url}", Nivel.B))
                provas.append(Prova("1.1", "disponibilidade", True, "ambas",
                                    "o sítio oficial da Prefeitura respondeu na rodada da coleta",
                                    f"banco, tabela fontes: {url}", Nivel.B))
    provas += _siconfi(con)
    provas += _notas_fiscais(con)
    return provas


def _siconfi(con: sqlite3.Connection) -> list[Prova]:
    """O.4: RREO, RGF e DCA entregues ao Tesouro no prazo (coerência do ente com a fonte nacional)."""
    if not _tabela(con, "siconfi_periodos"):
        return []
    linhas = con.execute("select demonstrativo, exercicio, periodo, rotulo, prazo, situacao from siconfi_periodos"
                         ).fetchall()
    if not linhas:
        return []
    atrasos = [r for r in linhas if r[5] not in ("entregue", "no prazo")]
    if atrasos:
        return [Prova("O.4", "disponibilidade", False, "restritiva",
                      "demonstrativos fiscais não entregues ao SICONFI no prazo: " + ", ".join(r[3] for r in atrasos[:6]),
                      "banco, tabela siconfi_periodos", Nivel.B)]
    return [Prova("O.4", "disponibilidade", True, "restritiva",
                  f"os {len(linhas)} demonstrativos fiscais do período (RREO, RGF e DCA) foram entregues ao SICONFI "
                  "até o prazo legal", "banco, tabela siconfi_periodos", Nivel.B),
            Prova("O.4", "atualidade", True, "restritiva", "entregas dentro do prazo da LC 101/2000",
                  "banco, tabela siconfi_periodos", Nivel.B)]


def _notas_fiscais(con: sqlite3.Connection) -> list[Prova]:
    """O.1: o achado nf_ausente das conferências de compras entra como prova de falta de transparência."""
    try:
        conf = compras.conferir(con)
    except sqlite3.Error:
        return []
    ausentes = [a for a in conf.achados if a.tipo == "nf_ausente" and a.orgao_cnpj != CNPJ_CAMARA]
    if not ausentes:
        return []
    total = round(sum(a.valor for a in ausentes), 2)
    contratos = sum(int(a.dados.get("contratos", 0)) for a in ausentes)
    fmas = [a for a in ausentes if a.orgao_cnpj == CNPJ_FMAS]
    desc = (f"{len(ausentes)} órgãos do Executivo, com {contratos} contratos que somam {reais(total)}, não têm nenhuma "
            "nota fiscal publicada no PNCP nos meses lidos (achado nf_ausente)")
    if fmas:
        desc += f"; entre eles o Fundo Municipal de Assistência Social, com {reais(fmas[0].valor)} em contratos"
    return [Prova("O.1", "disponibilidade", False, "restritiva", desc,
                  "onisciente/conferencias/compras.py, achado nf_ausente", Nivel.F, total)]


# --- Mapa legal --------------------------------------------------------------------------------

ORCAMENTO = {"ppa-": "11.8", "ldo-": "11.9", "loa-": "11.10"}
NAO_LOCALIZADAS = {
    "subsidios-diarias-veiculos-e-telefonia": [("7.2", "disponibilidade", "a tabela de diárias não foi localizada")],
    "decretos-963-967-2022-e-3-182-2023": [("8.8", "disponibilidade",
                                            "os decretos que regulamentam a Lei 14.133/2021 não foram localizados")],
    "plano-municipal-de-saude": [("18.1", "atualidade",
                                  "o Plano Municipal de Saúde 2026-2029 não foi localizado; só o de 2022-2025")],
    "parcerias-com-organizacoes-sociais": [],
}


def do_mapa(mapa: MapaLegal) -> list[Prova]:
    provas: list[Prova] = []
    for n in mapa.normas.values():
        for prefixo, cid in ORCAMENTO.items():
            if n.id.startswith(prefixo) and n.localizada and n.oficial:
                url = n.oficial[0][1]
                provas.append(Prova(cid, "disponibilidade", True, "oficial",
                                    f"{n.norma} publicada no sistema de legislação da Prefeitura (E11: os anexos não "
                                    "foram conferidos, por isso não vale na leitura restritiva)", url, Nivel.D))
    nao = [n for n in mapa.normas.values() if not n.localizada]
    for n in nao:
        for cid, item, desc in NAO_LOCALIZADAS.get(n.id, []):
            provas.append(Prova(cid, item, False, "restritiva", desc + " no levantamento do mapa legal",
                                f"regras/mapa_legal.yml, {n.id}", Nivel.F))
    if nao:
        provas.append(Prova("O.5", "disponibilidade", False, "restritiva",
                            f"{len(nao)} normas locais que regem gasto não foram localizadas em fonte oficial: "
                            + "; ".join(n.norma for n in nao), "regras/mapa_legal.yml", Nivel.F))
    return provas


# --- Relatórios gravados pelos outros motores --------------------------------------------------

# O que falta no Fundo e no Conselho (ausências do parecer) e o critério que a falta derruba (E10).
AUSENCIA_CRITERIO = (
    ("empenhos", "4.3"), ("liquidac", "4.1"), ("pagamentos", "4.1"), ("ordens bancarias", "4.1"),
    ("restos a pagar", "4.1"), ("receita realizada", "3.1"), ("folha de pagamento", "6.2"),
    ("forma de provimento", "6.1"), ("diarias", "7.1"), ("relatorios de viagem", "7.1"),
    ("planos de trabalho", "5.2"), ("prestacoes de contas", "5.2"), ("editais de chamamento", "5.2"),
    ("justificativas de dispensa", "8.4"), ("resolucoes", "19.4"), ("atas de plenaria", "19.4"),
    ("regimento interno", "19.4"), ("decreto de nomeacao", "19.4"), ("apreciacao mensal das contas", "19.4"),
    ("prestacao quadrimestral", "19.4"),
)


def _sem_acento(t: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()


def ausencias_da_pasta(raiz: Path = RAIZ) -> tuple[str | None, list[dict]]:
    """As ausências do parecer mais recente (assistência social), com a competência."""
    pasta = raiz / "relatorios" / "onisciente"
    arquivos = sorted(pasta.glob("panorama_*.json"))
    if not arquivos:
        return None, []
    d = json.loads(arquivos[-1].read_text(encoding="utf-8"))
    return d.get("competencia"), d.get("ausencias") or []


def dos_relatorios(raiz: Path = RAIZ) -> list[Prova]:
    provas: list[Prova] = []
    competencia, ausencias = ausencias_da_pasta(raiz)
    for a in ausencias:
        nome = _sem_acento(a.get("o_que_falta", ""))
        for chave, cid in AUSENCIA_CRITERIO:
            if chave in nome:
                item = "atualidade" if cid == "3.1" else "disponibilidade"
                provas.append(Prova(cid, item, False, "restritiva",
                                    f"{a['o_que_falta']} ({a.get('periodo') or competencia}) não publicado; deveria "
                                    f"estar em {a.get('onde_deveria_estar')}",
                                    f"parecer {competencia}, ausências (relatorios/onisciente/panorama_{competencia}.json)",
                                    Nivel.F))
                break
    etapa = raiz / "relatorios" / "segunda_etapa.json"
    if etapa.exists():
        fontes = json.loads(etapa.read_text(encoding="utf-8")).get("fontes") or {}
        esic = fontes.get("esic")
        if esic and not esic.get("disponivel"):
            quando = json.loads(etapa.read_text(encoding="utf-8")).get("sondado_em", "")
            desc = f"o endereço do e-SIC ({esic.get('url')}) não respondeu na sondagem de {quando}"
            provas.append(Prova("12.3", "disponibilidade", False, "restritiva", desc,
                                "relatorios/segunda_etapa.json", Nivel.F))
            provas.append(Prova("O.6", "disponibilidade", False, "restritiva", desc,
                                "relatorios/segunda_etapa.json", Nivel.F))
    portais = raiz / "config" / "portais.yml"
    if portais.exists():
        cfg = yaml.safe_load(portais.read_text(encoding="utf-8")) or {}
        for grupo in cfg.values():
            if not isinstance(grupo, dict):
                continue
            for item in grupo.values():
                if isinstance(item, dict) and "cmasgyn" in str(item.get("url", "")) and \
                        str(item.get("status", "")).upper() == "DESATUALIZADO":
                    provas.append(Prova("19.4", "atualidade", False, "restritiva",
                                        f"sítio do Conselho marcado como desatualizado: {item.get('nota', '')}".strip(),
                                        "config/portais.yml", Nivel.F))
    return provas


def repasses_fnas(con: sqlite3.Connection | None) -> dict:
    """Dinheiro que o Fundo Nacional mandou ao FMAS, por ano: prova de que há o que prestar contas."""
    if con is None or not _tabela(con, "repasses_fnas"):
        return {"total": 0.0, "por_ano": {}, "linhas": 0, "ultima": None}
    por_ano = {a: round(v, 2) for a, v in con.execute(
        "select substr(competencia,1,4), sum(valor) from repasses_fnas group by 1 order by 1")}
    linhas, ultima = con.execute("select count(*), max(competencia) from repasses_fnas").fetchone()
    return {"total": round(sum(por_ano.values()), 2), "por_ano": por_ano, "linhas": linhas, "ultima": ultima}


def todas(con: sqlite3.Connection | None, mapa: MapaLegal, raiz: Path = RAIZ) -> list[Prova]:
    provas = do_banco(con) if con is not None else []
    return provas + do_mapa(mapa) + dos_relatorios(raiz)
