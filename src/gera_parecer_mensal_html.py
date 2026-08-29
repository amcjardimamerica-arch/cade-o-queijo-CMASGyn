#!/usr/bin/env python3
"""Parecer mensal em HTML único — visual law, autossuficiente, com a marca
do Núcleo de Fiscalização no topo.

Tópicos, em seções distintas:
  1. resumo em uma frase e placar;
  2. linha do exercício (jan–jul, mês em destaque);
  3. fluxograma de balões — entrada de valores → conta do Fundo → saída,
     com balões proporcionais, tooltip no passar do mouse e dados completos
     ao clicar;
  4. fluxograma das duas contas — Fundo (3650) × Gabinete da Secretaria
     (3601), com a transferência automática descumprida em destaque;
  5. de onde veio — pizza das fontes previstas do mês;
  6. as quatro estações legais no mês;
  7. calendário do Diário Oficial;
  8. cronologia da trilha do dinheiro, com o valor classificado pela
     estação alcançada (repasse publicado > empenho > menção textual);
  9. prestação de contas mensal por entidade — omissões, com semáforo de
     verificação: verde = duas vias independentes, azul = uma via,
     laranja = só menção, vermelho = totalmente omisso;
 10. demonstrações de dados (IGD e entidades);
 11. fichas de desconformidade; condições estruturais; advertência.

Toda informação visual tem resumo no hover (tooltip/data-tip ou <title>
em SVG) e abertura de dados completos no clique (<details>).

CNPJ é sempre normalizado por dígitos antes de casar com o cadastro e
exibido no padrão 00.000.000/0000-00 — '05039050/0001-04' e
'05.039.050/0001-04' são a mesma inscrição.
"""
from __future__ import annotations
import json, math, re, sys
from datetime import date, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DADOS = RAIZ / "dados"
REL = RAIZ / "relatorios" / "mensal"
DOCS = RAIZ / "docs" / "mensal"
sys.path.insert(0, str(RAIZ / "src"))
from marca import cabecalho_html, rodape_marca_html

COR_SEV = {"critica": "#8c1d18", "alta": "#a85b00", "media": "#5c5c00"}
ROTULO_SEV = {"critica": "CRÍTICA", "alta": "ALTA", "media": "MÉDIA"}
COR_SELO = {"CONFIRMADO": "#1d4f2b", "INDICIARIO": "#6a4a00",
            "INCONCLUSIVO_POR_DOCUMENTO_FALTANTE": "#4a4a58"}
ROTULO_SELO = {"CONFIRMADO": "CONFIRMADO — duas vias independentes",
               "INDICIARIO": "INDICIÁRIO — uma via",
               "INCONCLUSIVO_POR_DOCUMENTO_FALTANTE":
               "INCONCLUSIVO — documento faltante"}
ICONE = {"REC": "◔", "IGD": "▣", "PUB": "▤", "EXE": "⇢", "CMAS": "◈"}
COR_FONTE = {"1660": "#3a5f8a", "1661": "#4a7c59", "1665": "#7a9c6e",
             "tesouro": "#8c1d18", "patrimonial": "#a85b00",
             "nao_identificada": "#8a8a94"}
NOME_FONTE = {"1660": "União — FNAS (contém IGD)", "1661": "Estado",
              "1665": "Estado — programas", "tesouro": "Tesouro Municipal",
              "patrimonial": "Receita patrimonial",
              "nao_identificada": "Fonte não identificada"}
COR_EST = {"dotacao": "#3a5f8a", "orcamento": "#3a5f8a", "credito": "#5b7ea8",
           "empenho": "#a85b00", "liquidacao": "#1d4f2b",
           "pagamento": "#1d4f2b", "repasse": "#4a7c59",
           "vinculo": "#6a4a00", "entidade": "#5c5c00"}
MESES_ROT = ["jan", "fev", "mar", "abr", "mai", "jun", "jul",
             "ago", "set", "out", "nov", "dez"]
DESPESA = {"repasse", "liquidacao", "pagamento"}

CSS = """
:root{--tinta:#1c1b1f;--papel:#faf8f5;--linha:#d8d2c8;--rubrica:#8c1d18;--suave:#6b6660;
--azul:#1d4f8a;--ouro:#e8a000}
*{box-sizing:border-box;margin:0;padding:0}
body{font:16px/1.55 Georgia,'Times New Roman',serif;color:var(--tinta);
background:var(--papel);max-width:940px;margin:0 auto;padding:28px 22px 60px}
header.peca{border-bottom:3px double var(--tinta);padding-bottom:14px;margin-bottom:22px}
.orgao{font:700 11px/1.5 Arial,sans-serif;letter-spacing:.12em;text-transform:uppercase;color:var(--suave)}
h1{font:400 28px/1.2 Georgia,serif;margin:6px 0 2px}
h1 b{color:var(--rubrica)}
.uma-frase{background:#fff;border-left:6px solid var(--rubrica);padding:14px 18px;
margin:18px 0;font-size:19px;box-shadow:0 1px 3px rgba(0,0,0,.07)}
.uma-frase small{display:block;font:700 11px/2 Arial,sans-serif;letter-spacing:.12em;
text-transform:uppercase;color:var(--suave)}
.placar{display:flex;gap:10px;flex-wrap:wrap;margin:16px 0}
.placar div{flex:1;min-width:130px;background:#fff;border:1px solid var(--linha);
border-top:4px solid var(--cor,#888);padding:10px 12px;text-align:center}
.placar .n{font:700 30px/1 Arial,sans-serif}
.placar .t{font:700 10px/1.5 Arial,sans-serif;letter-spacing:.1em;text-transform:uppercase;color:var(--suave)}
h2{font:700 13px/1.4 Arial,sans-serif;letter-spacing:.14em;text-transform:uppercase;
border-bottom:1px solid var(--linha);padding-bottom:6px;margin:36px 0 12px}
.explica{font:13px/1.6 Arial,sans-serif;color:var(--suave);margin:0 0 12px}
[data-tip]{position:relative;cursor:help}
[data-tip]:hover::after{content:attr(data-tip);position:absolute;left:0;top:calc(100% + 8px);
z-index:9;background:#1c2733;color:#fff;font:12px/1.5 Arial,sans-serif;padding:8px 11px;
border-radius:6px;width:max-content;max-width:340px;white-space:normal;
box-shadow:0 4px 14px rgba(0,0,0,.25)}
[data-tip]:hover::before{content:"";position:absolute;left:14px;top:100%;z-index:9;
border:7px solid transparent;border-bottom-color:#1c2733;transform:translateY(-1px)}
details.dados{margin:8px 0 4px;font:13px/1.6 Arial,sans-serif}
details.dados>summary{cursor:pointer;color:var(--azul);font-weight:700;list-style:none}
details.dados>summary::before{content:"▸ ";transition:.15s}
details.dados[open]>summary::before{content:"▾ "}
details.dados>div{background:#fff;border:1px solid var(--linha);border-radius:6px;
padding:10px 14px;margin-top:6px}
.grade2{display:grid;grid-template-columns:300px 1fr;gap:18px;align-items:center}
@media(max-width:700px){.grade2{grid-template-columns:1fr}}
.leg{font:13px/1.9 Arial,sans-serif}
.leg i{display:inline-block;width:12px;height:12px;border-radius:3px;vertical-align:-1px;margin-right:7px}
.leg b.v{float:right;font-family:Arial}
.calendario{display:grid;grid-template-columns:repeat(auto-fill,minmax(30px,1fr));gap:4px}
.dia{aspect-ratio:1;display:flex;align-items:center;justify-content:center;
font:700 11px/1 Arial,sans-serif;border-radius:4px;color:#fff}
.dia.pub{background:#1d4f2b}.dia.nao{background:#8c1d18}
.dia.fds{background:#e6e1d8;color:#a09a90}
.legenda{font:12px/1.6 Arial,sans-serif;color:var(--suave);margin-top:8px}
.legenda i{display:inline-block;width:11px;height:11px;border-radius:3px;
vertical-align:-1px;margin:0 4px 0 12px}
.crono{position:relative;margin:8px 0 0 8px;padding-left:26px;border-left:3px solid var(--linha)}
.ev{position:relative;margin:0 0 14px;background:#fff;border:1px solid var(--linha);
border-radius:6px;padding:9px 12px;page-break-inside:avoid}
.ev::before{content:"";position:absolute;left:-33px;top:14px;width:13px;height:13px;
border-radius:50%;background:var(--pt,#888);border:3px solid var(--papel)}
.ev .qd{font:700 12px/1.4 Arial,sans-serif;color:var(--suave)}
.ev .qd b{color:var(--tinta)}
.chip{display:inline-block;font:700 10px/1 Arial,sans-serif;letter-spacing:.06em;
padding:4px 8px;border-radius:999px;color:#fff;margin:3px 4px 0 0;text-transform:uppercase}
.ev .ent{font:13px/1.5 Arial,sans-serif;margin-top:5px}
.ev .val{font:700 13px/1.3 Arial,sans-serif;float:right;text-align:right}
.ev .val small{display:block;font:700 9px/1.4 Arial;letter-spacing:.08em;color:var(--suave);text-transform:uppercase}
table{border-collapse:collapse;width:100%;font:13px/1.5 Arial,sans-serif;background:#fff}
th{font:700 10px/1.4 Arial,sans-serif;letter-spacing:.1em;text-transform:uppercase;
color:var(--suave);text-align:left;border-bottom:2px solid var(--tinta);padding:7px 9px}
td{border-bottom:1px solid var(--linha);padding:7px 9px;vertical-align:top}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
tr.ruim td{background:#faf1f0}
.presta{display:grid;gap:8px}
.plin{background:#fff;border:1px solid var(--linha);border-radius:6px}
.plin>summary{display:grid;grid-template-columns:1fr auto 26px;gap:12px;align-items:center;
padding:9px 12px;cursor:pointer;list-style:none;font:13px/1.45 Arial,sans-serif}
.plin>summary::-webkit-details-marker{display:none}
.plin .quem b{display:block}
.plin .oq{font:12px/1.4 Arial,sans-serif;text-align:right;color:var(--suave)}
.plin .oq b{color:var(--tinta);font-size:13px}
.sem{width:15px;height:15px;border-radius:50%;justify-self:center;flex:none}
.sem.verde{background:#1d8a3a;box-shadow:0 0 0 3px #1d8a3a33}
.sem.azul{background:#1d4f8a;box-shadow:0 0 0 3px #1d4f8a33}
.sem.laranja{background:#e07b00;box-shadow:0 0 0 3px #e07b0033}
.sem.vermelho{background:#c1281f;box-shadow:0 0 0 3px #c1281f33}
.sem.roxo{background:#6b3fa0;box-shadow:0 0 0 3px #6b3fa033}
.plin .det{border-top:1px dashed var(--linha);padding:10px 12px;font:13px/1.6 Arial,sans-serif;background:#fbfaf7}
.ficha{background:#fff;border:1px solid var(--linha);border-radius:6px;
margin:0 0 16px;overflow:hidden;page-break-inside:avoid}
.ficha .topo{display:flex;align-items:center;gap:10px;padding:10px 14px;
border-left:6px solid var(--sev);background:linear-gradient(#fff,#fbf9f6)}
.ficha .ic{font-size:20px;color:var(--sev)}
.ficha .tit{font:700 15px/1.35 Arial,sans-serif;flex:1}
.badge{font:700 10px/1 Arial,sans-serif;letter-spacing:.08em;padding:5px 9px;
border-radius:999px;color:#fff;white-space:nowrap}
.corpo{padding:12px 16px 14px;display:grid;gap:10px}
.camada b.rot{display:block;font:700 10px/2 Arial,sans-serif;letter-spacing:.12em;
text-transform:uppercase;color:var(--suave)}
.falta{background:#f4f1ec;border:1px dashed var(--linha);padding:9px 12px;border-radius:4px}
.norma{font:12px/1.5 Arial,sans-serif;color:var(--suave);border-top:1px solid var(--linha);
padding:9px 16px;background:#fbfaf7}
.estrutural{background:#f4f1ec;border:1px solid var(--linha);padding:12px 16px;
font-size:14px;border-radius:6px}
.estrutural li{margin:4px 0 4px 18px}
footer{margin-top:40px;border-top:3px double var(--tinta);padding-top:12px;
font:12px/1.7 Arial,sans-serif;color:var(--suave)}
.adv{background:#fff;border:1px solid var(--rubrica);color:var(--rubrica);
font:700 12px/1.6 Arial,sans-serif;padding:10px 14px;border-radius:4px;margin-bottom:10px}
a{color:var(--azul)}
.fxg{display:grid;grid-template-columns:1fr 84px 1.05fr 84px 1fr;gap:0;align-items:start}
.fxg .colrot{grid-column:1/6;display:grid;grid-template-columns:1fr 84px 1.05fr 84px 1fr;
font:700 11px/1.4 Arial,sans-serif;letter-spacing:.1em;color:var(--suave);
text-transform:uppercase;text-align:center;margin-bottom:8px}
.qds{display:grid;gap:10px}
.qd{background:#fff;border:2px solid var(--qc,#3a5f8a);border-radius:10px;overflow:hidden}
.qd>summary{list-style:none;cursor:pointer;padding:9px 10px;min-height:78px;
display:flex;flex-direction:column;justify-content:center;gap:2px}
.qd>summary::-webkit-details-marker{display:none}
.qd .nm{font:700 12px/1.25 Arial,sans-serif}
.qd .vl{font:700 13px/1.2 Arial,sans-serif;color:var(--qc,#3a5f8a)}
.qd .sub{font:10px/1.3 Arial,sans-serif;color:var(--suave);text-transform:uppercase;letter-spacing:.06em}
.qd .abre{border-top:1px dashed var(--linha);background:#fbfaf7;
padding:9px 11px;font:12px/1.55 Arial,sans-serif}
.qd.central{border-width:3px;box-shadow:0 2px 10px rgba(29,79,138,.18)}
.qd.central>summary{min-height:110px;text-align:center;align-items:center}
.setacol svg{width:100%;height:100%}
.cr-bloco{margin:14px 0 6px;font:700 12px/1.4 Arial,sans-serif;letter-spacing:.12em;
text-transform:uppercase;color:#fff;background:var(--bc,#3a5f8a);display:inline-block;
padding:6px 12px;border-radius:6px}
.cr-etapa{font:700 11px/1.4 Arial,sans-serif;letter-spacing:.1em;text-transform:uppercase;
color:var(--suave);border-bottom:1px dashed var(--linha);margin:12px 0 8px;padding-bottom:4px}
.ev .li{display:block;font:13px/1.65 Arial,sans-serif;padding:1px 0;border-bottom:1px dotted #eee8de}
.ev .li b.k{display:inline-block;min-width:150px;font:700 10px/1.6 Arial,sans-serif;
letter-spacing:.1em;text-transform:uppercase;color:var(--suave)}
.parecer-mini{background:#fdf6f5;border-left:4px solid #c1281f;padding:8px 11px;
font:13px/1.55 Arial,sans-serif;margin-top:6px;border-radius:0 6px 6px 0}
.parte{margin:44px 0 6px;padding:14px 18px;border-radius:8px;color:#fff;
background:linear-gradient(100deg,var(--pc1,#1c2733),var(--pc2,#3a5f8a))}
.parte .pt{font:700 11px/1.6 Arial,sans-serif;letter-spacing:.18em;text-transform:uppercase;opacity:.85}
.parte .pn{font:400 22px/1.25 Georgia,serif}
.orig{display:inline-block;font:700 10px/1 Arial,sans-serif;letter-spacing:.06em;
padding:4px 8px;border-radius:4px;background:#eef2f7;color:#1d4f8a;margin:2px 4px 2px 0}
@media print{body{background:#fff}.ficha,.ev,.plin{box-shadow:none}
[data-tip]:hover::after,[data-tip]:hover::before{display:none}}
"""

