#!/usr/bin/env python3
"""Verificação individualizada por competência (mês) do exercício de 2026.

Aplica, mês a mês, os parâmetros que têm natureza mensal:

  REC-M  publicação da receita realizada da competência
  IGD-M  demonstrativo do piso de 10% do IGD ao controle social na competência
  PUB-M  circulação do Diário Oficial nos dias úteis do mês
  EXE-M  execução da despesa publicada no mês (estações da trilha)
  CMAS-M publicidade dos atos do Conselho citados no mês

Regras herdadas do projeto, sem exceção:
  - só desconformidade entra no relatório;
  - todo achado carrega selo CONFIRMADO, INDICIARIO ou
    INCONCLUSIVO_POR_DOCUMENTO_FALTANTE;
  - dado faltante é achado, não silêncio;
  - norma citada por extenso;
  - tudo determinístico — nenhuma chamada de modelo (camada 0 do roteador).

Uso: python3 src/verifica_mensal.py 2026-01
Saída: relatorios/mensal/verificacao_2026-MM.json
"""
from __future__ import annotations
import json, re, sys
from datetime import date, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DADOS = RAIZ / "dados"
SAIDA = RAIZ / "relatorios" / "mensal"

FERIADOS_GOIANIA_2026 = {
    "2026-01-01", "2026-02-16", "2026-02-17", "2026-04-03", "2026-04-21",
    "2026-05-01", "2026-05-24", "2026-06-04", "2026-09-07", "2026-10-12",
    "2026-10-24", "2026-11-02", "2026-11-15", "2026-12-25",
}  # nacionais, aniversário da cidade (24/10) e N. S. Auxiliadora (24/05)

MESES = {1: "janeiro", 2: "fevereiro", 3: "março", 4: "abril", 5: "maio",
         6: "junho", 7: "julho", 8: "agosto", 9: "setembro", 10: "outubro",
         11: "novembro", 12: "dezembro"}


def carrega(nome):
    return json.loads((DADOS / nome).read_text(encoding="utf-8"))


def dias_uteis_do_mes(ano, mes):
    d = date(ano, mes, 1)
    uteis = []
    while d.month == mes:
        if d.weekday() < 5 and d.isoformat() not in FERIADOS_GOIANIA_2026:
            uteis.append(d.isoformat())
        d += timedelta(days=1)
    return uteis


def edicoes_conhecidas():
    """Varre todos os JSON de dados atrás de nomes de edição do Diário
    (do_YYYYMMDD_0000NNNN.pdf). Devolve {data_iso: {numeros}} e o conjunto
    ordenado de números sequenciais, para detectar lacuna de numeração —
    tarefa da camada determinística (detectar_lacuna_de_numeracao)."""
    padrao = re.compile(r"do_(\d{8})_0*(\d+)\.pdf")
    por_dia, numeros = {}, set()
    for arq in DADOS.glob("*.json"):
        for m in padrao.finditer(arq.read_text(encoding="utf-8")):
            iso = f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:]}"
            n = int(m.group(2))
            por_dia.setdefault(iso, set()).add(n)
            numeros.add((iso, n))
    return por_dia, sorted(numeros, key=lambda t: t[1])


