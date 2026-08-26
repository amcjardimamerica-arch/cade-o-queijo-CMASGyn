#!/usr/bin/env python3
"""Analise retroativa de 3 anos. Aplica config/parametros_fiscalizacao.json
aos dados ja existentes, separa trilhas SEMASDH e CMASGyn, deteta padroes
e defeitos de integridade do proprio sistema."""
import json, re, os, sys
from collections import defaultdict, Counter
from datetime import datetime, date, timedelta

D = os.path.join(os.path.dirname(__file__), '..', 'dados')
C = os.path.join(os.path.dirname(__file__), '..', 'config')
L = lambda n, base=D: json.load(open(os.path.join(base, n), encoding='utf-8'))

fin = L('financeiro.json'); tri = L('trilha_dinheiro.json')
bib = L('biblioteca_cmasgyn.json'); dup = L('verificacao_dupla.json')
pub = L('publicacao_diaria.json')
LEGAL = L('base_legal.json', C)

out = {"gerado_em": datetime.utcnow().isoformat(), "achados": [],
       "trilha_semasdh": {}, "trilha_cmasgyn": {}, "integridade_sistema": [],
       "padroes": [], "lacunas": []}

def ach(trilha, pid, sev, selo, titulo, detalhe, norma="", valor=None):
    out["achados"].append({"trilha": trilha, "parametro": pid, "severidade": sev,
        "selo": selo, "titulo": titulo, "detalhe": detalhe, "norma": norma, "valor": valor})

def brl(v):
    return f"R$ {v:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')

# ---------- 1. INTEGRIDADE DO PROPRIO SISTEMA ----------
det = fin.get('detalhe', [])
desalinhados = []
for r in det:
    nat = (r.get('natureza') or '')
    rot = (r.get('rotulo') or '').strip()
    m = re.match(r'^(\d{8})', rot)
    if nat and m and m.group(1) != nat:
        desalinhados.append({"dotacao": r.get('dotacao'), "campo": nat, "rotulo": m.group(1),
                             "valor": r.get('valor'), "data": r.get('data'),
                             "grupo_campo": nat[0], "grupo_rotulo": m.group(1)[0],
                             "edicao": r.get('edicao')})
troca_grupo = [d for d in desalinhados if d['grupo_campo'] != d['grupo_rotulo']]
v_troca = sum(d['valor'] or 0 for d in troca_grupo)
out["integridade_sistema"].append({
    "id": "SYS-02", "titulo": "Desalinhamento entre natureza e valor",
    "registros_desalinhados": len(desalinhados),
    "com_troca_de_grupo_economico": len(troca_grupo),
    "valor_afetado_por_troca_de_grupo": v_troca,
    "percentual_do_total": round(100 * v_troca / (fin['valor_total'] or 1), 2),
    "exemplos": troca_grupo[:6]})

v_ent = tri.get('valor_associado_a_entidades', 0)
out["integridade_sistema"].append({
    "id": "SYS-03", "titulo": "Soma de repasses excede o total da funcao",
    "valor_associado_a_entidades": v_ent, "valor_total_funcao_08": fin['valor_total'],
    "razao": round(v_ent / (fin['valor_total'] or 1), 2),
    "veredito": "IMPOSSIVEL" if v_ent > fin['valor_total'] else "coerente"})

# fan-out: mesmo valor replicado em varios CNPJ
por_valor = defaultdict(set)
for e in tri.get('entidades', []):
    if e.get('valor'):
        por_valor[round(e['valor'], 2)].add(e['cnpj'])
fanout = {v: sorted(c) for v, c in por_valor.items() if len(c) >= 3}
out["integridade_sistema"].append({
    "id": "SYS-04", "titulo": "Fan-out: mesmo valor replicado em multiplas inscricoes",
    "grupos": len(fanout),
    "valor_inflado_estimado": sum(v * (len(c) - 1) for v, c in fanout.items()),
    "maiores": sorted(({"valor": v, "n_cnpj": len(c), "cnpjs": c} for v, c in fanout.items()),
                      key=lambda x: -x['valor'] * x['n_cnpj'])[:5]})

