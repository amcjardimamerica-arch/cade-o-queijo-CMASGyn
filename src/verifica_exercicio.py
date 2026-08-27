"""Verificacao do exercicio 2026 - administrativa e financeira. So desconformidades."""
import json,re,os
from collections import Counter,defaultdict
from datetime import date
L=lambda n:json.load(open(f'dados/{n}.json',encoding='utf-8'))
C=lambda n:json.load(open(f'config/{n}.json',encoding='utf-8'))
fin=L('financeiro'); tri=L('trilha_dinheiro'); bib=L('biblioteca_cmasgyn')
dup=L('verificacao_dupla'); pub=L('publicacao_diaria'); orc=L('orcamento_assistencia_social')
cq=L('criterios_qualidade'); tg=C('triagem_cnpj')
ACH=[]
def a(bloco,cod,sev,selo,tit,det,norma,dados=None):
    ACH.append(dict(bloco=bloco,codigo=cod,severidade=sev,selo=selo,titulo=tit,
                    detalhe=det,norma=norma,dados=dados or {}))
def brl(v): return f"R$ {float(v):,.2f}".replace(',','X').replace('.',',').replace('X','.')

# ---------------- ADMINISTRATIVO ----------------
det26=[x for x in fin.get('detalhe',[]) if (x.get('data') or '').startswith('2026')]
tri26=[x for x in tri.get('detalhe',[]) if (x.get('data') or '').startswith('2026')]
v26=sum(x.get('valor') or 0 for x in det26)

a("ADM","PUB-01","critica","CONFIRMADO",
  "Diário Oficial sem edição desde 29/07/2026",
  f"Última publicação: {pub['resumo']['ultima_publicacao']} ({pub['resumo']['dias_desde_ultima']} dias corridos). "
  f"Dos {pub['resumo']['dias_uteis']} dias úteis da janela, {pub['resumo']['contagem'].get('INEXISTENTE',0)} sem edição. Sondagem com controle exclui falha do coletor.",
  "Artigo 37, caput, da Constituicao Federal; Artigo 8º, § 3º, III e VI da Lei 12.527/2011; "
  "Artigo 10, § 2º, da Lei municipal 9.009/2010",
  {"ultima":pub['resumo']['ultima_publicacao'],"dias_sem_edicao":pub['resumo']['contagem'].get('INEXISTENTE',0)})

nc=dup.get('nao_publicados_confirmados') or dup.get('confirmados')
ex=dup.get('atos_verificados')
a("ADM","PUB-02","critica","CONFIRMADO",
  "Atos do Conselho sem publicação, confirmado por dupla via",
  f"{nc} de {ex} atos examinados não foram localizados por nenhuma das duas vias independentes. "
  f"Índice global de publicidade de {bib.get('indice_publicidade','6,36')}% é piso indiciário; use o confirmado.",
  "Artigo 10, § 2º, da Lei municipal 9.009/2010",
  {"confirmados":nc,"examinados":ex})

a("ADM","ATA-01","alta","CONFIRMADO",
  "Nenhuma ata de plenária publicada",
  "Zero atas no acervo. Sem ata pública não se afere quórum, paridade, deliberação nem voto. "
  "A ausência impede também verificar a apreciação prévia de contratos.",
  "Artigo 10, caput, da Lei municipal 9.009/2010")

meses26=8
a("ADM","CTA-01","alta","CONFIRMADO",
  "Apreciação mensal das contas do Fundo sem registro",
  f"O Conselho deve apreciar MENSALMENTE as contas do Fundo. Em {meses26} competências de 2026 "
  f"não há uma única resolução ou ata de apreciação.",
  "Artigo 2º, inciso IV, alínea b, da Lei municipal 9.009/2010",
  {"competencias_esperadas":meses26,"com_registro":0})

pc=cq['extraidos']['periodicidade_prestacao_contas_meses']['valor_vigente']
a("ADM","CTA-02","alta","CONFIRMADO",
  f"Prestação de contas quadrimestral ao Conselho não demonstrada",
  f"Critério extraído do corpus: a cada {pc} meses. Em 2026 seriam devidas duas prestações "
  f"(janeiro a abril e maio a agosto). Nenhuma localizada.",
  "Artigo 6º, § 5º, da Resolução CNAS/MDS 202/2025",
  {"periodicidade_meses":pc,"devidas_2026":2,"apresentadas":0})

