#!/usr/bin/env python3
"""Analisador diario. Aplica config/parametros_fiscalizacao.json sobre
dados/coleta_bruta.json e emite parecer por ato.

Papel: fiscal de tribunal de contas e promotor de justica. Verifica cabimento,
legitimacao, procedimento e EFICACIA JURIDICA de cada ato encontrado.

Regra de ouro: legislacao vem SOMENTE de config/base_legal.json. Nenhuma
consulta externa de norma durante a rotina."""
import os, json, re, sys
from collections import defaultdict
from datetime import datetime, date

RAIZ = os.path.join(os.path.dirname(__file__), '..')
DADOS = os.path.join(RAIZ, 'dados'); CONF = os.path.join(RAIZ, 'config')
def L(n, base=DADOS):
    p = os.path.join(base, n)
    return json.load(open(p, encoding='utf-8')) if os.path.exists(p) else None

LEGAL = L('base_legal.json', CONF)
PARAM = L('parametros_fiscalizacao.json', CONF)
TRIAGEM = L('triagem_cnpj.json', CONF)
NAT = L('naturezas_despesa.json', CONF)

NEGRA = {x['cnpj'] for x in TRIAGEM['lista_negra_confirmada']}
NEGRA |= {x['cnpj'] for x in TRIAGEM['dominio_estranho_confirmado']}
DOMINIO_ESTRANHO = TRIAGEM['palavras_chave_de_dominio_estranho']

def brl(v):
    try: return f"R$ {float(v):,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    except Exception: return str(v)

# ------------------------------------------------- PARECER POR ATO (CMASGyn)
def parecer_ato(ato, contexto_texto=""):
    """CMAS-CAB-*, CMAS-PROC-*. Retorna cabimento, legitimacao, procedimento e eficacia."""
    t = contexto_texto.lower()
    p = {"ato": f"Resolucao {ato['numero']}/{ato['ano']}",
         "ad_referendum": ato.get('ad_referendum', False),
         "cabimento": {}, "legitimacao": {}, "procedimento": {}, "eficacia": {}}

    # cabimento - materia dentro da competencia do artigo 2 da Lei 9.009/2010
    comp = {"I": "prioridades", "II": "diretrizes do plano", "III": "politica municipal",
            "IVb": "contas do fundo", "V": "criterios de execucao financeira",
            "VI": "fiscalizacao de servicos", "VII": "criterios de qualidade",
            "VIII": "criterios de contratos", "IX": "apreciacao previa de contratos",
            "XII": "conferencia", "XIII": "gestao dos recursos", "XIV": "beneficios eventuais"}
    marcas = {"IVb": ["contas", "balancete", "relatorio do fundo", "prestacao de contas do fmas"],
              "IX": ["termo de fomento", "termo de colaboracao", "convenio", "contrato", "plano de trabalho"],
              "VII": ["inscricao", "criterio de qualidade", "atualizacao de inscricao"],
              "XIV": ["beneficio eventual", "auxilio natalidade", "auxilio funeral"],
              "XIII": ["execucao", "monitoramento", "avaliacao"]}
    enq = [k for k, ws in marcas.items() if any(w in t for w in ws)]
    p['cabimento'] = {"enquadramento": enq or ["INDETERMINADO"],
        "competencia": [comp.get(k, k) for k in enq] or ["nao identificada no texto disponivel"],
        "norma": "Artigo 2 da Lei municipal 9.009/2010",
        "status": "verde" if enq else "amarelo",
        "nota": "" if enq else "Sem inteiro teor publicado nao se afere a materia. A ausencia e o achado."}

    # legitimacao - orgao competente e quorum
    plenario = any(w in t for w in ["plenaria", "plenario", "assembleia", "reuniao ordinaria", "reuniao extraordinaria"])
    p['legitimacao'] = {"instancia_declarada": "plenario" if plenario else "nao declarada",
        "norma": "Artigo 7 da Lei municipal 9.009/2010 - o plenario e a instancia de deliberacao maxima",
        "quorum_aferivel": False,
        "status": "vermelho" if ato.get('ad_referendum') and not plenario else ("verde" if plenario else "cinza"),
        "nota": ("Ato ad referendum: so produz eficacia definitiva apos ratificacao pelo plenario seguinte, "
                 "que deve ser publicada. Verificar CMAS-CAB-03." if ato.get('ad_referendum') else
                 "Quorum e paridade sao inaferiveis sem ata publicada. Artigo 10 da Lei municipal 9.009/2010.")}

    # procedimento - motivacao, data, assinatura
    motivado = any(w in t for w in ["considerando", "tendo em vista", "fundamento", "nos termos"])
    assinado = any(w in t for w in ["assinado eletronicamente", "presidente", "gabinete"])
    p['procedimento'] = {"motivacao": motivado, "assinatura_identificada": assinado,
        "norma": "Artigos 22, paragrafo 1, e 50 da Lei 9.784/1999",
        "status": "verde" if (motivado and assinado) else "amarelo"}

    # eficacia - CMAS-PROC-03
    publicado = bool(contexto_texto.strip())
    p['eficacia'] = {"publicado_no_diario": publicado,
        "norma": "Artigo 10, paragrafo 2, da Lei municipal 9.009/2010",
        "teste": "cabimento + competencia + quorum + motivacao + PUBLICACAO",
        "conclusao": ("Ato apto a produzir efeitos." if publicado else
            "Ato NAO PRODUZ EFICACIA JURIDICA perante terceiros. A publicacao e condicao de eficacia, "
            "nao de validade: o ato pode existir e ser valido, mas nao vincula. Se produziu efeito "
            "financeiro sem publicacao, ha vicio autonomo."),
        "status": "verde" if publicado else "vermelho", "severidade": None if publicado else "critica"}
    return p

