#!/usr/bin/env python3
"""Identifica quem recebeu, quanto, com que periodicidade e para quê.

Enriquece cada inscrição com razão social, nome fantasia, natureza jurídica e
atividade econômica, consultados em base pública. O enriquecimento serve a dois
fins: descrever o destinatário e denunciar incompatibilidade — sociedade
empresária com fins lucrativos não celebra termo de fomento, que é instrumento
de parceria com organização da sociedade civil.

Periodicidade sai da contagem de pagamentos no exercício, não de presunção:
três ou mais competências com valor estável indicam despesa mensal; ocorrência
única indica pagamento anual ou pontual.

Advertência que o módulo carrega em cada registro: a inscrição foi extraída da
página do Diário Oficial. Se a página traz vários atos, a inscrição pode não ser
a beneficiária daquele instrumento. Por isso todo vínculo entre inscrição e
instrumento nasce com selo A_CONFERIR até o empenho individualizado.
"""
from __future__ import annotations
import json, re, sys, time, urllib.request
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CACHE = RAIZ / "estado" / "cnpj.json"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/120"}

# Naturezas jurídicas que podem celebrar termo de fomento ou de colaboração
OSC = {"3999", "3220", "3069", "3271", "3999", "3212", "3301", "3306", "3999"}
OSC_PREFIXO = "3"     # entidades sem fins lucrativos

def consultar(cnpj, cache):
    n = re.sub(r"\D", "", cnpj)
    if n in cache: return cache[n]
    for url in (f"https://brasilapi.com.br/api/cnpj/v1/{n}",
                f"https://minhareceita.org/{n}"):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25) as r:
                d = json.loads(r.read())
            cache[n] = {
              "razao_social": d.get("razao_social") or d.get("nome"),
              "nome_fantasia": (d.get("nome_fantasia") or d.get("fantasia") or "").strip() or None,
              "natureza_juridica": str(d.get("codigo_natureza_juridica") or
                                       d.get("natureza_juridica") or ""),
              "atividade": d.get("cnae_fiscal_descricao"),
              "situacao": d.get("descricao_situacao_cadastral") or d.get("situacao"),
              "municipio": d.get("municipio"), "uf": d.get("uf"),
              "abertura": d.get("data_inicio_atividade") or d.get("abertura")}
            time.sleep(0.5)
            return cache[n]
        except Exception:
            continue
    cache[n] = {"razao_social": None, "erro": "não consultado"}
    return cache[n]

def sem_fins_lucrativos(nj):
    m = re.search(r"(\d{3,4})", str(nj) or "")
    return bool(m) and str(m.group(1)).startswith(OSC_PREFIXO)

def main():
    L = lambda p: json.loads((RAIZ / p).read_text(encoding="utf-8"))
    fluxo = L("dados/fluxo_2026.json")
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}

    # agrupa por inscrição, dentro do exercício
    grupos = defaultdict(list)
    for d in fluxo["despesas"]:
        grupos[d["cnpj"]].append(d)

    saida = []
    for cnpj, itens in grupos.items():
        itens.sort(key=lambda x: x["data"])
        meses = sorted({x["data"][:7] for x in itens})
        total = sum(x["valor"] or 0 for x in itens)
        vals = [x["valor"] for x in itens if x["valor"]]
        media = sum(vals)/len(vals) if vals else 0
        variacao = (max(vals)-min(vals))/media if vals and media else 0
        if len(meses) >= 3 and variacao < 0.15:
            period, nota_p = "MENSAL", "três ou mais competências com valor estável"
        elif len(meses) >= 3:
            period, nota_p = "RECORRENTE", "três ou mais competências, valor variável"
        elif len(meses) == 2:
            period, nota_p = "PARCELADO", "duas competências"
        else:
            period, nota_p = "ANUAL OU PONTUAL", "ocorrência única no exercício"

        c = consultar(cnpj, cache)
        instrumentos = sorted({v for x in itens for v in (x.get("vinculo") or [])})
        parceria = any(re.search(r"TERMO DE (FOMENTO|COLABORA)", i, re.I) for i in instrumentos)
        alerta = None
        if parceria and c.get("natureza_juridica") and not sem_fins_lucrativos(c["natureza_juridica"]):
            alerta = ("Instrumento de parceria com organização da sociedade civil celebrado "
                      f"com inscrição de natureza jurídica {c['natureza_juridica']}, que não é "
                      "entidade sem fins lucrativos. Ou a natureza jurídica mudou, ou a "
                      "inscrição não é a beneficiária deste instrumento — a página do Diário "
                      "reúne vários atos. Exige o processo para desempatar.")

        # acumulado por competência, dentro do ano
        acumulado, corrente = [], 0.0
        for m in meses:
            v = sum(x["valor"] or 0 for x in itens if x["data"][:7] == m)
            corrente += v
            acumulado.append({"competencia": m, "no_mes": round(v, 2),
                              "acumulado_no_ano": round(corrente, 2)})

        finalidades = [re.sub(r"\s+", " ", x.get("objeto") or "")[:170] for x in itens]
        saida.append({
          "cnpj": cnpj,
          "razao_social": c.get("razao_social"),
          "nome_fantasia": c.get("nome_fantasia"),
          "descricao": f"{cnpj} — {c.get('razao_social') or 'razão social não consultada'}"
                       + (f" (nome fantasia: {c['nome_fantasia']})" if c.get("nome_fantasia") else ""),
          "natureza_juridica": c.get("natureza_juridica"),
          "sem_fins_lucrativos": sem_fins_lucrativos(c.get("natureza_juridica")),
          "atividade_economica": c.get("atividade"),
          "situacao_cadastral": c.get("situacao"),
          "municipio": c.get("municipio"), "uf": c.get("uf"),
          "valor_total_no_exercicio": round(total, 2),
          "pagamentos": len(itens), "competencias": meses,
          "periodicidade": period, "criterio_periodicidade": nota_p,
          "valor_medio": round(media, 2),
          "acumulado_mensal": acumulado,
          "instrumentos": instrumentos,
          "tem_vinculo": bool(instrumentos),
          "finalidade": finalidades,
          "selo": "A_CONFERIR",
          "ressalva": "Inscrição extraída da página do Diário Oficial. O vínculo com o "
                      "instrumento só se confirma com o empenho individualizado.",
          "alerta_incompatibilidade": alerta})

    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    saida.sort(key=lambda x: -x["valor_total_no_exercicio"])
    res = {"exercicio": 2026, "destinatarios": saida,
      "resumo": {"total": len(saida),
        "com_vinculo": sum(1 for x in saida if x["tem_vinculo"]),
        "mensais": sum(1 for x in saida if x["periodicidade"] == "MENSAL"),
        "pontuais": sum(1 for x in saida if x["periodicidade"].startswith("ANUAL")),
        "com_alerta": sum(1 for x in saida if x["alerta_incompatibilidade"]),
        "valor": round(sum(x["valor_total_no_exercicio"] for x in saida), 2)}}
    (RAIZ / "dados" / "destinatarios_2026.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for x in saida:
        print(f"  {x['cnpj']}  R$ {x['valor_total_no_exercicio']:>12,.2f}  "
              f"{x['periodicidade']:17s} {(x['razao_social'] or '?')[:38]}")
        if x["alerta_incompatibilidade"]: print("      ALERTA de incompatibilidade")
    print(f"  {res['resumo']}")

if __name__ == "__main__":
    main()
