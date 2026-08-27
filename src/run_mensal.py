#!/usr/bin/env python3
"""Executor da fiscalização individualizada por mês.

Cada competência roda isolada: verificação determinística e parecer
visual próprio. Nenhuma soma cruza meses — a regra de separar por fonte
vale também no tempo: total agregado esconde o mês descumprido.

Uso: python3 src/run_mensal.py 2026-01 [2026-02 ...]
     python3 src/run_mensal.py 2026-01..2026-07
"""
from __future__ import annotations
import re, subprocess, sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def expande(args):
    comps = []
    for a in args:
        m = re.fullmatch(r"(\d{4})-(\d{2})\.\.(\d{4})-(\d{2})", a)
        if m:
            a1, m1, a2, m2 = map(int, m.groups())
            y, mo = a1, m1
            while (y, mo) <= (a2, m2):
                comps.append(f"{y}-{mo:02d}")
                mo += 1
                if mo == 13:
                    mo, y = 1, y + 1
        elif re.fullmatch(r"\d{4}-\d{2}", a):
            comps.append(a)
    return comps


def main():
    comps = expande(sys.argv[1:])
    if not comps:
        print(__doc__); return 2
    falhas = 0
    for c in comps:
        print(f"— competência {c} —")
        for script in ("src/verifica_mensal.py",
                       "src/gera_parecer_mensal_html.py"):
            r = subprocess.run([sys.executable, script, c], cwd=RAIZ)
            if r.returncode != 0:
                print(f"  [FALHA] {script} {c}")
                falhas += 1
                break
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
