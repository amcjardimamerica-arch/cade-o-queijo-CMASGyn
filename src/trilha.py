"""Trilha do dinheiro público — da entrada no caixa ao gasto final.

Sete estações, na ordem em que o dinheiro efetivamente anda:

  1 REPASSE     União e Estado transferem ao Fundo Municipal
  2 ORÇAMENTO   a Lei Orçamentária consigna a dotação
  3 CRÉDITO     suplementação, anulação e remanejamento alteram a dotação
  4 DELIBERAÇÃO o conselho aprova o plano de aplicação
  5 VÍNCULO     contrato, termo de fomento, colaboração ou convênio
  6 EMPENHO     compromete-se a despesa; liquida-se; paga-se
  7 ENTIDADE    o recurso chega a quem executa o serviço

Cada estação ausente é ruptura da trilha e vira achado. A ruptura mais grave
não é o desvio: é o trecho invisível, onde não se pode nem afirmar nem negar.

Sobre sobrepreço: este módulo produz INDÍCIOS, jamais conclusões. Sobrepreço
se demonstra por confronto com preço de mercado em perícia, não por estatística
sobre texto de Diário Oficial. O que se faz aqui é apontar onde vale olhar.
"""
from __future__ import annotations

import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))

import extracao
from util import RAIZ, agora, gravar_json, ler_json, log

SAIDA = RAIZ / "dados" / "trilha_dinheiro.json"

RE_VALOR = re.compile(r"(?:R\$\s*)?\b(\d{1,3}(?:\.\d{3})+,\d{2})\b")
RE_CNPJ = re.compile(r"\b(\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2})\b")
RE_DOTACAO = re.compile(r"\b(\d{2})\.(\d{3})\.(\d{4})\.(\d{4})\b")
RE_PROCESSO = re.compile(r"(?:processo|autos?)\s*n?[.º°]?\s*([\d./\-]{6,25})", re.I)
RE_CONTRATO = re.compile(
    r"(contrato|termo de (?:fomento|colabora[çc][ãa]o|parceria)|conv[êe]nio|"
    r"acordo de coopera[çc][ãa]o|termo aditivo)\s*n?[.º°]?\s*([\d./\-]{2,20})", re.I)

ESTACOES = {
    "repasse": r"(transfer[êe]ncia fundo a fundo|repasse d[ao] (?:Uni[ãa]o|Estado|FNAS|FEAS)|"
               r"(?-i:\bIGD\b)|Piso (?:B[áa]sico|Fixo|Vari[áa]vel)|emenda parlamentar|"
               r"cofinanciamento)",
    "orcamento": r"(Lei Or[çc]ament[áa]ria|(?-i:\bLOA\b)|dota[çc][ãa]o or[çc]ament[áa]ria|"
                 r"Quadro de Detalhamento|(?-i:\bQDD\b)|or[çc]amento anual)",
    "credito": r"(cr[ée]dito (?:adicional|suplementar|especial)|suplementa[çc][ãa]o|"
               r"anula[çc][ãa]o (?:parcial|total) de dota[çc][ãa]o|remanejamento|transposi[çc][ãa]o)",
    "deliberacao": r"(plano de a[çc][ãa]o|plano de aplica[çc][ãa]o|aprova[çc][ãa]o d[oe] "
                   r"(?:plano|contas)|delibera[çc][ãa]o d[oe] (?:plen[áa]ria|conselho))",
    "vinculo": r"(termo de (?:fomento|colabora[çc][ãa]o|parceria)|contrato n|conv[êe]nio|"
               r"chamamento p[úu]blico|inexigibilidade|dispensa de licita[çc][ãa]o|"
               r"termo aditivo|acordo de coopera[çc][ãa]o)",
    "empenho": r"(nota de empenho|empenho n|liquida[çc][ãa]o|ordem de pagamento|"
               r"pagamento efetuado|nota fiscal)",
    "entidade": r"(institui[çc][ãa]o privada sem fins lucrativos|organiza[çc][ãa]o da "
                r"sociedade civil|(?-i:\bOSC\b)|entidade (?:beneficiada|executora|parceira)|"
                r"subven[çc][ãa]o social)",
}
ESTACOES_RE = {k: re.compile(v, re.IGNORECASE) for k, v in ESTACOES.items()}