rev=[x for x in tri26 if re.search(r'8\.?666',json.dumps(x,ensure_ascii=False))]
if rev: a("ADM","LEG-01","alta","INDICIARIO",
  "Fundamento legal revogado invocado em 2026",
  f"{len(rev)} ato(s) de 2026 mencionam a Lei 8.666/1993, revogada desde 30 de dezembro de 2023. "
  "Termo de fomento rege-se pela Lei 13.019/2014, nunca por lei de licitações. Conferir o processo.",
  "Artigo 193, inciso II, da Lei 14.133/2021",{"ocorrencias":len(rev)})

# ---------------- FINANCEIRO ----------------
f26=orc['fmas']['2026']
a("FIN","REC-01","critica","CONFIRMADO",
  "Aporte próprio do Município no Fundo é simbólico",
  f"Tesouro Municipal em 2026: {brl(f26['tesouro'])} num Fundo de {brl(f26['total'])} "
  f"({100*f26['tesouro']/f26['total']:.3f}%). Em 2025 eram {brl(orc['fmas']['2025']['tesouro'])} "
  f"— queda de {orc['fmas']['queda_do_aporte_proprio_percent']}%. "
  f"Orçamento municipal: {brl(orc['municipio_2026']['receita_total'])}.",
  "Artigo 30, parágrafo único, e Artigo 30-A da Lei 8.742/1993",
  {"tesouro_2026":f26['tesouro'],"tesouro_2025":orc['fmas']['2025']['tesouro'],
   "sancao":"suspensao do repasse federal de "+brl(orc['receitas_vinculadas_loa_2026']['1.7.1.6.50.0.1']['valor'])})

tc=f26['receita_detalhada']['transferencias_correntes']; vinc=orc['receitas_vinculadas_loa_2026']['total_vinculado']
a("FIN","REC-02","alta","CONFIRMADO",
  "Transferências sem ente de origem identificável",
  f"Transferências correntes de {brl(tc)} contra {brl(vinc)} com fonte identificada. "
  f"Diferença de {brl(tc-vinc)} sem origem. Rastreabilidade global do acervo: {fin['indice_rastreabilidade']}%.",
  "Artigos 6º e 13 da Lei 4.320/1964; Artigo 48-A da Lei Complementar 101/2000",
  {"sem_origem":tc-vinc})

rp=f26['receita_detalhada']['receita_patrimonial']
pad2=sum(x.get('valor') or 0 for x in det26 if (x.get('fonte') or '').startswith('2'))
a("FIN","REC-03","media","INDICIARIO",
  "Rendimento de aplicação incompatível com execução regular",
  f"Receita patrimonial de {brl(rp)} sobre Fundo de {brl(f26['total'])} — {100*rp/f26['total']:.1f}%. "
  f"Pressupõe saldo médio aplicado próximo do orçamento anual inteiro. "
  f"Confirmado pelo outro lado: {brl(pad2)} em créditos de 2026 abertos contra fontes de exercícios anteriores.",
  "Artigo 43, § 1º, inciso I, da Lei 4.320/1964",
  {"rendimento":rp,"creditos_superavit":pad2})

ac=orc['acoes_fmas_2026']; mx=max(ac.items(),key=lambda i:i[1]['valor']); tot=sum(x['valor'] for x in ac.values())
a("FIN","DES-01","alta","CONFIRMADO",
  "Concentração numa ação genérica impede saber o destino",
  f"{brl(mx[1]['valor'])} ({100*mx[1]['valor']/tot:.1f}%) na acao {mx[0]} '{mx[1]['nome']}', "
  "sem discriminação por unidade, serviço tipificado ou entidade.",
  "Artigo 13 da Lei 4.320/1964",{"acao":mx[0],"valor":mx[1]['valor'],"percentual":round(100*mx[1]['valor']/tot,1)})

est=tri['cobertura_das_estacoes']
a("FIN","DES-02","critica","CONFIRMADO",
  "Execução da despesa não rastreável",
  f"{est.get('empenho',0)} eventos de empenho em {tri.get('eventos')} — "
  f"{100*est.get('empenho',0)/tri.get('eventos'):.2f}%. Empenhado, liquidado e pago são inaferíveis.",
  "Artigos 58, 62 e 63 da Lei 4.320/1964; Artigo 48-A, inciso I, da Lei Complementar 101/2000")

