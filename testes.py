#!/usr/bin/env python3
"""Teste de autonomia: roda o ciclo inteiro como o robô rodaria, sem intervenção."""
import json, subprocess, sys, time, pathlib
sys.path.insert(0, 'src')
R = pathlib.Path(__file__).parent
falhas, ok = [], []

def t(nome, fn):
    ini = time.time()
    try:
        r = fn()
        ok.append((nome, round(time.time()-ini,1), r))
        print(f"  PASSOU  {nome:44s} {round(time.time()-ini,1):>5}s  {r}")
    except Exception as e:
        falhas.append((nome, str(e)[:150]))
        print(f"  FALHOU  {nome:44s} {type(e).__name__}: {str(e)[:90]}")

print("\n=== 1. INTEGRIDADE DO CÓDIGO ===")
def imports():
    import util, filtro, cliente_http, orcamento, conformidade, igd, retencao
    import coleta_dom, coleta_cmasgyn, historico, extracao, biblioteca
    import financeiro, movimentacao_contas, trilha, verificacao_dupla, publicacao_diaria
    import cobertura, padroes, qualidade, busca_local, atas, painel
    return "23 módulos"
t("importação de todos os módulos", imports)

def configs():
    import yaml, glob
    n=0
    for f in glob.glob('config/**/*.yml', recursive=True) + glob.glob('.github/workflows/*.yml'):
        yaml.safe_load(open(f, encoding='utf-8')); n+=1
    return f"{n} arquivos válidos"
t("sintaxe de todos os YAML", configs)

print("\n=== 2. COLETA E ACESSO ÀS FONTES ===")
def solr():
    import requests, urllib3; urllib3.disable_warnings()
    r = requests.get("https://sileg.goiania.go.gov.br/solr-4.1.0/select",
        params={"q":'attr_content:"CMASGyn"',"wt":"json","rows":1,"fl":"id"},
        timeout=60, verify=False)
    return f"{r.json()['response']['numFound']} documentos no índice"
t("índice Solr do Diário Oficial responde", solr)

def cmas():
    from cliente_http import ClienteHTTP
    c = ClienteHTTP(user_agent="AMC-Vigilancia/1.0", intervalo=1)
    r = c.obter("https://cmasgyn.com.br/Documentos", condicional=False)
    assert r.status == 200
    return f"HTTP {r.status}, {len(r.conteudo)} bytes"
t("sítio do CMASGyn acessível", cmas)

print("\n=== 3. PROCESSAMENTO DETERMINÍSTICO (custo zero) ===")
def filtragem():
    import filtro
    lex = filtro.Lexico()
    a = ("PORTARIA. Designa servidor. RESOLUÇÃO CMASGyn nº 045/2026 aprova plano de "
         "aplicação do IGD-PBF de R$ 480.000,00. CPF 123.456.789-00 do beneficiário "
         "João da Silva. Entidade 12.345.678/0001-99. Conselho Municipal de Saúde delibera.")
    ts = filtro.processar('t.pdf', a, lex)
    assert ts and 'CPF-SUPRIMIDO' in ts[0].texto and '12.345.678/0001-99' in ts[0].texto
    return f"{len(ts)} trecho, CPF suprimido, CNPJ preservado"
t("filtro e supressão LGPD", filtragem)

def extrai():
    import extracao
    tr = extracao.carregar('assistencia_social')
    assert tr, "nenhum trecho"
    c = tr[0]
    assert c['sha256_edicao'] and c['url_original'] and c['pagina_estimada']
    return f"{len(tr)} trechos com proveniência completa"
t("extração com proveniência", extrai)

def bib():
    from util import ler_json
    d = ler_json(R/'dados'/'biblioteca_cmasgyn.json', {})
    assert d.get('total_atos')
    return f"{d['total_atos']} atos, publicidade {d['indice_de_publicidade']}%"
t("biblioteca de atos", bib)

def verif():
    from util import ler_json
    d = ler_json(R/'dados'/'verificacao_dupla.json', {})
    assert d.get('atos_verificados')
    return (f"{d['atos_verificados']} atos, concordância {d['concordancia']}%, "
            f"{len(d['fila_de_conferencia_humana'])} p/ conferência")
t("verificação dupla", verif)

def fin():
    from util import ler_json
    d = ler_json(R/'dados'/'financeiro.json', {})
    assert d.get('linhas')
    return f"{d['linhas']} linhas, R$ {d['valor_total']:,.2f}"
t("conciliação financeira", fin)

def privacidade_mov():
    import movimentacao_contas as mc
    texto = "Beneficiário: João da Silva CPF [CPF-SUPRIMIDO], pagamento efetuado"
    assert mc.primeiro_nome_pessoa_fisica(texto) == "João"
    assert mc.primeiro_nome_pessoa_fisica(
        "Beneficiário: João da Silva CNPJ 12.345.678/0001-99") is None
    return "pessoa física reduzida ao primeiro nome"
t("minimização de beneficiário pessoa física", privacidade_mov)

def tri():
    from util import ler_json
    d = ler_json(R/'dados'/'trilha_dinheiro.json', {})
    assert d.get('eventos')
    return (f"{d['eventos']} eventos, integridade {d['integridade_da_trilha']}%, "
            f"{len(d['indicios'])} indícios")
t("trilha do dinheiro", tri)

print("\n=== 4. AUTONOMIA ===")
def semaforo():
    import publicacao_diaria as pd
    s = pd.apurar(7)
    r = s['resumo']
    return f"{r['dias_uteis']} dias úteis, {r['contagem']}"
t("semáforo diário reapura sozinho", semaforo)

def idem():
    import publicacao_diaria as pd
    a = pd.apurar(7)['resumo']; b = pd.apurar(7)['resumo']
    assert a['contagem'] == b['contagem'], "não idempotente"
    return "resultado estável em duas execuções"
t("idempotência (roda 2x, mesmo resultado)", idem)

def semchave():
    import os
    assert not os.environ.get('ANTHROPIC_API_KEY'), "chave presente no ambiente de teste"
    return "nenhuma chave de API no ambiente — tudo acima rodou de graça"
t("independência de API paga", semchave)

def busca():
    import busca_local
    r = busca_local.buscar("IGD", limite=3)
    return f"{len(r)} resultados, custo zero"
t("banco de busca local", busca)

def oficio():
    p = R/'documentos'/'Oficio_LAI_CMASGyn.docx'
    assert p.exists() and p.stat().st_size > 10000
    return f"{p.stat().st_size} bytes"
t("ofício de acesso à informação gerado", oficio)

print("\n" + "="*70)
print(f"RESULTADO: {len(ok)} passaram, {len(falhas)} falharam")
if falhas:
    for n, e in falhas: print(f"  ! {n}: {e}")
print("="*70)
sys.exit(1 if falhas else 0)
