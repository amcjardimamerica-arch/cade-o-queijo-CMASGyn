"""O mapa legal como régua: as nove áreas, cada limiar com valor, justificativa e base, e as regras que
as outras frentes leem (prazos dos demonstrativos, fontes federais)."""

from __future__ import annotations

from datetime import date

import pytest

from onisciente import tempo
from onisciente.legal.mapa import carregar

NOVAS = ("ACAO-GENERICA", "RP-NUNCA-LIQUIDADOS", "CUSTO-FIXO-SEM-ADITIVO", "FIM-DE-MANDATO-CAIXA",
         "FIM-DE-MANDATO-PESSOAL", "PISO-MAGISTERIO", "QUINQUENIO", "SERVIDOR-CONTRATADA", "CONTROLE-INTERNO",
         "JETON", "APOSENTADORIAS", "FGTS-DIA-20", "FOLHA-DIA-5", "PREVIDENCIA-DIA-20", "REVISAO-GERAL-ANUAL",
         "VALOR-DEVIDO", "CONTAS-PRAZOS", "PRAZO-DEMONSTRATIVOS", "ALUGUEL-M2", "BENEFICIOS-GESTORES",
         "PRESTACAO-PARCERIAS", "NEGAR-PUBLICIDADE", "RENUNCIA-SEM-ESTIMATIVA", "IPTU-AUMENTO", "CRECHE-META",
         "PRAZO-RREO", "PRAZO-RGF", "PRAZO-DCA", "PRAZO-MSC", "PRAZO-SIOPS", "CONTRATADA-SANCIONADA",
         "COTA-ESTADUAL-PUBLICACAO", "REPASSE-FUNDO-A-FUNDO-VIAS")


@pytest.fixture(scope="module")
def mapa():
    return carregar()


def test_mapa_sem_problemas_e_com_as_nove_areas(mapa):
    """Requisito 84: as nove áreas, cada uma com pelo menos uma regra e uma norma."""
    import yaml

    from onisciente.legal.mapa import CAMINHO_PADRAO as CAMINHO
    bruto = yaml.safe_load(CAMINHO.read_text(encoding="utf-8"))
    areas = bruto["areas"]
    assert len(areas) == 9
    assert mapa.problemas() == []
    for area in areas:
        assert any(r.get("area") == area for r in mapa.regras.values()), area
        assert any(n.area == area for n in mapa.normas.values()), area
    assert all(r.get("area") in areas for r in mapa.regras.values())


def test_cada_limiar_novo_tem_valor_justificativa_e_base(mapa):
    """Requisito 85: a régua completa, cada limiar documentado (valor, justificativa e base)."""
    for rid in NOVAS:
        r = mapa.regra(rid)
        assert r.get("justificativa"), rid
        assert r.get("base_do_limiar"), rid
        assert r.norma and "—" not in r.get("justificativa"), rid
        tem_numero = r.valor is not None or any(isinstance(v, (int, float, dict)) for v in r.extras.values())
        assert tem_numero or r.tipo == "ordem", rid


def test_servidor_em_contratada_fica_so_como_regra(mapa):
    """Requisito 88: a regra do art. 29 está no mapa com limiar zero; o cruzamento é da conferência de empresas."""
    r = mapa.regra("SERVIDOR-CONTRATADA")
    assert r.valor == 0 and "29" in r.norma and r.get("texto")


def test_prazos_dos_demonstrativos_lidos_pela_agenda(mapa):
    """Pedido da frente B: PRAZO-RREO, RGF, DCA, MSC e SIOPS no mapa, com o prazo da lei sem margem."""
    assert tempo.prazo_legal("RREO", 2025, 6, mapa) == (date(2026, 1, 30), "LC 101/2000, art. 52")
    assert tempo.prazo_legal("RGF", 2025, 3, mapa)[0] == date(2026, 1, 30)
    assert tempo.prazo_legal("DCA", 2025, 1, mapa)[0] == date(2026, 4, 30)
    assert tempo.prazo_legal("MSC", 2026, 1, mapa)[0] == date(2026, 2, 28)
    assert tempo.prazo_legal("SIOPS", 2026, 1, mapa)[0] == date(2026, 3, 30)
    assert mapa.regra("PRAZO-DCA").get("data_limite") == {"mes": 4, "dia": 30}