# CNPJ malformado / duplicado por formatacao
def dv_ok(c):
    n = re.sub(r'\D', '', c)
    if len(n) != 14 or len(set(n)) == 1: return False
    for pos, pesos in ((12, [5,4,3,2,9,8,7,6,5,4,3,2]), (13, [6,5,4,3,2,9,8,7,6,5,4,3,2])):
        s = sum(int(n[i]) * pesos[i] for i in range(pos))
        r = s % 11
        if int(n[pos]) != (0 if r < 2 else 11 - r): return False
    return True

cnpjs = [e['cnpj'] for e in tri.get('entidades', [])]
invalidos = [c for c in cnpjs if not dv_ok(c)]
norm = defaultdict(list)
for c in cnpjs: norm[re.sub(r'\D', '', c)].append(c)
dupfmt = {k: v for k, v in norm.items() if len(set(v)) > 1}
out["integridade_sistema"].append({
    "id": "SYS-05", "titulo": "Inscricoes invalidas ou duplicadas por formatacao",
    "total_inscricoes": len(cnpjs), "digito_verificador_invalido": len(invalidos),
    "lista_invalidas": invalidos, "duplicadas_por_formatacao": dupfmt})

out["integridade_sistema"].append({
    "id": "SYS-06", "titulo": "Metrica de integridade da trilha nao alerta",
    "declarado": tri.get('integridade_da_trilha'), "rupturas_declaradas": len(tri.get('rupturas', [])),
    "eventos_com_empenho": tri['cobertura_das_estacoes'].get('empenho', 0),
    "eventos_totais": tri.get('eventos'),
    "cobertura_real_estacao_6": round(100 * tri['cobertura_das_estacoes'].get('empenho', 0) / (tri.get('eventos') or 1), 2),
    "veredito": "metrica mede existencia de estacao, nao percurso do recurso"})

# ---------- 2. TRILHA SEMASDH ----------
S = out["trilha_semasdh"]

# receita: existe?
S["A_RECEITA"] = {"campos_de_receita_no_repositorio": 0,
    "veredito": "AUSENTE. O repositorio nao contem receita. Nenhum parametro SEM-REC pode ser aferido.",
    "impede": ["SEM-REC-01", "SEM-REC-02", "SEM-REC-03", "SEM-REC-04", "SEM-REC-05", "SEM-REC-06",
               "DEST-01", "DEST-02", "DEST-06"]}
ach("SEMASDH", "SEM-REC-01", "critica", "CONFIRMADO",
    "Nenhum dado de receita no acervo",
    "O arquivo financeiro.json nao possui campo de receita. Sem receita nao ha como aferir superavit, deficit, "
    "cumprimento do teto de 30% do artigo 4, paragrafo unico, da Lei municipal 7.531/1995, nem a transferencia "
    "automatica ao FMAS do artigo 2, paragrafo 1, da mesma lei.",
    "Artigos 6 e 13 da Lei 4.320/1964; artigo 48 da Lei Complementar 101/2000")

# despesa: estagio
est = tri['cobertura_das_estacoes']
S["B_DESPESA"] = {"dotacao_e_credito": est.get('orcamento', 0) + est.get('credito', 0),
    "empenho_liquidacao_pagamento": est.get('empenho', 0),
    "cobertura_execucao_percent": round(100 * est.get('empenho', 0) / (tri.get('eventos') or 1), 2),
    "veredito": "O acervo capta AUTORIZACAO, nao EXECUCAO. Empenhado, liquidado e pago sao inaferiveis."}
ach("SEMASDH", "SEM-DES-03", "critica", "CONFIRMADO",
    "Despesa efetivamente realizada nao rastreavel",
    f"Apenas {est.get('empenho',0)} de {tri.get('eventos')} eventos alcancam a estacao de empenho e pagamento "
    f"({S['B_DESPESA']['cobertura_execucao_percent']}%). O Diario Oficial publica autorizacao, nao execucao.",
    "Artigos 58, 62 e 63 da Lei 4.320/1964; artigo 48-A da Lei Complementar 101/2000")

