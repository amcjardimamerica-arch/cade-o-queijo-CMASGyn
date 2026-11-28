"""Linguagem direta: o que o Onisciente mostra não usa a metáfora do rio.

Decisão do usuário de 28/11/2026: a imagem do rio era só um exemplo de fluxo para o desenho, não a premissa do
sistema. As travas daqui conferem a régua (acha a metáfora e deixa passar nome de lugar e palavra que só contém
"rio"), a troca dos textos guardados antes da decisão sem mexer em número, o parecer gerado e os pareceres já
publicados. As telas têm as suas travas em test_telas.py.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest

from onisciente.linguagem import direto, metaforas

RAIZ = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("texto", [
    "o rio do Município", "Os afluentes somados", "COSIP fora do leito", "água vinculada", "A foz: funções",
    "As margens do que não chegou", "FUNDEB (sangria)", "a nascente da receita", "Margens", "O rio-mapa",
    "A Foz: funções", "As Margens",
])
def test_a_regua_acha_a_metafora(texto):
    assert metaforas(texto), texto


@pytest.mark.parametrize("texto", [
    "Rio Verde", "Rio de Janeiro", "Foz do Iguaçu", "BEIRA RIO", "RIO-ORIGEM-FNAS-2026-10", "relatório", "rioja",
    "Prestação de contas", "margem de erro", "água mineral", "leitos de UTI", "o Rio Grande do Sul", "Rio Vermelho",
    "Município de Pires Do Rio: valor", "sede em Tres Rios/RJ",
])
def test_a_regua_deixa_passar_lugar_e_palavra_que_so_contem_rio(texto):
    assert metaforas(texto) == [], texto


def test_direto_troca_so_as_expressoes_e_nenhum_numero():
    antes = ("FNAS: empenhada fora do seu leito, na função 04 (R$ 1.234,56). Afluentes somados 9.876,54; "
             "FUNDEB entregue ao fundo (sangria) -12,00. Água parada: 3,00.")
    depois = direto(antes)
    assert metaforas(depois) == []
    assert re.findall(r"[\d.,]+\d", antes) == re.findall(r"[\d.,]+\d", depois)
    assert "fora da sua finalidade" in depois and "(dedução)" in depois and "Arrecadado e não empenhado" in depois
    assert direto(None) is None and direto("") == ""


def test_parecer_gerado_sem_metafora():
    from onisciente.nucleo import Selo
    from onisciente.panorama import Panorama
    from onisciente.parecer import html
    from onisciente.rio import Afluente, Esfera, Rio
    rio = Rio("2026-10", [Afluente("Fonte de teste", Esfera.MUNICIPAL, 100.0, "1751", Selo.AZUL,
                                   "previsto na LOA (lei publicada)")])
    p = Panorama(competencia="2026-10", alvo="Alvo de teste", dominio="Teste", rio=rio)
    pagina = html.gerar(p, hoje=date(2026, 11, 28))
    assert "<h2>2. Origem do dinheiro</h2>" in pagina and "<th>Funções permitidas</th>" in pagina
    assert metaforas(re.sub(r"<[^>]+>", " ", pagina)) == []


def test_pareceres_publicados_e_paginas_do_painel_sem_metafora():
    docs = RAIZ / "docs" / "onisciente"
    paginas = sorted(docs.glob("parecer_*.html")) + sorted((docs / "app").glob("*.html"))
    assert paginas
    for arq in paginas:
        texto = arq.read_text(encoding="utf-8")
        assert metaforas(re.sub(r"<[^>]+>", " ", texto)) == [], (arq.name, metaforas(texto)[:5])
    assert not (docs / "app" / "rio.html").exists() and (docs / "app" / "origem.html").exists()
