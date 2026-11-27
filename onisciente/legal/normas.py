"""Norma não localizada vira ofício.

Uma regra sem o texto oficial da norma não pode ser conferida: a falta do texto é
descumprimento de transparência ativa (Lei 12.527/2011, art. 8º; Lei 9.262/2013, art. 7º)
e vira item de ofício, como qualquer outro documento não publicado.

Entram no ofício:

* as normas que o mapa legal dá como não localizadas, alvo a alvo, enquanto a procura
  semanal no índice do Sileg não as achar (sem banco ou sem procura, a norma inteira entra);
* o documento da lista de procuras (o QDD do exercício) que o índice não trouxe;
* a norma localizada cujo endereço oficial no Sileg deixou de abrir (HTTP 404 ou 410).
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

from .. import RAIZ
from ..nucleo.ausencias import Ausencia
from .mapa import MapaLegal, carregar

BANCO = RAIZ / "dados" / "onisciente" / "historico.db"
ONDE = ("Sistema de Legislação de Goiânia (Sileg) e Diário Oficial do Município, em "
        "transparência ativa")
FUNDAMENTO = ("Lei 12.527/2011, art. 8º; Lei municipal 9.262/2013, art. 7º; "
              "Lei Complementar 101/2000, art. 48")
ASSUNTO = "Normas e documentos oficiais não localizados no Sileg nem no Diário Oficial"


def _linhas(banco: Path | str | None, sql: str) -> list[tuple] | None:
    """Linhas de uma tabela do banco histórico, ou None se o banco ou a tabela não existem."""
    caminho = Path(banco) if banco else BANCO
    if not caminho.exists():
        return None
    con = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    try:
        return con.execute(sql).fetchall()
    except sqlite3.OperationalError:
        return None
    finally:
        con.close()


def ausencias(mapa: MapaLegal | None = None, banco: Path | str | None = None,
              procuras: list[dict] | None = None) -> list[Ausencia]:
    """Os itens de ofício das normas e documentos que o sistema não achou."""
    from ..coletores.leis import carregar_procuras

    mapa = mapa or carregar()
    procuras = carregar_procuras() if procuras is None else procuras
    achados: dict[str, dict[str, int]] = {}
    for norma_id, alvo, achada, confirmada in _linhas(
            banco, "SELECT norma_id, alvo, achada, confirmada FROM normas_procura") or []:
        achados.setdefault(norma_id, {})[alvo] = int(bool(achada and confirmada))
    por_id = {p.get("norma") or p.get("documento"): p for p in procuras}
    saida: list[Ausencia] = []

    for n in mapa.nao_localizadas():
        resultado = achados.get(n.id)
        alvos = [a.get("rotulo") for a in (por_id.get(n.id) or {}).get("procurar") or []]
        if not resultado:                      # nunca procurada: a norma inteira vai ao ofício
            saida.append(Ausencia(
                o_que_falta=f"Texto oficial de {n.norma} ({n.assunto})",
                conferencia_impedida=f"{n.parametro} Conferências: {', '.join(n.conferencias)}",
                onde_deveria_estar=ONDE, fundamento=FUNDAMENTO, bloco="Normas"))
            continue
        for alvo in alvos or list(resultado):
            if not resultado.get(alvo):
                saida.append(Ausencia(
                    o_que_falta=f"Texto oficial: {alvo}, parte de {n.norma}",
                    conferencia_impedida=f"{n.parametro} Conferências: {', '.join(n.conferencias)}",
                    onde_deveria_estar=ONDE, fundamento=FUNDAMENTO, bloco="Normas"))

    for p in procuras:
        if not p.get("documento"):
            continue
        resultado = achados.get(p["documento"]) or {}
        if not any(resultado.values()):
            saida.append(Ausencia(
                o_que_falta=p.get("nome") or p["documento"],
                conferencia_impedida=p.get("conferencia") or "execução contra o orçamento",
                onde_deveria_estar=ONDE, fundamento=p.get("fundamento") or FUNDAMENTO,
                bloco="Normas"))

    for norma_id, norma, nome, url, http in _linhas(
            banco, "SELECT norma_id, norma, nome, url, http FROM normas_municipais "
                   "WHERE ok = 0 AND http IN (404, 410)") or []:
        saida.append(Ausencia(
            o_que_falta=f"Texto oficial de {norma} ({nome}), fora do ar no endereço do Sileg {url}",
            conferencia_impedida=f"as regras do mapa legal que citam {norma}",
            onde_deveria_estar=ONDE, fundamento=FUNDAMENTO, bloco="Normas"))
    return saida


def oficio(hoje: date | None = None, **kw) -> str:
    """O ofício pronto, com um item para cada norma ou documento não localizado."""
    from ..lai import oficios_por_orgao

    itens = ausencias(**kw)
    if not itens:
        return ""
    return ("\n\n" + "=" * 72 + "\n\n").join(o.texto(hoje=hoje) for o in oficios_por_orgao(itens, ASSUNTO))
