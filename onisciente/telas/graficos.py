"""Gráficos de série para o parecer mensal, em SVG embutido, sem biblioteca nenhuma.

    from ..telas.graficos import series_do_parecer
    secoes.append(series_do_parecer(p.competencia))

Três séries do exercício até a competência, cada barra com a origem na dica (``<title>``) e cada gráfico
com o endereço lido no rodapé:

* **G**: o Município, empenhado, liquidado e pago por mês (matriz de saldos contábeis);
* **F**: o FNAS, o que a União repassou por mês (planilha do FNAS) contra o liquidado na Assistência Social
  (função 08, matriz);
* **S**: a pasta, contratos assinados por mês no PNCP e os indícios de compras do mês.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

from .. import RAIZ
from .base import MESES_CURTOS, abrir, consultar, rotulo_mes

BANCO = RAIZ / "dados" / "onisciente" / "historico.db"
_SOMA = "SUM(CASE WHEN natureza_conta = 'C' THEN valor ELSE -valor END)"

ESTILO = """<style>
.series-onisciente{--s-ink:#0E1C52;--s-ink2:#47557F;--s-line:#D3DAEC;--s-a:#1D4ED8;--s-b:#0E7490;--s-c:#B57C05;--s-d:#E07B00;
  font-family:"IBM Plex Sans",system-ui,sans-serif;color:var(--s-ink);display:grid;gap:18px;margin:18px 0}
