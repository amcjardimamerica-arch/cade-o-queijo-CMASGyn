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
from marca import cabecalho_html

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
[data-tip]:hover::after{content:attr(data-tip);position:absolute;left:0;bottom:calc(100% + 8px);
z-index:9;background:#1c2733;color:#fff;font:12px/1.5 Arial,sans-serif;padding:8px 11px;
border-radius:6px;width:max-content;max-width:340px;white-space:normal;
box-shadow:0 4px 14px rgba(0,0,0,.25)}
[data-tip]:hover::before{content:"";position:absolute;left:14px;bottom:100%;z-index:9;
border:7px solid transparent;border-top-color:#1c2733;transform:translateY(1px)}
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
    """CNPJ (por dígitos) -> razão social, unindo o cadastro principal e o
    complemento cirúrgico da base oficial da Receita Federal."""
    m = {}
    dest = carrega("destinatarios_2026.json")
    for d in dest["destinatarios"]:
        if d.get("razao_social"):
            m[digitos(d["cnpj"])] = d["razao_social"]
    try:
        compl = carrega("cadastro_cnpj_complementar.json")
        for c, d in compl.get("cadastros", {}).items():
            if d.get("razao_social"):
                m.setdefault(digitos(c), d["razao_social"])
    except FileNotFoundError:
        pass
    return m


def classifica_valor(evento):
    """O rótulo do valor segue a estação alcançada no próprio evento:
    repasse/liquidação/pagamento publicados > empenho > menção textual."""
    ests = set(evento.get("estacoes") or [])
    if ests & DESPESA:
        return "repasse publicado"
    if "empenho" in ests:
        return "empenho publicado"
    return "menção textual"


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


def fluxograma_baloes(fluxo, evs_mes, mapa, comp):
    """Fluxograma de balões: entradas (fontes) → conta do Fundo → saídas
    (despesas publicadas do exercício). Raio proporcional à raiz do valor;
    hover mostra o resumo, o clique abre os dados completos."""
    fontes = sorted(fluxo["fontes"], key=lambda f: -f["valor"])[:6]
    fundo = next(c for c in fluxo["contas"] if c["unidade"] == "3650")
    saidas = sorted(fluxo["despesas"], key=lambda d: -d["valor"])[:6]
    W, H = 900, 460
    maxf = max(f["valor"] for f in fontes)
    maxs = max((d["valor"] for d in saidas), default=1)
    g = [f'<svg viewBox="0 0 {W} {H}" role="img">']
    n = len(fontes)
    cx_f, cx_c, cx_s = 120, W / 2, W - 130
    for i, f in enumerate(fontes):
        y = 50 + i * (H - 90) / max(n - 1, 1)
        r = 18 + 26 * math.sqrt(f["valor"] / maxf)
        cor = COR_FONTE.get(f.get("fonte"), "#4a7c59")
        if f.get("status") != "comprovada":
            cor = "#8a8a94"
        tip = (f'{f["nome"]} — {fmt(f["valor"])} no exercício '
               f'({f.get("status", "?")}). Prova: {f.get("prova", "—")}')
        g.append(_balao(cx_f, y, r, cor, f.get("fonte", "?"), f["valor"], tip))
        g.append(_seta(cx_f + r, y, cx_c - 92, H / 2,
                       2 + 8 * f["valor"] / maxf, cor,
                       f'entrada: {f["nome"]} → conta do Fundo — '
                       f'{fmt(f["valor"])}'))
    g.append(_balao(cx_c, H / 2, 88, "#1d4f8a", "Conta especial|do Fundo|un. 3650",
                    fundo["valor"],
                    f'{fundo["nome"]} — {fmt(fundo["valor"])}. {fundo["nota"]} '
                    f'Falta: {fundo.get("falta", "—")}'))
    ev_desp = sum(1 for e in evs_mes if DESPESA & set(e.get("estacoes") or []))
    for i, d in enumerate(saidas):
        y = 50 + i * (H - 90) / max(len(saidas) - 1, 1)
        r = 14 + 22 * math.sqrt(d["valor"] / maxs)
        nome = mapa.get(digitos(d.get("cnpj", "")), "")
        rot = (nome.split()[0][:12] if nome else fmt_cnpj(d.get("cnpj", "?"))[:10])
        comprovada = d.get("tipo") == "comprovada"
        cor = "#1d4f2b" if comprovada else "#a85b00"
        tip = (f'saída: {fmt_cnpj(d.get("cnpj", "?"))} — '
               f'{nome or "razão social pendente"} — {fmt(d["valor"])} '
               f'em {d.get("data", "?")}. Vínculo: '
               f'{", ".join(d.get("vinculo") or ["nenhum publicado"])}. '
               f'Objeto: {d.get("objeto", "—")}')
        g.append(_seta(cx_c + 92, H / 2, cx_s - r - 4, y,
                       2 + 8 * d["valor"] / maxs, cor, tip,
                       tracejada=not comprovada))
        g.append(_balao(cx_s, y, r, cor, rot, d["valor"], tip))
    g.append(f'<text x="{cx_f}" y="24" text-anchor="middle" '
             f'style="font:700 12px Arial;fill:#6b6660">ENTRADA — FONTES</text>'
             f'<text x="{cx_c}" y="24" text-anchor="middle" '
             f'style="font:700 12px Arial;fill:#6b6660">PASSAGEM PELO FUNDO</text>'
             f'<text x="{cx_s}" y="24" text-anchor="middle" '
             f'style="font:700 12px Arial;fill:#6b6660">SAÍDA — DESTINATÁRIOS</text>')
    g.append('</svg>')
    aviso = (f'<p class="legenda">balões e setas proporcionais ao valor; '
             f'tracejado = sem vínculo publicado. No mês da competência, '
             f'{ev_desp} evento(s) alcançaram estação de despesa — '
             f'{"nenhuma saída do mês tem liquidação ou pagamento publicado" if ev_desp == 0 else "ver cronologia abaixo"}. '
             f'Do total do Fundo, só {fmt(fluxo["totais"]["despesa_comprovada"])} '
             f'de despesa comprovada no exercício.</p>')
    linhas = "".join(
        f'<tr><td>{fmt_cnpj(d.get("cnpj", "?"))}</td>'
        f'<td>{esc(mapa.get(digitos(d.get("cnpj", "")), "razão social pendente"))}</td>'
        f'<td>{d.get("data", "—")}</td>'
        f'<td>{esc(", ".join(d.get("vinculo") or ["—"]))}</td>'
        f'<td class="num">{fmt(d["valor"])}</td></tr>' for d in saidas)
    tab = ('<table><tr><th>Inscrição</th><th>Razão social</th><th>Data</th>'
           '<th>Vínculo publicado</th><th class="num">Valor</th></tr>'
           + linhas + '</table>')
    return "".join(g) + aviso + detalhes(
        "Abrir dados completos das saídas do exercício", tab)


def fluxograma_duas_contas(fluxo):
    """Conta do Fundo (3650) × conta do Gabinete da Secretaria (3601)."""
    fundo = next(c for c in fluxo["contas"] if c["unidade"] == "3650")
    gab = next(c for c in fluxo["contas"] if c["unidade"] == "3601")
    tot = fundo["valor"] + gab["valor"]
    rf = 34 + 52 * math.sqrt(fundo["valor"] / tot)
    rg = 34 + 52 * math.sqrt(gab["valor"] / tot)
    W, H = 900, 330
    g = [f'<svg viewBox="0 0 {W} {H}" role="img">']
    g.append(_balao(150, 110, 52, "#8c1d18", "Tesouro|Municipal", None,
                    "Tesouro Municipal — fonte integral da unidade 3601 e de "
                    "apenas R$ 9.000 do Fundo em 2026"))
    g.append(_seta(202, 96, W/2 - rg - 8, 88, 2 + 10 * gab["valor"] / tot,
                   "#8c1d18",
                   f'Tesouro → Gabinete (3601): {fmt(gab["valor"])} correm '
                   f'FORA do Fundo'))
    g.append(_balao(W/2, 88, rg, "#a85b00", "Gabinete da|Secretaria|un. 3601",
                    gab["valor"],
                    f'{gab["nome"]} — {fmt(gab["valor"])}. {gab["nota"]}'))
    g.append(_seta(202, 124, W/2 - rf - 8, 240, 2 + 10 * 9000 / tot, "#8c1d18",
                   "Tesouro → Fundo: apenas R$ 9.000,00 em 2026 (queda de "
                   "99,46% sobre 2025)"))
    g.append(_balao(W/2, 240, rf, "#1d4f8a", "Conta especial|do Fundo|un. 3650",
                    fundo["valor"],
                    f'{fundo["nome"]} — {fmt(fundo["valor"])}. {fundo["nota"]}'))
    g.append(_seta(W/2, 88 + rg, W/2, 240 - rf, 4, "#c1281f",
                   "Transferência automática ao Fundo determinada pelo "
                   "Artigo 2º, § 1º, da Lei municipal 7.531/1995 — NÃO "
                   "localizada em publicação alguma do exercício",
                   tracejada=True))
    g.append(f'<text x="{W/2 + 20}" y="170" '
             f'style="font:700 12px Arial;fill:#c1281f">transferência '
             f'automática (Artigo 2º, § 1º, da Lei 7.531/1995): '
             f'não publicada ✕</text>')
    g.append(f'<text x="{W-250}" y="80" style="font:700 12px Arial;'
             f'fill:#a85b00">⅘ do dinheiro da pasta</text>'
             f'<text x="{W-250}" y="96" style="font:12px Arial;'
             f'fill:#6b6660">fora do controle do Conselho</text>'
             f'<text x="{W-250}" y="232" style="font:700 12px Arial;'
             f'fill:#1d4f8a">onde o Conselho controla</text>'
             f'<text x="{W-250}" y="248" style="font:12px Arial;'
             f'fill:#6b6660">Artigo 30, inciso II, da Lei 8.742/1993</text>')
    g.append('</svg>')
    tab = (f'<table><tr><th>Conta</th><th>Unidade</th><th class="num">Valor '
           f'2026</th><th>Base legal</th><th>Situação</th></tr>'
           f'<tr><td>{esc(fundo["nome"])}</td><td>3650</td>'
           f'<td class="num">{fmt(fundo["valor"])}</td>'
           f'<td>{esc(fundo["base"])}</td><td>{esc(fundo["status"])}</td></tr>'
           f'<tr class="ruim"><td>{esc(gab["nome"])}</td><td>3601</td>'
           f'<td class="num">{fmt(gab["valor"])}</td>'
           f'<td>{esc(gab["base"])}</td><td>{esc(gab["status"])} — '
           f'integralmente Tesouro, fora do Fundo</td></tr></table>')
    return ("".join(g) +
            '<p class="legenda">passe o mouse sobre balões e setas para o '
            'resumo; a seta tracejada vermelha é a transferência que a lei '
            'manda e não aparece publicada.</p>' +
            detalhes("Abrir dados completos das duas contas", tab))


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


def cronologia_html(evs, mapa):
    if not evs:
        return ('<p class="explica">Nenhum evento publicado na competência — '
                'a ausência é, ela própria, o achado EXE-M do mês.</p>')
    linhas = []
    for e in sorted(evs, key=lambda x: (x.get("data", ""), x.get("pagina", 0))):
        ests = e.get("estacoes") or []
        cor = COR_EST.get(ests[0], "#8a8a94") if ests else "#8a8a94"
        chips = "".join(
            f'<span class="chip" style="background:'
            f'{COR_EST.get(s, "#8a8a94")}" data-tip="estação {s} — '
            f'{"comprova saída" if s in DESPESA else "não comprova saída de dinheiro"}">'
            f'{s}</span>' for s in ests)
        val = max(e.get("valores") or [0])
        rotv = classifica_valor(e)
        ents = ""
        if e.get("cnpjs"):
            nomes = []
            for c in e["cnpjs"][:4]:
                razao = mapa.get(digitos(c))
                nomes.append(f"{fmt_cnpj(c)} — {razao}" if razao
                             else f"{fmt_cnpj(c)} (cadastro em busca na base "
                                  f"da Receita)")
            ents = ('<div class="ent"><b>Pessoas jurídicas citadas:</b> '
                    + "; ".join(nomes) + "</div>")
        ed = e.get("edicao", "—")
        url = e.get("url")
        ed_html = f'<a href="{url}">{ed}</a>' if url else ed
        vhtml = (f'<span class="val" data-tip="classificação pela estação '
                 f'alcançada no próprio evento: {rotv}">{fmt(val)}'
                 f'<small>{rotv}</small></span>' if val else "")
        linhas.append(
            f'<div class="ev" style="--pt:{cor}">{vhtml}'
            f'<div class="qd"><b>{e.get("data", "—")}</b> · edição {ed_html} '
            f'· página {e.get("pagina", "—")}</div>{chips}{ents}</div>')
    return ('<p class="explica">Cada ponto é uma publicação do Diário que '
            'toca dinheiro da assistência social. O valor à direita é '
            'rotulado pela estação alcançada: só "repasse publicado" indica '
            'saída; "menção textual" é associação no texto, não prova de '
            'pagamento.</p><div class="crono">' + "".join(linhas) + "</div>")


def prestacao_por_entidade(comp, evs, fluxo, mapa):
    """Semáforo de verificação por entidade no mês:
       verde   = duas vias independentes (estação de despesa no Diário E
                 instrumento de vínculo publicado);
       azul    = uma via;
       laranja = apenas menção textual, nenhuma via de despesa;
       vermelho = entidade do exercício totalmente omissa no mês."""
    vinculos = {digitos(d.get("cnpj", "")): d for d in fluxo["despesas"]}
    exercicio = set(vinculos) | {
        digitos(c) for e in [x for x in carrega("trilha_dinheiro.json")["detalhe"]]
        for c in (e.get("cnpjs") or [])}
    no_mes = {}
    for e in evs:
        ests = set(e.get("estacoes") or [])
        val = max(e.get("valores") or [0])
        for c in e.get("cnpjs") or []:
            n = digitos(c)
            r = no_mes.setdefault(n, {"despesa": False, "mencao": 0,
                                      "valor": 0.0, "edicoes": set()})
            r["mencao"] += 1
            r["edicoes"].add(e.get("edicao", "?"))
            if ests & DESPESA:
                r["despesa"] = True
                r["valor"] = max(r["valor"], val)
            elif not r["despesa"]:
                r["valor"] = max(r["valor"], val)
    linhas = []

    def linha(n, sem, tip, oq, det):
        nome = mapa.get(n, "razão social pendente na base da Receita")
        return (f'<details class="plin"><summary>'
                f'<span class="quem"><b>{esc(nome)}</b>{fmt_cnpj(n)}</span>'
                f'<span class="oq">{oq}</span>'
                f'<span class="sem {sem}" data-tip="{esc(tip)}"></span>'
                f'</summary><div class="det">{det}</div></details>')

    ordem = {"vermelho": 0, "laranja": 1, "azul": 2, "verde": 3}
    itens = []
    for n, r in no_mes.items():
        v = vinculos.get(n)
        if r["despesa"] and v:
            sem = "verde"
            tip = ("VERIFICADO POR DUAS VIAS: (1ª) estação de despesa "
                   f"publicada no Diário — edições {', '.join(sorted(r['edicoes']))}; "
                   f"(2ª) instrumento de vínculo publicado — "
                   f"{', '.join(v.get('vinculo') or ['?'])}")
            oq = f'<b>{fmt(v["valor"])}</b>repasse com vínculo'
            det = (f"Enviado no mês: {fmt(v['valor'])} em {v.get('data')}. "
                   f"Objeto: {esc(v.get('objeto', '—'))}. Processo: "
                   f"{esc(v.get('processo', '—'))}. Vias de verificação: "
                   f"Diário Oficial (estação de despesa) e instrumento "
                   f"{esc(', '.join(v.get('vinculo') or []))}.")
        elif r["despesa"]:
            sem = "azul"
            tip = ("VERIFICADO POR UMA VIA: estação de despesa publicada no "
                   f"Diário — edições {', '.join(sorted(r['edicoes']))}. "
                   "Sem instrumento de vínculo localizado; segunda via "
                   "indisponível (portal da transparência — pendência P2).")
            oq = f'<b>{fmt(r["valor"])}</b>repasse publicado, sem vínculo'
            det = (f"Repasse publicado de {fmt(r['valor'])} sem contrato, "
                   "convênio ou termo localizado. O que falta: extrato da "
                   "conta especial e o instrumento de vínculo.")
        elif v:
            sem = "azul"
            tip = ("VERIFICADO POR UMA VIA: instrumento de vínculo publicado "
                   f"({', '.join(v.get('vinculo') or ['?'])}); no mês, porém, "
                   "só menção textual — nenhuma estação de despesa.")
            oq = f'<b>{fmt(r["valor"])}</b>menção; vínculo do exercício'
            det = (f"Entidade com vínculo publicado no exercício "
                   f"({esc(', '.join(v.get('vinculo') or []))}, "
                   f"{fmt(v['valor'])}), mas o mês registra apenas menção "
                   f"em {r['mencao']} evento(s), sem liquidação nem pagamento.")
        else:
            sem = "laranja"
            tip = (f"APENAS MENÇÃO: citada em {r['mencao']} evento(s) — "
                   f"edições {', '.join(sorted(r['edicoes']))} — sem estação "
                   "de despesa e sem instrumento de vínculo. O valor ao lado "
                   "é associação textual, não repasse.")
            oq = f'<b>{fmt(r["valor"])}</b>só menção textual'
            det = ("Nenhuma via de verificação de repasse: a prestação de "
                   "contas do mês é omissa quanto a esta entidade, embora o "
                   "Diário a mencione.")
        itens.append((ordem[sem], -r["valor"], linha(n, sem, tip, oq, det)))
    omissas = sorted(exercicio - set(no_mes) - {""})
    graves = []
    for n in omissas:
        v = vinculos.get(n)
        if not v:
            continue  # menção esparsa no exercício sem vínculo: ruído
        tip = ("TOTALMENTE OMISSO NO MÊS: entidade com vínculo publicado no "
               f"exercício ({', '.join(v.get('vinculo') or ['?'])}, "
               f"{fmt(v['valor'])}) e nenhum registro — nem menção — na "
               "competência. Sem demonstrativo, o envio do mês é inaferível.")
        oq = '<b>—</b>nada publicado no mês'
        det = (f"Vínculo do exercício: {esc(', '.join(v.get('vinculo') or []))} "
               f"— {fmt(v['valor'])} em {v.get('data')}. No mês: nenhuma "
               "publicação. O que falta: demonstrativo mensal de repasses e "
               "extrato da conta especial (Artigo 48-A, inciso I, da Lei "
               "Complementar 101/2000).")
        graves.append((0, -v["valor"], linha(n, "vermelho", tip, oq, det)))
    todos = [h for _, _, h in sorted(graves + itens)]
    if not todos:
        return ('<p class="explica">Nenhuma entidade com vínculo no exercício '
                'e nenhuma menção no mês.</p>')
    return ('<p class="explica">O que consta como enviado a cada entidade na '
            'competência, com o grau de verificação no símbolo à direita — '
            'passe o mouse para ver ONDE foi verificado; clique na linha '
            'para os dados completos.</p>'
            '<p class="legenda"><span class="sem verde" style="display:inline-block;vertical-align:-3px"></span> duas vias independentes '
            '<span class="sem azul" style="display:inline-block;vertical-align:-3px;margin-left:10px"></span> uma via '
            '<span class="sem laranja" style="display:inline-block;vertical-align:-3px;margin-left:10px"></span> só menção '
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
                       f'<td>{esc(mapa.get(n, "cadastro em busca na base da Receita"))}</td>'
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


def ficha_html(a):
    sev = COR_SEV[a["severidade"]]
    selo = COR_SELO[a["selo"]]
    pref = a["codigo"].split("-")[0]
    falta = ""
    if a.get("impedimento"):
        falta = (f'<div class="camada falta"><b class="rot">O que falta e '
                 f'onde obter</b>Fica impedido: {a["impedimento"]}. '
                 f'Obter em: {a.get("onde_obter", "—")}.</div>')
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
 <div class="norma"><b>Fundamento:</b> {a["norma"]}</div>
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
    fichas = "".join(ficha_html(a) for a in v["achados"])
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

<h2>1 · Linha do exercício — o mês no contexto de janeiro a julho</h2>
<p class="explica">O que foi publicado mês a mês na trilha do dinheiro; a
faixa sombreada é a competência deste parecer. Passe o mouse nos pontos.</p>
{linha_exercicio_svg(trilha, comp)}

<h2>2 · Fluxograma do dinheiro — entrada, passagem pelo Fundo e saída</h2>
<p class="explica">Balões proporcionais ao valor do exercício; passe o mouse
para o resumo de cada balão e seta, clique abaixo para os dados completos.</p>
{fluxograma_baloes(fluxo, evs, mapa, comp)}

<h2>3 · As duas contas — Fundo da assistência social × Gabinete da Secretaria</h2>
{fluxograma_duas_contas(fluxo)}

<h2>4 · De onde veio — fontes previstas da competência</h2>
<div class="grade2"><div>{pizza}</div>{legenda_pizza}</div>

<h2>5 · Por onde passou — as quatro estações legais no mês</h2>
{fluxo_estacoes_svg(comp_rec["previsto_total"] if comp_rec else None,
                    v["execucao_do_mes"]["por_estacao"])}

<h2>6 · O Diário Oficial no mês</h2>
{calendario_html(comp, pub)}

<h2>7 · Cronologia — a trilha do dinheiro no mês, evento a evento</h2>
{cronologia_html(evs, mapa)}

<h2>8 · Prestação de contas mensal por entidade — omissões</h2>
{prestacao_por_entidade(comp, evs, fluxo, mapa)}

<h2>9 · Demonstração de dados · piso do IGD na competência</h2>
{t_igd}

<h2>10 · Demonstração de dados · pessoas jurídicas citadas no mês</h2>
{t_ent}

<h2>11 · Fichas de desconformidade</h2>
{fichas}

<h2>12 · Condições estruturais que perduram na competência</h2>
<div class="estrutural"><ul>{estruturais}</ul>
<p style="margin-top:8px">Apuradas no exercício e vigentes no mês; constam do
parecer consolidado anual e não são recontadas como achados mensais novos.</p></div>
<footer>
 <div class="adv">Este documento é subsídio técnico de fiscalização. Nada aqui
 é peça processual sem revisão de advogado — Artigo 32 da Lei 8.906/1994.
 Indício de sobrepreço é indício: sobrepreço se demonstra por perícia com
 preço de mercado.</div>
 Pessoas físicas, quando referidas, aparecem apenas pelo primeiro nome,
 minimizadas na extração. Pessoas jurídicas mantêm razão social e inscrição
 completas. Metodologia e dados: repositório público da fiscalização.
</footer></body></html>"""
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
<footer><div class="adv">Nada aqui é peça processual sem revisão de advogado —
Artigo 32 da Lei 8.906/1994.</div></footer></body></html>"""
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
