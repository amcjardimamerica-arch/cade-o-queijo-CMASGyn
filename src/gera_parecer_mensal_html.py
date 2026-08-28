#!/usr/bin/env python3
"""Parecer mensal em HTML único — funde fluxograma do dinheiro e trilha
didática no recorte da competência, com técnicas de visual law.

Camadas visuais, na ordem de leitura:
  1. resumo em uma frase e placar de severidade;
  2. linha do exercício — série janeiro–julho com o mês em destaque;
  3. de onde veio — pizza das fontes previstas do mês, com valores;
  4. por onde passou — fluxo com setas proporcionais e ponto de ruptura;
  5. calendário de circulação do Diário Oficial;
  6. cronologia — a trilha do dinheiro do mês, evento a evento;
  7. demonstração de dados — IGD da competência e entidades citadas;
  8. fichas de desconformidade em três camadas;
  9. condições estruturais e advertência do Artigo 32 da Lei 8.906/1994.

Autossuficiente: sem fonte externa, sem script, imprime bem em A4.
Pessoa jurídica com razão social e inscrição completas; pessoa física,
se ocorrer, já chega minimizada da extração (primeiro nome).

Uso: python3 src/gera_parecer_mensal_html.py 2026-01
"""
from __future__ import annotations
import json, math, re, sys
from datetime import date, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DADOS = RAIZ / "dados"
REL = RAIZ / "relatorios" / "mensal"
DOCS = RAIZ / "docs" / "mensal"

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