@media (prefers-color-scheme:dark){.series-onisciente{--s-ink:#E9EDFB;--s-ink2:#AEB9DD;--s-line:#24346F;--s-a:#7EA4FF;--s-b:#22B8CF;--s-c:#F5B82E;--s-d:#FF9F2E}}
.series-onisciente figure{margin:0;border:1px solid var(--s-line);border-radius:12px;padding:14px 16px}
.series-onisciente figcaption{font-family:"Zilla Slab",Georgia,serif;font-size:18px;font-weight:700;margin-bottom:2px}
.series-onisciente p{margin:2px 0;font-size:12.5px;color:var(--s-ink2)}
.series-onisciente svg{width:100%;height:auto;display:block}
.series-onisciente text{font-size:11px;fill:var(--s-ink2)}
.series-onisciente .eixo{stroke:var(--s-line)}
.series-onisciente .ba{fill:var(--s-a)}.series-onisciente .bb{fill:var(--s-b)}.series-onisciente .bc{fill:var(--s-c)}.series-onisciente .bd{fill:var(--s-d)}
.series-onisciente .leg i{display:inline-block;width:10px;height:10px;border-radius:2px;margin:0 4px 0 10px;vertical-align:-1px}
.series-onisciente a{color:var(--s-a)}
</style>"""


def _moeda(v: float) -> str:
    a = abs(v)
    if a >= 1e9:
        return f"R$ {v / 1e9:.1f} bi".replace(".", ",")
    if a >= 1e6:
        return f"R$ {v / 1e6:.1f} mi".replace(".", ",")
    if a >= 1e4:
        return f"R$ {v / 1e3:.0f} mil"
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def barras(titulo: str, meses: list[str], series: list[tuple[str, str, list[float | None]]], fonte: str,
           url: str = "", formato=_moeda, nota: str = "") -> str:
    """Um gráfico de barras agrupadas por mês. ``series``: (nome, classe ba/bb/bc/bd, valores)."""
    W, H, e, d, t, b = 760, 240, 70, 10, 12, 30
    iw, ih = W - e - d, H - t - b
    maximo = max([v for _, _, vs in series for v in vs if v is not None] + [0]) * 1.08 or 1
    bw = iw / max(len(meses), 1)
    w = bw * 0.78 / max(len(series), 1)
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{escape(titulo)}">']
    for i in range(5):
        v = maximo * i / 4
        y = t + ih - v / maximo * ih
        out.append(f'<line class="eixo" x1="{e}" x2="{W - d}" y1="{y:.1f}" y2="{y:.1f}"/>'
                   f'<text x="{e - 6}" y="{y + 4:.1f}" text-anchor="end">{escape(formato(v))}</text>')
    for i, m in enumerate(meses):
        out.append(f'<text x="{e + bw * i + bw / 2:.1f}" y="{H - 10}" text-anchor="middle">'
                   f'{MESES_CURTOS[int(m[5:]) - 1]}</text>')
    for j, (nome, classe, vs) in enumerate(series):
        for i, v in enumerate(vs):
            if v is None:
                continue
            x = e + bw * i + bw * 0.11 + w * j
            y = t + ih - max(v, 0) / maximo * ih
            out.append(f'<rect class="{classe}" x="{x:.1f}" y="{y:.1f}" width="{max(w - 1.5, 1):.1f}" '
                       f'height="{t + ih - y:.1f}"><title>{escape(nome)}, {escape(rotulo_mes(meses[i]))}: '
                       f'{escape(formato(v))}. Fonte: {escape(fonte)}</title></rect>')
    out.append("</svg>")
    legenda = "".join(f'<i class="{c}" style="background:var(--s-{c[1]})"></i>{escape(n)}' for n, c, _ in series)
    origem = (f'Fonte: <a href="{escape(url)}" rel="noopener">{escape(fonte)}</a>' if url
              else f"Fonte: {escape(fonte)}; o original deste número não está guardado no banco")
    return (f'<figure><figcaption>{escape(titulo)}</figcaption>{"".join(out)}<p class="leg">{legenda}</p>'
            f'<p>{origem}.{(" " + escape(nota)) if nota else ""}</p></figure>')


def _url(con, motor: str, mes: str | None, contem: str = "") -> str:
    sql, args = "SELECT url FROM coletas WHERE ok = 1 AND motor = ? AND alvo LIKE ?", [motor, f"%{contem}%"]
    if mes:
        sql, args = sql + " AND mes = ?", args + [mes]
    linhas = consultar(con, sql + " ORDER BY quando DESC LIMIT 1", tuple(args))
    return linhas[0][0] if linhas else ""


def series_do_parecer(competencia: str, *, banco: Path | str = BANCO) -> str:
    """As séries do exercício até a competência, prontas para entrar no HTML do parecer."""
    if not Path(banco).exists():
        return ""
    con = abrir(banco)
    try:
        ano = competencia[:4]
        meses = [m for (m,) in consultar(con, "SELECT mes FROM msc_meses WHERE situacao = 'entregue' AND mes LIKE ? "
                                              "AND mes <= ? ORDER BY mes", (f"{ano}-%", competencia))]
        if not meses:
            return ""
        exe: dict[str, dict[str, float]] = {m: {} for m in meses}
        liquidado = ("6221303%", "6221304%", "6221307%")
        for chave, prefixos, funcao in (("emp", ("62213%",), None), ("liq", liquidado, None),
                                        ("pago", ("6221304%",), None), ("liq08", liquidado, "08")):
            contas = " OR ".join("conta_contabil LIKE ?" for _ in prefixos)
            sql = (f"SELECT mes, {_SOMA} FROM msc_itens WHERE ({contas}) AND "
                   "substr(natureza_despesa, 3, 2) != '91' AND mes LIKE ? AND mes <= ?")
            args: tuple = (*prefixos, f"{ano}-%", competencia)
            if funcao:
                sql += " AND funcao = ?"
                args += (funcao,)
            for mes, v in consultar(con, sql + " GROUP BY mes", args):
                if mes in exe:
                    exe[mes][chave] = float(v or 0)
        ultimo = meses[-1]
        msc = "Matriz de saldos contábeis do SICONFI (Tesouro Nacional), mês a mês"
        g = barras(f"G. O Município em {ano}: empenhado, liquidado e pago por mês", meses,
                   [("Empenhado", "ba", [exe[m].get("emp") for m in meses]),
                    ("Liquidado", "bb", [exe[m].get("liq") for m in meses]),
                    ("Pago", "bc", [exe[m].get("pago") for m in meses])],
                   msc, _url(con, "msc", ultimo, "classe 6"),
                   nota="Exceto intraorçamentário. O endereço é o da matriz do último mês.")
        repasses = dict(consultar(con, "SELECT substr(competencia, 1, 7), SUM(valor) FROM repasses_fnas "
                                       "WHERE competencia LIKE ? GROUP BY 1", (f"{ano}-%",)))
        f = barras(f"F. O FNAS em {ano}: o que a União repassou e o que a Assistência Social liquidou", meses,
                   [("Repassado pelo FNAS", "bd", [repasses.get(m) for m in meses]),
                    ("Liquidado na função 08", "bb", [exe[m].get("liq08") for m in meses])],
                   f"Planilha de repasses do FNAS de {ano} e matriz de saldos contábeis",
                   _url(con, "fnas", None, f"planilha {ano}"),
                   nota="O liquidado inclui todas as fontes da função 08, não só a do FNAS. Mês sem barra laranja é mês "
                        "sem repasse na planilha lida.")
        from ..conferencias.compras import da_pasta
        contratos: dict[str, list[float]] = {m: [0, 0.0] for m in meses}
        for mes, orgao, valor in consultar(con, "SELECT mes, orgao, valor_global FROM contratos_pncp WHERE mes LIKE ? "
                                                "AND mes <= ?", (f"{ano}-%", competencia)):
            if mes in contratos and da_pasta(orgao or ""):
                contratos[mes][0] += 1
                contratos[mes][1] += float(valor or 0)
        s = barras(f"S. A pasta em {ano}: valor dos contratos assinados por mês", meses,
                   [("Valor contratado", "ba", [contratos[m][1] or None for m in meses])],
                   "PNCP, contratos dos órgãos da Assistência Social",
                   nota="Quantidade no mês: " + ", ".join(f"{MESES_CURTOS[int(m[5:]) - 1]} {int(contratos[m][0])}"
                                                          for m in meses) + ".")
    finally:
        con.close()
    return (f'<section class="series-onisciente" aria-label="Séries do exercício">{ESTILO}'
            f'<h2>As séries de {ano} até {escape(rotulo_mes(competencia))}</h2>{g}{f}{s}</section>')
