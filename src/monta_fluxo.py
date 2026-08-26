#!/usr/bin/env python3
"""Monta dados/fluxo_2026.json — o modelo de origem, passagem e destino.

Classificação, e a razão de cada cor:
  verde    fonte com ente de origem e código de fonte identificados
  laranja  receita prevista cujo ente de origem não se identifica
  roxo     conta ou unidade por onde o dinheiro passa
  azul     despesa com contrato, termo ou convênio publicado
  vermelho despesa sem vínculo, ou dotação sem execução publicada

Regra dura: publicação com várias inscrições e um valor único não gera um
registro por inscrição. Vira lançamento não atribuível.
"""
import json, re
from pathlib import Path
RAIZ = Path(__file__).resolve().parent.parent

def dv(c):
    n = re.sub(r"\D", "", c)
    if len(n) != 14 or len(set(n)) == 1: return False
    for pos, p in ((12, [5,4,3,2,9,8,7,6,5,4,3,2]), (13, [6,5,4,3,2,9,8,7,6,5,4,3,2])):
        r = sum(int(n[i]) * p[i] for i in range(pos)) % 11
        if int(n[pos]) != (0 if r < 2 else 11 - r): return False
    return True

def main():
    L = lambda p: json.loads((RAIZ / p).read_text(encoding="utf-8"))
    o = L("dados/orcamento_assistencia_social.json")
    tri = L("dados/trilha_dinheiro.json")
    tg = L("config/triagem_cnpj.json")
    NEG = {x["cnpj"] for x in tg["lista_negra_confirmada"]} | \
          {x["cnpj"] for x in tg["dominio_estranho_confirmado"]}

    rd = o["fmas"]["2026"]["receita_detalhada"]; E = o["receitas_vinculadas_loa_2026"]
    sem_fonte = rd["transferencias_correntes"] - E["total_vinculado"]

    fontes = [
     {"id":"f1","nome":"União — Fundo Nacional de Assistência Social","fonte":"1660",
      "valor":E["1.7.1.6.50.0.1"]["valor"],"status":"comprovada","ente":"União",
      "prova":"Lei Orçamentária 11.590/2026, receita 1.7.1.6.50.0.1, fonte 1660"},
     {"id":"f2","nome":"Estado — Assistência Social","fonte":"1661",
      "valor":E["1.7.2.9.51.0.1"]["valor"],"status":"comprovada","ente":"Estado",
      "prova":"Lei Orçamentária 11.590/2026, receita 1.7.2.9.51.0.1, fonte 1661"},
     {"id":"f3","nome":"Estado — Programas de Assistência Social","fonte":"1665",
      "valor":E["1.7.1.7.52.0.1"]["valor"],"status":"comprovada","ente":"Estado",
      "prova":"Lei Orçamentária 11.590/2026, receita 1.7.1.7.52.0.1, fonte 1665"},
     {"id":"f4","nome":"Rendimento de aplicação financeira","fonte":"própria",
      "valor":rd["receita_patrimonial"],"status":"comprovada","ente":"Fundo",
      "prova":"Lei Orçamentária 11.590/2026, receita patrimonial do Fundo"},
     {"id":"f5","nome":"Município — Tesouro Municipal","fonte":"tesouro",
      "valor":rd["tesouro_financiamento_royalties"],"status":"comprovada","ente":"Município",
      "prova":"Lei Orçamentária 11.590/2026, unidade 3650, coluna Tesouro",
      "alerta":"Aporte próprio de R$ 9.000,00 contra R$ 17.354.000,00 recebidos de União e "
               "Estado. O artigo 30, parágrafo único, da Lei 8.742/1993 faz da alocação de "
               "recursos próprios no Fundo condição para o repasse federal."},
     {"id":"f6","nome":"Transferências correntes sem fonte identificada","fonte":"—",
      "valor":sem_fonte,"status":"nao_comprovada","ente":"não identificado","prova":None,
      "falta":"Quadro de Detalhamento de Despesas 2026 com o mapa de fontes"},
     {"id":"f7","nome":"Transferências de capital","fonte":"—",
      "valor":rd["transferencias_de_capital"],"status":"nao_comprovada",
      "ente":"não identificado","prova":None,
      "falta":"Demonstrativo de receita por fonte e ente de origem"},
     {"id":"f8","nome":"Outras receitas correntes","fonte":"—",
      "valor":rd["outras_receitas_correntes"],"status":"nao_comprovada",
      "ente":"não identificado","prova":None,
      "falta":"Relatório Resumido da Execução Orçamentária"}]

    contas = [
     {"id":"c1","nome":"Conta especial do Fundo Municipal de Assistência Social",
      "valor":o["fmas"]["2026"]["total"],"unidade":"3650",
      "base":"Artigo 2º, § 2º, da Lei municipal 7.531/1995","status":"comprovada",
      "nota":"Toda receita da assistência social deve transitar por esta conta. É o ponto "
             "onde o Conselho exerce orientação e controle.",
      "falta":"Extratos mensais da conta especial"},
     {"id":"c2","nome":"Unidade orçamentária 3601 — Gabinete da Secretaria",
      "valor":o["unidades_da_secretaria_2026"]["3601_gabinete_semasdh"]["total"],
      "unidade":"3601","base":"Artigo 2º, § 1º, da Lei municipal 7.531/1995",
      "status":"nao_comprovada",
      "nota":"Integralmente custeada pelo Tesouro Municipal e fora do Fundo. A lei manda "
             "transferir automaticamente ao Fundo a dotação do órgão. O que fica aqui "
             "escapa ao controle do Conselho.",
      "falta":"Segregação da despesa de assistência social dentro da unidade 3601"}]

    despesas, fan = [], 0
    for x in tri.get("detalhe", []):
        d = x.get("data") or ""
        if not d.startswith("2026"): continue
        cn = [c for c in (x.get("cnpjs") or []) if dv(c) and c not in NEG]
        if not cn: continue
        if len(cn) > 1 or not x.get("valor_maior"):
            fan += len(cn); continue
        ct = (x.get("contratos") or [])[:3]
        despesas.append({"tipo":"comprovada" if ct else "sem_vinculo","cnpj":cn[0],
          "valor":x["valor_maior"],"data":d,"vinculo":ct,"dotacao":x.get("dotacao"),
          "processo":(x.get("processos") or [None])[0],
          "objeto":re.sub(r"\s+"," ",(x.get("objeto") or ""))[:200],"edicao":x.get("edicao"),
          "conta":"c1",
          **({} if ct else {"falta":"Contrato, termo de fomento, convênio ou ata de "
                                    "registro de preços que justifique o pagamento"})})

    acoes = [{"id":k,"nome":v["nome"],"valor":v["valor"],"status":"nao_comprovada",
              "falta":"Empenho, liquidação e pagamento; detalhamento por unidade e serviço"}
             for k, v in sorted(o["acoes_fmas_2026"].items(), key=lambda i: -i[1]["valor"])]

    saida = {"exercicio":2026,"fontes":fontes,"contas":contas,"despesas":despesas,
     "acoes":acoes,
     "fanout":{"lancamentos":fan,
       "nota":"Publicação com várias inscrições e um valor único. Atribuir esse valor a "
              "cada inscrição multiplicaria o gasto."},
     "totais":{
       "fonte_comprovada":sum(f["valor"] for f in fontes if f["status"]=="comprovada"),
       "fonte_nao_comprovada":sum(f["valor"] for f in fontes if f["status"]=="nao_comprovada"),
       "despesa_comprovada":sum(x["valor"] for x in despesas if x["tipo"]=="comprovada"),
       "despesa_sem_vinculo":sum(x["valor"] for x in despesas if x["tipo"]=="sem_vinculo"),
       "fundo":o["fmas"]["2026"]["total"],
       "fora_do_fundo":o["unidades_da_secretaria_2026"]["3601_gabinete_semasdh"]["total"]}}

    T = saida["totais"]
    assert abs(T["fonte_comprovada"] + T["fonte_nao_comprovada"] - T["fundo"]) < 1, \
"fontes não fecham com o total do Fundo"
    (RAIZ/"dados"/"fluxo_2026.json").write_text(
        json.dumps(saida, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  fontes {len(fontes)} · contas {len(contas)} · despesas {len(despesas)} · "
          f"fan-out {fan} · confere com o Fundo")

if __name__ == "__main__":
    main()
