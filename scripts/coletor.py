#!/usr/bin/env python3
"""Coletor diario. Roda no GitHub Actions, nao no chat.
Tres fontes: Diario Oficial de Goiania, Portal da Transparencia e FNAS.
Toda a carga pesada acontece aqui. O chat recebe apenas o destilado."""
import os, re, json, hashlib, sys
from datetime import date, timedelta, datetime
import urllib.request, urllib.error

RAIZ = os.path.join(os.path.dirname(__file__), '..')
DADOS = os.path.join(RAIZ, 'dados'); ESTADO = os.path.join(RAIZ, 'estado')
ACERVO = os.path.join(RAIZ, 'acervo')
for d in (DADOS, ESTADO, ACERVO): os.makedirs(d, exist_ok=True)

UA = {'User-Agent': 'Mozilla/5.0 (vigilancia-cmasgyn)'}
TIMEOUT = 60

def get(url, binario=False):
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            b = r.read()
        return b if binario else b.decode('utf-8', 'ignore')
    except Exception as e:
        print(f"  ! {url} -> {e}", file=sys.stderr)
        return None

# ---------------------------------------------------------------- 1. DIARIO
BASE_DO = "http://sileg.goiania.go.gov.br/geral/"

def carrega_estado():
    p = os.path.join(ESTADO, 'historico_registro.json')
    return json.load(open(p, encoding='utf-8')) if os.path.exists(p) else {"edicoes": {}, "ultimo_numero": None}

def coleta_diario(estado, dias=7):
    """Varre por numero sequencial a partir do ultimo conhecido.
    O nome segue do_AAAAMMDD_000008NNN.pdf"""
    novos = []
    ult = estado.get('ultimo_numero') or 8829
    hoje = date.today()
    for n in range(ult, ult + 40):
        achou = False
        for delta in range(0, dias * 3):
            d = hoje - timedelta(days=delta)
            for suf in ('', '_edi'):
                nome = f"do_{d:%Y%m%d}_{n:012d}{suf}.pdf"
                if nome in estado['edicoes']: achou = True; break
                b = get(BASE_DO + nome, binario=True)
                if b and b[:4] == b'%PDF':
                    h = hashlib.sha256(b).hexdigest()
                    open(os.path.join(ACERVO, nome), 'wb').write(b)
                    estado['edicoes'][nome] = {"data": d.isoformat(), "sha256": h,
                                               "bytes": len(b), "numero": n}
                    estado['ultimo_numero'] = max(n, estado.get('ultimo_numero') or 0)
                    novos.append(nome); achou = True; break
            if achou: break
        if not achou and n > (estado.get('ultimo_numero') or 0) + 5: break
    return novos