# --------------------------------------------------------- indícios de sobrepreço
INDICIOS = {
    "SOB-01": {
        "titulo": "Mesmo objeto com valores díspares entre beneficiários",
        "severidade": "media",
        "descricao": ("Duas ou mais entidades recebem pelo mesmo objeto declarado com "
                      "diferença superior a 40% no valor. Pode decorrer de porte "
                      "distinto do serviço — ou não."),
    },
    "SOB-02": {
        "titulo": "Valor muito acima da mediana da mesma ação orçamentária",
        "severidade": "media",
        "descricao": ("Lançamento que excede em mais de três desvios a mediana dos "
                      "lançamentos da mesma dotação no período."),
    },
    "SOB-03": {
        "titulo": "Fracionamento aparente de despesa",
        "severidade": "alta",
        "descricao": ("Mesma entidade, mesmo objeto, lançamentos sucessivos em janela "
                      "curta cuja soma ultrapassa o limite que exigiria outra "
                      "modalidade. Indício de fuga ao procedimento, na forma do artigo "
                      "75, § 1º, da Lei 14.133/2021."),
    },
    "SOB-04": {
        "titulo": "Aditivo que excede o limite legal de acréscimo",
        "severidade": "alta",
        "descricao": ("Termo aditivo cujo valor supera 25% do original, limite do "
                      "artigo 125 da Lei 14.133/2021."),
    },
    "SOB-05": {
        "titulo": "Concentração de repasses em poucas entidades",
        "severidade": "media",
        "descricao": ("Poucos beneficiários absorvem parcela desproporcional do total "
                      "repassado, o que merece conferência quanto à seleção por "
                      "chamamento público."),
    },
    "SOB-06": {
        "titulo": "Repasse sem vínculo formal identificável",
        "severidade": "alta",
        "descricao": ("Valor destinado a entidade sem que a publicação indique "
                      "contrato, termo de fomento, de colaboração ou convênio "
                      "correspondente."),
    },
    "SOB-07": {
        "titulo": "Repasse sem chamamento público prévio",
        "severidade": "alta",
        "descricao": ("Parceria com organização da sociedade civil sem chamamento "
                      "público nem justificativa de dispensa ou inexigibilidade, "
                      "exigidos pelos artigos 24, 30 e 31 da Lei 13.019/2014."),
    },
}


