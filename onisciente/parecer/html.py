"""O parecer mensal em HTML: um arquivo só, com gráficos próprios, arquivável.

Nove seções: em uma frase, o rio, pisos e tetos, as contas uma a uma, preço e
entrega, prestação de contas, fichas, ausências (com os pedidos de acesso
prontos) e custódia. O que está em ordem foi omitido.
"""

from __future__ import annotations

from datetime import date
from html import escape

from .. import __version__
from ..lai import ESCADA, oficios_por_orgao
from ..nucleo.indicios import Familia, Ficha
from ..nucleo.integridade import PESOS, ROTULOS
from ..nucleo.selos import Selo, Verificacao
from ..panorama import Panorama
from ..rio.fontes import classificar
from . import svg

MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
         "setembro", "outubro", "novembro", "dezembro"]

CSS = """
:root{--tinta:#1F2933;--apagado:#5B6672;--linha:#D7DCE1;--papel:#FBFAF7;--cartao:#FFFFFF;
--verde:#15803D;--azul:#2563EB;--roxo:#7E22CE;--vermelho:#C81E1E;
--critica:#E01B0E;--alta:#E07B00;--media:#A16207}
*{box-sizing:border-box}
body{margin:0;background:var(--papel);color:var(--tinta);
font:16px/1.55 "IBM Plex Sans",system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:860px;margin:0 auto;padding:32px 16px 64px}
h1,h2,h3{font-family:"Zilla Slab",Georgia,serif;line-height:1.2}
h1{font-size:30px;margin:0 0 6px}
h2{font-size:22px;margin:40px 0 12px;padding-top:16px;border-top:1px solid var(--linha)}
h3{font-size:18px;margin:0 0 6px}
.sub{color:var(--apagado);margin:0 0 20px}
.frase{font-size:19px;background:var(--cartao);border:1px solid var(--linha);border-radius:10px;padding:16px 18px}
.omitido{color:var(--apagado);font-style:italic}
.grafico{width:100%;height:auto;display:block;margin:8px 0}
.grafico .t{font-size:13px;fill:#1F2933}.grafico .ts{font-size:11.5px;fill:#5B6672}
.grafico .th{font-size:15px;font-weight:600;fill:#1F2933}
.ficha{background:var(--cartao);border:1px solid var(--linha);border-left:6px solid var(--alta);
border-radius:10px;padding:14px 16px;margin:12px 0}
.ficha.critica{border-left-color:var(--critica)}.ficha.media{border-left-color:var(--media)}
.ficha dl{display:grid;grid-template-columns:150px 1fr;gap:4px 12px;margin:8px 0 0}
.ficha dt{color:var(--apagado);font-size:14px}.ficha dd{margin:0}
.etiqueta{display:inline-block;font-size:12px;font-weight:600;border-radius:999px;padding:1px 9px;
margin-right:6px;color:#fff;vertical-align:middle}
.g-critica{background:var(--critica)}.g-alta{background:var(--alta)}.g-media{background:var(--media)}
.v{background:#EEF1F4;color:var(--tinta)}
.selo{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px;vertical-align:middle}
.s-verde{background:var(--verde)}.s-azul{background:var(--azul)}.s-vermelho{background:var(--vermelho)}
.s-roxo{background:var(--roxo);animation:pulsa 1.6s ease-in-out infinite}
@keyframes pulsa{50%{box-shadow:0 0 0 5px rgba(126,34,206,.18)}}
@media (prefers-reduced-motion:reduce){.s-roxo{animation:none}}
table{width:100%;border-collapse:collapse;font-size:14px;margin:8px 0}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--linha);vertical-align:top}
th{color:var(--apagado);font-weight:600}
td.num{text-align:right;white-space:nowrap}
.tabela{overflow-x:auto}
.ausencia{border-left:4px solid var(--roxo);background:var(--cartao);padding:10px 14px;margin:8px 0;border-radius:8px}
.vermelho{border-left:4px solid var(--vermelho);background:var(--cartao);padding:10px 14px;margin:8px 0;border-radius:8px}
details{margin:10px 0}summary{cursor:pointer;font-weight:600}
pre{white-space:pre-wrap;background:var(--cartao);border:1px solid var(--linha);border-radius:8px;padding:12px;font-size:13px}
.hash{font-family:ui-monospace,Menlo,monospace;font-size:12px;word-break:break-all}
footer{margin-top:48px;color:var(--apagado);font-size:13px}
@media (max-width:600px){.ficha dl{grid-template-columns:1fr}h1{font-size:25px}}
@media print{.s-roxo{animation:none}details{display:block}}
"""


