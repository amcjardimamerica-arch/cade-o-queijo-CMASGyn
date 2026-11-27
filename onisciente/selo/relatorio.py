"""Saídas da auditoria do selo: fichas, ofícios, a página ``docs/onisciente/selo/goiania.html``, o JSON
em ``relatorios/onisciente/selo/`` e a seção pronta para o parecer mensal.

No parecer, alerta é indício, não acusação: cada ficha diz o que a lei pede, o que se viu e o que pedir.
"""

from __future__ import annotations

import json
from datetime import date
from html import escape
from pathlib import Path

from .. import RAIZ
from ..lai import Oficio
from ..nucleo.ausencias import Ausencia
from ..nucleo.indicios import Familia, Ficha, emitir
from ..nucleo.provas import Nivel
from ..parecer.html import CSS, _ficha
from .avaliador import DECLARADO, DIMENSAO_O, Auditoria
from .formula import itens_da_leitura
from .matriz import ROTULO_CLASSE, ROTULO_ITEM
from .provas import reais

DOCS = RAIZ / "docs" / "onisciente" / "selo"
RELATORIOS = RAIZ / "relatorios" / "onisciente" / "selo"
CGM = "Controladoria Geral do Município de Goiânia"
TCM = "Presidência do Tribunal de Contas dos Municípios do Estado de Goiás"
COR = {"atendido": "#15803D", "não atendido": "#C81E1E", "não verificável": "#7E22CE"}


def pct(v: float) -> str:
    return f"{v:.2f}".replace(".", ",") + "%"


# --- Fichas -------------------------------------------------------------------------------------

def fichas(aud: Auditoria, competencia: str | None = None) -> list[Ficha]:
    out: list[Ficha] = []
    for a in aud.achados:
        if a.tipo == "selo_nao_confirmado":
            out.append(emitir(
                codigo=f"PCT-SELO01-{aud.matriz.ciclo}", familia=Familia.PCT, gravidade="alta",
                titulo="Selo Diamante de transparência sem confirmação independente",
                como_deveria="O Selo Diamante do PNTP exige índice de 95% ou mais e 100% dos critérios essenciais, "
                             "cada resposta Sim com o link da evidência (Cartilha PNTP 2026, Atricon).",
                norma="Cartilha e matriz do PNTP 2026 (Atricon); LC 101/2000, arts. 48 e 48-A; Lei 12.527/2011, art. 8º",
                como_esta=a.descricao, niveis=[Nivel.F], documento_faltante=True,
                providencia="Pedir ao TCM-GO os papéis de trabalho da validação do PNTP de Goiânia (respostas e links "
                            "por critério) e à Controladoria a publicação do que falta; rodar a sondagem do selo.",
                competencia=competencia, observacao="indício, não acusação"))
        elif a.tipo == "selo_essencial_em_falta":
            cid = a.dados["criterio"]
            out.append(emitir(
                codigo=f"PCT-SELO02-{cid}", familia=Familia.PCT, gravidade="alta",
                titulo=f"Critério essencial {cid} do PNTP sem cumprimento comprovado",
                como_deveria="Critério essencial atendido por inteiro: disponível, atualizado, com série histórica, "
                             "gravável em formato aberto e com filtro.",
                norma=a.dados["base_legal"], como_esta=a.descricao[:1].upper() + a.descricao[1:] + ".",
                niveis=[Nivel.F], documento_faltante=True,
                providencia="Pedir a publicação, para todas as unidades gestoras, inclusive os fundos, em formato aberto.",
                competencia=competencia, observacao="leitura restritiva"))
        elif a.tipo in ("fundo_sem_transparencia", "conselho_sem_transparencia"):
            fundo = a.tipo == "fundo_sem_transparencia"
            out.append(emitir(
                codigo=f"PCT-{'FMAS' if fundo else 'CMAS'}-T{a.chave}", familia=Familia.PCT,
                gravidade="alta" if a.valor else "media",
                titulo=("Fundo Municipal de Assistência Social" if fundo else "Conselho Municipal de Assistência Social")
                       + ": transparência sem comprovação",
                como_deveria=f"Publicação em transparência ativa ({a.dados['obrigacao']}).",
                norma=a.dados["base"], como_esta=a.descricao[:1].upper() + a.descricao[1:],
                niveis=[Nivel.F], documento_faltante=True,
                providencia="Pedir por LAI a publicação e, enquanto isso, o envio dos documentos; ausência de dado é "
                            "alerta de descumprimento de transparência.",
                competencia=competencia, observacao="indício, não acusação"))
    return out


