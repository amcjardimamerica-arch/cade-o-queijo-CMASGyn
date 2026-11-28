"""O rio do Município inteiro (bloco 3): espécies, fontes, as três conferências, o ritmo e o leito.

Os números de 2026 são os do banco histórico (RREO do 4º bimestre e matriz de saldos contábeis de
janeiro a outubro, Portal da Transparência no mesmo período). As adulterações rodam numa cópia do banco.
"""

from __future__ import annotations

from datetime import date

import pytest

from onisciente import RAIZ, partes
from onisciente.adaptadores import cadeoqueijo
from onisciente.fiscal import Leitor
from onisciente.nucleo import Selo
from onisciente.nucleo.indicios import Familia
from onisciente.parecer import html, svg
from onisciente.rio import Afluente, Esfera, Rio
from onisciente.rio import matriz as mz
from onisciente.rio import municipio

BANCO = RAIZ / "dados" / "onisciente" / "historico.db"
pytestmark = pytest.mark.skipif(not BANCO.exists(), reason="banco histórico ausente")
OUT = date(2026, 10, 31)


def _montar(banco=BANCO, ate=OUT):
    lt = Leitor(banco)
    try:
        return municipio.montar(lt, lt.ultimo("RREO", ate), ate=ate)
    finally:
        lt.fechar()


@pytest.fixture(scope="module")
def rm():
    return _montar()


def _conf(rm, titulo, tipo):
    return next(c for c in rm.conferencias if c.titulo == titulo and c.tipo == tipo)


# --- O rio e as suas contas -----------------------------------------------------------------------

def test_rio_fecha_ao_centavo_com_a_receita_realizada_do_rreo(rm):
    assert rm.rotulo == "RREO do 4º bimestre de 2026"
    assert rm.liquido == pytest.approx(rm.realizado_declarado, abs=0.01)
    assert rm.realizado_declarado == pytest.approx(7_069_819_837.61, abs=0.01)
    for c in rm.conferencias:
        if c.tipo == municipio.Tipo.MESMO_RELATORIO:
            assert c.selo is Selo.VERDE and not c.certificacao.divergencia, c.titulo


def test_cada_especie_confere_com_a_matriz_de_saldos_contabeis(rm):
    entre = [c for c in rm.conferencias if c.tipo == municipio.Tipo.ENTRE_DEMONSTRATIVOS]
    titulos = {c.titulo for c in entre}
    assert {e.nome for e in municipio.CORRENTES} <= titulos
    assert {"Receitas de capital", "Receita realizada (Anexo 1 e matriz)", "Despesa empenhada",
            "Despesa liquidada", "Despesa paga"} <= titulos
    for c in entre:
        assert c.selo is Selo.VERDE, c.titulo
        rreo, msc = (v.valor for v in c.certificacao.vias)
        assert rreo == pytest.approx(msc, abs=0.05), c.titulo
    assert _conf(rm, "Despesa empenhada", municipio.Tipo.ENTRE_DEMONSTRATIVOS).certificacao.vias[0].valor == \
        pytest.approx(8_609_003_089.53, abs=0.01)


def test_rreo_e_matriz_iguais_em_todos_os_bimestres_de_2025_e_2026():
    """Onze RREO, cada um contra a matriz dos mesmos meses, à tolerância do arredondamento (1e-6).

    No 6º bimestre o liquidado inclui o inscrito em restos a pagar processados (6.2.2.1.3.07).
    """
    lt = Leitor(BANCO)
    try:
        periodos = [p for p in lt.periodos("RREO") if p.exercicio >= 2025]
        assert len(periodos) >= 10
        for per in periodos:
            rm = municipio.montar(lt, per, ate=per.termina)
            entre = [c for c in rm.conferencias if c.tipo == municipio.Tipo.ENTRE_DEMONSTRATIVOS]
            assert len(entre) == len(municipio.CORRENTES) + 5, per
            for c in entre:
                assert c.selo is Selo.VERDE and not c.detalhe, (per, c.titulo)
            assert rm.liquido == pytest.approx(rm.realizado_declarado, abs=0.05), per
    finally:
        lt.fechar()


def test_afluentes_abrem_pelas_fontes_registradas_e_a_esfera_vem_da_especie(rm):
    por_nome = {}
    for a in rm.rio.afluentes:
        por_nome.setdefault(a.nome.split(":")[0], []).append(a)
    # o FPM é da União mesmo entrando na fonte livre 1500
    fpm = por_nome["FPM"]
    assert len(fpm) == 1 and fpm[0].fonte == "1500" and fpm[0].esfera is Esfera.FEDERAL
    # as espécies mistas tomam a esfera da destinação
    fnas = [a for a in por_nome["Outras transferências correntes"] if a.fonte == "1660"]
    assert fnas and fnas[0].esfera is Esfera.FEDERAL
    # a soma dos afluentes de cada espécie é a espécie do RREO
    especie = sum(sum(m.values()) for n, m in rm.meses.items() if n == "Taxas e outros tributos")
    assert sum(a.valor for a in por_nome["Taxas e outros tributos"]) == pytest.approx(especie, abs=0.01)
    # e a fonte diz se a água é vinculada ou livre
    vl = rm.rio.vinculada_e_livre()
    assert vl["vinculada"] > 0 and vl["livre"] > 0
    assert sum(vl.values()) == pytest.approx(rm.rio.total(), abs=0.01)