ESTRUTURAIS = [
    ("Aporte próprio do Município no Fundo caiu 99,46%",
     "R$ 9.000 previstos em 2026 contra R$ 1.669.000 em 2025 — a previsão "
     "mensal de R$ 750,00 vigora em todos os meses do exercício."),
    ("R$ 81.202.000 correm fora do Fundo",
     "A unidade orçamentária 3601 concentra recursos do Tesouro que, por "
     "força do Artigo 30, parágrafo único, da Lei 8.742/1993, deveriam "
     "transitar pelo Fundo (unidade 3650)."),
    ("Dotação do Conselho sem execução publicada",
     "A ação 3650.0824401082.591 existe com R$ 256.000; nenhum empenho a "
     "débito dela foi localizado em edição alguma do exercício."),
]


# ------------------------------------------------------------------ util
def fmt(v, sinal=True):
    if v is None:
        return "—"
    s = "R$ " if sinal else ""
    return s + "{:,.2f}".format(v).replace(",", "X").replace(".", ",").replace("X", ".")


def digitos(c: str) -> str:
    return re.sub(r"\D", "", c or "")


def fmt_cnpj(c: str) -> str:
    n = digitos(c)
    if len(n) != 14:
        return c
    return f"{n[:2]}.{n[2:5]}.{n[5:8]}/{n[8:12]}-{n[12:]}"


def carrega(nome):
    return json.loads((DADOS / nome).read_text(encoding="utf-8"))


def esc(t):
    return (str(t).replace("&", "&amp;").replace('"', "&quot;")
            .replace("<", "&lt;").replace(">", "&gt;"))


def detalhes(rotulo, corpo_html):
    return (f'<details class="dados"><summary>{rotulo}</summary>'
            f'<div>{corpo_html}</div></details>')


def mapa_entidades():
    """CNPJ (dígitos) -> {nome, municipio, uf, sem_fins} — cadastro principal
    unido ao complemento cirúrgico da base oficial da Receita Federal."""
    m = {}

    def poe(c, d):
        n = digitos(c)
        if d.get("razao_social") and n not in m:
            m[n] = {"nome": d["razao_social"],
                    "municipio": (d.get("municipio") or "").upper(),
                    "uf": d.get("uf") or "",
                    "sem_fins": d.get("sem_fins_lucrativos")}
    for d in carrega("destinatarios_2026.json")["destinatarios"]:
        poe(d["cnpj"], d)
    try:
        for c, d in carrega("cadastro_cnpj_complementar.json")["cadastros"].items():
            poe(c, d)
    except FileNotFoundError:
        pass
    return m


def nome_de(mapa, c):
    d = mapa.get(digitos(c))
    return d["nome"] if d else None


def classifica_valor(evento):
    """Rótulo do valor pela estação alcançada — com a trava do valor
    coletivo: página que lista muitas entidades e cita um único valor
    dominante não autoriza atribuição individual (foi assim que
    R$ 1.500.000,00 de uma deliberação apareceu 'para' 24 entidades)."""
    ests = set(evento.get("estacoes") or [])
    ncnpj = len(evento.get("cnpjs") or [])
    vs = evento.get("valores") or []
    if ncnpj > 3 and len([v for v in vs if v == max(vs)]) <= 2 and len(vs) < ncnpj:
        return "valor coletivo da página/deliberação — atribuição individual indevida"
    if ests & DESPESA:
        return "repasse publicado"
    if "empenho" in ests:
        return "empenho publicado"
    return "menção textual"


def valor_coletivo(evento) -> bool:
    return classifica_valor(evento).startswith("valor coletivo")


# ------------------------------------------------------ camadas visuais
def pizza_svg(itens, tot_rot="previsto"):
    tot = sum(v for _, v, _ in itens) or 1
    cx = cy = 150; R = 118
    ang = -math.pi / 2
    partes = []
    for rot, val, cor in itens:
        if val <= 0:
            continue
        a2 = ang + 2 * math.pi * val / tot
        gr = 1 if a2 - ang > math.pi else 0
        x1, y1 = cx + R * math.cos(ang), cy + R * math.sin(ang)
        x2, y2 = cx + R * math.cos(a2), cy + R * math.sin(a2)
        partes.append(
            f'<path d="M{cx},{cy} L{x1:.1f},{y1:.1f} A{R},{R} 0 {gr},1 '
            f'{x2:.1f},{y2:.1f} Z" fill="{cor}" stroke="#fff" '
            f'stroke-width="2"><title>{esc(rot)}: {fmt(val)} '
            f'({100*val/tot:.1f}% do previsto do mês)</title></path>')
        p = 100 * val / tot
        if p > 4.5:
            am = (ang + a2) / 2
            lx, ly = cx + R * .66 * math.cos(am), cy + R * .66 * math.sin(am)
            partes.append(f'<text x="{lx:.0f}" y="{ly:.0f}" text-anchor="middle" '
                          f'style="font:700 12px Arial;fill:#fff" '
                          f'pointer-events="none">{p:.0f}%</text>')
        ang = a2
    partes.append(
        f'<circle cx="{cx}" cy="{cy}" r="46" fill="#faf8f5"/>'
        f'<text x="{cx}" y="{cy-4}" text-anchor="middle" '
        f'style="font:11px Georgia;fill:#6b6660">{tot_rot}</text>'
        f'<text x="{cx}" y="{cy+14}" text-anchor="middle" '
        f'style="font:700 12px Arial">{fmt(tot)}</text>')
    return ('<svg viewBox="0 0 300 300" role="img">' + "".join(partes) + "</svg>")


