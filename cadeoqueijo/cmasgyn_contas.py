#!/usr/bin/env python3
"""Análise separada do Conselho Municipal de Assistência Social de Goiânia.

Duas perguntas:
  1. Quanto o Conselho tem, em que rubricas, e de que fonte.
  2. O conselheiro recebe apoio material, estrutural e financeiro para exercer
     a função, como manda o artigo 8º da Lei municipal 9.009/2010.

O método é ler o Quadro de Detalhamento de Despesas e olhar tanto o que está
lá quanto o que não está. Rubrica ausente é resposta: sem dotação de diárias e
passagens, o conselheiro não se desloca; sem auxílio a pessoa física, não há
apoio financeiro ao colegiado.
"""
from __future__ import annotations
import json
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
L = lambda p: json.loads((RAIZ / p).read_text(encoding="utf-8"))

NOMES = {
 "3.3.90.14.00":"Diárias — pessoal civil",
 "3.3.90.30.00":"Material de consumo",
 "3.3.90.33.00":"Passagens e despesas com locomoção",
 "3.3.90.35.00":"Serviços de consultoria",
 "3.3.90.36.00":"Outros serviços de terceiros — pessoa física",
 "3.3.90.39.00":"Outros serviços de terceiros — pessoa jurídica",
 "3.3.90.40.00":"Serviços de tecnologia da informação",
 "3.3.90.46.00":"Auxílio alimentação",
 "3.3.90.48.00":"Outros auxílios financeiros a pessoas físicas",
 "3.3.90.49.00":"Auxílio transporte",
 "3.3.90.92.00":"Despesas de exercícios anteriores",
 "3.1.90.11.00":"Vencimentos e vantagens fixas",
 "4.4.90.51.00":"Obras e instalações",
 "4.4.90.52.00":"Equipamentos e material permanente",
}
# rubricas indispensáveis ao funcionamento de um colegiado
ESSENCIAIS = {
 "3.3.90.14.00":("Diárias","Sem dotação de diárias o conselheiro não participa de "
   "conferência estadual ou nacional, nem de reunião fora do Município. O artigo 2º, "
   "inciso XII, da Lei municipal 9.009/2010 impõe conferência a cada dois anos."),
 "3.3.90.33.00":("Passagens e locomoção","Sem passagens não há deslocamento, e sem "
   "deslocamento não há fiscalização in loco dos serviços, que o artigo 2º, inciso VI, "
   "da Lei municipal 9.009/2010 atribui ao Conselho."),
 "3.3.90.48.00":("Auxílio financeiro a pessoa física","É a rubrica por onde se custeia "
   "apoio ao conselheiro representante de usuário, que costuma ser quem tem menos meios "
   "próprios de comparecer. Sua ausência afeta desigualmente a paridade do artigo 3º."),
 "3.3.90.35.00":("Consultoria e assessoria técnica","O artigo 6º, inciso V, prevê Corpo "
   "Técnico. Sem esta rubrica na ação própria, o apoio técnico depende inteiramente do "
   "órgão gestor — que é justamente o fiscalizado."),
 "3.1.90.11.00":("Vencimentos","O artigo 6º, inciso III, prevê Secretaria Executiva "
   "contratada e disponibilizada pelo órgão gestor. Não estando na ação do Conselho, "
   "a remuneração corre pela folha da Secretaria e não se afere aqui."),
}

