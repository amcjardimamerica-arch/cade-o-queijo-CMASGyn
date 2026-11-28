"""Agenda própria do Onisciente: as rodadas que o relógio do GitHub liga sozinho.

    python -m onisciente.agenda diaria     # Diário Oficial (SILEG e Querido Diário), PNCP e o detalhe
    python -m onisciente.agenda precos     # painel de preços: o preço nacional do semestre de novo
    python -m onisciente.agenda mensal     # SICONFI, MSC, SIOPS, SIOPE, Tesouro, transferências, FNAS
    python -m onisciente.agenda leis       # normas federais e de Goiânia, procura e ofício do que falta
    python -m onisciente.agenda serie      # estende a série para trás, até o primeiro exercício do alvo
    python -m onisciente.agenda parecer    # parecer da última competência; falha é falha do sistema
    python -m onisciente.agenda pagina     # refaz só a página da agenda (docs/onisciente/agenda.html)

Toda coleta da agenda é incremental: soma ao banco ``dados/onisciente/historico.db`` e nunca
refaz os dois anos. Dois jeitos de somar, conforme o motor:

* **janela**: o motor roda num banco à parte só com os meses da janela (os últimos meses, ou
  o trecho novo da série), e o resultado entra no banco principal trocando apenas as linhas
  desses meses (ou desses períodos e exercícios). O que está fora da janela fica como estava.
* **continuar**: os motores do PNCP já continuam de onde pararam. A agenda alarga o intervalo
  do banco para cobrir a janela, reabre só os meses da janela (que ainda recebem publicações)
  e liga o motor sobre o banco principal com ``somar``.

Cada rodada deixa o resultado em ``relatorios/onisciente/agenda_estado.json``, na página
``docs/onisciente/agenda.html`` e no estado de coleta do sistema (``estado/onisciente_coleta.json``),
de onde o parecer tira a ficha vermelha de "coleta parada". Rodada que quebra sai com código 1:
o fluxo do GitHub fica vermelho e o registro fica visível.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sqlite3
import sys
import tempfile
import tomllib
import traceback
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from . import RAIZ, historico, partes, rastreio
from .coletores import base as coleta

BANCO = historico.BANCO
ESTADO = RAIZ / "relatorios" / "onisciente" / "agenda_estado.json"
PAGINA = RAIZ / "docs" / "onisciente" / "agenda.html"
TEMPESTIVIDADE = RAIZ / "relatorios" / "onisciente" / "tempestividade.json"
OFICIO_NORMAS = RAIZ / "relatorios" / "onisciente" / "oficio_normas.txt"
INICIO_PADRAO = "2019-01"


# --- As rodadas ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Grupo:
    motores: tuple[str, ...]
    janela: int                   # meses até o mês corrente (inclusive) que a rodada lê de novo
    modo: str = "janela"          # janela | continuar
    reabrir: tuple[str, ...] = ()  # o que reabrir no modo continuar: meses, precos


@dataclass(frozen=True)
class Rodada:
    nome: str
    titulo: str
    quando: str                   # em palavras; o cron fica no fluxo do GitHub
    ciclo_dias: int
    grupos: tuple[Grupo, ...] = ()
    fluxo: str = ""


RODADAS: dict[str, Rodada] = {r.nome: r for r in (
    Rodada("diaria", "Diário Oficial e compras públicas", "todo dia, 23h em Goiânia", 1, (
        Grupo(("sileg", "querido_diario"), janela=2),
        Grupo(("pncp", "pncp_detalhe"), janela=2, modo="continuar", reabrir=("meses",)),
        Grupo(("sancoes",), janela=1),        # CEIS e CNEP: o arquivo do dia substitui o anterior
        Grupo(("execucao_goiania",), janela=2),  # empenhos e pagamentos; o próprio motor continua de onde parou
    ), fluxo="onisciente-agenda-diaria.yml"),
    Rodada("precos", "Painel de preços e repasses federais", "toda quarta-feira, 9h em Goiânia", 7, (
        Grupo(("pncp_detalhe",), janela=1, modo="continuar", reabrir=("precos",)),
        Grupo(("fns", "fnde", "transferegov"), janela=3),
    ), fluxo="onisciente-agenda-precos.yml"),
    Rodada("mensal", "Contas do Tesouro, saúde, educação e repasses", "todo dia 2, 6h em Goiânia", 31, (
        Grupo(("siconfi", "siops", "siope", "fnas"), janela=12),
        Grupo(("msc", "tesouro", "transferencias", "fontes"), janela=3),
        Grupo(("economia_go",), janela=3),    # cota-parte do Estado (ICMS e IPVA)
        Grupo(("cnpj",), janela=1),           # base mensal da Receita; nos outros meses, só os CNPJs novos
    ), fluxo="onisciente-agenda-mensal.yml"),
    Rodada("leis", "Leis federais e de Goiânia e decisões dos tribunais de contas", "toda segunda-feira, 9h em Goiânia", 7, (
        Grupo(("normas",), janela=1),
        Grupo(("tcu", "tcm"), janela=1),
        Grupo(("impedimentos",), janela=1),   # CEPIM e inidôneos do TCU
    ), fluxo="onisciente-agenda-leis.yml"),
    Rodada("serie", "Série histórica desde o primeiro exercício", "todo dia 10, 13h em Goiânia", 31, (
        Grupo(("siconfi", "siops", "siope", "fnas", "msc", "tesouro", "transferencias", "sileg",
               "querido_diario", "fns", "fnde", "transferegov", "economia_go"), janela=12),
        # O detalhe das compras do trecho novo fica com a rodada diária, que lê o banco inteiro.
        Grupo(("pncp",), janela=12, modo="continuar", reabrir=("meses",)),
    ), fluxo="onisciente-agenda-serie.yml"),
    Rodada("parecer", "Parecer da última competência", "todo domingo e todo dia 5, 12h em Goiânia", 7,
           fluxo="onisciente-agenda-parecer.yml"),
)}
PASSO_DA_SERIE = 12               # meses que cada rodada da série acrescenta para trás


# --- Calendário ----------------------------------------------------------------------------

def _mes(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def somar_meses(mes: str, n: int) -> str:
    a, m = map(int, mes.split("-"))
    total = a * 12 + (m - 1) + n
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def janela(hoje: date, meses: int) -> tuple[str, str]:
    """Os ``meses`` meses que terminam no mês de ``hoje`` (inclusive)."""
    fim = _mes(hoje)
    return somar_meses(fim, -(max(1, meses) - 1)), fim


def inicio_da_serie(alvo: Path | None = None) -> str:
    """Primeiro mês da série: janeiro do ``primeiro_exercicio`` do alvo (2019 em Goiânia)."""
    caminho = alvo or (RAIZ / "alvos" / "goiania.toml")
    try:
        ano = int(tomllib.loads(caminho.read_text(encoding="utf-8")).get("primeiro_exercicio"))
        return f"{ano:04d}-01"
    except (OSError, TypeError, ValueError):
        return INICIO_PADRAO


def intervalo_do_banco(banco: historico.Banco) -> tuple[str, str] | None:
    valor = dict(banco.consultar("SELECT chave, valor FROM meta")).get("intervalo")
    if not valor or " a " not in valor:
        return None
    a, b = valor.split(" a ", 1)
    return a.strip(), b.strip()


def _uniao(atual: tuple[str, str] | None, novo: tuple[str, str]) -> tuple[str, str]:
    if not atual:
        return novo
    return min(atual[0], novo[0]), max(atual[1], novo[1])


# --- Somar uma janela ao banco principal ---------------------------------------------------

# Linhas que uma janela substitui, tabela a tabela: as do banco principal com a mesma chave de
# alguma linha nova saem antes de as novas entrarem. Tabela com chave primária troca linha a
# linha; chave vazia é retrato inteiro (a tabela toda é refeita a cada leitura).
CHAVES_DA_JANELA: dict[str, tuple[str, ...]] = {
    "coletas": ("motor", "mes"),
    "siconfi_periodos": ("demonstrativo", "exercicio", "periodo"),
    "siconfi_anexos": ("demonstrativo", "exercicio", "periodo"),
    "siconfi_itens": ("demonstrativo", "exercicio", "periodo"),
    "siconfi_entregas": ("exercicio",),
    "diario_oficial": ("fonte", "mes"),
    "diario_oficial_mes": ("fonte", "mes"),
    "diario_oficial_dias": ("fonte", "mes"),
    "repasses_fnas": ("competencia",),
    "transferencias_tesouro": ("mes",),
    "transferencias_federais": ("mes",),
    "msc_itens": ("mes",),
    "msc_meses": ("mes",),
    "externos_periodos": ("fonte", "exercicio", "periodo"),
    "externos_itens": ("fonte", "exercicio", "periodo"),
    "fontes": ("url",),
    "normas": ("caminho",),
    "normas_municipais": ("url",),
    "normas_procura": ("norma_id", "alvo"),
}
# Linha nova que só registra que a fonte não respondeu (falha do sistema, não dado novo): ela
# não apaga o que o banco já tinha da mesma chave. Sem linha antiga, entra para o buraco aparecer.
FALHA_DA_JANELA: dict[str, str] = {
    "siconfi_periodos": "situacao = 'falha'",
    "msc_meses": "situacao IN ('falha', 'formato')",
    "externos_periodos": "situacao IN ('falha', 'formato')",
    "diario_oficial_mes": "erro IS NOT NULL",
    "normas": "ok = 0 AND COALESCE(erro, '') NOT LIKE 'HTTP 4%'",
    "normas_municipais": "ok = 0 AND (http IS NULL OR http >= 500)",
    "normas_procura": "achada = 0 AND erro IS NOT NULL",
}
# Chaves de ``meta`` que são listas de meses lidos: somam-se em vez de trocar.
META_DE_MESES = ("tesouro_meses", "transferencias_meses", "fnas_do_arquivo")
META_DO_BANCO = ("intervalo", "rodada", "hoje")


def _colunas(con: sqlite3.Connection, tabela: str, esquema: str = "main") -> list[str]:
    return [c[1] for c in con.execute(f"PRAGMA {esquema}.table_info({tabela})")]


def _tem_chave_primaria(con: sqlite3.Connection, tabela: str, esquema: str = "main") -> bool:
    return any(c[5] for c in con.execute(f"PRAGMA {esquema}.table_info({tabela})"))


def _chave(con: sqlite3.Connection, tabela: str) -> tuple[str, ...] | None:
    """A chave da janela de uma tabela; None quando a tabela troca linha a linha (chave primária)."""
    if tabela in CHAVES_DA_JANELA:
        return CHAVES_DA_JANELA[tabela]
    if _tem_chave_primaria(con, tabela, "novo"):
        return None
    colunas = set(_colunas(con, tabela, "novo"))
    for chave in (("fonte", "mes"), ("mes",), ("competencia",), ("fonte", "exercicio", "periodo"),
                  ("demonstrativo", "exercicio", "periodo"), ("exercicio", "periodo")):
        if set(chave) <= colunas:
            return chave
    return ()                     # sem chave conhecida: retrato inteiro


def _mesclar_lista(antiga, nova, meses_da_janela: set[str]):
    if isinstance(antiga, list) and isinstance(nova, list):
        fora = [x for x in antiga if str(x) not in meses_da_janela and x not in nova]
        return sorted(fora + nova, key=str)
    if isinstance(antiga, dict) and isinstance(nova, dict):
        return {k: _mesclar_lista(antiga.get(k, []), nova.get(k, []), meses_da_janela)
                for k in sorted(set(antiga) | set(nova))}
    return nova


def somar_janela(principal: historico.Banco, novo: Path, meses_da_janela: list[str]) -> dict[str, int]:
    """Põe no banco principal o que a rodada da janela coletou, trocando só o que ela releu."""
    con = principal.con
    con.execute("ATTACH DATABASE ? AS novo", (str(novo),))
    trocadas: dict[str, int] = {}
    try:
        tabelas = [t for (t,) in con.execute(
            "SELECT name FROM novo.sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
        # Cada tabela é gravada no esquema onde está no principal: o banco ou uma parte (precos.db,
        # sancoes.db; onisciente.partes). Tabela nova de uma parte nasce no arquivo da parte.
        existentes = partes.tabelas(con)
        for tabela in tabelas:
            if tabela == "meta" or tabela.startswith(rastreio.PREFIXO):
                continue          # o rastreio da janela entra pelo importar_selos, na rodada da soma
            if not con.execute(f"SELECT 1 FROM novo.{tabela} LIMIT 1").fetchone():
                continue          # a janela não trouxe nada para esta tabela: o principal fica como está
            if tabela not in existentes:
                [(sql,)] = con.execute("SELECT sql FROM novo.sqlite_master WHERE name = ?", (tabela,))
                parte = partes.PARTE_DA_TABELA.get(tabela)
                if parte in partes.anexadas(con):
                    sql = re.sub(r"^CREATE TABLE (IF NOT EXISTS )?\"?(\w+)\"?", f"CREATE TABLE {parte}.\\2", sql,
                                 count=1)
                con.execute(sql)
                existentes[tabela] = parte if parte in partes.anexadas(con) else "main"
            esq = existentes[tabela]
            colunas_novo = _colunas(con, tabela, "novo")
            colunas = [c for c in _colunas(con, tabela, esq) if c in colunas_novo]
            lista = ", ".join(colunas)
            chave = _chave(con, tabela)
            falha = FALHA_DA_JANELA.get(tabela)
            filtro = ""
            if chave == ():
                con.execute(f"DELETE FROM {esq}.{tabela}")
            elif chave:
                cols = ", ".join(chave)
                boas = f"SELECT DISTINCT {cols} FROM novo.{tabela}" + (f" WHERE NOT ({falha})" if falha else "")
                con.execute(f"DELETE FROM {esq}.{tabela} WHERE ({cols}) IN ({boas})")
                if falha:
                    filtro = (f" WHERE NOT ({falha}) OR ({cols}) NOT IN "
                              f"(SELECT {cols} FROM {esq}.{tabela})")
            cur = con.execute(f"INSERT OR REPLACE INTO {esq}.{tabela} ({lista}) "
                              f"SELECT {lista} FROM novo.{tabela}{filtro}")
            trocadas[tabela] = cur.rowcount
        janela_meses = set(meses_da_janela)
        antigos = dict(con.execute("SELECT chave, valor FROM main.meta"))
        for chave, valor in con.execute("SELECT chave, valor FROM novo.meta").fetchall():
            if chave in META_DO_BANCO:
                continue
            if chave in META_DE_MESES and antigos.get(chave):
                try:
                    valor = json.dumps(_mesclar_lista(json.loads(antigos[chave]), json.loads(valor),
                                                      janela_meses), ensure_ascii=False)
                except ValueError:
                    pass
            con.execute("INSERT OR REPLACE INTO main.meta (chave, valor) VALUES (?, ?)", (chave, valor))
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.execute("DETACH DATABASE novo")
    return trocadas


# --- Reabrir meses no que os motores do PNCP já deram por lidos ------------------------------

def _meta_json(banco: historico.Banco, chave: str, padrao):
    valor = dict(banco.consultar("SELECT chave, valor FROM meta")).get(chave)
    try:
        return json.loads(valor) if valor else padrao
    except ValueError:
        return padrao


def _guardar_meta(banco: historico.Banco, chave: str, valor) -> None:
    banco.inserir("meta", {"chave": chave, "valor": json.dumps(valor, ensure_ascii=False)})


def reabrir_meses(banco: historico.Banco, meses_reabertos: list[str]) -> dict[str, int]:
    """Tira os meses dados do que o PNCP e o detalhe marcaram como lido por inteiro.

    O mês que terminou ontem ainda recebe publicações com data dele; o ano que ganha meses na
    série precisa ser lido de novo mês a mês. Só esses meses (e os anos deles, na marca
    anual dos itens) voltam a ser lidos; o resto do banco continua de onde parou.
    """
    meses_set = set(meses_reabertos)
    anos = {m[:4] for m in meses_reabertos}
    janelas = _meta_json(banco, "pncp_janelas", [])
    novas, tiradas = [], 0
    for j in janelas:
        ficam = [m for m in j.get("meses") or [] if m not in meses_set]
        tiradas += len(j.get("meses") or []) - len(ficam)
        if ficam:
            novas.append({**j, "meses": ficam})
    if janelas:
        _guardar_meta(banco, "pncp_janelas", novas)
    procura = _meta_json(banco, "pncp_procura", None)
    if procura is not None:
        _guardar_meta(banco, "pncp_procura", [m for m in procura if m not in meses_set])
    lidos = _meta_json(banco, "pncp_detalhe_lidos", None)
    reabertos = 0
    if lidos is not None:
        def fica(k: str) -> bool:
            partes = k.split()
            if partes[0] in ("cobrancas", "amparos", "itens") and len(partes) >= 3:
                if partes[2] in meses_set:
                    return False
                if partes[0] == "itens" and partes[2] in anos:
                    return False
            return True
        mantidos = [k for k in lidos if fica(k)]
        reabertos = len(lidos) - len(mantidos)
        _guardar_meta(banco, "pncp_detalhe_lidos", sorted(mantidos))
    banco.con.commit()
    return {"janelas_reabertas": tiradas, "detalhe_reaberto": reabertos}


def semestres_recentes(hoje: date, quantos: int = 2) -> list[str]:
    s = f"{hoje.year}-{1 if hoje.month <= 6 else 2}"
    saida = [s]
    while len(saida) < quantos:
        ano, n = map(int, saida[-1].split("-"))
        saida.append(f"{ano - 1}-2" if n == 1 else f"{ano}-1")
    return saida


def reabrir_precos(banco: historico.Banco, hoje: date) -> int:
    """O preço nacional do semestre corrente e do anterior muda com as compras novas do país:
    a marca de lido desses semestres sai, e o painel de preços é lido de novo."""
    semestres = set(semestres_recentes(hoje))
    lidos = _meta_json(banco, "pncp_detalhe_lidos", None)
    if lidos is None:
        return 0
    mantidos = [k for k in lidos if not (k.startswith("preco ") and k.rsplit(" ", 1)[-1] in semestres)]
    _guardar_meta(banco, "pncp_detalhe_lidos", sorted(mantidos))
    banco.con.commit()
    return len(lidos) - len(mantidos)


# --- Rodar ----------------------------------------------------------------------------------

def _abrir_ou_criar(caminho: Path, intervalo: tuple[str, str]) -> historico.Banco:
    if Path(caminho).exists():
        return historico.Banco.abrir(caminho)
    banco = historico.Banco(caminho)
    banco.inserir("meta", {"chave": "intervalo", "valor": f"{intervalo[0]} a {intervalo[1]}"})
    banco.con.commit()
    return banco


def _motores_quebrados(banco: historico.Banco, motores) -> dict[str, str]:
    meta = dict(banco.consultar("SELECT chave, valor FROM meta"))
    saida = {}
    for m in motores:
        try:
            erro = json.loads(meta.get(f"motor:{m}") or "{}").get("erro")
        except ValueError:
            erro = None
        if erro:
            saida[m] = erro
    return saida


def _rodada_da_janela(principal: historico.Banco, grupo: Grupo, temporario: Path, janela_: str) -> int | None:
    """Abre no banco principal a rodada da soma da janela, com o resumo da rodada da janela."""
    try:
        con = sqlite3.connect(f"file:{temporario}?mode=ro", uri=True)
        try:
            da_janela = rastreio.verificar_cadeia(con)["ultima"]
        finally:
            con.close()
        return rastreio.abrir_rodada(principal.con, list(grupo.motores), "janela",
                                     detalhe={"janela": janela_, "rodada_da_janela": da_janela})
    except Exception as e:  # noqa: BLE001 (o rastreio não derruba a soma; a verificação aponta)
        print(f"rastreio: rodada da janela não aberta: {type(e).__name__}: {e}", flush=True)
        return None


def coletar_grupo(grupo: Grupo, intervalo: tuple[str, str], *, caminho: Path = BANCO, hoje: date,
                  **kw) -> dict:
    """Roda um grupo de motores sobre ``intervalo`` e soma o resultado ao banco principal."""
    desde, ate = intervalo
    meses_janela = historico.meses(desde, ate)
    resultado = {"motores": list(grupo.motores), "modo": grupo.modo, "janela": f"{desde} a {ate}"}
    if grupo.modo == "janela":
        with tempfile.TemporaryDirectory(prefix="onisciente-janela-") as pasta:
            temporario = Path(pasta) / "janela.db"
            novo = historico.rodar(desde, ate, motores=grupo.motores, caminho=temporario, hoje=hoje, **kw)
            quebrados = _motores_quebrados(novo, grupo.motores)
            novo.con.commit()
            novo.con.close()
            principal = _abrir_ou_criar(caminho, intervalo)
            try:
                uniao = _uniao(intervalo_do_banco(principal), intervalo)
                # A soma da janela é uma rodada do banco principal: os selos e as origens que a janela
                # gravou vêm junto, e a raiz da rodada cobre o que entrou.
                rodada = _rodada_da_janela(principal, grupo, temporario, f"{desde} a {ate}")
                resultado["linhas"] = somar_janela(principal, temporario, meses_janela)
                principal.inserir("meta", {"chave": "intervalo", "valor": f"{uniao[0]} a {uniao[1]}"})
                principal.con.commit()
                if rodada is not None:
                    rastreio.importar_selos(principal.con, temporario, rodada)
                    resultado["rastreio"] = rastreio.fechar_rodada(principal.con, rodada)["hash"]
            finally:
                principal.fechar()
    else:
        principal = _abrir_ou_criar(caminho, intervalo)
        uniao = _uniao(intervalo_do_banco(principal), intervalo)
        principal.inserir("meta", {"chave": "intervalo", "valor": f"{uniao[0]} a {uniao[1]}"})
        if "meses" in grupo.reabrir:
            resultado["reaberto"] = reabrir_meses(principal, meses_janela)
        if "precos" in grupo.reabrir:
            resultado["precos_reabertos"] = reabrir_precos(principal, hoje)
        principal.con.commit()
        principal.con.close()
        banco = historico.rodar(uniao[0], uniao[1], motores=grupo.motores, caminho=caminho, hoje=hoje,
                                somar=True, **kw)
        quebrados = _motores_quebrados(banco, grupo.motores)
        banco.fechar()
        resultado["intervalo_do_banco"] = f"{uniao[0]} a {uniao[1]}"
    resultado["quebrados"] = quebrados
    return resultado


def proxima_janela_da_serie(caminho: Path, inicio: str, passo: int = PASSO_DA_SERIE) -> tuple[str, str] | None:
    """O trecho que a próxima rodada da série acrescenta antes do começo atual do banco."""
    if not Path(caminho).exists():
        return None
    banco = historico.Banco.abrir(caminho)
    try:
        atual = intervalo_do_banco(banco)
    finally:
        banco.con.close()
    if not atual or atual[0] <= inicio:
        return None
    fim = somar_meses(atual[0], -1)
    comeco = max(inicio, somar_meses(atual[0], -passo))
    return comeco, fim


def coletar(nome: str, *, caminho: Path = BANCO, hoje: date | None = None, inicio: str | None = None,
            **kw) -> dict:
    """Roda uma rodada de coleta da agenda e devolve o resumo (sem gravar o estado)."""
    rodada = RODADAS[nome]
    hoje = hoje or date.today()
    resumo = {"rodada": nome, "grupos": [], "quebrados": {}}
    if nome == "serie":
        trecho = proxima_janela_da_serie(caminho, inicio or inicio_da_serie())
        if trecho is None:
            resumo["nota"] = f"série completa desde {inicio or inicio_da_serie()}"
            return resumo
        resumo["trecho"] = f"{trecho[0]} a {trecho[1]}"
    for grupo in rodada.grupos:
        intervalo = trecho if nome == "serie" else janela(hoje, grupo.janela)
        r = coletar_grupo(grupo, intervalo, caminho=caminho, hoje=hoje, **kw)
        resumo["grupos"].append(r)
        resumo["quebrados"].update(r["quebrados"])
    return resumo


# --- Depois da coleta: tempestividade e ofício das normas ------------------------------------

def gravar_tempestividade(caminho: Path = BANCO, destino: Path = TEMPESTIVIDADE, hoje: date | None = None) -> dict:
    from . import tempo
    from .legal.mapa import carregar
    hoje = hoje or date.today()
    banco = historico.Banco.abrir(caminho)
    try:
        itens = tempo.tempestividade_dos_documentos(banco, hoje, carregar())
        intervalo = intervalo_do_banco(banco)
        publicacao = [tempo.publicacao_do_mes(banco, m) for m in
                      (historico.meses(*intervalo) if intervalo else [])]
    finally:
        banco.con.close()
    dados = {"gerado_em": hoje.isoformat(), "indice": tempo.indice_de_tempestividade(itens),
             "documentos": itens, "publicacao_do_diario": publicacao}
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(dados, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return dados


def gravar_oficio_normas(caminho: Path = BANCO, destino: Path = OFICIO_NORMAS, hoje: date | None = None) -> int:
    from .legal import normas
    itens = normas.ausencias(banco=caminho)
    destino.parent.mkdir(parents=True, exist_ok=True)
    texto = normas.oficio(hoje=hoje, banco=caminho) if itens else ""
    destino.write_text((texto or "Nenhuma norma ou documento por localizar nesta rodada.") + "\n",
                       encoding="utf-8")
    return len(itens)


def registrar_ctresb(caminho: Path = BANCO, estado_coleta: Path = coleta.ESTADO) -> None:
    """A conferência das normas federais (ctresb/leis) no estado de coleta do sistema, como fazia
    o passo mensal ``python -m onisciente coletar leis``, agora a cada semana."""
    from .coletores.leis import RAW_CTRESB
    banco = historico.Banco.abrir(caminho)
    try:
        linhas = banco.consultar("SELECT caminho, ok FROM normas")
    finally:
        banco.con.close()
    if not linhas:
        return
    falhas = [c for c, ok in linhas if not ok]
    coleta.registrar("ctresb", coleta.Leitura(not falhas, RAW_CTRESB, erro="; ".join(falhas)),
                     caminho=estado_coleta, ciclo_dias=7)


# --- Estado e página ---------------------------------------------------------------------------

def carregar_estado(caminho: Path = ESTADO) -> dict:
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"rodadas": {}}


def registrar(nome: str, ok: bool, *, erro: str | None = None, resumo: dict | None = None,
              inicio: str | None = None, caminho: Path = ESTADO,
              estado_coleta: Path = coleta.ESTADO) -> dict:
    """Guarda o resultado da rodada no estado da agenda e no estado de coleta do sistema."""
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    estado = carregar_estado(caminho)
    item = estado.setdefault("rodadas", {}).setdefault(nome, {})
    item.update(ultima_tentativa=agora, inicio=inicio or agora, ok=bool(ok), erro=erro or None,
                resumo=resumo or {})
    if ok:
        item["ultimo_sucesso"] = agora
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(estado, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    rodada = RODADAS.get(nome)
    coleta.registrar(f"agenda-{nome}", coleta.Leitura(bool(ok), f"agenda:{nome}", erro=erro or ""),
                     caminho=estado_coleta, ciclo_dias=rodada.ciclo_dias if rodada else 1)
    return estado


def pagina(estado: dict | None = None, hoje: date | None = None) -> str:
    """A página da agenda: cada rodada, quando roda, a última tentativa e o resultado."""
    estado = estado if estado is not None else carregar_estado()
    hoje = hoje or date.today()
    linhas = []
    for nome, r in RODADAS.items():
        item = (estado.get("rodadas") or {}).get(nome) or {}
        if not item:
            situacao, classe = "ainda não rodou", "espera"
        elif item.get("ok"):
            situacao, classe = "funcionou", "ok"
        else:
            situacao, classe = "falhou: falha do sistema", "falha"
        tentativa = (item.get("ultima_tentativa") or "")[:16].replace("T", " ")
        sucesso = (item.get("ultimo_sucesso") or "")[:16].replace("T", " ")
        erro = item.get("erro") or ""
        linhas.append(
            f"<tr class='{classe}'><td><strong>{html.escape(r.titulo)}</strong><br>"
            f"<small>{html.escape(nome)} ({html.escape(r.fluxo)})</small></td>"
            f"<td>{html.escape(r.quando)}</td><td>{html.escape(tentativa or 'nunca')}</td>"
            f"<td>{html.escape(sucesso or 'nunca')}</td>"
            f"<td>{html.escape(situacao)}{('<br><small>' + html.escape(erro[:400]) + '</small>') if erro else ''}"
            f"</td></tr>")
    falhas = [n for n, i in (estado.get("rodadas") or {}).items() if i and not i.get("ok")]
    aviso = (f"<p class='alerta'>{len(falhas)} rodada(s) com falha na última tentativa: "
             f"{html.escape(', '.join(falhas))}. Falha de coleta ou de parecer é falha do próprio "
             f"sistema e aparece em vermelho no parecer.</p>" if falhas else
             "<p>Todas as rodadas que já rodaram funcionaram na última tentativa.</p>")
    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agenda do Onisciente</title>
<style>
body{{font-family:system-ui,sans-serif;margin:0 auto;max-width:960px;padding:16px;color:#1b1b1b;background:#fff}}
table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #ddd;padding:8px;text-align:left;vertical-align:top}}
tr.ok td:last-child{{color:#176f2c}}tr.falha td:last-child{{color:#b3261e;font-weight:600}}tr.espera td:last-child{{color:#6b6b6b}}
.alerta{{background:#fdecea;border-left:4px solid #b3261e;padding:8px 12px}}small{{color:#555}}
@media (prefers-color-scheme: dark){{body{{background:#111;color:#eee}}td,th{{border-color:#333}}small{{color:#aaa}}
.alerta{{background:#3a1512}}tr.ok td:last-child{{color:#6fd08a}}tr.falha td:last-child{{color:#ff8a80}}}}
</style></head><body>
<h1>Agenda do Onisciente</h1>
<p>O sistema roda sozinho, no relógio do GitHub. Cada coleta soma ao banco o que é novo e nunca refaz
a série inteira. Página refeita em {hoje.strftime('%d/%m/%Y')}.</p>
{aviso}
<table><thead><tr><th>Rodada</th><th>Quando</th><th>Última tentativa (UTC)</th><th>Último sucesso (UTC)</th>
<th>Resultado</th></tr></thead><tbody>
{chr(10).join(linhas)}
</tbody></table>
<p><a href="index.html">Pareceres e banco histórico</a></p>
</body></html>
"""