def test_regras_das_fontes_federais(mapa):
    """Pedido da frente D1: as três regras das conferências federais, com as normas indicadas."""
    s = mapa.regra("CONTRATADA-SANCIONADA")
    assert s.valor == 0 and "156" in s.norma and "12.846" in s.norma
    c = mapa.regra("COTA-ESTADUAL-PUBLICACAO")
    assert "162" in c.norma and "63/1990" in c.norma
    v = mapa.regra("REPASSE-FUNDO-A-FUNDO-VIAS")
    assert v.valor == pytest.approx(0.001) and "141/2012" in v.norma and "14.113" in v.norma


def test_limiares_restritivos(mapa):
    """Os limiares novos ficam no mais exigente que a lei e os dados sustentam: um dia, um real, zero."""
    assert mapa.regra("FIM-DE-MANDATO-PESSOAL").get("aumento_maximo") == 0.0
    assert mapa.regra("FIM-DE-MANDATO-CAIXA").valor == 0.0
    assert mapa.regra("CUSTO-FIXO-SEM-ADITIVO").valor == 1.0
    assert mapa.regra("RP-NUNCA-LIQUIDADOS").get("idade_maxima_exercicios") == 1
    assert mapa.regra("FOLHA-DIA-5").get("saldo_tolerado") == 1.0
    assert mapa.regra("APOSENTADORIAS").valor == 1.0
    assert mapa.regra("QUINQUENIO").get("tolerancia_meses") == 0


def test_prazo_legal_le_data_limite_e_meses_depois_do_mapa(mapa):
    """tempo.prazo_legal segue data_limite e meses_depois da regra, e não uma data escrita no código."""
    import copy
    outro = copy.deepcopy(mapa)
    outro.regras["PRAZO-DCA"].extras["data_limite"] = {"mes": 5, "dia": 15}
    outro.regras["PRAZO-MSC"].extras["meses_depois"] = 2
    assert tempo.prazo_legal("DCA", 2025, 1, outro)[0] == date(2026, 5, 15)
    assert tempo.prazo_legal("MSC", 2026, 1, outro)[0] == date(2026, 3, 31)
    assert tempo.prazo_legal("MSC", 2026, 12, mapa)[0] == date(2027, 1, 31)       # vira o ano


def test_lei_estadual_de_acesso_no_mapa_e_no_oficio_ao_estado(mapa):
    """Os ofícios ao Estado citam a Lei 12.527/2011 e a lei estadual de acesso de Goiás (Lei 18.025/2013)."""
    from datetime import date as _date

    from onisciente import lai
    from onisciente.nucleo.ausencias import Ausencia
    n = mapa.normas["lei-estadual-go-18-025-2013"]
    assert n.norma == "Lei estadual 18.025/2013" and n.localizada and "acesso à informação" in n.assunto.lower()
    assert lai.lei_estadual_de_acesso() == "Lei estadual 18.025/2013"
    [e] = lai.oficios_por_orgao([Ausencia("Cota do ICMS", "x", "Portal",
                                          orgao="Secretaria de Estado da Economia de Goiás")], "Assunto")
    texto = e.texto(hoje=_date(2026, 11, 28))
    assert "Lei 12.527/2011" in texto and "Lei estadual 18.025/2013" in texto and "9.262" not in texto
    [m] = lai.oficios_por_orgao([Ausencia("Empenhos", "x", "Portal", orgao=lai.CGM)], "Assunto")
    assert "18.025" not in m.texto(hoje=_date(2026, 11, 28))
