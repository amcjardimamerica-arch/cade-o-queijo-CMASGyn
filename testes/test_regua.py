"""Régua: mapa legal, alvo, domínios, rio e pisos."""

from datetime import date

import pytest

from onisciente.config import carregar_alvo
from onisciente.legal.mapa import carregar
from onisciente.pisos import Lancamento, fichas_da_medida, gasto_de_piso, medir
from onisciente.rio import Afluente, Esfera, Margens, Rio, classificar, desvio_de_finalidade


@pytest.fixture(scope="module")
def mapa():
    return carregar()


# --- Mapa legal ---------------------------------------------------------------

def test_mapa_legal_sem_problemas(mapa):
    assert mapa.problemas() == []
    assert len(mapa.normas) >= 60
    assert len(mapa.regras) >= 20


def test_toda_regra_tem_norma_e_numero(mapa):
    for r in mapa.regras.values():
        assert r.norma, r.id
        if r.tipo in {"minimo", "maximo", "tolerancia", "prazo"}:
            assert r.valor is not None or r.get("faixas") or r.get("outros"), r.id


def test_parametros_constitucionais(mapa):
    assert mapa.regra("PISO-SAUDE").valor == 15
    assert mapa.regra("PISO-EDUCACAO").valor == 25
    assert mapa.regra("FUNDEB-PROFISSIONAIS").valor == 70
    pessoal = mapa.regra("PESSOAL-EXECUTIVO")
    assert (pessoal.valor, pessoal.get("alerta"), pessoal.get("prudencial")) == (54, 48.6, 51.3)
    assert mapa.regra("CAMARA").get("faixas")["IV"] == 4.5


def test_normas_federais_apontam_para_o_ctresb(mapa):
    lrf = [n for n in mapa.normas.values() if "LC 101/2000" in n.norma]
    assert lrf and any("lcp-101-2000-05-04.md" in c for n in lrf for c in n.ctresb)


def test_endereco_previsivel_do_sileg(mapa):
    url = mapa.url_sileg("lo", date(2026, 1, 9), 11590)
    assert url.endswith("/legis/2026/lo_20260109_000011590.html")
    with pytest.raises(ValueError):
        mapa.url_sileg("xx", date(2026, 1, 1), 1)


def test_norma_revogada_sai_das_vigentes(mapa):
    assert all(not n.revogada for n in mapa.vigentes())


def test_alvo_e_dominios():
    alvo = carregar_alvo()
    assert alvo.ibge == 5208707 and alvo.faixa_camara == "IV"
    # Decisão do coordenador (27/11/2026, requisito 108): as seis secretarias da trilha ativas,
    # nesta ordem. Um domínio que entre ou saia sem querer quebra este teste.
    assert [d.id for d in alvo.ativos()] == ["assistencia", "saude", "educacao", "infraestrutura",
                                              "comurg", "administracao"]
    for d in alvo.dominios.values():
        assert d.problemas() == [], d.id


# --- Rio ------------------------------------------------------------------------

def test_classificar_fontes():
    assert classificar("1500").vinculada is False
    f = classificar("1660")
    assert f.vinculada and f.exercicio == "corrente" and f.destinacao.esfera is Esfera.FEDERAL
    assert classificar("2660").exercicio == "anteriores"
    assert not classificar("1999").conhecida


def test_agua_vinculada_no_leito_errado_e_desvio():
    assert desvio_de_finalidade("1600", "10") is False
    assert desvio_de_finalidade("1600", "12") is True     # SUS na educação
    assert desvio_de_finalidade("1660", "8") is False      # função 08
    assert desvio_de_finalidade("1500", "04") is False     # água livre
    assert desvio_de_finalidade("1700", "04") is None      # convênio: confere pelo objeto
    assert desvio_de_finalidade("1999", "04") is None


def test_rio_separa_vinculada_e_livre():
    r = Rio("2026-03", [Afluente("FNAS", Esfera.FEDERAL, 100, "1660"),
                        Afluente("Tesouro", Esfera.MUNICIPAL, 50, "1500"),
                        Afluente("Sem fonte", Esfera.MISTA, 10)])
    assert r.total() == 160
    assert r.vinculada_e_livre() == {"vinculada": 100, "livre": 50, "sem_fonte": 10}
    assert r.por_esfera()[Esfera.FEDERAL] == 100


def test_margens_do_rio():
    m = Margens(previsto=100, empenhado=80, liquidado=60, pago=50, pago_com_vinculo=20)
    assert m.como_dict() == {"previsto_nao_empenhado": 20, "empenhado_nao_liquidado": 20,
                             "liquidado_nao_pago": 10, "pago_sem_vinculo": 30}


# --- Pisos ----------------------------------------------------------------------

def test_gasto_de_piso_segue_as_tres_regras_do_motor():
    lanc = [
        Lancamento(100, "1500", "10"),                       # conta
        Lancamento(500, "1600", "10"),                       # SUS: vinculada, nunca conta
        Lancamento(40, "1500", "12"),                        # outra função
        Lancamento(0, "1500", "10", restos_a_pagar=80),      # restos só até o caixa
        Lancamento(30, "1999", "10"),                        # fonte desconhecida não se presume livre
    ]
    assert gasto_de_piso(lanc, "10", caixa_para_restos=50) == 150


def test_piso_de_saude_cumprido_com_segunda_via_verde(mapa):
    m = medir("PISO-SAUDE", 160, 1000, declarado=16.05, mapa=mapa)
    assert m.situacao == "cumpre" and m.selo.value == "verde" and not m.divergencia


def test_divergencia_acima_de_um_por_cento_e_indicio(mapa):
    m = medir("PISO-EDUCACAO", 260, 1000, declarado=27.0, mapa=mapa)
    assert m.cumpre and m.divergencia
    fichas = fichas_da_medida(m, competencia="2025-12")
    assert [f.codigo for f in fichas] == ["PISO-DIV-PISO-EDUCACAO-2025-12"]


def test_teto_de_pessoal_com_alerta_e_prudencial(mapa):
    assert medir("PESSOAL-EXECUTIVO", 47, 100, mapa=mapa).situacao == "cumpre"
    assert medir("PESSOAL-EXECUTIVO", 49, 100, mapa=mapa).situacao == "alerta"
    assert medir("PESSOAL-EXECUTIVO", 52, 100, mapa=mapa).situacao == "prudencial"
    m = medir("PESSOAL-EXECUTIVO", 55, 100, mapa=mapa)
    assert m.situacao == "descumpre"
    assert fichas_da_medida(m, competencia="2026-04")[0].gravidade.value == "critica"


def test_camara_usa_a_faixa_do_alvo(mapa):
    assert medir("CAMARA", 4.6, 100, faixa="IV", mapa=mapa).situacao == "descumpre"
    assert medir("CAMARA", 4.6, 100, faixa="III", mapa=mapa).situacao == "cumpre"
    with pytest.raises(ValueError):
        medir("CAMARA", 4.6, 100, mapa=mapa)


def test_piso_sem_dado_e_roxo_e_nao_vira_ficha(mapa):
    m = medir("IGD-CONTROLE-SOCIAL", None, 140625.21, mapa=mapa)
    assert m.situacao == "sem_dado" and m.selo.value == "roxo"
    assert fichas_da_medida(m, competencia="2026-10") == []
