"""A página pública dos ofícios: um ofício pronto por órgão, para cada competência.

Lê os panoramas já gerados (``relatorios/onisciente/panorama_AAAA-MM.json``), agrupa as ausências
pelo órgão que guarda cada documento (``lai.orgao_competente``) e publica em
``docs/onisciente/oficios/``:

* ``index.html``: as competências, quantos ofícios e quantos itens em cada uma, e os protocolos
  registrados com o prazo acompanhado;
* ``oficios_AAAA-MM.html``: cada ofício com o texto inteiro e um link de e-mail já preenchido, para
  quem assina copiar, protocolar ou enviar. O sistema nunca protocola nem envia nada sozinho.

    python -m onisciente.oficios
"""

from __future__ import annotations

import json
import re
from datetime import date
from html import escape
from pathlib import Path
from urllib.parse import quote

from . import RAIZ
from .lai import Oficio, acompanhar, carregar_registro, oficios_por_orgao
from .nucleo.ausencias import Ausencia

RELATORIOS = RAIZ / "relatorios" / "onisciente"
SAIDA = RAIZ / "docs" / "onisciente" / "oficios"

CSS = """body{margin:0;background:#FBFAF7;color:#1F2933;font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:860px;margin:0 auto;padding:32px 16px 64px}h1,h2{font-family:Georgia,serif;line-height:1.2}
h2{margin:36px 0 10px;padding-top:14px;border-top:1px solid #D7DCE1}.sub{color:#5B6672}
pre{white-space:pre-wrap;background:#fff;border:1px solid #D7DCE1;border-radius:8px;padding:12px;font-size:13px}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;padding:6px 8px;
border-bottom:1px solid #D7DCE1}td.num{text-align:right}details{margin:10px 0}summary{cursor:pointer;font-weight:600}"""

MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
         "novembro", "dezembro"]


def _mes(competencia: str) -> str:
    ano, mes = competencia.split("-")
    return f"{MESES[int(mes) - 1]} de {ano}"


def _pagina(titulo: str, corpo: str) -> str:
    return ("<!doctype html><html lang=\"pt-BR\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{escape(titulo)}</title><style>{CSS}</style></head><body><main>{corpo}</main></body></html>")


def ausencias_do_panorama(caminho: Path) -> tuple[str, list[Ausencia]]:
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    campos = ("o_que_falta", "conferencia_impedida", "onde_deveria_estar", "fundamento", "periodo", "orgao", "bloco")
    return dados.get("dominio", ""), [Ausencia(**{k: a.get(k, "") or "" for k in campos})
                                      for a in dados.get("ausencias", [])]


def oficios_da_competencia(competencia: str, raiz: Path = RAIZ) -> list[Oficio]:
    caminho = raiz / "relatorios" / "onisciente" / f"panorama_{competencia}.json"
    if not caminho.exists():
        return []
    dominio, itens = ausencias_do_panorama(caminho)
    return oficios_por_orgao(itens, f"Documentos não publicados: {dominio}, {_mes(competencia)}")


def pagina_oficios(competencia: str, oficios: list[Oficio], hoje: date) -> str:
    corpo = [f"<h1>Ofícios de {escape(_mes(competencia))}</h1>",
             f'<p class="sub">{len(oficios)} ofício(s), {sum(len(o.itens) for o in oficios)} item(ns). Cada '
             "ofício vai ao órgão que guarda o documento, com cópia à Controladoria, que atende os pedidos de "
             "acesso. Quem assina confere, protocola e registra a data em estado/protocolos_lai.json; o sistema "
             "acompanha o prazo.</p>"]
    for o in oficios:
        texto = o.texto(hoje=hoje)
        mailto = f"mailto:?subject={quote(o.assunto)}&body={quote(texto)}"
        corpo.append(f'<h2 id="{escape(re.sub(r"[^a-z0-9]+", "-", o.destinatario.lower()).strip("-"))}">'
                     f"{escape(o.destinatario)}</h2>")
        corpo.append(f'<p class="sub">{len(o.itens)} item(ns). <a href="{escape(mailto)}">Abrir no e-mail</a> '
                     "(o endereço do órgão fica com quem envia).</p>")
        corpo.append(f"<pre>{escape(texto)}</pre>")
    if not oficios:
        corpo.append('<p class="sub">Nenhum documento faltando nesta competência.</p>')
    corpo.append('<p><a href="index.html">Todas as competências</a></p>')
    return _pagina(f"Ofícios de {_mes(competencia)}", "".join(corpo))


def pagina_indice(resumo: list[tuple[str, int, int]], protocolos: list[dict]) -> str:
    linhas = "".join(f'<tr><td><a href="oficios_{c}.html">{escape(_mes(c).capitalize())}</a></td>'
                     f'<td class="num">{n}</td><td class="num">{i}</td></tr>' for c, n, i in sorted(resumo, reverse=True))
    corpo = ["<h1>Ofícios prontos</h1>",
             '<p class="sub">Todo documento que a lei manda publicar e não está publicado vira um pedido de acesso '
             "pronto: publicação em transparência ativa, em formato aberto, e envio por meio eletrônico enquanto não "
             "for publicado.</p>",
             "<table><tr><th>Competência</th><th>Ofícios</th><th>Itens</th></tr>"
             + (linhas or '<tr><td colspan="3">Nenhuma competência ainda.</td></tr>') + "</table>",
             "<h2>Protocolos acompanhados</h2>"]
    if protocolos:
        corpo.append("<table><tr><th>Pedido</th><th>Protocolado</th><th>Situação</th><th>Prazo</th></tr>" + "".join(
            f"<tr><td>{escape(p['assunto'])}</td><td>{escape(p['protocolado_em'])}</td><td>{escape(p['situacao'])}</td>"
            f"<td>{escape(p.get('vence_em') or p.get('agir_ate') or '')}</td></tr>" for p in protocolos) + "</table>")
        for p in protocolos:
            if p.get("recurso"):
                corpo.append(f"<details><summary>Recurso pronto: {escape(p['proximo'])} ({escape(p['assunto'])})"
                             f"</summary><pre>{escape(p['recurso'])}</pre></details>")
    else:
        corpo.append('<p class="sub">Nenhum protocolo registrado em estado/protocolos_lai.json.</p>')
    corpo.append('<p><a href="../index.html">Pareceres</a></p>')
    return _pagina("Ofícios prontos", "".join(corpo))


def publicar(*, raiz: Path = RAIZ, hoje: date | None = None, saida: Path | None = None) -> list[Path]:
    hoje = hoje or date.today()
    saida = saida or raiz / "docs" / "onisciente" / "oficios"
    saida.mkdir(parents=True, exist_ok=True)
    escritos, resumo = [], []
    for caminho in sorted((raiz / "relatorios" / "onisciente").glob("panorama_*.json")):
        m = re.fullmatch(r"panorama_(\d{4}-\d{2})\.json", caminho.name)
        if not m:
            continue
        comp = m.group(1)
        oficios = oficios_da_competencia(comp, raiz)
        arq = saida / f"oficios_{comp}.html"
        arq.write_text(pagina_oficios(comp, oficios, hoje), encoding="utf-8")
        escritos.append(arq)
        resumo.append((comp, len(oficios), sum(len(o.itens) for o in oficios)))
    registro = carregar_registro(raiz / "estado" / "protocolos_lai.json")
    indice = saida / "index.html"
    indice.write_text(pagina_indice(resumo, acompanhar(registro, hoje)), encoding="utf-8")
    return escritos + [indice]


if __name__ == "__main__":
    for p in publicar():
        print(p.relative_to(RAIZ))
