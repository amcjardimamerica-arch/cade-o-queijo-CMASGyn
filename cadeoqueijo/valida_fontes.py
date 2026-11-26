#!/usr/bin/env python3
"""Parâmetro de qualidade automatizado: toda URL registrada nos dados deve
pertencer a domínio oficial (config/fontes_oficiais.yml). Determinístico,
camada 0. Fora da lista => achado QUAL-FONTE no relatório de qualidade e
marca REQUER_CONFIRMACAO_FONTE_OFICIAL nos precedentes.
"""
from __future__ import annotations
import json, re, sys
from pathlib import Path
from urllib.parse import urlparse
import yaml

RAIZ = Path(__file__).resolve().parent.parent
CFG = yaml.safe_load((RAIZ / "config" / "fontes_oficiais.yml").read_text())
OFICIAIS = tuple(CFG["dominios_oficiais"])


def oficial(url: str) -> bool:
    try:
        h = urlparse(url).hostname or ""
    except Exception:
        return False
    return any(h == d or h.endswith("." + d) for d in OFICIAIS)


def main():
    suspeitas = []
    for arq in sorted((RAIZ / "dados").glob("*.json")):
        for u in set(re.findall(r'https?://[^\s"\\]+', arq.read_text(encoding="utf-8"))):
            if not oficial(u):
                suspeitas.append({"arquivo": arq.name, "url": u[:120]})
    # precedentes: marcar item a item (news.google e imprensa são esperados
    # ali — a marca obriga a confirmação, não condena a captura)
    prec_path = RAIZ / "referencias" / "transparencia" / "precedentes.json"
    marcados = 0
    if prec_path.exists():
        p = json.loads(prec_path.read_text(encoding="utf-8"))
        for it in p.get("itens", []):
            if not oficial(it.get("url", "")) and it.get("situacao") == "A_AVALIAR":
                it["situacao"] = "REQUER_CONFIRMACAO_FONTE_OFICIAL"
                marcados += 1
        prec_path.write_text(json.dumps(p, ensure_ascii=False, indent=1),
                             encoding="utf-8")
    rel = {"suspeitas_em_dados": suspeitas, "precedentes_marcados": marcados,
           "criterio": CFG["regra"].strip()}
    (RAIZ / "relatorios" / "qualidade_fontes.json").write_text(
        json.dumps(rel, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  fontes: {len(suspeitas)} URLs fora da lista oficial em dados/ | "
          f"{marcados} precedentes marcados para confirmação")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