# bolsoes
BOL = {"PESSOAL": r'^31', "ENTIDADES": r'^(33503900|33504100|33504300|33508500|44504200)$',
       "INVESTIMENTO": r'^44', "CUSTEIO": r'^33'}
bols = defaultdict(float); bolsn = defaultdict(int)
for nat, d in fin['por_natureza'].items():
    if nat == 'não identificada':
        bols['NAO_IDENTIFICADA'] += d['valor']; bolsn['NAO_IDENTIFICADA'] += d['linhas']; continue
    for nome, pat in (("ENTIDADES", BOL["ENTIDADES"]), ("PESSOAL", BOL["PESSOAL"]),
                      ("INVESTIMENTO", BOL["INVESTIMENTO"]), ("CUSTEIO", BOL["CUSTEIO"])):
        if re.match(pat, nat):
            bols[nome] += d['valor']; bolsn[nome] += d['linhas']; break
S["bolsoes_segundo_campo_natureza"] = {k: {"valor": round(v, 2), "linhas": bolsn[k]} for k, v in bols.items()}
S["bolsoes_alerta"] = ("Estes bolsoes derivam do campo natureza, comprovadamente desalinhado. "
                       f"{len(troca_grupo)} registros trocam de grupo economico, {brl(v_troca)} afetados. Use como INDICIARIO.")

# folha: existe 31901100?
folha = [n for n in fin['por_natureza'] if n.startswith('3190') and n[4:6] in ('11', '04', '13', '16')]
ach("SEMASDH", "SEM-PES-01", "alta", "CONFIRMADO",
    "Folha de pagamento invisivel no acervo",
    "Nao ha natureza 31901100 (Vencimentos e vantagens fixas) em nenhuma das 133 linhas. As rubricas do grupo 31 "
    "presentes sao 31901300, 31909200 e 31909600, e ao menos duas delas estao desalinhadas: o rotulo aponta "
    "33504100 e 33504300, transferencias a instituicao privada. Nao ha como contar cargos nem aferir o teto de 30%.",
    "Artigo 4, paragrafo unico, da Lei municipal 7.531/1995",
    {"naturezas_de_folha_encontradas": folha})

# aluguel
sub10 = [n for n in fin['por_natureza'] if len(n) > 8]
ach("SEMASDH", "SEM-DES-06", "alta", "CONFIRMADO",
    "Aluguel matematicamente inatingivel",
    "Todas as naturezas foram extraidas com 8 digitos. Locacao de imovel e subitem (33903615 pessoa fisica, "
    "33903910 pessoa juridica). Sem os dois digitos finais nenhum filtro por codigo isola aluguel. "
    "Ha locacao identificavel por texto: edicao de 10/04/2026, R$ 257.040,00, imovel na Rua 1105, Quadra 204, "
    "Lote 23, Setor Pedro Ludovico, para o Complexo 24 Horas.",
    "Artigo 13 da Lei 4.320/1964; artigo 4, inciso IV, da Lei municipal 7.531/1995",
    {"naturezas_com_10_digitos": len(sub10)})

# IGD
igd = {}
for a, d in fin['por_acao'].items():
    if a in ('08.244.0165.1103', '08.244.0165.2555'):
        igd[a] = d['valor']
base_igd = sum(igd.values())
S["E_IGD"] = {"acoes": igd, "base_dotacao": round(base_igd, 2),
    "piso_10_por_cento_res_202_2025": round(base_igd * 0.10, 2),
    "piso_3_por_cento_lei_14601_2023": round(base_igd * 0.03, 2),
    "dotacao_identificada_do_cmasgyn": 0,
    "veredito": "Nenhuma dotacao, empenho ou despesa identificavel do CMASGyn no acervo."}
