"""As secretarias pela trilha (Frente D2): domínios ativos, execução, integridade, plano e parecer.

Travas dos requisitos 83, 105, 106, 108, 130, 132, 138, 164 (ativação dos domínios) e 166.

Os testes do banco histórico usam os números de Goiânia (RREO de 2025 e 2026 e a matriz de saldos
contábeis); os do segundo Município usam um banco de fixture montado aqui mesmo, com o esquema do
banco histórico e números inventados, para provar que o parecer sai só da configuração.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from onisciente import RAIZ
from onisciente.config import carregar_alvo, carregar_dominio
from onisciente.nucleo import Selo
from onisciente.rio import parecer_dominio as P
from onisciente.rio import secretarias as S

BANCO = RAIZ / "dados" / "onisciente" / "historico.db"
real = pytest.mark.skipif(not BANCO.exists(), reason="banco histórico ausente")
HOJE = date(2026, 11, 27)
SEIS = ["assistencia", "saude", "educacao", "infraestrutura", "comurg", "administracao"]


# --- Domínios ativos e recortes (108, 164) -----------------------------------------------------------

def test_seis_secretarias_ativas_com_recorte_valido():
    alvo = carregar_alvo()
    assert [d.id for d in alvo.ativos()] == SEIS
    for d in alvo.ativos():
        assert d.ativo and d.recortes, d.id
        assert not d.problemas(), (d.id, d.problemas())
        assert d.funcao in d.funcoes
        q = d.qualidade
        assert q.get("plano") and q.get("norma_do_plano"), d.id


def test_recortes_por_funcao_e_subfuncao():
    alvo = carregar_alvo()
    d = {x.id: x for x in alvo.ativos()}
    assert d["saude"].contem("10") and d["saude"].contem("10", "301") and not d["saude"].contem("12")
    assert d["infraestrutura"].contem("26", "782") and d["infraestrutura"].contem("15", "451")
    assert not d["infraestrutura"].contem("15", "452")
    assert d["comurg"].contem("15", "452") and d["comurg"].contem("17", "512")
    assert not d["comurg"].contem("17", "511") and not d["comurg"].contem("15", "451")


def test_recortes_das_pastas_nao_se_sobrepoem():
    alvo = carregar_alvo()
    amostra = [("10", "301"), ("12", "361"), ("08", "244"), ("04", "122"), ("26", "782"), ("15", "451"),
               ("15", "452"), ("17", "512")]
    for f, s in amostra:
        donos = [d.id for d in alvo.ativos() if d.contem(f, s)]
        assert len(donos) == 1, (f, s, donos)


def test_recorte_invalido_e_apontado(tmp_path):
    arq = tmp_path / "x.toml"
    arq.write_text('id = "x"\nnome = "X"\nativo = true\nfuncao = "10"\nrecorte = ["10.30", "12"]\n',
                   encoding="utf-8")
    assert any("10.30" in p for p in carregar_dominio(arq).problemas())
    arq.write_text('id = "x"\nnome = "X"\nativo = true\nfuncao = "10"\nrecorte = ["12"]\n', encoding="utf-8")
    assert any("função principal 10" in p for p in carregar_dominio(arq).problemas())


# --- Execução por secretaria nas duas vias (105) e margens (22) -------------------------------------

@real
@pytest.mark.parametrize("exercicio,bimestre", [(2025, 3), (2025, 6), (2026, 4)])
def test_execucao_por_secretaria_rreo_igual_a_matriz(exercicio, bimestre):
    con = S.abrir(BANCO)
    try:
        for d in carregar_alvo().ativos():
            ex = S.execucao(con, d, exercicio, bimestre)
            for k in ("autorizado", "empenhado", "liquidado"):
                c = ex.valores[k].certificacao
                assert c.selo is Selo.VERDE and len(c.vias) == 2, (d.id, k, c)
            assert ex.valores["pago"].selo is Selo.AZUL
            assert 0 < ex.v("pago") <= ex.v("liquidado") <= ex.v("empenhado") <= ex.v("autorizado"), d.id
            assert ex.por_fonte and abs(sum(f["pago"] for f in ex.por_fonte) - ex.v("pago")) < 1.0
    finally:
        con.close()


@real
def test_saude_2025_nos_numeros_do_rreo():
    con = S.abrir(BANCO)
    try:
        d = carregar_alvo().dominios["saude"]
        ex = S.execucao(con, d, 2025, 6)
        assert round(ex.v("autorizado")) == 2_379_999_598
        assert round(ex.v("empenhado")) == 2_123_805_780
        assert round(ex.v("liquidado")) == 2_111_242_840
        assert round(ex.v("pago")) == 2_089_005_643
        m = ex.margens
        assert round(m.previsto_nao_empenhado) == 2_379_999_598 - 2_123_805_780
        assert m.pago_sem_vinculo is None   # sem o item a item, a quarta margem não é zero: não se mede
    finally:
        con.close()


@real
def test_execucao_por_secretaria_no_ultimo_bimestre():
    con = S.abrir(BANCO)
    try:
        lista = S.execucao_por_secretaria(con, carregar_alvo().ativos(), HOJE)
        assert [e.dominio.id for e in lista] == SEIS
        assert {(e.exercicio, e.bimestre) for e in lista} == {(2026, 4)}
    finally:
        con.close()


def test_margens_sem_vinculo_medido_ficam_sem_medida():
    from onisciente.rio import Margens
    m = Margens(100, 80, 60, 50, None)
    assert m.pago_sem_vinculo is None and m.como_dict()["pago_sem_vinculo"] is None
    assert Margens(100, 80, 60, 50, 20).pago_sem_vinculo == 30


# --- Integridade por secretaria (83) ---------------------------------------------------------------

@real
def test_integridade_por_secretaria():
    con = S.abrir(BANCO)
    try:
        for d in carregar_alvo().ativos():
            ind = S.integridade_da_secretaria(con, d, 2026, 4, HOJE)
            assert ind.coerencia == 1.0, d.id
            assert ind.tempestividade is not None and 0 <= ind.tempestividade <= 1
            assert ind.cobertura is None and ind.vinculo is None and ind.prestacao is None
            assert "item a item" in ind.motivos["cobertura"] and "no prazo" in ind.motivos["tempestividade"]
            assert not ind.completo
    finally:
        con.close()


def test_trilha_da_secretaria_com_eventos_item_a_item():
    from onisciente.conferencias.execucao import EventoDespesa, ContextoTrilha, percursos
    alvo = carregar_alvo()
    ev = [EventoDespesa("empenho", "1", date(2025, 3, 1), "SAUDE", "A", "11222333000181", 100.0, "339039",
                        "1500", "10", "302"),
          EventoDespesa("pagamento", "1", date(2025, 3, 20), "SAUDE", "A", "11222333000181", 100.0, "339039",
                        "1500", "10", "302"),
          EventoDespesa("pagamento", "2", date(2025, 3, 20), "EDUCACAO", "B", "44555666000102", 50.0, "339039",
                        "1500", "12", "361")]
    ctx = ContextoTrilha()
    ctx.contratos["11222333000181"] = [object()]
    cob, vin = S.trilha_da_secretaria(percursos(ev, ctx), ev, alvo.dominios["saude"])
    assert cob == 0.0 and vin == 1.0
    assert S.trilha_da_secretaria(percursos(ev, ctx), ev, alvo.dominios["comurg"]) == (None, None)


# --- Qualidade do plano (106) ---------------------------------------------------------------------

@real
def test_qualidade_do_plano_por_secretaria():
    con = S.abrir(BANCO)
    try:
        q = S.qualidade_do_plano(con, carregar_alvo().dominios["saude"], HOJE)
        assert q.exercicio == 2025 and q.plano == "Plano Municipal de Saúde"
        assert q.aderencia == round(1 - abs(2_379_999_598.12 - 2_063_256_000) / 2_063_256_000, 4)
        assert q.execucao == round(2_111_242_839.69 / 2_379_999_598.12, 4)
        assert 0 < q.nota <= 100
        assert q.valor_indicador is None and "ainda não roda" in q.motivo_indicador
    finally:
        con.close()


# --- As contas uma a uma (132) e o rio da pasta (130) ---------------------------------------------

@real
def test_contas_uma_a_uma_nove_maiores_com_quatro_estacoes():
    con = S.abrir(BANCO)
    try:
        d = carregar_alvo().dominios["saude"]
        c = S.contas_uma_a_uma(con, d, 2025, 12)
        saidas = c["matriz"]
        assert len(saidas) == 9
        pagos = [x["estacoes"]["pagamento"] for x in saidas]
        assert pagos == sorted(pagos, reverse=True)
        for x in saidas:
            assert set(x["estacoes"]) == {"empenho", "liquidacao", "ordem_pagamento", "pagamento"}
            assert x["estacoes"]["ordem_pagamento"] is None       # a matriz não traz a ordem
            assert x["estacoes"]["pagamento"] <= x["estacoes"]["liquidacao"] + 0.01
            assert [m["mes"] for m in x["cronologia"]] == sorted(m["mes"] for m in x["cronologia"])
        assert c["item_a_item"] == [] and "portal" in c["falta"]
    finally:
        con.close()


@real
def test_rio_da_secretaria_e_o_realizado_por_fonte():
    con = S.abrir(BANCO)
    try:
        ex = S.execucao(con, carregar_alvo().dominios["educacao"], 2025, 6)
        rio = S.rio_da_secretaria(ex)
        assert abs(rio.total() - ex.v("pago")) < 1.0
        assert all("pago" in a.origem for a in rio.afluentes)
        assert any(a.vinculado for a in rio.afluentes)
    finally:
        con.close()


# --- O parecer de cada secretaria (138, 130) --------------------------------------------------------

@real
def test_parecer_por_secretaria_no_banco(tmp_path):
    resumo = P.gerar_todos(ate=HOJE, saida=tmp_path, hoje=HOJE)
    assert [r["dominio"] for r in resumo] == SEIS
    for r in resumo:
        assert r["situacao"] == "gerado" and r["competencia"] == "2026-08"
        html = Path(r["html"]).read_text(encoding="utf-8")
        assert "A execução da pasta" in html and "As nove maiores saídas" in html
        assert "Pago no exercício" in html and "Previsto no mês" not in html
        assert P.AVISO_DA_SECAO_4 not in html
        assert "Receita realizada pelo rio" in html            # o Município inteiro vem junto (130)
        assert (tmp_path / f"panorama_{r['dominio']}_2026-08.json").exists()
    saude = Path(resumo[1]["html"]).read_text(encoding="utf-8")
    assert "Aplicação mínima em saúde" in saude and "Plano Municipal de Saúde" in saude


def test_inserir_execucao_sem_o_aviso_vai_antes_da_secao_5():
    assert P.inserir_execucao("<h2>4.</h2><h2>5. Preço</h2>", "<b>x</b>") == "<h2>4.</h2><b>x</b>\n<h2>5. Preço</h2>"


# --- O segundo Município só pela configuração (166) -----------------------------------------------

RECORTES = {   # (função, subfunção, nome no RREO): empenhado por mês
    ("10", None, "Saúde"): 1_000.0, ("12", None, "Educação"): 900.0, ("08", None, "Assistência Social"): 100.0,
    ("04", None, "Administração"): 500.0, ("26", None, "Transporte"): 300.0,
    ("15", "451", "Infra-Estrutura Urbana"): 50.0, ("15", "452", "Serviços Urbanos"): 200.0,
    ("17", "512", "Saneamento Básico Urbano"): 20.0,
}


def banco_de_fixture(caminho: Path, *, divergir_administracao: bool = True) -> Path:
    """Um Município inventado: 2025 inteiro na matriz e no RREO (1º e 6º bimestres), entregues no prazo."""
    from onisciente.historico import Banco
    b = Banco(caminho)
    con = b.con
    for m in range(1, 13):
        mes = f"2025-{m:02d}"
        con.execute("insert into msc_meses values (?, 'entregue', 1, ?, '')", (mes, mes))
        con.execute("insert into siconfi_entregas values (2025, 'MSC Agregada', ?, 'M', 'HO', ?, 'P', 'MSC')",
                    (m, f"2025-{m:02d}-20" if m < 12 else "2026-01-20"))
        for (f, s, _n), v in RECORTES.items():
            sub = s or "122"
            for conta, valor in (("622130400", 0.9 * v), ("622130100", 0.1 * v)):
                con.execute("insert into msc_itens values (?, ?, '10131', 2025, '1500', ?, ?, null, '33903900', "
                            "null, null, 'C', ?)", (mes, conta, f, sub, valor))
            if m == 1:
                con.execute("insert into msc_itens values (?, '622110000', '10131', 2025, '1600', ?, ?, null, "
                            "'33903900', null, null, 'C', ?)", (mes, f, sub, 2 * v))
    for per, termina, prazo, meses in ((1, "2025-02-28", "2025-03-30", 2), (6, "2025-12-31", "2026-01-30", 12)):
        con.execute("insert into siconfi_periodos values ('RREO', 2025, ?, ?, ?, ?, 'entregue', 10, 1, '')",
                    (per, f"{per}º bimestre", termina, prazo))
        con.execute("insert into siconfi_entregas values (2025, 'Relatório Resumido de Execução Orçamentária', "
                    "?, 'B', 'HO', ?, 'P', 'RREO')", (per, prazo[:8] + "15"))
        for (f, s, nome), v in RECORTES.items():
            emp = v * meses
            liq = 0.9 * v * meses
            if divergir_administracao and nome == "Administração" and per == 6:
                liq += 1_000.0
            aut = 2 * v + emp
            for coluna, valor in (("DOTAÇÃO INICIAL", 2 * v + 12 * v), ("DOTAÇÃO ATUALIZADA (a)", aut),
                                  ("DESPESAS EMPENHADAS ATÉ O BIMESTRE (b)", emp),
                                  ("DESPESAS LIQUIDADAS ATÉ O BIMESTRE (d)", liq)):
                con.execute("insert into siconfi_itens values ('RREO', 2025, ?, 'RREO-Anexo 02', "
                            "'Total das Despesas Exceto Intra-Orçamentárias', ?, '', ?, ?)",
                            (per, coluna, nome, valor))
    con.commit()
    con.close()
    return caminho


@pytest.fixture(scope="module")
def fixture_anapolis(tmp_path_factory):
    return banco_de_fixture(tmp_path_factory.mktemp("anapolis") / "historico.db")


def test_segundo_municipio_so_pela_configuracao(fixture_anapolis, tmp_path):
    alvo = carregar_alvo(RAIZ / "alvos" / "anapolis.toml")
    assert alvo.ibge == 5201108 and alvo.faixa_camara == "III" and alvo.municipio == "Anápolis"
    assert {d.id for d in alvo.ativos()} == set(SEIS)
    assert alvo.dominios["comurg"].nome == "Limpeza urbana"
    resumo = P.gerar_todos(alvo, banco=fixture_anapolis, ate=date(2026, 3, 1), saida=tmp_path,
                           hoje=date(2026, 3, 1))
    assert [r["situacao"] for r in resumo] == ["gerado"] * 6
    assert {r["competencia"] for r in resumo} == {"2025-12"}
    for r in resumo:
        html = Path(r["html"]).read_text(encoding="utf-8")
        assert "Prefeitura de Anápolis" in html and "Goiânia" not in html, r["dominio"]
        assert "A execução da pasta" in html


def test_segundo_municipio_numeros_e_divergencia(fixture_anapolis):
    alvo = carregar_alvo(RAIZ / "alvos" / "anapolis.toml")
    con = S.abrir(fixture_anapolis)
    try:
        saude = S.execucao(con, alvo.dominios["saude"], 2025, 6)
        assert saude.v("empenhado") == pytest.approx(12_000.0)
        assert saude.v("liquidado") == pytest.approx(10_800.0) and saude.v("pago") == pytest.approx(10_800.0)
        assert saude.v("autorizado") == pytest.approx(14_000.0)
        assert all(saude.valores[k].selo is Selo.VERDE for k in ("autorizado", "empenhado", "liquidado"))
        comurg = S.execucao(con, alvo.dominios["comurg"], 2025, 6)
        assert comurg.v("empenhado") == pytest.approx(12 * 220.0)
        adm = S.execucao(con, alvo.dominios["administracao"], 2025, 6)
        assert adm.valores["liquidado"].certificacao.divergencia
        ind = S.integridade_da_secretaria(con, alvo.dominios["administracao"], 2025, 6, date(2026, 3, 1))
        assert ind.coerencia == pytest.approx(5 / 6)
        assert ind.tempestividade == 1.0
        q = S.qualidade_do_plano(con, alvo.dominios["saude"], date(2026, 3, 1))
        assert q.aderencia == 1.0 and q.execucao == round(10_800 / 14_000, 4)
    finally:
        con.close()
    p = P.montar(alvo, alvo.dominios["administracao"], fixture_anapolis, date(2026, 3, 1))
    assert any(f.codigo.startswith("VIAS-ADMINISTRACAO-LIQUIDADO") for f in p.panorama.fichas)
    assert all("Indício, não acusação" in f.como_esta for f in p.panorama.fichas if f.codigo.startswith("VIAS-"))


def test_panorama_da_pasta_leva_execucao_e_banco(fixture_anapolis):
    """Pedido da Frente C: o panorama da pasta define execucao e banco, e o parecer não insere a seção
    da execução por fora (o gerador do parecer a põe uma vez só)."""
    alvo = carregar_alvo(RAIZ / "alvos" / "anapolis.toml")
    p = P.montar(alvo, alvo.dominios["saude"], fixture_anapolis, date(2026, 3, 1))
    assert p.panorama.execucao is p.execucao and p.panorama.banco == fixture_anapolis
    assert p.panorama.contas == p.contas and p.panorama.qualidade is p.qualidade
    html = p.html(hoje=date(2026, 3, 1))
    assert html.count("A execução da pasta") == 1 and P.AVISO_DA_SECAO_4 not in html
