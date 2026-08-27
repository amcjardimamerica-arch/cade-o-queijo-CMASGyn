#!/usr/bin/env python3
"""Parecer mensal em HTML único — funde o conteúdo dos dois HTML do ciclo
(fluxograma do dinheiro e trilha didática) em uma peça por competência,
com técnicas de visual law:

  - resumo em uma frase no topo, antes de qualquer tecnicismo;
  - semáforo de severidade e selos de prova como distintivos visuais;
  - linha do tempo dos dias úteis do mês (publicou / não circulou);
  - fluxo do dinheiro do mês com barras proporcionais por estação;
  - cada achado em ficha de três camadas: o que se apurou, por que importa,
    o que falta — da mais simples para a mais técnica;
  - norma sempre por extenso, no rodapé da ficha, nunca no meio do texto;
  - advertência do Artigo 32 da Lei 8.906/1994 em faixa própria.

Autossuficiente: sem fonte externa, sem script externo, imprime bem em A4.

Uso: python3 src/gera_parecer_mensal_html.py 2026-01
Lê : relatorios/mensal/verificacao_AAAA-MM.json
Grava: docs/mensal/parecer_AAAA-MM.html (+ docs/mensal/index.html)
"""
from __future__ import annotations
import json, re, sys
from datetime import date, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
REL = RAIZ / "relatorios" / "mensal"
DOCS = RAIZ / "docs" / "mensal"

COR_SEV = {"critica": "#8c1d18", "alta": "#a85b00", "media": "#5c5c00"}
ROTULO_SEV = {"critica": "CRÍTICA", "alta": "ALTA", "media": "MÉDIA"}
COR_SELO = {"CONFIRMADO": "#1d4f2b",
            "INDICIARIO": "#6a4a00",
            "INCONCLUSIVO_POR_DOCUMENTO_FALTANTE": "#4a4a58"}
ROTULO_SELO = {"CONFIRMADO": "CONFIRMADO — duas vias independentes",
               "INDICIARIO": "INDICIÁRIO — uma via",
               "INCONCLUSIVO_POR_DOCUMENTO_FALTANTE":
               "INCONCLUSIVO — documento faltante"}
ICONE = {"REC": "◔", "IGD": "▣", "PUB": "▤", "EXE": "⇢", "CMAS": "◈"}

CSS = """
:root{--tinta:#1c1b1f;--papel:#faf8f5;--linha:#d8d2c8;--rubrica:#8c1d18;
--fundo-ficha:#fff;--suave:#6b6660}
*{box-sizing:border-box;margin:0;padding:0}
body{font:16px/1.55 Georgia,'Times New Roman',serif;color:var(--tinta);
background:var(--papel);max-width:880px;margin:0 auto;padding:28px 22px 60px}
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
.calendario{display:grid;grid-template-columns:repeat(auto-fill,minmax(30px,1fr));gap:4px}
.dia{aspect-ratio:1;display:flex;align-items:center;justify-content:center;
font:700 11px/1 Arial,sans-serif;border-radius:4px;color:#fff}
.dia.pub{background:#1d4f2b}.dia.nao{background:#8c1d18}
.dia.fds{background:#e6e1d8;color:#a09a90}
.legenda{font:12px/1.6 Arial,sans-serif;color:var(--suave);margin-top:8px}
.legenda i{display:inline-block;width:11px;height:11px;border-radius:3px;
vertical-align:-1px;margin:0 4px 0 12px}
.estacoes{display:flex;flex-direction:column;gap:8px;margin:10px 0}
.est{display:grid;grid-template-columns:110px 1fr 60px;gap:10px;align-items:center;
font:13px/1.3 Arial,sans-serif}
.est .barra{height:20px;background:#e6e1d8;border-radius:3px;overflow:hidden}
.est .barra i{display:block;height:100%;background:#3a5f8a}
.est.morta .barra i{background:#8c1d18}
.seta-quebra{font:14px/1.5 Arial,sans-serif;color:var(--rubrica);margin:6px 0 0;font-weight:700}
.ficha{background:var(--fundo-ficha);border:1px solid var(--linha);border-radius:6px;
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
@media print{body{background:#fff}.ficha{box-shadow:none}}
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
     "A ação 3650.0824401082.591 existe com R$ 256.000; nenhum empenho "
     "a débito dela foi localizado em edição alguma do exercício."),
]


def fmt(v):
    if v is None:
        return "—"
    return ("R$ {:,.2f}".format(v).replace(",", "X")
            .replace(".", ",").replace("X", "."))


def calendario_html(comp, dados_pub):
    ano, mes = int(comp[:4]), int(comp[5:7])
    d = date(ano, mes, 1)
    dias_sem = set(dados_pub.get("dias_uteis_sem_edicao", []))
    celulas = []
    while d.month == mes:
        iso = d.isoformat()
        if d.weekday() >= 5:
            cls = "fds"
        elif iso in dias_sem:
            cls = "nao"
        else:
            cls = "pub"
        celulas.append(f'<span class="dia {cls}" title="{iso}">{d.day}</span>')
        d += timedelta(days=1)
    return ('<div class="calendario">' + "".join(celulas) + "</div>"
            '<p class="legenda">cada quadrado é um dia do mês —'
            '<i style="background:#1d4f2b"></i>edição localizada'
            '<i style="background:#8c1d18"></i>dia útil sem edição'
            '<i style="background:#e6e1d8"></i>fim de semana ou feriado</p>')


def fluxo_html(exec_mes):
    est = exec_mes.get("por_estacao", {})
    ordem = [("dotacao", "Dotação"), ("empenho", "Empenho"),
             ("liquidacao", "Liquidação"), ("pagamento", "Pagamento")]
    maximo = max([est.get(k, 0) for k, _ in ordem] + [1])
    linhas = []
    for k, rot in ordem:
        n = est.get(k, 0)
        pct = round(100 * n / maximo)
        morta = " morta" if n == 0 else ""
        linhas.append(
            f'<div class="est{morta}"><span>{rot}</span>'
            f'<span class="barra"><i style="width:{max(pct, 2)}%"></i></span>'
            f'<b>{n}</b></div>')
    quebra = ""
    if est.get("empenho", 0) > 0 and est.get("liquidacao", 0) == 0:
        quebra = ('<p class="seta-quebra">⚠ A trilha se interrompe entre o '
                  'empenho e a liquidação: o dinheiro some do papel neste '
                  'ponto. Dotação e empenho não comprovam saída de dinheiro.</p>')
    return ('<div class="estacoes">' + "".join(linhas) + "</div>" + quebra +
            '<p class="legenda">barras proporcionais ao número de eventos '
            'publicados no mês em cada estágio da despesa — Artigo 62, '
            'Artigo 63 e Artigo 64 da Lei 4.320/1964</p>')


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
<h2>▤ O Diário Oficial no mês</h2>
{calendario_html(comp, pub)}
<h2>⇢ O caminho do dinheiro no mês</h2>
{fluxo_html(v["execucao_do_mes"])}
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