def gravar_pagina(destino: Path = PAGINA, estado: dict | None = None) -> Path:
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(pagina(estado), encoding="utf-8")
    return destino


# --- Linha de comando ---------------------------------------------------------------------------

def _resumo_curto(resumo: dict) -> dict:
    """O que vai para o estado: sem as contagens de linha de cada tabela."""
    saida = {k: v for k, v in resumo.items() if k != "grupos"}
    saida["grupos"] = [{k: v for k, v in g.items() if k != "linhas"} for g in resumo.get("grupos", [])]
    return saida


def executar(nome: str, *, caminho: Path = BANCO, hoje: date | None = None, estado: Path = ESTADO,
             estado_coleta: Path = coleta.ESTADO, pagina_destino: Path = PAGINA, **kw) -> int:
    """Roda a rodada, registra o resultado (sucesso ou falha) e devolve o código de saída."""
    inicio = datetime.now(timezone.utc).isoformat(timespec="seconds")
    erro, resumo = None, {}
    try:
        if nome == "parecer":
            from .__main__ import main as onisciente
            codigo = onisciente(["parecer"])
            if codigo:
                erro = f"o parecer saiu com o código {codigo}"
        elif nome == "pagina":
            gravar_pagina(pagina_destino, carregar_estado(estado))
            return 0
        else:
            resumo = coletar(nome, caminho=caminho, hoje=hoje, **kw)
            if resumo.get("quebrados"):
                erro = "; ".join(f"motor {m} quebrou: {e}" for m, e in resumo["quebrados"].items())
            if nome in ("mensal", "serie") and Path(caminho).exists():
                t = gravar_tempestividade(caminho, hoje=hoje)
                resumo["tempestividade"] = t["indice"]
            if nome == "leis" and Path(caminho).exists():
                resumo["oficio_normas_itens"] = gravar_oficio_normas(caminho, hoje=hoje)
                registrar_ctresb(caminho, estado_coleta)
    except Exception as e:  # noqa: BLE001 (a falha vira registro visível e código 1)
        erro = f"{type(e).__name__}: {e}"[:600]
        traceback.print_exc()
    registrar(nome, erro is None, erro=erro, resumo=_resumo_curto(resumo), inicio=inicio, caminho=estado,
              estado_coleta=estado_coleta)
    gravar_pagina(pagina_destino, carregar_estado(estado))
    print(f"rodada {nome}: {'ok' if erro is None else 'FALHOU: ' + erro}", flush=True)
    return 0 if erro is None else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="onisciente.agenda", description="Rodadas agendadas do Onisciente.")
    p.add_argument("rodada", choices=[*RODADAS, "pagina"])
    p.add_argument("--brutos", help="pasta para guardar as respostas cruas")
    p.add_argument("--inicio", help="primeiro mês da série (padrão: primeiro_exercicio do alvo)")
    args = p.parse_args(argv)
    kw = {}
    if args.brutos:
        kw["brutos"] = Path(args.brutos)
    if args.inicio:
        if not re.fullmatch(r"\d{4}-\d{2}", args.inicio):
            p.error("--inicio no formato AAAA-MM")
        kw["inicio"] = args.inicio
    return executar(args.rodada, **kw)


if __name__ == "__main__":
    sys.exit(main())
