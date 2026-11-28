"""O parecer mensal em HTML: um arquivo só, com gráficos próprios, arquivável.

Nove seções: em uma frase, o rio, pisos e tetos, as contas uma a uma, preço e
entrega, prestação de contas, fichas, ausências (com os pedidos de acesso
prontos) e custódia. O que está em ordem foi omitido.
"""

from __future__ import annotations

import re
from datetime import date
from html import escape
from typing import Callable

from .. import __version__
from ..lai import ESCADA, acompanhar, carregar_registro, oficios_por_orgao
from ..nucleo.indicios import Familia, Ficha
from ..nucleo.integridade import PESOS, ROTULOS
from ..nucleo.selos import Selo, Verificacao, Via, selar
from ..panorama import Panorama
from ..rio.fontes import classificar
from ..rio.municipio import RioMunicipal, Tipo
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
.painel a{display:inline-block;padding:10px 16px;border-radius:10px;background:var(--azul);color:#fff;font-weight:600;text-decoration:none}
.grafico{width:100%;height:auto;display:block;margin:8px 0}
.grafico .t{font-size:13px;fill:#1F2933}.grafico .ts{font-size:11.5px;fill:#5B6672}
.grafico .th{font-size:15px;font-weight:600;fill:#1F2933}
.ficha{background:var(--cartao);border:1px solid var(--linha);border-left:6px solid var(--alta);
border-radius:10px;padding:14px 16px;margin:12px 0}
.ficha-selo{background:var(--cartao);border:1px solid var(--linha);border-left:6px solid var(--alta);
border-radius:10px;padding:14px 16px;margin:12px 0}
.ficha.critica,.ficha-selo.critica{border-left-color:var(--critica)}
.ficha.media,.ficha-selo.media{border-left-color:var(--media)}
.ficha dl,.ficha-selo dl{display:grid;grid-template-columns:150px 1fr;gap:4px 12px;margin:8px 0 0}
.ficha dt,.ficha-selo dt{color:var(--apagado);font-size:14px}.ficha dd,.ficha-selo dd{margin:0}
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
@media (max-width:600px){.ficha dl,.ficha-selo dl{grid-template-columns:1fr}h1{font-size:25px}}
@media print{.s-roxo{animation:none}details{display:block}}
"""


# Ponto de extensão: seções de módulos externos (por exemplo, a conferência de empresas da Receita
# Federal). Cada função recebe o panorama da competência e a data do parecer e devolve HTML pronto
# (já escapado), que entra depois da seção 9, na ordem do registro. A função não deve usar a classe
# "ficha" (as fichas ficam só na seção 7) nem carregar scripts ou folhas de estilo externas.
SECOES_EXTERNAS: list[Callable[[Panorama, date], str]] = []


def registrar_secao(fn: Callable[[Panorama, date], str]) -> Callable[[Panorama, date], str]:
    """Registra uma seção externa no parecer (pode ser usada como decorador). Idempotente."""
    if fn not in SECOES_EXTERNAS:
        SECOES_EXTERNAS.append(fn)
    return fn


TOLERANCIA_RIO_RREO = 0.01   # o rio contra a receita realizada do RREO: até 1% (requisito 162)


def _numerico(v) -> bool:
    s = str(v)
    return s.startswith(("R$", "-R$")) or s.endswith("%") or s.replace(".", "").replace(",", "").isdigit()


def _original(o) -> str:
    if o is None:
        return '<td class="sub">sem original no banco</td>'
    return (f'<td><a href="{escape(o.url)}">{escape(o.fonte or o.url)}</a><br>'
            f'<span class="sub">{escape(o.coletado_em)}</span> '
            f'<span class="hash" title="{escape(o.sha256)}">{escape(o.sha256[:16])}</span></td>')


def _quadro(q) -> str:
    """Um quadro das conferências do banco: cada linha com o selo e o original de onde saiu."""
    cab = "".join(f"<th>{escape(c)}</th>" for c in q.colunas) + "<th>Original</th>"
    linhas = "".join(
        f"<tr><td>{_selo(x.selo)}{escape(x.rotulo)}</td>"
        + "".join(f'<td{" class=\"num\"" if _numerico(v) else ""}>{escape(str(v))}</td>' for v in x.valores)
        + _original(x.original) + "</tr>" for x in q.linhas)
    partes = [f"<h3>{escape(q.titulo)}</h3>", f'<p class="sub">{escape(q.explica)}</p>',
              f'<div class="tabela"><table><tr>{cab}</tr>{linhas}</table></div>']
    if q.regra:
        partes.append(f'<p class="sub">Limiar: {escape(q.regra)}</p>')
    partes += [f'<p class="omitido">{escape(n)}</p>' for n in q.notas]
    return "".join(partes)


def _quadros(p: Panorama, secao: int) -> list[str]:
    if p.auditoria is None:
        return []
    return [_quadro(q) for q in p.auditoria.da_secao(secao)]


def _federais(p: Panorama) -> list[str]:
    """As fontes federais e estaduais: cada conferência com as vias e o selo."""
    fed = p.federais
    if fed is None or not fed.conferencias:
        return []
    linhas = "".join(
        f"<tr><td>{_selo(c.certificacao.selo)}{escape(c.titulo)}<br><span class=\"sub\">{escape(c.referencia)}</span></td>"
        + "".join(f'<td class="num">{escape(v.fonte)}<br>{svg.moeda(v.valor)}</td>' for v in c.certificacao.vias[:3])
        + "".join("<td></td>" for _ in range(3 - len(c.certificacao.vias[:3])))
        + f"<td>{'divergem' if c.certificacao.divergencia else 'iguais' if len(c.certificacao.vias) > 1 else 'uma via'}</td></tr>"
        for c in fed.conferencias)
    return ["<h3>Fontes federais e estaduais: as vias de cada repasse</h3>",
            '<p class="sub">O que a União e o Estado dizem ter entregue contra o que o Município registrou '
            "(FNS, FNDE, Transferegov, cota estadual). Alerta é indício, não acusação.</p>",
            '<div class="tabela"><table><tr><th>Conferência</th><th>Via 1</th><th>Via 2</th><th>Via 3</th>'
            "<th>Resultado</th></tr>" + linhas + "</table></div>"]


def _rotulo_do_valor(p: Panorama) -> str:
    """O cabeçalho da coluna de valor segue a origem dos afluentes: previsto, realizado ou pago."""
    origens = " ".join(a.origem.lower() for a in p.rio.afluentes)
    if origens.startswith("pago") or " pago no" in origens:
        return "Pago no exercício"
    if "realizad" in origens:
        return "Realizado no exercício"
    return "Previsto no mês"


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


def _secao_compras(p: Panorama) -> str:
    """As compras e os contratos: o que fechou e o que não fechou, na pasta e no Município."""
    from ..conferencias.compras import TITULOS
    c = p.compras
    s = []
    da_pasta = c.da_competencia(p.competencia)
    cont = {t: sum(1 for a in da_pasta if a.tipo == t) for t in TITULOS}
    linhas = "".join(f"<tr><td>{escape(TITULOS[t])}</td><td class=\"num\">{n}</td></tr>" for t, n in cont.items())
    s.append('<p>As compras e os contratos publicados no PNCP pelos órgãos da pasta, conferidos nos últimos '
             "12 meses até a competência (Lei 14.133/2021, arts. 23, 75 e 125; Lei 4.320/1964, art. 63).</p>")
    s.append('<div class="tabela"><table><tr><th>Conferência</th><th>Achados da pasta</th></tr>'
             + linhas + "</table></div>")
    orgaos = c.por_orgao()[:10]
    if orgaos:
        s.append('<details><summary>O Município inteiro: os órgãos com mais achados nos dois anos</summary>'
                 '<div class="tabela"><table><tr><th>Órgão</th><th>Achados</th><th>Valor em jogo</th></tr>'
                 + "".join(f"<tr><td>{_selo(Selo.AZUL)}{escape(o.title())}</td><td class=\"num\">{n}</td>"
                           f'<td class="num">{svg.moeda(v)}</td></tr>' for o, n, v in orgaos)
                 + "</table></div></details>")
    cob = c.cobertura
    if cob.get("compras"):
        s.append(f'<p class="omitido">Base: {cob["compras"]} compras e {cob.get("contratos", 0)} contratos do '
                 f'Município; amparo legal lido em {cob.get("amparo_lido", 0)} de '
                 f'{cob.get("dispensas_e_inexigibilidades", 0)} dispensas e inexigibilidades; '
                 f'{cob.get("contratos_com_detalhe", 0)} contratos com valor inicial e vigência; '
                 f'{cob.get("termos", 0)} termos aditivos; {cob.get("itens_comparados_com_o_pais", 0)} itens '
                 f'comparados com o preço do país ({cob.get("servicos_contratados_por_lote", 0)} serviços '
                 f'contratados por lote e {cob.get("itens_com_unidade_incompativel", 0)} itens com unidade '
                 f'diferente da referência ficam fora da comparação); {cob.get("notas_fiscais", 0)} notas '
                 f'fiscais publicadas; {cob.get("orgaos_sem_nota_fiscal_publicada", 0)} órgãos sem nenhuma '
                 f'nota fiscal nos meses lidos.</p>')
    for lacuna in cob.get("lacunas_da_pasta") or []:
        s.append(f'<p class="omitido">{_selo(Selo.VERMELHO)}Falta no banco: {escape(lacuna)}.</p>')
    return "".join(s)


def _secao_familias(p: Panorama, familias: set[Familia], vazio: str) -> str:
    fichas = [f for f in p.fichas_ordenadas() if f.familia in familias]
    if not fichas:
        return f'<p class="omitido">{escape(vazio)}</p>'
    return "".join(
        f'<p><a href="#{escape(f.codigo)}">{escape(f.titulo)}</a> '
        f'<span class="etiqueta g-{f.gravidade.value}">{f.gravidade.rotulo}</span></p>'
        for f in fichas)


_TEMA_ESCURO_DAS_TELAS = re.compile(r"@media \(prefers-color-scheme:dark\)\{[^{}]*\{[^{}]*\}\}\n?")


def _series_mensais(p: Panorama) -> str:
    """As séries mensais do exercício, as mesmas das telas (``telas.graficos.series_do_parecer``).

    Saem do banco histórico do alvo configurado, como as conferências do banco; para outro alvo, nada.
    A adaptação fica deste lado: o parecer é impresso em papel claro, então o tema escuro das telas sai,
    e o título da seção vira subtítulo para não quebrar a numeração das seções do parecer.
    """
    if not p.do_alvo_configurado():
        return ""
    from ..telas.graficos import BANCO, series_do_parecer
    trecho = series_do_parecer(p.competencia, banco=p.banco or BANCO)
    if not trecho:
        return ""
    trecho = _TEMA_ESCURO_DAS_TELAS.sub("", trecho)
    return trecho.replace("<h2>", "<h3>", 1).replace("</h2>", "</h3>", 1)


def gerar(p: Panorama, *, hoje: date | None = None) -> str:
    hoje = hoje or date.today()
    p.completar()
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
        az = _selo(Selo.AZUL)
        s.append('<div class="tabela"><table><tr><th>Margem: o que não chegou</th><th>Valor</th></tr>'
                 f'<tr><td>{az}Previsto e não empenhado</td><td class="num">{svg.moeda(m.previsto_nao_empenhado)}</td></tr>'
                 f'<tr><td>{az}Empenhado e não liquidado</td><td class="num">{svg.moeda(m.empenhado_nao_liquidado)}</td></tr>'
                 f'<tr><td>{az}Liquidado e não pago</td><td class="num">{svg.moeda(m.liquidado_nao_pago)}</td></tr>'
                 f'<tr><td>{az}Pago sem vínculo publicado</td><td class="num">{svg.moeda(m.pago_sem_vinculo)}</td></tr>'
                 "</table></div>")
    else:
        s.append('<p class="omitido">As margens (previsto e não empenhado, empenhado e não liquidado, '
                 "liquidado e não pago, pago sem vínculo) dependem da execução publicada, que não "
                 "existe para a competência.</p>")
    for v in p.leitura_falhou:
        s.append(f'<div class="vermelho">{_selo(Selo.VERMELHO)}{escape(v)}</div>')
    if p.fiscal is not None and p.fiscal.rio is not None:
        s.extend(_rio_municipal(p.fiscal.rio))
    s.append(_series_mensais(p))

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
    s.extend(_quadros(p, 3))

    # 4. As contas, uma a uma
    s.append("<h2>4. As contas, uma a uma</h2>")
    if p.rio.afluentes:
        linhas = []
        for a in sorted(p.rio.afluentes, key=lambda a: -a.valor):
            fonte = classificar(a.fonte) if a.fonte else None
            if fonte is None:
                leito = "sem fonte declarada"
            elif fonte.destinacao is None:
                leito = "fora do catálogo"
            else:
                leito = ", ".join(fonte.destinacao.leito) if fonte.destinacao.leito else "livre"
            linhas.append(f"<tr><td>{_selo(a.selo)}{escape(a.nome)}</td><td>{escape(a.fonte or '—')}</td>"
                          f"<td>{escape(a.esfera.value)}</td><td>{escape(leito)}</td>"
                          f'<td class="num">{svg.moeda(a.valor)}</td></tr>')
        s.append('<div class="tabela"><table><tr><th>Entrada</th><th>Fonte</th><th>Esfera</th>'
                 f'<th>Leito (função)</th><th>{_rotulo_do_valor(p)}</th></tr>' + "".join(linhas) + "</table></div>")
    if p.execucao is not None:
        from ..rio.parecer_dominio import secao_execucao
        s.append(secao_execucao(p.execucao, p.contas or {}, p.qualidade))
    else:
        s.append('<p class="omitido">As saídas, as quatro estações legais e a cronologia evento a evento '
                 "aparecem quando a execução da despesa é publicada.</p>")
    s.extend(_quadros(p, 4))
    s.extend(_federais(p))

    # 5. Preço e entrega
    s.append("<h2>5. Preço e entrega</h2>")
    if p.compras is not None:
        s.append(_secao_compras(p))
    if getattr(p, "empresas", None) is not None:
        from ..conferencias import empresas
        s.append("<h3>Empresas contratadas</h3>" + empresas.secao_parecer(p.empresas, p.competencia))
    s.extend(_quadros(p, 5))
    s.append(_secao_familias(p, {Familia.PRC, Familia.ENT},
                             "Nenhum contrato fora da curva com os dados publicados; sem medição e "
                             "liquidação publicadas, preço e entrega não se confrontam."))

    # 6. Prestação de contas
    s.append("<h2>6. Prestação de contas</h2>")
    s.append(_secao_familias(p, {Familia.PCT, Familia.CTA},
                             "Nenhuma prestação de contas publicada para conferir."))
    s.extend(_quadros(p, 6))
    confirmados = [f for f in p.fichas if f.verificacao is Verificacao.CONFIRMADO]
    if confirmados:
        s.append(f"<p>{_selo(Selo.AZUL)}{len(confirmados)} indício(s) confirmado(s) em duas vias neste parecer. "
                 "A Controladoria comunica ao Tribunal de Contas as irregularidades de que tiver ciência (Lei "
                 "Orgânica, art. 104; CF, art. 74, § 1º); sem as comunicações publicadas, não se confere se cada "
                 "um foi comunicado.</p>")

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
        s.append(f'<p>Os ofícios do mês, por órgão, também estão na <a href="oficios/oficios_{escape(p.competencia)}.html">'
                 "página pública dos ofícios</a>, para protocolo e envio por e-mail.</p>")
        s.extend(_protocolos(hoje))
        s.append("<details><summary>A escada contra a não resposta</summary><ol>" + "".join(
            f"<li><strong>{escape(d.nome)}</strong> ({escape(d.fundamento)})"
            + (f": {escape(d.observacao)}" if d.observacao else "") + "</li>" for d in ESCADA)
            + "</ol></details>")

    from ..selo.relatorio import secao_parecer   # importa daqui (CSS e _ficha): por isso fica aqui dentro
    selo = secao_parecer() if p.do_alvo_configurado() else ""
    if selo:
        # As fichas da auditoria do selo não são fichas do panorama: a seção 7 é a única lista de fichas.
        s.append(selo.replace('class="ficha ', 'class="ficha-selo '))

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
    s.extend(_custodia_do_banco(p))
    for fn in SECOES_EXTERNAS:
        trecho = fn(p, hoje)
        if trecho:
            s.append(trecho)

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
    ligacao += ("<h2>Agenda e ofícios</h2><ul><li><a href=\"agenda.html\">Agenda da coleta: o que cada fonte "
                "publica, quando o sistema lê e o prazo legal de cada documento</a></li>"
                "<li><a href=\"oficios/index.html\">Ofícios prontos, por órgão e por competência</a></li></ul>")
    return ("<!doctype html><html lang=\"pt-BR\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>Onisciente</title><style>{CSS}</style></head><body><main>"
            f"<h1>Onisciente</h1><p class=\"sub\">{escape(alvo)} · a trilha do dinheiro público</p>"
            "<p class=\"painel\"><a href=\"app/index.html\">Abrir o painel do Onisciente</a></p>"
            f"<h2>Pareceres mensais</h2><ul>{itens or '<li>Nenhum parecer ainda.</li>'}</ul>"
            f"{ligacao}</main></body></html>")


_TIPOS = (
    (Tipo.ENTRE_FONTES, "A origem: o que a União transferiu contra o que o Município registrou",
     "Portal da Transparência (SIAFI) contra a matriz de saldos contábeis, na natureza e na fonte que "
     "vinculam o recurso."),
    (Tipo.ENTRE_DEMONSTRATIVOS, "O RREO contra a matriz de saldos contábeis",
     "Duas entregas do Município, homologadas em separado pelo Tesouro."),
    (Tipo.MESMO_RELATORIO, "O rio contra o próprio RREO",
     "Quadros do mesmo relatório: confere a montagem do rio, mas não é outra via e não entra na coerência."),
)


def _rio_municipal(rm: RioMunicipal) -> list[str]:
    """O rio do Município inteiro no exercício, com as três conferências, o ritmo e o leito."""
    s = [f"<h3>O rio do Município inteiro: {escape(rm.rotulo)}</h3>",
         '<p class="sub">Cada espécie de receita do exercício, aberta pelas fontes em que o Município a '
         "registrou na matriz de saldos contábeis. A fonte diz se a água é vinculada ou livre.</p>",
         svg.rio(rm.rio, rotulo="no exercício", maximo=24)]
    az = _selo(Selo.AZUL)
    rio_rreo = selar([Via("rio", rm.liquido), Via("RREO", rm.realizado_declarado)], tolerancia=TOLERANCIA_RIO_RREO)
    # O rio é montado do mesmo RREO: fechar dentro de 1% confere a montagem (azul), não é segunda via.
    selo_rio = _selo(Selo.VERMELHO if rio_rreo.divergencia else Selo.AZUL)
    s.append('<div class="tabela"><table><tr><th>O leito</th><th>Valor</th></tr>'
             f'<tr><td>{az}Afluentes somados</td><td class="num">{svg.moeda(rm.rio.total())}</td></tr>'
             f'<tr><td>{az}FUNDEB entregue ao fundo (sangria)</td><td class="num">{svg.moeda(-rm.sangria_fundeb)}</td></tr>'
             f'<tr><td>{selo_rio}Receita realizada pelo rio</td><td class="num">{svg.moeda(rm.liquido)}</td></tr>'
             f'<tr><td>{az}Receita realizada declarada no RREO</td><td class="num">{svg.moeda(rm.realizado_declarado)}</td></tr>'
             f'<tr><td>{az}Receita prevista no ano</td><td class="num">{svg.moeda(rm.previsto_ano)}</td></tr>'
             "</table></div>")
    if rio_rreo.divergencia:
        s.append('<p class="omitido">O rio e a receita realizada do RREO se separam em mais de 1%: a montagem do '
                 "rio está errada e o número do rio não vale até ser corrigida (falha do sistema).</p>")
    if rm.margens is not None:
        m = rm.margens
        s.append('<div class="tabela"><table><tr><th>Margem do Município inteiro</th><th>Valor</th></tr>'
                 + (f'<tr><td>{az}Previsto e não empenhado</td><td class="num">{svg.moeda(m.previsto_nao_empenhado)}</td></tr>'
                    if rm.margens_no_ano else
                    f'<tr><td>{az}Dotação ainda não empenhada (o ano não acabou)</td>'
                    f'<td class="num">{svg.moeda(m.previsto_nao_empenhado)}</td></tr>')
                 + f'<tr><td>{az}Empenhado e não liquidado</td><td class="num">{svg.moeda(m.empenhado_nao_liquidado)}</td></tr>'
                 f'<tr><td>{az}Liquidado e não pago</td><td class="num">{svg.moeda(m.liquidado_nao_pago)}</td></tr>'
                 "</table></div>")
    for tipo, titulo, explica in _TIPOS:
        conf = [c for c in rm.conferencias if c.tipo == tipo]
        if not conf:
            continue
        linhas = []
        mesma_ref = all(c.referencia == conf[0].referencia for c in conf)
        for c in conf:
            vias = c.certificacao.vias
            linhas.append(
                f"<tr><td>{_selo(c.selo)}{escape(c.titulo)}</td>"
                + "".join(f'<td class="num">{escape(v.fonte)}<br>{svg.moeda(v.valor)}</td>' for v in vias[:2])
                + f"<td>{'divergem' if c.certificacao.divergencia else 'iguais'}</td></tr>")
            nota = ([c.referencia + "."] if not mesma_ref else []) + c.detalhe
            if nota:
                linhas.append(f'<tr><td colspan="4" class="sub">{escape(" ".join(nota))}</td></tr>')
        comum = conf[0].referencia if mesma_ref else ""
        s.append(f"<h4>{escape(titulo)}</h4><p class=\"sub\">{escape(explica)}"
                 + (f" {escape(comum)}." if comum else "") + "</p>")
        s.append('<div class="tabela"><table><tr><th>Valor</th><th>Via 1</th><th>Via 2</th><th>Resultado</th></tr>'
                 + "".join(linhas) + "</table></div>")
    if rm.ritmos:
        nome = {"cumpre": "no ritmo", "alerta": "abaixo do ritmo", "abaixo_imaterial": "abaixo, sem relevância",
                "sem_dado": "sem ano anterior"}
        linhas = "".join(
            f"<tr><td>{_selo(Selo.AZUL)}{escape(r.especie)}</td><td class=\"num\">{svg.moeda(r.realizado)}</td>"
            f"<td class=\"num\">{svg.moeda(r.esperado)}</td><td class=\"num\">{svg.moeda(r.previsto)}</td>"
            f"<td>{escape(nome.get(r.situacao, r.situacao))}</td></tr>" for r in rm.ritmos)
        s.append("<h4>Realizado contra o previsto</h4><p class=\"sub\">Cada espécie contra a previsão atualizada, "
                 "no ritmo em que o ano anterior se realizou até o mesmo bimestre.</p>")
        s.append('<div class="tabela"><table><tr><th>Espécie</th><th>Realizado</th><th>Esperado no ritmo</th>'
                 "<th>Previsto no ano</th><th>Situação</th></tr>" + linhas + "</table></div>")
    s.append("<h4>O leito: água vinculada empenhada fora da sua finalidade</h4>")
    if rm.meses_desvio:
        s.append(f'<p class="sub">Empenhos da matriz de saldos contábeis, {escape(", ".join(rm.meses_desvio[:1]))} '
                 f"a {escape(rm.meses_desvio[-1])}, por fonte e função.</p>")
    if rm.desvios:
        linhas = "".join(
            f"<tr><td>{_selo(Selo.AZUL)}{escape(d.fonte)} · {escape(d.nome_fonte)}</td><td>{escape(d.funcao)}</td>"
            f'<td class="num">{svg.moeda(d.valor)}</td><td>{escape(d.norma)}</td></tr>' for d in rm.desvios)
        s.append('<div class="tabela"><table><tr><th>Fonte</th><th>Função</th><th>Empenhado</th><th>Norma</th></tr>'
                 + linhas + "</table></div>")
    elif rm.meses_desvio:
        s.append('<p class="sub">Nenhuma fonte vinculada empenhada fora do seu leito.</p>')
    else:
        s.append('<p class="omitido">A matriz de saldos contábeis do exercício não está no banco: o leito '
                 "não pôde ser conferido.</p>")
    if rm.fontes_sem_catalogo:
        itens = ", ".join(f"{f} ({svg.moeda(v)})" for f, v in sorted(rm.fontes_sem_catalogo.items(),
                                                                     key=lambda kv: -kv[1]))
        s.append(f'<p class="omitido">Destinações sem leito no catálogo do sistema, que ainda não se '
                 f"conferem: {escape(itens)}. Falha do sistema, não do Município.</p>")
    for n in rm.notas:
        s.append(f'<p class="omitido">{escape(n)}</p>')
    return s


def _protocolos(hoje: date) -> list[str]:
    """Os protocolos registrados, com o prazo acompanhado e o recurso pronto quando venceu."""
    itens = acompanhar(carregar_registro(), hoje)
    if not itens:
        return ['<p class="omitido">Nenhum protocolo registrado ainda em estado/protocolos_lai.json. Quem '
                "protocolar registra ali a data; o sistema acompanha o prazo de cada um e deixa pronto o "
                "recurso de cada degrau da escada.</p>"]
    linhas = "".join(
        f"<tr><td>{escape(i['assunto'])}</td><td>{escape(i['protocolado_em'])}</td>"
        f"<td>{escape(i['situacao'])}</td><td>{escape(i.get('vence_em') or i.get('agir_ate') or '')}</td></tr>"
        for i in itens)
    s = ['<h3>Protocolos acompanhados</h3><div class="tabela"><table><tr><th>Pedido</th><th>Protocolado</th>'
         "<th>Situação</th><th>Prazo</th></tr>" + linhas + "</table></div>"]
    for i in itens:
        if i.get("recurso"):
            s.append(f"<details><summary>Recurso pronto: {escape(i['proximo'])} ({escape(i['assunto'])})</summary>"
                     f"<pre>{escape(i['recurso'])}</pre></details>")
    return s


def _custodia_do_banco(p: Panorama) -> list[str]:
    """Os originais das coletas guardadas no banco: endereço, data e impressão digital."""
    a = p.auditoria
    s: list[str] = []
    if a is not None and a.custodia_por_motor:
        s.append("<h3>Os originais das coletas do banco histórico</h3>"
                 '<p class="sub">Cada leitura guardada tem o endereço, a data e a impressão digital (SHA-256) do '
                 "que foi lido. A impressão do conjunto muda se qualquer leitura mudar.</p>")
        s.append('<div class="tabela"><table><tr><th>Motor</th><th>Leituras</th><th>Período</th>'
                 "<th>Impressão do conjunto</th></tr>" + "".join(
                     f"<tr><td>{escape(m['motor'])}</td><td class=\"num\">{m['leituras']}</td>"
                     f"<td>{escape(m['primeira'])} a {escape(m['ultima'])}</td>"
                     f'<td class="hash">{escape(m["impressao_do_conjunto"])}</td></tr>' for m in a.custodia_por_motor)
                 + "</table></div>")
        if a.custodia:
            s.append(f"<details><summary>As {len(a.custodia)} leituras uma a uma (motores com até 60 "
                     "leituras)</summary><div class=\"tabela\"><table><tr><th>Original</th><th>Coletado</th>"
                     "<th>Impressão digital</th></tr>" + "".join(
                         f'<tr><td><a href="{escape(o.url)}">{escape(o.fonte or o.url)}</a></td>'
                         f"<td>{escape(o.coletado_em)}</td><td class=\"hash\">{escape(o.sha256)}</td></tr>"
                         for o in a.custodia) + "</table></div></details>")
    fed = p.federais
    if fed is not None:
        problemas = sorted((fed.cobertura.get("problemas") or {}).items())
        for motor, problema in problemas:
            s.append(f'<div class="vermelho">{_selo(Selo.VERMELHO)}Fonte federal ou estadual sem leitura '
                     f"({escape(motor)}): {escape(problema)}. Falha do sistema, não do Município.</div>")
    return s