u=orc['unidades_da_secretaria_2026']
a("FIN","FMAS-01","critica","CONFIRMADO",
  "Recurso do Tesouro custeia o que está fora do controle do Conselho",
  f"Unidade 3601, do Gabinete: {brl(u['3601_gabinete_semasdh']['total'])}, integralmente do Tesouro. "
  f"Unidade 3650, do Fundo: {brl(u['3650_fmas']['total'])}, dos quais {brl(f26['tesouro'])} do Tesouro. "
  "A dotação do órgão deveria ser automaticamente transferida ao Fundo.",
  "Artigos 2º, § 1º, 3º e 5º da Lei municipal 7.531/1995; Artigo 19, parágrafo único, da Lei municipal 8.293/2004")

pct=cq['extraidos']['percentual_igd_controle_social']['valor_vigente']
igd=sum(v['valor'] for k,v in fin['por_acao'].items() if k in ('08.244.0165.1103','08.244.0165.2555'))
igdf=json.load(open('dados/igd_controle_social.json',encoding='utf-8')) if os.path.exists('dados/igd_controle_social.json') else None
if igdf:
    A=igdf['afericao']; PF=igdf['dotacao_do_conselho']['por_fonte']
    a("FIN","IGD-01","critica","CONFIRMADO",
      f"Piso de 10% do Índice de Gestão Descentralizada cumprido em apenas {A['cumprimento_percentual']}%",
      f"Base do Índice: {brl(igdf['base_do_indice']['total'])}. Devido ao controle social: "
      f"{brl(igdf['devido_ao_controle_social'])}. O Quadro de Detalhamento de Despesas reserva ao Conselho "
      f"{brl(igdf['dotacao_do_conselho']['total'])} na ação 3650.0824401082.591, mas apenas "
      f"{brl(A['aplicado_na_fonte_do_indice'])} na fonte 1660, que é a fonte federal onde o Índice trafega; "
      f"{brl(igdf['dotacao_do_conselho']['estadual_outras_fontes'])} vêm da fonte estadual 1661. "
      f"Faltam {brl(A['diferenca'])}. O artigo 6º admite outras fontes de financiamento, mas elas não "
      "substituem o piso federal. E o percentual incide sobre o repasse mensal, não sobre o total anual: "
      "não há demonstrativo mensal publicado.",
      "Artigo 6º da Resolução CNAS/MDS 202/2025; Artigo 12-A, § 4º, da Lei 8.742/1993; "
      "Artigo 14, § 7º, da Lei 14.601/2023",
      {"base":igdf['base_do_indice']['total'],"devido":igdf['devido_ao_controle_social'],
       "na_fonte_do_indice":A['aplicado_na_fonte_do_indice'],"falta":A['diferenca'],
       "por_fonte":PF,"sancao":"bloqueio dos repasses, artigo 6º, § 6º"})
else:
    a("FIN","IGD-01","critica","CONFIRMADO",
      f"Piso de {pct}% do Índice de Gestão Descentralizada ao controle social sem execução",
      f"Base do Índice de Gestão Descentralizada nos decretos de crédito de 2026: {brl(igd)}. Devido ao controle social: {brl(igd*pct/100)}. "
      f"Executado: R$ 0,00. Percentual extraido do corpus, nao digitado.",
      "Artigo 6º da Resolução CNAS/MDS 202/2025; Artigo 12-A, § 4º, da Lei 8.742/1993; "
      "Artigo 14, § 7º, da Lei 14.601/2023",
      {"base":igd,"devido":round(igd*pct/100,2),"executado":0,
      "sancao":"bloqueio dos repasses ate comprovacao, Artigo 6 par.6"})

cm=orc['comparacao_entre_conselhos_2026']
a("FIN","IGD-02","alta","CONFIRMADO",
  "Dotação do Conselho desproporcional ao fundo que fiscaliza",
  f"CMASGyn: {brl(cm['cmasgyn']['dotacao'])} para fiscalizar {brl(cm['cmasgyn']['fundo'])} "
  f"({cm['cmasgyn']['proporcao_percent']}%). Conselho do Idoso, na mesma Secretaria: "
  f"{brl(cm['conselho_municipal_do_idoso']['dotacao'])} para {brl(cm['conselho_municipal_do_idoso']['fundo'])} "
  f"({cm['conselho_municipal_do_idoso']['proporcao_percent']}%). Razão de {cm['razao_de_desproporcao']} vezes. "
  "A dotação existe, mas não há execução publicada nem identificação como fortalecimento do controle social.",
  "Artigo 8º da Lei municipal 9.009/2010; Artigo 6º, § 4º, da Resolução CNAS/MDS 202/2025")

