"""A casca HTML de cada tela: topo com os recortes, a barra das etapas, os ícones, os dados embutidos e o rodapé.

O conteúdo de cada tela é desenhado no navegador por ``app.js`` a partir dos dados embutidos, para que os
recortes (alvo, período e secretaria) mudem a tela sem ir a servidor nenhum. Os ícones das etapas e das três
condições (conforme, alerta, sem dado) vão uma vez em cada página, como símbolos SVG, e o app.js só os usa.
"""

from __future__ import annotations

from html import escape

from .base import json_seguro

FONTES_GOOGLE = ("https://fonts.googleapis.com/css2?family=Zilla+Slab:wght@600;700&family=IBM+Plex+Sans:"
                 "wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap")

# Os grupos da barra, na ordem do gasto público, e o ícone de cada um.
GRUPOS = (
    ("Início", "inicio"), ("Origem do dinheiro", "origem"), ("Orçamento", "orcamento"),
    ("Contratação", "contratacao"), ("Liquidação e pagamento", "pagamento"),
    ("Prestação de contas", "prestacao"), ("Consulta", "consulta"),
)

# Ícones próprios (24 x 24, traço da cor do texto). Etapas: origem, orçamento, contratação, liquidação,
# pagamento, prestação de contas. Condições: conforme, alerta, sem dado. Verificado por hash: o sinal
# de cerquilha num hexágono, no mesmo traço das condições e com forma própria (nem círculo, nem
# triângulo, nem quadrado). Demais: início, consulta, secretarias e normas.
ICONES = {
    "inicio": '<path d="M3 11.5 12 4l9 7.5"/><path d="M5.5 10v10h13V10"/><path d="M10 20v-5h4v5"/>',
    "origem": ('<ellipse cx="12" cy="6" rx="7" ry="2.8"/><path d="M5 6v4.5c0 1.5 3.1 2.8 7 2.8s7-1.3 7-2.8V6"/>'
               '<path d="M5 10.5V15c0 1.5 3.1 2.8 7 2.8s7-1.3 7-2.8v-4.5"/><path d="M12 18v3.5m-2.2-2 2.2 2 2.2-2"/>'),
    "orcamento": ('<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M8 6.5h8v3H8z"/>'
                  '<path d="M8.5 13h.01M12 13h.01M15.5 13h.01M8.5 16.5h.01M12 16.5h.01M15.5 16.5h.01"/>'),
    "contratacao": ('<path d="M14 3H6.5A1.5 1.5 0 0 0 5 4.5v15A1.5 1.5 0 0 0 6.5 21h11a1.5 1.5 0 0 0 1.5-1.5V8z"/>'
                    '<path d="M14 3v5h5"/><path d="M8 12h8M8 15.5h5"/><path d="M13 19c1-1.4 2-1.4 2.6 0 .5-.8 1.2-.9 1.9-.2"/>'),
    "liquidacao": ('<path d="M3.5 7.5 12 3.5l8.5 4v9L12 20.5l-8.5-4z"/><path d="M3.5 7.5 12 11.5l8.5-4M12 11.5v9"/>'
                   '<path d="m7.5 5.5 8.5 4"/>'),
    "pagamento": ('<rect x="2.5" y="6" width="19" height="12" rx="2"/><circle cx="12" cy="12" r="2.6"/>'
                  '<path d="M6 9.5v5M18 9.5v5"/>'),
    "prestacao": ('<rect x="5" y="4.5" width="14" height="16.5" rx="2"/><path d="M9 4.5V3h6v1.5"/>'
                  '<path d="m8.8 13 2.3 2.3 4.2-4.6"/>'),
    "consulta": '<circle cx="10.5" cy="10.5" r="6"/><path d="m15 15 5.5 5.5"/><path d="M8 10.5h5"/>',
    "secretarias": ('<path d="M4 21V5.5L12 3v18M12 8.5l8 2V21M3 21h18"/>'
                    '<path d="M7 8.5h2M7 12h2M7 15.5h2M15 13.5h2M15 17h2"/>'),
    "normas": ('<path d="M12 4v16M7 20h10M5 7.5h14"/><path d="m6.5 7.5-3 6.5h6zM17.5 7.5l-3 6.5h6z"/>'
               '<path d="M3.5 14a3 1.6 0 0 0 6 0M14.5 14a3 1.6 0 0 0 6 0"/>'),
    "conforme": '<circle cx="12" cy="12" r="9"/><path d="m7.8 12.4 2.8 2.8 5.6-6"/>',
    "alerta": '<path d="M12 3.2 21.6 20H2.4z"/><path d="M12 9.5v5M12 17.3v.2"/>',
    "semdado": ('<rect x="3.5" y="3.5" width="17" height="17" rx="3" stroke-dasharray="3.2 2.4"/>'
                '<path d="M9.7 9.6a2.4 2.4 0 1 1 3.3 2.2c-.7.3-1 .8-1 1.5v.5M12 16.6v.2"/>'),
    "hash": ('<path d="M12 2.6 20.2 7.3v9.4L12 21.4l-8.2-4.7V7.3z"/>'
             '<path d="M10.4 8.2 9.2 15.8M14.8 8.2l-1.2 7.6M8.1 10.4h8.3M7.6 13.6h8.3"/>'),
}

RASTREIO_PENDENTE = "rastreio começa na próxima coleta"