# ------------------------------------------------- PARECER DE DESPESA (SEMASDH)
def parecer_despesa(linha, instrumentos, texto=""):
    """SEM-CON-01, SEM-CON-02, SEM-CON-07, SEM-CON-08."""
    t = texto.lower()
    r = {"dotacao": linha.get('dotacao'), "natureza": linha.get('natureza'),
         "subitem": linha.get('subitem'), "fonte": linha.get('fonte'),
         "valor": linha.get('valor'), "checks": []}

    def ck(pid, ok, msg, norma, sev="media", selo="CONFIRMADO"):
        r['checks'].append({"parametro": pid, "status": "verde" if ok else "vermelho",
                            "mensagem": msg, "norma": norma, "severidade": sev, "selo": selo})

    ck("SEM-DES-04", bool(linha.get('subitem')),
       "Natureza com subitem capturado." if linha.get('subitem') else
       "Natureza truncada em 8 digitos. Aluguel e beneficio eventual ficam inatingiveis.",
       "Artigo 13 da Lei 4.320/1964", "alta")

    ck("SEM-CON-01", bool(instrumentos),
       f"Vinculo identificado: {', '.join(i['tipo']+' '+i['numero'] for i in instrumentos[:3])}" if instrumentos
       else "Valor sem contrato, termo, convenio ou ata que o justifique na mesma publicacao.",
       "Artigo 62 da Lei 4.320/1964; artigo 48-A, inciso I, da Lei Complementar 101/2000", "alta")

    parceria = any(i['tipo'].startswith(('TERMO DE FOMENTO', 'TERMO DE COLABORA')) for i in instrumentos)
    if parceria:
        tem_cham = any(w in t for w in ["chamamento publico", "inexigibilidade", "dispensa de chamamento",
                                        "emenda parlamentar", "artigo 29", "art. 29", "art. 30", "art. 31"])
        ck("SEM-CON-02", tem_cham,
           "Chamamento, dispensa ou inexigibilidade mencionados." if tem_cham else
           "Parceria publicada sem registro de chamamento publico nem justificativa de dispensa ou inexigibilidade.",
           "Artigos 24, 29, 30, 31 e 32 da Lei 13.019/2014", "alta")
        ck("SEM-CON-03", "plano de trabalho" in t,
           "Plano de trabalho referido." if "plano de trabalho" in t else "Plano de trabalho nao referido.",
           "Artigo 42 da Lei 13.019/2014", "media")

    revogada = bool(re.search(r'8\.?666[/\s]*(?:de\s*)?(?:19)?93', t))
    if revogada:
        ck("SEM-CON-07", False,
           "Ato invoca a Lei 8.666/1993, revogada desde 30/12/2023. Termo de fomento nunca se rege por lei "
           "de licitacoes: rege-se pela Lei 13.019/2014.",
           "Artigo 193, inciso II, da Lei 14.133/2021", "alta")

    disp = re.search(r'artigo?\s*75[,\s]*(?:inciso\s*)?(I{1,2}|1|2)', t)
    if disp:
        ck("SEM-CON-06", None if True else True,
           f"Dispensa do artigo 75 invocada com valor de {brl(linha.get('valor'))}. Conferir contra o limite "
           "vigente e contra a soma do exercicio para o mesmo objeto. Fracionamento se demonstra por processo.",
           "Artigo 75, paragrafo 1, da Lei 14.133/2021", "media", "INDICIARIO")
        r['checks'][-1]['status'] = "amarelo"

    ck("SEM-CON-08", None, "Preco nao aferido. Sobrepreco exige pericia com preco de mercado; "
       "estatistica sobre texto de Diario Oficial nao serve.",
       "metodo", "media", "INDICIARIO")
    r['checks'][-1]['status'] = "cinza"
    return r

# ------------------------------------------------- DOMINIO
def dominio_estranho(texto):
    t = texto.lower()
    for dom, ws in DOMINIO_ESTRANHO.items():
        if sum(1 for w in ws if w in t) >= 2: return dom
    return None

# ------------------------------------------------- MAIN
def main():
    bruta = L('coleta_bruta.json') or []
    saida = {"gerado_em": datetime.now().isoformat(), "pareceres_cmasgyn": [],
             "pareceres_despesa": [], "descartes": [], "alertas": []}
    for reg in bruta:
        txt = reg.get('texto', '') or ''
        dom = dominio_estranho(txt)
        if dom:
            saida['descartes'].append({"edicao": reg['edicao'], "motivo": f"dominio {dom}"})
            continue
        for ato in reg.get('resolucoes', []):
            saida['pareceres_cmasgyn'].append(
                {"edicao": reg['edicao'], **parecer_ato(ato, txt)})
        for linha in reg.get('linhas_orcamentarias', []):
            saida['pareceres_despesa'].append(
                {"edicao": reg['edicao'], **parecer_despesa(linha, reg.get('instrumentos', []), txt)})
        for c in reg.get('cnpjs', []):
            if not c['dv_valido']:
                saida['alertas'].append({"tipo": "SYS-05", "edicao": reg['edicao'],
                                         "cnpj": c['cnpj'], "motivo": "digito verificador invalido"})
            elif c['cnpj'] in NEGRA:
                saida['alertas'].append({"tipo": "triagem", "edicao": reg['edicao'],
                                         "cnpj": c['cnpj'], "motivo": "lista negra - nao e entidade privada"})
    json.dump(saida, open(os.path.join(DADOS, 'pareceres.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print(f"pareceres CMASGyn={len(saida['pareceres_cmasgyn'])} "
          f"despesa={len(saida['pareceres_despesa'])} "
          f"descartes={len(saida['descartes'])} alertas={len(saida['alertas'])}")

if __name__ == '__main__':
    main()