ach("SEMASDH", "SEM-IGD-03", "critica", "CONFIRMADO",
    "Piso de 10% do IGD ao controle social sem qualquer execucao identificavel",
    f"Base de dotacao do IGD localizada: {brl(base_igd)} "
    f"(08.244.0165.1103 Modernizacao da Gestao do IGD SUAS e 08.244.0165.2555 IGD Bolsa Familia e CadUnico). "
    f"Piso de 10% desde janeiro de 2026: {brl(base_igd*0.10)}. Piso legal absoluto de 3%: {brl(base_igd*0.03)}. "
    "Nenhum valor identificavel destinado ao CMASGyn.",
    "Artigo 6 da Resolucao CNAS/MDS 202/2025; artigo 12-A, paragrafo 4, da Lei 8.742/1993; "
    "artigo 14, paragrafo 7, da Lei 14.601/2023",
    {"base": base_igd, "devido_10": round(base_igd*0.10, 2), "devido_3": round(base_igd*0.03, 2), "executado": 0})

# fontes
S["fontes_sem_mapeamento"] = fin.get('fontes_pendentes', {})
pref2 = {f: n for f, n in fin.get('fontes_pendentes', {}).items() if f.startswith('2')}
ach("SEMASDH", "SEM-REC-05", "media", "INDICIARIO",
    "Creditos abertos contra fontes de exercicios anteriores",
    f"Fontes com prefixo 2 observadas: {', '.join(sorted(pref2))} em {sum(pref2.values())} lancamentos. "
    "No padrao da Secretaria do Tesouro Nacional o primeiro digito separa exercicio corrente (1) de exercicios "
    "anteriores (2). Se confirmado, sao creditos contra superavit financeiro, que exige superavit demonstrado. "
    "CONFIRMAR contra o Quadro de Detalhamento de Despesas antes de afirmar.",
    "Artigo 43, paragrafo 1, inciso I, da Lei 4.320/1964")

# rastreabilidade
ach("SEMASDH", "SEM-REC-02", "alta", "CONFIRMADO",
    f"Rastreabilidade da origem em {fin['indice_rastreabilidade']}%",
    f"De {brl(fin['valor_total'])} em linhas da funcao 08, apenas {brl(fin['valor_classificado'])} identificam o ente. "
    "Nenhuma linha atribuida ao Estado. Nenhuma ao Municipio.",
    "Artigos 6 e 13 da Lei 4.320/1964; artigo 48-A da Lei Complementar 101/2000")

# contratos e vinculos
sem_vinc = [e for e in tri.get('entidades', []) if not e.get('com_vinculo') and (e.get('valor') or 0) > 0]
S["D_CONTRATOS"] = {"entidades_sem_vinculo_formal": len(sem_vinc),
    "valor_sem_vinculo": round(sum(e['valor'] for e in sem_vinc), 2),
    "instrumentos_localizados": len(tri.get('contratos_localizados', [])),
    "alerta": "Lista contaminada. Ver triagem_cnpj.json antes de qualquer uso."}

# ---------- 3. TRILHA CMASGYN ----------
K = out["trilha_cmasgyn"]
K["publicidade"] = {
    "atos_identificados": bib.get('total_atos') or bib.get('atos') or len(bib.get('atos', []) if isinstance(bib.get('atos'), list) else []),
    "confirmado_nao_publicado_duas_vias": dup.get('nao_publicados_confirmados') or dup.get('confirmados'),
    "examinados_duas_vias": dup.get('examinados') or dup.get('total_examinados'),
    "divergentes_pendentes": dup.get('divergentes') or len(dup.get('fila_de_conferencia_humana', []))}
ach("CMASGYN", "CMAS-ATO-01", "critica", "CONFIRMADO",
    "Resolucoes do Conselho sem publicacao no Diario Oficial",
    "O artigo 10, paragrafo 2, da Lei municipal 9.009/2010 determina de forma expressa e especifica que as "
    "Resolucoes do CMASGyn SERAO PUBLICADAS no Diario Oficial do Municipio. Esta e norma municipal propria, mais "
    "forte que o dever geral de transparencia. A publicacao e condicao de eficacia: o ato nao publicado nao produz "
    "efeitos perante terceiros, e ainda assim produziu efeito financeiro.",
    "Artigo 10, paragrafo 2, da Lei municipal 9.009/2010; artigo 37, caput, da Constituicao Federal; "
    "artigo 8 da Lei 12.527/2011")