# --- Ofícios ------------------------------------------------------------------------------------

def oficios(aud: Auditoria) -> list[Oficio]:
    itens: list[Ausencia] = []
    por_id = {r.criterio.id: r for r in aud.resultados}
    for cid in sorted(set(aud.nota("restritiva", "teto").essenciais_em_falta) - {"O.2", "O.4"},
                      key=lambda x: por_id[x].criterio.ordem):
        c = por_id[cid].criterio
        itens.append(Ausencia(f"Critério essencial {cid} do PNTP: {c.texto[:1].lower() + c.texto[1:]}, para todas as unidades gestoras, "
                              "com série de três anos e arquivo em formato aberto",
                              "auditoria independente do selo de transparência", "portal da transparência do Município",
                              c.base_legal, orgao=CGM))
    for s in aud.fundos:
        if s.alerta:
            itens.append(Ausencia(s.obrigacao.texto, "transparência do Fundo e do Conselho de Assistência Social",
                                  "portal da transparência do Município e sítio do Conselho", s.obrigacao.base, orgao=CGM))
    tcm = [Ausencia("Papéis de trabalho da validação do PNTP 2025 e 2026 da Prefeitura de Goiânia: respostas, links de "
                    "evidência e notas por critério, e o resultado da garantia da qualidade, se a Prefeitura entrou na "
                    "amostra", "confronto independente do selo declarado com o selo apurado",
                    "Radar da Transparência Pública e sítio do TCM-GO", "Lei 12.527/2011, arts. 8º e 10", orgao=TCM)]
    return [Oficio(destinatario=CGM, assunto="Transparência ativa: critérios do PNTP, Fundo e Conselho de "
                                             "Assistência Social", itens=itens),
            Oficio(destinatario=TCM, assunto="Acesso aos papéis da avaliação do PNTP de Goiânia", itens=tcm)]


# --- Página -------------------------------------------------------------------------------------

def _tabela_notas(aud: Auditoria) -> str:
    linhas = []
    rot = {"oficial/comprovada": "Oficial, só com provas", "oficial/teto": "Oficial, teto (sem prova conta como atendido)",
           "restritiva/comprovada": "Restritiva, só com provas", "restritiva/teto": "Restritiva, teto"}
    for k, r in rot.items():
        n = aud.notas[k]
        falta = ", ".join(n.essenciais_em_falta) or "nenhum"
        linhas.append(f"<tr><td>{r}</td><td class=\"num\">{pct(n.indice)}</td><td>{escape(n.nivel)}</td>"
                      f"<td>{'sim' if n.selo else 'não'}</td><td>{escape(falta)}</td></tr>")
    return ('<div class="tabela"><table><tr><th>Leitura</th><th>Índice</th><th>Nível</th><th>Selo</th>'
            "<th>Essenciais sem prova ou em falta</th></tr>" + "".join(linhas) + "</table></div>")


def _peso(aud: Auditoria, criterio) -> float:
    """Quanto o critério vale no índice oficial, em pontos de 100."""
    m = aud.matriz
    lista = m.do_executivo()
    dims = m.dimensoes
    total = sum(dims[d]["peso"] for d in {c.dimensao for c in lista})
    pes = m.metodologia["pesos_exigibilidade"]
    if criterio.matriz == "onisciente":
        return 0.0
    soma_e = sum(pes[c.classe] for c in lista if c.dimensao == criterio.dimensao)
    return 100.0 * dims[criterio.dimensao]["peso"] * pes[criterio.classe] / soma_e / total


