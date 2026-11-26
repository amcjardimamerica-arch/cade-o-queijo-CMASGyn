#!/usr/bin/env python3
"""Atualizacao mensal do corpus legal. Roda no Actions, nunca no chat.
Rebaixa as normas e reconverte para texto. Depois disso, TODA consulta de
legislacao usa corpus_txt/ via consulta_local.py, sem rede."""
import os,re,html,json,urllib.request,hashlib
UA={'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) Chrome/120'}
RAIZ=os.path.join(os.path.dirname(__file__),'..')
P="https://www.planalto.gov.br/ccivil_03/"
G="https://www.goiania.go.gov.br/html/gabinete_civil/sileg/dados/legis/"
FONTES={
 "federal/constituicao_federal.html":P+"constituicao/constituicao.htm",
 "federal/lei_8742_1993_loas.html":P+"leis/l8742compilado.htm",
 "federal/lei_14601_2023.html":P+"_ato2023-2026/2023/lei/L14601.htm",
 "federal/lei_13019_2014.html":P+"_ato2011-2014/2014/lei/l13019.htm",
 "federal/lei_14133_2021.html":P+"_ato2019-2022/2021/lei/l14133.htm",
 "federal/lei_12527_2011.html":P+"_ato2011-2014/2011/lei/l12527.htm",
 "federal/lei_4320_1964.html":P+"leis/l4320compilado.htm",
 "federal/lc_101_2000.html":P+"leis/lcp/lcp101.htm",
 "federal/lei_9784_1999.html":P+"leis/l9784.htm",
 "municipal/lei_7531_1995_fmas.html":G+"1995/lo_19951226_000007531.html",
 "municipal/lei_9009_2010_cmasgyn.html":G+"2010/lo_20101230_000009009.html",
}
def baixar(u):
    r=urllib.request.Request(u,headers=UA)
    return urllib.request.urlopen(r,timeout=90).read()
def limpar(raw):
    for enc in ('utf-8','cp1252','latin-1'):
        try:
            t=raw.decode(enc)
            if 'Assistência' in t or 'Municipal' in t or enc=='latin-1': break
        except: continue
    t=re.sub(r'<(script|style)[^>]*>.*?</\1>',' ',t,flags=re.S|re.I)
    t=re.sub(r'<[^>]+>',' ',t); t=html.unescape(t)
    return re.sub(r'\n\s*\n+','\n',re.sub(r'[ \t\xa0]+',' ',t))
idx={}
for rel,url in FONTES.items():
    dst=os.path.join(RAIZ,'corpus',rel)
    os.makedirs(os.path.dirname(dst),exist_ok=True)
    try:
        b=baixar(url)
        if len(b)<3000: raise ValueError("resposta curta")
        open(dst,'wb').write(b)
        t=limpar(b); dt=os.path.join(RAIZ,'corpus_txt',rel.replace('.html','.txt'))
        os.makedirs(os.path.dirname(dt),exist_ok=True); open(dt,'w',encoding='utf-8').write(t)
        idx[rel]={"bytes":len(b),"sha256":hashlib.sha256(b).hexdigest()[:16],"ok":True}
        print("OK",rel,len(b))
    except Exception as e:
        idx[rel]={"ok":False,"erro":str(e)}; print("FALHA",rel,e)
json.dump(idx,open(os.path.join(RAIZ,'corpus','INDICE.json'),'w'),ensure_ascii=False,indent=1)
