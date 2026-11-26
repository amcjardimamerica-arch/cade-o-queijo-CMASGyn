"""Núcleo: níveis de prova, selos, estações, fichas, ausências e integridade."""

from datetime import date

import pytest

from onisciente.nucleo import (Ausencia, Estacao, Evento, Familia, IndiceIntegridade, Nivel,
                               Original, Percurso, Selo, Verificacao, Via, emitir, selar)
from onisciente.nucleo.custodia import impressao
from onisciente.nucleo.estacoes import integridade_da_trilha
from onisciente.nucleo.indicios import LEGADO_SOB, familia_do_legado, ordenar
from onisciente.nucleo.provas import (pode_afirmar_irregularidade, pode_afirmar_pagamento,
                                      pode_afirmar_vinculo)
from onisciente.nucleo.selos import Gravidade


# --- Níveis de prova e as três travas --------------------------------------

def test_pesos_dos_niveis():
    assert [n.peso for n in Nivel] == [5, 4, 3, 2, 1, 0]
    assert Nivel.de("b") is Nivel.B


def test_pagamento_so_com_a_ou_b():
    assert pode_afirmar_pagamento("A") and pode_afirmar_pagamento(Nivel.B)
    assert not pode_afirmar_pagamento(Nivel.C)
    assert not pode_afirmar_pagamento(Nivel.E)


def test_vinculo_exige_instrumento():
    assert pode_afirmar_vinculo(Nivel.C)
    assert not pode_afirmar_vinculo(Nivel.D)


def test_irregularidade_exige_duas_fontes_de_niveis_distintos():
    assert not pode_afirmar_irregularidade([Nivel.B])
    assert not pode_afirmar_irregularidade([Nivel.B, Nivel.B])
    assert not pode_afirmar_irregularidade([Nivel.B, Nivel.F])  # ausência não conta
    assert pode_afirmar_irregularidade([Nivel.B, Nivel.C])


# --- Selos ------------------------------------------------------------------

def test_duas_vias_que_batem_dao_selo_verde():
    c = selar([Via("Diário Oficial", 100.0), Via("SICONFI", 100.5)])
    assert c.selo is Selo.VERDE and not c.divergencia


def test_divergencia_rebaixa_para_azul_e_vira_indicio():
    c = selar([Via("Diário Oficial", 100.0), Via("SICONFI", 120.0)])
    assert c.selo is Selo.AZUL and c.divergencia


def test_uma_via_e_azul_mesmo_repetida():
    c = selar([Via("Diário Oficial", 10.0), Via("Diário Oficial", 10.0)])
    assert c.selo is Selo.AZUL


def test_sem_via_e_roxo_quando_a_lei_manda_publicar():
    assert selar([], exigido_por_lei=True).selo is Selo.ROXO
    assert selar([Via("Portal", None)], leitura_falhou=True).selo is Selo.VERMELHO
    assert selar([]).selo is None


def test_selo_nao_e_gravidade():
    assert Gravidade.de("crítica") is Gravidade.CRITICA
    assert {s.value for s in Selo} == {"verde", "azul", "roxo", "vermelho"}


def test_verificacao_le_o_rotulo_antigo():
    assert Verificacao.de("INCONCLUSIVO_POR_DOCUMENTO_FALTANTE") is Verificacao.INCONCLUSIVO
    assert Verificacao.de("INDICIÁRIO") is Verificacao.INDICIARIO


# --- Custódia ---------------------------------------------------------------

def test_custodia_prova_o_que_estava_la():
    o = Original.de_texto("https://exemplo.gov.br/do.pdf", "texto lido", coletado_em="2026-11-01")
    assert o.sha256 == impressao("texto lido")
    assert o.confere("texto lido") and not o.confere("texto trocado")


# --- Estações ---------------------------------------------------------------

def test_nove_estacoes_com_nivel_minimo():
    assert len(Estacao) == 9
    assert Estacao.PAGAMENTO.nivel_minimo is Nivel.B
    assert Estacao.VINCULO.nivel_minimo is Nivel.C
    assert Estacao.PREVISAO.acende_com(Nivel.D)
    assert not Estacao.EMPENHO.acende_com(Nivel.C)
    assert Estacao.de("repasse") is Estacao.ORIGEM  # nome antigo do Cadê o Queijo