CSS = """
:root{--tinta:#1c1b1f;--papel:#faf8f5;--linha:#d8d2c8;--rubrica:#8c1d18;--suave:#6b6660}
*{box-sizing:border-box;margin:0;padding:0}
body{font:16px/1.55 Georgia,'Times New Roman',serif;color:var(--tinta);
background:var(--papel);max-width:920px;margin:0 auto;padding:28px 22px 60px}
header.peca{border-bottom:3px double var(--tinta);padding-bottom:14px;margin-bottom:22px}
.orgao{font:700 12px/1.4 Arial,sans-serif;letter-spacing:.14em;text-transform:uppercase;color:var(--suave)}
h1{font:400 30px/1.2 Georgia,serif;margin:6px 0 2px}
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
border-bottom:1px solid var(--linha);padding-bottom:6px;margin:34px 0 14px}
.explica{font:13px/1.6 Arial,sans-serif;color:var(--suave);margin:-6px 0 12px}
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
.ev .val{font:700 14px/1.4 Arial,sans-serif;float:right}
tabela,table{border-collapse:collapse;width:100%;font:13px/1.5 Arial,sans-serif;background:#fff}
th{font:700 10px/1.4 Arial,sans-serif;letter-spacing:.1em;text-transform:uppercase;
color:var(--suave);text-align:left;border-bottom:2px solid var(--tinta);padding:7px 9px}
td{border-bottom:1px solid var(--linha);padding:7px 9px;vertical-align:top}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
tr.ruim td{background:#faf1f0}
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
a{color:#3a5f8a}
@media print{body{background:#fff}.ficha,.ev{box-shadow:none}}
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


def fmt(v, sinal=True):
    if v is None:
        return "—"
    s = "R$ " if sinal else ""
    return s + "{:,.2f}".format(v).replace(",", "X").replace(".", ",").replace("X", ".")


def carrega(nome):
    return json.loads((DADOS / nome).read_text(encoding="utf-8"))


# ------------------------------------------------------------------ camadas
def pizza_svg(itens, tot_rot="previsto"):
    """Pizza estática em SVG puro — porte da função do fluxograma anual."""
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
        partes.append(f'<path d="M{cx},{cy} L{x1:.1f},{y1:.1f} '
                      f'A{R},{R} 0 {gr},1 {x2:.1f},{y2:.1f} Z" fill="{cor}" '
                      f'stroke="#fff" stroke-width="2"/>')
        p = 100 * val / tot
        if p > 4.5:
            am = (ang + a2) / 2
            lx, ly = cx + R * .66 * math.cos(am), cy + R * .66 * math.sin(am)
            partes.append(f'<text x="{lx:.0f}" y="{ly:.0f}" text-anchor="middle" '
                          f'style="font:700 12px Arial;fill:#fff">{p:.0f}%</text>')
        ang = a2
    partes.append(
        f'<circle cx="{cx}" cy="{cy}" r="46" fill="#faf8f5"/>'
        f'<text x="{cx}" y="{cy-4}" text-anchor="middle" '
        f'style="font:11px Georgia;fill:#6b6660">{tot_rot}</text>'
        f'<text x="{cx}" y="{cy+14}" text-anchor="middle" '
        f'style="font:700 12px Arial">{fmt(tot)}</text>')
    return ('<svg viewBox="0 0 300 300" role="img" '
            'aria-label="composição por fonte">' + "".join(partes) + "</svg>")


def linha_exercicio_svg(trilha, comp):
    """Série janeiro–julho: eventos publicados e empenhos por mês, com o mês
    do parecer em destaque — devolve a linha do tempo do exercício."""
    meses = [f"2026-{m:02d}" for m in range(1, 8)]
    evs = {m: [e for e in trilha["detalhe"]
               if str(e.get("data", "")).startswith(m)] for m in meses}
    serie_ev = [len(evs[m]) for m in meses]
    serie_emp = [sum(1 for e in evs[m] if "empenho" in (e.get("estacoes") or []))
                 for m in meses]
    serie_pag = [sum(1 for e in evs[m]
                     if {"liquidacao", "pagamento"} & set(e.get("estacoes") or []))
                 for m in meses]
    W, H, PAD = 860, 210, 42
    maxv = max(serie_ev + [1])

    def xy(i, v):
        x = PAD + i * (W - 2 * PAD) / (len(meses) - 1)
        y = H - PAD - v * (H - 2 * PAD) / maxv
        return x, y

    def poli(serie, cor, largura, traco=""):
        pts = " ".join(f"{xy(i, v)[0]:.0f},{xy(i, v)[1]:.0f}"
                       for i, v in enumerate(serie))
        return (f'<polyline points="{pts}" fill="none" stroke="{cor}" '
                f'stroke-width="{largura}" {traco}/>')

    g = ['<svg viewBox="0 0 860 210" role="img" '
         'aria-label="linha do exercício, eventos por mês">']
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
        g.append(f'<circle cx="{xe:.0f}" cy="{ye:.0f}" r="{5 if i==idx else 3}" '
                 f'fill="#3a5f8a"/>')
    g.append('</svg>')
    legenda = ('<p class="legenda"><i style="background:#3a5f8a"></i>eventos '
               'publicados na trilha<i style="background:#a85b00"></i>com '
               'estação de empenho<i style="background:#8c1d18"></i>com '
               'liquidação ou pagamento — a linha vermelha rente ao zero nos '
               'sete meses é o achado central do exercício</p>')
    return "".join(g) + legenda


def fluxo_svg(previsto_total, est):
    """Fluxo do mês: Fundo → estações da despesa, seta com espessura
    proporcional aos eventos; ruptura tracejada em vermelho onde zera."""
    ordem = [("dotacao", "Dotação"), ("empenho", "Empenho"),
             ("liquidacao", "Liquidação"), ("pagamento", "Pagamento")]
    maxn = max([est.get(k, 0) for k, _ in ordem] + [1])
    W = 860
    g = [f'<svg viewBox="0 0 {W} 190" role="img" aria-label="fluxo do mês">']
    g.append(f'<rect x="10" y="60" width="150" height="70" rx="8" fill="#3a5f8a"/>'
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
        tracejo = '' if n else ' stroke-dasharray="7 6"'
        g.append(f'<line x1="{x0}" y1="95" x2="{x1}" y2="95" stroke="{cor}" '
                 f'stroke-width="{esp:.0f}"{tracejo}/>'
                 f'<polygon points="{x1},95 {x1-11},89 {x1-11},101" fill="{cor}"/>')
        boxc = "#fff" if n else "#faf1f0"
        borda = "#d8d2c8" if n else "#8c1d18"
        g.append(f'<rect x="{x1}" y="60" width="130" height="70" rx="8" '
                 f'fill="{boxc}" stroke="{borda}" stroke-width="2"/>'
                 f'<text x="{x1+65}" y="88" text-anchor="middle" '
                 f'style="font:700 13px Arial">{rot}</text>'
                 f'<text x="{x1+65}" y="110" text-anchor="middle" '
                 f'style="font:700 17px Arial;fill:{"#1c1b1f" if n else "#8c1d18"}">'
                 f'{n}</text>')
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
        celulas.append(f'<span class="dia {cls}" title="{iso}">{d.day}</span>')
        d += timedelta(days=1)
    return ('<div class="calendario">' + "".join(celulas) + "</div>"
            '<p class="legenda">cada quadrado é um dia do mês —'
            '<i style="background:#1d4f2b"></i>edição localizada'
            '<i style="background:#8c1d18"></i>dia útil sem edição'
            '<i style="background:#e6e1d8"></i>fim de semana ou feriado</p>')


def cronologia_html(evs, mapa_ent):
    if not evs:
        return ('<p class="explica">Nenhum evento publicado na competência — '
                'a ausência é, ela própria, o achado EXE-M do mês.</p>')
    linhas = []
    for e in sorted(evs, key=lambda x: (x.get("data", ""), x.get("pagina", 0))):
        ests = e.get("estacoes") or []
        cor = COR_EST.get(ests[0], "#8a8a94") if ests else "#8a8a94"
        chips = "".join(f'<span class="chip" style="background:'
                        f'{COR_EST.get(s, "#8a8a94")}">{s}</span>' for s in ests)
        val = max(e.get("valores") or [0])
        ents = ""
        if e.get("cnpjs"):
            nomes = []
            for c in e["cnpjs"][:4]:
                razao = mapa_ent.get(c)
                nomes.append(f"{c} — {razao}" if razao else c)
            ents = ('<div class="ent"><b>Pessoas jurídicas citadas:</b> '
                    + "; ".join(nomes) + "</div>")
        ed = e.get("edicao", "—")
        url = e.get("url")
        ed_html = f'<a href="{url}">{ed}</a>' if url else ed
        linhas.append(
            f'<div class="ev" style="--pt:{cor}">'
            f'{f"<span class=\"val\">{fmt(val)}</span>" if val else ""}'
            f'<div class="qd"><b>{e.get("data", "—")}</b> · edição {ed_html} '
            f'· página {e.get("pagina", "—")}</div>{chips}{ents}</div>')
    return ('<p class="explica">Cada ponto é uma publicação do Diário Oficial '
            'que toca dinheiro da assistência social; a cor marca a estação '
            'alcançada e o valor à direita é o maior citado no trecho.</p>'
            '<div class="crono">' + "".join(linhas) + "</div>")


def tabelas_dados_html(comp_receita, evs, mapa_ent):
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
          'a competência; aplicar sobre o acumulado do ano não satisfaz a '
          'norma.</p>')
    por_ent = {}
    for e in evs:
        for c in e.get("cnpjs") or []:
            r = por_ent.setdefault(c, {"n": 0, "v": 0.0})
            r["n"] += 1
            r["v"] = max(r["v"], max(e.get("valores") or [0]))
    if por_ent:
        ordenado = sorted(por_ent.items(), key=lambda kv: -kv[1]["v"])
        linhas = "".join(
            f'<tr><td>{c}</td>'
            f'<td>{mapa_ent.get(c, "razão social não localizada no cadastro nacional")}</td>'
            f'<td class="num">{r["n"]}</td>'
            f'<td class="num">{fmt(r["v"])}</td></tr>'
            for c, r in ordenado)
        t2 = ('<table><tr><th>Inscrição (CNPJ)</th><th>Razão social</th>'
              '<th class="num">Menções</th><th class="num">Maior valor no '
              'trecho</th></tr>' + linhas + '</table>'
              '<p class="legenda">Valor "no trecho" é o maior citado na '
              'vizinhança da menção — associação textual, não liquidação: '
              'indício de vínculo, não prova de pagamento.</p>')
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
  <span class="badge" style="background:{sev}">{ROTULO_SEV[a["severidade"]]}</span>
  <span class="badge" style="background:{selo}">{ROTULO_SELO[a["selo"]]}</span>
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
    dest = carrega("destinatarios_2026.json")
    mapa_ent = {d["cnpj"]: d.get("razao_social") for d in dest["destinatarios"]}
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
        f'<div style="--cor:{COR_SEV[s]}"><div class="n">{sev.get(s, 0)}</div>'
        f'<div class="t">{ROTULO_SEV[s]}</div></div>'
        for s in ("critica", "alta", "media")) + (
        f'<div style="--cor:#4a4a58"><div class="n">'
        f'{v["por_selo"].get("INCONCLUSIVO_POR_DOCUMENTO_FALTANTE", 0)}</div>'
        f'<div class="t">Documento faltante</div></div>')

    itens_pizza, leg = [], []
    if comp_rec:
        for f, val in sorted(comp_rec["previsto_por_fonte"].items(),
                             key=lambda kv: -kv[1]):
            cor = COR_FONTE.get(f, "#8a8a94")
            itens_pizza.append((f, val, cor))
            leg.append(f'<div><i style="background:{cor}"></i>'
                       f'{NOME_FONTE.get(f, f)}<b class="v">{fmt(val)}</b></div>')
    pizza = pizza_svg(itens_pizza) if itens_pizza else ""
    legenda_pizza = ('<div class="leg">' + "".join(leg) +
                     '<p class="legenda" style="margin-top:10px">A fatia '
                     'vermelha do Tesouro — R$ 750,00 mensais — é a expressão '
                     'mensal da queda de 99,46% do aporte próprio.</p></div>')

    t_igd, t_ent = tabelas_dados_html(comp_rec, evs, mapa_ent)
    fichas = "".join(ficha_html(a) for a in v["achados"])
    estruturais = "".join(f"<li><b>{t}</b> — {d}</li>" for t, d in ESTRUTURAIS)

    html = f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Parecer mensal — {v["mes"]} de {v["exercicio"]}</title>
<style>{CSS}</style></head><body>
<header class="peca">
 <div class="orgao">Vigilância da assistência social — Município de Goiânia<br>
 trilhas separadas: SEMASDH (execução) · CMASGyn (controle social)</div>
 <h1>Parecer de fiscalização — <b>{v["mes"]} de {v["exercicio"]}</b></h1>
 <div class="orgao">competência {comp} · gerado em {v["gerado_em"]} · camada de IA: {v["camada_ia"]}</div>
</header>
<div class="uma-frase"><small>Em uma frase</small>{frase}</div>
<div class="placar">{placar}</div>

<h2>Linha do exercício — o mês no contexto de janeiro a julho</h2>
<p class="explica">O que foi publicado mês a mês na trilha do dinheiro; a
faixa sombreada é a competência deste parecer.</p>
{linha_exercicio_svg(trilha, comp)}

<h2>Estágio 1 · De onde veio — fontes previstas da competência</h2>
<div class="grade2"><div>{pizza}</div>{legenda_pizza}</div>

<h2>Estágio 2 · Por onde passou — as quatro estações legais no mês</h2>
{fluxo_svg(comp_rec["previsto_total"] if comp_rec else None,
           v["execucao_do_mes"]["por_estacao"])}

<h2>▤ O Diário Oficial no mês</h2>
{calendario_html(comp, pub)}

<h2>⇢ Cronologia — a trilha do dinheiro no mês, evento a evento</h2>
{cronologia_html(evs, mapa_ent)}

<h2>Demonstração de dados · piso do IGD na competência</h2>
{t_igd}

<h2>Demonstração de dados · pessoas jurídicas citadas no mês</h2>
{t_ent}

<h2>Fichas de desconformidade</h2>
{fichas}

<h2>Condições estruturais que perduram na competência</h2>
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
<header class="peca"><div class="orgao">Vigilância da assistência social —
Município de Goiânia</div><h1>Pareceres <b>mensais</b> — 2026</h1></header>
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
