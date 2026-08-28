#!/usr/bin/env python3
"""Sonda de 2ª etapa: verifica quais fontes oficiais alternativas estão
no ar, para que cada informação indisponível no Diário aponte um caminho
concreto — e resolve a pendência P2 descobrindo o endereço vivo do portal
da transparência. Camada 0: nenhuma chamada de modelo."""
from __future__ import annotations
import json, sys, urllib.request, ssl
from datetime import date
from pathlib import Path
import yaml

RAIZ = Path(__file__).resolve().parent.parent
CFG = yaml.safe_load((RAIZ / "config" / "segunda_etapa.yml").read_text())
CTX = ssl.create_default_context(); CTX.check_hostname=False; CTX.verify_mode=ssl.CERT_NONE
UA = {"User-Agent": "AMC-Jardim-America-Vigilancia/1.0"}


def sonda(url):
    try:
        req = urllib.request.Request(url, headers=UA, method="GET")
        with urllib.request.urlopen(req, timeout=25, context=CTX) as r:
            return r.status, r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, url
    except Exception:
        return None, url


def main():
    saida = {"sondado_em": date.today().isoformat(), "fontes": {}}
    for chave, f in CFG["fontes"].items():
        melhor = None
        for u in f["candidatas"]:
            code, final = sonda(u)
            ok = code is not None and code < 400
            print(f"  {chave}: {u} -> {code}")
            if ok and not melhor:
                melhor = {"url": final, "http": code}
        saida["fontes"][chave] = {
            "nome": f["nome"],
            "disponivel": bool(melhor),
            "url": (melhor or {}).get("url", f["candidatas"][0]),
            "http": (melhor or {}).get("http"),
        }
    saida["mapa"] = CFG["mapa"]
    (RAIZ / "relatorios" / "segunda_etapa.json").write_text(
        json.dumps(saida, ensure_ascii=False, indent=1), encoding="utf-8")
    disp = sum(1 for f in saida["fontes"].values() if f["disponivel"])
    print(f"  2ª etapa: {disp}/{len(saida['fontes'])} fontes no ar")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