def _mes(competencia: str) -> str:
    ano, mes = competencia.split("-")
    return f"{MESES[int(mes) - 1]} de {ano}"


def _selo(s: Selo | None) -> str:
    if s is None:
        return ""
    return f'<span class="selo s-{s.value}" title="{escape(s.significado)}"></span>'


def _ficha(f: Ficha) -> str:
    g = f.gravidade
    ver = f.verificacao.rotulo
    custodia = ""
    if f.custodia:
        custodia = "<dt>Custódia</dt><dd>" + "<br>".join(
            f'<a href="{escape(o.url)}">{escape(o.url)}</a> · {escape(o.coletado_em)} · '
            f'<span class="hash">{escape(o.sha256)}</span>' for o in f.custodia) + "</dd>"
    extras = ""
    if f.observacao:
        extras = f' <span class="etiqueta v">{escape(f.observacao)}</span>'
    return (
        f'<article class="ficha {g.value}" id="{escape(f.codigo)}">'
        f'<h3><span class="etiqueta g-{g.value}">{g.rotulo}</span>{escape(f.titulo)}</h3>'
        f'<div><span class="etiqueta v">{escape(f.codigo)}</span>'
        f'<span class="etiqueta v">{escape(f.familia.value)}</span>'
        f'<span class="etiqueta v">{ver}</span>{extras}</div>'
        f"<dl>"
        f"<dt>Como deveria ser</dt><dd>{escape(f.como_deveria)}</dd>"
        f"<dt>Como está</dt><dd>{escape(f.como_esta)}</dd>"
        f"<dt>Verificação</dt><dd>{ver}: "
        + {Verificacao.CONFIRMADO: "duas vias oficiais.",
           Verificacao.INDICIARIO: "uma via oficial; não afirma irregularidade sozinha.",
           Verificacao.INCONCLUSIVO: "falta o documento, e a falta também é achado."}[f.verificacao]
        + "</dd>"
        + (f"<dt>Providência</dt><dd>{escape(f.providencia)}</dd>" if f.providencia else "")
        + (f"<dt>Caso semelhante</dt><dd>{escape(f.caso_semelhante)}</dd>" if f.caso_semelhante else "")
        + custodia
        + "</dl></article>"
    )


def _secao_familias(p: Panorama, familias: set[Familia], vazio: str) -> str:
    fichas = [f for f in p.fichas_ordenadas() if f.familia in familias]
    if not fichas:
        return f'<p class="omitido">{escape(vazio)}</p>'
    return "".join(
        f'<p><a href="#{escape(f.codigo)}">{escape(f.titulo)}</a> '
        f'<span class="etiqueta g-{f.gravidade.value}">{f.gravidade.rotulo}</span></p>'
        for f in fichas)


