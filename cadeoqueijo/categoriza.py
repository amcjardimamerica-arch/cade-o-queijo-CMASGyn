#!/usr/bin/env python3
"""Classifica cada despesa nas categorias de config/categorias_despesa.yml
e afere os tetos de config/parametros_tcm.yml.

Ordem de decisão: subitem de dez dígitos, natureza de oito, texto do ato, ação
orçamentária. Se código e texto divergirem, prevalece o texto e o registro é
marcado para conferência humana — nunca se rateia o que não se classifica.
"""
from __future__ import annotations
import json, re, sys
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
L = lambda p: json.loads((RAIZ / p).read_text(encoding="utf-8"))

def yml(p):
    import yaml
    return yaml.safe_load((RAIZ / p).read_text(encoding="utf-8"))

def primeiro_nome(t):
    t = re.sub(r"\s+", " ", (t or "").strip())
    if not t: return ""
    p = t.split(" ")[0]
    return p.capitalize()

def bate(nat, lista):
    n = str(nat or "")
    return any(n.startswith(x[:-1]) if x.endswith("*") else n == x for x in lista)

def classificar(reg, cat):
    """Devolve (categoria, subcategoria, base_da_decisao)."""
    nat = str(reg.get("natureza") or "")
    txt = (reg.get("objeto") or "").lower()
    por_texto = None
    for cn, cv in cat.items():
        for sn, sv in (cv.get("subcategorias") or {}).items():
            for t in (sv.get("texto") or []):
                if t.lower() in txt:
                    por_texto = (cn, sn); break
            if por_texto: break
        if por_texto: break
    por_codigo = None
    for cn, cv in cat.items():
        if bate(nat, cv.get("naturezas") or []):
            por_codigo = (cn, None); break
        for sn, sv in (cv.get("subcategorias") or {}).items():
            if bate(nat, sv.get("naturezas") or []):
                por_codigo = (cn, sn); break
        if por_codigo: break
    if por_texto and por_codigo and por_texto[0] != por_codigo[0]:
        return (*por_texto, "TEXTO — divergente do código, marcado para conferência")
    if por_texto:  return (*por_texto, "texto do ato")
    if por_codigo: return (*por_codigo, "natureza")
    # instrumento: termo de fomento e de colaboração são repasse a instituição
    inst = " ".join(reg.get("vinculo") or []).upper()
    if re.search(r"TERMO DE (FOMENTO|COLABORA)", inst):
        return ("REPASSE_ENTIDADE", None, "instrumento de parceria")
    if "CONV" in inst and "NIO" in inst:
        return ("REPASSE_ENTIDADE", None, "convênio")
    if "CONTRATO" in inst or "ATA DE REGISTRO" in inst:
        return ("CONTRATUAL_FIXA", "servicos_continuados", "instrumento contratual")
    # objeto: pistas de repasse e de serviço
    if re.search(r"organiza[çc][ãa]o da sociedade civil|entidade|associa[çc][ãa]o|"
                 r"institui[çc][ãa]o|plano de trabalho|parceria", txt):
        return ("REPASSE_ENTIDADE", None, "texto do objeto")
    if re.search(r"aquisi[çc][ãa]o|fornecimento|presta[çc][ãa]o de servi[çc]o|"
                 r"contrata[çc][ãa]o da empresa|empresa", txt):
        return ("CONTRATUAL_FIXA", "servicos_continuados", "texto do objeto")
    # ação orçamentária atribui o programa
    dot = str(reg.get("dotacao") or "")
    if dot and dot in ((cat.get("PROGRAMA") or {}).get("mapa_por_acao") or {}):
        return ("PROGRAMA", None, "ação orçamentária")
    if dot.startswith("08."):
        return ("PROGRAMA", None, "função 08, ação não mapeada")
    return ("NAO_CLASSIFICADA", None, "sem critério aplicável")