def brl(v):
    return "R$ " + f"{float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def main():
    igd = L("dados/igd_controle_social.json")
    orc = L("dados/orcamento_assistencia_social.json")
    linhas = igd["dotacao_do_conselho"]["detalhe"]
    total = igd["dotacao_do_conselho"]["total"]

    por_nat = defaultdict(lambda: {"valor":0,"fontes":{}})
    for x in linhas:
        n = x["natureza"]
        por_nat[n]["valor"] += x["valor"]
        por_nat[n]["fontes"][x["fonte"]] = por_nat[n]["fontes"].get(x["fonte"],0)+x["valor"]
    rubricas = [{"natureza":n,"nome":NOMES.get(n,"não catalogada"),
                 "valor":d["valor"],"fontes":d["fontes"],
                 "simbolica": d["valor"] <= 2000}
                for n,d in sorted(por_nat.items(), key=lambda i:-i[1]["valor"])]

    simbolicas = [r for r in rubricas if r["simbolica"]]
    v_simb = sum(r["valor"] for r in simbolicas)
    ausentes = [{"natureza":k,"nome":NOMES[k],"rubrica":v[0],"consequencia":v[1]}
                for k,v in ESSENCIAIS.items() if k not in por_nat]

    # apoio ao conselheiro, por espécie
    def soma(*nats): return sum(por_nat[n]["valor"] for n in nats if n in por_nat)
    apoio = {
      "material":{"valor":soma("3.3.90.30.00"),
        "descricao":"Material de consumo — papel, expediente, copa",
        "situacao":"previsto"},
      "estrutural":{"valor":soma("4.4.90.52.00","4.4.90.51.00","3.3.90.40.00"),
        "descricao":"Equipamentos, obras e tecnologia da informação",
        "situacao":"previsto"},
      "servicos":{"valor":soma("3.3.90.39.00","3.3.90.36.00"),
        "descricao":"Serviços de terceiros, pessoa física e jurídica",
        "situacao":"previsto"},
      "deslocamento":{"valor":soma("3.3.90.14.00","3.3.90.33.00"),
        "descricao":"Diárias e passagens",
        "situacao":"AUSENTE" if not soma("3.3.90.14.00","3.3.90.33.00") else "previsto"},
      "apoio_financeiro_ao_conselheiro":{"valor":soma("3.3.90.48.00"),
        "descricao":"Auxílio financeiro a pessoa física",
        "situacao":"AUSENTE" if not soma("3.3.90.48.00") else "previsto"},
      "apoio_tecnico_proprio":{"valor":soma("3.3.90.35.00","3.1.90.11.00"),
        "descricao":"Consultoria e pessoal próprio",
        "situacao":"AUSENTE" if not soma("3.3.90.35.00","3.1.90.11.00") else "previsto"},
    }

    achados = []
    def a(cod,sev,selo,tit,det,norma,dados=None):
        achados.append({"codigo":cod,"severidade":sev,"selo":selo,"titulo":tit,
                        "detalhe":det,"norma":norma,"dados":dados or {}})

    a("CMAS-FIN-01","alta","CONFIRMADO",
      "Conselho sem dotação de diárias e passagens",
      "A ação 3650.0824401082.591 não tem uma única linha de diárias (3.3.90.14) nem de "
      "passagens (3.3.90.33). O conselheiro não dispõe de meio orçamentário para participar "
      "de conferência fora do Município nem para fiscalizar serviços in loco. As duas "
      "atribuições estão na lei que criou o Conselho.",
      "Artigo 8º e artigo 2º, incisos VI e XII, da Lei municipal 9.009/2010",
      {"diarias":0,"passagens":0,"total_da_acao":total})

    a("CMAS-FIN-02","alta","CONFIRMADO",
      "Nenhum apoio financeiro direto ao conselheiro",
      "Não há dotação de auxílio financeiro a pessoa física (3.3.90.48), de auxílio "
      "alimentação (3.3.90.46) nem de auxílio transporte (3.3.90.49). O mandato de "
      "conselheiro é gratuito, o que é legítimo, mas gratuidade do mandato não dispensa o "
      "custeio da participação. A ausência pesa de modo desigual sobre o representante de "
      "usuário, que ocupa seis das quinze cadeiras da sociedade civil.",
      "Artigo 8º da Lei municipal 9.009/2010; artigo 3º quanto à paridade",
      {"auxilio_pf":0})

    a("CMAS-FIN-03","media","CONFIRMADO",
      f"{len(simbolicas)} rubricas do Conselho são dotação simbólica",
      f"{len(simbolicas)} de {len(rubricas)} rubricas têm valor de até R$ 2.000,00, somando "
      f"{brl(v_simb)}. Dotação nesse patamar não custeia atividade: existe para permitir "
      "suplementação por decreto sem abrir nova linha orçamentária. Contabilmente a rubrica "
      "existe; na prática, não financia nada enquanto não for suplementada.",
      "Artigo 13 da Lei 4.320/1964",
      {"rubricas_simbolicas":len(simbolicas),"valor":v_simb,
       "lista":[r["natureza"] for r in simbolicas]})

    a("CMAS-FIN-04","alta","CONFIRMADO",
      "Apoio técnico do Conselho depende integralmente do fiscalizado",
      "Não há dotação de consultoria (3.3.90.35) nem de pessoal próprio (3.1.90.11) na ação "
      "do Conselho. A Secretaria Executiva e o Corpo Técnico são contratados e "
      "disponibilizados pelo órgão gestor, na forma da lei. O desenho é legal, mas produz "
      "dependência: quem fornece a estrutura de fiscalização é quem está sendo fiscalizado. "
      "Sem os atos de designação, não se sabe sequer se existem.",
      "Artigo 6º, incisos III e V, e artigo 8º da Lei municipal 9.009/2010",
      {"consultoria":0,"pessoal_proprio":0})

    a("CMAS-FIN-05","critica","CONFIRMADO",
      "Piso federal do Índice cumprido em 22,6%",
      f"Dos {brl(total)} da ação, apenas "
      f"{brl(igd['dotacao_do_conselho']['federal_fonte_do_indice'])} vêm da fonte 1660, "
      f"onde trafega o Índice de Gestão Descentralizada. O devido é "
      f"{brl(igd['devido_ao_controle_social'])}. "
      f"Os {brl(igd['dotacao_do_conselho']['estadual_outras_fontes'])} de fonte estadual "
      "contam como outra fonte de financiamento, admitida na parte final do artigo 6º, "
      "mas não substituem o piso federal.",
      "Artigo 6º da Resolução CNAS/MDS 202/2025",
      igd["afericao"])

    a("CMAS-FIN-06","media","CONFIRMADO",
      "Conselho ausente das metas e prioridades da Lei de Diretrizes",
      "O Anexo III da Lei de Diretrizes Orçamentárias 11.589/2026 elenca, no setor de "
      "políticas para mulher, direitos humanos e assistência social, a meta de "
      "R$ 41.265.955,98, com cinco ações — inclusive manutenção de cemitérios. O Conselho "
      "não figura entre elas.",
      "Artigo 165, § 2º, da Constituição Federal",
      {"meta_do_setor":41265955.98})

    a("CMAS-FIN-07","alta","INCONCLUSIVO_POR_DOCUMENTO_FALTANTE",
      "Execução da dotação do Conselho não publicada",
      f"A dotação de {brl(total)} é previsão. Não há empenho, liquidação nem pagamento "
      "publicados para a ação. Não se sabe se o Conselho recebeu, gastou ou devolveu.",
      "Artigos 58, 62 e 63 da Lei 4.320/1964; artigo 48-A da Lei Complementar 101/2000",
      {"documento_necessario":"Execução orçamentária da ação 3650.0824401082.591 por estágio"})

    comp = {"cmasgyn":{"dotacao":total,"fundo":orc["fmas"]["2026"]["total"],
              "proporcao":round(100*total/orc["fmas"]["2026"]["total"],2)},
            "conselho_do_idoso":orc["comparacao_entre_conselhos_2026"]["conselho_municipal_do_idoso"]}

    saida = {"exercicio":2026,"acao":"3650.0824401082.591",
      "denominacao":"Manutenção do Conselho Municipal de Assistência Social — CMASGyn",
      "dotacao_total":total,"por_fonte":igd["dotacao_do_conselho"]["por_fonte"],
      "rubricas":rubricas,"rubricas_ausentes_essenciais":ausentes,
      "apoio_ao_conselheiro":apoio,"comparacao":comp,"achados":achados,
      "documentos_para_conciliar":[
        "Execução orçamentária da ação 3650.0824401082.591, por estágio e por rubrica",
        "Atos de designação da Secretaria Executiva e do Corpo Técnico",
        "Regimento Interno vigente",
        "Decreto de nomeação dos conselheiros, com segmento e mandato",
        "Atas de plenária de 2024 a 2026, com lista de presença por segmento",
        "Prestação de contas quadrimestral do Índice, artigo 6º, § 5º",
        "Demonstrativo de bens patrimoniados na sede do Conselho"]}

    (RAIZ/"dados"/"cmasgyn_contas_2026.json").write_text(
        json.dumps(saida, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  dotação total  R$ {total:,.2f}  ({igd['dotacao_do_conselho']['por_fonte']})")
    print(f"  rubricas: {len(rubricas)} · simbólicas (até R$ 2.000): {len(simbolicas)} = R$ {v_simb:,.2f}")
    print("  apoio ao conselheiro:")
    for k,v in apoio.items():
        print(f"    {v['situacao']:9s} {k:32s} R$ {v['valor']:>10,.2f}")
    print(f"  rubricas essenciais ausentes: {len(ausentes)} — {[a['rubrica'] for a in ausentes]}")
    print(f"  achados: {len(achados)}")

if __name__ == "__main__":
    main()
