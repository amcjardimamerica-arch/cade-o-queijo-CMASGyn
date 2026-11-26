#!/usr/bin/env python3
"""Destilador. Le tudo que o coletor e o analisador produziram e escreve
docs/CONSULTA.md com teto rigido de tamanho.

Principio de economia de tokens: o repositorio processa megabytes; o chat le
kilobytes. Se o destilado passar do teto, corta pelo fim, nunca pelo topo -
achado critico fica sempre visivel."""
import os, json, sys
from datetime import datetime

RAIZ = os.path.join(os.path.dirname(__file__), '..')
DADOS = os.path.join(RAIZ, 'dados'); DOCS = os.path.join(RAIZ, 'docs')
os.makedirs(DOCS, exist_ok=True)

TETO_CARACTERES = 24000   # ~6k tokens
def L(n):
    p = os.path.join(DADOS, n)
    return json.load(open(p, encoding='utf-8')) if os.path.exists(p) else None

def brl(v):
    try: return f"R$ {float(v):,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
    except Exception: return str(v)

def montar():
    an = L('analise_retroativa.json') or {}
    sem = L('publicacao_diaria.json') or {}
    fin = L('financeiro.json') or {}
    L_ = []
    a = L_.append
    a(f"# Vigilancia CMASGyn e SEMASDH - destilado de {datetime.utcnow():%d/%m/%Y %H:%M} UTC")
    a("")
    a("Documento gerado pelo repositorio. As analises consultam APENAS config/base_legal.json.")
    a("")

    # 1 SEMAFORO SEMPRE PRIMEIRO
    a("## 0. Semaforo do proprio sistema (SYS-01)")
    a("")
    a(f"- Estado: **{sem.get('estado','SEM DADO')}**")
    a(f"- Ultima publicacao indexada: {sem.get('ultima_publicacao','-')}")
    a(f"- Dias uteis sem edicao: {sem.get('dias_uteis_sem_edicao','-')}")
    a(f"- Leitura: {sem.get('leitura','-')}")
    a("")

    # 2 ACHADOS POR SEVERIDADE E TRILHA
    ach = an.get('achados', [])
    ordem = {"critica": 0, "alta": 1, "media": 2, "baixa": 3}
    ach.sort(key=lambda x: (ordem.get(x.get('severidade'), 9), x.get('trilha', '')))
    for trilha, titulo in (("SEMASDH", "1. Trilha SEMASDH e Fundo Municipal"),
                           ("CMASGYN", "2. Trilha CMASGyn - controle social")):
        sub = [x for x in ach if x.get('trilha') == trilha]
        a(f"## {titulo}")
        a("")
        if not sub: a("Sem achados no ciclo."); a(""); continue
        for x in sub:
            a(f"**[{x['parametro']}] {x['titulo']}** — severidade {x['severidade']}, selo {x['selo']}")
            a("")
            a(x['detalhe'])
            a("")
            if x.get('norma'): a(f"*Norma:* {x['norma']}"); a("")

    # 3 INTEGRIDADE
    a("## 3. Integridade do proprio sistema")
    a("")
    a("| Regra | Situacao |")
    a("|---|---|")
    for i in an.get('integridade_sistema', []):
        det = []
        for k, v in i.items():
            if k in ('id', 'titulo', 'exemplos', 'maiores', 'lista_invalidas', 'duplicadas_por_formatacao'): continue
            det.append(f"{k}={brl(v) if isinstance(v,(int,float)) and abs(v)>1000 else v}")
        a(f"| {i['id']} {i['titulo']} | {'; '.join(det[:4])} |")
    a("")

    # 4 PADROES
    if an.get('padroes'):
        a("## 4. Padroes e reincidencia")
        a("")
        a("| Codigo | Padrao | Serie anual |")
        a("|---|---|---|")
        for p in an['padroes']:
            a(f"| {p['id']} | {p['nome']} | {p.get('serie_anual')} |")
        a("")

    # 5 LACUNAS
    a("## 5. Dado faltante (achado por omissao)")
    a("")
    a("| Codigo | Falta | Impede | Onde obter |")
    a("|---|---|---|---|")
    for l in an.get('lacunas', []):
        a(f"| {l['id']} | {l['falta']} | {', '.join(l['impede'][:3])} | {l['onde']} |")
    a("")

    # 6 NUMEROS DE APOIO
    if fin:
        a("## 6. Numeros de apoio")
        a("")
        a(f"- Valor rastreado na funcao 08: {brl(fin.get('valor_total'))}")
        a(f"- Rastreabilidade da origem: {fin.get('indice_rastreabilidade')}%")
        a(f"- Linhas: {fin.get('linhas')}")
        a("")

    a("---")
    a("Indice global e piso. Use o numero confirmado por duas vias em qualquer peca.")
    a("Indicio de sobrepreco e indicio; sobrepreco se demonstra por pericia com preco de mercado.")
    a("Nada aqui e peca processual sem revisao do advogado, artigo 32 da Lei 8.906/1994.")
    return "\n".join(L_)

if __name__ == '__main__':
    txt = montar()
    if len(txt) > TETO_CARACTERES:
        txt = txt[:TETO_CARACTERES] + "\n\n> [truncado no teto de economia de tokens; detalhe em dados/analise_retroativa.json]"
    open(os.path.join(DOCS, 'CONSULTA.md'), 'w', encoding='utf-8').write(txt)
    print(f"CONSULTA.md {len(txt)} caracteres (~{len(txt)//4} tokens)")