def _criterios(aud: Auditoria) -> str:
    s = []
    dims = dict(aud.matriz.dimensoes, O=DIMENSAO_O)
    atual = None
    for r in aud.resultados:
        c = r.criterio
        if c.dimensao != atual:
            if atual is not None:
                s.append("</table></div>")
            atual = c.dimensao
            d = dims[c.dimensao]
            s.append(f"<h3>{escape(str(c.dimensao))}. {escape(d['nome'])} (peso {d['peso']})</h3>"
                     '<div class="tabela"><table><tr><th>Critério</th><th>Classe</th><th>Vale</th>'
                     "<th>Oficial</th><th>Restritiva</th><th>Prova e fonte</th></tr>")
        sit = {l: r.situacao(l, aud.matriz) for l in r.itens}
        def cel(l):
            itens = itens_da_leitura(c, aud.matriz, l) if c.matriz != "onisciente" else c.itens
            det = ", ".join(f"{ROTULO_ITEM[i]} {'sim' if r.itens[l].get(i) else ('não' if r.itens[l].get(i) is False else '?')}"
                            for i in itens)
            return (f'<td><strong style="color:{COR[sit[l]]}">{sit[l]}</strong>'
                    f'<br><span class="sub">{escape(det)}</span></td>')
        provas = "".join(f"<li>{'Sim' if p.valor else 'Não'} ({escape(p.leituras)}): {escape(p.descricao)}. "
                         f'<span class="sub">{escape(p.fonte)}</span></li>' for p in r.provas[:4])
        notas = "".join(f"<li>{escape(n)}</li>" for n in (r.notas.get("restritiva") or [])[:2])
        onde = ", ".join(c.onde) or "provas sem rede"
        s.append(f"<tr><td><strong>{escape(c.id)}</strong> {escape(c.texto)}<br>"
                 f'<span class="sub">{escape(c.base_legal)}</span></td>'
                 f"<td>{escape(ROTULO_CLASSE[c.classe])}</td>"
                 f'<td class="num">{pct(_peso(aud, c)) if c.matriz != "onisciente" else "restritiva"}</td>'
                 + cel("oficial") + cel("restritiva")
                 + f'<td><ul>{provas}{notas}</ul><span class="sub">onde: {escape(onde)}</span></td></tr>')
    s.append("</table></div>")
    return "".join(s)


def _fundos(aud: Auditoria) -> str:
    rep = aud.repasses
    s = ["<p>A metodologia do PNTP cobre o Conselho só no critério 19.4 (recomendado, peso 1 dividido com a educação) "
         "e não tem critério para o Fundo: o Fundo só entra se o portal incluir a unidade gestora nas consultas de "
         "receita, despesa, convênios e contratos. Por isso o Onisciente confere os dois pela lei.</p>"]
    if rep.get("total"):
        anos = ", ".join(f"{a}: {reais(v)}" for a, v in rep["por_ano"].items())
        s.append(f"<p>Dinheiro que o Fundo Nacional de Assistência Social repassou ao FMAS ({rep['linhas']} ordens "
                 f"bancárias até {escape(str(rep['ultima']))}): <strong>{reais(rep['total'])}</strong> ({anos}). "
                 "É o que o Fundo tem de mostrar como recebeu, gastou e prestou contas.</p>")
    s.append('<div class="tabela"><table><tr><th>Obrigação</th><th>Base legal</th><th>PNTP</th><th>Situação</th>'
             "<th>Prova</th></tr>")
    for x in aud.fundos:
        o = x.obrigacao
        cor = "#15803D" if not x.alerta else "#C81E1E"
        s.append(f"<tr><td><strong>{o.id}</strong> {escape(o.orgao)}: {escape(o.texto)}</td><td>{escape(o.base)}</td>"
                 f"<td>{escape(o.pntp or 'não cobre')}</td><td><strong style=\"color:{cor}\">{escape(x.estado)}</strong></td>"
                 f"<td>{escape(' '.join(x.provas[:2]))}</td></tr>")
    s.append("</table></div>")
    return "".join(s)


