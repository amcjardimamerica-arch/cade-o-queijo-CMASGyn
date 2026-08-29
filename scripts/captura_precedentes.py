#!/usr/bin/env python3
"""Precedentes de transparência em outros estados — notícias, decisões,
recomendações e Termos de Ajustamento de Conduta.

Pasta separada do corpus de leis (referencias/transparencia/), por desenho:
lei fundamenta parecer; precedente direciona pesquisa e sugere procedimento
já testado em outro lugar — TAC por Diário Oficial que não circula,
recomendação de Ministério Público por portal desatualizado, decisão de
Tribunal de Contas por piso de conselho descumprido.

Custo de tokens: zero na coleta. A captura é por RSS do Google Notícias
(consulta determinística), a triagem primária é por palavra-chave (camada 0).
Quando ANTHROPIC_API_KEY existir, uma única passada de Haiku pontua a
relevância dos itens novos (tarefa triar_precedente_transparencia do
roteador) — e nada mais: julgamento de mérito fica com o ciclo dominical.

Uso: python3 scripts/captura_precedentes.py
Saída: referencias/transparencia/precedentes.json e AAAA-MM.md
"""
from __future__ import annotations
import json, re, sys, time, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PASTA = RAIZ / "referencias" / "transparencia"

CONSULTAS = [
    '"termo de ajustamento de conduta" transparência "diário oficial"',
    '"termo de ajustamento de conduta" "portal da transparência" prefeitura',
    'ministério público recomendação "diário oficial" "não circula" OR "sem publicação"',
    'tribunal de contas "portal da transparência" desatualizado município',
    '"conselho municipal de assistência social" repasse bloqueio transparência',
    'ação civil pública "portal da transparência" município condenação',
    'IGD SUAS "controle social" percentual conselho descumprimento',
,
    'acórdão tribunal de contas "assistência social" fundo municipal irregularidade',
    'TCE OR TCM julgamento contas prefeitura "fundo de assistência social"',
    'acórdão "conselho municipal" "controle social" repasse irregular',
]

RELEVANTES = re.compile(
    r"transpar[êe]ncia|di[áa]rio oficial|portal|ajustamento de conduta|"
    r"recomenda[çc][ãa]o|tribunal de contas|minist[ée]rio p[úu]blico|"
    r"conselho|IGD", re.I)
RUIDO = re.compile(r"futebol|celebridade|novela|loteria", re.I)

UA = {"User-Agent": "AMC-Jardim-America-Vigilancia/1.0 (fiscalizacao publica)"}


def rss(consulta: str) -> list[dict]:
    url = ("https://news.google.com/rss/search?q="
           + urllib.parse.quote(consulta) + "&hl=pt-BR&gl=BR&ceid=BR:pt-419")
    try:
        with urllib.request.urlopen(
                urllib.request.Request(url, headers=UA), timeout=30) as r:
            raiz = ET.fromstring(r.read())
    except Exception as e:
        print(f"  [aviso] consulta falhou ({e}): {consulta[:50]}",
              file=sys.stderr)
        return []
    itens = []
    for it in raiz.iter("item"):
        t = (it.findtext("title") or "").strip()
        itens.append({
            "titulo": t,
            "url": (it.findtext("link") or "").strip(),
            "data": (it.findtext("pubDate") or "").strip(),
            "fonte": (it.findtext("source") or "").strip(),
            "consulta": consulta,
        })
    return itens


def triagem_camada0(itens: list[dict]) -> list[dict]:
    vistos, saida = set(), []
    for it in itens:
        chave = it["url"] or it["titulo"]
        if chave in vistos or not it["titulo"]:
            continue
        vistos.add(chave)
        if RUIDO.search(it["titulo"]):
            continue
        if RELEVANTES.search(it["titulo"]):
            saida.append(it)
    return saida


def triagem_haiku(itens: list[dict]) -> list[dict]:
    """Opcional: só roda com chave presente, e só sobre itens novos."""
    try:
        sys.path.insert(0, str(RAIZ / "src"))
        from roteador_ia import chamar  # type: ignore
    except Exception:
        return itens
    import os
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return itens
    for it in itens:
        try:
            r = chamar("triar_precedente_transparencia", it["titulo"])
            it["relevancia_haiku"] = (r or "").strip()[:40]
        except Exception:
            break
        time.sleep(0.3)
    return itens


def main():
    PASTA.mkdir(parents=True, exist_ok=True)
    arq = PASTA / "precedentes.json"
    base = (json.loads(arq.read_text(encoding="utf-8"))
            if arq.exists() else {"itens": []})
    conhecidos = {i["url"] for i in base["itens"]}
    novos = []
    for q in CONSULTAS:
        novos += rss(q)
        time.sleep(1.0)
    novos = [i for i in triagem_camada0(novos) if i["url"] not in conhecidos]
    novos = triagem_haiku(novos)
    for i in novos:
        i["capturado_em"] = date.today().isoformat()
        i["situacao"] = "A_AVALIAR"
    base["itens"] = novos + base["itens"]
    base["gerado_em"] = date.today().isoformat()
    base["nota"] = ("Precedente direciona pesquisa; não fundamenta parecer. "
                    "Avaliação de aplicabilidade a Goiânia é do ciclo "
                    "dominical (modelo avançado) ou de revisão humana.")
    arq.write_text(json.dumps(base, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    mes = PASTA / f"{date.today():%Y-%m}.md"
    if novos:
        linhas = [f"# Precedentes capturados — {date.today():%m/%Y}\n"]
        for i in novos:
            linhas.append(f"- **{i['titulo']}** — {i['fonte']} "
                          f"({i['data'][:16]})\n  {i['url']}\n  "
                          f"consulta: `{i['consulta'][:60]}`")
        conteudo = "\n".join(linhas) + "\n"
        if mes.exists():
            conteudo = mes.read_text(encoding="utf-8") + "\n" + conteudo
        mes.write_text(conteudo, encoding="utf-8")
    print(f"  precedentes: {len(novos)} novos, {len(base['itens'])} no acervo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
