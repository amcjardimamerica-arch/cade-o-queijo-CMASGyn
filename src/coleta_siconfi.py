#!/usr/bin/env python3
"""Trilha do Queijo · via federal da folha — SICONFI/Tesouro Nacional.

O RGF (Relatório de Gestão Fiscal) é declaração OBRIGATÓRIA do ente ao
Tesouro: traz a Despesa Total com Pessoal (DTP) e a Receita Corrente
Líquida que o Diário municipal esconde. O RREO traz a execução bimestral.
Divergência entre o declarado aqui e o publicado lá é achado forte.

Descoberta com autodiagnóstico: candidatos de endpoint da API pública,
caso de controle embutido (exercício anterior, que TEM de existir) e o
erro gravado no próprio JSON. id_ente = código IBGE 5208707 (Goiânia).
Camada 0 — zero tokens. Saída: dados/siconfi.json
"""
from __future__ import annotations
import json, sys
from datetime import date
from pathlib import Path
import requests

RAIZ = Path(__file__).resolve().parent.parent
requests.packages.urllib3.disable_warnings()
S = requests.Session(); S.verify = False
S.headers.update({"User-Agent": "AMC-Jardim-America-Vigilancia/1.0",
                  "Accept": "application/json"})
IBGE = "5208707"
BASES = ["https://apidatatransparencia.tesouro.gov.br/ords/siconfi/tt",
         "https://apidados.tesouro.gov.br/ords/siconfi/tt"]
ROTULOS_DTP = ("DESPESA TOTAL COM PESSOAL", "DTP")
ROTULOS_RCL = ("RECEITA CORRENTE LÍQUIDA", "RECEITA CORRENTE LIQUIDA")


def consulta(base, rec, **par):
    r = S.get(f"{base}/{rec}", params=par, timeout=60)
    r.raise_for_status()
    return r.json().get("items", [])


def rgf(base, ano, periodicidade, periodo):
    return consulta(base, "rgf", an_exercicio=ano,
                    in_periodicidade=periodicidade, nr_periodo=periodo,
                    co_tipo_demonstrativo="RGF", co_esfera="M",
                    co_poder="E", id_ente=IBGE)


def extrai(items):
    dtp = rcl = None
    linhas = []
    for it in items:
        rot = (str(it.get("cod_conta") or "") + " "
               + str(it.get("conta") or "")).upper()
        col = str(it.get("coluna") or "").upper()
        val = it.get("valor")
        if val is None:
            continue
        if any(k in rot for k in ROTULOS_DTP) and ("TOTAL" in col
                                                   or "%" not in col):
            if dtp is None or "ÚLTIMOS 12" in col or "APURADO" in col:
                dtp = val
            linhas.append({"conta": rot[:90], "coluna": col[:50],
                           "valor": val})
        if any(k in rot for k in ROTULOS_RCL):
            if rcl is None:
                rcl = val
            linhas.append({"conta": rot[:90], "coluna": col[:50],
                           "valor": val})
    return dtp, rcl, linhas[:30]


def main():
    hoje = date.today()
    saida = {"coletado_em": hoje.isoformat(), "id_ente": IBGE,
             "fonte": "SICONFI/STN — RGF declarado pelo próprio ente",
             "tentativas": [], "controle": None, "rgf": None}
    for base in BASES:
        # caso de controle: exercício anterior, algum período TEM de existir
        ctrl = None
        for per, n in (("Q", 3), ("S", 2), ("Q", 2), ("S", 1)):
            try:
                items = rgf(base, hoje.year - 1, per, n)
                if items:
                    ctrl = {"base": base, "periodicidade": per,
                            "periodo": n, "itens": len(items)}
                    break
            except Exception as e:
                saida["tentativas"].append(
                    f"{base} {hoje.year-1}/{per}{n}: "
                    f"{type(e).__name__} {str(e)[:80]}")
        if not ctrl:
            continue
        saida["controle"] = ctrl
        # do mais recente do exercício corrente para trás
        for ano in (hoje.year, hoje.year - 1):
            for per, n in (("Q", 2), ("Q", 1), ("S", 1),
                           ("Q", 3), ("S", 2)):
                try:
                    items = rgf(base, ano, per, n)
                except Exception:
                    continue
                if not items:
                    continue
                dtp, rcl, linhas = extrai(items)
                saida["rgf"] = {"exercicio": ano, "periodicidade": per,
                                "periodo": n, "itens": len(items),
                                "despesa_total_pessoal": dtp,
                                "receita_corrente_liquida": rcl,
                                "linhas_relevantes": linhas}
                break
            if saida["rgf"]:
                break
        break
    (RAIZ / "dados" / "siconfi.json").write_text(
        json.dumps(saida, ensure_ascii=False, indent=1), encoding="utf-8")
    r = saida["rgf"]
    print(f"  SICONFI: controle={'ok' if saida['controle'] else 'FALHOU'} | "
          + (f"RGF {r['exercicio']}/{r['periodicidade']}{r['periodo']} — "
             f"DTP R$ {r['despesa_total_pessoal']:,.2f} | RCL "
             f"R$ {r['receita_corrente_liquida']:,.2f}"
             if r and r["despesa_total_pessoal"] else
             "sem RGF legível — autodiagnóstico no JSON"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
