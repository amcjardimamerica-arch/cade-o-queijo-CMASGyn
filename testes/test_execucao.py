"""A execução da despesa item a item (Frente D2): o coletor do portal e as conferências da execução.

As fixtures ``portal_antigo_real.html`` e ``wordpress_transparencia_real.html`` são as páginas
públicas lidas pela sondagem de 27/11/2026 (commit fa208ec), sem o cabeçalho da sondagem.

Travas dos requisitos 30, 31, 32, 55, 56, 57, 63, 64, 66, 132 e 141. O coletor roda contra as
fixtures de ``testes/dados/transweb/`` (imitam o formato descrito no manual do TransWeb e a lista de
arquivos do portal WordPress; não são cópias de páginas reais) com um leitor HTTP de mentira. As
conferências rodam num banco de fixture com o esquema do banco histórico.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest

from onisciente import RAIZ
from onisciente.coletores import goiania_transweb as G
from onisciente.coletores.base import Leitura
from onisciente.conferencias import execucao as X
from onisciente.nucleo.estacoes import Estacao

DADOS = Path(__file__).parent / "dados" / "transweb"
BANCO = RAIZ / "dados" / "onisciente" / "historico.db"
real = pytest.mark.skipif(not BANCO.exists(), reason="banco histórico ausente")
PORTAL = G.carregar_portal("alvos/portais/goiania.toml")


def _f(nome: str) -> bytes:
    return (DADOS / nome).read_bytes()


class LeitorFalso:
    """Responde como o TransWeb das fixtures e guarda cada pedido feito."""

    def __init__(self, vazio: bool = False):
        self.pedidos: list[tuple[str, dict | None]] = []
        self.vazio = vazio

    def __call__(self, url, formulario=None, **_):
        self.pedidos.append((url, formulario))
        nome = url.rsplit("/", 1)[-1]
        if formulario is None:
            if nome == "EmpenhoOrgao.aspx":
                return Leitura(True, url, _f("empenho_orgao.html"), http=200)
            return Leitura(False, url, b"", erro="HTTP 404", http=404)
        arg = formulario.get("__EVENTARGUMENT", "")
        if self.vazio:
            return Leitura(True, url, _f("vazio.html"), http=200)
        if arg == "Page$2":
            return Leitura(True, url, _f("empenho_orgao_p2.html"), http=200)
        if arg == "Select$0" and formulario.get("__VIEWSTATE", "").endswith("Y3RsMDA"):
            return Leitura(True, url, _f("detalhe_empenho.html"), http=200)
        if arg.startswith("Select$"):
            return Leitura(True, url, b"<html><body><p>Sem movimento.</p></body></html>", http=200)
        return Leitura(True, url, _f("empenho_orgao_p1.html"), http=200)


# --- O coletor do portal (141) --------------------------------------------------------------------

def test_portal_configurado_sem_caminho_confirmado():
    assert not PORTAL.confirmado
    ids = [c.id for c in PORTAL.consultas]
    assert ids == ["empenho_orgao", "empenho_credor", "ordem_pagamento_orgao"]
    for c in PORTAL.consultas:
        assert c.paginas and c.botao and "valor" in c.colunas
    assert set(PORTAL.detalhe) >= {"liquidacao", "pagamento", "ordem_pagamento"}


def test_sondagem_cobre_todas_as_paginas_candidatas():
    from onisciente.sondagem import CANDIDATOS
    urls = set(CANDIDATOS["d2_transweb"])
    for c in PORTAL.consultas:
        for p in c.paginas:
            assert PORTAL.base + p in urls, p
    for e in PORTAL.entradas:
        assert PORTAL.base + e in urls
    assert any("categoria=49" in u for u in CANDIDATOS["d2_wordpress"])


def test_formulario_aspnet_campos_pelo_fim_do_nome():
    f = G.formularios(_f("empenho_orgao.html"))[0]
    assert f.aspnet
    assert set(f.estado()) >= {"__VIEWSTATE", "__EVENTVALIDATION", "__VIEWSTATEGENERATOR"}
    assert f.achar(["txtData"]) == "ctl00$ContentPlaceHolder1$txtData"
    assert f.achar(["ddlOrgao"]) == "ctl00$ContentPlaceHolder1$ddlOrgao"
    assert f.achar(["naoexiste"]) is None
    c = PORTAL.consulta("empenho_orgao")
    assert G.opcoes_de_orgao(f, c) == [("1650", "SECRETARIA MUNICIPAL DE SAÚDE"),
                                       ("3650", "FUNDO MUNICIPAL DE ASSISTÊNCIA SOCIAL")]
    corpo = f.envio({"ctl00$ContentPlaceHolder1$txtData": "15/03/2025"}, botao=f.botao(c.botao))
    assert corpo["__VIEWSTATE"] == "/wEPDwUKMTY1NDU2MTA1MmRk"
    assert corpo["__EVENTVALIDATION"] == "/wEWBALVnu0NAoznisYGAq2"
    assert corpo["ctl00$ContentPlaceHolder1$btnConsultar"] == "Consultar"
    assert corpo["__EVENTTARGET"] == ""


def test_consulta_com_paginacao_e_detalhe():
    ler = LeitorFalso()
    c = PORTAL.consulta("empenho_orgao")
    res = G.consultar(ler, PORTAL, c, {"data": "15/03/2025", "orgao": "1650", "orgao_nome": "SAUDE"})
    assert res.ok and not res.vazio and res.paginas == 2
    empenhos = [e for e in res.eventos if e["tipo"] == "empenho"]
    assert [e["empenho"] for e in empenhos] == ["2025/000123", "2025/000124", "2025/000125"]
    primeiro = empenhos[0]
    assert primeiro["valor"] == 150_000.0 and primeiro["documento"] == "11222333000181"
    assert primeiro["funcao"] == "10" and primeiro["subfuncao"] == "302" and primeiro["fonte"] == "1500"
    assert primeiro["elemento"] == "33903900" and primeiro["data"] == "2025-03-15"
    assert all(e["valor"] != 232_500.0 for e in res.eventos)          # a linha de total fica fora
    liq = [e for e in res.eventos if e["tipo"] == "liquidacao"]
    pag = [e for e in res.eventos if e["tipo"] == "pagamento"]
    assert [(e["data"], e["valor"]) for e in liq] == [("2025-03-10", 50_000.0), ("2025-04-10", 50_000.0)]
    assert [(e["data"], e["valor"]) for e in pag] == [("2025-03-05", 50_000.0), ("2025-04-20", 50_000.0)]
    assert all(e["empenho"] == "2025/000123" and e["funcao"] == "10" for e in liq + pag)
    # O POST de cada página devolve o estado da página anterior, como o navegador.
    posts = [f for _u, f in ler.pedidos if f]
    assert posts[0]["__VIEWSTATE"] == "/wEPDwUKMTY1NDU2MTA1MmRk"
    pagina2 = next(f for f in posts if f.get("__EVENTARGUMENT") == "Page$2")
    assert pagina2["__EVENTVALIDATION"].endswith("pagina1")


def test_transweb_real_e_outsystems_com_menu_da_despesa():
    """Amostra real lida pela sondagem de 27/11/2026 (PortaldaTransparencia.aspx?Antigo=True)."""
    html = _f("portal_antigo_real.html")
    f = G.formularios(html)[0]
    assert f.aspnet and f.outsystems and f.campos["__VIEWSTATE"] == ""
    assert f.envio({})["__OSVSTATE"] == f.campos["__OSVSTATE"] != ""
    entrada = PORTAL.base + PORTAL.entradas[0]
    assert G.paginas_do_menu(html, entrada, PORTAL.menu_despesa) == [PORTAL.base + "Portal_Despesas.aspx"]
    assert all(c.paginas[0] == "Portal_Despesas.aspx" for c in PORTAL.consultas)
    assert "Home.aspx" not in PORTAL.entradas and "Default.aspx" not in PORTAL.entradas


def test_abrir_consulta_procura_no_menu_quando_os_caminhos_falham():
    import dataclasses
    c = dataclasses.replace(PORTAL.consulta("empenho_orgao"), paginas=("NaoExiste.aspx",))
    portal = dataclasses.replace(PORTAL, consultas=(c,))
    pedidos = []

    def ler(url, formulario=None, **_):
        pedidos.append(url)
        if url.endswith("PortaldaTransparencia.aspx?Antigo=True"):
            return Leitura(True, url, _f("portal_antigo_real.html"), http=200)
        if url.endswith("Portal_Despesas.aspx"):
            return Leitura(True, url, _f("empenho_orgao.html"), http=200)
        return Leitura(False, url, b"", erro="HTTP 404", http=404)

    acao, form, _ = G.abrir_consulta(ler, portal, c)
    assert acao.endswith("EmpenhoOrgao.aspx") and form.achar(["txtData"])
    assert [u.rsplit("/", 1)[-1] for u in pedidos] == ["NaoExiste.aspx", "PortaldaTransparencia.aspx?Antigo=True",
                                                       "Portal_Despesas.aspx"]


def test_wordpress_real_categoria_49_e_despesas_e_receitas():
    """Amostra real do portal novo: a categoria 49 é Despesas e Receitas e a lista vem do navegador."""
    html = _f("wordpress_transparencia_real.html")
    assert G.categorias_do_portal(html)[49] == "Despesas e Receitas"
    assert PORTAL.wordpress["categorias"] == {"despesas_e_receitas": 49}
    assert G.arquivos_da_categoria(html, PORTAL.wordpress["base"]) == []


def test_consulta_vazia_e_pagina_inexistente():
    c = PORTAL.consulta("empenho_orgao")
    res = G.consultar(LeitorFalso(vazio=True), PORTAL, c, {"data": "01/01/2025"})
    assert res.ok and res.vazio and res.eventos == []
    c2 = PORTAL.consulta("empenho_credor")
    falha = G.consultar(LeitorFalso(), PORTAL, c2, {"data_inicial": "01/01/2025"})
    assert not falha.ok and "404" in falha.erro


def test_wordpress_lista_arquivos_e_le_csv():
    arqs = G.arquivos_da_categoria(_f("categoria_despesas.html"), PORTAL.wordpress["base"])
    assert [a["formato"] for a in arqs] == ["csv", "pdf"]
    assert arqs[1]["url"].startswith("https://www.goiania.go.gov.br/transparencia/wp-content/")
    evs = G.eventos_do_csv(_f("empenhos.csv"), PORTAL.consulta("empenho_orgao").colunas, "empenho")
    assert len(evs) == 1 and evs[0]["valor"] == 1_000_000.0 and evs[0]["documento"] == "12345678000190"


@dataclass
class _Banco:
    con: sqlite3.Connection


@dataclass
class _Ctx:
    banco: _Banco
    meses: list
    hoje: date
    ler_falso: LeitorFalso

    def ler(self, motor, alvo, url, mes=None, formulario=None, tempo=60):
        assert motor == "execucao_goiania"
        return self.ler_falso(url, formulario=formulario)


def test_motor_registra_dias_e_continua_de_onde_parou():
    con = sqlite3.connect(":memory:")
    ctx = _Ctx(_Banco(con), ["2025-03"], date(2025, 3, 4), LeitorFalso())
    resumo = G.motor(ctx, PORTAL, consultas=("empenho_orgao",), limite_de_dias=2)
    assert resumo["consultas"] == 4 and resumo["falhas"] == 0     # 2 dias, 2 órgãos
    dias = [d for (d,) in con.execute("select distinct dia from despesa_consultas order by dia")]
    assert dias == ["2025-03-02", "2025-03-03"]
    assert G.dias_a_ler(con, "empenho_orgao", date(2025, 3, 1), date(2025, 3, 3)) == [date(2025, 3, 1)]
    n = con.execute("select count(*) from despesa_eventos").fetchone()[0]
    assert n == resumo["eventos"] > 0
    G.gravar(con, [dict(r) for r in []])
    con.execute("insert into despesa_consultas values ('empenho_orgao', '2025-03-02', 'X', 'falha', 0, 0, '', 'e', '')")
    assert date(2025, 3, 2) in G.dias_a_ler(con, "empenho_orgao", date(2025, 3, 1), date(2025, 3, 3))


def test_gravar_nao_repete():
    con = sqlite3.connect(":memory:")
    ev = {"tipo": "empenho", "empenho": "1", "data": "2025-03-01", "orgao": "X", "documento": "1", "valor": 1.0}
    assert G.gravar(con, [ev]) == 1 and G.gravar(con, [ev]) == 0


# --- As conferências da execução (30, 31, 32, 55, 56, 57, 63, 64, 66) -------------------------------

def _evento(tipo, emp, dia, valor, doc="11222333000181", credor="LIMPA BEM", orgao="SAUDE", elemento="33903900",
            fonte="1500", funcao="10", sub="302"):
    return {"tipo": tipo, "empenho": emp, "data": dia, "orgao": orgao, "credor": credor, "documento": doc,
            "valor": valor, "elemento": elemento, "fonte": fonte, "funcao": funcao, "subfuncao": sub}


def banco_de_execucao(caminho: Path) -> Path:
    """Os eventos das fixtures do portal mais casos montados para cada conferência."""
    from onisciente.historico import Banco
    b = Banco(caminho)
    con = b.con
    res = G.consultar(LeitorFalso(), PORTAL, PORTAL.consulta("empenho_orgao"),
                      {"data": "15/03/2025", "orgao": "1650", "orgao_nome": "SAUDE"})
    G.gravar(con, res.eventos)
    evs = []
    # Medições repetidas: três liquidações iguais ao centavo no mesmo empenho.
    for m in (5, 6, 7):
        evs.append(_evento("liquidacao", "2025/000300", f"2025-{m:02d}-10", 33_333.33, doc="55666777000188",
                           credor="VIGILANCIA X"))
        evs.append(_evento("pagamento", "2025/000300", f"2025-{m:02d}-20", 33_333.33, doc="55666777000188",
                           credor="VIGILANCIA X"))
    evs.append(_evento("empenho", "2025/000300", "2025-05-01", 100_000.0, doc="55666777000188", credor="VIGILANCIA X"))
    # Recorrente sem contrato: pago em dois meses, sem contrato no PNCP; e uma folha, que não entra.
    for m in (2, 3):
        evs.append(_evento("pagamento", f"2025/0004{m}", f"2025-{m:02d}-15", 10_000.0, doc="99888777000166",
                           credor="SEM CONTRATO LTDA"))
        evs.append(_evento("pagamento", f"2025/0005{m}", f"2025-{m:02d}-15", 5_000.0, doc="12312312000112",
                           credor="FOLHA", elemento="31901100"))
    # Empenho de fim de ano: 30% do empenhado do órgão na segunda quinzena de dezembro.
    evs.append(_evento("empenho", "2025/000900", "2025-12-28", 140_000.0, doc="77777777000177", orgao="OBRAS",
                       funcao="15", sub="451"))
    evs.append(_evento("empenho", "2025/000100", "2025-06-01", 330_000.0, doc="77777777000177", orgao="OBRAS",
                       funcao="15", sub="451"))
    G.gravar(con, evs)
    # O contrato do credor da fixture é menor que o liquidado (R$ 100 mil liquidados).
    con.execute("insert into contratos_pncp (pncp_id, orgao_cnpj, orgao, fornecedor_ni, valor_global, "
                "data_assinatura) values ('c1', '25141524000123', 'SAUDE', '11222333000181', 90000, '2025-01-10')")
    con.execute("insert into contratos_pncp (pncp_id, orgao_cnpj, orgao, fornecedor_ni, valor_global, "
                "data_assinatura) values ('c2', '25141524000123', 'SAUDE', '55666777000188', 500000, '2025-01-10')")
    con.commit()
    con.close()
    return caminho


@pytest.fixture(scope="module")
def conf(tmp_path_factory):
    return X.conferir_execucao(banco_de_execucao(tmp_path_factory.mktemp("exec") / "historico.db"))


def test_limiares_documentados_e_restritivos():
    lim = X.carregar_limiares()
    assert X.limiares_sem_justificativa() == []
    assert lim["concentracao"]["corte_pct"] == 80.0 and lim["concentracao"]["minimo_de_credores"] <= 5
    assert lim["recorrente_sem_contrato"]["minimo_de_meses"] == 2
    assert lim["medicoes_repetidas"]["tolerancia_relativa"] == 0.0
    assert lim["liquidado_acima_do_contratado"]["tolerancia_absoluta"] <= 0.01
    assert lim["ordem"]["dias_de_tolerancia"] == 0
    for grupo in ("concentracao", "fim_de_ano", "recorrente_sem_contrato", "medicoes_repetidas"):
        assert all(v == 0.0 for k, v in lim[grupo].items() if k.endswith("minimo") or k == "pago_minimo")


def test_percursos_pelas_nove_estacoes(conf):
    p = {x.chave: x for x in conf.percursos}
    um = p["SAUDE|2025/000123"]
    acesas = um.acesas()
    assert {Estacao.EMPENHO, Estacao.LIQUIDACAO, Estacao.PAGAMENTO, Estacao.VINCULO} <= acesas
    assert not um.completo                     # sem matriz no banco de fixture: sem origem, previsão, dotação
    assert um.valor_pago() == 100_000.0
    assert conf.integridade == 0.0             # nenhum pago cruza as nove estações


def test_integridade_e_a_fracao_do_pago_completo():
    ctx = X.ContextoTrilha(receitas={(2025, "500")}, dotacoes={(2025, "10")}, dotacoes_fonte={(2025, "10", "500")},
                           contratos={"11222333000181": [object()]}, rreo={(2025, 2)})
    evs = [X.EventoDespesa("empenho", "1", date(2025, 3, 1), "S", "A", "11222333000181", 100.0, "339039", "1500", "10"),
           X.EventoDespesa("liquidacao", "1", date(2025, 3, 2), "S", "A", "11222333000181", 100.0, "339039", "1500", "10"),
           X.EventoDespesa("pagamento", "1", date(2025, 3, 3), "S", "A", "11222333000181", 100.0, "339039", "1500", "10"),
           X.EventoDespesa("pagamento", "2", date(2025, 3, 3), "S", "B", "", 300.0, "339039", "1999", "10")]
    ps = X.percursos(evs, ctx)
    out = X.ConferenciasExecucao(percursos=ps)
    assert [p.completo for p in ps] == [True, False]
    assert out.integridade == pytest.approx(0.25)
    assert X.ConferenciasExecucao().integridade is None      # sem pagamento lido: sem medida, nunca zero


def test_ordem_violada_pagamento_antes_da_liquidacao(conf):
    ordem = {a.chave: a for a in conf.achados if a.tipo == "ordem"}
    assert "SAUDE|2025/000123" in ordem                    # pagou em 05/03 o que só liquidou em 10/03
    assert "SAUDE|2025/000300" not in ordem                # empenho, liquidação e pagamento em ordem
    assert "SAUDE|2025/00042" in ordem                     # pago sem empenho nem liquidação lidos
    f = X.ficha_execucao(ordem["SAUDE|2025/000123"], "2025-04")
    assert f.codigo.startswith("ENT-ORD") or "ordem" in f.titulo.lower()


def test_liquidado_acima_do_contratado(conf):
    a = [x for x in conf.achados if x.tipo == "liquidado_acima"]
    assert len(a) == 1 and a[0].chave == "11222333000181"
    assert a[0].valor == pytest.approx(10_000.0) and a[0].limite == 90_000.0


def test_medicoes_repetidas(conf):
    a = [x for x in conf.achados if x.tipo == "medicoes"]
    assert [x.chave for x in a] == ["SAUDE|2025/000300"]


def test_concentracao_e_credor_unico(conf):
    conc = [x for x in conf.achados if x.tipo in ("concentracao_pago", "credor_unico")]
    assert any(x.tipo == "credor_unico" and x.orgao == "SAUDE" for x in conc)
    tudo = [X.EventoDespesa("pagamento", str(i), date(2025, 1, 1), "O", f"C{i}", f"{i:014d}", v)
            for i, v in enumerate([800.0, 50.0, 50.0, 50.0, 50.0])]
    out = X.ConferenciasExecucao()
    X._concentracao_do_pago(tudo, out, X.carregar_limiares()["concentracao"])
    assert {a.tipo for a in out.achados} == {"concentracao_pago", "credor_unico"}


def test_credor_recorrente_sem_contrato(conf):
    a = [x for x in conf.achados if x.tipo == "sem_contrato"]
    assert [x.chave for x in a] == ["SAUDE|99888777000166"]       # a folha (31.90.11) não entra
    assert conf.cobertura["pagamentos_com_documento_mascarado"] == 0


def test_empenhos_de_fim_de_ano(conf):
    a = [x for x in conf.achados if x.tipo == "fim_de_ano"]
    assert [x.orgao for x in a] == ["OBRAS"]


def test_fichas_sao_indicio_nao_acusacao(conf):
    fichas = conf.fichas()
    assert len(fichas) == len(conf.achados) >= 6
    for f in fichas:
        if not f.codigo.startswith("ENT-ORD"):
            assert f.como_esta.startswith("Indício, não acusação.")


def test_contas_item_a_item_nove_maiores_quatro_estacoes(conf, tmp_path):
    con = sqlite3.connect(banco_de_execucao(tmp_path / "h.db"))
    try:
        linhas = X.contas_item_a_item(X.ler_eventos(con), maiores=9)
    finally:
        con.close()
    assert len(linhas) <= 9
    assert all(set(x["estacoes"]) == set(X.ESTACOES_LEGAIS) for x in linhas)
    topo = linhas[0]
    assert topo["documento"] == "11222333000181" and topo["estacoes"]["pagamento"] == 100_000.0
    datas = [c["data"] for c in topo["cronologia"]]
    assert datas == sorted(datas)


# --- O banco histórico: a execução que já está lá (66, 105) ---------------------------------------

@real
def test_fim_de_ano_medido_na_matriz_real():
    c = X.conferir_execucao(BANCO)
    assert c.cobertura["funcoes_ano_medidas_no_fim_de_ano"] >= 10
    assert c.cobertura.get("sem_item_a_item") is True and c.integridade is None
    assert not [a for a in c.achados if a.tipo == "fim_de_ano_funcao"]   # 2025: nenhum dezembro acima de 12,5%


def test_fim_de_ano_na_matriz_aponta_dezembro_concentrado(tmp_path):
    from onisciente.historico import Banco
    b = Banco(tmp_path / "m.db")
    for m in range(1, 13):
        v = 100.0 if m < 12 else 400.0
        b.con.execute("insert into msc_itens (mes, conta_contabil, funcao, natureza_despesa, natureza_conta, valor) "
                      "values (?, '622130100', '10', '33903900', 'C', ?)", (f"2025-{m:02d}", v))
    b.con.commit()
    c = X.conferir_execucao(b.con)
    a = [x for x in c.achados if x.tipo == "fim_de_ano_funcao"]
    assert [x.chave for x in a] == ["10|2025"]


# --- A página real Portal_Despesas.aspx e os popups (terceira rodada, 141) --------------------------
#
# portal_despesas_real.html, liquidacao_popup*_real.html, pagamento_popup*_real.html e
# empenho_popup_real.html são recortes das páginas lidas pela sondagem de 27/11/2026 (só o <head>, os
# scripts soltos e parte das linhas e das opções tirados; credores só pessoas jurídicas).
# portal_despesas_pagina2_sintetico.txt é SINTÉTICO: a resposta OsAjax no formato do _osjs.js.

LISTA = PORTAL.consulta("despesas_favorecido")
EMP1, EMP2, EMP_INSS = "20261101002310011", "20261101002310012", "20261101002430005"


class LeitorReal:
    """Responde com os recortes reais: a página, os popups lidos e a página 2 sintética."""

    POPUPS = {("LiquidacaoPopUp.aspx", EMP1): "liquidacao_popup_real.html",
              ("PagamentoPopUp.aspx", EMP1): "pagamento_popup_real.html",
              ("LiquidacaoPopUp.aspx", EMP_INSS): "liquidacao_popup_inss_real.html",
              ("PagamentoPopUp.aspx", EMP_INSS): "pagamento_popup_inss_real.html"}

    def __init__(self):
        self.pedidos: list[tuple[str, dict | None]] = []

    def __call__(self, url, formulario=None, **_):
        self.pedidos.append((url, formulario))
        pagina = url.split("?", 1)[0].rsplit("/", 1)[-1]
        if formulario is not None:
            alvo = formulario.get("__EVENTTARGET", "")
            if alvo.endswith("$wt86"):                       # Buscar: a página como veio
                return Leitura(True, url, _f("portal_despesas_real.html"), http=200)
            if alvo.endswith("$RichWidgets_wt150$block$wt28"):  # next
                return Leitura(True, url, _f("portal_despesas_pagina2_sintetico.txt"), http=200)
            return Leitura(False, url, b"", erro="HTTP 500", http=500)
        if pagina == "Portal_Despesas.aspx":
            return Leitura(True, url, _f("portal_despesas_real.html"), http=200)
        if pagina == "EmpenhoPopUp.aspx":
            return Leitura(True, url, _f("empenho_popup_real.html"), http=200)
        emp = url.rsplit("Empenho=", 1)[-1].split("&", 1)[0]
        if (pagina, emp) in self.POPUPS:
            return Leitura(True, url, _f(self.POPUPS[(pagina, emp)]), http=200)
        return Leitura(False, url, b"", erro="HTTP 404", http=404)


def test_leitor_ignora_script_e_texto_oculto_nas_celulas():
    html = ("<table><tr><th>Valor<a style='display:none' href='#'>lnkSort</a><script>x('y')</script></th></tr>"
            "<tr><td>1.234,56<span><div style='display:none'><input type='submit' value='z'/>oculto</div></span>"
            "<script>outsystems.internal.$()</script></td></tr></table>")
    t = G.tabelas(html)[0]
    assert t.cabecalho == ["Valor"] and t.linhas[0][0].texto == "1.234,56"


def test_portal_despesas_real_formulario_tabela_e_paginacao():
    html = _f("portal_despesas_real.html")
    assert LISTA.confirmado and LISTA.granularidade == "mes" and LISTA.paginas == ("Portal_Despesas.aspx",)
    assert not LISTA.envio_confirmado and LISTA.envio == "ajax"
    lido = G.ler_html(html)
    f = lido.formularios[0]
    assert f.outsystems and f.acao == "Portal_Despesas.aspx" and f.campos["__VIEWSTATE"] == ""
    prefixo = "WebPatterns_wt2$block$wtMainContent$DespesasWebBlocks_wt1$block$"
    for campo, fim in (("mes", "wtcboMes"), ("ano", "wtcboAno"), ("orgao", "wtcboOrgao"),
                       ("favorecido", "wtNmFavorecido"), ("empenho", "wtNrEmpenho")):
        assert f.achar(LISTA.campos[campo]) == prefixo + fim
    mes = prefixo + "wtcboMes"
    assert f.valor_de_opcao(mes, "11") == "__ossli_11" and f.valor_de_opcao(mes, "Março") == "__ossli_03"
    assert f.valor_de_opcao(prefixo + "wtcboAno", "2025") == "2025"
    assert ("1650", "SECRETARIA MUNICIPAL DE SAÚDE") not in f.opcoes[prefixo + "wtcboOrgao"]
    assert len(f.opcoes[prefixo + "wtcboOrgao"]) == 38                 # "Selecione" e os 37 órgãos
    assert f.botao(LISTA.botao) == (prefixo + "wt86", "Buscar")
    corpo = f.envio_ajax({mes: "__ossli_11"}, prefixo + "wt86")
    assert corpo["__EVENTTARGET"] == prefixo + "wt86" and corpo["__AJAX"] == "__OSVSTATE,"
    assert corpo["__OSVSTATE"] == f.campos["__OSVSTATE"] and corpo[mes] == "__ossli_11"
    assert "__AJAXEVENT" not in corpo and not any(n in corpo for n, _ in f.botoes)
    # A tabela: uma linha por empenho, sem o texto dos scripts e dos links de ordenação.
    t, mapa = G.tabela_de_resultado(lido.tabelas, LISTA.colunas)
    assert t.id.endswith(LISTA.tabela) and len(t.linhas) == 6
    assert t.cabecalho == ["Beneficiário", "Nr. Empenho", "Data", "Orgão", "Natureza Despesa", "Valor Empenhado",
                           "Valor Liquidado", "Valor Pago"]
    assert {"credor", "empenho", "data", "orgao", "elemento", "valor", "liquidado", "pago"} <= set(mapa)
    primeira = t.linhas[0]
    assert [c.texto for c in primeira][-3:] == ["1.170.877,06"] * 3
    links = [h for c in primeira for h in c.links]
    assert links[0].startswith("https://www10.goiania.go.gov.br/DespesasWebBlocks/EmpenhoPopUp.aspx?CdOrgao=1101"
                               f"&Empenho={EMP1}&NmOrgao=SECRETARIA+MUNICIPAL+DE+GOVERNO++")
    assert G._popups_da_linha(LISTA, links) == {
        "empenho": links[0],
        "liquidacao": f"https://www10.goiania.go.gov.br/DespesasWebBlocks/LiquidacaoPopUp.aspx?Empenho={EMP1}",
        "pagamento": f"https://www10.goiania.go.gov.br/DespesasWebBlocks/PagamentoPopUp.aspx?Empenho={EMP1}"}
    zerada = t.linhas[4]                                                # 0,00: os links são "#"
    assert G._popups_da_linha(LISTA, [h for c in zerada for h in c.links]).keys() == {"empenho"}
    evs = G.eventos_da_tabela(t, mapa, "empenho")
    assert (evs[0]["credor"], evs[0]["empenho"], evs[0]["data"], evs[0]["elemento"], evs[0]["valor"]) == \
        ("ITAU UNIBANCO S.A.", EMP1, "2026-11-24", "31901100", 1_170_877.06)
    assert evs[0]["orgao"] == "SECRETARIA MUNICIPAL DE GOVERNO" and evs[0]["documento"] == ""
    # Contador, totais e o "next" da paginação (OsAjax).
    assert G.contador(html) == (1, 20, 822)
    assert G.totais_da_lista(lido.tabelas) == {"empenhado": 477_509_816.05, "liquidado": 318_962_998.72,
                                               "pago": 313_012_618.28}
    prox = G.proxima_pagina(lido.ajax, 1)
    assert prox["alvo"] == prefixo + "RichWidgets_wt150$block$wt28" and prox["baldes"] == "__OSVSTATE,"


def test_popups_reais_de_liquidacao_e_pagamento_somam_a_linha():
    base = {"empenho": EMP1, "credor": "ITAU UNIBANCO S.A.", "orgao": "SECRETARIA MUNICIPAL DE GOVERNO",
            "elemento": "31901100", "consulta": LISTA.id}
    liq = G.eventos_do_popup(_f("liquidacao_popup_real.html"), "liquidacao",
                             LISTA.popups["liquidacao"]["colunas"], base)
    assert [(e["tipo"], e["ordem"], e["data"], e["valor"]) for e in liq] == [
        ("anulacao", "0316702026", "2026-11-24", 435_537.30),          # a primeira liquidação foi anulada
        ("liquidacao", "0316862026", "2026-11-24", 735_537.30),
        ("liquidacao", "0317092026", "2026-11-24", 435_339.76)]
    assert round(sum(e["valor"] for e in liq if e["tipo"] == "liquidacao"), 2) == 1_170_877.06
    pag = G.eventos_do_popup(_f("pagamento_popup_real.html"), "pagamento", LISTA.popups["pagamento"]["colunas"], base)
    assert [(e["tipo"], e["ordem"], e["valor"], e["fonte"]) for e in pag] == [
        ("pagamento", "202611010023100110001", 735_537.30, "501"),
        ("pagamento", "202611010023100110002", 435_339.76, "501")]
    assert all(e["empenho"] == EMP1 and e["credor"] == "ITAU UNIBANCO S.A." for e in liq + pag)
    assert LISTA.popups["liquidacao"]["confirmado"] and LISTA.popups["pagamento"]["confirmado"]


def test_empenho_popup_real_tem_os_campos_e_veio_vazio():
    """A sondagem pediu o popup com "&amp;": os campos existem, os valores não vieram."""
    cfg = LISTA.popups["empenho"]
    assert not cfg["confirmado"]
    f = G.formularios(_f("empenho_popup_real.html"))[0]
    for campo, cands in cfg["campos"].items():
        assert f.achar(cands), campo
    assert f.achar(cfg["campos"]["funcao"]).endswith("wtemp_Funcao")
    assert f.achar(cfg["campos"]["fonte"]).endswith("DETALHADA_NOME_FONTE_DETALHADA")
    assert G.dados_do_empenho(_f("empenho_popup_real.html"), cfg["campos"]) == {}
    cheio = (b'<form action="EmpenhoPopUp.aspx"><input name="a$wtemp_CPF_CNPJ" value="60.701.190/0001-04"/>'
             b'<input name="a$wtemp_Funcao" value="04 - ADMINISTRACAO"/><input name="a$wtemp_SubFuncao" value=" - "/>'
             b'<textarea name="a$wtemp_Historico">FOLHA DE NOVEMBRO</textarea></form>')
    assert G.dados_do_empenho(cheio, cfg["campos"]) == {"documento": "60701190000104", "funcao": "04",
                                                         "historico": "FOLHA DE NOVEMBRO"}


def test_consulta_da_lista_real_com_popups_e_segunda_pagina():
    ler = LeitorReal()
    res = G.consultar_lista(ler, PORTAL, LISTA, {"mes": "11", "ano": "2026"})
    assert res.ok and res.paginas == 2, res.erro
    posts = [f for _u, f in ler.pedidos if f]
    prefixo = "WebPatterns_wt2$block$wtMainContent$DespesasWebBlocks_wt1$block$"
    assert posts[0][prefixo + "wtcboMes"] == "__ossli_11" and posts[0][prefixo + "wtcboAno"] == "2026"
    assert posts[0]["__AJAX"] == "__OSVSTATE," and posts[0]["__EVENTTARGET"] == prefixo + "wt86"
    assert posts[1]["__EVENTTARGET"] == prefixo + "RichWidgets_wt150$block$wt28"
    assert posts[1]["__OSVSTATE"] == G.formularios(_f("portal_despesas_real.html"))[0].campos["__OSVSTATE"]
    empenhos = [e["empenho"] for e in res.eventos if e["tipo"] == "empenho"]
    assert len(empenhos) == 8 and empenhos[0] == EMP1 and empenhos[-1] == "20261101006010017"
    liq = [e for e in res.eventos if e["tipo"] == "liquidacao"]
    assert {e["empenho"] for e in liq} == {EMP1, EMP_INSS}
    assert sum(e["valor"] for e in liq if e["empenho"] == EMP_INSS) == 238_394.59   # parcial: 424.304,55 empenhados
    falhas = [e for e in res.eventos if e["tipo"] == "falha_detalhe"]
    assert any(e["empenho"] == EMP2 and "404" in e["historico"] for e in falhas)     # popup não lido: falha descrita
    assert any("total empenhado" in e["historico"] for e in falhas)                  # o recorte não soma o mês
    # Os popups dos valores zero não são pedidos; o empenho já conhecido não pede popup de novo.
    pedidos = [u for u, f in ler.pedidos if f is None]
    assert not any("20261101004510011" in u and "PopUp" in u and "EmpenhoPopUp" not in u for u in pedidos)
    ler2 = LeitorReal()
    conhecidos = {EMP1: {"documento": "60701190000104", "liquidacao": 1_170_877.06, "pagamento": 1_170_877.06}}
    res2 = G.consultar_lista(ler2, PORTAL, LISTA, {"mes": "11", "ano": "2026"}, conhecidos=conhecidos)
    assert not any(EMP1 in u for u, f in ler2.pedidos if f is None)
    assert next(e for e in res2.eventos if e["empenho"] == EMP1)["documento"] == "60701190000104"


def test_motor_mensal_le_o_mes_e_regrava_sem_duplicar():
    con = sqlite3.connect(":memory:")
    ctx = _Ctx(_Banco(con), ["2026-11"], date(2026, 11, 27), LeitorFalso())
    ctx.ler_falso = LeitorReal()
    resumo = G.motor(ctx, PORTAL)
    assert resumo["consultas"] == 1 and resumo["falhas"] == 0
    assert con.execute("select consulta, dia, situacao from despesa_consultas").fetchall() == \
        [("despesas_favorecido", "2026-11", "lida")]
    n = con.execute("select count(*) from despesa_eventos").fetchone()[0]
    assert n > 8
    pedidos_antes = len(ctx.ler_falso.pedidos)
    ctx.ler_falso = LeitorReal()
    G.motor(ctx, PORTAL)                                   # o mês corrente é lido de novo
    assert con.execute("select count(*) from despesa_eventos").fetchone()[0] == n
    assert len(ctx.ler_falso.pedidos) < pedidos_antes      # os popups já gravados não são pedidos
    assert G.meses_a_ler(con, "despesas_favorecido", ["2026-09", "2026-10", "2026-11"], releitura=1) == \
        ["2026-11", "2026-10", "2026-09"]


def test_sondagem_cobre_a_pagina_real_e_os_popups():
    from onisciente.sondagem import CANDIDATOS
    urls = CANDIDATOS["d2_transweb"]
    for c in PORTAL.despesas:
        for p in c.paginas:
            assert PORTAL.base + p in urls
    popups = [u for u in urls if "EmpenhoPopUp.aspx" in u]
    assert popups and all("&amp;" not in u and "&Empenho=" in u for u in popups)
