"""A casca HTML de cada tela: topo com os recortes, a régua do rio, os dados embutidos e o rodapé.

O conteúdo de cada tela é desenhado no navegador por ``app.js`` a partir dos dados embutidos, para que os
recortes (alvo, período e secretaria) mudem a tela sem ir a servidor nenhum.
"""

from __future__ import annotations

from html import escape

from .base import json_seguro

FONTES_GOOGLE = ("https://fonts.googleapis.com/css2?family=Zilla+Slab:wght@600;700&family=IBM+Plex+Sans:"
                 "wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap")

TRECHOS = ("Nascente", "Leito", "Foz", "Margens")


def regua(paginas: list[dict], atual: str) -> str:
    partes = []
    for trecho in TRECHOS:
        links = []
        for p in paginas:
            if p["trecho"] != trecho:
                continue
            atual_attr = ' aria-current="page"' if p["id"] == atual else ""
            links.append(f'<a href="{p["id"]}.html" data-pagina="{p["id"]}"{atual_attr}>{escape(p["titulo"])}'
                         f'<span class="cont" data-cont="{p["id"]}"></span></a>')
        partes.append(f'<div class="trecho"><span aria-hidden="true">{trecho}</span>{"".join(links)}</div>')
    inicio = next(p for p in paginas if p["id"] == "index")
    atual_attr = ' aria-current="page"' if atual == "index" else ""
    primeiro = (f'<div class="trecho"><span aria-hidden="true">Início</span><a href="index.html" data-pagina="index"'
                f'{atual_attr}>{escape(inicio["titulo"])}<span class="cont" data-cont="index"></span></a></div>')
    return (f'<nav class="regua" aria-label="Telas, na ordem do rio"><div class="wrap">{primeiro}'
            f'{"".join(partes)}</div></nav>')


def html(pagina: dict, comum: dict, dados: dict, fontes: dict, indice: list, *, versao_estatico: str) -> str:
    """Uma página completa. ``pagina`` é a entrada de ``comum['paginas']``."""
    pid = pagina["id"]
    titulo = f"{pagina['titulo']} · Onisciente" if pid != "index" else "Onisciente · Núcleo de Fiscalização"
    alvo = comum["alvo"]
    descricao = f"{pagina['pergunta']}. {alvo['nome']}."
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(titulo)}</title>
<meta name="description" content="{escape(descricao)}">
<link rel="icon" href="escudo.webp" type="image/webp">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{FONTES_GOOGLE}">
<link rel="stylesheet" href="app.css?v={versao_estatico}">
<script>try{{var t=localStorage.getItem('onisciente.tema');if(t)document.documentElement.dataset.theme=t}}catch(e){{}}</script>
</head>
<body data-pagina="{pid}">
<a class="pular" href="#conteudo">Pular para o conteúdo</a>
<header class="topo">
  <div class="wrap">
    <a class="marca" href="index.html" aria-label="Onisciente, página inicial">
      <img src="escudo.webp" alt="" width="44" height="50">
      <span><b class="nome">Onisci<span>ente</span></b><small>Núcleo de Fiscalização · A.M.C. Jardim América</small></span>
    </a>
    <form class="recorte" id="recorte" data-aberto="false" aria-label="Recorte dos dados" onsubmit="return false">
      <p class="resumo-recorte" id="resumo-recorte" aria-live="polite"></p>
      <label>Alvo<select id="sel-alvo" name="alvo"></select></label>
      <label>Período<select id="sel-periodo" name="c"></select></label>
      <label>Secretaria<select id="sel-secretaria" name="s"></select></label>
      <div class="botoes">
        <button type="button" class="bt" id="bt-recorte" aria-expanded="false" hidden>Recorte</button>
        <button type="button" class="bt primario" id="bt-apresentar" title="Modo apresentação (tecla P)">▶ <span class="longo">Apresentar</span></button>
        <button type="button" class="bt" id="bt-tema" aria-label="Alternar tema claro e escuro">◐</button>
      </div>
    </form>
  </div>
  <div class="ouro" aria-hidden="true"></div>
</header>
{regua(comum["paginas"], pid)}
<main id="conteudo" class="wrap" tabindex="-1">
  <header class="cabeca">
    <div>
      <p class="trecho-nome">{escape(pagina["trecho"])}</p>
      <h1>{escape(pagina["titulo"])}</h1>
      <p class="pergunta">{escape(pagina["pergunta"])}.</p>
    </div>
    <p class="onde" id="onde" aria-live="polite"></p>
  </header>
  <div class="tela" id="tela"><p class="carregando">Montando a tela…</p></div>
  <noscript><p>Esta tela é desenhada no navegador a partir dos dados embutidos na própria página. Ative o
  JavaScript para ver os números, os recortes e a origem de cada dado.</p></noscript>
  <nav class="caminho" id="caminho" aria-label="Seguir o dinheiro"></nav>
</main>
<footer class="rodape">
  <div class="wrap">
    <div>
      <p><b>Onisciente</b>, conferência de prestação de contas pela trilha do dinheiro público. Cada número mostra a sua
      origem ao passar o mouse ou tocar; o clique abre o original guardado. Alerta é indício, não acusação.</p>
      <p class="nota" id="gerado"></p>
    </div>
    <ul id="links-rodape">
      <li><a href="../index.html">Pareceres mensais</a></li>
      <li><a href="../banco/index.html">O banco de dados</a></li>
      <li><a href="../ux/estudo_ux.md">Estudo de UX</a></li>
      <li><a href="https://github.com/ctresb/leis" rel="noopener">Acervo de leis</a></li>
    </ul>
  </div>
</footer>
<div id="dica" role="tooltip" hidden></div>
<div class="palco" id="palco" aria-live="polite"><span class="fonte-tela" id="palco-tela"></span>
<span><span class="contador" id="palco-cont"></span> <button type="button" id="palco-sair">Sair (Esc)</button></span></div>
<script type="application/json" id="d-comum">{json_seguro(comum)}</script>
<script type="application/json" id="d-indice">{json_seguro(indice)}</script>
<script type="application/json" id="d-fontes">{json_seguro(fontes)}</script>
<script type="application/json" id="d-tela">{json_seguro(dados)}</script>
<script src="app.js?v={versao_estatico}"></script>
</body>
</html>
"""
