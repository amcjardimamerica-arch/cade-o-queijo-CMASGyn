"""Monta o site publicado no GitHub Pages com o painel na página inicial.

Pedido do usuário de 28/11/2026, 12:28Z: o endereço do painel fica só com "onisciente"
(o repositório passou a se chamar onisciente, e o Pages a responder em
amcjardimamerica-arch.github.io/onisciente/). O painel (docs/onisciente/app) vai para a raiz do site;
os pareceres, o banco, os ofícios e o selo (docs/onisciente) ficam ao lado dele; a lista dos pareceres
passa a ser pareceres.html; o relatório de empresas, que tinha o mesmo nome da tela de empresas,
passa a ser empresas-relatorio.html; e o acervo anterior do Cadê o Queijo (o resto de docs/) fica em
cmasgyn/. Nada em docs/ muda: o site é montado numa pasta à parte, no fluxo de publicação.

Uso: python -m onisciente site --saida _site
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DOCS = RAIZ / "docs"

# Ligações do painel (que vivia em onisciente/app/) para as páginas ao lado dele.
_DO_PAINEL = [
    ("../index.html", "pareceres.html"),
    ("../empresas.html", "empresas-relatorio.html"),
    ("../", ""),
]
# Ligações das páginas de docs/onisciente para o painel e para o relatório de empresas.
_DAS_PAGINAS = [
    ('"app/index.html"', '"index.html"'),
    ('"app/', '"'),
    ('"empresas.html"', '"empresas-relatorio.html"'),
]
_TEXTO = {".html", ".js", ".css", ".md", ".json"}


def _trocar(caminho: Path, trocas: list[tuple[str, str]]) -> None:
    if caminho.suffix not in _TEXTO:
        return
    texto = caminho.read_text(encoding="utf-8")
    novo = texto
    for de, para in trocas:
        novo = novo.replace(de, para)
    if novo != texto:
        caminho.write_text(novo, encoding="utf-8")


def montar(saida: Path, docs: Path = DOCS) -> dict:
    """Monta o site em ``saida`` (apagada antes) e devolve um resumo do que foi posto onde."""
    oni = docs / "onisciente"
    painel = oni / "app"
    if not (painel / "index.html").exists():
        raise FileNotFoundError(f"painel não encontrado em {painel}")
    if saida.exists():
        shutil.rmtree(saida)
    saida.mkdir(parents=True)

    # 1. As páginas do Onisciente (pareceres, banco, ofícios, selo), sem o painel.
    for item in oni.iterdir():
        if item.name == "app":
            continue
        destino = saida / item.name
        if item.is_dir():
            shutil.copytree(item, destino)
        else:
            shutil.copy2(item, destino)
    if (saida / "index.html").exists():
        (saida / "index.html").rename(saida / "pareceres.html")
    if (saida / "empresas.html").exists():
        (saida / "empresas.html").rename(saida / "empresas-relatorio.html")
    for arq in saida.rglob("*"):
        if arq.is_file():
            _trocar(arq, _DAS_PAGINAS)

    # 2. O painel na raiz.
    for item in painel.iterdir():
        destino = saida / item.name
        if item.is_dir():
            shutil.copytree(item, destino)
        else:
            shutil.copy2(item, destino)
            _trocar(destino, _DO_PAINEL)

    # 3. O acervo anterior do Cadê o Queijo em cmasgyn/.
    acervo = saida / "cmasgyn"
    acervo.mkdir()
    for item in docs.iterdir():
        if item.name == "onisciente":
            continue
        destino = acervo / item.name
        if item.is_dir():
            shutil.copytree(item, destino)
        else:
            shutil.copy2(item, destino)
    # O acervo apontava para o Onisciente em onisciente/; agora ele está um nível acima.
    for arq in acervo.rglob("*.html"):
        texto = arq.read_text(encoding="utf-8", errors="surrogateescape")
        novo = re.sub(r'(href|src)="onisciente/', r'\1="../', texto)
        if novo != texto:
            arq.write_text(novo, encoding="utf-8", errors="surrogateescape")

    (saida / ".nojekyll").write_text("", encoding="utf-8")
    return {
        "painel": sorted(p.name for p in painel.iterdir()),
        "paginas": sorted(p.name for p in oni.iterdir() if p.name != "app"),
        "acervo": sorted(p.name for p in docs.iterdir() if p.name != "onisciente"),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m onisciente site", description=__doc__.splitlines()[0])
    ap.add_argument("--saida", type=Path, default=Path("_site"))
    ap.add_argument("--docs", type=Path, default=DOCS)
    a = ap.parse_args(argv)
    r = montar(a.saida, a.docs)
    print(f"site em {a.saida}: painel na raiz ({len(r['painel'])} arquivos), "
          f"{len(r['paginas'])} páginas do Onisciente ao lado, acervo do Cadê o Queijo em cmasgyn/ "
          f"({len(r['acervo'])} itens)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