def _v(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


def mapear(dominio: dict) -> dict:
    trechos = extracao.carregar(dominio["id"])
    funcao = dominio["orcamento"]["funcao"]

    eventos: list[dict] = []
    for t in trechos:
        texto = t["texto"]
        estacoes = [k for k, r in ESTACOES_RE.items() if r.search(texto)]
        if not estacoes:
            continue
        dot = RE_DOTACAO.search(texto)
        if dot and dot.group(1) != funcao:
            continue
        contratos = [f"{a.strip()} {b}" for a, b in RE_CONTRATO.findall(texto)]
        eventos.append({
            "data": t["data"], "edicao": t["edicao"], "trecho_id": t["id"],
            "url": t["url_original"], "pagina": t["pagina_estimada"],
            "sha256_edicao": t["sha256_edicao"],
            "estacoes": estacoes,
            "dotacao": dot.group(0) if dot else None,
            "cnpjs": sorted(set(RE_CNPJ.findall(texto))),
            "valores": sorted({_v(v) for v in RE_VALOR.findall(texto)}, reverse=True)[:12],
            "valor_maior": max((_v(v) for v in RE_VALOR.findall(texto)), default=None),
            "contratos": sorted(set(contratos))[:8],
            "processos": sorted(set(RE_PROCESSO.findall(texto)))[:5],
            "objeto": re.sub(r"\s+", " ", texto[:220]),
        })

    # ------------------------------------------------- cobertura das estações
    cont = Counter(e for ev in eventos for e in ev["estacoes"])
    cobertura = {k: cont.get(k, 0) for k in ESTACOES}
    rupturas = [k for k, v in cobertura.items() if v == 0]

    # ------------------------------------------------------ perfil por entidade
    por_cnpj: dict[str, dict] = defaultdict(
        lambda: {"lancamentos": 0, "valor": 0.0, "datas": [], "contratos": set(),
                 "estacoes": set(), "dotacoes": set()})
    for ev in eventos:
        # O valor é rateado entre os CNPJ do mesmo trecho: atribuir o total a
        # cada um multiplicaria o dinheiro. Este número é associação, não soma.
        rateio = (ev["valor_maior"] or 0.0) / max(len(ev["cnpjs"]), 1)
        for c in ev["cnpjs"]:
            k = re.sub(r"\D", "", c)
            r = por_cnpj[k]
            r["lancamentos"] += 1
            r["valor"] += rateio
            r["datas"].append(ev["data"])
            r["contratos"].update(ev["contratos"])
            r["estacoes"].update(ev["estacoes"])
            if ev["dotacao"]:
                r["dotacoes"].add(ev["dotacao"])

    entidades = [{
        "cnpj": f"{k[:2]}.{k[2:5]}.{k[5:8]}/{k[8:12]}-{k[12:]}" if len(k) == 14 else k,
        "lancamentos": v["lancamentos"], "valor": round(v["valor"], 2),
        "primeiro": min(v["datas"]), "ultimo": max(v["datas"]),
        "contratos": sorted(v["contratos"])[:6],
        "com_vinculo": bool(v["contratos"]),
        "estacoes": sorted(v["estacoes"]),
        "dotacoes": sorted(v["dotacoes"])[:6],
    } for k, v in por_cnpj.items()]
    entidades.sort(key=lambda x: -x["valor"])

    # ----------------------------------------------------------- indícios
    achados_ind: list[dict] = []
    base = {"detectado_em": agora().isoformat()}

    # SOB-02: outlier por dotação
    por_dot: dict[str, list] = defaultdict(list)
    for ev in eventos:
        if ev["dotacao"] and ev["valor_maior"]:
            por_dot[ev["dotacao"]].append(ev)
    for dot, evs in por_dot.items():
        vals = [e["valor_maior"] for e in evs]
        if len(vals) < 5:
            continue
        med = statistics.median(vals)
        try:
            desvio = statistics.stdev(vals)
        except statistics.StatisticsError:
            continue
        for e in evs:
            if desvio and e["valor_maior"] > med + 3 * desvio:
                achados_ind.append({**base, "regra": "SOB-02",
                    "severidade": INDICIOS["SOB-02"]["severidade"],
                    "titulo": f"Lançamento discrepante na dotação {dot}",
                    "detalhe": (f"Valor de R$ {e['valor_maior']:,.2f} contra mediana de "
                                f"R$ {med:,.2f} na mesma ação orçamentária. "
                                "Indício, não conclusão: conferir o objeto e o porte do "
                                "serviço antes de qualquer inferência."
                                ).replace(",", "@").replace(".", ",").replace("@", "."),
                    "documento": e["edicao"], "data_ref": e["data"], "url": e["url"]})

    # SOB-05: concentração
    total = sum(x["valor"] for x in entidades)
    if total and len(entidades) >= 4:
        top3 = sum(x["valor"] for x in entidades[:3])
        if top3 / total > 0.6:
            achados_ind.append({**base, "regra": "SOB-05",
                "severidade": INDICIOS["SOB-05"]["severidade"],
                "titulo": "Concentração de repasses em poucas entidades",
                "detalhe": (f"Três de {len(entidades)} entidades identificadas absorvem "
                            f"{100*top3/total:.1f}% do total localizado. Conferir a "
                            "seleção por chamamento público, na forma do artigo 24 da "
                            "Lei 13.019/2014.")})

    # SOB-06: repasse sem vínculo formal
    sem_vinculo = [e for e in entidades if not e["com_vinculo"] and e["valor"] > 0]
    if sem_vinculo:
        achados_ind.append({**base, "regra": "SOB-06",
            "severidade": INDICIOS["SOB-06"]["severidade"],
            "titulo": f"{len(sem_vinculo)} entidade(s) com valor sem vínculo formal identificável",
            "detalhe": ("A publicação associa valor a inscrição no cadastro nacional de "
                        "pessoa jurídica sem indicar contrato, termo de fomento, de "
                        "colaboração ou convênio correspondente. Sem o vínculo não se "
                        "pode aferir objeto, prazo, meta nem prestação de contas.")})

    # SOB-07: parceria sem chamamento
    com_vinculo = {e["edicao"] for e in eventos if "vinculo" in e["estacoes"]}
    com_chamamento = {e["edicao"] for e in eventos
                      if re.search(r"chamamento p[úu]blico", e["objeto"], re.I)}
    sem_cham = com_vinculo - com_chamamento
    if len(sem_cham) >= 3:
        achados_ind.append({**base, "regra": "SOB-07",
            "severidade": INDICIOS["SOB-07"]["severidade"],
            "titulo": f"{len(sem_cham)} publicação(ões) de vínculo sem menção a chamamento público",
            "detalhe": ("Termo de fomento ou colaboração publicado sem que a mesma "
                        "publicação registre chamamento público, dispensa ou "
                        "inexigibilidade. Os artigos 24, 30 e 31 da Lei 13.019/2014 "
                        "exigem o procedimento ou a justificativa expressa de sua "
                        "dispensa.")})

    # rupturas da trilha
    if rupturas:
        achados_ind.append({**base, "regra": "TRI-01", "severidade": "alta",
            "titulo": f"Trilha rompida em {len(rupturas)} estação(ões)",
            "detalhe": ("Nenhuma publicação no acervo permite observar: "
                        + ", ".join(rupturas) + ". O trecho invisível da trilha é o "
                        "mais grave: impede tanto afirmar quanto negar a regularidade. "
                        "É o que fundamenta o pedido com base na Lei 12.527/2011."),
            "saida_sugerida": "minuta_lai"})

    dados = {
        "dominio": dominio["id"], "gerado_em": agora().isoformat(),
        "eventos": len(eventos),
        "cobertura_das_estacoes": cobertura,
        "rupturas": rupturas,
        "integridade_da_trilha": round(
            100 * sum(1 for v in cobertura.values() if v) / len(cobertura), 2),
        "entidades": entidades[:150],
        "entidades_identificadas": len(entidades),
        "valor_associado_a_entidades": round(total, 2),
        "nota_metodologica": ("Valor rateado entre os CNPJ do mesmo trecho. É medida de associação para priorizar conferência, não apuração contábil. A soma exata exige o empenho e a nota fiscal, obtidos por pedido com base na Lei 12.527/2011."),
        "contratos_localizados": sorted({c for ev in eventos for c in ev["contratos"]})[:200],
        "indicios": achados_ind,
        "catalogo_de_indicios": INDICIOS,
        "detalhe": sorted(eventos, key=lambda e: -(e["valor_maior"] or 0))[:300],
    }
    gravar_json(SAIDA, dados)
    log.info("Trilha: %d eventos | integridade %.2f%% | %d entidade(s) | "
             "%d indício(s) | rupturas: %s",
             len(eventos), dados["integridade_da_trilha"], len(entidades),
             len(achados_ind), rupturas or "nenhuma")
    return dados


if __name__ == "__main__":
    nome = sys.argv[1] if len(sys.argv) > 1 else "assistencia_social"
    dom = yaml.safe_load((RAIZ / "config" / "dominios" / f"{nome}.yml").read_text(encoding="utf-8"))
    d = mapear(dom)
    print(json.dumps({k: d[k] for k in
                      ("eventos", "cobertura_das_estacoes", "rupturas",
                       "integridade_da_trilha", "entidades_identificadas",
                       "valor_associado_a_entidades")}, ensure_ascii=False, indent=2))
    for a in d["indicios"]:
        print(f"[{a['regra']}·{a['severidade']}] {a['titulo']}")