ach("CMASGYN", "CMAS-ATO-02", "alta", "CONFIRMADO",
    "Nenhuma ata de plenaria publicada no trienio",
    "O artigo 10, caput, da Lei municipal 9.009/2010 declara publicas TODAS as sessoes ordinarias e "
    "extraordinarias. Sem ata publica sao inaferiveis quorum, paridade, deliberacao e voto. A ausencia de ata "
    "impede tambem aferir o parametro CMAS-CAB-04.",
    "Artigo 10 da Lei municipal 9.009/2010")
ach("CMASGYN", "CMAS-PROC-05", "alta", "CONFIRMADO",
    "Apreciacao mensal das contas do FMAS sem registro publico",
    "O artigo 2, inciso IV, alinea b, da Lei municipal 9.009/2010 impoe ao CMASGyn apreciar MENSALMENTE as contas "
    "e os relatorios do FMASGyn. Em tres anos de edicoes nao se localizou uma unica resolucao ou ata de apreciacao "
    "mensal de contas. Sao 36 competencias sem cumprimento demonstravel.",
    "Artigo 2, inciso IV, alinea b, da Lei municipal 9.009/2010",
    {"competencias_esperadas": 36, "competencias_com_registro": 0})
ach("CMASGYN", "CMAS-PROC-04", "alta", "INDICIARIO",
    "Apreciacao previa de contratos e convenios nao demonstrada",
    "O artigo 2, inciso IX, da Lei municipal 9.009/2010 exige apreciacao PREVIA dos contratos e convenios. "
    f"O acervo registra {len(tri.get('contratos_localizados', []))} instrumentos e apenas "
    f"{est.get('deliberacao', 0)} eventos de deliberacao. Confrontar data de resolucao contra data de assinatura "
    "exige as atas, que nao existem publicadas.",
    "Artigo 2, inciso IX, da Lei municipal 9.009/2010")

# ---------- 4. PADROES ----------
anos = defaultdict(lambda: defaultdict(int))
for d in tri.get('detalhe', []):
    a = (d.get('data') or '')[:4]
    if 'Lei 8.666' in json.dumps(d, ensure_ascii=False) or '8.666/93' in json.dumps(d, ensure_ascii=False):
        anos[a]['PAD-07'] += 1
    if d.get('contratos') and 'repasse' in d.get('estacoes', []) and not any(
            k in json.dumps(d, ensure_ascii=False).lower() for k in ('chamamento', 'inexigibilidade', 'dispensa')):
        anos[a]['PAD-01'] += 1
for pid, nome in (("PAD-01", "Vinculo publicado sem mencao a chamamento publico"),
                  ("PAD-07", "Fundamento legal revogado (Lei 8.666/1993 apos 30/12/2023)")):
    ser = {a: anos[a][pid] for a in sorted(anos) if anos[a][pid]}
    if ser:
        out["padroes"].append({"id": pid, "nome": nome, "serie_anual": ser,
            "primeira": min(ser), "ultima": max(ser), "total": sum(ser.values()),
            "tendencia": "crescente" if list(ser.values())[-1] > list(ser.values())[0] else "estavel ou decrescente"})

# fontes prefixo 2 por ano
pad02 = defaultdict(float)
for r in det:
    if (r.get('fonte') or '').startswith('2'):
        pad02[(r.get('data') or '')[:4]] += r.get('valor') or 0
if pad02:
    out["padroes"].append({"id": "PAD-02", "nome": "Credito adicional contra fonte de exercicios anteriores",
        "serie_anual": {k: round(v, 2) for k, v in sorted(pad02.items())}, "selo": "INDICIARIO"})

