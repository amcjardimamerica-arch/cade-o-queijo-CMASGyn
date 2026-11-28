"""O parecer recebe as seções das outras frentes pelos pontos combinados: execução da pasta (D2), empresas
contratadas (F), auditoria do selo (E), seções externas registradas; e a coluna de valor e o leito
dizem a verdade sobre a origem e o catálogo das fontes."""

from __future__ import annotations

from datetime import date

from onisciente.nucleo import Selo
from onisciente.panorama import Panorama
from onisciente.parecer import html
from onisciente.rio import Afluente, Esfera, Rio


def _panorama(origem: str = "", fonte: str = "1999") -> Panorama:
    rio = Rio("2026-10", [Afluente("Fonte de teste", Esfera.MUNICIPAL, 100.0, fonte, Selo.AZUL, origem)])
    return Panorama(competencia="2026-10", alvo="Alvo de teste", dominio="Teste", rio=rio)


def test_cabecalho_segue_a_origem_do_afluente_e_leito_fora_do_catalogo():
    pagina = html.gerar(_panorama("pago no exercício até o 5º bimestre, matriz de saldos contábeis"),
                        hoje=date(2026, 11, 27))
    assert "<th>Pago no exercício</th>" in pagina and "<th>Previsto no mês</th>" not in pagina
    assert "<td>fora do catálogo</td>" in pagina
    previsto = html.gerar(_panorama("previsto na LOA (lei publicada)", "1500"), hoje=date(2026, 11, 27))
    assert "<th>Previsto no mês</th>" in previsto and "fora do catálogo" not in previsto


def test_secao_da_execucao_entra_no_lugar_do_aviso(monkeypatch):
    from onisciente.rio import parecer_dominio
    monkeypatch.setattr(parecer_dominio, "secao_execucao", lambda ex, contas, q: "<h3>EXECUCAO-DA-PASTA</h3>")
    p = _panorama()
    sem = html.gerar(p, hoje=date(2026, 11, 27))
    assert parecer_dominio.AVISO_DA_SECAO_4 in sem and "EXECUCAO-DA-PASTA" not in sem
    p.execucao = object()
    com = html.gerar(p, hoje=date(2026, 11, 27))
    assert "EXECUCAO-DA-PASTA" in com and parecer_dominio.AVISO_DA_SECAO_4 not in com
    assert com.index("4. As contas, uma a uma") < com.index("EXECUCAO-DA-PASTA") < com.index("5. Preço e entrega")


def test_secao_das_empresas_ao_lado_das_compras(monkeypatch):
    from onisciente.conferencias import empresas
    monkeypatch.setattr(empresas, "secao_parecer", lambda conf, comp: "<p>EMPRESAS-DA-PASTA</p>")
    p = _panorama()
    p.empresas = object()
    pagina = html.gerar(p, hoje=date(2026, 11, 27))
    secao5 = pagina[pagina.index("5. Preço e entrega"):pagina.index("6. Prestação de contas")]
    assert "Empresas contratadas" in secao5 and "EMPRESAS-DA-PASTA" in secao5


def test_selo_so_no_alvo_configurado_e_sem_fichas_fora_da_secao_7(monkeypatch):
    from onisciente.selo import relatorio
    ficha = relatorio._ficha_html({"gravidade": "alta", "titulo": "x", "codigo": "PCT-SELO-1",
                                   "verificacao": "inconclusivo", "como_deveria": "a", "norma": "n",
                                   "como_esta": "b", "providencia": "p"})
    monkeypatch.setattr(relatorio, "secao_parecer", lambda: '<h2 id="selo">Selo de teste</h2>' + ficha)
    outro = html.gerar(_panorama(), hoje=date(2026, 11, 27))
    assert "Selo de teste" not in outro                       # outro Município: a auditoria é do alvo
    p = _panorama()
    monkeypatch.setattr(Panorama, "do_alvo_configurado", lambda self: True)
    pagina = html.gerar(p, hoje=date(2026, 11, 27))
    assert pagina.index("Selo de teste") < pagina.index("9. Custódia")
    assert pagina.count('class="ficha ') == len(p.fichas) == 0


def test_secao_externa_registrada_entra_depois_da_custodia():
    marca = html.registrar_secao(lambda p, hoje: f"<h2>Externa {p.competencia}</h2>")
    try:
        assert html.registrar_secao(marca) is marca and html.SECOES_EXTERNAS.count(marca) == 1
        pagina = html.gerar(_panorama(), hoje=date(2026, 11, 27))
        assert pagina.index("9. Custódia") < pagina.index("<h2>Externa 2026-10</h2>")
    finally:
        html.SECOES_EXTERNAS.remove(marca)


def test_indice_liga_agenda_e_oficios():
    pagina = html.indice([("2026-10", "parecer_2026-10.html")], "Alvo")
    assert 'href="agenda.html"' in pagina and 'href="oficios/index.html"' in pagina


def test_notas_fiscais_no_pncp_citam_o_inciso_vi():
    """Lei 14.133/2021, art. 174, § 2º: V é contratos e aditivos; VI é notas fiscais eletrônicas."""
    import inspect

    from onisciente.conferencias import compras
    fonte = inspect.getsource(compras)
    assert "art. 174, § 2º, VI" in fonte and "174, § 2º, V;" not in fonte


def test_indice_abre_o_painel_no_topo():
    """Pedido da frente A: o índice dos pareceres leva ao painel (app/index.html), antes de tudo o mais."""
    pagina = html.indice([("2026-10", "parecer_2026-10.html")], "Alvo")
    assert '<a href="app/index.html">Abrir o painel do Onisciente</a>' in pagina
    assert pagina.index("app/index.html") < pagina.index("Pareceres mensais")


def test_parecer_usa_as_series_das_telas(monkeypatch):
    """Pedido da frente A: o parecer e as telas desenham as mesmas séries mensais (series_do_parecer),
    só para o alvo configurado, na seção 2, sem o tema escuro das telas e sem quebrar a numeração."""
    from onisciente.telas import graficos
    chamadas = []

    def falsa(competencia, *, banco=graficos.BANCO):
        chamadas.append((competencia, banco))
        return (f'<section class="series-onisciente">{graficos.ESTILO}<h2>SERIES-DAS-TELAS</h2>'
                "<figure><svg></svg></figure></section>")

    monkeypatch.setattr(graficos, "series_do_parecer", falsa)
    assert "SERIES-DAS-TELAS" not in html.gerar(_panorama(), hoje=date(2026, 11, 27)) and not chamadas
    monkeypatch.setattr(Panorama, "do_alvo_configurado", lambda self: True)
    pagina = html.gerar(_panorama(), hoje=date(2026, 11, 27))
    assert chamadas == [("2026-10", graficos.BANCO)]
    assert pagina.index("2. O rio") < pagina.index("<h3>SERIES-DAS-TELAS</h3>") < pagina.index("3. Pisos e tetos")
    assert "prefers-color-scheme" not in pagina and "<h2>SERIES-DAS-TELAS" not in pagina


def test_series_do_parecer_no_banco_real():
    """No banco histórico do alvo, o trecho das telas entra no parecer com os três gráficos."""
    import pytest

    from onisciente.telas import graficos
    if not graficos.BANCO.exists():
        pytest.skip("banco histórico ausente")
    p = _panorama()
    p.competencia = "2026-02"
    p.do_alvo_configurado = lambda: True
    trecho = html._series_mensais(p)
    assert trecho.count("<svg") == 3 and "<h3>As séries de 2026" in trecho
