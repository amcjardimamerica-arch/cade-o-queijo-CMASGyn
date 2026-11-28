"""Trava: os fluxos que gravam o banco partem da ponta do branch.

Um pedido de coleta que espera na fila (grupo onisciente-banco) roda depois de outra rodada ter
gravado o banco. Se ele fizer checkout do commit da hora do pedido, a gravação final conflita
com o banco da rodada anterior e a coleta inteira se perde (aconteceu em 28/11/2026).
"""
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[1]


def _fluxos_do_banco():
    for p in sorted((RAIZ / ".github" / "workflows").glob("*.yml")):
        dados = yaml.safe_load(p.read_text(encoding="utf-8"))
        grupo = (dados.get("concurrency") or {}).get("group")
        if grupo == "onisciente-banco":
            yield p, dados


def test_todo_fluxo_do_banco_faz_checkout_da_ponta_do_branch():
    fluxos = list(_fluxos_do_banco())
    assert len(fluxos) >= 7
    for p, dados in fluxos:
        for job in dados["jobs"].values():
            passos = [s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/checkout")]
            assert passos, p.name
            assert passos[0].get("with", {}).get("ref") == "${{ github.ref_name }}", p.name