def analisa_mes(competencia: str) -> dict:
    ano, mes = int(competencia[:4]), int(competencia[5:7])
    nome_mes = MESES[mes]
    achados = []

    receita = carrega("receita_mensal_2026.json")
    trilha = carrega("trilha_dinheiro.json")
    biblio = carrega("biblioteca_cmasgyn.json")

    comp = next((c for c in receita["competencias"]
                 if c["competencia"] == competencia), None)

    # ------------------------------------------------------------- REC-M
    if comp and comp.get("realizado") is None:
        achados.append({
            "codigo": f"REC-M-{competencia}", "bloco": "SEMASDH",
            "severidade": "alta", "selo": "INCONCLUSIVO_POR_DOCUMENTO_FALTANTE",
            "titulo": f"Receita realizada de {nome_mes} de {ano} não publicada",
            "detalhe": (f"A previsão da competência é de R$ {comp['previsto_total']:,.2f} "
                        "somadas as fontes, mas nenhum demonstrativo de receita "
                        "realizada do mês foi localizado em publicação oficial. Sem "
                        "o realizado, a conciliação entre entrada e saída do Fundo "
                        "fica impedida para a competência."),
            "norma": ("Artigo 48 e Artigo 48-A da Lei Complementar 101/2000; "
                      "Artigo 8º, § 1º, da Lei 12.527/2011"),
            "impedimento": "conciliação receita×despesa da competência",
            "onde_obter": "portal da transparência do Município ou SICONFI",
            "dados": {"previsto_total": comp["previsto_total"],
                      "previsto_por_fonte": comp["previsto_por_fonte"]},
        })

    # ------------------------------------------------------------- IGD-M
    if comp:
        igd = comp.get("igd", {})
        devido = igd.get("devido_ao_conselho_10")
        aplicado = igd.get("aplicado_publicado")
        if aplicado is None:
            achados.append({
                "codigo": f"IGD-M-{competencia}", "bloco": "CMAS",
                "severidade": "critica",
                "selo": "INCONCLUSIVO_POR_DOCUMENTO_FALTANTE",
                "titulo": (f"Piso de 10% do IGD ao controle social: aplicação de "
                           f"{nome_mes} de {ano} sem demonstrativo"),
                "detalhe": (f"Estimados R$ {igd.get('base_mensal_estimada', 0):,.2f} "
                            f"de base na competência, o piso devido ao Conselho é de "
                            f"R$ {devido:,.2f}. A norma incide competência a "
                            "competência: aplicar o percentual sobre o acumulado do "
                            "ano não a satisfaz. Nenhum demonstrativo de aplicação "
                            "do mês foi publicado. A planilha do Fundo Nacional "
                            "disponível alcança a competência 2025-11, de modo que "
                            "o repasse efetivo de 2026 tampouco é conferível por "
                            "via federal até a atualização da extração."),
                "norma": ("Artigo 6º da Resolução CNAS/MDS 202/2025; "
                          "Artigo 14, § 7º, da Lei 14.601/2023"),
                "impedimento": "aferição do piso mensal de 10% na competência",
                "onde_obter": ("demonstrativo mensal do Fundo Municipal e extração "
                               "de repasses do Fundo Nacional quando alcançar 2026"),
                "dados": {"base_mensal_estimada": igd.get("base_mensal_estimada"),
                          "devido_ao_conselho_10": devido,
                          "sancao": ("bloqueio dos repasses até a comprovação — "
                                     "Artigo 6º, § 6º, da Resolução CNAS/MDS "
                                     "202/2025")},
            })
        elif devido and aplicado < devido:
            achados.append({
                "codigo": f"IGD-M-{competencia}", "bloco": "CMAS",
                "severidade": "critica", "selo": "CONFIRMADO",
                "titulo": (f"Piso de 10% do IGD descumprido em {nome_mes} "
                           f"de {ano}"),
                "detalhe": (f"Devidos R$ {devido:,.2f}, aplicados "
                            f"R$ {aplicado:,.2f} — diferença de "
                            f"R$ {devido - aplicado:,.2f} na competência."),
                "norma": ("Artigo 6º da Resolução CNAS/MDS 202/2025; "
                          "Artigo 14, § 7º, da Lei 14.601/2023"),
                "dados": {"devido": devido, "aplicado": aplicado},
            })

    # ------------------------------------------------------------- PUB-M
    uteis = dias_uteis_do_mes(ano, mes)
    por_dia, seq = edicoes_conhecidas()
    dias_com_edicao = sorted(d for d in por_dia if d.startswith(competencia))
    uteis_sem = [d for d in uteis if d not in por_dia]
    numeros_mes = sorted(n for d, n in seq if d.startswith(competencia))
    lacunas = []
    for a, b in zip(numeros_mes, numeros_mes[1:]):
        if b - a > 1:
            lacunas.append({"entre": [a, b], "faltam": b - a - 1})
    hoje = date.today().isoformat()
    if uteis_sem and competencia <= hoje[:7]:
        # dias úteis sem edição conhecida no acervo: como o acervo é amostral
        # (só edições citadas nos dados), a ausência isolada é INDICIARIA;
        # vira CONFIRMADA quando também há lacuna na numeração sequencial,
        # que é via independente da amostragem.
        selo = "CONFIRMADO" if lacunas else "INDICIARIO"
        via = ("dupla via: dias úteis sem edição no acervo E lacuna na "
               "numeração sequencial das edições vizinhas"
               if lacunas else
               "via única: ausência no acervo amostral de edições citadas")
        achados.append({
            "codigo": f"PUB-M-{competencia}", "bloco": "SEMASDH",
            "severidade": "alta" if len(uteis_sem) > 5 else "media",
            "selo": selo,
            "titulo": (f"Diário Oficial: {len(uteis_sem)} de {len(uteis)} dias "
                       f"úteis de {nome_mes} de {ano} sem edição localizada"),
            "detalhe": (f"O mês teve {len(uteis)} dias úteis; localizaram-se "
                        f"edições em {len(dias_com_edicao)} dias. {via.capitalize()}."
                        + (f" Lacunas de numeração no mês: {lacunas}."
                           if lacunas else "")),
            "norma": ("Artigo 37, caput, da Constituição da República — princípio "
                      "da publicidade; Artigo 8º da Lei 12.527/2011"),
            "dados": {"dias_uteis": len(uteis), "dias_com_edicao":
                      len(dias_com_edicao), "dias_uteis_sem_edicao": uteis_sem,
                      "lacunas_numeracao": lacunas},
        })

    # ------------------------------------------------------------- EXE-M
    ESTACOES = ("dotacao", "empenho", "liquidacao", "pagamento", "vinculo")
    evs = [e for e in trilha["detalhe"]
           if str(e.get("data", "")).startswith(competencia)]
    contagem = {est: sum(1 for e in evs if est in (e.get("estacoes") or []))
                for est in ESTACOES}
    valor_mes = sum(max(e.get("valores") or [0]) for e in evs
                    if e.get("valores"))
    sem_liq_pag = contagem["liquidacao"] == 0 and contagem["pagamento"] == 0
    if evs and sem_liq_pag:
        achados.append({
            "codigo": f"EXE-M-{competencia}", "bloco": "SEMASDH",
            "severidade": "critica", "selo": "CONFIRMADO",
            "titulo": (f"Execução sem liquidação nem pagamento publicados em "
                       f"{nome_mes} de {ano}"),
            "detalhe": (f"O mês registra {len(evs)} eventos na trilha do "
                        f"dinheiro ({contagem['empenho']} com estação de "
                        f"empenho, {contagem['dotacao']} de dotação, "
                        f"{contagem['vinculo']} de vínculo), e nenhum evento "
                        "de liquidação ou pagamento. Dotação e empenho não "
                        "comprovam saída de dinheiro: sem os estágios do "
                        "Artigo 63 e do Artigo 64 da Lei 4.320/1964 publicados, "
                        "o destino efetivo dos recursos do mês permanece "
                        "desconhecido."),
            "norma": ("Artigo 62, Artigo 63 e Artigo 64 da Lei 4.320/1964; "
                      "Artigo 48-A, inciso I, da Lei Complementar 101/2000"),
            "dados": {"eventos": len(evs), "por_estacao": contagem,
                      "maior_valor_citado": valor_mes},
        })
    elif not evs and competencia <= hoje[:7]:
        achados.append({
            "codigo": f"EXE-M-{competencia}", "bloco": "SEMASDH",
            "severidade": "alta",
            "selo": "INCONCLUSIVO_POR_DOCUMENTO_FALTANTE",
            "titulo": (f"Nenhum evento de execução localizado em {nome_mes} "
                       f"de {ano}"),
            "detalhe": ("A trilha do dinheiro não registra evento algum na "
                        "competência. Ou não houve publicação, ou as edições "
                        "do período não circularam — as duas hipóteses são "
                        "desconformidade; nenhuma delas é conformidade."),
            "norma": "Artigo 48-A, inciso I, da Lei Complementar 101/2000",
            "impedimento": "qualquer aferição de execução na competência",
            "onde_obter": "URL_TRANSPARENCIA (pendência P2) e edições do Diário",
            "dados": {"eventos": 0},
        })

    # ------------------------------------------------------------- CMAS-M
    citados_no_mes = []
    for ato in biblio.get("atos", []):
        for c in ato.get("citacoes", []):
            if str(c.get("data", "")).startswith(competencia):
                if ato.get("situacao") == "APENAS_CITADO":
                    citados_no_mes.append(ato["chave"])
                break
    citados_no_mes = sorted(set(citados_no_mes))
    if citados_no_mes:
        achados.append({
            "codigo": f"CMAS-M-{competencia}", "bloco": "CMAS",
            "severidade": "media", "selo": "CONFIRMADO",
            "titulo": (f"{len(citados_no_mes)} resoluções do Conselho citadas em "
                       f"{nome_mes} de {ano} sem publicação da íntegra"),
            "detalhe": ("Resoluções referidas em atos publicados no mês, cuja "
                        "íntegra não consta de nenhuma edição do Diário nem do "
                        "sítio do Conselho: " + ", ".join(citados_no_mes) +
                        ". Ato normativo de conselho de política pública é "
                        "documento de interesse coletivo e sua íntegra é de "
                        "divulgação obrigatória."),
            "norma": ("Artigo 8º, § 1º, inciso I, da Lei 12.527/2011; "
                      "Artigo 37, caput, da Constituição da República"),
            "dados": {"resolucoes": citados_no_mes},
        })

    # IMOB-M: contratação/locação de imóvel exige pesquisa de mercado
    imoveis = [e for e in evs if any(t in json.dumps(e, ensure_ascii=False)
               .upper() for t in ("LOCACAO DE IMOVEL", "ALUGUEL DE IMOVEL",
                                  "LOCAÇÃO DE IMÓVEL"))]
    if imoveis:
        achados.append({
            "codigo": f"IMOB-M-{competencia}", "bloco": "SEMASDH",
            "severidade": "alta", "selo": "INDICIARIO",
            "titulo": (f"{len(imoveis)} contratação(ões) de imóvel em "
                       f"{nome_mes} de {ano} sem pesquisa de mercado anexa"),
            "detalhe": ("Locação de imóvel publicada sem laudo de avaliação "
                        "ou pesquisa de preços da região (metro quadrado "
                        "comercial de imóveis semelhantes). Indício de "
                        "sobrepreço é indício: a pesquisa imobiliária "
                        "comparativa da região é a providência que o "
                        "converte em prova ou o afasta."),
            "norma": ("Artigo 51, caput e inciso II, da Lei 14.133/2021 — "
                      "locação exige avaliação prévia; Artigo 23 da mesma "
                      "lei — parâmetros de preço"),
            "impedimento": "aferição de compatibilidade do aluguel com o mercado",
            "onde_obter": ("laudo de avaliação no processo; pesquisa de "
                           "mercado imobiliário da região do imóvel"),
            "dados": {"eventos": [e.get("edicao") for e in imoveis]},
        })
    achados.sort(key=lambda a: {"critica": 0, "alta": 1, "media": 2}.get(
        a["severidade"], 9))
    resumo = {
        "competencia": competencia, "mes": nome_mes, "exercicio": ano,
        "gerado_em": date.today().isoformat(),
        "parametros_aplicados": ["REC-M", "IGD-M", "PUB-M", "EXE-M", "CMAS-M"],
        "total_achados": len(achados),
        "por_severidade": {s: sum(1 for a in achados if a["severidade"] == s)
                           for s in ("critica", "alta", "media")},
        "por_selo": {s: sum(1 for a in achados if a["selo"] == s)
                     for s in ("CONFIRMADO", "INDICIARIO",
                               "INCONCLUSIVO_POR_DOCUMENTO_FALTANTE")},
        "execucao_do_mes": {"eventos": len(evs), "por_estacao": contagem},
        "publicacao_do_mes": {"dias_uteis": len(uteis),
                              "dias_com_edicao": len(dias_com_edicao)},
        "achados": achados,
        "camada_ia": "nenhuma — verificação integralmente determinística",
    }
    return resumo


def main():
    if len(sys.argv) < 2 or not re.fullmatch(r"\d{4}-\d{2}", sys.argv[1]):
        print("uso: verifica_mensal.py AAAA-MM"); return 2
    comp = sys.argv[1]
    SAIDA.mkdir(parents=True, exist_ok=True)
    r = analisa_mes(comp)
    (SAIDA / f"verificacao_{comp}.json").write_text(
        json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  {comp}: {r['total_achados']} achados — "
          f"{r['por_severidade']} | selos {r['por_selo']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
