#!/usr/bin/env python3
"""Concilia a receita da assistência social entre previsão anual e entrada mensal.

A pergunta que o módulo responde: o dinheiro entra em parcelas mensais, ou existe
um depósito único que vai sendo consumido? São regimes diferentes, com controles
diferentes, e a resposta muda a fiscalização.

  Fundo a fundo (União e Estado) — parcela mensal, regular e automática.
    Artigo 30 da Lei 8.742/1993 e Resolução CNAS 33/2012.
  Tesouro Municipal — liberação conforme a programação financeira.
    Artigo 2º, § 1º, da Lei municipal 7.531/1995 manda transferir ao Fundo
    tão logo realizada a receita.
  Superávit de exercícios anteriores — saldo acumulado, reaberto por decreto.
    Artigo 43, § 1º, inciso I, da Lei 4.320/1964. Não é entrada nova: é sobra.

O acervo só tem previsão. A realização mensal não está publicada, e isso é o
achado — não uma limitação a contornar por estimativa.
"""
from __future__ import annotations
import json
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
L = lambda p: json.loads((RAIZ / p).read_text(encoding="utf-8"))
MESES = ["janeiro","fevereiro","março","abril","maio","junho",
         "julho","agosto","setembro","outubro","novembro","dezembro"]

def main():
    orc = L("dados/orcamento_assistencia_social.json")
    igd = L("dados/igd_controle_social.json")
    fin = L("dados/financeiro.json")
    f26 = orc["fmas"]["2026"]; rd = f26["receita_detalhada"]; E = orc["receitas_vinculadas_loa_2026"]

    fontes = [
     {"fonte":"1660","nome":"União — Fundo Nacional de Assistência Social",
      "anual":E["1.7.1.6.50.0.1"]["valor"],"regime":"fundo a fundo, parcela mensal",
      "norma":"Artigo 30 da Lei 8.742/1993; Resolução CNAS 33/2012",
      "esperado_mensal":round(E["1.7.1.6.50.0.1"]["valor"]/12,2),
      "contem_igd":True},
     {"fonte":"1661","nome":"Estado — Assistência Social","anual":E["1.7.2.9.51.0.1"]["valor"],
      "regime":"transferência estadual","norma":"convênio ou repasse fundo a fundo estadual",
      "esperado_mensal":round(E["1.7.2.9.51.0.1"]["valor"]/12,2),"contem_igd":False},
     {"fonte":"1665","nome":"Estado — Programas de Assistência Social",
      "anual":E["1.7.1.7.52.0.1"]["valor"],"regime":"transferência estadual","norma":"—",
      "esperado_mensal":round(E["1.7.1.7.52.0.1"]["valor"]/12,2),"contem_igd":False},
     {"fonte":"tesouro","nome":"Município — Tesouro Municipal",
      "anual":rd["tesouro_financiamento_royalties"],
      "regime":"programação financeira; transferência automática ao Fundo",
      "norma":"Artigo 2º, § 1º, da Lei municipal 7.531/1995",
      "esperado_mensal":round(rd["tesouro_financiamento_royalties"]/12,2),"contem_igd":False},
     {"fonte":"patrimonial","nome":"Rendimento de aplicação financeira",
      "anual":rd["receita_patrimonial"],"regime":"crédito mensal sobre saldo aplicado",
      "norma":"Artigo 2º, inciso IV, da Lei municipal 7.531/1995",
      "esperado_mensal":round(rd["receita_patrimonial"]/12,2),"contem_igd":False},
     {"fonte":"nao_identificada","nome":"Transferências correntes sem fonte declarada",
      "anual":rd["transferencias_correntes"]-E["total_vinculado"],"regime":"indeterminado",
      "norma":"—","esperado_mensal":round((rd["transferencias_correntes"]-E["total_vinculado"])/12,2),
      "contem_igd":False},
     {"fonte":"capital","nome":"Transferências de capital","anual":rd["transferencias_de_capital"],
      "regime":"parcela única ou por etapa de projeto","norma":"—",
      "esperado_mensal":None,"contem_igd":False},
    ]

    base_igd = igd["base_do_indice"]["total"]
    igd_mensal = round(base_igd/12,2); dev_mensal = round(igd_mensal*0.10,2)
    reservado_federal = igd["dotacao_do_conselho"]["federal_fonte_do_indice"]

    competencias = []
    for i, m in enumerate(MESES, start=1):
        competencias.append({
          "competencia": f"2026-{i:02d}", "mes": m,
          "previsto_total": round(f26["total"]/12,2),
          "previsto_por_fonte": {f["fonte"]: f["esperado_mensal"] for f in fontes if f["esperado_mensal"]},
          "igd": {"base_mensal_estimada": igd_mensal,
                  "devido_ao_conselho_10": dev_mensal,
                  "aplicado_publicado": None,
                  "situacao": "SEM DEMONSTRATIVO PUBLICADO"},
          "realizado": None,
          "situacao": "NÃO PUBLICADO"})

    ldo = {"meta_financeira_do_setor": 41265955.98,
      "setor":"Políticas Públicas para Mulher, Direitos Humanos e Assistência Social",
      "fonte":"Lei de Diretrizes Orçamentárias 11.589/2026, Anexo III, Metas e Prioridades",
      "acoes_na_meta":["Goiânia + direitos humanos","Rede + mulher",
        "Manutenção dos serviços e da rede","Ação acolher e cuidar (primeira infância)",
        "Manutenção dos cemitérios"],
      "observacao":"A meta reúne três políticas distintas — mulher, direitos humanos e "
        "assistência social — e ainda inclui manutenção de cemitérios. Não é comparável "
        "diretamente com a função 08. A inclusão de cemitérios no setor da assistência "
        "social é do próprio Município, não erro de leitura.",
      "cmasgyn_nas_metas": False,
      "nota_cmasgyn":"O Conselho Municipal de Assistência Social não figura entre as metas "
        "e prioridades da Lei de Diretrizes Orçamentárias de 2026."}

    conciliacao = {
      "loa_funcao_08": orc["funcao_08_assistencia_social"]["2026"],
      "loa_fundo": f26["total"],
      "ldo_meta_setor": ldo["meta_financeira_do_setor"],
      "diferenca_ldo_menos_funcao08": round(ldo["meta_financeira_do_setor"]-orc["funcao_08_assistencia_social"]["2026"],2),
      "leitura":"A meta da Lei de Diretrizes supera a função 08 da Lei Orçamentária em "
        f"{ldo['meta_financeira_do_setor']-orc['funcao_08_assistencia_social']['2026']:,.2f}, "
        "porque agrega políticas de mulher e direitos humanos, além de cemitérios. Só o "
        "detalhamento por ação permite separar o que é assistência social."}

    regime = {
      "pergunta":"O dinheiro entra em parcela mensal ou é depósito único consumido ao longo do ano?",
      "resposta":"Os dois regimes convivem, e é preciso separá-los.",
      "parcela_mensal":["fonte 1660 — repasse federal fundo a fundo, regular e automático",
        "fonte 1661 e 1665 — transferências estaduais",
        "rendimento de aplicação, creditado mensalmente sobre o saldo"],
      "saldo_acumulado":{
        "descricao":"Superávit financeiro de exercícios anteriores, reaberto por decreto de "
          "crédito adicional. Não é entrada nova: é sobra do que não se gastou.",
        "valor_2026": sum(x.get("valor") or 0 for x in fin.get("detalhe",[])
                          if (x.get("data") or "").startswith("2026")
                          and str(x.get("fonte") or "").startswith("2")),
        "norma":"Artigo 43, § 1º, inciso I, da Lei 4.320/1964",
        "exige":"superávit apurado em Balanço Patrimonial do exercício anterior"},
      "indicio":"A receita patrimonial de "
        f"{rd['receita_patrimonial']:,.2f} sobre um Fundo de {f26['total']:,.2f} — "
        f"{100*rd['receita_patrimonial']/f26['total']:.1f}% — pressupõe saldo médio aplicado "
        "próximo do orçamento anual inteiro. É o retrato de um fundo que acumula e não executa.",
      "o_que_falta":"Extratos mensais da conta especial do Fundo e Relatório Resumido da "
        "Execução Orçamentária. Sem eles, não se distingue o que entrou do que sobrou."}

    saida = {"exercicio":2026,"fontes":fontes,"competencias":competencias,
      "ldo":ldo,"conciliacao":conciliacao,"regime_de_entrada":regime,
      "igd_mensal":{"base_anual":base_igd,"base_mensal_estimada":igd_mensal,
        "devido_mensal_ao_conselho":dev_mensal,"devido_anual":round(base_igd*0.10,2),
        "reservado_na_fonte_federal":reservado_federal,
        "competencias_com_demonstrativo":0,
        "norma":"Artigo 6º da Resolução CNAS/MDS 202/2025",
        "leitura":f"O piso incide sobre o repasse de cada mês. Estimando a base em doze "
          f"parcelas, seriam {dev_mensal:,.2f} por competência. Nenhuma das doze tem "
          "demonstrativo publicado. A estimativa serve para dimensionar, não para acusar: "
          "o repasse real varia mês a mês e só a Consulta de Pagamentos do Fundo Nacional o revela."},
      "achado":"Nenhuma das doze competências de 2026 tem receita realizada publicada. "
        "A conciliação entre previsto e realizado é impossível com o que está público."}

    (RAIZ/"dados"/"receita_mensal_2026.json").write_text(
        json.dumps(saida, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  previsto anual do Fundo   R$ {f26['total']:>13,.2f}")
    print(f"  meta do setor na LDO      R$ {ldo['meta_financeira_do_setor']:>13,.2f}")
    print(f"  saldo de exercícios ant.  R$ {regime['saldo_acumulado']['valor_2026']:>13,.2f}")
    print(f"  IGD devido por mês        R$ {dev_mensal:>13,.2f}  ·  12 competências sem demonstrativo")
    print(f"  competências com receita realizada publicada: 0 de 12")

if __name__ == "__main__":
    main()