# ---------------------------------------------------------------- 2. SEMAFORO
def semaforo(estado):
    """SYS-01: alerta se 3 dias uteis sem edicao nova."""
    datas = sorted({v['data'] for v in estado['edicoes'].values()})
    ultima = datas[-1] if datas else None
    hoje = date.today()
    uteis = 0
    if ultima:
        d = date.fromisoformat(ultima)
        while d < hoje:
            d += timedelta(days=1)
            if d.weekday() < 5: uteis += 1
    st = {"ultima_publicacao": ultima, "dias_uteis_sem_edicao": uteis,
          "estado": "VERDE" if uteis <= 2 else ("AMARELO" if uteis <= 5 else "VERMELHO"),
          "regra": "SYS-01",
          "leitura": ("coletor operante" if uteis <= 2 else
                      "ATENCAO: ou o Municipio parou de publicar, ou o coletor quebrou. "
                      "Coletor parado produz silencio, e silencio parece regularidade.")}
    json.dump(st, open(os.path.join(DADOS, 'publicacao_diaria.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    return st

# ---------------------------------------------------------------- 3. EXTRACAO
RE_NAT10 = re.compile(r'\b(\d{8})\.?(\d{2})?\b')
RE_DOT = re.compile(r'\b(\d{2})\.(\d{3})\.(\d{4})\.(\d{4})\b')
RE_VAL = re.compile(r'R\$\s*([\d\.]+,\d{2})')
RE_CNPJ = re.compile(r'\b(\d{2})\.?(\d{3})\.?(\d{3})/?(\d{4})-?(\d{2})\b')
RE_INSTR = re.compile(r'(TERMO DE (?:FOMENTO|COLABORA\w+)|CONTRATO|CONV\w+NIO|ACORDO DE COOPERA\w+)\s*n?[.\u00ba\s]*(\d{1,4}\s*/\s*\d{4})', re.I)
RE_RES = re.compile(r'RESOLU\w+\s+(?:AD\s+REFERENDUM\s+)?N?[.\u00ba\s]*(\d{1,4})\s*/\s*(\d{4})', re.I)
RE_PROC = re.compile(r'\b(\d{2}\.\d{1,2}\.\d{9}-\d)\b')

def valor(s): return float(s.replace('.', '').replace(',', '.'))

def dv_ok(c):
    n = re.sub(r'\D', '', c)
    if len(n) != 14 or len(set(n)) == 1: return False
    for pos, p in ((12, [5,4,3,2,9,8,7,6,5,4,3,2]), (13, [6,5,4,3,2,9,8,7,6,5,4,3,2])):
        r = sum(int(n[i]) * p[i] for i in range(pos)) % 11
        if int(n[pos]) != (0 if r < 2 else 11 - r): return False
    return True

def pares_natureza_valor(txt):
    """SYS-02: natureza e valor lidos da MESMA posicao, nunca de posicoes vizinhas."""
    pares = []
    for m in re.finditer(r'(\d{2}\.\d{3}\.\d{4}\.\d{4})\.(\d{8})(\d{2})?[.\s]([\d\s]+?)(\d{4})\s+(\d{4})\s+R\$\s*([\d\.]+,\d{2})', txt):
        pares.append({"dotacao": m.group(1), "natureza": m.group(2),
                      "subitem": m.group(3), "fonte": m.group(5),
                      "valor": valor(m.group(7)), "trecho": m.group(0)[:120]})
    return pares

def extrai(nome, texto):
    reg = {"edicao": nome, "resolucoes": [], "instrumentos": [], "cnpjs": [],
           "linhas_orcamentarias": [], "processos": []}
    for m in RE_RES.finditer(texto):
        reg['resolucoes'].append({"numero": int(m.group(1)), "ano": int(m.group(2)),
                                  "ad_referendum": 'AD REFERENDUM' in m.group(0).upper(),
                                  "pos": m.start()})
    for m in RE_INSTR.finditer(texto):
        reg['instrumentos'].append({"tipo": m.group(1).upper(), "numero": re.sub(r'\s', '', m.group(2)),
                                    "pos": m.start()})
    vistos = set()
    for m in RE_CNPJ.finditer(texto):
        c = f"{m.group(1)}.{m.group(2)}.{m.group(3)}/{m.group(4)}-{m.group(5)}"
        if c in vistos: continue
        vistos.add(c)
        reg['cnpjs'].append({"cnpj": c, "dv_valido": dv_ok(c), "pos": m.start()})
    reg['linhas_orcamentarias'] = pares_natureza_valor(texto)
    reg['processos'] = sorted({m.group(1) for m in RE_PROC.finditer(texto)})
    return reg

def texto_pdf(caminho):
    try:
        import pdfplumber
        with pdfplumber.open(caminho) as pdf:
            return "\n".join((p.extract_text() or '') for p in pdf.pages)
    except Exception:
        try:
            from pypdf import PdfReader
            return "\n".join((p.extract_text() or '') for p in PdfReader(caminho).pages)
        except Exception as e:
            print(f"  ! sem texto: {caminho} {e}", file=sys.stderr)
            return ""

# ---------------------------------------------------------------- 4. TRANSPARENCIA
def coleta_transparencia(ano, orgao='3650'):
    """LAC-02. Empenho, liquidacao e pagamento por credor e competencia.
    PREENCHER a URL apos confirmar o endpoint do Portal da Transparencia de Goiania.
    Enquanto nao preenchido, grava lacuna explicita - dado faltante e achado."""
    alvo = os.path.join(DADOS, f'execucao_{ano}.json')
    if os.environ.get('URL_TRANSPARENCIA'):
        raw = get(os.environ['URL_TRANSPARENCIA'].format(ano=ano, orgao=orgao))
        if raw:
            open(alvo, 'w', encoding='utf-8').write(raw); return True
    json.dump({"status": "LACUNA", "id": "LAC-02", "ano": ano,
               "falta": "empenho, liquidacao e pagamento por credor e competencia",
               "norma": "Artigo 48-A, inciso I, da Lei Complementar 101/2000",
               "acao": "definir a variavel URL_TRANSPARENCIA ou juntar extracao manual"},
              open(alvo, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return False

def coleta_fnas(ano):
    """LAC-03. Parcelas pagas pelo Fundo Nacional por competencia e bloco."""
    alvo = os.path.join(DADOS, f'fnas_{ano}.json')
    if os.environ.get('URL_FNAS'):
        raw = get(os.environ['URL_FNAS'].format(ano=ano))
        if raw: open(alvo, 'w', encoding='utf-8').write(raw); return True
    json.dump({"status": "LACUNA", "id": "LAC-03", "ano": ano,
               "falta": "repasses do FNAS por competencia e bloco",
               "norma": "Artigo 30 da Lei 8.742/1993",
               "acao": "definir a variavel URL_FNAS ou juntar extracao manual da Consulta de Pagamentos"},
              open(alvo, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return False

# ---------------------------------------------------------------- MAIN
if __name__ == '__main__':
    est = carrega_estado()
    novos = coleta_diario(est)
    print(f"edicoes novas: {len(novos)}")
    registros = []
    for nome in novos:
        t = texto_pdf(os.path.join(ACERVO, nome))
        if t: registros.append(extrai(nome, t))
    if registros:
        p = os.path.join(DADOS, 'coleta_bruta.json')
        antigo = json.load(open(p, encoding='utf-8')) if os.path.exists(p) else []
        json.dump(antigo + registros, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    json.dump(est, open(os.path.join(ESTADO, 'historico_registro.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    st = semaforo(est)
    print(f"semaforo: {st['estado']} - {st['dias_uteis_sem_edicao']} dias uteis")
    ano = date.today().year
    coleta_transparencia(ano); coleta_fnas(ano)
