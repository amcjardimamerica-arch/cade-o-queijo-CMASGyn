"""Os 183 requisitos do projeto original e a recontagem com evidência.

O registro fica em ``config/requisitos_onisciente.yml``. Cumprido vale 1, parcial vale meio e
ausente vale zero. Um requisito só conta como cumprido com evidência; quando tem trava, a trava é
um teste que falha se o requisito deixar de ser cumprido.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import yaml

from . import RAIZ

REGISTRO = RAIZ / "config" / "requisitos_onisciente.yml"
# Os pedidos que vieram depois do projeto original (selo, Receita Federal, painel...), com ids a partir de 184.
AMPLIACAO = RAIZ / "config" / "requisitos_ampliacao.yml"
VALOR = {"cumprido": 1.0, "parcial": 0.5, "ausente": 0.0}


def carregar(caminho: Path = REGISTRO) -> list[dict]:
    return yaml.safe_load(caminho.read_text(encoding="utf-8"))


def contar(itens: list[dict]) -> dict:
    total = len(itens)
    c = Counter(i["situacao"] for i in itens)
    pontos = sum(VALOR[i["situacao"]] for i in itens)
    por_bloco: dict[str, Counter] = {}
    for i in itens:
        por_bloco.setdefault(i["bloco"], Counter())[i["situacao"]] += 1
    return {
        "total": total,
        "cumpridos": c["cumprido"], "parciais": c["parcial"], "ausentes": c["ausente"],
        "percentual": round(100 * pontos / total, 1) if total else 0.0,
        "por_bloco": {b: {"itens": sum(v.values()), "cumpridos": v["cumprido"],
                          "parciais": v["parcial"], "ausentes": v["ausente"],
                          "percentual": round(100 * (v["cumprido"] + v["parcial"] / 2) / sum(v.values()), 1)}
                      for b, v in por_bloco.items()},
    }


def problemas(itens: list[dict], raiz: Path = RAIZ, *, desde: int = 1, contigua: bool = True) -> list[str]:
    """O que torna o registro desonesto: cumprido sem evidência, falta sem dono, trava inexistente.

    O registro original é contíguo de 1 a 183; o da ampliação começa em 184 e pode ter saltos
    (cada frente reservou a sua faixa), mas nunca repete nem desce para dentro do original."""
    erros = []
    ids = [i["id"] for i in itens]
    if contigua and ids != list(range(desde, desde + len(ids))):
        erros.append("numeração fora de ordem ou com buraco")
    if not contigua and (ids != sorted(set(ids)) or (ids and ids[0] < desde)):
        erros.append("numeração repetida, fora de ordem ou dentro do registro original")
    for i in itens:
        n = i["id"]
        if i["situacao"] not in VALOR:
            erros.append(f"#{n}: situação desconhecida {i['situacao']!r}")
        if not (i.get("evidencia") or "").strip():
            erros.append(f"#{n}: sem evidência")
        if i["situacao"] != "cumprido" and not (i.get("falta") or "").strip():
            erros.append(f"#{n}: {i['situacao']} sem dizer o que falta")
        trava = i.get("trava")
        if trava:
            arquivo, _, funcao = trava.partition("::")
            caminho = raiz / arquivo
            if not caminho.exists() or f"def {funcao}(" not in caminho.read_text(encoding="utf-8"):
                erros.append(f"#{n}: trava {trava} não existe")
    return erros


def carregar_ampliacao(caminho: Path = AMPLIACAO) -> list[dict]:
    return yaml.safe_load(caminho.read_text(encoding="utf-8")) if caminho.exists() else []


def problemas_ampliacao(itens: list[dict], raiz: Path = RAIZ) -> list[str]:
    return problemas(itens, raiz, desde=184, contigua=False)