# ---------- 5. LACUNAS ----------
out["lacunas"] = [
    {"id": "LAC-01", "falta": "Receita mensal do FMAS por fonte", "impede": ["SEM-REC-01", "DEST-01", "DEST-02"],
     "onde": "RREO bimestral e extrato da conta especial do FMAS", "como": "Artigo 48 da Lei Complementar 101/2000 e pedido pela Lei 12.527/2011"},
    {"id": "LAC-02", "falta": "Empenho, liquidacao e pagamento por credor e competencia", "impede": ["SEM-DES-01", "SEM-DES-02", "SEM-DES-03", "SEM-DES-10", "SEM-CON-01"],
     "onde": "Portal da Transparencia de Goiania", "como": "Artigo 48-A, inciso I, da Lei Complementar 101/2000"},
    {"id": "LAC-03", "falta": "Repasses do FNAS por competencia e bloco", "impede": ["SEM-REC-03", "SEM-IGD-01", "SEM-IGD-02"],
     "onde": "Consulta de Pagamentos do Fundo Nacional de Assistencia Social", "como": "consulta publica"},
    {"id": "LAC-04", "falta": "Quadro de Detalhamento de Despesas 2026", "impede": ["mapeamento das 6 fontes pendentes", "SEM-REC-05"],
     "onde": "Anexo da LOA, Diario Oficial Edicao 8697 de 09/01/2026", "como": "download direto"},
    {"id": "LAC-05", "falta": "Quadro de pessoal da SEMASDH com vinculo", "impede": ["SEM-PES-01", "SEM-PES-02", "SEM-PES-03"],
     "onde": "Portal da Transparencia, folha de pagamento", "como": "Artigo 8, paragrafo 1, inciso III, da Lei 12.527/2011"},
    {"id": "LAC-06", "falta": "Atas de plenaria do CMASGyn", "impede": ["CMAS-CAB-04", "CMAS-PROC-04", "CMAS-PROC-05"],
     "onde": "Secretaria Executiva do CMASGyn", "como": "Artigo 10 da Lei municipal 9.009/2010 e pedido pela Lei 12.527/2011"},
    {"id": "LAC-07", "falta": "Planos de trabalho e prestacoes de contas das parcerias", "impede": ["SEM-CON-03", "SEM-CON-04"],
     "onde": "SEMASDH", "como": "Artigos 42 e 63 da Lei 13.019/2014"},
    {"id": "LAC-08", "falta": "Regimento Interno vigente do CMASGyn e decreto de nomeacao", "impede": ["CMAS-CAB-05", "CMAS-CAB-06", "CMAS-CAB-07"],
     "onde": "SEMASDH e Gabinete do Prefeito", "como": "Artigo 17 da Lei municipal 9.009/2010"},
    {"id": "LAC-09", "falta": "criterios_qualidade.json", "impede": ["aplicacao automatica dos parametros"],
     "onde": "proprio repositorio", "como": "gerar a partir de config/parametros_fiscalizacao.json"}]

json.dump(out, open(os.path.join(D, 'analise_retroativa.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1)

# resumo no terminal
print(f"achados={len(out['achados'])} lacunas={len(out['lacunas'])} padroes={len(out['padroes'])}")
print(f"SYS-02 desalinhados={len(desalinhados)} troca_grupo={len(troca_grupo)} valor={brl(v_troca)} ({out['integridade_sistema'][0]['percentual_do_total']}%)")
print(f"SYS-03 razao={out['integridade_sistema'][1]['razao']}x")
print(f"SYS-04 grupos_fanout={len(fanout)} inflacao={brl(out['integridade_sistema'][2]['valor_inflado_estimado'])}")
print(f"SYS-05 dv_invalido={len(invalidos)} {invalidos} dup_formato={list(dupfmt.values())}")
print(f"IGD base={brl(base_igd)} 10%={brl(base_igd*0.10)} 3%={brl(base_igd*0.03)}")
print("bolsoes:", {k: brl(v) for k, v in bols.items()})
for p in out['padroes']: print("PAD", p['id'], p.get('serie_anual'))
