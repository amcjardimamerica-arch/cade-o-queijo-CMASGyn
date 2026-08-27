#!/usr/bin/env python3
"""Rotina de fiscalização. Encadeia os blocos e só emite parecer se houver achado.

Ordem: critérios de qualidade (do corpus) -> exercício -> pessoal -> consolidação
-> trilha visual -> parecer. Sem irregularidade, não há parecer: o silêncio do
relatório é resultado, não omissão.
"""
from __future__ import annotations
import json, subprocess, sys
from collections import Counter
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
REL = RAIZ / "relatorios"; DADOS = RAIZ / "dados"

ETAPAS = [
    ("critérios de qualidade", "src/qualidade.py"),
    ("verificação do exercício", "src/verifica_exercicio.py"),
    ("pessoal e diárias", "src/pessoal.py"),
    ("modelo de fluxo", "src/monta_fluxo.py"),
    ("trilha visual", "src/gera_fluxo_html.py"),
    ("categorias e tetos", "src/categoriza.py"),
    ("trilha didática", "src/gera_trilha_didatica.py"),
]

def rodar(nome, script):
    r = subprocess.run([sys.executable, script], cwd=RAIZ, capture_output=True, text=True)
    ok = r.returncode == 0
    print(f"  [{'ok' if ok else 'FALHA'}] {nome}")
    if not ok: print(r.stderr[-400:], file=sys.stderr)
    return ok

def consolidar():
    v = json.loads((REL / "verificacao_2026.json").read_text(encoding="utf-8"))
    p = json.loads((DADOS / "pessoal.json").read_text(encoding="utf-8"))
    todos = v["achados"] + [{"bloco": "PES", "codigo": a["regra"], **{k: a[k] for k in
        ("severidade", "selo", "titulo", "detalhe", "norma")}, "dados": a.get("dados", {})}
        for a in p["achados"]]
    docs = json.loads((RAIZ / "config" / "documentos_complementares.json").read_text(encoding="utf-8"))
    for a in todos:
        a["documentos_complementares"] = docs.get(a["codigo"], [])
    ORD = {"critica": 0, "alta": 1, "media": 2, "baixa": 3}
    todos.sort(key=lambda x: (ORD.get(x["severidade"], 9), x["bloco"]))
    return todos

def main():
    print(f"Fiscalização — {date.today().isoformat()}")
    for nome, s in ETAPAS:
        if not rodar(nome, s): return 1
    achados = consolidar()
    sev = Counter(a["severidade"] for a in achados)
    selo = Counter(a["selo"] for a in achados)

    if not achados:
        (REL / f"sem_achados_{date.today():%Y-%m}.md").write_text(
            f"# Fiscalização de {date.today():%m/%Y}\n\n"
            "Nenhuma desconformidade apurada no ciclo. As regras foram aplicadas e "
            "não encontraram achado. Isto não equivale a conformidade comprovada: "
            "regras marcadas como inconclusivas por documento faltante permanecem "
            "sem avaliação até que o documento chegue.\n", encoding="utf-8")
        print("  sem achados — parecer não emitido")
        return 0

    # há irregularidade: consolida, pede documentos e sinaliza parecer
    docs = [d for a in achados for d in a.get("documentos_complementares", [])]
    saida = {"exercicio": 2026, "gerado_em": date.today().isoformat(),
             "achados": achados, "total": len(achados),
             "por_severidade": dict(sev), "por_selo": dict(selo),
             "documentos_requisitados": len(docs),
             "parecer_devido": True}
    (REL / "achados_consolidados_2026.json").write_text(
        json.dumps(saida, ensure_ascii=False, indent=1), encoding="utf-8")
    # parecer em Word
    r = subprocess.run(["node", "src/parecer_docx/doc2run.js"], cwd=RAIZ,
                       capture_output=True, text=True)
    print(f"  [{'ok' if r.returncode == 0 else 'FALHA'}] parecer em Word")

    print(f"  {len(achados)} achados — {dict(sev)}")
    print(f"  selos: {dict(selo)}")
    print(f"  PARECER DEVIDO. {len(docs)} documentos complementares a requisitar.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