def linha_exercicio_svg(trilha, comp):
    meses = [f"2026-{m:02d}" for m in range(1, 8)]
    evs = {m: [e for e in trilha["detalhe"]
               if str(e.get("data", "")).startswith(m)] for m in meses}
    serie_ev = [len(evs[m]) for m in meses]
    serie_emp = [sum(1 for e in evs[m] if "empenho" in (e.get("estacoes") or []))
                 for m in meses]
    serie_pag = [sum(1 for e in evs[m]
                     if DESPESA & set(e.get("estacoes") or [])) for m in meses]
    W, H, PAD = 860, 210, 42
    maxv = max(serie_ev + [1])

    def xy(i, v):
        return (PAD + i * (W - 2 * PAD) / (len(meses) - 1),
                H - PAD - v * (H - 2 * PAD) / maxv)

    def poli(serie, cor, largura, traco=""):
        pts = " ".join(f"{xy(i, v)[0]:.0f},{xy(i, v)[1]:.0f}"
                       for i, v in enumerate(serie))
        return (f'<polyline points="{pts}" fill="none" stroke="{cor}" '
                f'stroke-width="{largura}" {traco}/>')

    g = ['<svg viewBox="0 0 860 210" role="img">']
    for v in range(0, maxv + 1, max(1, maxv // 4)):
        _, y = xy(0, v)
        g.append(f'<line x1="{PAD}" y1="{y:.0f}" x2="{W-PAD}" y2="{y:.0f}" '
                 f'stroke="#e6e1d8"/><text x="{PAD-8}" y="{y+4:.0f}" '
                 f'text-anchor="end" style="font:11px Arial;fill:#6b6660">{v}</text>')
    idx = meses.index(comp)
    xm, _ = xy(idx, 0)
    g.append(f'<rect x="{xm-26:.0f}" y="{PAD-18}" width="52" '
             f'height="{H-2*PAD+18}" fill="#8c1d18" opacity=".07"/>')
    g.append(poli(serie_ev, "#3a5f8a", 3))
    g.append(poli(serie_emp, "#a85b00", 2, 'stroke-dasharray="5 4"'))
    g.append(poli(serie_pag, "#8c1d18", 2))
    for i, m in enumerate(meses):
        x, _ = xy(i, 0)
        peso = 700 if i == idx else 400
        g.append(f'<text x="{x:.0f}" y="{H-14}" text-anchor="middle" '
                 f'style="font:{peso} 12px Arial">{MESES_ROT[i]}</text>')
        xe, ye = xy(i, serie_ev[i])
        g.append(f'<circle cx="{xe:.0f}" cy="{ye:.0f}" r="{6 if i==idx else 4}" '
                 f'fill="#3a5f8a"><title>{MESES_ROT[i]}/2026 — '
                 f'{serie_ev[i]} eventos publicados, {serie_emp[i]} com '
                 f'empenho, {serie_pag[i]} com liquidação ou pagamento'
                 f'</title></circle>')
    g.append('</svg>')
    legenda = ('<p class="legenda"><i style="background:#3a5f8a"></i>eventos '
               'publicados na trilha<i style="background:#a85b00"></i>com '
               'estação de empenho<i style="background:#8c1d18"></i>com '
               'liquidação ou pagamento — a linha vermelha rente ao zero nos '
               'sete meses é o achado central do exercício</p>')
    tab = ('<table><tr><th>mês</th>' + "".join(f'<td class="num">{r}</td>'
           for r in MESES_ROT[:7]) + '</tr><tr><th>eventos</th>' +
           "".join(f'<td class="num">{v}</td>' for v in serie_ev) +
           '</tr><tr><th>empenhos</th>' +
           "".join(f'<td class="num">{v}</td>' for v in serie_emp) +
           '</tr><tr><th>liquid./pagto.</th>' +
           "".join(f'<td class="num">{v}</td>' for v in serie_pag) +
           '</tr></table>')
    return ("".join(g) + legenda +
            detalhes("Abrir dados completos da série", tab))


def _balao(x, y, r, cor, rot, val, tip, texto_cor="#fff"):
    linhas = rot.split("|")
    ty = y - 6 * (len(linhas) - 1)
    txt = "".join(f'<text x="{x}" y="{ty + i*14}" text-anchor="middle" '
                  f'style="font:700 12px Arial;fill:{texto_cor}" '
                  f'pointer-events="none">{esc(l)}</text>'
                  for i, l in enumerate(linhas))
    vtx = (f'<text x="{x}" y="{ty + len(linhas)*14 + 2}" text-anchor="middle" '
           f'style="font:11px Arial;fill:{texto_cor}" pointer-events="none">'
           f'{fmt(val)}</text>' if val is not None else "")
    return (f'<circle cx="{x}" cy="{y}" r="{r:.0f}" fill="{cor}" '
            f'stroke="#fff" stroke-width="3"><title>{esc(tip)}</title>'
            f'</circle>{txt}{vtx}')


def _seta(x1, y1, x2, y2, esp, cor, tip, tracejada=False):
    tr = ' stroke-dasharray="8 7"' if tracejada else ""
    ang = math.atan2(y2 - y1, x2 - x1)
    ax, ay = x2 - 14 * math.cos(ang), y2 - 14 * math.sin(ang)
    px1 = ax + 7 * math.cos(ang + math.pi / 2)
    py1 = ay + 7 * math.sin(ang + math.pi / 2)
    px2 = ax + 7 * math.cos(ang - math.pi / 2)
    py2 = ay + 7 * math.sin(ang - math.pi / 2)
    return (f'<g><title>{esc(tip)}</title>'
            f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{ax:.0f}" y2="{ay:.0f}" '
            f'stroke="{cor}" stroke-width="{esp:.0f}"{tr}/>'
            f'<polygon points="{x2:.0f},{y2:.0f} {px1:.0f},{py1:.0f} '
            f'{px2:.0f},{py2:.0f}" fill="{cor}"/></g>')


def _qd(cor, nome, valor, sub, tip, abre, central=False):
    return (f'<details class="qd{" central" if central else ""}" '
            f'style="--qc:{cor}"><summary data-tip="{esc(tip)}">'
            f'<span class="nm">{esc(nome)}</span>'
            f'<span class="vl">{fmt(valor) if valor is not None else ""}</span>'
            f'<span class="sub">{esc(sub)}</span></summary>'
            f'<div class="abre">{abre}</div></details>')


def _setas_svg(ys_origem, y_destino, larguras, cores, tips, invertido=False):
    H = max(max(ys_origem, default=0), y_destino) + 60
    g = [f'<svg viewBox="0 0 84 {H:.0f}" preserveAspectRatio="none" '
         f'style="height:{H:.0f}px">']
    for y, w, c, tp in zip(ys_origem, larguras, cores, tips):
        x1, x2 = (2, 74) if not invertido else (2, 74)
        y1, y2 = (y, y_destino) if not invertido else (y_destino, y)
        g.append(f'<g><title>{esc(tp)}</title>'
                 f'<path d="M{x1},{y1:.0f} C 40,{y1:.0f} 44,{y2:.0f} '
                 f'{x2},{y2:.0f}" fill="none" stroke="{c}" '
                 f'stroke-width="{w:.0f}" opacity=".85"/>'
                 f'<polygon points="82,{y2:.0f} 71,{y2-6:.0f} 71,{y2+6:.0f}" '
                 f'fill="{c}"/></g>')
    g.append('</svg>')
    return "".join(g)


def fluxograma_baloes(fluxo, evs_mes, mapa, comp):
    """Balões QUADRADOS em três colunas alinhadas — entrada, Fundo, saída.
    Cada quadrado: resumo no hover (data-tip) e dados completos no clique
    (o próprio quadrado abre). Setas com espessura proporcional ao valor."""
    fontes = sorted(fluxo["fontes"], key=lambda f: -f["valor"])[:6]
    fundo = next(c for c in fluxo["contas"] if c["unidade"] == "3650")
    saidas = sorted(fluxo["despesas"], key=lambda d: -d["valor"])[:6]
    maxf = max(f["valor"] for f in fontes)
    maxs = max((d["valor"] for d in saidas), default=1)
    ALT, GAP = 82, 10
    n = max(len(fontes), len(saidas))
    y_meio = (n * (ALT + GAP)) / 2

    col_f, ys_f, ws_f, cs_f, tp_f = [], [], [], [], []
    for i, f in enumerate(fontes):
        cor = COR_FONTE.get(f.get("fonte"), "#4a7c59")
        if f.get("status") != "comprovada":
            cor = "#8a8a94"
        tip = (f'{f["nome"]}: {fmt(f["valor"])} no exercício '
               f'({f.get("status", "?")}).')
        abre = (f'<b>Prova documental:</b> {esc(f.get("prova", "—"))}.<br>'
                f'<b>Ente:</b> {esc(f.get("ente", "—"))} · '
                f'<b>fonte orçamentária:</b> {esc(f.get("fonte", "—"))}.'
                + ('<br><b>Omissão legal:</b> fonte sem prova publicada — '
                   'Artigo 48-A da Lei Complementar 101/2000.'
                   if f.get("status") != "comprovada" else ""))
        col_f.append(_qd(cor, f["nome"].split("—")[0].strip(), f["valor"],
                         f'fonte {f.get("fonte", "?")} · '
                         f'{f.get("status", "?")}', tip, abre))
        ys_f.append(i * (ALT + GAP) + ALT / 2)
        ws_f.append(2 + 9 * f["valor"] / maxf)
        cs_f.append(cor)
        tp_f.append(f'entrada: {f["nome"]} → conta do Fundo — {fmt(f["valor"])}')

    abre_fundo = (f'{esc(fundo["nota"])}<br><b>O que falta:</b> '
                  f'{esc(fundo.get("falta", "—"))} — Artigo 30, inciso II, '
                  f'da Lei 8.742/1993.')
    card_fundo = _qd("#1d4f8a", "Conta especial do Fundo — un. 3650",
                     fundo["valor"], "onde o Conselho controla",
                     f'{fundo["nome"]}: {fmt(fundo["valor"])}. Clique para os '
                     f'dados completos.', abre_fundo, central=True)

    col_s, ys_s, ws_s, cs_s, tp_s = [], [], [], [], []
    for i, d in enumerate(saidas):
        nome = nome_de(mapa, d.get("cnpj", "")) or fmt_cnpj(d.get("cnpj", "?"))
        comprovada = d.get("tipo") == "comprovada"
        cor = "#1d4f2b" if comprovada else "#a85b00"
        tip = (f'saída: {nome} — {fmt(d["valor"])} em {d.get("data", "?")}. '
               f'Vínculo: {", ".join(d.get("vinculo") or ["nenhum publicado"])}.')
        abre = (f'<b>Inscrição:</b> {fmt_cnpj(d.get("cnpj", "?"))}<br>'
                f'<b>Vínculo publicado:</b> '
                f'{esc(", ".join(d.get("vinculo") or ["nenhum"]))}<br>'
                f'<b>Objeto:</b> {esc(d.get("objeto", "—"))}<br>'
                f'<b>Processo:</b> {esc(d.get("processo", "—"))}'
                + ('' if comprovada else '<br><b>Omissão legal:</b> despesa '
                   'sem instrumento de vínculo publicado — Artigo 61 da Lei '
                   '4.320/1964 e Artigo 38 da Lei 13.019/2014.'))
        col_s.append(_qd(cor, nome[:46], d["valor"],
                         "com vínculo" if comprovada else "sem vínculo "
                         "publicado", tip, abre))
        ys_s.append(i * (ALT + GAP) + ALT / 2)
        ws_s.append(2 + 9 * d["valor"] / maxs)
        cs_s.append(cor)
        tp_s.append(f'Fundo → {nome}: {fmt(d["valor"])}')

    setas1 = _setas_svg(ys_f, y_meio, ws_f, cs_f, tp_f)
    setas2 = _setas_svg([y_meio] * len(ys_s), 0, ws_s, cs_s, tp_s)
    # segunda coluna de setas: origem única no meio, destinos escalonados
    g2 = [f'<svg viewBox="0 0 84 {max(ys_s, default=60)+60:.0f}" '
          f'preserveAspectRatio="none" '
          f'style="height:{max(ys_s, default=60)+60:.0f}px">']
    for y, w, c, tp in zip(ys_s, ws_s, cs_s, tp_s):
        g2.append(f'<g><title>{esc(tp)}</title>'
                  f'<path d="M2,{y_meio:.0f} C 40,{y_meio:.0f} 44,{y:.0f} '
                  f'74,{y:.0f}" fill="none" stroke="{c}" '
                  f'stroke-width="{w:.0f}" opacity=".85"/>'
                  f'<polygon points="82,{y:.0f} 71,{y-6:.0f} 71,{y+6:.0f}" '
                  f'fill="{c}"/></g>')
    g2.append('</svg>')
    setas2 = "".join(g2)

    ev_desp = sum(1 for e in evs_mes if DESPESA & set(e.get("estacoes") or []))
    topo = ('<div class="colrot"><span>Entrada — fontes</span><span></span>'
            '<span>Passagem pelo Fundo</span><span></span>'
            '<span>Saída — destinatários</span></div>')
    grade = (f'<div class="fxg">{topo}'
             f'<div class="qds">{"".join(col_f)}</div>'
             f'<div class="setacol">{setas1}</div>'
             f'<div style="display:flex;align-items:center;'
             f'min-height:{n*(ALT+GAP):.0f}px">{card_fundo}</div>'
             f'<div class="setacol">{setas2}</div>'
             f'<div class="qds">{"".join(col_s)}</div></div>')
    aviso = (f'<p class="legenda">quadrados clicáveis; setas proporcionais '
             f'ao valor. No mês, {ev_desp} evento(s) alcançaram estação de '
             f'despesa. Despesa comprovada no exercício: '
             f'{fmt(fluxo["totais"]["despesa_comprovada"])} de um Fundo de '
             f'{fmt(fluxo["totais"]["fundo"])}.</p>')
    return grade + aviso


def fluxograma_duas_contas(fluxo):
    fundo = next(c for c in fluxo["contas"] if c["unidade"] == "3650")
    gab = next(c for c in fluxo["contas"] if c["unidade"] == "3601")
    tes = _qd("#8c1d18", "Tesouro Municipal", None, "origem dos recursos",
              "Fonte integral da unidade 3601 e de apenas R$ 9.000,00 do "
              "Fundo em 2026 (queda de 99,46%).",
              "<b>Para o Gabinete (3601):</b> " + fmt(gab["valor"]) +
              " — fora do Fundo.<br><b>Para o Fundo (3650):</b> R$ 9.000,00 "
              "no exercício.<br><b>Omissão legal:</b> a comprovação "
              "orçamentária de recursos próprios no Fundo é condição do "
              "repasse federal — Artigo 30, parágrafo único, da Lei "
              "8.742/1993.")
    g = _qd("#a85b00", "Gabinete da Secretaria — un. 3601", gab["valor"],
            "⅘ do dinheiro da pasta, fora do controle do Conselho",
            f'{gab["nome"]}: {fmt(gab["valor"])}, integralmente do Tesouro '
            f'e fora do Fundo.',
            esc(gab["nota"]) + "<br><b>Base:</b> " + esc(gab["base"]) +
            "<br><b>Omissão legal:</b> recursos da assistência social devem "
            "transitar pelo Fundo sob controle do Conselho — Artigo 30, "
            "incisos I e II, da Lei 8.742/1993.")
    f = _qd("#1d4f8a", "Conta especial do Fundo — un. 3650", fundo["valor"],
            "onde o Conselho controla (Artigo 30, inciso II, da Lei "
            "8.742/1993)",
            f'{fundo["nome"]}: {fmt(fundo["valor"])}.',
            esc(fundo["nota"]) + "<br><b>O que falta:</b> " +
            esc(fundo.get("falta", "—")))
    seta_gab = ('<svg viewBox="0 0 84 60" style="height:60px" '
                'preserveAspectRatio="none"><g><title>Tesouro → Gabinete '
                '(3601): ' + fmt(gab["valor"]) + ' correm FORA do Fundo</title>'
                '<line x1="2" y1="30" x2="70" y2="30" stroke="#8c1d18" '
                'stroke-width="12"/><polygon points="82,30 68,22 68,38" '
                'fill="#8c1d18"/></g></svg>')
    seta_fundo = ('<svg viewBox="0 0 84 60" style="height:60px" '
                  'preserveAspectRatio="none"><g><title>Tesouro → Fundo: '
                  'apenas R$ 9.000,00 em 2026</title>'
                  '<line x1="2" y1="30" x2="70" y2="30" stroke="#8c1d18" '
                  'stroke-width="2"/><polygon points="82,30 70,25 70,35" '
                  'fill="#8c1d18"/></g></svg>')
    seta_transf = ('<div style="text-align:center"><svg viewBox="0 0 60 96" '
                   'style="height:96px"><g><title>Transferência automática '
                   'ao Fundo — Artigo 2º, § 1º, da Lei municipal 7.531/1995 '
                   '— NÃO localizada em publicação alguma do exercício'
                   '</title><line x1="30" y1="4" x2="30" y2="78" '
                   'stroke="#c1281f" stroke-width="5" '
                   'stroke-dasharray="9 8"/><polygon points="30,92 22,78 '
                   '38,78" fill="#c1281f"/></g></svg>'
                   '<div style="font:700 12px Arial;color:#c1281f">'
                   'transferência automática (Artigo 2º, § 1º, da Lei '
                   '7.531/1995): não publicada ✕</div></div>')
    grade = (f'<div class="fxg"><div class="qds" style="align-self:center">'
             f'{tes}</div>'
             f'<div class="setacol" style="align-self:center">{seta_gab}'
             f'{seta_fundo}</div>'
             f'<div class="qds">{g}{seta_transf}{f}</div>'
             f'<div></div><div></div></div>')
    tab = (f'<table><tr><th>Conta</th><th>Unidade</th><th class="num">Valor '
           f'2026</th><th>Base legal</th><th>Situação</th></tr>'
           f'<tr><td>{esc(fundo["nome"])}</td><td>3650</td>'
           f'<td class="num">{fmt(fundo["valor"])}</td>'
           f'<td>{esc(fundo["base"])}</td><td>{esc(fundo["status"])}</td></tr>'
           f'<tr class="ruim"><td>{esc(gab["nome"])}</td><td>3601</td>'
           f'<td class="num">{fmt(gab["valor"])}</td>'
           f'<td>{esc(gab["base"])}</td><td>fora do Fundo</td></tr></table>')
    return (grade + '<p class="legenda">quadrados clicáveis; a seta '
            'tracejada vermelha é a transferência que a lei manda e não '
            'aparece publicada.</p>'
            + detalhes("Abrir dados completos das duas contas", tab))


def fluxograma_gabinete(fluxo):
    """Fluxograma próprio da conta do Gabinete da Secretaria (un. 3601):
    Tesouro → 3601 → destinações do QDD capturado, com a fatia ainda não
    extraída explicitada como lacuna, não como silêncio."""
    gab = next(c for c in fluxo["contas"] if c["unidade"] == "3601")
    try:
        qdd = carrega("qdd_2026.json")
    except FileNotFoundError:
        qdd = []
    acoes = {}
    for r in qdd:
        if str(r.get("unid", "")).startswith("3601"):
            a = acoes.setdefault(r["acao"], {"v": 0.0, "nome": r["nome"],
                                             "nats": {}})
            a["v"] += r["valor"]
            a["nats"][r.get("nat_fmt", "?")] = (
                a["nats"].get(r.get("nat_fmt", "?"), 0) + r["valor"])
    capturado = sum(a["v"] for a in acoes.values())
    resto = max(gab["valor"] - capturado, 0)
    tes = _qd("#8c1d18", "Tesouro Municipal", gab["valor"],
              "fonte integral da unidade 3601",
              f"Toda a unidade 3601 é custeada pelo Tesouro: "
              f"{fmt(gab['valor'])} na Lei Orçamentária 11.590/2026.",
              esc(gab["nota"]) + "<br><b>Omissão legal:</b> por força do "
              "Artigo 30, parágrafo único, da Lei 8.742/1993 e do Artigo 2º "
              "da Lei municipal 7.531/1995, recursos da assistência social "
              "devem transitar pelo Fundo sob controle do Conselho.")
    card_gab = _qd("#a85b00", "Gabinete da Secretaria — un. 3601",
                   gab["valor"], "execução FORA do Fundo",
                   f'{gab["nome"]}: {fmt(gab["valor"])}, sem passagem pela '
                   f'conta especial.',
                   esc(gab["base"]) + "<br><b>Análise:</b> nenhum "
                   "demonstrativo próprio da unidade foi publicado no "
                   "exercício; a prestação de contas desta conta é, até "
                   "aqui, integralmente omissa.", central=True)
    col_s, ys, ws, cs, tp = [], [], [], [], []
    ordenadas = sorted(acoes.items(), key=lambda kv: -kv[1]["v"])[:5]
    maxv = max([a["v"] for _, a in ordenadas] + [resto, 1])
    ALT, GAP = 82, 10
    for i, (cod, a) in enumerate(ordenadas):
        nats = ", ".join(f"{k} ({fmt(v)})" for k, v in
                         sorted(a["nats"].items(), key=lambda x: -x[1]))
        pessoal = a["nats"].get("3.1.90.11", 0)
        obs = ("<br><b>Atenção:</b> despesa de pessoal — soma para o teto "
               "de 30% do Artigo 4º da Lei Complementar municipal 273/2014."
               if pessoal else "")
        col_s.append(_qd("#5c5c00" if pessoal else "#3a5f8a",
                         a["nome"].title()[:46], a["v"],
                         f"ação {cod.split('.')[-1]}",
                         f'{a["nome"].title()}: {fmt(a["v"])} '
                         f'({100*a["v"]/gab["valor"]:.1f}% da unidade).',
                         f"<b>Ação:</b> {cod}<br><b>Naturezas:</b> {nats}"
                         + obs))
        ys.append(i * (ALT + GAP) + ALT / 2)
        ws.append(2 + 9 * a["v"] / maxv)
        cs.append("#5c5c00" if pessoal else "#3a5f8a")
        tp.append(f'3601 → {a["nome"].title()}: {fmt(a["v"])}')
    if resto > 0:
        i = len(col_s)
        col_s.append(_qd("#8a8a94", "Linhas do QDD ainda não capturadas",
                         resto, "lacuna de extração — não é conformidade",
                         f"{fmt(resto)} da unidade 3601 ainda sem detalhe "
                         f"capturado do Quadro de Detalhamento da Despesa.",
                         "A extração do QDD publicado alcançou "
                         f"{fmt(capturado)} de {fmt(gab['valor'])} "
                         f"({100*capturado/gab['valor']:.0f}%). Dado "
                         "faltante é achado: completar a captura é "
                         "providência, e o detalhamento integral é "
                         "exigível — Artigo 48-A, inciso I, da Lei "
                         "Complementar 101/2000."))
        ys.append(i * (ALT + GAP) + ALT / 2)
        ws.append(2 + 9 * resto / maxv)
        cs.append("#8a8a94")
        tp.append(f'3601 → linhas não capturadas: {fmt(resto)}')
    y_meio = (len(col_s) * (ALT + GAP)) / 2
    g1 = (f'<svg viewBox="0 0 84 {max(y_meio*2,120):.0f}" '
          f'preserveAspectRatio="none" style="height:'
          f'{max(y_meio*2,120):.0f}px"><g><title>Tesouro → 3601: '
          f'{fmt(gab["valor"])}</title>'
          f'<line x1="2" y1="{y_meio:.0f}" x2="70" y2="{y_meio:.0f}" '
          f'stroke="#8c1d18" stroke-width="12"/>'
          f'<polygon points="82,{y_meio:.0f} 68,{y_meio-8:.0f} '
          f'68,{y_meio+8:.0f}" fill="#8c1d18"/></g></svg>')
    g2 = [f'<svg viewBox="0 0 84 {len(col_s)*(ALT+GAP):.0f}" '
          f'preserveAspectRatio="none" '
          f'style="height:{len(col_s)*(ALT+GAP):.0f}px">']
    for y, w, c, tpp in zip(ys, ws, cs, tp):
        g2.append(f'<g><title>{esc(tpp)}</title>'
                  f'<path d="M2,{y_meio:.0f} C 40,{y_meio:.0f} 44,{y:.0f} '
                  f'74,{y:.0f}" fill="none" stroke="{c}" '
                  f'stroke-width="{w:.0f}" opacity=".85"/>'
                  f'<polygon points="82,{y:.0f} 71,{y-6:.0f} 71,{y+6:.0f}" '
                  f'fill="{c}"/></g>')
    g2.append('</svg>')
    topo = ('<div class="colrot"><span>Origem</span><span></span>'
            '<span>Conta do Gabinete</span><span></span>'
            '<span>Destinações do QDD</span></div>')
    grade = (f'<div class="fxg">{topo}'
             f'<div class="qds" style="align-self:center">{tes}</div>'
             f'<div class="setacol" style="align-self:center">{g1}</div>'
             f'<div style="display:flex;align-items:center;min-height:'
             f'{len(col_s)*(ALT+GAP):.0f}px">{card_gab}</div>'
             f'<div class="setacol">{"".join(g2)}</div>'
             f'<div class="qds">{"".join(col_s)}</div></div>')
    pess = sum(a["nats"].get("3.1.90.11", 0) for a in acoes.values())
    aviso = (f'<p class="legenda">Do QDD capturado da unidade, '
             f'{fmt(pess)} ({100*pess/max(capturado,1):.1f}%) é folha de '
             f'pagamento — natureza 3.1.90.11 — a cruzar com o teto de 30% '
             f'do Artigo 4º da Lei Complementar municipal 273/2014.</p>')
    return grade + aviso


def prestacao_gabinete(comp, evs, nome_mes):
    """Prestação de contas mensal da conta 3601 — análise individual."""
    dots = [e for e in evs if e.get("dotacao")]
    linhas = []
    for e in dots:
        linhas.append(f'<span class="li"><b class="k">{e.get("data")}</b>'
                      f'dotação funcional {esc(str(e.get("dotacao")))} — '
                      f'edição {esc(e.get("edicao", "—"))}</span>')
    corpo_dot = ("".join(linhas) if linhas else
                 '<span class="li">nenhuma dotação citada em evento do mês'
                 '</span>')
    return (f'<div class="estrutural">'
            f'<p><b>Demonstrativo próprio da unidade 3601 em {nome_mes}:</b> '
            f'não publicado — a prestação de contas mensal desta conta é '
            f'integralmente omissa (Artigo 48-A, inciso I, da Lei '
            f'Complementar 101/2000). Selo: '
            f'INCONCLUSIVO_POR_DOCUMENTO_FALTANTE.</p>'
            f'<p style="margin-top:8px"><b>Opacidade que impede separar as '
            f'contas:</b> as dotações publicadas no Diário vêm no formato '
            f'funcional-programático (ex.: 08.244.0108.2263), sem o código '
            f'da unidade orçamentária — pelo Diário é impossível atribuir '
            f'cada despesa à conta 3650 ou 3601. A separação exige o QDD '
            f'integral ou o portal da transparência (pendência P2). '
            f'Dotações citadas no mês:</p><div class="ev" style="--pt:#a85b00">'
            f'{corpo_dot}</div></div>')


NAT_NOME = {
    "3.1.90.11": "Vencimentos e vantagens fixas — pessoal civil",
    "3.1.90.13": "Obrigações patronais",
    "3.1.90.92": "Despesas de exercícios anteriores — pessoal",
    "3.1.90.96": "Ressarcimento de pessoal requisitado",
    "3.3.90.14": "Diárias — civil",
    "3.3.90.30": "Material de consumo",
    "3.3.90.32": "Material, bem ou serviço para distribuição gratuita",
    "3.3.90.39": "Outros serviços de terceiros — pessoa jurídica",
    "3.3.50.41": "Contribuições a entidades privadas sem fins lucrativos",
    "4.4.90.52": "Equipamentos e material permanente",
}


def prestacao_gabinete_completa(comp, evs, nome_mes, fluxo):
    """Prestação de contas da conta 3601 no mesmo padrão da Parte I:
    cada destinação do QDD pormenorizada em linha própria, com semáforo —
    ROXO quando não existe informação publicada sobre a execução."""
    gab = next(c for c in fluxo["contas"] if c["unidade"] == "3601")
    try:
        qdd = carrega("qdd_2026.json")
    except FileNotFoundError:
        qdd = []
    acoes = {}
    for r in qdd:
        if str(r.get("unid", "")).startswith("3601"):
            a = acoes.setdefault(r["acao"], {"v": 0.0, "nome": r["nome"],
                                             "nats": {}, "fontes": set()})
            a["v"] += r["valor"]
            a["nats"][r.get("nat_fmt", "?")] = (
                a["nats"].get(r.get("nat_fmt", "?"), 0) + r["valor"])
            a["fontes"].add(str(r.get("fonte", "?")))
    capturado = sum(a["v"] for a in acoes.values())
    resto = max(gab["valor"] - capturado, 0)

    def linha(titulo, sub, oq, sem, tip, det):
        return (f'<details class="plin"><summary>'
                f'<span class="quem"><b>{esc(titulo)}</b>{esc(sub)}</span>'
                f'<span class="oq">{oq}</span>'
                f'<span class="sem {sem}" data-tip="{esc(tip)}"></span>'
                f'</summary><div class="det">{det}</div></details>')

    linhas = []
    for cod, a in sorted(acoes.items(), key=lambda kv: -kv[1]["v"]):
        nats = "".join(
            f'<span class="li"><b class="k">{k}</b>'
            f'{NAT_NOME.get(k[:9], "natureza da despesa")} — {fmt(v)}</span>'
            for k, v in sorted(a["nats"].items(), key=lambda x: -x[1]))
        pess = a["nats"].get("3.1.90.11", 0)
        alerta = ("<br><b>Atenção — pessoal:</b> esta destinação soma para o "
                  "teto de 30% do Artigo 4º da Lei Complementar municipal "
                  "273/2014, hoje inaferível pela invisibilidade da folha "
                  "(achado PES-01/PES-02)." if pess else "")
        tip = (f"SEM INFORMAÇÃO PUBLICADA: dotação de {fmt(a['v'])} e nenhum "
               "empenho, liquidação ou pagamento identificável desta ação em "
               "edição alguma do exercício — a dotação publicada no Diário "
               "não carrega o código da unidade.")
        det = (f'<b>Ação:</b> {cod} · <b>fontes:</b> '
               f'{", ".join(sorted(a["fontes"]))}<br>'
               f'<b>Detalhamento por natureza (QDD):</b>'
               f'<div class="ev" style="--pt:#6b3fa0">{nats}</div>'
               f'<b>Execução publicada em {nome_mes}:</b> nenhuma '
               f'identificável.<br><b>O que falta e onde obter:</b> empenhos '
               f'a débito da dotação {cod}, notas de liquidação e ordens de '
               f'pagamento — Artigo 61, Artigo 63 e Artigo 64 da Lei '
               f'4.320/1964; Artigo 48-A, inciso I, da Lei Complementar '
               f'101/2000. Fonte: QDD integral ou portal da transparência '
               f'(pendência P2).{alerta}')
        linhas.append(linha(a["nome"].title(), f"ação {cod}",
                            f'<b>{fmt(a["v"])}</b>dotado no QDD',
                            "roxo", tip, det))
    if resto > 0:
        linhas.append(linha(
            "Linhas do QDD ainda não capturadas",
            f"{100*resto/gab['valor']:.0f}% da unidade",
            f'<b>{fmt(resto)}</b>sem detalhamento capturado', "roxo",
            "SEM INFORMAÇÃO PUBLICADA/CAPTURADA: parcela da unidade cujo "
            "detalhamento do QDD ainda não foi extraído — lacuna de captura, "
            "não conformidade.",
            "Extração do QDD alcançou " + fmt(capturado) + " de "
            + fmt(gab["valor"]) + ". Dado faltante é achado: o detalhamento "
            "integral é exigível — Artigo 48-A, inciso I, da Lei "
            "Complementar 101/2000."))
    cab = ('<p class="explica">Cada destinação do Quadro de Detalhamento da '
           'Despesa da unidade 3601, pormenorizada: passe o mouse no símbolo '
           'para o estado da informação; clique na linha para naturezas, '
           'fontes e o que falta. O símbolo ROXO marca ausência de '
           'informação publicada.</p>'
           '<p class="legenda"><span class="sem roxo" style="display:inline-'
           'block;vertical-align:-3px"></span> sem informação publicada '
           '— nenhuma execução identificável da destinação</p>')
    return cab + '<div class="presta">' + "".join(linhas) + '</div>'


def folha_gabinete_resumo(nome_mes):
    """Resumo dirigido da folha do Gabinete: só o que interessa ao rigor —
    adicionais, horas extras e pagamentos acima do teto municipal. Como a
    folha é invisível (nenhuma linha 3.1.90.11 publicada, achado PES-01),
    as três categorias saem em ROXO com a norma e o documento necessário."""
    try:
        fin = carrega("financeiro.json")
        g31 = {k: v for k, v in fin.get("por_natureza", {}).items()
               if k.startswith("319")}
    except FileNotFoundError:
        g31 = {}
    cats = [
        ("Adicionais e gratificações",
         "adicionais noturno, de insalubridade, de periculosidade e "
         "gratificações de qualquer espécie",
         "folha analítica por competência com rubricas — Artigo 48-A, "
         "inciso I, da Lei Complementar 101/2000; Artigo 8º, § 1º, "
         "inciso III, da Lei 12.527/2011"),
        ("Horas extras — serviço extraordinário",
         "quantidade e valor de horas extraordinárias por servidor "
         "(primeiro nome apenas, minimizado na extração)",
         "folha analítica e atos de autorização do serviço extraordinário — "
         "Artigo 48-A, inciso I, da Lei Complementar 101/2000"),
        ("Pagamentos acima do teto municipal",
         "remunerações que excedam o subsídio do Prefeito, teto no "
         "Município",
         "Artigo 37, inciso XI, da Constituição da República; conferência "
         "exige a folha nominal com totais por servidor"),
    ]
    cards = []
    for tit, escopo, norma in cats:
        cards.append(
            f'<details class="plin"><summary>'
            f'<span class="quem"><b>{tit}</b>{escopo}</span>'
            f'<span class="oq"><b>—</b>sem informação publicada</span>'
            f'<span class="sem roxo" data-tip="SEM INFORMAÇÃO PUBLICADA: '
            f'a folha da unidade não consta de nenhuma edição do exercício '
            f'(achado PES-01) — impossível confirmar ou afastar."></span>'
            f'</summary><div class="det"><b>O que seria conferido:</b> '
            f'{escopo}.<br><b>Documento necessário e fundamento:</b> '
            f'{norma}.</div></details>')
    sobras = "".join(
        f'<span class="li"><b class="k">{k[:1]}.{k[1]}.{k[2:4]}.{k[4:6]}</b>'
        f'{NAT_NOME.get(f"{k[:1]}.{k[1]}.{k[2:4]}.{k[4:6]}", "rubrica do grupo de pessoal")} — '
        f'{fmt(v["valor"])} em {v["linhas"]} linha(s)</span>'
        for k, v in sorted(g31.items(), key=lambda x: -x[1]["valor"]))
    nota = (f'<div class="estrutural" style="margin-top:10px"><b>O que o '
            f'grupo de pessoal efetivamente publicou no exercício '
            f'(nenhuma é a folha):</b><div class="ev" style="--pt:#6b3fa0">'
            f'{sobras or "<span class=li>nada do grupo 31 publicado</span>"}'
            f'</div>Dotação de folha do Gabinete no QDD: R$ 48.204.000 '
            f'(3.1.90.11) — publicada como previsão, jamais como execução. '
            f'A vedação de custear pessoal efetivo e gratificações com '
            f'recurso do IGD do controle social (Artigo 12-A, § 4º, da Lei '
            f'8.742/1993) também fica inaferível sem a folha por fonte '
            f'(achado PES-07).</div>')
    return ('<p class="explica">Resumo dirigido: apenas as informações de '
            'salário que interessam ao controle — adicionais, horas extras '
            'e pagamentos acima do teto municipal. Tudo em ROXO porque a '
            'folha é invisível no acervo.</p>'
            '<div class="presta">' + "".join(cards) + '</div>' + nota)


def fluxo_estacoes_svg(previsto_total, est):
    ordem = [("dotacao", "Dotação"), ("empenho", "Empenho"),
             ("liquidacao", "Liquidação"), ("pagamento", "Pagamento")]
    maxn = max([est.get(k, 0) for k, _ in ordem] + [1])
    W = 860
    g = [f'<svg viewBox="0 0 {W} 190" role="img">']
    g.append(f'<rect x="10" y="60" width="150" height="70" rx="8" fill="#3a5f8a">'
             f'<title>previsão de entrada da competência: {fmt(previsto_total)}'
             f'</title></rect>'
             f'<text x="85" y="88" text-anchor="middle" '
             f'style="font:700 13px Arial;fill:#fff">Fundo Municipal</text>'
             f'<text x="85" y="108" text-anchor="middle" '
             f'style="font:12px Arial;fill:#fff">{fmt(previsto_total)}/mês</text>')
    x0 = 160
    for i, (k, rot) in enumerate(ordem):
        n = est.get(k, 0)
        x1 = 205 + i * 165
        cor = COR_EST["empenho"] if k == "empenho" else (
            "#1d4f2b" if n else "#8c1d18")
        esp = 2 + 10 * n / maxn
        tr = '' if n else ' stroke-dasharray="7 6"'
        g.append(f'<g><title>{rot}: {n} evento(s) publicado(s) no mês</title>'
                 f'<line x1="{x0}" y1="95" x2="{x1}" y2="95" stroke="{cor}" '
                 f'stroke-width="{esp:.0f}"{tr}/>'
                 f'<polygon points="{x1},95 {x1-11},89 {x1-11},101" '
                 f'fill="{cor}"/></g>')
        boxc = "#fff" if n else "#faf1f0"
        borda = "#d8d2c8" if n else "#8c1d18"
        g.append(f'<rect x="{x1}" y="60" width="130" height="70" rx="8" '
                 f'fill="{boxc}" stroke="{borda}" stroke-width="2">'
                 f'<title>{rot} — Artigo 6{"2" if k=="dotacao" else "3" if k=="liquidacao" else "4" if k=="pagamento" else "0"}'
                 f' da Lei 4.320/1964</title></rect>'
                 f'<text x="{x1+65}" y="88" text-anchor="middle" '
                 f'style="font:700 13px Arial">{rot}</text>'
                 f'<text x="{x1+65}" y="110" text-anchor="middle" '
                 f'style="font:700 17px Arial;fill:'
                 f'{"#1c1b1f" if n else "#8c1d18"}">{n}</text>')
        if not n:
            g.append(f'<text x="{x1+65}" y="150" text-anchor="middle" '
                     f'style="font:700 11px Arial;fill:#8c1d18">✕ nada '
                     f'publicado</text>')
        x0 = x1 + 130
    g.append('</svg>')
    aviso = ""
    if est.get("empenho", 0) > 0 and est.get("liquidacao", 0) == 0:
        aviso = ('<p class="legenda" style="color:#8c1d18;font-weight:700">'
                 '⚠ A trilha se interrompe entre o empenho e a liquidação: '
                 'dotação e empenho não comprovam saída de dinheiro — Artigo '
                 '62, Artigo 63 e Artigo 64 da Lei 4.320/1964.</p>')
    elif sum(est.get(k, 0) for k, _ in ordem) == 0:
        aviso = ('<p class="legenda" style="color:#8c1d18;font-weight:700">'
                 '⚠ Nenhuma das quatro estações legais da despesa teve '
                 'publicação no mês.</p>')
    return "".join(g) + aviso


def calendario_html(comp, dados_pub):
    ano, mes = int(comp[:4]), int(comp[5:7])
    d = date(ano, mes, 1)
    dias_sem = set(dados_pub.get("dias_uteis_sem_edicao", []))
    celulas = []
    while d.month == mes:
        iso = d.isoformat()
        cls = "fds" if d.weekday() >= 5 else ("nao" if iso in dias_sem else "pub")
        tip = {"fds": "fim de semana ou feriado",
               "nao": "dia útil sem edição localizada",
               "pub": "edição do Diário localizada"}[cls]
        celulas.append(f'<span class="dia {cls}" data-tip="{iso} — {tip}">'
                       f'{d.day}</span>')
        d += timedelta(days=1)
    lista = ("Dias úteis sem edição: " + ", ".join(sorted(dias_sem))
             if dias_sem else "Todos os dias úteis com edição localizada.")
    return ('<div class="calendario">' + "".join(celulas) + "</div>"
            '<p class="legenda">cada quadrado é um dia do mês —'
            '<i style="background:#1d4f2b"></i>edição localizada'
            '<i style="background:#8c1d18"></i>dia útil sem edição'
            '<i style="background:#e6e1d8"></i>fim de semana ou feriado</p>'
            + detalhes("Abrir dados completos da circulação", f"<p>{lista}</p>"))


ENTRADA_EST = {"repasse", "orcamento", "credito", "deliberacao"}
ETAPAS_SAIDA = [("empenho", "1ª etapa — Empenho (Artigo 58 e Artigo 60 da "
                 "Lei 4.320/1964)"),
                ("liquidacao", "2ª etapa — Liquidação (Artigo 63 da Lei "
                 "4.320/1964)"),
                ("pagamento", "3ª etapa — Pagamento (Artigo 64 da Lei "
                 "4.320/1964)")]


def _ev_linhas(e, mapa):
    ests = e.get("estacoes") or []
    chips = "".join(
        f'<span class="chip" style="background:{COR_EST.get(s, "#8a8a94")}" '
        f'data-tip="estação {s}">{s}</span>' for s in ests)
    val = max(e.get("valores") or [0])
    rotv = classifica_valor(e)
    url = e.get("url")
    ed = e.get("edicao", "—")
    linhas = [
        f'<span class="li"><b class="k">Data</b>{e.get("data", "—")}</span>',
        f'<span class="li"><b class="k">Edição do Diário</b>'
        f'{f"<a href=\'{url}\'>{ed}</a>" if url else ed} · página '
        f'{e.get("pagina", "—")}</span>',
        f'<span class="li"><b class="k">Estações</b>{chips}</span>',
    ]
    if val:
        linhas.append(f'<span class="li"><b class="k">Valor</b>{fmt(val)} — '
                      f'<i>{rotv}</i></span>')
    pareceres = []
    for c in e.get("cnpjs") or []:
        d = mapa.get(digitos(c))
        nome = d["nome"] if d else None
        rot = (f"{fmt_cnpj(c)} — {nome}" if nome
               else f"{fmt_cnpj(c)} (cadastro em busca na base da Receita)")
        extra = ""
        if d and d["municipio"] and d["municipio"] != "GOIANIA":
            if (nome or "").upper().startswith("MUNICIPIO DE"):
                extra = " ⚠ ente público de outro município"
                pareceres.append(
                    f'<div class="parecer-mini"><b>Parecer sobre a saída '
                    f'para {esc(nome.title())}:</b> valor do Fundo de '
                    f'Goiânia associado a outro ente federado. '
                    f'Transferência a outro Município é transferência '
                    f'voluntária e exige convênio ou instrumento congênere '
                    f'com publicação — Artigo 25 da Lei Complementar '
                    f'101/2000 e Artigo 62 da Lei 4.320/1964. Nenhuma '
                    f'justificativa ou convênio foi localizado nas edições '
                    f'do exercício. Selo: INDICIÁRIO — a menção é de uma '
                    f'via; o instrumento, se existir, não está publicado.'
                    f'</div>')
            else:
                extra = (f" · sede em {d['municipio'].title()}/{d['uf']} — "
                         f"aquisição de fornecedor de fora, não repasse "
                         f"fundo a fundo")
        linhas.append(f'<span class="li"><b class="k">Pessoa jurídica</b>'
                      f'{rot}{extra}</span>')
    cor = COR_EST.get(ests[0], "#8a8a94") if ests else "#8a8a94"
    return (f'<div class="ev" style="--pt:{cor}">' + "".join(linhas)
            + "".join(pareceres) + '</div>')


def cronologia_html(evs, mapa):
    if not evs:
        return ('<p class="explica">Nenhum evento publicado na competência — '
                'a ausência é, ela própria, o achado EXE-M do mês.</p>')
    evs = sorted(evs, key=lambda x: (x.get("data", ""), x.get("pagina", 0)))
    entradas = [e for e in evs
                if set(e.get("estacoes") or []) & ENTRADA_EST
                and not set(e.get("estacoes") or []) & DESPESA
                and "empenho" not in (e.get("estacoes") or [])]
    saidas = [e for e in evs if e not in entradas]
    partes = ['<p class="explica">Cada evento em ficha própria, uma '
              'informação por linha, em ordem cronológica dentro de cada '
              'bloco. Entradas e saídas separadas; a saída distingue as '
              'três etapas legais da despesa pela data de cada uma.</p>']
    partes.append('<div class="cr-bloco" style="--bc:#1d6f42">▼ ENTRADAS — '
                  'recursos chegando (repasses, orçamento e créditos)</div>')
    if entradas:
        partes.append('<div class="crono">' +
                      "".join(_ev_linhas(e, mapa) for e in entradas) +
                      '</div>')
    else:
        partes.append('<p class="explica">Nenhuma entrada publicada no mês '
                      '— a receita realizada segue sem demonstrativo '
                      '(achado REC-M).</p>')
    partes.append('<div class="cr-bloco" style="--bc:#8c1d18">▲ SAÍDAS — '
                  'despesa e vinculações</div>')
    usados = set()
    for est, rotulo in ETAPAS_SAIDA:
        bloco = [e for e in saidas if est in (e.get("estacoes") or [])]
        if bloco:
            partes.append(f'<div class="cr-etapa">{rotulo}</div>'
                          '<div class="crono">' +
                          "".join(_ev_linhas(e, mapa) for e in bloco) +
                          '</div>')
        else:
            partes.append(f'<div class="cr-etapa">{rotulo} — <b style='
                          f'"color:#8c1d18">nenhum evento no mês ✕</b></div>')
        usados |= {id(e) for e in bloco}
    resto = [e for e in saidas if id(e) not in usados]
    if resto:
        partes.append('<div class="cr-etapa">Atos preparatórios, dotações e '
                      'vinculações (não comprovam saída de dinheiro)</div>'
                      '<div class="crono">' +
                      "".join(_ev_linhas(e, mapa) for e in resto) + '</div>')
    return "".join(partes)


def _origens(n, mapa, vinculos, coletivo_igual):
    """Origem do recurso da entidade: emenda parlamentar (anexo da LOA),
    instrumento da Lei 13.019/2014 ou deliberação coletiva do Conselho."""
    tags, det = [], []
    try:
        em = carrega("entidades_emendas_2026.json")
    except FileNotFoundError:
        em = {}
    nome = (mapa.get(n) or {}).get("nome", "")
    import unicodedata
    def nrm(s):
        s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
        return re.sub(r"[^A-Z0-9 ]", " ", s.upper()).strip()
    for chave, info in em.items():
        if chave == "NAO_IDENTIFICADA" or len(nrm(chave)) < 10:
            continue
        a, b = nrm(chave), nrm(nome)
        if a and b and (b.startswith(a[:14]) or a[:14] in b or b[:14] in a):
            tags.append('<span class="orig">EMENDA PARLAMENTAR</span>')
            det.append(f"Emenda(s) parlamentar(es) na Lei Orçamentária: "
                       f"{fmt(info['valor'])}, indicação de "
                       f"{', '.join(info.get('vereadores', ['?']))}. Pela "
                       f"origem em emenda, o chamamento público é "
                       f"dispensável (Artigo 29 da Lei 13.019/2014), mas "
                       f"termo, plano de trabalho e prestação de contas "
                       f"continuam obrigatórios.")
            break
    v = vinculos.get(n)
    if v:
        instr = ", ".join(v.get("vinculo") or [])
        up = instr.upper()
        tipo = ("TERMO DE FOMENTO (Artigo 17 da Lei 13.019/2014)"
                if "FOMENTO" in up else
                "TERMO DE COLABORAÇÃO (Artigo 16 da Lei 13.019/2014)"
                if "COLABORA" in up else
                "ACORDO/TERMO DE COOPERAÇÃO (Artigo 2º, inciso VIII-A, da "
                "Lei 13.019/2014)" if "COOPERA" in up else
                "CONTRATO ADMINISTRATIVO (Lei 14.133/2021)"
                if "CONTRATO" in up else "INSTRUMENTO NÃO CLASSIFICADO")
        tags.append(f'<span class="orig">{tipo.split(" (")[0]}</span>')
        det.append(f"Instrumento publicado: {instr} — regime: {tipo}.")
    if n in coletivo_igual:
        tags.append('<span class="orig">DELIBERAÇÃO COLETIVA CMAS</span>')
        det.append("Consta da lista de 24 entidades da edição de 12/05/2026 "
                   "associada ao valor coletivo de R$ 1.500.000,00 (e à "
                   "deliberação de 04/11/2025). O valor é da deliberação, "
                   "não repasse individual comprovado: rateado em partes "
                   "iguais seriam R$ 62.500,00 por entidade, MAS nenhum "
                   "critério de rateio foi publicado — o repasse individual "
                   "permanece não demonstrado.")
    if not tags:
        tags.append('<span class="orig" style="background:#fdf1e7;'
                    'color:#a85b00">ORIGEM NÃO PUBLICADA</span>')
        det.append("Nenhuma origem localizada: nem emenda, nem instrumento "
                   "da Lei 13.019/2014, nem deliberação — omissão que "
                   "impede qualquer verificação de regularidade.")
    checagem = ("<b>Checagem Lei 13.019/2014:</b> chamamento público — não "
                "localizado; plano de trabalho (Artigo 22) — não localizado; "
                "prestação de contas (Artigo 63 e seguintes) — não "
                "localizada. Cumprimento INAFERÍVEL por documento faltante.")
    return "".join(tags), "<br>".join(det) + "<br>" + checagem


def prestacao_por_entidade(comp, evs, fluxo, mapa):
    vinculos = {digitos(d.get("cnpj", "")): d for d in fluxo["despesas"]}
    trilha_toda = carrega("trilha_dinheiro.json")["detalhe"]
    exercicio = set(vinculos) | {digitos(c) for e in trilha_toda
                                 for c in (e.get("cnpjs") or [])}
    coletivo_igual = set()
    for e in trilha_toda:
        if valor_coletivo(e):
            coletivo_igual |= {digitos(c) for c in (e.get("cnpjs") or [])}
    coletivos_mes = [e for e in evs if valor_coletivo(e)]
    no_mes = {}
    for e in evs:
        ests = set(e.get("estacoes") or [])
        val = max(e.get("valores") or [0])
        if valor_coletivo(e):
            continue  # tratado em linha única consolidada, sem repetição
        for c in e.get("cnpjs") or []:
            n = digitos(c)
            r = no_mes.setdefault(n, {"despesa": False, "mencao": 0,
                                      "valor": 0.0, "coletivo": False,
                                      "edicoes": set()})
            r["mencao"] += 1
            r["edicoes"].add(e.get("edicao", "?"))
            if ests & DESPESA:
                r["despesa"] = True
                r["valor"] = max(r["valor"], val)
            elif not r["despesa"]:
                r["valor"] = max(r["valor"], val)

    _av = alertas_vinculo()["alertas"]
    _al_por_cnpj = {}
    for a in _av:
        for c in ([a.get("cnpj")] if a.get("cnpj") else a.get("empresas", [])):
            _al_por_cnpj.setdefault(digitos(c or ""), []).append(a)

    def linha(n, sem, tip, oq, det):
        d = mapa.get(n)
        nome = d["nome"] if d else ("razão social pendente — reconsulta "
                                    "automática na base da Receita em curso")
        tags, origem_det = _origens(n, mapa, vinculos, coletivo_igual)
        return (f'<details class="plin"><summary>'
                f'<span class="quem"><b>{esc(nome)}</b>{fmt_cnpj(n)}<br>'
                f'{tags}</span>'
                f'<span class="oq">{oq}</span>'
                f'<span class="sem {sem}" data-tip="{esc(tip)}"></span>'
                f'</summary><div class="det"><b>Causa do valor:</b> {det}'
                f'<br><br><b>Origem do recurso:</b><br>{origem_det}'
                f'</div></details>')

    ordem = {"vermelho": 0, "laranja": 1, "azul": 2, "verde": 3}
    itens = []
    for n, r in no_mes.items():
        v = vinculos.get(n)
        if r["despesa"] and v:
            sem = "verde"
            tip = ("VERIFICADO POR DUAS VIAS: (1ª) estação de despesa no "
                   f"Diário — edições {', '.join(sorted(r['edicoes']))}; "
                   f"(2ª) instrumento publicado — "
                   f"{', '.join(v.get('vinculo') or ['?'])}")
            oq = f'<b>{fmt(v["valor"])}</b>repasse com vínculo'
            det = (f"repasse de {fmt(v['valor'])} em {v.get('data')}, "
                   f"objeto {esc(v.get('objeto', '—'))}, processo "
                   f"{esc(v.get('processo', '—'))}; confirmado pelas duas "
                   f"vias do selo.")
        elif r["despesa"]:
            sem = "azul"
            tip = ("VERIFICADO POR UMA VIA: estação de despesa no Diário — "
                   f"edições {', '.join(sorted(r['edicoes']))}. Instrumento "
                   "de vínculo não localizado; portal da transparência "
                   "indisponível (pendência P2).")
            oq = f'<b>{fmt(r["valor"])}</b>repasse publicado, sem vínculo'
            det = (f"repasse publicado de {fmt(r['valor'])} sem contrato, "
                   "convênio ou termo localizado.")
        elif v:
            sem = "azul"
            tip = ("VERIFICADO POR UMA VIA: instrumento publicado "
                   f"({', '.join(v.get('vinculo') or ['?'])}); no mês, só "
                   "menção — nenhuma estação de despesa.")
            oq = f'<b>{fmt(r["valor"])}</b>menção; vínculo do exercício'
            det = (f"vínculo do exercício {esc(', '.join(v.get('vinculo') or []))} "
                   f"({fmt(v['valor'])}); no mês, apenas {r['mencao']} "
                   f"menção(ões).")
        else:
            sem = "laranja"
            tip = (f"APENAS MENÇÃO: {r['mencao']} evento(s) — edições "
                   f"{', '.join(sorted(r['edicoes']))} — sem estação de "
                   "despesa e sem instrumento. O valor é associação "
                   "textual, não repasse.")
            oq = f'<b>{fmt(r["valor"])}</b>só menção textual'
            det = (f"a associação vem do texto da(s) edição(ões) "
                   f"{', '.join(sorted(r['edicoes']))}; nenhuma via de "
                   "verificação de repasse.")
        itens.append((ordem[sem], -(r["valor"] or 0),
                      linha(n, sem, tip, oq, det)))
    graves = []
    for n in sorted(exercicio - set(no_mes) - {""}):
        v = vinculos.get(n)
        if not v:
            continue
        tip = ("TOTALMENTE OMISSO NO MÊS: entidade com vínculo no exercício "
               f"({', '.join(v.get('vinculo') or ['?'])}, {fmt(v['valor'])}) "
               "e nenhum registro na competência.")
        oq = '<b>—</b>nada publicado no mês'
        det = (f"vínculo do exercício: "
               f"{esc(', '.join(v.get('vinculo') or []))} — "
               f"{fmt(v['valor'])} em {v.get('data')}; no mês, nenhuma "
               "publicação. Falta o demonstrativo mensal — Artigo 48-A, "
               "inciso I, da Lei Complementar 101/2000.")
        graves.append((0, -v["valor"], linha(n, "vermelho", tip, oq, det)))
    consolidados = []
    for e in coletivos_mes:
        val = max(e.get("valores") or [0])
        nomes = []
        for c in e.get("cnpjs") or []:
            d = mapa.get(digitos(c))
            nomes.append(f"{(d['nome'] if d else 'razão social pendente')} "
                         f"({fmt_cnpj(c)})")
        nlist = "".join(f'<span class="li">{esc(x)}</span>' for x in nomes)
        consolidados.append(
            f'<details class="plin"><summary>'
            f'<span class="quem"><b>ENVIO COLETIVO — deliberação de '
            f'{e.get("data")}</b>edição {esc(e.get("edicao", "?"))} · '
            f'{len(nomes)} entidades em conjunto</span>'
            f'<span class="oq"><b>{fmt(val)}</b>valor único, coletivo</span>'
            f'<span class="sem laranja" data-tip="SEM INDIVIDUALIZAÇÃO: a '
            f'publicação traz um único valor para o conjunto de '
            f'{len(nomes)} entidades. A ausência de individualização é, '
            f'ela própria, desconformidade: a liquidação exige identificar '
            f'o credor e o valor de cada um — Artigo 63, § 2º, da Lei '
            f'4.320/1964."></span></summary>'
            f'<div class="det"><b>Observação:</b> não existe '
            f'individualização publicada — o valor é do conjunto e não se '
            f'repete por entidade nesta análise. Rateio igualitário seria '
            f'{fmt(val / max(len(nomes), 1))} por entidade, sem critério '
            f'publicado que o sustente.<br><br>'
            f'<b>Entidades alcançadas em conjunto:</b>'
            f'<div class="ev" style="--pt:#e07b00">{nlist}</div>'
            f'{bloco_segunda_etapa("prestacao_entidades_13019", "Validação em 2ª etapa do envio coletivo")}'
            f'</div></details>')
    todos = consolidados + [h for _, _, h in sorted(graves + itens)]
    if not todos:
        return ('<p class="explica">Nenhuma entidade com vínculo no '
                'exercício e nenhuma menção no mês.</p>')
    return ('<p class="explica">O que consta como enviado a cada entidade '
            'na competência, com a ORIGEM do recurso (emenda parlamentar, '
            'instrumento da Lei 13.019/2014 ou deliberação coletiva), a '
            'checagem de cumprimento da Lei 13.019/2014 e a CAUSA de cada '
            'valor. Símbolo à direita: passe o mouse para ver onde foi '
            'verificado; clique para os dados completos.</p>'
            '<p class="legenda"><span class="sem verde" style="display:inline-block;vertical-align:-3px"></span> duas vias '
            '<span class="sem azul" style="display:inline-block;vertical-align:-3px;margin-left:10px"></span> uma via '
            '<span class="sem laranja" style="display:inline-block;vertical-align:-3px;margin-left:10px"></span> só menção/valor coletivo '
            '<span class="sem vermelho" style="display:inline-block;vertical-align:-3px;margin-left:10px"></span> totalmente omisso</p>'
            '<div class="presta">' + "".join(todos) + '</div>')


def tabelas_dados_html(comp_receita, evs, fluxo, mapa):
    igd = comp_receita.get("igd", {}) if comp_receita else {}
    situ = igd.get("situacao", "—")
    ruim = ' class="ruim"' if igd.get("aplicado_publicado") is None else ""
    t1 = (f'<table><tr><th>Competência</th><th class="num">Base mensal '
          f'estimada</th><th class="num">Devido ao Conselho (10%)</th>'
          f'<th class="num">Aplicação publicada</th><th>Situação</th></tr>'
          f'<tr{ruim}><td>{comp_receita["competencia"]}</td>'
          f'<td class="num">{fmt(igd.get("base_mensal_estimada"))}</td>'
          f'<td class="num">{fmt(igd.get("devido_ao_conselho_10"))}</td>'
          f'<td class="num">{fmt(igd.get("aplicado_publicado"))}</td>'
          f'<td>{situ}</td></tr></table>'
          '<p class="legenda">Artigo 6º da Resolução CNAS/MDS 202/2025 e '
          'Artigo 14, § 7º, da Lei 14.601/2023 — o piso incide competência '
          'a competência.</p>')
    vinculos = {digitos(d.get("cnpj", "")): d for d in fluxo["despesas"]}
    por_ent = {}
    for e in evs:
        ests = set(e.get("estacoes") or [])
        for c in e.get("cnpjs") or []:
            n = digitos(c)
            r = por_ent.setdefault(n, {"n": 0, "v": 0.0, "despesa": False})
            r["n"] += 1
            r["v"] = max(r["v"], max(e.get("valores") or [0]))
            r["despesa"] |= bool(ests & DESPESA)
    if por_ent:
        def rotulo(n, r):
            v = vinculos.get(n)
            if v and (r["despesa"] or True) and v.get("valor"):
                return fmt(v["valor"]), "repasse publicado no exercício"
            if r["despesa"]:
                return fmt(r["v"]), "repasse publicado no mês"
            return fmt(r["v"]), "menção textual — não é repasse"
        linhas = ""
        for n, r in sorted(por_ent.items(), key=lambda kv: -kv[1]["v"]):
            val, rot = rotulo(n, r)
            linhas += (f'<tr><td>{fmt_cnpj(n)}</td>'
                       f'<td>{esc((mapa.get(n) or {}).get("nome", "cadastro em busca na base da Receita"))}</td>'
                       f'<td class="num">{r["n"]}</td>'
                       f'<td class="num" data-tip="{rot}">{val}<br>'
                       f'<small style="color:#6b6660">{rot}</small></td></tr>')
        t2 = ('<table><tr><th>Inscrição (CNPJ)</th><th>Razão social</th>'
              '<th class="num">Menções</th><th class="num">Valor e natureza'
              '</th></tr>' + linhas + '</table>'
              '<p class="legenda">O valor exibido é o do repasse publicado '
              'quando existe; menção textual permanece rotulada como tal — '
              'associação no texto não é prova de pagamento.</p>')
    else:
        t2 = ('<p class="explica">Nenhuma pessoa jurídica citada nos eventos '
              'do mês.</p>')
    return t1, t2


def _seg_etapa():
    try:
        return json.loads((RAIZ / "relatorios" / "segunda_etapa.json")
                          .read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def bloco_segunda_etapa(chave_mapa, rotulo="Validação em 2ª etapa"):
    """Para uma informação indisponível na 1ª via (Diário), lista as fontes
    oficiais alternativas do mapa, com o estado da última sonda."""
    se = _seg_etapa()
    if not se:
        return ""
    fontes = se.get("mapa", {}).get(chave_mapa, [])
    if not fontes:
        return ""
    linhas = []
    for f in fontes:
        d = se["fontes"].get(f, {})
        if d.get("disponivel"):
            est, cor = "fonte no ar — consultar", "#1d8a3a"
        elif d.get("http") is None and se.get("sondado_em"):
            est, cor = "fora do ar na última sonda", "#c1281f"
        else:
            est, cor = f'respondeu HTTP {d.get("http")}', "#a85b00"
        linhas.append(
            f'<span class="li"><b class="k" style="color:{cor}">●</b>'
            f'<b>{esc(d.get("nome", f))}</b> — '
            f'<a href="{d.get("url", "#")}">{esc(d.get("url", ""))}</a> '
            f'<i>({est}, sonda de {se.get("sondado_em")})</i></span>')
    return (f'<div class="camada falta"><b class="rot">{rotulo} — a mesma '
            f'informação em outra fonte oficial</b>'
            f'<div class="ev" style="--pt:#1d4f8a">{"".join(linhas)}</div>'
            f'A confirmação por qualquer destas vias eleva o achado de '
            f'INCONCLUSIVO/INDICIÁRIO a CONFIRMADO por dupla via.</div>')


CHAVE_2E = {"REC": "receita_realizada", "IGD": "igd_demonstrativo",
            "EXE": "empenhos_por_dotacao", "PUB": None, "CMAS": None}


def casos_semelhantes(v):
    """Top-3 precedentes da Trilha do Mato tematicamente próximos dos
    achados do mês — inspiram providência, jamais fundamentam parecer."""
    try:
        prec = json.loads((RAIZ / "referencias" / "transparencia" /
                           "precedentes.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ""
    temas = " ".join(a["titulo"] for a in v["achados"]).upper()
    chaves = [("DIÁRIO OFICIAL", "diário"), ("TRANSPAR", "transpar"),
              ("CONSELHO", "conselho"), ("IGD", "igd"),
              ("PORTAL", "portal"), ("FUNDO", "fundo")]
    ativos = [c for c, k in chaves if c in temas]
    sel = []
    for it in prec.get("itens", []):
        tt = (it.get("titulo") or "").upper()
        if any(c in tt for c in ativos):
            sel.append(it)
        if len(sel) == 3:
            break
    if not sel:
        return ""
    linhas = "".join(
        f'<span class="li"><b class="k">{esc(i.get("fonte", "?"))}</b>'
        f'<a href="{i.get("url", "#")}">{esc(i.get("titulo", ""))}</a> '
        f'<i>({i.get("situacao", "")})</i></span>' for i in sel)
    return ('<h2><span data-tip="Trilha do Mato: onde outros já acharam o '
            'queijo escondido — inspira providência, nunca fundamenta">'
            'Casos semelhantes em outros estados</span></h2>'
            '<p class="explica">Precedentes capturados que tocam os temas '
            'dos achados do mês; itens de imprensa exigem confirmação na '
            'fonte oficial antes de qualquer uso.</p>'
            f'<div class="ev" style="--pt:#4a7c59">{linhas}</div>')


def alertas_vinculo():
    try:
        return json.loads((RAIZ / "referencias" / "vinculos" /
                           "alertas.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"alertas": []}


def pncp_da_entidade(cnpj_dig):
    try:
        p = json.loads((RAIZ / "dados" / "pncp_contratos.json")
                       .read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ""
    meus = [c for c in p.get("contratos", [])
            if digitos(c.get("cnpj_fornecedor") or "") == cnpj_dig]
    if not meus:
        return ""
    linhas = "".join(
        f'<span class="li"><b class="k">{esc(c.get("modalidade") or "?")}</b>'
        f'{esc((c.get("objeto") or "")[:110])} — {fmt(c.get("valor"))} '
        f'(PNCP {esc(str(c.get("pncp_id")))})'
        + (f'<br><i style="color:#a85b00">{esc(c["observacao_q2"])}</i>'
           if c.get("observacao_q2") else "") + '</span>' for c in meus[:5])
    return (f'<br><b>Contratações no PNCP (Lei 14.133/2021, Artigo 174):</b>'
            f'<div class="ev" style="--pt:#3a5f8a">{linhas}</div>')


def ficha_html(a):
    sev = COR_SEV[a["severidade"]]
    selo = COR_SELO[a["selo"]]
    pref = a["codigo"].split("-")[0]
    falta = ""
    if a.get("impedimento"):
        ch = CHAVE_2E.get(a["codigo"].split("-")[0])
        falta = (f'<div class="camada falta"><b class="rot">O que falta e '
                 f'onde obter</b>Fica impedido: {a["impedimento"]}. '
                 f'Obter em: {a.get("onde_obter", "—")}.</div>'
                 + (bloco_segunda_etapa(ch) if ch else ""))
    return f"""<article class="ficha" style="--sev:{sev}">
 <div class="topo"><span class="ic">{ICONE.get(pref, "•")}</span>
  <span class="tit">{a["titulo"]}</span>
  <span class="badge" style="background:{sev}" data-tip="severidade da desconformidade">{ROTULO_SEV[a["severidade"]]}</span>
  <span class="badge" style="background:{selo}" data-tip="nível de prova do achado">{ROTULO_SELO[a["selo"]]}</span>
 </div>
 <div class="corpo">
  <div class="camada"><b class="rot">O que se apurou</b>{a["detalhe"]}</div>
  {falta}
 </div>
 <div class="norma"><b>Fundamento:</b> {a["norma"]}<br>
 <b>Fonte e rastreio:</b> apuração determinística sobre publicações do
 Diário Oficial ancoradas por sha256 no histórico do repositório (arquivo
 relatorios/mensal/verificacao_da_competência); edições citadas nos dados do
 achado. Reprodutível por terceiro a partir do hash.</div>
</article>"""


def gera(comp):
    v = json.loads((REL / f"verificacao_{comp}.json").read_text(encoding="utf-8"))
    receita = carrega("receita_mensal_2026.json")
    trilha = carrega("trilha_dinheiro.json")
    fluxo = carrega("fluxo_2026.json")
    mapa = mapa_entidades()
    comp_rec = next((c for c in receita["competencias"]
                     if c["competencia"] == comp), None)
    evs = [e for e in trilha["detalhe"]
           if str(e.get("data", "")).startswith(comp)]
    pub = next((a["dados"] for a in v["achados"]
                if a["codigo"].startswith("PUB-M")), {})
    sev = v["por_severidade"]

    frase = (f'{v["total_achados"]} desconformidades na competência — '
             f'{sev.get("critica", 0)} críticas, {sev.get("alta", 0)} altas, '
             f'{sev.get("media", 0)} médias. O que está em ordem foi omitido: '
             'o silêncio do relatório é resultado.')
    placar = "".join(
        f'<div style="--cor:{COR_SEV[s]}" data-tip="desconformidades de '
        f'severidade {ROTULO_SEV[s].lower()} na competência">'
        f'<div class="n">{sev.get(s, 0)}</div>'
        f'<div class="t">{ROTULO_SEV[s]}</div></div>'
        for s in ("critica", "alta", "media")) + (
        f'<div style="--cor:#4a4a58" data-tip="regra aplicada, documento '
        f'ausente — dado faltante é achado, não silêncio"><div class="n">'
        f'{v["por_selo"].get("INCONCLUSIVO_POR_DOCUMENTO_FALTANTE", 0)}</div>'
        f'<div class="t">Documento faltante</div></div>')

    itens_pizza, leg = [], []
    if comp_rec:
        for f, val in sorted(comp_rec["previsto_por_fonte"].items(),
                             key=lambda kv: -kv[1]):
            cor = COR_FONTE.get(f, "#8a8a94")
            itens_pizza.append((NOME_FONTE.get(f, f), val, cor))
            leg.append(f'<div><i style="background:{cor}"></i>'
                       f'{NOME_FONTE.get(f, f)}<b class="v">{fmt(val)}</b></div>')
    pizza = pizza_svg(itens_pizza) if itens_pizza else ""
    legenda_pizza = ('<div class="leg">' + "".join(leg) +
                     '<p class="legenda" style="margin-top:10px">A fatia '
                     'vermelha do Tesouro — R$ 750,00 mensais — é a expressão '
                     'mensal da queda de 99,46% do aporte próprio.</p></div>')
    t_igd, t_ent = tabelas_dados_html(comp_rec, evs, fluxo, mapa)
    ger = {"REC", "PUB"}
    fichas_gerais = "".join(ficha_html(a) for a in v["achados"]
                            if a["codigo"].split("-")[0] in ger) or (
        '<p class="explica">nenhuma desconformidade geral no mês.</p>')
    fichas_fundo = "".join(ficha_html(a) for a in v["achados"]
                           if a["codigo"].split("-")[0] not in ger) or (
        '<p class="explica">nenhuma desconformidade específica no mês.</p>')
    estruturais = "".join(f"<li><b>{t}</b> — {d}</li>" for t, d in ESTRUTURAIS)
    titulo = f'Parecer de fiscalização — <b>{v["mes"]} de {v["exercicio"]}</b>'
    sub = (f'competência {comp} · gerado em {v["gerado_em"]} · camada de IA: '
           f'{v["camada_ia"]}')

    html = f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Parecer mensal — {v["mes"]} de {v["exercicio"]}</title>
<style>{CSS}</style></head><body>
{cabecalho_html(titulo, sub)}
<div class="uma-frase"><small>Em uma frase</small>{frase}</div>
<div class="placar">{placar}</div>

<div class="parte" style="--pc1:#1c2733;--pc2:#3a5f8a"><div class="pt">Parte
Geral</div><div class="pn">Recursos da assistência social — o que afeta as
duas contas</div></div>

<h2><span data-tip="série mensal do que foi publicado na trilha do dinheiro">G1 · Linha do exercício — o mês no contexto de janeiro a julho</span></h2>
{detalhes("Informações completas e omissões legais desta seção", "Parâmetros: eventos publicados, empenhos, liquidações/pagamentos por mês. Omissão legal permanente: nenhum mês exibe liquidação ou pagamento — Artigo 63 e Artigo 64 da Lei 4.320/1964; Artigo 48-A, inciso I, da Lei Complementar 101/2000.")}
<p class="explica">O que foi publicado mês a mês na trilha do dinheiro; a
faixa sombreada é a competência deste parecer. Passe o mouse nos pontos.</p>
{linha_exercicio_svg(trilha, comp)}

<h2><span data-tip="separação entre a conta controlada pelo Conselho (3650) e a unidade do Gabinete (3601)">G2 · As duas contas — visão comparada — Fundo da assistência social × Gabinete da Secretaria</span></h2>
{detalhes("Informações completas e omissões legais desta seção", "Parâmetro: trânsito obrigatório pelo Fundo — Artigo 30 da Lei 8.742/1993 e Artigo 2º da Lei municipal 7.531/1995. Omissão: transferência automática do § 1º não localizada em publicação alguma.")}
{fluxograma_duas_contas(fluxo)}

<h2><span data-tip="composição prevista das fontes da competência">G3 · De onde veio — fontes previstas da competência</span></h2>
{detalhes("Informações completas e omissões legais desta seção", "Parâmetro: previsão por fonte na Lei Orçamentária 11.590/2026. Omissão: receita realizada do mês sem demonstrativo — Artigo 48 e Artigo 48-A da Lei Complementar 101/2000 (achado REC-M).")}
<div class="grade2"><div>{pizza}</div>{legenda_pizza}</div>

<h2>G4 · O Diário Oficial no mês</h2>
{calendario_html(comp, pub)}

<h2>G5 · Fichas de desconformidade — gerais (receita e publicidade)</h2>
{fichas_gerais}

<div class="parte" style="--pc1:#123524;--pc2:#1d6f42"><div class="pt">Parte I — Conta especial do Fundo (un. 3650)</div><div class="pn">Prestação de contas sob orientação e controle do CMASGyn — Artigo 30, inciso II, da Lei 8.742/1993</div></div>

<h2><span data-tip="entrada por fonte, passagem pela conta especial e saída por destinatário, no exercício">F1 · Fluxograma da conta especial — entrada, passagem pelo Fundo e saída</span></h2>
{detalhes("Informações completas e omissões legais desta seção", "Parâmetros: comprovação documental de cada fonte e vínculo de cada saída. Omissões: extratos mensais da conta especial não publicados; despesa sem instrumento — Artigo 61 da Lei 4.320/1964 e Artigo 38 da Lei 13.019/2014.")}
<p class="explica">Balões proporcionais ao valor do exercício; passe o mouse
para o resumo de cada balão e seta, clique abaixo para os dados completos.</p>
{fluxograma_baloes(fluxo, evs, mapa, comp)}

<h2><span data-tip="as quatro estações legais da despesa no mês">F2 · Por onde passou no Fundo — as quatro estações legais no mês</span></h2>
{detalhes("Informações completas e omissões legais desta seção", "Parâmetro: Artigo 58, Artigo 60, Artigo 62, Artigo 63 e Artigo 64 da Lei 4.320/1964. Omissão do mês: estações zeradas indicadas em vermelho no próprio fluxo.")}
{fluxo_estacoes_svg(comp_rec["previsto_total"] if comp_rec else None,
                    v["execucao_do_mes"]["por_estacao"])}

<h2>F3 · Cronologia — a trilha do dinheiro no mês, evento a evento</h2>
{cronologia_html(evs, mapa)}

<h2>F4 · Prestação de contas mensal por entidade — omissões</h2>
{prestacao_por_entidade(comp, evs, fluxo, mapa)}
{bloco_segunda_etapa("prestacao_entidades_13019", "Validação em 2ª etapa das parcerias")}

<h2>F5 · Demonstração de dados · piso do IGD na competência</h2>
{t_igd}

<h2>F6 · Demonstração de dados · pessoas jurídicas citadas no mês</h2>
{t_ent}

<h2>F7 · Fichas de desconformidade — do Fundo e do controle social</h2>
{fichas_fundo}

<div class="parte" style="--pc1:#4a2703;--pc2:#a85b00"><div class="pt">Parte II — Conta do Gabinete da Secretaria (un. 3601)</div><div class="pn">Prestação de contas e análise individual — execução fora do Fundo</div></div>

<h2><span data-tip="destinações da unidade 3601 no Quadro de Detalhamento da Despesa, com a lacuna de extração explicitada">S1 · Fluxograma da conta do Gabinete — origem e destinações</span></h2>
{detalhes("Informações completas e omissões legais desta seção", "Parâmetro: trânsito obrigatório pelo Fundo — Artigo 30, parágrafo único, da Lei 8.742/1993; Artigo 2º da Lei municipal 7.531/1995. Omissões: nenhum demonstrativo próprio da unidade publicado; QDD capturado parcialmente; folha de pagamento a cruzar com o teto de 30% do Artigo 4º da Lei Complementar municipal 273/2014.")}
{fluxograma_gabinete(fluxo)}

<h2><span data-tip="o que a conta 3601 publicou (ou omitiu) na competência">S2 · Prestação de contas mensal da conta 3601 — análise individual</span></h2>
{prestacao_gabinete(comp, evs, v["mes"])}
{bloco_segunda_etapa("folha_e_execucao_3601", "Validação em 2ª etapa da conta 3601")}

<h2><span data-tip="cada destinação do QDD da unidade 3601, pormenorizada, com o estado da informação em símbolo — roxo quando nada foi publicado">S3 · Prestação de contas por destinação do QDD — pormenorizada</span></h2>
{prestacao_gabinete_completa(comp, evs, v["mes"], fluxo)}

<h2><span data-tip="apenas adicionais, horas extras e pagamentos acima do teto municipal — o restante da folha não entra no resumo">S4 · Folha do Gabinete — resumo dirigido (adicionais, horas extras e teto)</span></h2>
{folha_gabinete_resumo(v["mes"])}
{bloco_segunda_etapa("folha_e_execucao_3601", "Validação em 2ª etapa da folha")}

{casos_semelhantes(v)}\n\n<h2>G6 · Condições estruturais que perduram na competência</h2>
<div class="estrutural"><ul>{estruturais}</ul>
<p style="margin-top:8px">Apuradas no exercício e vigentes no mês; constam do
parecer consolidado anual e não são recontadas como achados mensais novos.</p></div>
<footer>
 Pessoas físicas, quando referidas, aparecem apenas pelo primeiro nome,
 minimizadas na extração. Pessoas jurídicas mantêm razão social e inscrição
 completas. Metodologia e dados: repositório público da fiscalização.
</footer>
{rodape_marca_html()}</body></html>"""
    DOCS.mkdir(parents=True, exist_ok=True)
    destino = DOCS / f"parecer_{comp}.html"
    destino.write_text(html, encoding="utf-8")
    return destino


def indice():
    meses = sorted(REL.glob("verificacao_*.json"))
    linhas = []
    for m in meses:
        v = json.loads(m.read_text(encoding="utf-8"))
        c = v["competencia"]
        s = v["por_severidade"]
        linhas.append(
            f'<a class="ficha" style="--sev:#8c1d18;display:block;'
            f'text-decoration:none;color:inherit" href="parecer_{c}.html">'
            f'<div class="topo"><span class="tit">{v["mes"].capitalize()} de '
            f'{v["exercicio"]}</span>'
            f'<span class="badge" style="background:{COR_SEV["critica"]}">'
            f'{s.get("critica", 0)} críticas</span>'
            f'<span class="badge" style="background:{COR_SEV["alta"]}">'
            f'{s.get("alta", 0)} altas</span>'
            f'<span class="badge" style="background:{COR_SEV["media"]}">'
            f'{s.get("media", 0)} médias</span></div></a>')
    html = f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pareceres mensais — 2026</title><style>{CSS}</style></head><body>
{cabecalho_html("Pareceres <b>mensais</b> — 2026")}
{"".join(linhas)}
<footer></footer>
{rodape_marca_html()}</body></html>"""
    (DOCS / "index.html").write_text(html, encoding="utf-8")


def main():
    if len(sys.argv) < 2 or not re.fullmatch(r"\d{4}-\d{2}", sys.argv[1]):
        print("uso: gera_parecer_mensal_html.py AAAA-MM"); return 2
    destino = gera(sys.argv[1])
    indice()
    print(f"  parecer: {destino.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