def _ficha_html(f: dict) -> str:
    g = f["gravidade"]
    rot = {"critica": "crítica", "alta": "alta", "media": "média"}[g]
    return (f'<article class="ficha {g}"><h3><span class="etiqueta g-{g}">{rot}</span>{escape(f["titulo"])}</h3>'
            f'<div><span class="etiqueta v">{escape(f["codigo"])}</span><span class="etiqueta v">{escape(f["verificacao"])}</span>'
            f'<span class="etiqueta v">{escape(f.get("observacao") or "")}</span></div><dl>'
            f"<dt>Como deveria ser</dt><dd>{escape(f['como_deveria'])}</dd>"
            f"<dt>Norma</dt><dd>{escape(f['norma'])}</dd>"
            f"<dt>Como está</dt><dd>{escape(f['como_esta'])}</dd>"
            f"<dt>Providência</dt><dd>{escape(f['providencia'])}</dd></dl></article>")


def _radar(aud: Auditoria) -> str:
    r = aud.radar
    if r.get("lido"):
        return (f"<p>O Radar da Transparência mostra para Goiânia índice {escape(str(r.get('indice')))}% e nível "
                f"{escape(str(r.get('nivel')))} (lido em {escape(r['quando'])}, {escape(r['url'])}).</p>")
    return f'<p class="omitido">Radar da Transparência não lido: {escape(r.get("motivo", ""))}.</p>'


def pagina(aud: Auditoria) -> str:
    v = aud.veredito
    s = [f"<h1>Selo de transparência de Goiânia: auditoria independente</h1>",
         f'<p class="sub">Programa Nacional de Transparência Pública, ciclo {aud.matriz.ciclo} · gerado em '
         f"{aud.hoje:%d/%m/%Y} · {aud.paginas_lidas} páginas do portal lidas pela sondagem</p>",
         "<h2>1. Em uma frase</h2>", f'<p class="frase">{escape(v["frase"])}</p>',
         '<p class="omitido">Alerta é indício, não acusação. O sistema refaz a avaliação dos Tribunais de Contas com o '
         "que consegue provar e mostra também a leitura mais exigente onde a metodologia deixa margem.</p>",
         "<h2>2. Selo declarado e selo encontrado</h2>",
         f"<p>Declarado: <strong>Selo {escape(DECLARADO['selo'])}</strong>, ciclo {DECLARADO['ciclo']}, índice "
         f"{escape(DECLARADO['indice'])} ({escape(DECLARADO['fonte'])}). {escape(DECLARADO['ciclo_2026'])}</p>",
         _radar(aud), _tabela_notas(aud),
         "<p>Como ler: a nota só com provas conta como zero o que o Onisciente ainda não conseguiu ver; o teto conta "
         "como atendido. Se o teto já fica abaixo do Diamante, o selo declarado não se sustenta, qualquer que seja o "
         "resultado da sondagem. A fórmula: o peso de cada dimensão se reparte entre os critérios pelo peso de "
         "exigibilidade (essencial 2, obrigatório 1,5, recomendado 1) e, em cada critério, pelos itens (disponibilidade "
         "30%, atualidade 30%, série histórica 20%, gravação 10%, filtro 10%).</p>",
         "<h2>3. Critério por critério</h2>", _criterios(aud),
         "<h2>4. Fundo e Conselho Municipal de Assistência Social</h2>", _fundos(aud),
         "<h2>5. Alertas que o Onisciente já tem e que tocam o selo</h2>"]
    linhas = "".join(f"<tr><td>{escape(x['dimensao'])}</td><td class=\"num\">{x['achados']}</td>"
                     f"<td class=\"num\">{reais(x['valor'])}</td><td>{escape(', '.join(f'{k}: {n}' for k, n in x['tipos'].items()))}</td></tr>"
                     for x in aud.alertas_cruzados.values())
    s.append('<div class="tabela"><table><tr><th>Dimensão</th><th>Achados</th><th>Valor em jogo</th><th>Tipos</th></tr>'
             + linhas + "</table></div><p class=\"sub\">Gastos fora do padrão já apontados pelas conferências de "
             "compras (dispensas no teto, fracionamento, emergenciais, concentração, preço acima da curva nacional, "
             "notas fiscais ausentes). O selo não mede nenhum deles.</p>")
    s.append("<h2>6. Fichas</h2>")
    s += [_ficha(f) for f in fichas(aud)]
    s.append("<h2>7. Pedidos de acesso prontos</h2>")
    for o in oficios(aud):
        s.append(f"<details><summary>Para {escape(o.destinatario)} ({len(o.itens)} itens)</summary>"
                 f"<pre>{escape(o.texto(hoje=aud.hoje))}</pre></details>")
    s.append("<h2>8. Fontes, escolhas e pendências</h2><ul>" + "".join(
        f'<li>{escape(f["titulo"])}: <a href="{escape(f["url"])}">{escape(f["url"])}</a>, lida em {escape(f["lida_em"])}.</li>'
        for f in aud.matriz.fontes) + "</ul>")
    s.append("<p>As escolhas de leitura (oficial e restritiva) estão em regras/pntp/escolhas.yml; o estudo da "
             "metodologia está em docs/onisciente/selo/estudo_pntp.md.</p><ul>"
             + "".join(f"<li>{escape(p)}</li>" for p in aud.matriz.pendencias) + "</ul>")
    s.append("<h2>9. Para o parecer mensal</h2><p>A seção “Selo de transparência: auditoria independente” do parecer "
             "sai de <code>onisciente.selo.relatorio.secao_parecer()</code>, que lê "
             "relatorios/onisciente/selo/auditoria.json.</p>")
    s.append("<footer>É uma trilha e não um cartório. O sistema nunca imputa crime: a ficha afirma só o que as provas "
             "permitem.</footer>")
    return ("<!doctype html><html lang=\"pt-BR\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>Selo de transparência de Goiânia</title>"
            f"<style>{CSS}</style></head><body><main>" + "".join(s) + "</main></body></html>")