def main():
    cat = yml("config/categorias_despesa.yml")["categorias"]
    lim = {x["id"]: x for x in yml("config/parametros_tcm.yml")["limites"]}
    fluxo = L("dados/fluxo_2026.json")
    orc = L("dados/orcamento_assistencia_social.json")
    pes = L("dados/pessoal.json")

    itens, divergentes = [], []
    for d in fluxo["despesas"]:
        c, s, base = classificar(d, cat)
        it = {**d, "categoria": c, "subcategoria": s, "base_classificacao": base,
              "cor": (cat.get(c) or {}).get("cor", "#6b665c")}
        if "divergente" in base: divergentes.append(it)
        itens.append(it)
    for dia in pes.get("diarias", []):
        itens.append({"tipo": "sem_vinculo", "categoria": "PESSOAL", "subcategoria": "diarias",
            "base_classificacao": "texto do ato", "cor": cat["PESSOAL"]["cor"],
            "beneficiario_pf": dia.get("primeiro_nome"), "valor": None,
            "data": dia.get("data_do_ato"), "edicao": dia.get("edicao"),
            "objeto": f"Concessão de diária a {dia.get('primeiro_nome')}"
                      + (f", destino {dia['destino']}" if dia.get("destino") else ""),
            "vinculo": [], "falta": "Ato com destino, período, finalidade, quantidade e valor; "
                                    "prestação de contas do deslocamento"})

    resumo = defaultdict(lambda: {"n": 0, "valor": 0.0, "com_vinculo": 0})
    for i in itens:
        k = i["categoria"]
        resumo[k]["n"] += 1
        resumo[k]["valor"] += i.get("valor") or 0
        if i.get("vinculo"): resumo[k]["com_vinculo"] += 1

    # tetos
    tesouro = orc["fmas"]["2026"]["receita_detalhada"]["tesouro_financiamento_royalties"]
    teto30 = tesouro * 0.30
    pessoal = resumo["PESSOAL"]["valor"]
    igd_base = 706707.15
    tetos = [
      {"id": "LIM-02", "nome": lim["LIM-02"]["nome"], "base": tesouro, "teto": teto30,
       "apurado": pessoal, "aferivel": False,
       "situacao": "INAFERÍVEL — a folha não está publicada",
       "nota": f"O Tesouro aporta {tesouro:,.2f} no Fundo. O teto de 30% resulta em "
               f"{teto30:,.2f}. Qualquer despesa de pessoal do Fundo custeada pelo Tesouro "
               f"acima disso rompe o limite. Sem a folha por fonte, não se afere."},
      {"id": "LIM-04", "nome": lim["LIM-04"]["nome"], "base": igd_base,
       "teto": igd_base * 0.10, "apurado": 0.0, "aferivel": True,
       "situacao": "DESCUMPRIDO",
       "nota": f"Devido ao controle social: {igd_base*0.10:,.2f}. Executado: R$ 0,00. "
               "A sanção do artigo 6º, § 6º, da Resolução CNAS/MDS 202/2025 é o bloqueio "
               "dos repasses."},
      {"id": "LIM-01", "nome": lim["LIM-01"]["nome"], "base": None, "teto": None,
       "apurado": None, "aferivel": False,
       "situacao": "INAFERÍVEL — falta o Relatório de Gestão Fiscal",
       "nota": "Limite de 54% da receita corrente líquida para o Executivo, com alerta "
               "prudencial em 51,3%."},
      {"id": "LIM-03", "nome": lim["LIM-03"]["nome"], "base": None, "teto": None,
       "apurado": None, "aferivel": False,
       "situacao": "INAFERÍVEL — falta a folha e a lei do subsídio do Prefeito",
       "nota": "Nenhuma remuneração pode superar o subsídio do Prefeito."}]

    saida = {"exercicio": 2026, "itens": itens,
             "resumo": {k: dict(v) for k, v in resumo.items()},
             "divergentes": len(divergentes), "tetos": tetos,
             "nao_classificadas": sum(1 for i in itens if i["categoria"] == "NAO_CLASSIFICADA")}
    (RAIZ / "dados" / "categorias_2026.json").write_text(
        json.dumps(saida, ensure_ascii=False, indent=1), encoding="utf-8")
    for k, v in sorted(resumo.items(), key=lambda x: -x[1]["valor"]):
        print(f"  {k:20s} {v['n']:3d} itens  R$ {v['valor']:>14,.2f}  "
              f"{v['com_vinculo']} com vínculo")
    print(f"  divergentes: {len(divergentes)} · não classificadas: {saida['nao_classificadas']}")
    for t in tetos:
        print(f"  {t['id']}: {t['situacao']}")

if __name__ == "__main__":
    main()