def test_receitas_de_capital_entram_pelo_anexo_1(rm):
    op = [a for a in rm.rio.afluentes if a.nome == "Operações de crédito"]
    assert op and op[0].fonte == "1754" and op[0].valor == pytest.approx(293_846_000.00, abs=0.01)


# --- A origem: o que a União transferiu contra o que o Município registrou ------------------------

def test_origem_confere_fpm_itr_royalties_e_aponta_fnas(rm):
    origem = {c.titulo: c for c in rm.conferencias if c.tipo == municipio.Tipo.ENTRE_FONTES}
    for nome in ("FPM", "Cota-parte do ITR", "Royalties do petróleo e da mineração"):
        assert origem[nome].selo is Selo.VERDE and not origem[nome].certificacao.divergencia, nome
    fnas = origem["FNAS (assistência social)"]
    assert fnas.certificacao.divergencia and fnas.selo is Selo.AZUL
    siafi, municipio_ = (v.valor for v in fnas.certificacao.vias)
    assert siafi == pytest.approx(9_140_489, abs=1) and municipio_ == pytest.approx(5_261_009, abs=1)
    # o recurso que entrou, mas fora da fonte que o vincula
    assert any("natureza 17199901, fonte 1706" in d and "fora da fonte que o vincula" in d for d in fnas.detalhe)
    fichas = {f.codigo: f for f in rm.fichas("2026-10")}
    f = fichas["RIO-ORIGEM-FNAS-ASSISTENCIA-SOCIAL-2026-10"]
    assert f.familia is Familia.RIO and f.gravidade.value == "alta"
    assert "a União transferiu mais" in f.titulo


def test_fpm_da_uniao_e_oitenta_por_cento_do_registrado_no_municipio():
    """O Portal traz o FPM líquido da retenção do FUNDEB; a matriz, o bruto: a conferência desconta."""
    con = partes.conectar_leitura(BANCO)   # 28/11/2026, divisão do banco em partes
    try:
        bruto = mz.receita(con, mz.Natureza(("1711511",)), ["2026-03"])["2026-03"]
        portal = con.execute(
            "select sum(valor) from transferencias_federais where mes='2026-03' and acao='0045' and "
            "tipo_favorecido in ('Administração Pública','Administração Pública Municipal')").fetchone()[0]
    finally:
        con.close()
    assert portal == pytest.approx(0.8 * bruto, rel=1e-6)


# --- O ritmo e o leito ----------------------------------------------------------------------------

def test_iptu_abaixo_do_ritmo_vira_ficha_e_itr_pequeno_nao(rm):
    ritmo = {r.especie: r for r in rm.ritmos}
    assert ritmo["IPTU"].situacao == "alerta" and ritmo["IPTU"].realizado < ritmo["IPTU"].esperado
    assert ritmo["Cota-parte do ITR"].situacao == "abaixo_imaterial"
    assert not any(e.anexo == "Anexo 01" for e in municipio.CORRENTES)   # capital não tem ritmo
    codigos = {f.codigo for f in rm.fichas("2026-10")}
    assert "RIO-RECEITA-IPTU-2026-10" in codigos and "RIO-RECEITA-COTA-PARTE-DO-ITR-2026-10" not in codigos


def test_cosip_empenhada_fora_do_leito(rm):
    assert rm.meses_desvio[0] == "2026-01" and rm.meses_desvio[-1] == "2026-10"
    d = next(d for d in rm.desvios if d.fonte == "751" and d.funcao == "04")
    assert d.valor == pytest.approx(14_660_791, abs=1) and d.motivo == "leito"
    assert any(n.startswith("319011") for _, n, _ in d.naturezas)         # vencimentos de pessoal
    f = next(f for f in rm.fichas("2026-10") if f.codigo == "VIN-DESVIO-751-04-2026-10")
    assert f.familia is Familia.VIN and f.gravidade.value == "alta"
    # as destinações que o catálogo ainda não conhece ficam à vista, não somem
    assert {"753", "759", "799"} <= set(rm.fontes_sem_catalogo)


# --- Adulterações: o sistema acha o que foi plantado ----------------------------------------------

@pytest.fixture()
def copia(tmp_path):
    destino = tmp_path / "historico.db"
    # 28/11/2026, divisão do banco em partes: a cópia leva as partes e a conexão as enxerga.
    partes.copiar_banco(BANCO, destino)
    return destino


