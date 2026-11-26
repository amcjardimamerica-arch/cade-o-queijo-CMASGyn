#!/usr/bin/env python3
"""Captura de resolucoes do CNAS pelo Diario Oficial da Uniao.

Via primaria que funciona: o proprio DOU. Os portais do Ministerio caem, mudam
de endereco e encerram plataformas; o DOU permanece e e a fonte autoritativa.

Estrategia de tres vias, em cascata:
  1. DOU busca estruturada, janelas de data, delta=50, texto em /web/dou/-/{slug}
  2. blob individual do Participa+Brasil, quando o identificador for conhecido
  3. PDF da pagina do DOU antigo, para materia anterior a 2016

Fidelidade: extrai o corpo da materia, preserva texto literal, grava cabecalho
com data, edicao, secao, pagina e URL. Nunca resume nem interpreta.
"""
import re,json,os,sys,time,html,urllib.request
UA={'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) Chrome/120'}
RAIZ=os.path.join(os.path.dirname(__file__),'..')
DEST=os.path.join(RAIZ,'corpus_txt','cnas')
CAT=os.path.join(RAIZ,'config','catalogo_cnas.json')
os.makedirs(DEST,exist_ok=True)

def get(u,binario=False,t=30):
    try:
        with urllib.request.urlopen(urllib.request.Request(u,headers=UA),timeout=t) as r:
            b=r.read()
        return b if binario else b.decode('utf-8','ignore')
    except Exception:
        return None

def indice(d1,d2):
    """Via 1a - lista materias na janela. delta=50 e o teto por consulta."""
    u=("https://www.in.gov.br/consulta/-/buscar/dou?q=%22RESOLU%C3%87%C3%83O+CNAS%22&s=do1"
       f"&exactDate=personalizado&publishFrom={d1}&publishTo={d2}&delta=50&sortType=0")
    t=get(u)
    if not t: return []
    m=re.search(r'type="application/json">\s*(\{.*?\})\s*</script>',t,re.S)
    if not m: return []
    try: return json.loads(m.group(1)).get("jsonArray",[])
    except Exception: return []

def texto_dou(slug):
    """Via 1b - corpo literal da materia."""
    t=get("https://www.in.gov.br/web/dou/-/"+slug)
    if not t: return None
    for pat in (r'<div[^>]*class="[^"]*texto-dou[^"]*"[^>]*>(.*?)</div>\s*</div>',
                r'id="materia"(.*?)</article>', r'class="texto-dou"(.*?)<script'):
        m=re.search(pat,t,re.S)
        if not m: continue
        c=re.sub(r'<(script|style)[^>]*>.*?</\1>',' ',m.group(1),flags=re.S)
        c=re.sub(r'</p>|<br\s*/?>','\n',c,flags=re.I)
        c=re.sub(r'<[^>]+>',' ',c); c=html.unescape(c)
        c=re.sub(r'[ \t\xa0]+',' ',c); c=re.sub(r'\n\s*\n+','\n',c).strip()
        if len(c)>300: return c
    return None

def via_blob(ident):
    """Via 2 - documento individual do Participa+Brasil, se o id for conhecido."""
    b=get(f"https://www.gov.br/participamaisbrasil/blob/baixar/{ident}",binario=True)
    return b if b and b[:4]==b'%PDF' else None

def via_dou_antigo(data,pagina):
    """Via 3 - PDF da pagina do DOU. Para materia anterior a 2016.
    data no formato DD/MM/AAAA."""
    b=get(f"https://pesquisa.in.gov.br/imprensa/servlet/INPDFViewer"
          f"?jornal=1&pagina={pagina}&data={data}&captchafield=firstAccess",binario=True)
    return b if b and b[:4]==b'%PDF' else None

def gravar(slug,meta,corpo):
    nome=re.sub(r'[^a-z0-9]+','_',slug.lower())[:80]+".txt"
    cab=(f"# {re.sub(r'<[^>]+>','',html.unescape(meta.get('title','')))}\n"
         f"# DOU {meta.get('pubDate','')} Edicao {meta.get('editionNumber','')} "
         f"Secao 1 Pagina {meta.get('numberPage','')}\n"
         f"# fonte: https://www.in.gov.br/web/dou/-/{slug}\n\n")
    open(os.path.join(DEST,nome),'w',encoding='utf-8').write(cab+corpo)
    return nome

def main(ano_ini=2016,ano_fim=None):
    from datetime import date
    ano_fim=ano_fim or date.today().year
    novos=falhas=0
    ULT=[31,28,31,30,31,30,31,31,30,31,30,31]
    for ano in range(ano_ini,ano_fim+1):
        for tri,(a,b) in enumerate([("01-01","31-03"),("01-04","30-06"),
                                    ("01-07","30-09"),("01-10","31-12")]):
            lote=indice(f"{a}-{ano}",f"{b}-{ano}")
            if len(lote)>=50:   # janela estourou o teto, refinar por mes
                lote=[]
                for m in range(tri*3+1,tri*3+4):
                    lote+=indice(f"01-{m:02d}-{ano}",f"{ULT[m-1]}-{m:02d}-{ano}")
                    time.sleep(0.3)
            for x in lote:
                slug=x.get("urlTitle","")
                if not re.match(r'resolucao',slug,re.I): continue
                nome=re.sub(r'[^a-z0-9]+','_',slug.lower())[:80]+".txt"
                if os.path.exists(os.path.join(DEST,nome)): continue
                c=texto_dou(slug)
                if c: gravar(slug,x,c); novos+=1
                else: falhas+=1
                time.sleep(0.25)
            print(f"{ano}T{tri+1}: lote={len(lote)} novos={novos} falhas={falhas}",
                  file=sys.stderr,flush=True)
            time.sleep(0.3)
    # atualizar catalogo
    if os.path.exists(CAT):
        cat=json.load(open(CAT,encoding='utf-8'))
        cat["_meta"]["ultima_captura"]={"executado_em":date.today().isoformat(),
            "novos":novos,"falhas":falhas,
            "total_com_texto":len([f for f in os.listdir(DEST) if f.endswith('.txt')])}
        json.dump(cat,open(CAT,'w',encoding='utf-8'),ensure_ascii=False,indent=1)
    print(json.dumps({"novos":novos,"falhas":falhas},ensure_ascii=False))

if __name__=='__main__':
    main(int(sys.argv[1]) if len(sys.argv)>1 else 2016)
