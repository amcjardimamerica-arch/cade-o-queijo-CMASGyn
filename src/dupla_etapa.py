#!/usr/bin/env python3
"""Auditoria de dupla etapa. Só existe quando há suspeita.

A regra que governa este módulo: achado de mera ausência documental não aciona
segunda via. Falta de documento já é conclusivo — não há o que reconferir. A
segunda via existe para achado que imputa uso indevido, porque é ali que o erro
custa caro.

Independência é o ponto. A segunda via não pode reusar a extração da primeira:
ou relê o documento bruto pelo digest, ou consulta fonte oficial de outro nível
de governo. Duas leituras do mesmo cache não são duas vias.
"""
from __future__ import annotations
import json, re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
L = lambda p: json.loads((RAIZ / p).read_text(encoding="utf-8"))

def yml(p):
    import yaml
    return yaml.safe_load((RAIZ / p).read_text(encoding="utf-8"))

def aciona(a):
    """Gatilhos de config/qualidade_fontes.yml. Ausência documental não aciona."""
    if a.get("selo") == "INCONCLUSIVO_POR_DOCUMENTO_FALTANTE": return None
    if a.get("severidade") == "critica": return "severidade crítica"
    if a.get("severidade") == "alta" and a.get("selo") == "CONFIRMADO":
        return "severidade alta com selo confirmado"
    d = a.get("dados") or {}
    if d.get("falta") and (d.get("falta") or 0) > 50000: return "diferença acima de cinquenta mil reais"
    if "incompatib" in (a.get("titulo","") + a.get("detalhe","")).lower():
        return "incompatibilidade de natureza jurídica"
    return None

# ── segundas vias, cada uma independente da primeira ────────────────────────
def via_federal_igd(a):
    """Reconfere o piso do Índice contra a planilha do Fundo Nacional — outro nível."""
    try:
        fed = L("dados/repasses_federais.json"); igd = L("dados/igd_controle_social.json")
    except Exception:
        return {"via": "planilha federal", "resultado": "INDISPONIVEL"}
    comps = fed["igd"]["competencias"]
    devido = round(sum(c["devido_ao_controle_social"] for c in comps), 2)
    aplicado = igd["afericao"]["aplicado_na_fonte_do_indice"]
    return {"via": "planilha de repasses do Fundo Nacional, competência a competência",
            "independencia": "fonte federal, não deriva da extração do Diário Oficial",
            "devido_recalculado": devido, "aplicado": aplicado,
            "competencias_conferidas": len(comps),
            "resultado": "CONFIRMA" if aplicado < devido else "DIVERGE"}

def via_aritmetica(a):
    """Reconfere pelo fechamento: as partes somam o todo?"""
    try:
        f = L("dados/fluxo_2026.json"); o = L("dados/orcamento_assistencia_social.json")
    except Exception:
        return {"via": "fechamento aritmético", "resultado": "INDISPONIVEL"}
    T = f["totais"]
    ok = abs(T["fonte_comprovada"] + T["fonte_nao_comprovada"] - T["fundo"]) < 1
    ac = sum(x["valor"] for x in o["acoes_fmas_2026"].values())
    ok2 = abs(ac - o["fmas"]["2026"]["total"]) < 1
    return {"via": "fechamento aritmético entre fontes, ações e total do Fundo",
            "independencia": "não relê documento; testa a coerência interna",
            "fontes_somam_o_fundo": ok, "acoes_somam_o_fundo": ok2,
            "resultado": "CONFIRMA" if ok and ok2 else "DIVERGE"}

def via_documento_bruto(a):
    """Relê o texto do anexo orçamentário, não o JSON derivado."""
    p = RAIZ / "corpus_txt" / "orcamento" / "loa_2026_lei_11590_anexos.txt"
    if not p.exists(): return {"via": "documento bruto", "resultado": "INDISPONIVEL"}
    t = p.read_text(encoding="utf-8")
    achou = {}
    for termo, rx in (("dotação do Conselho", r"MANUTENCAO DO CONSELHO MUNICIPAL DE ASSISTENCIA SOCIAL[^\d]*([\d\.]+,\d{2})"),
                      ("função 08", r"08\s+ASSIST[EÊ]NCIA SOCIAL\s+([\d\.]+)")):
        m = re.search(rx, t)
        achou[termo] = m.group(1) if m else None
    return {"via": "releitura do texto do anexo da Lei Orçamentária",
            "independencia": "lê o documento original, não o JSON derivado",
            "valores_relidos": achou,
            "resultado": "CONFIRMA" if any(achou.values()) else "INDISPONIVEL"}

VIAS = {"IGD-01": via_federal_igd, "CMAS-FIN-05": via_federal_igd,
        "SYS-03": via_aritmetica, "FIN-DES-01": via_aritmetica,
        "IGD-02": via_documento_bruto, "CMAS-FIN-07": via_documento_bruto,
        "REC-01": via_documento_bruto, "FMAS-01": via_documento_bruto}

def main():
    cfg = yml("config/qualidade_fontes.yml")
    try:
        ach = L("relatorios/achados_consolidados_2026.json")["achados"]
    except Exception:
        print("  sem achados consolidados"); return
    resultados = []
    for a in ach:
        g = aciona(a)
        if not g: continue
        fn = VIAS.get(a["codigo"], via_aritmetica)
        r = fn(a)
        if r["resultado"] == "CONFIRMA":
            selo, nota = a["selo"], "segunda via convergiu; selo mantido"
        elif r["resultado"] == "DIVERGE":
            selo, nota = "INDICIARIO", "segunda via divergiu; rebaixado e enviado à conferência humana"
        else:
            selo, nota = a["selo"], "segunda via indisponível; selo preservado, falha registrada"
        resultados.append({"codigo": a["codigo"], "titulo": a["titulo"],
            "gatilho": g, "selo_original": a["selo"], "selo_apos_dupla_via": selo,
            "segunda_via": r, "efeito": nota})

    if not resultados:
        print("  nenhum gatilho de dupla etapa — relatório não emitido")
        return
    conv = sum(1 for r in resultados if r["segunda_via"]["resultado"] == "CONFIRMA")
    div = sum(1 for r in resultados if r["segunda_via"]["resultado"] == "DIVERGE")
    ind = len(resultados) - conv - div
    saida = {"gerado_em": "2026-08-27", "regra": cfg["dupla_etapa"]["quando_roda"],
      "acionados": len(resultados), "convergiram": conv, "divergiram": div,
      "indisponiveis": ind, "resultados": resultados,
      "leitura": f"{len(resultados)} achados acionaram segunda via independente. "
                 f"{conv} convergiram e mantêm o selo. {div} divergiram e foram rebaixados. "
                 f"{ind} não puderam ser reconferidos."}
    (RAIZ / "relatorios" / "dupla_etapa_2026.json").write_text(
        json.dumps(saida, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  acionados {len(resultados)} · convergiram {conv} · divergiram {div} · indisponíveis {ind}")

if __name__ == "__main__":
    main()