def test_matriz_adulterada_no_iptu_vira_ficha_rio_msc(copia):
    con = partes.conectar(copia)   # 28/11/2026, divisão do banco em partes
    con.execute("update msc_itens set valor = valor * 1.10 where mes='2026-03' and conta_contabil like '6212%' "
                "and natureza_receita like '111250%'")
    con.commit()
    con.close()
    rm = _montar(copia)
    iptu = _conf(rm, "IPTU", municipio.Tipo.ENTRE_DEMONSTRATIVOS)
    # menos de 1% da espécie no ano, mas o RREO e a matriz saem da mesma contabilidade: diverge
    assert iptu.certificacao.divergencia and iptu.selo is Selo.AZUL
    assert len(iptu.detalhe) == 1 and iptu.detalhe[0].startswith("mar/2026")
    assert "RIO-MSC-IPTU-2026-10" in {f.codigo for f in rm.fichas("2026-10")}


def test_salario_educacao_na_saude_e_alienacao_no_custeio_viram_desvio(copia):
    con = partes.conectar(copia)   # 28/11/2026, divisão do banco em partes
    linha = ("2026-05", "622130400", "10131", 2026, "1550", "10", "302", None, "33903900", None, None, "C",
             250_000.0)
    con.execute("insert into msc_itens values (?,?,?,?,?,?,?,?,?,?,?,?,?)", linha)
    con.execute("insert into msc_itens values (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("2026-06", "622130400", "10131", 2026, "1755", "04", "122", None, "33903900", None, None, "C",
                 80_000.0))
    con.commit()
    con.close()
    rm = _montar(copia)
    desvios = {(d.fonte, d.funcao, d.motivo): d for d in rm.desvios}
    assert desvios[("550", "10", "leito")].valor == pytest.approx(250_000.0)
    assert desvios[("755", "04", "alienacao")].valor == pytest.approx(80_000.0)
    codigos = {f.codigo for f in rm.fichas("2026-10")}
    assert {"VIN-DESVIO-550-10-2026-10", "VIN-DESVIO-755-04-2026-10"} <= codigos


def test_transferencia_que_some_da_matriz_vira_ficha_de_origem(copia):
    con = partes.conectar(copia)   # 28/11/2026, divisão do banco em partes
    con.execute("delete from msc_itens where mes='2026-04' and natureza_receita like '1711511%'")
    con.commit()
    con.close()
    rm = _montar(copia)
    fpm = _conf(rm, "FPM", municipio.Tipo.ENTRE_FONTES)
    assert fpm.certificacao.divergencia and any(d.startswith("abr/2026") for d in fpm.detalhe)
    assert "RIO-ORIGEM-FPM-2026-10" in {f.codigo for f in rm.fichas("2026-10")}


def test_sem_matriz_o_rio_fica_nas_fontes_padrao_e_diz_por_que(copia):
    con = partes.conectar(copia)   # 28/11/2026, divisão do banco em partes
    con.execute("delete from msc_meses where mes='2026-02'")
    con.commit()
    con.close()
    rm = _montar(copia)
    assert any("A matriz de saldos contábeis cobre 7 dos 8 meses" in n for n in rm.notas)
    assert all(":" not in a.nome for a in rm.rio.afluentes)
    assert rm.liquido == pytest.approx(rm.realizado_declarado, abs=0.01)


# --- O parecer ------------------------------------------------------------------------------------

def test_parecer_mostra_o_rio_do_municipio_e_as_tres_conferencias():
    p = cadeoqueijo.montar("2026-10")
    assert p.fiscal is not None and p.fiscal.rio is not None
    pagina = html.gerar(p, hoje=date(2026, 11, 26))
    assert "A receita do Município inteiro: RREO do 4º bimestre de 2026" in pagina  # decisão do usuário de 28/11/2026: sem a metáfora do rio
    for titulo in ("A origem: o que a União transferiu contra o que o Município registrou",
                   "O RREO contra a matriz de saldos contábeis", "A soma por espécie contra o próprio RREO",  # decisão do usuário de 28/11/2026: sem a metáfora do rio
                   "Realizado contra o previsto", "Recurso vinculado empenhado fora da sua finalidade"):  # decisão do usuário de 28/11/2026: sem a metáfora do rio
        assert titulo in pagina, titulo
    d = p.como_dict()["municipio"]["rio"]
    assert d["liquido"] == pytest.approx(d["realizado_declarado"], abs=0.01)
    assert {c["tipo"] for c in d["conferencias"]} == {"mesmo_relatorio", "entre_demonstrativos", "entre_fontes"}
    codigos = {f.codigo for f in p.fichas}
    assert "RIO-ORIGEM-FNAS-ASSISTENCIA-SOCIAL-2026-10" in codigos and "VIN-DESVIO-751-04-2026-10" in codigos


def test_desenho_junta_os_afluentes_menores_por_esfera():
    r = Rio("2026", [Afluente(f"A{i}", Esfera.FEDERAL if i % 2 else Esfera.MUNICIPAL, 1000.0 - i, "1500")
                     for i in range(40)])
    desenho = svg.rio(r, rotulo="no exercício", maximo=10)
    assert desenho.count("<path") == 11            # 9 maiores + demais federais + demais municipais
    assert "Demais receitas (16), federal" in desenho and "no exercício" in desenho  # decisão do usuário de 28/11/2026: sem a metáfora do rio
    assert svg.rio(r).count("<path") == 40