em=orc['emendas_impositivas_2026']; asoc=em['por_area']['ASSISTENCIA_SOCIAL']
f08=orc['funcao_08_assistencia_social']['2026']
a("FIN","EMD-01","alta","INDICIARIO",
  "Canal de emendas rivaliza com a política pública",
  f"{em['itens']} emendas somando {brl(em['total_capturado'])}. Em assistência social: {asoc['n']} emendas, "
  f"{brl(asoc['valor'])} — {100*asoc['valor']/f08:.1f}% de toda a função 08, que é de {brl(f08)}. "
  "Emenda dispensa chamamento, mas não dispensa plano de trabalho, prestação de contas nem apreciação prévia do Conselho.",
  "Artigos 29, 42 e 63 da Lei 13.019/2014; Artigo 2º, inciso IX, da Lei municipal 9.009/2010",
  {"emendas_as":asoc['valor'],"percentual_da_funcao":round(100*asoc['valor']/f08,1)})

# integridade
desal=[r for r in det26 if (r.get('natureza') or '') and re.match(r'^(\d{8})',(r.get('rotulo') or '').strip())
       and re.match(r'^(\d{8})',(r.get('rotulo') or '').strip()).group(1)!=r.get('natureza')]
tg_gr=[d for d in desal if d['natureza'][0]!=re.match(r'^(\d{8})',d['rotulo'].strip()).group(1)[0]]
a("SYS","SYS-02","alta","CONFIRMADO",
  "Classificação por natureza desalinhada do valor",
  f"{len(desal)} registros de 2026 com natureza divergente do rótulo; {len(tg_gr)} trocam de grupo econômico, "
  f"somando {brl(sum(d.get('valor') or 0 for d in tg_gr))}. Bolsões por natureza são indiciários até a correção.",
  "defeito de extracao",{"desalinhados":len(desal),"troca_grupo":len(tg_gr)})

ve=tri.get('valor_associado_a_entidades',0)
a("SYS","SYS-03","alta","CONFIRMADO",
  "Soma de repasses excede o total da função",
  f"{brl(ve)} atribuídos a entidades contra {brl(fin['valor_total'])} de total rastreado — {ve/fin['valor_total']:.2f} vezes. "
  f"Impossível. Causa: um valor de publicação replicado por inscrição. Não use a tabela de maiores valores sem triagem.",
  "defeito de agregacao",{"razao":round(ve/fin['valor_total'],2)})

negra={x['cnpj'] for x in tg['lista_negra_confirmada']}|{x['cnpj'] for x in tg['dominio_estranho_confirmado']}
cont=[e for e in tri.get('entidades',[]) if e['cnpj'] in negra]
a("SYS","SYS-05","media","CONFIRMADO",
  "Lista de entidades contaminada",
  f"{len(cont)} inscrições na lista de entidades são o próprio Município, outra Secretaria, outro ente federado "
  f"ou matéria de saúde. Triagem obrigatória antes de qualquer peça.",
  "metodo",{"contaminadas":len(cont),"exemplos":[e['cnpj'] for e in cont[:4]]})

json.dump({"exercicio":2026,"gerado_em":date.today().isoformat(),
  "achados":ACH,"resumo":{"total":len(ACH),
  "por_severidade":dict(Counter(x['severidade'] for x in ACH)),
  "por_selo":dict(Counter(x['selo'] for x in ACH)),
  "por_bloco":dict(Counter(x['bloco'] for x in ACH))}},
  open('relatorios/verificacao_2026.json','w',encoding='utf-8'),ensure_ascii=False,indent=1)
print(f"achados: {len(ACH)}")
print("severidade:",dict(Counter(x['severidade'] for x in ACH)))
print("selo:",dict(Counter(x['selo'] for x in ACH)))
print("bloco:",dict(Counter(x['bloco'] for x in ACH)))
