"""Trava do pedido do usuário de 28/11/2026, 12:28Z: o painel abre direto no endereço do site
(amcjardimamerica-arch.github.io/onisciente/), sem caminho intermediário."""
from pathlib import Path

from onisciente import site


def _docs(tmp: Path) -> Path:
    docs = tmp / "docs"
    app = docs / "onisciente" / "app"
    app.mkdir(parents=True)
    (app / "index.html").write_text('<a href="../index.html">Pareceres</a><a href="../parecer_2026-10.html">p</a>'
                                    '<a href="../banco/index.html">b</a><a href="empresas.html">tela</a>'
                                    '<a href="../empresas.html">rel</a>', encoding="utf-8")
    (app / "empresas.html").write_text("tela de empresas", encoding="utf-8")
    (app / "app.js").write_text('const x = "../banco/index.html";', encoding="utf-8")
    oni = docs / "onisciente"
    (oni / "index.html").write_text('<a href="app/index.html">Painel</a><a href="parecer_2026-10.html">p</a>',
                                    encoding="utf-8")
    (oni / "empresas.html").write_text('relatório', encoding="utf-8")
    (oni / "parecer_2026-10.html").write_text('<a href="empresas.html">e</a><a href="app/indicios.html">i</a>',
                                              encoding="utf-8")
    (oni / "banco").mkdir()
    (oni / "banco" / "index.html").write_text("banco", encoding="utf-8")
    (docs / "index.html").write_text('<a href="onisciente/index.html">Onisciente</a>', encoding="utf-8")
    return docs


def test_painel_na_raiz_e_as_ligacoes_continuam_certas(tmp_path):
    saida = tmp_path / "_site"
    site.montar(saida, _docs(tmp_path))
    raiz = (saida / "index.html").read_text(encoding="utf-8")
    assert 'href="pareceres.html"' in raiz and 'href="parecer_2026-10.html"' in raiz
    assert 'href="banco/index.html"' in raiz and 'href="empresas-relatorio.html"' in raiz
    assert "../" not in raiz and "../" not in (saida / "app.js").read_text(encoding="utf-8")
    assert (saida / "empresas.html").read_text(encoding="utf-8") == "tela de empresas"
    assert (saida / "empresas-relatorio.html").read_text(encoding="utf-8") == "relatório"
    assert 'href="index.html"' in (saida / "pareceres.html").read_text(encoding="utf-8")
    parecer = (saida / "parecer_2026-10.html").read_text(encoding="utf-8")
    assert 'href="empresas-relatorio.html"' in parecer and 'href="indicios.html"' in parecer
    assert (saida / "banco" / "index.html").exists() and not (saida / "app").exists()
    acervo = (saida / "cmasgyn" / "index.html").read_text(encoding="utf-8")
    assert 'href="../index.html"' in acervo
    assert (saida / ".nojekyll").exists()


def test_o_fluxo_de_publicacao_monta_o_site_e_nao_publica_docs_cru():
    fluxo = (Path(__file__).resolve().parent.parent / ".github" / "workflows" / "publicar-painel.yml").read_text(
        encoding="utf-8")
    assert "python -m onisciente.site --saida _site" in fluxo
    assert "path: _site" in fluxo and "path: docs" not in fluxo