# --- Seção do parecer ---------------------------------------------------------------------------

def secao_parecer(dados: dict | None = None, caminho: Path | None = None) -> str:
    """A seção do parecer mensal, lida do JSON gravado (o parecer não recalcula a auditoria)."""
    if dados is None:
        arq = caminho or (RELATORIOS / "auditoria.json")
        if not arq.exists():
            return ""
        dados = json.loads(arq.read_text(encoding="utf-8"))
    v = dados["veredito"]
    n = dados["notas"]
    s = ['<h2 id="selo">Selo de transparência: auditoria independente</h2>',
         f'<p class="frase">{escape(v["frase"])}</p>',
         '<div class="tabela"><table><tr><th>Leitura</th><th>Índice</th><th>Nível</th></tr>'
         + "".join(f"<tr><td>{escape(k.replace('/', ', '))}</td><td class=\"num\">{pct(x['indice'])}</td>"
                   f"<td>{escape(x['nivel'])}</td></tr>" for k, x in n.items()) + "</table></div>"]
    s += [_ficha_html(f) for f in dados.get("fichas", [])]
    s.append('<p class="omitido">Alerta é indício, não acusação. Critério por critério em '
             '<a href="selo/goiania.html">selo/goiania.html</a>.</p>')
    return "".join(s)


def gravar(aud: Auditoria) -> list[Path]:
    DOCS.mkdir(parents=True, exist_ok=True)
    RELATORIOS.mkdir(parents=True, exist_ok=True)
    html = DOCS / "goiania.html"
    html.write_text(pagina(aud), encoding="utf-8")
    dados = aud.como_dict()
    dados["fichas"] = [f.como_dict() for f in fichas(aud)]
    js = RELATORIOS / "auditoria.json"
    js.write_text(json.dumps(dados, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    of = RELATORIOS / "oficios.txt"
    of.write_text("\n\n" + ("\n\n" + "=" * 72 + "\n\n").join(o.texto(hoje=aud.hoje) for o in oficios(aud)) + "\n",
                  encoding="utf-8")
    return [html, js, of]
