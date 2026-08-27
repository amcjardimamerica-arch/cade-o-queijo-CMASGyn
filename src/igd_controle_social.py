#!/usr/bin/env python3
"""Aferição do piso de 10% do Índice de Gestão Descentralizada ao controle social.

Artigo 6º da Resolução CNAS/MDS 202/2025: no mínimo 10% do valor repassado
MENSALMENTE pelo IGD/SUAS e pelo IGD/PBF, destinados ao controle social, sem
prejuízo de outras fontes.

Dois pontos que mudam o cálculo e costumam ser confundidos:

1. O piso incide sobre o repasse FEDERAL do Índice. Recurso estadual alocado no
   Conselho é bem-vindo e conta como "outra fonte", mas não satisfaz o piso.
   Por isso a aferição separa a dotação do Conselho por fonte de recurso.

2. O percentual é mensal, não anual. Um ente que aplica 10% no acumulado do ano
   mas nada em oito meses descumpriu em oito competências.
"""
from __future__ import annotations
import json, re
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
L = lambda p: json.loads((RAIZ / p).read_text(encoding="utf-8"))

# Fontes de recurso federal onde o Índice trafega
FONTES_FEDERAIS = {"1660", "2660"}
FONTES_ESTADUAIS = {"1661", "2661", "1665"}
ACAO_CONSELHO = "3650.0824401082.591"
ACOES_IGD = {"08.244.0165.1103": "IGD SUAS", "08.244.0165.2555": "IGD Bolsa Família e CadÚnico"}

def qdd_conselho():
    """Lê o Quadro de Detalhamento de Despesas dentro dos anexos da Lei Orçamentária.
    Devolve a dotação do Conselho por natureza e fonte."""
    txt = (RAIZ / "corpus" / "orcamento" / "loa_2026_lei_11590_anexos.txt").read_text(encoding="utf-8")
    L = txt.split("\n")
    # O bloco do Conselho no Quadro começa na linha que traz a ação COM natureza
    # e fonte, e termina na linha de total isolada. Blocos anteriores da mesma
    # unidade também citam a ação, por isso a âncora exige natureza na linha.
    ini = None
    for i, l in enumerate(L):
        if ACAO_CONSELHO in l and re.search(r"\d\.\d\.\d{2}\.\d{2}\.\d{2}\s+\d{4}", l):
            ini = i; break
    if ini is None: return []
    linhas = []
    for l in L[ini:]:
        m = re.search(r"(\d\.\d\.\d{2}\.\d{2}\.\d{2})\s+(\d{4})\s*I\s*([\d\.]+)\s*I", l)
        if m:
            linhas.append({"natureza": m.group(1), "fonte": m.group(2),
                           "valor": int(m.group(3).replace(".", ""))})
            continue
        if re.match(r"^I\s+[\d\.]+\s+I\s*$", l.strip()):
            break   # total da ação encerra o bloco
    return linhas

def main():
    fin = L("dados/financeiro.json")
    orc = L("dados/orcamento_assistencia_social.json")

    # base do Índice, extraída dos decretos de crédito
    base = {}
    for a, nome in ACOES_IGD.items():
        v = (fin["por_acao"].get(a) or {}).get("valor")
        if v: base[a] = {"nome": nome, "valor": v}
    base_total = sum(x["valor"] for x in base.values())

    # dotação do Conselho, por fonte
    linhas = qdd_conselho()
    por_fonte = defaultdict(int)
    for x in linhas: por_fonte[x["fonte"]] += x["valor"]
    federal = sum(v for f, v in por_fonte.items() if f in FONTES_FEDERAIS)
    estadual = sum(v for f, v in por_fonte.items() if f in FONTES_ESTADUAIS)
    outras = sum(v for f, v in por_fonte.items()
                 if f not in FONTES_FEDERAIS | FONTES_ESTADUAIS)
    dot_total = federal + estadual + outras

    devido = round(base_total * 0.10, 2)
    piso_legal = round(base_total * 0.03, 2)
    cumprimento = round(100 * federal / devido, 1) if devido else None
    falta = round(devido - federal, 2)

    # aferição mensal — o piso é sobre o repasse de cada mês
    mensal = [{"competencia": f"2026-{m:02d}", "base_mensal": round(base_total/12, 2),
               "devido_mensal": round(base_total/12*0.10, 2),
               "aplicado_publicado": None,
               "situacao": "SEM DEMONSTRATIVO"} for m in range(1, 13)]

    saida = {
     "norma": "Artigo 6º da Resolução CNAS/MDS 202/2025",
     "texto": "no mínimo 10% do valor repassado mensalmente pelo IGD/SUAS e pelo IGD/PBF, "
              "destinados ao controle social, sem prejuízo de outras fontes de financiamento",
     "vigencia": "desde janeiro de 2026, artigo 15",
     "sancao": "bloqueio dos repasses até a comprovação, artigo 6º, § 6º",
     "piso_legal_absoluto": {"percentual": 3, "norma": "Artigo 14, § 7º, da Lei 14.601/2023",
                             "valor": piso_legal},
     "base_do_indice": {"acoes": base, "total": base_total,
       "origem": "decretos de crédito adicional publicados no Diário Oficial",
       "ressalva": "A base definitiva é o repasse efetivo do Fundo Nacional, por competência. "
                   "Sem a Consulta de Pagamentos, usa-se a dotação como aproximação."},
     "devido_ao_controle_social": devido,
     "dotacao_do_conselho": {
       "acao": ACAO_CONSELHO, "total": dot_total,
       "por_fonte": dict(por_fonte),
       "federal_fonte_do_indice": federal,
       "estadual_outras_fontes": estadual,
       "detalhe": linhas},
     "afericao": {
       "aplicado_na_fonte_do_indice": federal,
       "devido": devido,
       "diferenca": falta,
       "cumprimento_percentual": cumprimento,
       "situacao": "DESCUMPRIDO" if federal < devido else "CUMPRIDO",
       "leitura": (
         f"A ação do Conselho está dotada em {dot_total:,.2f}, mas apenas {federal:,.2f} "
         f"vêm da fonte federal onde o Índice trafega. O piso do artigo 6º exige "
         f"{devido:,.2f}. Faltam {falta:,.2f}. "
         f"Os {estadual:,.2f} de fonte estadual contam como outra fonte de financiamento, "
         "prevista na parte final do artigo 6º, mas não substituem o piso federal.")},
     "mensal": mensal,
     "documentos_para_conciliar": [
       "Consulta de Pagamentos do Fundo Nacional, por competência e bloco",
       "Extrato da conta específica do Índice de Gestão Descentralizada",
       "Demonstrativo de aplicação no controle social, com empenho, liquidação e pagamento",
       "Prestação de contas quadrimestral ao Conselho, artigo 6º, § 5º",
       "Quadro de Detalhamento de Despesas com dotação identificada como fortalecimento "
       "do controle social, artigo 6º, § 4º"]}

    (RAIZ / "dados" / "igd_controle_social.json").write_text(
        json.dumps(saida, ensure_ascii=False, indent=1), encoding="utf-8")
    a = saida["afericao"]
    print(f"  base do Índice        R$ {base_total:>12,.2f}")
    print(f"  devido (10%)          R$ {devido:>12,.2f}")
    print(f"  dotação do Conselho   R$ {dot_total:>12,.2f}  ({dict(por_fonte)})")
    print(f"  na fonte do Índice    R$ {federal:>12,.2f}")
    print(f"  {a['situacao']} — cumpre {cumprimento}%, faltam R$ {falta:,.2f}")

if __name__ == "__main__":
    main()