def _percurso_completo(chave, valor, d_liq=date(2026, 3, 10), d_pag=date(2026, 3, 20)):
    eventos = [Evento(e, Nivel.A if e is Estacao.PAGAMENTO else e.nivel_minimo,
                      valor=valor if e is Estacao.PAGAMENTO else None) for e in Estacao]
    eventos = [ev for ev in eventos if ev.estacao not in (Estacao.EMPENHO, Estacao.LIQUIDACAO,
                                                          Estacao.PAGAMENTO)]
    eventos += [Evento(Estacao.EMPENHO, Nivel.B, data=date(2026, 3, 1)),
                Evento(Estacao.LIQUIDACAO, Nivel.B, data=d_liq),
                Evento(Estacao.PAGAMENTO, Nivel.A, valor=valor, data=d_pag)]
    return Percurso(chave, eventos)


def test_percurso_completo_e_integridade_da_trilha():
    p1 = _percurso_completo("e1", 300.0)
    p2 = Percurso("e2", [Evento(Estacao.PAGAMENTO, Nivel.B, valor=100.0)])
    assert p1.completo and not p2.completo
    assert Estacao.VINCULO in p2.faltantes()
    assert integridade_da_trilha([p1, p2]) == pytest.approx(0.75)
    assert integridade_da_trilha([]) == 0.0


def test_pagamento_antes_da_liquidacao_viola_a_ordem():
    p = _percurso_completo("e3", 10.0, d_liq=date(2026, 3, 25), d_pag=date(2026, 3, 20))
    assert any("antes da liquidação" in x for x in p.ordem_violada())
    sem_liq = Percurso("e4", [Evento(Estacao.PAGAMENTO, Nivel.A, valor=5, data=date(2026, 1, 2))])
    assert any("sem liquidação" in x for x in sem_liq.ordem_violada())


def test_estacao_nao_acende_com_prova_fraca():
    p = Percurso("e5", [Evento(Estacao.PAGAMENTO, Nivel.E, valor=50.0)])
    assert p.valor_pago() == 0.0


# --- Fichas -----------------------------------------------------------------

def _ficha(**kw):
    base = dict(codigo="X-1", familia=Familia.VIN, titulo="t", gravidade="alta",
                como_deveria="d", norma="n", como_esta="e")
    base.update(kw)
    return emitir(**base)


def test_verificacao_decidida_pelas_travas():
    assert _ficha(niveis=["B", "C"]).verificacao is Verificacao.CONFIRMADO
    assert _ficha(niveis=["B"]).verificacao is Verificacao.INDICIARIO
    assert _ficha(niveis=[]).verificacao is Verificacao.INCONCLUSIVO
    assert _ficha(niveis=["B", "C"], documento_faltante=True).verificacao is Verificacao.INCONCLUSIVO


def test_homonimo_nunca_passa_de_indiciario():
    f = _ficha(niveis=["B", "C"], por_coincidencia_de_nome=True)
    assert f.verificacao is Verificacao.INDICIARIO


def test_fichas_saem_por_gravidade():
    fs = ordenar([_ficha(codigo="b", gravidade="media"), _ficha(codigo="a", gravidade="critica")])
    assert [f.gravidade for f in fs] == [Gravidade.CRITICA, Gravidade.MEDIA]


def test_catalogo_sob_mantido():
    assert set(LEGADO_SOB) == {f"SOB-0{i}" for i in range(1, 8)}
    assert familia_do_legado("SOB-06") is Familia.VIN
    assert familia_do_legado("SOB-05") is Familia.PCT
    assert familia_do_legado("IGD-M-2026-10") is Familia.PISO
    assert familia_do_legado("CTA-01") is Familia.CTA


def test_ficha_vira_dicionario_com_as_sete_partes():
    d = _ficha(niveis=["B"], providencia="pedir", caso_semelhante="TCM").como_dict()
    for parte in ("titulo", "gravidade", "como_deveria", "como_esta", "verificacao",
                  "providencia", "caso_semelhante", "custodia"):
        assert parte in d


# --- Ausência e integridade -----------------------------------------------------

def test_ausencia_responde_as_tres_perguntas_e_e_roxa():
    a = Ausencia("Empenhos de março", "empenho e pagamento", "Portal da Transparência")
    assert a.selo is Selo.ROXO
    assert "48-A" in a.fundamento
    assert set(a.como_dict()) >= {"o_que_falta", "conferencia_impedida", "onde_deveria_estar"}


def test_indice_de_integridade_pesa_40_25_15_10_10():
    cheio = IndiceIntegridade(1, 1, 1, 1, 1)
    assert cheio.nota == 100 and not cheio.gera_pedido_de_acesso
    i = IndiceIntegridade(cobertura=0.5, coerencia=0, tempestividade=1, vinculo=0.5, prestacao=0)
    assert i.nota == pytest.approx(40)
    assert i.gera_pedido_de_acesso
    assert IndiceIntegridade(2, -1, 0, 0, 0).nota == 40  # frações fora de 0..1 são aparadas
