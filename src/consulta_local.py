#!/usr/bin/env python3
"""Consulta a legislacao SEM REDE. Usa apenas corpus/.
Uso: python3 consulta_local.py "artigo 30" lei_8742
Devolve so o trecho pedido - e o mecanismo de economia de tokens."""
import os,re,sys,json
RAIZ=os.path.join(os.path.dirname(__file__),'..')
BASE=os.path.join(RAIZ,'corpus')
def arquivos(filtro=None):
    for r,_,fs in os.walk(BASE):
        for f in fs:
            if f.endswith('.txt') and (not filtro or filtro.lower() in f.lower()):
                yield os.path.join(r,f)
def buscar(termo,filtro=None,janela=900,maximo=6):
    res=[]
    rx=re.compile(re.escape(termo).replace(r'\ ',r'[\s\.\u00ba]*'),re.I)
    for p in arquivos(filtro):
        t=open(p,encoding='utf-8',errors='ignore').read()
        for m in list(rx.finditer(t))[:maximo]:
            s=max(0,m.start()-80)
            res.append({"arquivo":os.path.relpath(p,BASE),"trecho":re.sub(r'\s+',' ',t[s:m.start()+janela])})
    return res
if __name__=='__main__':
    termo=sys.argv[1]; filtro=sys.argv[2] if len(sys.argv)>2 else None
    r=buscar(termo,filtro)
    print(json.dumps(r[:4],ensure_ascii=False,indent=1))