def gerar(p: Panorama, *, hoje: date | None = None) -> str:
    hoje = hoje or date.today()
    titulo = f"Parecer de {_mes(p.competencia)} · {p.dominio}"
    s: list[str] = []
    s.append(f"<h1>{escape(titulo)}</h1>")
    s.append(f'<p class="sub">{escape(p.alvo)} · Onisciente {__version__} · gerado em '
             f"{hoje:%d/%m/%Y}</p>")

    # 1. Em uma frase
    s.append("<h2>1. Em uma frase</h2>")
    s.append(f'<p class="frase">{escape(p.em_uma_frase())}</p>')
    s.append('<p class="omitido">O que está em ordem foi omitido.</p>')
    if p.integridade:
        ind = p.integridade
        s.append(svg.integridade(ind))
        if ind.motivos:
            s.append('<ul class="sub">' + "".join(
                f"<li><strong>{escape(ROTULOS[n])}</strong>: {escape(ind.motivos[n])}.</li>"
                for n in PESOS if n in ind.motivos) + "</ul>")
        if ind.gera_pedido_de_acesso:
            extra = "" if ind.completo else (f" (mesmo se o que ficou sem medida estivesse perfeito, "
                                              f"a nota chegaria a {ind.nota_maxima:g})")
            s.append(f"<p>A nota de integridade ficou abaixo de {ind.minimo:g}{extra}: os pedidos "
                     'de acesso estão prontos na <a href="#ausencias">seção 8</a>.</p>')
        elif ind.nota < ind.minimo:
            s.append(f'<p class="omitido">A nota apurada está abaixo de {ind.minimo:g}, mas depende de '
                     "medida que o sistema não fez; nenhum pedido de acesso sai dela.</p>")
    for n in p.notas:
        s.append(f'<p class="omitido">{escape(n)}</p>')

    # 2. O rio
    s.append("<h2>2. O rio</h2>")
    s.append(svg.rio(p.rio))
    if p.margens:
        m = p.margens
        s.append('<div class="tabela"><table><tr><th>Margem: o que não chegou</th><th>Valor</th></tr>'
                 f'<tr><td>Previsto e não empenhado</td><td class="num">{svg.moeda(m.previsto_nao_empenhado)}</td></tr>'
                 f'<tr><td>Empenhado e não liquidado</td><td class="num">{svg.moeda(m.empenhado_nao_liquidado)}</td></tr>'
                 f'<tr><td>Liquidado e não pago</td><td class="num">{svg.moeda(m.liquidado_nao_pago)}</td></tr>'
                 f'<tr><td>Pago sem vínculo publicado</td><td class="num">{svg.moeda(m.pago_sem_vinculo)}</td></tr>'
                 "</table></div>")
    else:
        s.append('<p class="omitido">As margens (previsto e não empenhado, empenhado e não liquidado, '
                 "liquidado e não pago, pago sem vínculo) dependem da execução publicada, que não "
                 "existe para a competência.</p>")
    for v in p.leitura_falhou:
        s.append(f'<div class="vermelho">{_selo(Selo.VERMELHO)}{escape(v)}</div>')

    # 3. Pisos e tetos
    s.append("<h2>3. Pisos e tetos</h2>")
    if not p.medidas:
        s.append('<p class="omitido">Nenhum piso ou teto medido para este domínio na competência.</p>')
    for m in p.medidas:
        s.append(f"<h3>{_selo(m.selo)}{escape(m.regra.titulo)}</h3>")
        s.append(f'<p class="sub">{escape(m.regra.norma)} · base: {escape(m.regra.base)}</p>')
        s.append(svg.medidor(m))
    if p.fiscal is not None:
        f = p.fiscal
        s.append(f"<h3>O Município: {escape(f.rgf.rotulo if f.rgf else 'sem RGF entregue')}</h3>")
        for m in f.medidas:
            s.append(f"<h3>{_selo(m.selo)}{escape(m.regra.titulo)}</h3>")
            s.append(f'<p class="sub">{escape(m.regra.norma)} · base: {escape(m.regra.base)}</p>')
            s.append(svg.medidor(m))
            if f.memoria.get(m.regra.id):
                s.append(f'<p class="sub">{escape(f.memoria[m.regra.id])}</p>')
        if f.conferencias:
            linhas = "".join(
                f"<tr><td>{_selo(c.selo)}{escape(c.titulo)}</td>"
                + "".join(f'<td class="num">{escape(v.fonte)}<br>{svg.moeda(v.valor)}</td>'
                          for v in c.certificacao.vias[:2])
                + f"<td>{'divergem' if c.certificacao.divergencia else 'iguais'}</td></tr>"
                for c in f.conferencias)
            s.append('<div class="tabela"><table><tr><th>Duas vias</th><th>Via 1</th><th>Via 2</th>'
                     "<th>Resultado</th></tr>" + linhas + "</table></div>")
        for n in f.notas:
            s.append(f'<p class="omitido">{escape(n)}</p>')

    # 4. As contas, uma a uma
    s.append("<h2>4. As contas, uma a uma</h2>")
    if p.rio.afluentes:
        linhas = []
        for a in sorted(p.rio.afluentes, key=lambda a: -a.valor):
            fonte = classificar(a.fonte) if a.fonte else None
            leito = ", ".join(fonte.destinacao.leito) if fonte and fonte.destinacao and fonte.destinacao.leito else "livre"
            if fonte is None:
                leito = "sem fonte declarada"
            linhas.append(f"<tr><td>{_selo(a.selo)}{escape(a.nome)}</td><td>{escape(a.fonte or '—')}</td>"
                          f"<td>{escape(a.esfera.value)}</td><td>{escape(leito)}</td>"
                          f'<td class="num">{svg.moeda(a.valor)}</td></tr>')
        s.append('<div class="tabela"><table><tr><th>Entrada</th><th>Fonte</th><th>Esfera</th>'
                 '<th>Leito (função)</th><th>Previsto no mês</th></tr>' + "".join(linhas) + "</table></div>")
    s.append('<p class="omitido">As saídas, as quatro estações legais e a cronologia evento a evento '
             "aparecem quando a execução da despesa é publicada.</p>")

    # 5. Preço e entrega
    s.append("<h2>5. Preço e entrega</h2>")
    s.append(_secao_familias(p, {Familia.PRC, Familia.ENT},
                             "Nenhum contrato fora da curva com os dados publicados; sem medição e "
                             "liquidação publicadas, preço e entrega não se confrontam."))

    # 6. Prestação de contas
    s.append("<h2>6. Prestação de contas</h2>")
    s.append(_secao_familias(p, {Familia.PCT, Familia.CTA},
                             "Nenhuma prestação de contas publicada para conferir."))

    # 7. Fichas
    s.append("<h2>7. Fichas</h2>")
    fichas = p.fichas_ordenadas()
    if not fichas:
        s.append('<p class="omitido">Nenhum indício na competência.</p>')
    s.extend(_ficha(f) for f in fichas)

    # 8. Ausências
    s.append('<h2 id="ausencias">8. Ausências</h2>')
    if not p.ausencias:
        s.append('<p class="omitido">Nada do que a lei manda publicar está faltando.</p>')
    for a in p.ausencias:
        s.append(f'<div class="ausencia">{_selo(Selo.ROXO)}<strong>{escape(a.o_que_falta)}</strong>'
                 f'{" (" + escape(a.periodo) + ")" if a.periodo else ""}<br>'
                 f"Conferência impedida: {escape(a.conferencia_impedida)}<br>"
                 f"Onde deveria estar: {escape(a.onde_deveria_estar)}<br>"
                 f'<span class="sub">{escape(a.fundamento)}</span></div>')
    if p.ausencias:
        for o in oficios_por_orgao(p.ausencias, f"Documentos não publicados: {p.dominio}, "
                                                 f"{_mes(p.competencia)}"):
            s.append(f"<details><summary>Pedido de acesso pronto para {escape(o.destinatario)} "
                     f"({len(o.itens)} itens)</summary><pre>{escape(o.texto(hoje=hoje))}</pre>"
                     "<p class=\"omitido\">O protocolo e o envio ficam com quem assina.</p></details>")
        s.append("<details><summary>A escada contra a não resposta</summary><ol>" + "".join(
            f"<li><strong>{escape(d.nome)}</strong> ({escape(d.fundamento)})"
            + (f": {escape(d.observacao)}" if d.observacao else "") + "</li>" for d in ESCADA)
            + "</ol></details>")

    # 9. Custódia
    s.append("<h2>9. Custódia</h2>")
    if not p.custodia:
        s.append('<p class="omitido">Nenhum original do Diário Oficial na competência.</p>')
    else:
        s.append('<div class="tabela"><table><tr><th>Original</th><th>Página</th><th>Coletado</th>'
                 "<th>Impressão digital</th></tr>" + "".join(
                     f'<tr><td><a href="{escape(o.url)}">{escape(o.edicao or o.url)}</a></td>'
                     f"<td>{o.pagina or ''}</td><td>{escape(o.coletado_em)}</td>"
                     f'<td class="hash">{escape(o.sha256)}</td></tr>' for o in p.custodia)
                 + "</table></div>")

    s.append("<footer>É uma trilha e não um cartório. Cada número traz a fonte e o selo: "
             f"{_selo(Selo.VERDE)}duas vias {_selo(Selo.AZUL)}uma via "
             f"{_selo(Selo.ROXO)}não publicado {_selo(Selo.VERMELHO)}leitura não alcançou. "
             "A ficha afirma só o que os níveis de prova permitem; o sistema nunca imputa crime.</footer>")

    return ("<!doctype html><html lang=\"pt-BR\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{escape(titulo)}</title><style>{CSS}</style></head><body><main>"
            + "".join(s) + "</main></body></html>")


def indice(pareceres: list[tuple[str, str]], alvo: str, *, banco: bool = False) -> str:
    """Página que lista os pareceres publicados: [(competência, arquivo)].

    Com ``banco``, liga também a página do banco histórico (docs/onisciente/banco/).
    """
    itens = "".join(f'<li><a href="{escape(arq)}">{escape(_mes(c).capitalize())}</a></li>'
                    for c, arq in sorted(pareceres, reverse=True))
    ligacao = ("<h2>Banco histórico</h2><ul><li><a href=\"banco/index.html\">Banco de teste da "
               "coleta dos últimos dois anos</a></li></ul>") if banco else ""
    return ("<!doctype html><html lang=\"pt-BR\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>Onisciente</title><style>{CSS}</style></head><body><main>"
            f"<h1>Onisciente</h1><p class=\"sub\">{escape(alvo)} · a trilha do dinheiro público</p>"
            f"<h2>Pareceres mensais</h2><ul>{itens or '<li>Nenhum parecer ainda.</li>'}</ul>"
            f"{ligacao}</main></body></html>")