def rodape_rastreio(r: dict | None) -> str:
    """O topo da cadeia do rastreio por hash, no rodapé de todas as páginas, e se ela confere. Sem o
    arquivo do rastreio (banco ainda não migrado), a frase cinza de que o rastreio começa na próxima
    coleta, sem erro."""
    r = r or {}
    if not r.get("rastreado"):
        extra = " (o arquivo do rastreio não pôde ser lido nesta geração)" if r.get("erro") else ""
        return (f'<p class="rastreio-cadeia sem" id="rastreio-cadeia">{icone("hash", "hash sem")}'
                f'Rastreio por hash: {RASTREIO_PENDENTE}{extra}.</p>')
    u = r.get("ultima") or {}
    topo, raiz = u.get("hash") or "", u.get("raiz") or ""
    ok = r.get("ok")
    estado = ("a cadeia confere" if ok else
              f"a cadeia não confere ({r.get('problemas', 0)} problema(s); rode python -m onisciente rastreio)")
    quando = (u.get("fim") or u.get("inicio") or "")[:10]
    return (f'<p class="rastreio-cadeia {"ok" if ok else "falha"}" id="rastreio-cadeia" data-confere="{1 if ok else 0}">'
            f'{icone("hash", "hash " + ("ok" if ok else "falha"))}'
            f'Topo da cadeia do rastreio: rodada {escape(str(u.get("id", "")))}'
            + (f" de {escape(quando)}" if quando else "")
            + f', hash {_hash_copiavel(topo, "hash da rodada")}'
            + (f', raiz {_hash_copiavel(raiz, "raiz de Merkle da rodada")}' if raiz else "")
            + f'; {int(r.get("rodadas") or 0)} rodada(s); <b>{escape(estado)}</b>.</p>')


def _hash_copiavel(h: str, rotulo: str) -> str:
    """O hash curto (12 caracteres) com o completo no ``title`` e um botão que copia o completo."""
    h = h or ""
    return (f'<code class="hash" title="{escape(rotulo)}: {escape(h)}">{escape(h[:12])}</code>'
            f'<button type="button" class="copiar" data-copiar="{escape(h)}" aria-label="Copiar por inteiro: '
            f'{escape(rotulo)}">copiar</button>')


def simbolos() -> str:
    """O conjunto dos ícones, uma vez por página, para ``<use href="#i-nome">``."""
    return ('<svg xmlns="http://www.w3.org/2000/svg" class="simbolos" aria-hidden="true" focusable="false">'
            + "".join(f'<symbol id="i-{nome}" viewBox="0 0 24 24"><g fill="none" stroke="currentColor" '
                      f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{corpo}</g></symbol>'
                      for nome, corpo in ICONES.items()) + "</svg>")


def icone(nome: str, classe: str = "") -> str:
    return (f'<svg class="ic{(" " + classe) if classe else ""}" viewBox="0 0 24 24" aria-hidden="true" '
            f'focusable="false"><use href="#i-{nome}"/></svg>')


def regua(paginas: list[dict], atual: str) -> str:
    """A barra das etapas: cada grupo com o seu ícone e as suas telas, com a contagem do recorte."""
    partes = []
    for grupo, nome_icone in GRUPOS:
        links = []
        for p in paginas:
            if p["grupo"] != grupo:
                continue
            atual_attr = ' aria-current="page"' if p["id"] == atual else ""
            links.append(f'<a href="{p["id"]}.html" data-pagina="{p["id"]}"{atual_attr}>{escape(p["titulo"])}'
                         f'<span class="cont" data-cont="{p["id"]}"></span></a>')
        if links:
            partes.append(f'<div class="grupo"><span class="grupo-nome">{icone(nome_icone)}'
                          f'<span>{escape(grupo)}</span></span><div class="links">{"".join(links)}</div></div>')
    return (f'<nav class="regua" aria-label="Telas, pelas etapas do gasto público"><div class="wrap">'
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
{simbolos()}
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
      <p class="grupo-tela">{icone(_ICONE_DO_GRUPO.get(pagina["grupo"], "consulta"))}{escape(pagina["grupo"])}</p>
      <h1>{escape(pagina["titulo"])}</h1>
      <p class="pergunta">{escape(pagina["pergunta"])}.</p>
    </div>
    <p class="onde" id="onde" aria-live="polite"></p>
  </header>
  <div class="tela" id="tela"><p class="carregando">Montando a tela…</p></div>
  <noscript><p>Esta tela é desenhada no navegador a partir dos dados embutidos na própria página. Ative o
  JavaScript para ver os números, os recortes e a origem de cada dado.</p></noscript>
  <nav class="caminho" id="caminho" aria-label="Tela anterior e próxima, na ordem das etapas"></nav>
</main>
<footer class="rodape">
  <div class="wrap">
    <div>
      <p><b>Onisciente</b>, conferência da prestação de contas, etapa por etapa do gasto público. Cada número mostra a
      sua fonte ao passar o mouse ou tocar; o clique abre o original guardado. Alerta é indício, não acusação.</p>
      <p class="nota" id="gerado"></p>
      {rodape_rastreio(comum.get("rastreio"))}
    </div>
    <ul id="links-rodape">
      <li><a href="../index.html">Pareceres mensais</a></li>
      <li><a href="../banco/index.html">O banco de dados</a></li>
      <li><a href="indicios.html#busca-hash">Procurar por hash</a></li>
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


_ICONE_DO_GRUPO = dict(GRUPOS)
