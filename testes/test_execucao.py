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
    assert not [a for a in c.achados if a.tipo == "fim_de_ano_funcao"]   # 2025: nenhum dezembro acima de 12,5%
    # 28/11/2026, a despesa do portal chegou na coleta 07e130c: a asserção antiga (sem_item_a_item e
    # integridade None) descrevia o banco sem a execução do portal. Agora a cobertura é conferida contra
    # despesa_eventos lida direto, e cada empenho (órgão e número) vira um percurso. Nada depende de quantos meses
    # chegaram (14 dos 25 na coleta 07e130c); o caso "sem portal" fica em
    # test_execucao_sem_o_portal_fica_sem_item_a_item, num banco montado.
    from onisciente import partes
    con = partes.conectar_leitura(BANCO)
    try:
        por_tipo = dict(con.execute("select tipo, count(*) from despesa_eventos where tipo != 'falha_detalhe' "
                                    "group by tipo").fetchall())
        empenhos = {f"{o}|{e}" for o, e in con.execute("select distinct orgao, empenho from despesa_eventos "
                                                       "where tipo != 'falha_detalhe'")}
    finally:
        con.close()
    assert "sem_item_a_item" not in c.cobertura
    assert c.cobertura["eventos"] == sum(por_tipo.values()) > 0
    assert {t: n for t, n in c.cobertura["por_tipo"].items() if n} == por_tipo
    assert por_tipo.get("empenho") and por_tipo.get("liquidacao") and por_tipo.get("pagamento")
    assert {p.chave for p in c.percursos} == empenhos
    assert c.integridade is not None and 0.0 <= c.integridade <= 1.0
    pago = sum(p.valor_pago() for p in c.percursos)
    assert pago > 0 and abs(c.integridade * pago - sum(p.valor_pago() for p in c.percursos if p.completo)) < 1.0
    assert c.cobertura["contratos_no_banco"] > 0


def test_execucao_sem_o_portal_fica_sem_item_a_item(tmp_path):
    """O caso que a trava real descrevia antes de 28/11/2026, num banco montado só com a matriz."""
    from onisciente.historico import Banco
    b = Banco(tmp_path / "sem_portal.db")
    b.con.execute("insert into msc_itens (mes, conta_contabil, funcao, natureza_despesa, natureza_conta, valor) "
                  "values ('2025-12', '622130100', '10', '33903900', 'C', 100.0)")
    b.con.commit()
    c = X.conferir_execucao(b.con)
    assert c.cobertura.get("sem_item_a_item") is True and c.integridade is None and c.percursos == []
    assert c.cobertura["eventos"] == 0
    b.con.close()


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
    # 28/11/2026, mudança autorizada pelo coordenador da Frente D2 (rodada 11): esta trava fixava
    # __AJAX == "__OSVSTATE," (os baldes). Prova: o _osjs.js põe no __AJAX o contexto do evento, e a
    # sondagem de 28/11/2026 07:30Z abriu a página 2 dos popups (HTTP 200) com o contexto, depois de
    # todo OsAjax com os baldes voltar HTTP 500 de 894 bytes. Trava nova: test_lista_osajax_*.
    assert corpo["__EVENTTARGET"] == prefixo + "wt86"
    assert corpo["__AJAX"] == "1280,900,WebPatterns_wt2_block_wtMainContent_DespesasWebBlocks_wt1_block_wt86,0,0,0,0,0,0,"
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
    # Quinta rodada: a sondagem de 28/11/2026 pediu com "&" e o popup trouxe os valores; o coordenador
    # mandou marcar confirmado = true (ver test_empenho_popup_com_dados_real). O recorte antigo continua vazio.
    assert cfg["confirmado"]
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
    # 28/11/2026, mudança autorizada pelo coordenador da Frente D2 (rodada 11): esta trava fixava
    # __AJAX == "__OSVSTATE," (os baldes). Prova: o _osjs.js põe no __AJAX o contexto do evento, e a
    # sondagem de 28/11/2026 07:30Z abriu a página 2 dos popups (HTTP 200) com o contexto, depois de
    # todo OsAjax com os baldes voltar HTTP 500 de 894 bytes. Trava nova: test_lista_osajax_*.
    assert posts[0]["__AJAX"].startswith("1280,900,WebPatterns_wt2_block_wtMainContent_DespesasWebBlocks_wt1_block_wt86,")
    assert posts[0]["__EVENTTARGET"] == prefixo + "wt86"
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


# --- A sondagem da página real (quarta rodada): os pedidos montados pelo coletor, sem rede --------

def test_sondagem_segue_o_empenho_popup_com_e_comercial():
    from onisciente import sondagem
    url = PORTAL.base + "Portal_Despesas.aspx"
    novos = sondagem._seguir("d2_transweb", url, Leitura(True, url, _f("portal_despesas_real.html"), http=200))
    popups = [u for u in novos if "EmpenhoPopUp.aspx" in u]
    assert popups and all("&amp;" not in u and "&Empenho=" in u for u in popups)
    assert popups[0].startswith("https://www10.goiania.go.gov.br/DespesasWebBlocks/EmpenhoPopUp.aspx?CdOrgao=1101"
                                f"&Empenho={EMP1}&NmOrgao=")


def test_sondagem_monta_buscar_pagina_2_e_exportacao():
    from onisciente import sondagem
    url = PORTAL.base + "Portal_Despesas.aspx"
    pedidos, guardados = [], []

    def ler(destino, *, tempo=60, fonte="", formulario=None):
        pedidos.append((destino, formulario, tempo))
        if formulario.get("__AJAX") and formulario["__EVENTTARGET"].endswith("$wt86"):
            return Leitura(True, destino, _f("portal_despesas_pagina2_sintetico.txt"), http=200)
        return Leitura(True, destino, b"ok", http=200)

    def guardar(fonte, destino, leitura, formulario):
        guardados.append((fonte, destino, formulario))
        return {"fonte": fonte, "url": destino, "ok": leitura.ok}

    pagina = Leitura(True, url, _f("portal_despesas_real.html"), http=200)
    regs = sondagem._conversa_despesas("d2_transweb", url, pagina, ler_=ler, guardar=guardar)
    assert [r["passo"] for r in regs] == ["a_buscar_osajax", "b_pagina_2_osajax", "c_exportar_csv",
                                          "d_buscar_postback"]
    assert len(guardados) == 4 and all(t == 90 for _d, _f2, t in pedidos)
    prefixo = "WebPatterns_wt2$block$wtMainContent$DespesasWebBlocks_wt1$block$"
    inicial = G.formularios(_f("portal_despesas_real.html"))[0].campos["__OSVSTATE"]
    (u1, a, _), (u2, b, _), (u3, c, _), (u4, d, _) = pedidos
    assert u1.startswith(url + "?_ts=") and u2.startswith(url + "?_ts=") and u3 == u4 == url
    # 28/11/2026, mudança autorizada pelo coordenador da Frente D2 (rodada 11): esta trava fixava
    # __AJAX == "__OSVSTATE," (os baldes). Prova: o _osjs.js põe no __AJAX o contexto do evento, e a
    # sondagem de 28/11/2026 07:30Z abriu a página 2 dos popups (HTTP 200) com o contexto, depois de
    # todo OsAjax com os baldes voltar HTTP 500 de 894 bytes. Trava nova: test_lista_osajax_*.
    assert a["__EVENTTARGET"] == prefixo + "wt86" and a["__OSVSTATE"] == inicial
    assert a["__AJAX"] == "1280,900,WebPatterns_wt2_block_wtMainContent_DespesasWebBlocks_wt1_block_wt86,0,0,0,0,0,0,"
    assert a[prefixo + "wtcboMes"] == "__ossli_10" and a[prefixo + "wtcboAno"] == "2026"
    assert prefixo + "wt86" not in a                                     # o OsAjax não manda botão
    assert b["__EVENTTARGET"] == prefixo + "RichWidgets_wt150$block$wt28"            # (28/11/2026: ver acima)
    assert b["__AJAX"] == ("1280,900,WebPatterns_wt2_block_wtMainContent_DespesasWebBlocks_wt1_block_"
                           "RichWidgets_wt150_block_wt28,0,0,0,0,0,0,")
    assert b["__OSVSTATE"] == "ESTADO-SINTETICO-DA-PAGINA-2"            # o estado da resposta (a)
    assert c[prefixo + "wtselExportar"] == "__ossli_2" and c[prefixo + "wtbtnExportar"] == "OK"
    assert "__AJAX" not in c and c["__OSVSTATE"] == "ESTADO-SINTETICO-DA-PAGINA-2"
    assert c[prefixo + "wtcboMes"] == "__ossli_10" and c["__EVENTTARGET"] == ""
    assert d[prefixo + "wt86"] == "Buscar" and "__AJAX" not in d and d["__OSVSTATE"] == inicial
    # Quinta rodada: a exportação montada assim respondeu com a planilha (sondagem de 28/11/2026).
    assert LISTA.exportar["confirmado"]


# --- A exportação CSV (quinta rodada): o caminho principal da página real ---------------------------
# exportacao_outubro_real.csv: o cabeçalho e todas as linhas de dez empenhos (credores pessoas
# jurídicas) da planilha que a sondagem de 28/11/2026 (run 46087866124) baixou para outubro de 2026,
# byte a byte. empenho_popup_com_dados_real.html: o EmpenhoPopUp pedido com "&" na mesma sondagem.

CSV_OUT = "exportacao_outubro_real.csv"
PREFIXO = "WebPatterns_wt2$block$wtMainContent$DespesasWebBlocks_wt1$block$"


def _exportacao():
    return G.eventos_da_exportacao(_f(CSV_OUT), LISTA.exportar["colunas"], consulta=LISTA.id)


def test_exportacao_real_vira_empenho_liquidacao_e_pagamento():
    assert LISTA.exportar["confirmado"] and LISTA.exportar["formato"] == "CSV"
    exp = _exportacao()
    assert (exp.linhas, exp.incompletas, exp.empenhos) == (19, 0, 10)
    assert exp.por_mes == {"2026-10": 19}                     # só os empenhos do mês pedido
    tipos = [e["tipo"] for e in exp.eventos]
    assert {t: tipos.count(t) for t in set(tipos)} == {"empenho": 10, "liquidacao": 13, "pagamento": 13,
                                                        "anulacao": 1}
    por = {}
    for e in exp.eventos:
        por.setdefault(e["empenho"], []).append(e)
    emp = next(e for e in por["20261601023130011"] if e["tipo"] == "empenho")
    assert (emp["data"], emp["valor"], emp["documento"], emp["credor"]) == \
        ("2026-10-09", 19775.4, "40155486000151", "FS COMERCIO E DISTRIBUICAO DE BRINQUEDOS LTDA")
    assert (emp["modalidade"], emp["licitacao"], emp["elemento"]) == ("Dispensa de Licitação", "000000532026", "44905200")
    assert (emp["funcao"], emp["subfuncao"], emp["fonte"]) == ("04", "122", "100")
    assert emp["historico"].startswith("EMPENHO DE DESPESA COM CONTRATACAO DE EMPRESA ESPECIALIZADA")
    assert emp["orgao"] == "SECRETARIA MUNICIPAL DE FINANCAS"
    # Duas liquidações anuladas (saldo 0,00, uma com ordem de pagamento de 0,00) ficam fora.
    assert [(e["tipo"], e["ordem"], e["data"], e["valor"]) for e in por["20261601023130011"] if e["tipo"] != "empenho"] == \
        [("liquidacao", "0278952026", "2026-10-15", 19775.4), ("pagamento", "202616010231300110002", "2026-10-15", 19775.4)]
    # Três linhas iguais na planilha: uma liquidação e um pagamento só.
    assert sorted(e["tipo"] for e in por["20261601020830005"]) == ["empenho", "liquidacao", "pagamento"]
    # Empenho anulado por inteiro: o empenho e a anulação, sem liquidação.
    assert [(e["tipo"], e["valor"]) for e in por["20261401002010001"]] == [("empenho", 23368.8), ("anulacao", 23368.8)]
    folha = next(e for e in por["20261101002310009"] if e["tipo"] == "empenho")
    assert folha["licitacao"] == "" and folha["modalidade"] == "Não se aplica (Ex.: Despesas com Pessoal)"
    assert folha["documento"] == "60701190000104" and folha["elemento"] == "31901100"
    somas = G.somas_por_empenho(exp.eventos)
    assert somas["20261101002310009"] == {"empenho": 1171475.97, "liquidacao": 1171475.97, "pagamento": 1171475.97}
    # Liquidação e pagamento de novembro num empenho de outubro: a planilha vai até a data da leitura.
    assert ("pagamento", "2026-11-06", 24975.0) in [(e["tipo"], e["data"], e["valor"]) for e in por["20261601020730019"]]


def test_exportacao_recusa_pagina_de_erro_e_pula_linha_cortada():
    with pytest.raises(ValueError, match="não é a planilha"):
        G.eventos_da_exportacao(b"<html><body>Erro Interno</body></html>", LISTA.exportar["colunas"])
    cortado = _f(CSV_OUT).rsplit(b";", 5)[0]                  # a última linha sem as cinco últimas colunas
    exp = G.eventos_da_exportacao(cortado, LISTA.exportar["colunas"])
    assert (exp.linhas, exp.incompletas) == (18, 1)


def test_cpf_com_zeros_na_coluna_cnpj_vira_cpf():
    # Valores sintéticos: um CPF válido de exemplo (não é de ninguém conhecido) e o CNPJ do Itaú.
    assert G.cpf_valido("52998224725") and not G.cpf_valido("52998224724")
    assert G.cnpj_valido("60701190000104") and not G.cnpj_valido("60701190000105")
    # Sétima rodada: o CPF é gravado mascarado (repositório público), como o Portal e o QSA publicam.
    assert G.documento_do_credor("00052998224725") == "***.982.247-**"
    assert G.documento_do_credor("60701190000104") == "60701190000104"
    assert G.documento_do_credor("01536754000123") == "01536754000123"     # CNPJ que começa com 0
    assert G.documento_do_credor("00052998224724") == "00052998224724"     # nem CPF nem CNPJ: fica


def test_empenho_popup_com_dados_real():
    cfg = LISTA.popups["empenho"]
    assert cfg["confirmado"]
    d = G.dados_do_empenho(_f("empenho_popup_com_dados_real.html"), cfg["campos"])
    assert d["documento"] == "60701190000104" and d["credor"] == "ITAU UNIBANCO S.A."
    assert (d["funcao"], d["subfuncao"], d["elemento"], d["dotacao"]) == ("04", "122", "31901100", "202611010023")
    assert d["data"] == "2026-11-24"
    assert "licitacao" not in d                              # 000000000000: sem processo licitatório
    assert d["historico"].startswith("EMPENHO ORDINARIO PARA PAGAMENTO DA FOLHA")


def test_banco_antigo_ganha_modalidade_e_licitacao():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE despesa_eventos (tipo TEXT, empenho TEXT, ordem TEXT, data TEXT, orgao TEXT, credor TEXT, "
                "documento TEXT, valor REAL, elemento TEXT, fonte TEXT, funcao TEXT, subfuncao TEXT, dotacao TEXT, "
                "historico TEXT, consulta TEXT, url TEXT, sha256 TEXT, coletado_em TEXT)")
    G.criar_tabelas(con)
    colunas = [r[1] for r in con.execute("PRAGMA table_info(despesa_eventos)")]
    assert colunas[-2:] == ["modalidade", "licitacao"]
    assert G.gravar(con, _exportacao().eventos) == 37


def _popup(cabecalho, linhas):
    """Popup SINTÉTICO no formato dos recortes reais (uma tabela com o cabeçalho real)."""
    th = "".join(f"<th>{c}</th>" for c in cabecalho)
    trs = "".join("<tr>" + "".join(f"<td>{x}</td>" for x in ln) + "</tr>" for ln in linhas)
    return f"<html><body><table><tr>{th}</tr>{trs}</table></body></html>".encode()


class LeitorExportacao:
    """GET da página real; o postback da exportação devolve o recorte real da planilha; os popups da
    amostra são sintéticos (nenhum popup de outubro foi lido) ou faltam."""

    def __init__(self, exportacao=CSV_OUT, popups=None):
        self.pedidos: list[tuple[str, dict | None]] = []
        self.exportacao = exportacao
        self.popups = popups or {}

    def __call__(self, url, formulario=None, **_):
        self.pedidos.append((url, formulario))
        if formulario is not None:
            if formulario.get(PREFIXO + "wtbtnExportar") and self.exportacao:
                return Leitura(True, url, _f(self.exportacao), http=200)
            return Leitura(False, url, b"", erro="HTTP 500", http=500)
        if url.endswith("Portal_Despesas.aspx"):
            return Leitura(True, url, _f("portal_despesas_real.html"), http=200)
        if url in self.popups:
            return Leitura(True, url, self.popups[url], http=200)
        return Leitura(False, url, b"", erro="HTTP 404", http=404)


def test_motor_le_o_mes_pela_exportacao_e_confere_a_amostra():
    liq = "https://www10.goiania.go.gov.br/DespesasWebBlocks/LiquidacaoPopUp.aspx?Empenho="
    pag = "https://www10.goiania.go.gov.br/DespesasWebBlocks/PagamentoPopUp.aspx?Empenho="
    cab_l, cab_p = ["Liquidação", "Data", "Saldo Liquidado", "Valor Anulado"], ["Ordem de Pagamento", "Data OP",
                                                                                 "Valor Pago", "Valor OP"]
    popups = {
        liq + "20261101002310009": _popup(cab_l, [["0289912026", "26/10/2026", "732.127,06", "0,00"],
                                                  ["0290112026", "26/10/2026", "439.348,91", "0,00"]]),
        pag + "20261101002310009": _popup(cab_p, [["202611010023100090001", "26/10/2026", "732.127,06", "732.127,06"],
                                                  ["202611010023100090002", "26/10/2026", "439.348,91", "439.348,91"]]),
        liq + "20261101002310010": _popup(cab_l, [["0290182026", "26/10/2026", "726.516,79", "0,00"]]),  # falta uma
    }
    con = sqlite3.connect(":memory:")
    ctx = _Ctx(_Banco(con), ["2026-10"], date(2026, 11, 28), LeitorFalso())
    ctx.ler_falso = LeitorExportacao(popups=popups)
    resumo = G.motor(ctx, PORTAL)
    assert resumo == {"eventos": 37, "consultas": 1, "falhas": 0, "vazias": 0}
    (cid, mes, sit, linhas, url, nota), = con.execute(
        "select consulta, dia, situacao, linhas, url, erro from despesa_consultas").fetchall()
    assert (cid, mes, sit, linhas, url) == ("despesas_favorecido", "2026-10", "lida", 19, PORTAL.base + "Portal_Despesas.aspx")
    assert nota.startswith("exportação CSV")
    assert "amostra 20261101002310010: liquidacao soma 726516.79 no popup e 982660.12 na exportação" in nota
    assert "amostra 20261101002310010: popup de pagamento não lido (HTTP 404)" in nota
    assert "20261101002310009" not in nota                   # a amostra que bateu não vira nota
    corpo = next(f for _u, f in ctx.ler_falso.pedidos if f)
    assert corpo[PREFIXO + "wtselExportar"] == "__ossli_2" and corpo[PREFIXO + "wtbtnExportar"] == "OK"
    assert corpo[PREFIXO + "wtcboMes"] == "__ossli_10" and corpo[PREFIXO + "wtcboAno"] == "2026"
    assert "__AJAX" not in corpo and corpo["__EVENTTARGET"] == ""
    assert not any(f and f.get("__EVENTTARGET", "").endswith("$wt86") for _u, f in ctx.ler_falso.pedidos)
    linha = con.execute("select documento, credor, historico, modalidade, licitacao, fonte, funcao, elemento "
                        "from despesa_eventos where tipo = 'empenho' and empenho = '20261601020730019'").fetchone()
    assert linha[:2] == ("31537116000198", "GMS GOIAS MERCANTIL E SOLUCOES LTDA") and linha[3:] == \
        ("Pregão", "000000582023", "100", "04", "33903900")
    # A releitura do mês troca o que a exportação anterior gravou dos mesmos empenhos, sem duplicar.
    ctx.ler_falso = LeitorExportacao(popups=popups)
    G.motor(ctx, PORTAL)
    assert con.execute("select count(*) from despesa_eventos").fetchone()[0] == 37


def test_motor_sem_pagina_para_e_registra_a_falha():
    con = sqlite3.connect(":memory:")
    ctx = _Ctx(_Banco(con), ["2026-09", "2026-10"], date(2026, 11, 28), LeitorFalso())

    class Fora(LeitorExportacao):
        def __call__(self, url, formulario=None, **_):
            self.pedidos.append((url, formulario))
            return Leitura(False, url, b"", erro="HTTP 503", http=503)

    ctx.ler_falso = Fora()
    resumo = G.motor(ctx, PORTAL)
    assert resumo["falhas"] == 1 and resumo["consultas"] == 1          # um mês só: a página não abriu
    assert con.execute("select dia, situacao from despesa_consultas").fetchall() == [("2026-10", "falha")]


def test_conferencias_rodam_no_recorte_real_da_exportacao():
    """Percursos e ordem da despesa com a execução real (o recorte de dez empenhos de outubro)."""
    con = sqlite3.connect(":memory:")
    G.gravar(con, _exportacao().eventos)
    conf = X.conferir_execucao(con)
    assert conf.cobertura["por_tipo"] == {"empenho": 10, "liquidacao": 13, "ordem_pagamento": 0, "pagamento": 13,
                                          "anulacao": 1}
    p = {x.chave.split("|")[1]: x for x in conf.percursos}
    assert len(p) == 10
    assert {Estacao.EMPENHO, Estacao.LIQUIDACAO, Estacao.PAGAMENTO} <= p["20261601020730019"].acesas()
    assert p["20261601020730019"].valor_pago() == 62695.0
    assert p["20261401002010001"].acesas() == {Estacao.EMPENHO}          # anulado: só o empenho
    ordem = {a.chave.split("|")[1]: a for a in conf.achados if a.tipo == "ordem"}
    # Pago em 15/10/2026 e liquidado em 16/10/2026 (juros do contrato com o BNDES): indício, não acusação.
    assert list(ordem) == ["20261603003530022"]
    assert "pagamento antes da liquidação" in ordem["20261603003530022"].descricao


# --- Sexta rodada: a coleta real gravou zero eventos (rodada 46093388087) --------------------------
# O POST da exportação voltou com 19.654 bytes, sem a planilha. O corpo do pedido montado pelo motor é
# igual, campo a campo, ao da sondagem que recebeu a planilha; a diferença é a sessão: a sondagem lê
# com um CookieJar, e o leitor comum do banco histórico (coletores/base.py) não guarda cookies, então
# o postback chegava sem o ASP.NET_SessionId do GET. erro_interno_real.html: a página "Erro Interno"
# que o portal deu ao Buscar por postback na sondagem de 28/11/2026.

import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def test_postback_da_exportacao_vai_com_o_cookie_da_sessao_do_get():
    """Servidor local (sem rede): o GET dá o cookie de sessão; o POST só o devolve dentro da sessão."""
    from onisciente.coletores.base import ler
    cookies = []

    class Portal(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Set-Cookie", "ASP.NET_SessionId=sessao-de-teste; path=/; HttpOnly")
            self.end_headers()
            self.wfile.write(b"<html><form id='WebForm1'></form></html>")

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            cookies.append(self.headers.get("Cookie"))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Empenho;VlEmpenhado\r\n")

    servidor = ThreadingHTTPServer(("127.0.0.1", 0), Portal)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{servidor.server_address[1]}/transweb/Portal_Despesas.aspx"
    try:
        ler(url)
        ler(url, formulario={"__OSVSTATE": "x"})                 # como o motor da rodada 5 lia
        antes = urllib.request._opener
        with G.sessao_de_cookies():
            ler(url)
            ler(url, formulario={"__OSVSTATE": "x"})
        assert urllib.request._opener is antes                  # o abridor anterior volta no fim
        ler(url, formulario={"__OSVSTATE": "x"})
    finally:
        servidor.shutdown()
    assert cookies == [None, "ASP.NET_SessionId=sessao-de-teste", None]


def _conversa_da_ultima_sondagem(pasta):
    """Os passos da conversa com Portal_Despesas.aspx (GET, a_buscar_osajax, b_pagina_2_osajax e
    c_exportar_csv) de UMA mesma sondagem: a mais nova cujo índice traz a exportação. O GET fica sempre
    no mesmo arquivo (9cc968ae: URL sem corpo) e é regravado a cada sondagem; os POSTs têm o estado no
    nome do arquivo e ficam de sondagens antigas. Por isso os quatro vêm do mesmo índice, e o GET só vale
    se o arquivo tiver os bytes que o índice registrou."""
    import json
    indices = []
    for arq in pasta.glob("indice_*.json"):
        try:
            d = json.loads(arq.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        indices.append((d.get("quando", ""), d.get("leituras", [])))
    for _quando, leituras in sorted(indices, key=lambda x: x[0], reverse=True):
        regs = [r for r in leituras if r.get("fonte") == "d2_transweb" and r.get("arquivo")]
        passos = {r.get("passo"): r for r in regs if r.get("passo")}
        get = next((r for r in regs if not r.get("passo") and not r.get("post")
                    and r.get("url", "").endswith("/transweb/Portal_Despesas.aspx")), None)
        if "c_exportar_csv" in passos and get is not None:
            return get, passos
    return None, {}


def test_corpo_da_exportacao_do_motor_e_o_da_sondagem_que_funcionou():
    """O pedido do motor, montado da mesma página, é igual ao que a sondagem enviou (o POST guardado
    no cabeçalho da resposta real da exportação): a diferença não está no corpo.

    28/11/2026, rodada 12: esta trava comparava o GET 9cc968ae com o POST guardado em d4b55a13. Prova
    do que mudou, com o que está guardado: o __OSVSTATE do GET foi o mesmo nas sondagens de 00:29Z,
    03:34Z e 06:34Z (g6t2...) e outro na de 07:57Z (AoBn...); o GET é regravado a cada sondagem, mas o
    d4b55a13 não (o nome do arquivo vem do corpo, e o corpo de 07:57Z é outro). Além disso, com a lista
    por OsAjax funcionando (HTTP 200 desde 07:57Z), a exportação da sondagem parte do estado da resposta
    da página 2 (o último __OSVSTATE dela, qEJL...), e não mais do GET: o POST de 07:57Z está em
    9693dd3c. A trava agora segue a conversa de uma mesma sondagem, passo a passo, como a sondagem faz."""
    import json
    pasta = RAIZ / "relatorios" / "onisciente" / "sondagem"
    get, passos = _conversa_da_ultima_sondagem(pasta)
    if get is None:
        pytest.skip("respostas da sondagem ausentes")

    def guardado(reg):
        arq = pasta / reg["arquivo"]
        if not arq.exists():
            pytest.skip(f"resposta da sondagem ausente: {reg['arquivo']}")
        bruto = arq.read_bytes()
        cab, corpo = bruto.split(b"\n\n", 1)
        linhas = cab.decode().splitlines()
        post = json.loads(next(ln[6:] for ln in linhas if ln.startswith("POST: ")))
        return post, corpo, next(ln[7:] for ln in linhas if ln.startswith("BYTES: "))

    _p, pagina, bytes_get = guardado(get)
    if int(bytes_get) != get.get("bytes"):
        pytest.skip("o GET guardado já é de outra sondagem")
    form = G.formularios(pagina)[0]
    estado = dict(form.campos)
    a, b = passos.get("a_buscar_osajax"), passos.get("b_pagina_2_osajax")
    if a is not None and a.get("ok"):                 # como a sondagem: o estado vem da resposta que deu certo
        corpo_a, resposta_a, _ = guardado(a)
        estado, ajax, _h, _l = G.depois_da_resposta(G.estado_do_envio(corpo_a, form), list(form.ajax), resposta_a)
        if b is not None and b.get("ok"):
            _corpo_b, resposta_b, _ = guardado(b)
            estado, ajax, _h, _l = G.depois_da_resposta(estado, ajax, resposta_b)
    enviado, _resposta, _ = guardado(passos["c_exportar_csv"])
    assert G.corpo_exportar(form, LISTA, {"mes": "10", "ano": "2026"}, "CSV", estado=estado) == enviado


def test_motivo_legivel_da_resposta_que_nao_e_a_planilha():
    m = G.motivo_da_resposta(_f("erro_interno_real.html"))
    assert m.startswith("título 'Internal Error'; texto 'TransWeb salva Voltar Erro Interno Um erro interno ocorreu")
    assert "Device Emulation" not in m
    with pytest.raises(ValueError, match="não é a planilha.*Erro Interno"):
        G.eventos_da_exportacao(_f("erro_interno_real.html"), LISTA.exportar["colunas"])
    assert G.motivo_da_resposta(b"") == "resposta vazia"


@dataclass
class _CtxColetas(_Ctx):
    """Como o banco histórico: cada leitura vira uma linha de coletas, com o mês que o motor passou."""

    def ler(self, motor, alvo, url, mes=None, formulario=None, tempo=60):
        lida = self.ler_falso(url, formulario=formulario)
        self.banco.con.execute("INSERT INTO coletas VALUES (?,?,?,?,?,?,?,?)",
                               (motor, alvo, mes or "", url, int(lida.ok), lida.http, lida.erro or None,
                                len(lida.conteudo)))
        return lida


def test_motor_anota_o_motivo_na_coleta_grava_o_mes_e_nao_repete_a_reserva():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE coletas (motor, alvo, mes, url, ok, http, erro, bytes)")
    ctx = _CtxColetas(_Banco(con), ["2026-09", "2026-10"], date(2026, 11, 28), LeitorFalso())
    sessoes = []

    class ErroInterno(LeitorExportacao):
        def __call__(self, url, formulario=None, **kw):
            sessoes.append(any(isinstance(h, urllib.request.HTTPCookieProcessor)
                               for h in urllib.request._opener.handlers))
            if formulario is not None and formulario.get(PREFIXO + "wtbtnExportar"):
                self.pedidos.append((url, formulario))
                return Leitura(True, url, _f("erro_interno_real.html"), http=200)
            return super().__call__(url, formulario, **kw)

    ctx.ler_falso = ErroInterno()
    resumo = G.motor(ctx, PORTAL)
    assert all(sessoes)                                         # toda leitura dentro da sessão de cookies
    assert resumo == {"eventos": 0, "consultas": 2, "falhas": 2, "vazias": 0}
    linhas = con.execute("select mes, ok, http, erro from coletas order by rowid").fetchall()
    assert {m for m, *_ in linhas} == {"2026-10", "2026-09"}      # coletas.mes preenchido
    exportacoes = [ln for ln in linhas if ln[2] == 200 and ln[3]]
    assert len(exportacoes) == 2 and all(ok == 0 for _m, ok, _h, _e in exportacoes)
    assert "não é a planilha" in exportacoes[0][3] and "Erro Interno" in exportacoes[0][3]
    buscar = [ln for ln in linhas if ln[2] == 500]
    assert len(buscar) == 1 and buscar[0][0] == "2026-10"        # a reserva tentada uma vez só
    notas = dict(con.execute("select dia, erro from despesa_consultas").fetchall())
    assert "Erro Interno" in notas["2026-10"] and "reserva (Buscar): HTTP 500" in notas["2026-10"]
    assert "reserva não tentada (o Buscar deu HTTP 500 no mês 2026-10)" in notas["2026-09"]


def test_sondagem_repete_o_caminho_do_motor_em_tres_meses():
    from onisciente import sondagem
    pedidos, guardados, abridores = [], [], []

    def ler(destino, *, tempo=60, fonte="", formulario=None):
        pedidos.append((destino, formulario))
        if formulario is None:
            return Leitura(True, destino, _f("portal_despesas_real.html"), http=200)
        if formulario.get("__AJAX"):
            return Leitura(False, destino, b"", erro="HTTP 500", http=500)
        return Leitura(True, destino, _f(CSV_OUT if abridores[-1] else "erro_interno_real.html"), http=200)

    def guardar(fonte, destino, leitura, formulario):
        guardados.append(destino)
        return {"fonte": fonte, "url": destino, "ok": leitura.ok}

    regs = sondagem._caminho_do_motor("d2_transweb_motor", ler_=ler, guardar=guardar, abridor=abridores.append)
    assert abridores == [False, True, True, True, True, True]       # cada variante com sessão nova
    exportar = [r for r in regs if r["passo"] == "exportar"]
    assert [r["variante"] for r in exportar] == ["sem_cookies-2026-10", "com_cookies-2024-11", "com_cookies-2025-06",
                                                 "com_cookies-2026-10", "buscar_antes-2026-10"]
    assert not exportar[0]["planilha"] and "Erro Interno" in exportar[0]["motivo"]
    assert all(r["planilha"] and r["linhas"] == 19 for r in exportar[1:])
    assert [r["passo"] for r in regs if r["variante"] == "buscar_antes-2026-10"] == ["get", "buscar_osajax", "exportar"]
    meses = [f[PREFIXO + "wtcboMes"] for _d, f in pedidos if f and not f.get("__AJAX")]
    assert meses == ["__ossli_10", "__ossli_11", "__ossli_06", "__ossli_10", "__ossli_10"]
    assert len(set(guardados)) == len(guardados)                    # nenhuma resposta sobrescreve outra
    assert sondagem.CANDIDATOS["d2_transweb_motor"] == []


# --- Sétima rodada: os meses que faltaram e o CPF mascarado ----------------------------------------
# A coleta 46099474353 leu só 2026-11 a 2025-10 (14 meses em 338 s): o limite de meses por rodada
# era 14, e a soma (historico.rodar com somar) apagava despesa_eventos e despesa_consultas antes de
# o motor rodar, então nada continuava de onde parou. O CPF de pessoa física ia inteiro para o banco
# (7.292 linhas num repositório público). CPFs dos testes: números de exemplo válidos, sem dono.

import time

CPF_EXEMPLO = "52998224725"                  # o número de exemplo de validadores públicos de CPF


def test_coletor_nunca_grava_cpf_completo():
    con = sqlite3.connect(":memory:")
    base = {"tipo": "empenho", "data": "2026-10-01", "orgao": "SAUDE", "valor": 10.0, "credor": "FULANO"}
    eventos = [dict(base, empenho="1", documento=CPF_EXEMPLO),
               dict(base, empenho="2", documento="529.982.247-25"),
               dict(base, empenho="3", documento="000" + CPF_EXEMPLO),        # a coluna CNPJ da exportação
               dict(base, empenho="4", documento="***.982.247-**"),
               dict(base, empenho="5", documento="31537116000198", credor="GMS GOIAS MERCANTIL E SOLUCOES LTDA")]
    assert G.gravar(con, eventos) == 5
    docs = dict(con.execute("select empenho, documento from despesa_eventos").fetchall())
    assert docs == {"1": "***.982.247-**", "2": "***.982.247-**", "3": "***.982.247-**", "4": "***.982.247-**",
                    "5": "31537116000198"}                                     # o CNPJ fica inteiro
    assert not con.execute("select 1 from despesa_eventos where documento like '%" + CPF_EXEMPLO + "%' "
                           "or documento like '%52998224%'").fetchone()
    # A exportação real: nenhuma linha gravada com 11 dígitos, nem "000" e um CPF.
    con2 = sqlite3.connect(":memory:")
    G.substituir_empenhos(con2, _exportacao().eventos, LISTA.id)
    for (doc,) in con2.execute("select distinct documento from despesa_eventos"):
        assert G.documento_gravavel(doc) == doc and len(G.documento(doc)) != 11, doc
    # A resposta crua guardada pela sondagem também sai mascarada; o CNPJ válido fica.
    texto = f"x;{CPF_EXEMPLO};000{CPF_EXEMPLO};31537116000198;12345678901\r\n"
    assert G.mascarar_cpfs_no_texto(texto) == "x;***.982.247-**;***.982.247-**;31537116000198;12345678901\r\n"


def test_migracao_mascara_as_linhas_antigas_numa_rodada_do_rastreio(tmp_path):
    from onisciente import historico, rastreio
    caminho = tmp_path / "antigo.db"
    con = sqlite3.connect(caminho)
    con.executescript(historico.ESQUEMA)
    G.criar_tabelas(con)
    colunas = ", ".join(G.CAMPOS_EVENTO)
    def linha(emp, doc, credor="FULANO"):
        ev = {k: "" for k in G.CAMPOS_EVENTO}
        ev.update(tipo="empenho", empenho=emp, data="2025-10-01", orgao="SAUDE", valor=10.0, documento=doc,
                  credor=credor, coletado_em="2026-11-20")
        return [ev[k] for k in G.CAMPOS_EVENTO]
    # Como a rodada antiga gravava: o CPF inteiro, direto na tabela (sem passar pelo gravar de agora).
    con.executemany(f"INSERT INTO despesa_eventos ({colunas}) VALUES ({', '.join('?' for _ in G.CAMPOS_EVENTO)})",
                    [linha("1", CPF_EXEMPLO), linha("2", "000" + CPF_EXEMPLO), linha("3", "31537116000198", "GMS"),
                     linha("4", CPF_EXEMPLO), linha("4", "***.982.247-**")])   # o 4 já existe mascarado
    con.commit()
    con.close()
    banco = historico.Banco.abrir(caminho)
    con = banco.con
    docs = sorted(con.execute("select empenho, documento from despesa_eventos").fetchall())
    assert docs == [("1", "***.982.247-**"), ("2", "***.982.247-**"), ("3", "31537116000198"),
                    ("4", "***.982.247-**")]                      # a cópia mascarada do 4 não se repete
    modos = [m for (m,) in con.execute("select modo from rastreio_rodadas order by id")]
    assert modos == [rastreio.MODO_MIGRACAO, "mascara_cpf"]
    nota = con.execute("select detalhe from rastreio_rodadas where modo = 'mascara_cpf'").fetchone()[0]
    assert "3 linha(s)" in nota
    v = rastreio.verificar(con)
    assert v["integro"], v                                         # as linhas novas ganharam selo
    r = rastreio.registro(con, "despesa_eventos", con.execute(
        "select rowid from despesa_eventos where empenho = '1'").fetchone()[0])
    assert r["confere"]
    con.close()
    # Abrir de novo não abre outra rodada: não sobrou CPF inteiro.
    banco = historico.Banco.abrir(caminho)
    assert banco.con.execute("select count(*) from rastreio_rodadas").fetchone() == (2,)
    banco.con.close()


def _ctx_meses(con, meses):
    ctx = _Ctx(_Banco(con), meses, date(2026, 11, 28), LeitorFalso())
    ctx.ler_falso = LeitorExportacao()
    return ctx


def _meses_pedidos(ctx):
    return [f"{f[PREFIXO + 'wtcboAno']}-{f[PREFIXO + 'wtcboMes'][-2:]}" for _u, f in ctx.ler_falso.pedidos
            if f and f.get(PREFIXO + "wtbtnExportar")]


def _todos_os_meses(desde="2024-11", ate="2026-11"):
    out, (a, m) = [], map(int, desde.split("-"))
    while f"{a}-{m:02d}" <= ate:
        out.append(f"{a}-{m:02d}")
        a, m = (a + 1, 1) if m == 12 else (a, m + 1)
    return out


def test_proxima_rodada_completa_os_meses_que_faltam_sem_refazer_os_inteiros():
    meses = _todos_os_meses()
    lidos = [m for m in meses if m >= "2025-10"]                   # o que a coleta 46099474353 deixou
    faltam = sorted(set(meses) - set(lidos), reverse=True)
    assert faltam[0] == "2025-09" and faltam[-1] == "2024-11" and len(faltam) == 11
    con = sqlite3.connect(":memory:")
    G.criar_tabelas(con)
    con.executemany("INSERT INTO despesa_consultas VALUES ('despesas_favorecido', ?, '', 'lida', 1, 1, '', '', '')",
                    [(m,) for m in lidos])
    con.execute("INSERT INTO despesa_consultas VALUES ('despesas_favorecido', '2025-12', '', 'incompleta', 1, 1, "
                "'', '', '')")                                     # um mês com linha cortada não está inteiro
    ordem = G.meses_a_ler(con, LISTA.id, meses, releitura=2, faltantes_primeiro=True)
    assert ordem[:12] == ["2025-12"] + faltam                      # o que falta antes de tudo
    assert ordem[12:] == ["2026-11", "2026-10"]                    # depois, só as releituras dos recentes
    assert G.meses_a_ler(con, LISTA.id, meses, releitura=2) == ["2026-11", "2026-10", "2025-12"] + faltam
    # O motor lê o que falta primeiro e relê os 12 recentes da configuração, dentro do limite por rodada.
    assert LISTA.exportar["meses_por_rodada"] >= 23 and LISTA.exportar["releitura"] == 12
    ctx = _ctx_meses(con, meses)
    G.motor(ctx, PORTAL)
    pedidos = _meses_pedidos(ctx)
    assert pedidos[:12] == ["2025-12"] + faltam
    assert pedidos[12:] == [m for m in sorted(meses, reverse=True)[:12] if m != "2025-12"]
    assert not set(pedidos) & {"2025-10", "2025-11"}               # inteiros e fora da releitura: não refaz
    assert G.meses_a_ler(con, LISTA.id, meses, releitura=0, faltantes_primeiro=True) == []


def test_motor_para_antes_do_fim_do_tempo_e_a_soma_nao_apaga_o_que_ja_leu():
    from onisciente import historico
    meses = _todos_os_meses("2026-08", "2026-11")
    con = sqlite3.connect(":memory:")
    ctx = _ctx_meses(con, meses)
    ctx.fim_do_motor = time.monotonic() + 60                       # menos de dois minutos: nenhum mês começa
    assert G.motor(ctx, PORTAL)["consultas"] == 0 and _meses_pedidos(ctx) == []
    ctx.fim_do_motor = time.monotonic() + 3600
    assert G.motor(ctx, PORTAL)["consultas"] == 4
    # A soma (rodar com somar) apaga só as coletas do motor: os eventos e os meses lidos ficam, e a
    # rodada seguinte continua de onde parou.
    tabelas = {t for t, _f in historico.TABELAS_DO_MOTOR["execucao_goiania"]}
    assert tabelas == {"coletas"}


def test_cruzamento_com_o_pncp_casa_o_cpf_mascarado_pelos_seis_do_meio_e_o_nome(tmp_path):
    # Nenhuma conferência de empresas, impedimentos ou sócios lê despesa_eventos; o único cruzamento que
    # usava o documento inteiro do credor é o vínculo com o contrato do PNCP, que passa a casar como o QSA.
    from onisciente.historico import Banco
    b = Banco(tmp_path / "historico.db")
    con = b.con
    G.gravar(con, [_evento("empenho", "2025/000700", "2025-04-01", 50_000.0, doc=CPF_EXEMPLO, credor="Fulano de Tal"),
                   _evento("liquidacao", "2025/000700", "2025-04-10", 50_000.0, doc=CPF_EXEMPLO, credor="Fulano de Tal"),
                   _evento("pagamento", "2025/000700", "2025-04-20", 50_000.0, doc=CPF_EXEMPLO, credor="Fulano de Tal"),
                   _evento("pagamento", "2025/000701", "2025-04-20", 7_000.0, doc="***.982.247-**",
                           credor="OUTRA PESSOA")])                              # mesmo miolo, outro nome
    con.execute("insert into contratos_pncp (pncp_id, orgao_cnpj, orgao, fornecedor_ni, fornecedor, valor_global, "
                "data_assinatura) values ('pf1', '25141524000123', 'SAUDE', ?, 'FULANO DE TAL', 40000, '2025-01-10')",
                (CPF_EXEMPLO,))
    con.commit()
    ctx = X.contexto_do_banco(con)
    con.close()
    assert X.chave_pf("***.982.247-**", "Fulano  de Tál") == X.chave_pf(CPF_EXEMPLO, "FULANO DE TAL") == \
        ("982247", "FULANO DE TAL")
    assert X.chave_pf("31537116000198", "GMS") is None and X.chave_pf("***.982.247-**", "") is None
    assert [c.id for c in X.contratos_do_credor(ctx, "***.982.247-**", "FULANO DE TAL")] == ["pf1"]
    assert X.contratos_do_credor(ctx, "***.982.247-**", "OUTRA PESSOA") == []
    conf = X.conferir_execucao(tmp_path / "historico.db")
    acima = [a for a in conf.achados if a.tipo == "liquidado_acima"]
    assert len(acima) == 1 and "***.982.247-**" in acima[0].chave              # o vínculo casou pelo miolo
    assert CPF_EXEMPLO not in repr(conf.achados)


def test_tela_da_execucao_mostra_pessoa_fisica_para_o_cpf_mascarado():
    from onisciente import historico
    from onisciente.telas import entradas
    con = sqlite3.connect(":memory:")
    con.executescript(historico.ESQUEMA)
    G.gravar(con, [_evento("empenho", "2025/000800", "2025-04-01", 1_000.0, doc="***.982.247-**", credor="FULANO"),
                   _evento("empenho", "2025/000801", "2025-04-01", 1_000.0, doc="31537116000198", credor="GMS")])
    emp = {e["numero"]: e for e in entradas.execucao(con)["empenhos"]}
    assert emp["2025/000800"]["credor"] == "Pessoa física" and emp["2025/000800"]["credor_cnpj"] == ""
    assert emp["2025/000801"]["credor"] == "GMS" and emp["2025/000801"]["credor_cnpj"] == "31537116000198"
    # Duas pessoas com o mesmo miolo e nomes diferentes não se somam.
    assert X.chave_do_credor("***.982.247-**", "Fulano") != X.chave_do_credor("***.982.247-**", "Outra Pessoa")
    assert X.chave_do_credor("31537116000198", "GMS") == "31537116000198"


# --- Oitava rodada: o CPF que sobrava no credor e no histórico --------------------------------------
# A varredura da Frente H (mascara_banco.varrer) achou CPF completo em despesa_eventos.credor (o MEI vem
# como "NOME 12345678901") e em despesa_eventos.historico ("TOMADORA: NOME - CPF:NNN.NNN.NNN-NN").
# A regra é a da H para texto livre: o CPF formatado e os 11 dígitos isolados com dígito válido.

TELEFONE = "62999998888"                       # 11 dígitos sem dígito verificador de CPF
PROCESSO = "52998224724"                       # o CPF de exemplo com o último dígito trocado


def _formatado(cpf):
    return f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}"


def test_coletor_mascara_o_cpf_no_credor_e_no_historico_e_deixa_telefone_processo_e_hash():
    con = sqlite3.connect(":memory:")
    historico = (f"ADIANTAMENTO, TOMADORA: FULANA - CPF:{_formatado(CPF_EXEMPLO)}, FONE {TELEFONE}, "
                 f"PROCESSO {PROCESSO}, EMPENHO 20261101002310009, HASH ab{CPF_EXEMPLO}cd, CPF {CPF_EXEMPLO}.")
    ev = {"tipo": "empenho", "empenho": "1", "data": "2026-10-01", "orgao": "SAUDE", "valor": 10.0,
          "documento": "000" + CPF_EXEMPLO, "credor": f"FULANO DE TAL {CPF_EXEMPLO}", "historico": historico}
    G.gravar(con, [ev])
    doc, credor, hist = con.execute("select documento, credor, historico from despesa_eventos").fetchone()
    assert doc == "***.982.247-**" and credor == "FULANO DE TAL ***.982.247-**"
    assert hist == (f"ADIANTAMENTO, TOMADORA: FULANA - CPF:***.982.247-**, FONE {TELEFONE}, PROCESSO {PROCESSO}, "
                    f"EMPENHO 20261101002310009, HASH ab{CPF_EXEMPLO}cd, CPF ***.982.247-**.")
    from onisciente import mascara_banco
    assert mascara_banco.varrer(con) == {}                           # a trava da H não acha nada


def test_migracao_mascara_credor_e_historico_antigos_numa_rodada_do_rastreio(tmp_path):
    from onisciente import historico, mascara_banco, rastreio
    caminho = tmp_path / "antigo.db"
    con = sqlite3.connect(caminho)
    con.executescript(historico.ESQUEMA)
    G.criar_tabelas(con)
    colunas = list(G.CAMPOS_EVENTO)
    def linha(emp, doc, credor, hist):
        ev = {k: "" for k in colunas}
        ev.update(tipo="empenho", empenho=emp, data="2025-10-01", orgao="SAUDE", valor=10.0, documento=doc,
                  credor=credor, historico=hist, coletado_em="2026-11-20")
        return [ev[k] for k in colunas]
    # Como a coleta 550c30b gravou: o documento já mascarado, o CPF ainda no nome e no histórico.
    con.executemany(f"INSERT INTO despesa_eventos ({', '.join(colunas)}) VALUES ({', '.join('?' for _ in colunas)})",
                    [linha("1", "***.982.247-**", f"FULANO {CPF_EXEMPLO}", "COMPRA"),
                     linha("2", "31537116000198", "GMS", f"TOMADOR: FULANO - CPF:{_formatado(CPF_EXEMPLO)}"),
                     linha("3", "31537116000198", "GMS", f"FONE {TELEFONE} PROCESSO {PROCESSO}")])
    con.commit()
    assert mascara_banco.varrer(con) == {("despesa_eventos", "credor"): 1, ("despesa_eventos", "historico"): 1}
    con.close()
    banco = historico.Banco.abrir(caminho)
    con = banco.con
    linhas = dict((e, (c, h)) for e, c, h in con.execute("select empenho, credor, historico from despesa_eventos"))
    assert linhas == {"1": ("FULANO ***.982.247-**", "COMPRA"), "2": ("GMS", "TOMADOR: FULANO - CPF:***.982.247-**"),
                      "3": ("GMS", f"FONE {TELEFONE} PROCESSO {PROCESSO}")}
    nota = con.execute("select detalhe from rastreio_rodadas where modo = 'mascara_cpf'").fetchone()[0]
    assert "2 linha(s)" in nota and "documento 0, credor 1, histórico 1" in nota
    assert mascara_banco.varrer(con) == {}
    assert rastreio.verificar(con)["integro"]
    con.close()
    banco = historico.Banco.abrir(caminho)                          # abrir de novo não abre outra rodada
    assert banco.con.execute("select count(*) from rastreio_rodadas where modo = 'mascara_cpf'").fetchone() == (1,)
    banco.con.close()


def _popup_paginado(cabecalho, linhas, contador=None):
    """Popup SINTÉTICO com o rodapé do RichWidgets dos recortes reais (o contador e a navegação)."""
    html = _popup(cabecalho, linhas).decode()
    if contador:
        html = html.replace("</table>", f'</table><div class="Counter_Message">{contador}</div>'
                                        '<nav class="ListNavigation_Wrapper"></nav>')
    return html.encode()


def test_contador_do_popup_real_e_paginado():
    assert G.contador_do_popup(_f("liquidacao_popup_real.html")) == (3, 3)
    assert G.contador_do_popup(_f("pagamento_popup_inss_real.html")) == (1, 1)
    assert G.contador_do_popup('<div class="Counter_Message">1 to 50 of 1693 records</div>') == (50, 1693)
    assert G.contador_do_popup('<div class="Counter_Message">51 a 100 de 1.693 registros</div>') == (50, 1693)
    assert G.contador_do_popup("<p>sem contador</p>") is None


def test_amostra_com_popup_paginado_confere_a_primeira_pagina_pelo_numero():
    """As divergências da coleta 550c30b: o popup mostra só as primeiras 50 linhas de um empenho com mais.
    A primeira página é conferida linha a linha; a soma menor não vira divergência falsa."""
    emp = "20265150000230001"
    eventos = [{"tipo": "empenho", "empenho": emp, "valor": 60_000.0, "ordem": "", "data": "2026-01-02"}]
    for i in range(1, 53):
        dia = f"2026-{1 + (i - 1) // 6:02d}-{1 + (i - 1) % 6 * 4:02d}"
        eventos.append({"tipo": "liquidacao", "empenho": emp, "ordem": f"{i:04d}2026", "data": dia, "valor": 1000.0 + i})
        eventos.append({"tipo": "pagamento", "empenho": emp, "ordem": f"{emp}{i:04d}", "data": dia, "valor": 1000.0 + i})
    liq = [[f"{i:04d}2026", "02/01/2026", f"{1000 + i},00", "0,00"] for i in range(1, 51)]
    pag = [[f"{emp}{i:04d}", "02/01/2026", f"{1000 + i},00", f"{1000 + i},00"] for i in range(1, 51)]
    pag_errada = [list(x) for x in pag]
    pag_errada[9][2] = "9,99"
    cab_l, cab_p = ["Liquidação", "Data", "Saldo Liquidado", "Valor Anulado"], ["Ordem de Pagamento", "Data OP",
                                                                                 "Valor Pago", "Valor OP"]
    base = "https://www10.goiania.go.gov.br/DespesasWebBlocks/"

    def notas(popups):
        def ler(url, formulario=None):
            corpo = popups.get(url.split("/")[-1].split(".")[0])
            return Leitura(True, url, corpo, http=200) if corpo else Leitura(False, url, b"", erro="HTTP 404", http=404)
        return G.conferir_amostra(ler, LISTA, eventos, amostra=1)

    # Com o contador do RichWidgets ("1 to 50 of 52 records") e sem ele (a página cheia, 50 linhas).
    n = notas({"LiquidacaoPopUp": _popup_paginado(cab_l, liq, "1 to 50 of 52 records"),
               "PagamentoPopUp": _popup_paginado(cab_p, pag)})
    assert n == [f"amostra {emp}: popup de liquidacao paginado (50 de 52 linhas na primeira página): as 50 conferem "
                 "com a exportação pelo número; a soma inteira não foi conferida",
                 f"amostra {emp}: popup de pagamento paginado (50 de 52 linhas na primeira página): as 50 conferem "
                 "com a exportação pelo número; a soma inteira não foi conferida"]
    # Uma linha da página que não bate com a exportação continua divergência.
    n = notas({"LiquidacaoPopUp": _popup_paginado(cab_l, liq, "1 to 50 of 52 records"),
               "PagamentoPopUp": _popup_paginado(cab_p, pag_errada, "1 to 50 of 52 records")})
    assert n[1].startswith(f"amostra {emp}: pagamento soma") and "1 linha(s) da primeira página sem par" in n[1]
    assert f"{emp}0010 de 9.99" in n[1]
    # Sem paginação (o contador diz que é tudo), a soma menor é divergência, como antes.
    n = notas({"LiquidacaoPopUp": _popup_paginado(cab_l, liq, "50 records"),
               "PagamentoPopUp": _popup_paginado(cab_p, pag + [[f"{emp}0051", "02/01/2026", "1051,00", "1051,00"],
                                                              [f"{emp}0052", "02/01/2026", "1052,00", "1052,00"]],
                                                 "52 records")})
    assert n == [f"amostra {emp}: liquidacao soma 51275.00 no popup e 53378.00 na exportação"]


def test_sondagem_guarda_os_popups_paginados_sem_seguir_os_scripts():
    from onisciente import sondagem
    urls = sondagem.CANDIDATOS["d2_transweb_popup"]
    assert len(urls) == 8 and all(u.startswith("https://www10.goiania.go.gov.br/DespesasWebBlocks/") for u in urls)
    assert urls[0].endswith("LiquidacaoPopUp.aspx?Empenho=20262150000230001")
    lida = Leitura(True, urls[0], b'<html><script src="/x/a.js"></script><a href="B.aspx">b</a></html>', http=200)
    assert sondagem._seguir("d2_transweb_popup", urls[0], lida) == []


# --- Nona rodada: as páginas seguintes dos popups ----------------------------------------------------
# A sondagem d2_transweb_popup da integração (commit 1e36935) não leu nada: o fluxo passou as quatro
# fontes numa palavra só ("d2_transweb_popup,d1_fns,d1_tcm,d1_tcu") e nenhuma fonte tem esse nome (o
# índice veio com zero leituras). O recorte real da navegação do popup ainda não existe; o popup abaixo é
# SINTÉTICO, montado com a navegação real da lista de Portal_Despesas.aspx (o mesmo RichWidgets: o link
# ListNavigation_Next por OsAjax e o contador "1 to 20 of 822 records") e a resposta OsJSONUpdate no
# formato de portal_despesas_pagina2_sintetico.txt.

_NAV = ("WebPatterns_wt2_block_wtMainContent_DespesasWebBlocks_wt1_block_RichWidgets_wt9_block_wt28",
        "WebPatterns_wt2$block$wtMainContent$DespesasWebBlocks_wt1$block$RichWidgets_wt9$block$wt28")
_CAB_L = ["Liquidação", "Data", "Saldo Liquidado", "Valor Anulado"]


def _linhas_liq(de, ate):
    return "".join(f"<tr><td>{i:04d}2026</td><td>02/01/2026</td><td>{1000 + i},00</td><td>0,00</td></tr>"
                   for i in range(de, ate + 1))


def _popup_com_navegacao(empenho, de, ate, total):
    th = "".join(f"<th>{c}</th>" for c in _CAB_L)
    nav = (f'<a id="{_NAV[0]}" class="ListNavigation_Next" onclick="OsAjax(arguments[0] || window.event,'
           f"&#39;{_NAV[0]}&#39;,&#39;{_NAV[1]}&#39;,&#39;&#39;,&#39;__OSVSTATE,&#39;,&#39;&#39;); return false;\" "
           'href="#">next</a>') if ate < total else ""
    return (f'<html><body><form name="WebForm1" method="post" action="LiquidacaoPopUp.aspx?Empenho={empenho}" '
            f'id="WebForm1"><input type="hidden" name="__OSVSTATE" id="__OSVSTATE" value="ESTADO-1" />'
            f'<table id="tabela"><thead><tr>{th}</tr></thead><tbody>{_linhas_liq(de, ate)}</tbody></table>'
            f'<div id="rodape"><div class="Counter_Message">{de} to {ate} of {total} records</div>'
            f'<nav class="ListNavigation_Wrapper">{nav}</nav></div></form></body></html>').encode()


def _resposta_osajax(de, ate, total, estado):
    import json
    th = "".join(f"<th>{c}</th>" for c in _CAB_L)
    nav = "" if ate >= total else (f'<a id="{_NAV[0]}" class="ListNavigation_Next" onclick="OsAjax(arguments[0] || '
                                   f"window.event,&#39;{_NAV[0]}&#39;,&#39;{_NAV[1]}&#39;,&#39;&#39;,"
                                   '&#39;__OSVSTATE,&#39;,&#39;&#39;); return false;" href="#">next</a>')
    corpo = {"hidden": {"__OSVSTATE": estado},
             "outers": {"tabela": {"inner": f"<thead><tr>{th}</tr></thead><tbody>{_linhas_liq(de, ate)}</tbody>"},
                        "rodape": {"inner": f'<div class="Counter_Message">{de} to {ate} of {total} records</div>'
                                            f'<nav class="ListNavigation_Wrapper">{nav}</nav>'}}}
    return f'<script type="text/javascript">OsJSONUpdate({json.dumps(corpo)});</script>'.encode()


class LeitorDePopupPaginado:
    """O GET dá a primeira página (50 linhas); cada postback do next dá as 50 seguintes por OsAjax."""

    def __init__(self, total, empenho="20265151000730001"):
        self.total, self.empenho, self.pedidos = total, empenho, []

    def __call__(self, url, formulario=None, **_):
        self.pedidos.append((url, formulario))
        if formulario is None:
            return Leitura(True, url, _popup_com_navegacao(self.empenho, 1, min(50, self.total), self.total), http=200)
        pagina = len([f for _u, f in self.pedidos if f])
        assert formulario["__OSVSTATE"] == f"ESTADO-{pagina}"       # o estado da resposta anterior volta
        assert formulario.get("__AJAX") and formulario["__EVENTTARGET"] == _NAV[1]
        de = 50 * pagina + 1
        return Leitura(True, url, _resposta_osajax(de, min(de + 49, self.total), self.total, f"ESTADO-{pagina + 1}"),
                       http=200)


def test_popup_paginado_e_lido_inteiro_pelo_next_e_a_soma_confere():
    emp = "20265151000730001"
    cfg = LISTA.popups["liquidacao"]
    ler = LeitorDePopupPaginado(120, emp)
    pop = G.ler_popup(ler, cfg["endereco"].format(empenho=emp), "liquidacao", cfg["colunas"], {"empenho": emp})
    assert pop.completo and pop.paginas == 3 and pop.total == 120 and not pop.erro
    assert [e["ordem"] for e in pop.eventos] == [f"{i:04d}2026" for i in range(1, 121)]
    assert ler.pedidos[1][0] == f"https://www10.goiania.go.gov.br/DespesasWebBlocks/LiquidacaoPopUp.aspx?Empenho={emp}"
    # Na amostra: a soma das três páginas bate com a exportação, e nenhuma nota sai.
    eventos = [{"tipo": "empenho", "empenho": emp, "valor": 200_000.0, "ordem": "", "data": "2026-01-02"}]
    for i in range(1, 121):
        eventos.append({"tipo": "liquidacao", "empenho": emp, "ordem": f"{i:04d}2026", "data": "2026-01-02",
                        "valor": 1000.0 + i})
        eventos.append({"tipo": "pagamento", "empenho": emp, "ordem": f"{emp}{i:04d}", "data": "2026-01-02",
                        "valor": 1000.0 + i})

    def so_liquidacao(url, formulario=None):
        if "PagamentoPopUp" in url:
            return Leitura(False, url, b"", erro="HTTP 404", http=404)
        return ler(url, formulario)
    ler = LeitorDePopupPaginado(120, emp)
    assert G.conferir_amostra(so_liquidacao, LISTA, eventos, amostra=1) == [
        f"amostra {emp}: popup de pagamento não lido (HTTP 404)"]
    # Uma linha a menos na exportação: a soma inteira não bate e a nota diz quantas páginas foram lidas.
    ler = LeitorDePopupPaginado(120, emp)
    menos = [e for e in eventos if not (e["tipo"] == "liquidacao" and e["ordem"] == "01202026")]
    nota = G.conferir_amostra(so_liquidacao, LISTA, menos, amostra=1)[0]
    assert nota == f"amostra {emp}: liquidacao soma 127260.00 no popup e 126140.00 na exportação (3 páginas lidas)"


def test_popup_que_nao_leva_a_pagina_seguinte_fica_incompleto():
    emp = "20265151000730001"
    cfg = LISTA.popups["liquidacao"]

    class SemSeguinte(LeitorDePopupPaginado):
        def __call__(self, url, formulario=None, **kw):
            if formulario is not None:
                return Leitura(False, url, b"", erro="HTTP 500", http=500)
            return super().__call__(url, formulario, **kw)
    pop = G.ler_popup(SemSeguinte(120, emp), cfg["endereco"].format(empenho=emp), "liquidacao", cfg["colunas"],
                      {"empenho": emp})
    assert not pop.completo and pop.paginas == 1 and len(pop.eventos) == 50
    assert pop.erro == "página 2 do popup: HTTP 500"


def test_sondagem_le_as_fontes_separadas_por_virgula_e_segue_as_paginas_do_popup():
    from onisciente import sondagem
    assert sondagem.fontes_da_linha(["d2_transweb_popup,d1_fns,d1_tcm,d1_tcu"]) == \
        ["d2_transweb_popup", "d1_fns", "d1_tcm", "d1_tcu"]
    assert sondagem.fontes_da_linha(["d1_fns", " d1_tcm , ", ""]) == ["d1_fns", "d1_tcm"]
    guardados = []
    leitor = LeitorDePopupPaginado(120)

    def ler(destino, *, tempo=60, fonte="", formulario=None):
        if "PagamentoPopUp" in destino:
            return Leitura(False, destino, b"", erro="HTTP 404", http=404)
        return leitor(destino, formulario)

    def guardar(fonte, destino, leitura, formulario):
        guardados.append(destino)
        return {"fonte": fonte, "url": destino, "ok": leitura.ok}

    urls = [u for u in sondagem.CANDIDATOS["d2_transweb_popup"] if "20265151000730001" in u]
    regs = sondagem._popups_paginados("d2_transweb_popup", urls, ler_=ler, guardar=guardar)
    resumo = [r for r in regs if r.get("passo") == "resumo"]
    assert [(r["tipo"], r["paginas"], r["total"], r["completo"], r["linhas"]) for r in resumo] == [
        ("liquidacao", 3, 120, True, 120), ("pagamento", 0, None, False, 0)]
    assert len(set(guardados)) == len(guardados) == 4               # três páginas e o pagamento, sem sobrescrever
    assert all("http" in r and "erro" in r for r in resumo)         # o __main__ imprime os dois


# --- Rodada 10 (28/11/2026): a página 2 do popup voltou HTTP 500 (894 bytes) nos 8 casos -------------------
# A sondagem de 06:50Z leu a página 1 dos popups (HTTP 200) e o pedido da página 2 voltou 500 em todos. O
# mesmo 500 de 894 bytes veio em TODOS os OsAjax que o Onisciente já mandou (o Buscar e a página 2 da
# lista em Portal_Despesas.aspx, com ``?_ts=``, e o buscar_antes do motor): a lista por OsAjax nunca
# funcionou; o que funciona é a exportação por postback comum. Lendo o _osjs.js guardado, o ``__AJAX``
# que o navegador manda é o CONTEXTO do evento, e não os baldes (``__OSVSTATE,``) que mandávamos.
# Fixtures reais: liquidacao_popup_pagina1_real.html (a página 1, 4c444fbd), o pedido da página 2 com a
# resposta 500 (4f7c1915) e os recortes do _osjs.js.

_URL_POPUP_REAL = "https://www10.goiania.go.gov.br/DespesasWebBlocks/LiquidacaoPopUp.aspx?Empenho=20262150000230001"
_NEXT_REAL = "WebPatterns_wt13$block$wtMainContent$RichWidgets_wt1$block$wt28"
_CAIXA_REAL = "WebPatterns_wt13$block$wt5$wt4$wt43$wtCheckbox$wt37"


def _pedido_500_real() -> dict:
    import json
    return json.loads(_f("liquidacao_popup_pagina2_pedido_500_real.json").decode("utf-8"))


def test_osjs_real_poe_o_contexto_do_evento_no_ajax_e_nao_os_baldes():
    import re
    js = _f("osjs_osajax_recorte_real.js").decode("utf-8")
    # OsAjax(e, origem, alvo, evento, baldes, f): o contexto é montado com (e, origem, f)...
    assert "bucketIds:e,eventContext:OsBuildAjaxEventContext(a,b,f)" in js
    # ...e vai como o quinto argumento até o PrepareFormForSubmit, que o põe no __AJAX.
    assert "OsExecuteCallToServer(a.origin,a.eventTarget,a.ajaxEvent,a.bucketIds,a.eventContext," in js
    assert "osAjaxBackend.CallToServer(j,b,c,d,e,f)" in js
    assert "this.PrepareFormForSubmit(a,b,c,d,e);" in js
    prep = re.search(r"this\.PrepareFormForSubmit=function\(a,b,c,d,e\)\{.*", js).group(0)
    assert 'g.name="__AJAX"' in prep and prep.endswith("g.value=e,")          # e = o contexto, não d = os baldes
    # O contexto: largura, altura, origem, topo, esquerda, rolagens, x, y e o sexto argumento.
    assert "return d+o+e+o+f+o+g+o+h+o+k+o+l+o+m+o+n+o+c}" in js and 'var o=",";' in js
    # O envio: POST com ?_ts=, o tipo do corpo com charset e o X-Requested-With do jQuery.
    assert '"?_ts="+(new Date).getTime(),type:"POST",contentType:"application/x-www-form-urlencoded; charset=UTF-8"' in js
    assert 'e["X-Requested-With"]="XMLHttpRequest"' in js


def test_pedido_da_pagina_2_do_popup_real_leva_o_contexto_do_evento_e_os_cabecalhos_do_osajax():
    pagina1 = _f("liquidacao_popup_pagina1_real.html")
    antigo = _pedido_500_real()
    assert antigo["http"] == 500 and antigo["bytes"] == 894 and not antigo["ok"]
    form = G.formularios(pagina1)[0]
    assert form.acao == "LiquidacaoPopUp.aspx" and G.contador_do_popup(pagina1) == (50, 65)
    estado, links, _html, _lido = G.depois_da_resposta({}, [], pagina1)
    prox = G.proxima_pagina(links, 1)
    # O id do next do popup é o da página (não o da lista), e é o que o motor mandou.
    assert prox["alvo"] == antigo["post"]["__EVENTTARGET"] == _NEXT_REAL
    assert prox["id"] == "WebPatterns_wt13_block_wtMainContent_RichWidgets_wt1_block_wt28" and prox["extra"] == ""
    # O recorte do 500 é o pedido que o motor montava: o mesmo corpo, campo a campo, fora o __AJAX e a
    # caixa (28/11/2026, rodada 11: corpo_proxima da lista passou a mandar o contexto, como o popup).
    acao = "https://www10.goiania.go.gov.br/DespesasWebBlocks/LiquidacaoPopUp.aspx"
    lista = G.corpo_proxima(acao, estado, prox, ajax=True)
    assert {k: v for k, v in lista.items() if k not in ("__AJAX", _CAIXA_REAL)} == \
        {k: v for k, v in antigo["post"].items() if k not in ("__AJAX", _CAIXA_REAL)}
    assert antigo["post"]["__AJAX"] == "__OSVSTATE," and antigo["post"][_CAIXA_REAL] == ""
    assert "X-Requested-With" not in antigo["cabecalhos"]
    # O pedido novo leva o que faltava: o contexto do evento no __AJAX, a caixa marcada como "on" e os
    # cabeçalhos do OsAjax; o resto (o __OSVSTATE da página 1, o alvo, os campos) fica igual.
    corpo, cab = G.pedido_da_pagina_seguinte_do_popup(form, _URL_POPUP_REAL, estado, prox)
    assert corpo["__AJAX"] == "1280,900,WebPatterns_wt13_block_wtMainContent_RichWidgets_wt1_block_wt28,0,0,0,0,0,0,"
    assert corpo[_CAIXA_REAL] == "on"
    assert {k for k in corpo if corpo[k] != antigo["post"].get(k)} == {"__AJAX", _CAIXA_REAL}
    assert set(corpo) == set(antigo["post"]) and "__AJAXEVENT" not in corpo
    assert corpo["__OSVSTATE"] == form.campos["__OSVSTATE"]
    assert cab == {"X-Requested-With": "XMLHttpRequest", "Accept": "text/plain, */*; q=0.01",
                   "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                   "Referer": _URL_POPUP_REAL, "Origin": "https://www10.goiania.go.gov.br"}
    # 28/11/2026, rodada 11 (autorizado pelo coordenador): esta linha fixava a lista com os baldes no
    # __AJAX; a sondagem de 07:30Z abriu a página 2 dos popups com o contexto, e a lista passa a mandá-lo.
    assert G.Formulario(acao, "post", campos=estado).envio_ajax({}, _NEXT_REAL)["__AJAX"] == corpo["__AJAX"]


def test_ler_popup_real_manda_o_pedido_novo_e_o_500_fica_como_pagina_incompleta():
    pagina1 = _f("liquidacao_popup_pagina1_real.html")
    antigo = _pedido_500_real()
    pedidos = []

    def ler(url, formulario=None, cabecalhos=None):
        pedidos.append((url, formulario, cabecalhos))
        if formulario is None:
            return Leitura(True, url, pagina1, http=200)
        return Leitura(False, url, antigo["corpo"].encode(), erro=antigo["erro"], http=antigo["http"])

    cfg = LISTA.popups["liquidacao"]
    pop = G.ler_popup(ler, _URL_POPUP_REAL, "liquidacao", cfg["colunas"], {"empenho": "20262150000230001"})
    assert pop.paginas == 1 and pop.total == 65 and not pop.completo and len(pop.eventos) == 50
    assert pop.erro == "página 2 do popup: HTTP 500"
    (u1, f1, c1), (u2, f2, c2) = pedidos
    assert u1 == _URL_POPUP_REAL and f1 is None and c1 is None
    assert u2 == "https://www10.goiania.go.gov.br/DespesasWebBlocks/LiquidacaoPopUp.aspx"
    assert f2["__AJAX"].startswith("1280,900,WebPatterns_wt13_block_wtMainContent_RichWidgets_wt1_block_wt28,")
    assert f2["__EVENTTARGET"] == _NEXT_REAL and c2["X-Requested-With"] == "XMLHttpRequest"
    assert c2["Referer"] == _URL_POPUP_REAL
    # O leitor do motor (ctx.ler) recebe os cabeçalhos; um leitor sem o parâmetro recebe o pedido sem eles.
    assert G._so_com_cabecalhos(lambda url, formulario=None: None, {"a": "b"}) == {}
    assert G._so_com_cabecalhos(lambda url, formulario=None, **kw: None, {"a": "b"}) == {"cabecalhos": {"a": "b"}}


def test_sondagem_guarda_o_pedido_inteiro_e_o_corpo_do_500_do_popup(monkeypatch, tmp_path):
    from onisciente import sondagem
    pagina1 = _f("liquidacao_popup_pagina1_real.html")
    monkeypatch.setattr(sondagem, "PASTA", tmp_path)
    vistos = []

    def ler(destino, *, tempo=60, fonte="", formulario=None, cabecalhos=None):
        vistos.append((destino, cabecalhos))
        if formulario is None:
            return Leitura(True, destino, pagina1, http=200)
        return Leitura(False, destino, b"<html>Erro do servidor de teste</html>", erro="HTTP 500", http=500)

    regs = sondagem._popups_paginados("d2_transweb_popup", [_URL_POPUP_REAL], ler_=ler)
    pag2 = [r for r in regs if r.get("passo") == "pagina_2"][0]
    assert vistos[1][1]["X-Requested-With"] == "XMLHttpRequest"
    assert pag2["destino"] == "https://www10.goiania.go.gov.br/DespesasWebBlocks/LiquidacaoPopUp.aspx"
    assert "X-Requested-With" in pag2["cabecalhos"] and "Referer" in pag2["cabecalhos"]
    texto = (tmp_path / pag2["arquivo"]).read_text(encoding="utf-8")
    assert "CABECALHOS: " in texto and '"X-Requested-With": "XMLHttpRequest"' in texto
    assert "Erro do servidor de teste" in texto                      # o corpo do 500 agora fica guardado
    assert '"__AJAX": "1280,900,' in texto
    # O cookie vai só com o nome; o valor da sessão nunca entra no arquivo.
    assert sondagem._sem_valor_de_cookie("ASP.NET_SessionId=abc123; osVisitor=zz") == \
        "ASP.NET_SessionId=<valor omitido>; osVisitor=<valor omitido>"
    guardado = sondagem._guardar("d2_transweb_popup", _URL_POPUP_REAL + "#pagina-2",
                                 Leitura(False, _URL_POPUP_REAL, b"x", erro="HTTP 500", http=500), {"a": "1"},
                                 cabecalhos={"Cookie": "ASP.NET_SessionId=segredo123", "Referer": _URL_POPUP_REAL})
    texto = (tmp_path / guardado["arquivo"]).read_text(encoding="utf-8")
    assert "segredo123" not in texto and "ASP.NET_SessionId=<valor omitido>" in texto


# --- Rodada 11 (28/11/2026): a página 2 real dos popups, aberta pelo contexto do evento ------------------
# A sondagem de 28/11/2026 07:30Z, com o pedido da rodada 10, leu a página 2 de liquidação e de pagamento
# dos 4 empenhos (HTTP 200, 18 a 54 KB) e as páginas 2 e 3 do de 1.695 e 1.718 linhas. Fixtures reais do
# empenho 20262150000230001 (credor pessoa jurídica): as páginas 1 e 2 dos dois popups e as linhas da
# exportação desse empenho no banco real (despesa_eventos, coleta de 28/11/2026).

_EMP_REAL = "20262150000230001"
_POPUPS_REAIS = {
    "liquidacao": ("liquidacao_popup_pagina1_real.html", "liquidacao_popup_pagina2_real.txt", 65),
    "pagamento": ("pagamento_popup_pagina1_real.html", "pagamento_popup_pagina2_real.txt", 60),
}


def _exportacao_real() -> list[dict]:
    import json
    return json.loads(_f(f"exportacao_empenho_{_EMP_REAL}_real.json").decode("utf-8"))["eventos"]


class LeitorDosPopupsReais:
    """GET: a página 1 real do popup; POST pelo next: a página 2 real (resposta OsAjax)."""

    def __init__(self):
        self.pedidos = []

    def __call__(self, url, formulario=None, cabecalhos=None):
        self.pedidos.append((url, formulario, cabecalhos))
        tipo = "liquidacao" if "LiquidacaoPopUp" in url else "pagamento"
        p1, p2, _total = _POPUPS_REAIS[tipo]
        return Leitura(True, url, _f(p1) if formulario is None else _f(p2), http=200)


@pytest.mark.parametrize("tipo", ["liquidacao", "pagamento"])
def test_popup_real_pagina_2_le_da_linha_51_em_diante_sem_repetir_a_primeira(tipo):
    p1, p2, total = _POPUPS_REAIS[tipo]
    cfg = LISTA.popups[tipo]
    # A página 2 real é a resposta OsAjax do next: o contador diz 51 em diante, e ela não repete a 1.
    _e, _l, html2, _lido = G.depois_da_resposta({}, [], _f(p2))
    assert G.contador(html2) == (51, total, total)
    chave = lambda e: (e["tipo"], e["ordem"], e["data"], e["valor"])   # noqa: E731
    pag1 = [chave(e) for e in G.eventos_do_popup(_f(p1).decode("utf-8"), tipo, cfg["colunas"],
                                                    {"empenho": _EMP_REAL}, url="u")]
    pag2 = [chave(e) for e in G.eventos_do_popup(html2, tipo, cfg["colunas"], {"empenho": _EMP_REAL}, url="u")]
    assert len(pag1) == 50 and len(pag2) == total - 50 and not set(pag1) & set(pag2)
    # ler_popup lê as duas e para no contador: todas as linhas, nenhuma repetida.
    ler = LeitorDosPopupsReais()
    url = cfg["endereco"].format(empenho=_EMP_REAL)
    pop = G.ler_popup(ler, url, tipo, cfg["colunas"], {"empenho": _EMP_REAL})
    assert pop.completo and pop.paginas == 2 and pop.total == total and not pop.erro
    assert [chave(e) for e in pop.eventos] == pag1 + pag2
    # O pedido que abriu a página 2: o contexto do evento no __AJAX e os cabeçalhos do OsAjax.
    _u, corpo, cab = ler.pedidos[1]
    assert corpo["__AJAX"].startswith("1280,900,") and cab["X-Requested-With"] == "XMLHttpRequest"


def test_popup_real_soma_das_duas_paginas_bate_com_a_exportacao_linha_a_linha():
    exportacao = _exportacao_real()
    cfg = LISTA.popups
    for tipo, (_p1, _p2, _total) in _POPUPS_REAIS.items():
        pop = G.ler_popup(LeitorDosPopupsReais(), cfg[tipo]["endereco"].format(empenho=_EMP_REAL), tipo,
                          cfg[tipo]["colunas"], {"empenho": _EMP_REAL})
        do_popup = sorted((e["ordem"], round(e["valor"], 2)) for e in pop.eventos if e["tipo"] == tipo)
        da_exportacao = sorted((e["ordem"], round(e["valor"], 2)) for e in exportacao if e["tipo"] == tipo)
        assert len(do_popup) == 59 and do_popup == da_exportacao
        assert round(sum(v for _o, v in do_popup), 2) == 568_320_000.00
    # As outras linhas do popup não são liquidação nem pagamento: 6 anulações (65 - 59) e 1 ordem (60 - 59).
    liq = G.ler_popup(LeitorDosPopupsReais(), cfg["liquidacao"]["endereco"].format(empenho=_EMP_REAL),
                      "liquidacao", cfg["liquidacao"]["colunas"], {"empenho": _EMP_REAL})
    assert sorted({e["tipo"] for e in liq.eventos}) == ["anulacao", "liquidacao"]
    assert len([e for e in liq.eventos if e["tipo"] == "anulacao"]) == 6
    # Na amostra do motor: as duas páginas somadas batem com a exportação e nenhuma nota sai.
    assert G.conferir_amostra(LeitorDosPopupsReais(), LISTA, exportacao, amostra=1) == []


def test_popup_no_teto_de_paginas_diz_que_parou_no_teto():
    emp = "20265151000730001"
    cfg = LISTA.popups["liquidacao"]
    pop = G.ler_popup(LeitorDePopupPaginado(120, emp), cfg["endereco"].format(empenho=emp), "liquidacao",
                      cfg["colunas"], {"empenho": emp}, paginas_maximas=2)
    assert not pop.completo and pop.paginas == 2 and len(pop.eventos) == 100
    assert pop.erro == "parou no teto de 2 página(s): 100 de 120 linha(s) lidas"


class LeitorRealComCabecalhos(LeitorReal):
    def __init__(self):
        super().__init__()
        self.cabecalhos = []

    def __call__(self, url, formulario=None, cabecalhos=None, **kw):
        self.cabecalhos.append((formulario, cabecalhos))
        return super().__call__(url, formulario, **kw)


def test_lista_osajax_leva_o_contexto_do_evento_e_os_cabecalhos_como_o_popup_aberto():
    # 28/11/2026, rodada 11: autorizado pelo coordenador depois da sondagem de 07:30Z (a página 2 dos
    # popups abriu com o contexto do evento no __AJAX). O Buscar e o next da lista mandam o mesmo.
    ler = LeitorRealComCabecalhos()
    res = G.consultar_lista(ler, PORTAL, LISTA, {"mes": "11", "ano": "2026"})
    assert res.ok and res.paginas == 2, res.erro
    prefixo = "WebPatterns_wt2_block_wtMainContent_DespesasWebBlocks_wt1_block_"
    posts = [(f, c) for f, c in ler.cabecalhos if f]
    (buscar, cab1), (proxima, cab2) = posts[0], posts[1]
    assert buscar["__AJAX"] == f"1280,900,{prefixo}wt86,0,0,0,0,0,0,"               # o id do botão Buscar
    assert proxima["__AJAX"] == f"1280,900,{prefixo}RichWidgets_wt150_block_wt28,0,0,0,0,0,0,"
    assert "__OSVSTATE," not in (buscar["__AJAX"], proxima["__AJAX"])
    for cab in (cab1, cab2):
        assert cab["X-Requested-With"] == "XMLHttpRequest" and cab["Accept"] == "text/plain, */*; q=0.01"
        assert cab["Content-Type"] == "application/x-www-form-urlencoded; charset=UTF-8"
        assert cab["Referer"] == PORTAL.base + "Portal_Despesas.aspx" and cab["Origin"] == "https://www10.goiania.go.gov.br"
    # Sem a chamada OsAjax na página, o id de origem é o alvo com $ trocado por _ (o id do ASP.NET).
    f = G.Formulario("x.aspx", "post", campos={"__OSVSTATE": "E"}, tipos={"c": "checkbox"})
    corpo = f.envio_ajax({}, "a$b$wt9")
    assert corpo["__AJAX"] == "1280,900,a_b_wt9,0,0,0,0,0,0," and corpo["c"] == "off"


# --- Rodada 12 (28/11/2026): a lista por OsAjax real e o popup de 1.695 linhas lido inteiro --------------
# A sondagem de 28/11/2026 07:57Z, com o código da rodada 11, recebeu HTTP 200 no Buscar e na página 2 da
# lista em Portal_Despesas.aspx por OsAjax (858 KB e 851 KB; antes, HTTP 500) e leu inteiros os 8 popups.
# Recortes reais: lista_osajax_buscar_real.txt e lista_osajax_pagina2_real.txt (o bloco da tabela, o
# contador, o navegador e o último __OSVSTATE; os credores pessoas físicas com o nome trocado).

_ID_NEXT_DA_LISTA = "WebPatterns_wt2_block_wtMainContent_DespesasWebBlocks_wt1_block_RichWidgets_wt150_block_wt28"


def _linhas_da_lista(html) -> list[dict]:
    lido = G.ler_html(html)
    tabs = [t for t in lido.tabelas if not LISTA.tabela or t.id.endswith(LISTA.tabela)] or lido.tabelas
    tabela, mapa = G.tabela_de_resultado(tabs, LISTA.colunas)
    out = []
    for linha in tabela.linhas:
        evs = G.eventos_da_tabela(G.Tabela(tabela.id, tabela.cabecalho, [linha]), mapa, LISTA.tipo,
                                  consulta=LISTA.id, url="u", padrao_dotacao=PORTAL.dotacao, fixos={})
        out.append({**evs[0], "popups": G._popups_da_linha(LISTA, [h for cel in linha for h in cel.links])})
    return out


def test_lista_osajax_real_buscar_e_pagina_2_leem_20_linhas_cada_sem_repetir():
    buscar, pagina2 = _f("lista_osajax_buscar_real.txt"), _f("lista_osajax_pagina2_real.txt")
    # O Buscar: a resposta OsAjax traz a tabela da página 1 e o estado novo.
    estado, links, html1, _lido = G.depois_da_resposta({"__OSVSTATE": "DO-GET"}, [], buscar)
    assert G.contador(html1) == (1, 20, 792)
    linhas1 = _linhas_da_lista(html1)
    assert len(linhas1) == 20 and linhas1[0]["empenho"] == "20261101002310009"
    assert linhas1[0]["credor"] == "ITAU UNIBANCO S.A." and linhas1[0]["valor"] == 1_171_475.97
    assert linhas1[0]["popups"]["liquidacao"].endswith("LiquidacaoPopUp.aspx?Empenho=20261101002310009")
    # O pedido da página 2 sai do estado do Buscar, pelo next da lista, com o contexto do evento: o mesmo
    # que a sondagem mandou e que voltou HTTP 200 (o __OSVSTATE é o último da resposta do Buscar).
    prox = G.proxima_pagina(links, 1)
    assert prox["id"] == _ID_NEXT_DA_LISTA
    corpo = G.corpo_proxima(PORTAL.base + "Portal_Despesas.aspx", estado, prox, ajax=True)
    assert corpo["__OSVSTATE"] == estado["__OSVSTATE"] != "DO-GET"
    assert corpo["__AJAX"] == f"1280,900,{_ID_NEXT_DA_LISTA},0,0,0,0,0,0,"
    # A página 2: linhas 21 a 40 de 792, nenhum empenho da página 1.
    estado2, _links2, html2, _lido2 = G.depois_da_resposta(estado, links, pagina2)
    assert G.contador(html2) == (21, 40, 792) and estado2["__OSVSTATE"] != estado["__OSVSTATE"]
    linhas2 = _linhas_da_lista(html2)
    assert len(linhas2) == 20 and linhas2[0]["empenho"] == "20261101006010015"
    empenhos1, empenhos2 = [e["empenho"] for e in linhas1], [e["empenho"] for e in linhas2]
    assert len(set(empenhos1)) == len(set(empenhos2)) == 20 and not set(empenhos1) & set(empenhos2)
    assert all(e["data"].startswith("2026-10") for e in linhas1 + linhas2)
    assert "PESSOA FISICA 1 (NOME RETIRADO DO RECORTE)" in [e["credor"] for e in linhas2]


def test_lista_osajax_real_lida_pelo_motor_ate_onde_ha_pagina():
    """consultar_lista com o GET real guardado nas fixtures, o Buscar e a página 2 reais da sondagem de
    07:57Z: lê as duas páginas, as 40 linhas, sem repetir; a página 3 não está no recorte."""
    buscar, pagina2 = _f("lista_osajax_buscar_real.txt"), _f("lista_osajax_pagina2_real.txt")
    pedidos = []

    def ler(url, formulario=None, cabecalhos=None):
        pedidos.append((formulario, cabecalhos))
        if formulario is None:
            if "PopUp" in url:
                return Leitura(False, url, b"", erro="fora do recorte", http=404)
            return Leitura(True, url, _f("portal_despesas_real.html"), http=200)
        n = len([f for f, _c in pedidos if f])
        if n == 1:
            return Leitura(True, url, buscar, http=200)
        if n == 2:
            return Leitura(True, url, pagina2, http=200)
        return Leitura(False, url, b"", erro="página 3 fora do recorte", http=404)

    conhecidos = {e: {"documento": "x", "liquidado": 0.0, "pago": 0.0}
                  for e in [ln["empenho"] for ln in _linhas_da_lista(G.depois_da_resposta({}, [], buscar)[2])]
                  + [ln["empenho"] for ln in _linhas_da_lista(G.depois_da_resposta({}, [], pagina2)[2])]}
    res = G.consultar_lista(ler, PORTAL, LISTA, {"mes": "10", "ano": "2026"}, conhecidos=conhecidos)
    empenhos = [e["empenho"] for e in res.eventos if e["tipo"] == "empenho"]
    assert res.paginas == 2 and len(empenhos) == 40 == len(set(empenhos))
    assert not res.ok and res.erro == "página 3: página 3 fora do recorte"
    posts = [(f, c) for f, c in pedidos if f]
    assert posts[1][0]["__AJAX"] == f"1280,900,{_ID_NEXT_DA_LISTA},0,0,0,0,0,0,"
    assert posts[1][1]["X-Requested-With"] == "XMLHttpRequest"


def test_popup_real_de_1695_linhas_fecha_com_a_exportacao():
    """Empenho 20261201000430004 (credor pessoa jurídica: o Tribunal de Justiça de Goiás). A sondagem de
    07:57Z leu o popup de liquidação inteiro (34 páginas, 1.695 linhas) e o de pagamento (35 páginas,
    1.718 linhas): 1.693 liquidações e 1.693 pagamentos, iguais à exportação em número e em soma
    (16.441.027,87). As 2 linhas a mais do popup de liquidação são linhas sem saldo liquidado e as 25 a
    mais do de pagamento são linhas sem valor pago: o coletor não as conta como liquidação nem como
    pagamento (eventos_do_popup), e a exportação também não. O corpo das páginas 4 em diante não foi
    guardado; a próxima sondagem lista essas linhas no resumo (outras_linhas)."""
    import json
    conf = json.loads(_f("popup_20261201000430004_conferencia_real.json").decode("utf-8"))
    exp = conf["exportacao"]["por_tipo"]
    liq, pag = conf["sondagem"]
    assert liq["completo"] and pag["completo"] and not liq["erro"] and not pag["erro"]
    assert (liq["paginas"], liq["total"], pag["paginas"], pag["total"]) == (34, 1695, 35, 1718)
    assert liq["linhas"] == pag["linhas"] == exp["liquidacao"]["linhas"] == exp["pagamento"]["linhas"] == 1693
    assert liq["soma"] == pag["soma"] == exp["liquidacao"]["soma"] == exp["pagamento"]["soma"] == 16_441_027.87
    assert liq["total"] - liq["linhas"] == 2 and pag["total"] - pag["linhas"] == 25 and exp["anulacao"]["linhas"] == 0
    # As três primeiras páginas reais, lidas pelo motor, são as 150 primeiras liquidações da exportação em
    # ordem de data e de número, linha a linha; ler_popup diz que parou no teto.
    alvo = "20261201000430004"
    paginas = [_f(f"liquidacao_popup_{alvo}_pagina1_real.html"), _f(f"liquidacao_popup_{alvo}_pagina2_real.txt"),
               _f(f"liquidacao_popup_{alvo}_pagina3_real.txt")]
    lidas = []

    def ler(url, formulario=None, cabecalhos=None):
        lidas.append(url)
        return Leitura(True, url, paginas[len(lidas) - 1], http=200)

    cfg = LISTA.popups["liquidacao"]
    pop = G.ler_popup(ler, cfg["endereco"].format(empenho=alvo), "liquidacao", cfg["colunas"], {"empenho": alvo},
                      paginas_maximas=3)
    assert pop.total == 1695 and not pop.completo
    assert pop.erro == "parou no teto de 3 página(s): 150 de 1695 linha(s) lidas"
    do_popup = [[e["data"], e["ordem"], e["valor"]] for e in pop.eventos if e["tipo"] == "liquidacao"]
    assert do_popup == conf["exportacao"]["primeiras_liquidacoes"]
    assert len({e["ordem"] for e in pop.eventos}) == 150                 # nenhuma linha repetida entre as páginas


def test_sondagem_resume_os_tipos_e_as_linhas_que_nao_sao_do_tipo():
    from onisciente import sondagem
    leitor = LeitorDosPopupsReais()

    def ler(destino, *, tempo=60, fonte="", formulario=None, cabecalhos=None):
        return leitor(destino, formulario, cabecalhos)

    def guardar(fonte, destino, leitura, formulario, cabecalhos=None):
        return {"fonte": fonte, "url": destino, "ok": leitura.ok}

    urls = [u for u in sondagem.CANDIDATOS["d2_transweb_popup"] if _EMP_REAL in u]
    resumo = [r for r in sondagem._popups_paginados("d2_transweb_popup", urls, ler_=ler, guardar=guardar)
              if r.get("passo") == "resumo"]
    liq = next(r for r in resumo if r["tipo"] == "liquidacao")
    pag = next(r for r in resumo if r["tipo"] == "pagamento")
    assert liq["tipos"] == {"anulacao": 6, "liquidacao": 59} and pag["tipos"] == {"ordem_pagamento": 1, "pagamento": 59}
    assert [x["tipo"] for x in liq["outras_linhas"]] == ["anulacao"] * 6
    assert set(liq["outras_linhas"][0]) == {"tipo", "ordem", "data", "valor"}


# --- Décima terceira rodada: as conferências medidas no banco real (22, 30, 31, 32, 33, 55, 56, 57, 61, 63,
# 64, 66, 83, 132) -------------------------------------------------------------------------------------
#
# despesa_eventos_recorte_real.json é um recorte do banco de 28/11/2026 (155.879 eventos de 04/11/2024 a
# 26/11/2026, 25 meses lidos em despesa_consultas): os eventos de cada caso que a conferência aponta no banco
# inteiro, só credores pessoas jurídicas e sem o histórico do empenho, mais os contratos do PNCP desses
# credores e os meses lidos. No banco inteiro, depois das correções desta rodada: 3 empenhos com pagamento
# antes da liquidação, 60 credores com liquidado acima do contratado do órgão, 1.463 empenhos com três
# liquidações seguidas iguais, 47 órgãos e anos com 80% do pago em até 5 credores e 43 com um credor de 40%
# ou mais, 970 credores pagos em dois meses ou mais sem contrato do órgão, 10 órgãos com o fim de dezembro de
# 2025 acima do ritmo; integridade da trilha 0,0 (nenhum dos 24.101 percursos acende origem, fonte e dotação:
# a fonte do portal é o código antigo de três dígitos, como 100, e a matriz usa a destinação nova, como 500).

def _banco_do_recorte_real():
    import json
    from onisciente import historico
    r = json.loads((DADOS / "despesa_eventos_recorte_real.json").read_text(encoding="utf-8"))
    con = sqlite3.connect(":memory:")
    con.executescript(historico.ESQUEMA)
    G.criar_tabelas(con)
    G.gravar(con, r["eventos"], coletado_em="2026-11-28")
    for tabela in ("contratos_pncp", "pncp_contratos_detalhe", "despesa_consultas"):
        for linha in r[tabela]:
            con.execute(f"insert into {tabela} ({', '.join(linha)}) values ({', '.join('?' * len(linha))})",
                        list(linha.values()))
    con.commit()
    return con, r


def test_recorte_real_nao_tem_pessoa_fisica_nem_historico():
    import json
    import re
    _, r = _banco_do_recorte_real()
    assert len(r["eventos"]) == 212 and len(r["despesa_consultas"]) == 25
    assert all(len(re.sub(r"\D", "", e["documento"])) == 14 and "*" not in e["documento"] for e in r["eventos"])
    assert all("historico" not in e for e in r["eventos"])
    assert all(len(c["fornecedor_ni"]) == 14 for c in r["contratos_pncp"])
    texto = json.dumps(r, ensure_ascii=False)
    assert not re.search(r"\d{3}\.\d{3}\.\d{3}-\d{2}", texto)


def test_recorte_real_reproduz_as_conferencias_do_banco_inteiro():
    con, _ = _banco_do_recorte_real()
    c = X.conferir_execucao(con)
    achados = {(a.tipo, a.chave): a for a in c.achados}
    # 32 e 57: os três empenhos do banco inteiro com pagamento antes da liquidação, e só eles.
    ordem = sorted(k[1] for k in achados if k[0] == "ordem")
    assert ordem == ["SECRETARIA MUNICIPAL DE ADMINISTRACAO|20265501007010002",
                     "SECRETARIA MUNICIPAL DE EFICIENCIA|20267501000230004",
                     "SECRETARIA MUNICIPAL DE FINANCAS|20261603003530022"]
    assert all(achados[("ordem", k)].dados["problemas"] == ["pagamento antes da liquidação (Lei 4.320/1964, art. 62)"]
               for k in ordem)
    bndes = {e.tipo: e.data for e in X.ler_eventos(con) if e.empenho == "20261603003530022"}
    assert bndes["pagamento"] == date(2026, 10, 15) and bndes["liquidacao"] == date(2026, 10, 16)
    # 55: o liquidado do credor no órgão contra os contratos do mesmo órgão no PNCP.
    hosp = achados[("liquidado_acima", "05743288000108")]
    assert hosp.valor == pytest.approx(188_100.0) and hosp.limite == pytest.approx(63_000.0)
    assert hosp.dados["orgao_cnpj"] == "25141524000123"
    # A FLEXIBASE liquidou na Finanças e tem contrato na Saúde; a Equatorial e a Saneago têm contrato só com a
    # Câmara Municipal, outro Poder: nenhum dos três vira achado (antes de 28/11/2026, a Equatorial virava).
    assert [k for k in achados if k[0] == "liquidado_acima"] == [("liquidado_acima", "05743288000108")]
    # 56: as três liquidações iguais ao centavo do mesmo empenho.
    med = achados[("medicoes", "SECRETARIA MUNICIPAL DE POLITICAS PARA AS MULHERES, ASSISTENCIA SOCIAL E DIREITOS "
                               "HUMANOS|20253650029330014")]
    assert med.dados["valores"] == [138_490.0] * 3
    # 63: o PROCON em 2024, sem a folha (31), que vai ao banco pagador e não é escolha de fornecedor.
    conc = achados[("concentracao_pago", "PROGRAMA DE DEFESA DO CONSUMIDOR - PROCON|2024")]
    assert conc.limite == pytest.approx(2_432_265.75) and conc.valor == pytest.approx(2_290_036.64)
    unico = achados[("credor_unico", "PROGRAMA DE DEFESA DO CONSUMIDOR - PROCON|2024|12376894000106")]
    assert unico.valor == pytest.approx(1_690_000.0) and "EDITORA RS" in unico.descricao
    folha = sum(e.valor for e in X.ler_eventos(con) if e.tipo == "pagamento" and e.orgao.startswith("PROGRAMA DE DEFESA")
                and e.elemento.startswith("31"))
    assert folha == pytest.approx(904_235.26)
    # 64: pagos em dois meses sem contrato do órgão no PNCP.
    assert sorted(k[1] for k in achados if k[0] == "sem_contrato") == [
        "AGENCIA MUNICIPAL DE TURISMO E EVENTOS|13146254000164", "PROGRAMA DE DEFESA DO CONSUMIDOR - PROCON|02371916000183"]
    # 66: o corte de 15 dias de dezembro só nos exercícios lidos nos doze meses; 2024 (lido de novembro em
    # diante) e 2026 (sem dezembro) ficam fora, e o PROCON de 2024 já não aparece.
    fim = [a for a in c.achados if a.tipo == "fim_de_ano"]
    assert [(a.chave, a.valor, a.limite) for a in fim] == [
        ("SECRETARIA MUNICIPAL DE EFICIENCIA|2025", pytest.approx(13_499_600.61), pytest.approx(86_555_362.84))]
    assert c.cobertura["fim_de_ano_exercicios_medidos"] == [2025]
    assert c.cobertura["fim_de_ano_exercicios_incompletos"] == [2024, 2026]
    # 30 e 31: um percurso por empenho; nenhum completo, porque a fonte antiga não acende origem, fonte e dotação.
    assert len(c.percursos) == 124 and c.integridade == 0.0
    assert len(c.achados) == 10


def test_fonte_antiga_do_portal_nao_acende_origem_fonte_nem_dotacao():
    """A falta que fica nos requisitos 30, 31 e 83: o portal publica a fonte no código antigo (100, 107, 102),
    a matriz de saldos usa a destinação nova (500, 600). Com a receita e a dotação da destinação 500 no
    banco, o empenho de fonte 100 continua sem origem, fonte e dotação; a previsão (pela função) acende."""
    ctx = X.ContextoTrilha(receitas={(2025, "500")}, dotacoes={(2025, "08")}, dotacoes_fonte={(2025, "08", "500")})
    evs = [X.EventoDespesa("empenho", "20253650029330014", date(2025, 6, 2), "SEMAS", "CUIABA", "11222333000181",
                           138_490.0, "33903900", "100", "08", "244"),
           X.EventoDespesa("pagamento", "20253650029330014", date(2025, 7, 2), "SEMAS", "CUIABA", "11222333000181",
                           138_490.0, "33903900", "100", "08", "244")]
    acesas = X.percursos(evs, ctx)[0].acesas()
    assert not acesas & {Estacao.ORIGEM, Estacao.FONTE, Estacao.DOTACAO}
    assert Estacao.PREVISAO in acesas
    novo = [X.EventoDespesa(e.tipo, e.empenho, e.data, e.orgao, e.credor, e.documento, e.valor, e.elemento, "1500",
                            e.funcao, e.subfuncao) for e in evs]
    assert {Estacao.ORIGEM, Estacao.FONTE, Estacao.DOTACAO} <= X.percursos(novo, ctx)[0].acesas()


def test_vinculo_e_do_mesmo_orgao_quando_o_orgao_casa_com_o_pncp():
    con, _ = _banco_do_recorte_real()
    ctx = X.contexto_do_banco(con)
    assert X.cnpj_do_orgao("SECRETARIA MUNICIPAL DE SAUDE", ctx.orgaos_pncp) == "25141524000123"
    assert X.cnpj_do_orgao("SECRETARIA MUNICIPAL DE ADMINISTRACAO", ctx.orgaos_pncp) == "17577524000142"
    assert X.cnpj_do_orgao("SECRETARIA MUNICIPAL DE EFICIENCIA", ctx.orgaos_pncp) == ""
    # O nome quebrado do portal casa com o do PNCP com a sigla no fim.
    assert X.cnpj_do_orgao("INSTITUTO MUNICIPAL DE ASSISTENCIA A SAUDE DOS SERVIDO RES DE GOIANIA",
                           {X.chave_orgao("INSTITUTO MUNICIPAL DE ASSISTENCIA A SAUDE DOS SERVIDORES DE GOIANIA - IMAS"):
                            {"02371916000183"}}) == "02371916000183"
    # A Equatorial (CELG) tem contrato só com a Câmara: no PROCON (sem CNPJ casado no recorte) o vínculo cai no
    # contrato de qualquer órgão; num órgão casado com outro CNPJ, não.
    assert X.contratos_do_orgao(ctx, "01543032000104", "", "SECRETARIA MUNICIPAL DE SAUDE") == []


def test_trilha_da_secretaria_conta_so_o_pago_do_exercicio():
    """Requisitos 22 e 83: o vínculo da pasta multiplica o pago do exercício no parecer, então a fração é a do
    mesmo período. No recorte, a administração (função 04, subfunção 122) pagou em 2026 R$ 1.131,70 à CS Brasil
    com contrato do órgão, R$ 63.844,00 à FLEXIBASE (vínculo pelo credor: a Finanças não tem CNPJ no recorte) e
    R$ 313.669,27 ao INSS, sem contrato."""
    from onisciente.config import carregar_alvo
    from onisciente.rio import secretarias as S
    con, _ = _banco_do_recorte_real()
    c = X.conferir_execucao(con)
    evs = X.ler_eventos(con)
    adm = carregar_alvo().dominios["administracao"]
    cob, vin = S.trilha_da_secretaria(c.percursos, evs, adm, exercicio=2026)
    assert cob == 0.0 and vin == pytest.approx((1_131.70 + 63_844.0) / (1_131.70 + 63_844.0 + 313_669.27))
    assert S.trilha_da_secretaria(c.percursos, evs, adm, exercicio=2025) == (None, None)
    assert S.trilha_da_secretaria(c.percursos, evs, adm)[1] != pytest.approx(vin)   # sem o exercício, todos os anos


def test_contas_uma_a_uma_com_credor_data_e_a_ordem_sem_valor():
    """Requisito 132: credor, data e cronologia de cada saída vêm do portal; a exportação não publica o ato
    da ordem de pagamento em separado, e a coluna fica sem valor, nunca zero."""
    from onisciente.config import carregar_alvo
    from onisciente.rio import parecer_dominio as PD
    con, _ = _banco_do_recorte_real()
    saude = carregar_alvo().dominios["saude"]
    evs = [e for e in X.ler_eventos(con) if e.data and e.data.year == 2025 and saude.contem(e.funcao, e.subfuncao or None)]
    linhas = X.contas_item_a_item(evs)
    assert [x["saida"] for x in linhas] == ["HOSPCOM EQUIPAMENTOS HOSPITALARES LTDA"]
    topo = linhas[0]
    assert topo["estacoes"] == {"empenho": 314_100.0, "liquidacao": 63_000.0, "ordem_pagamento": None,
                                "pagamento": 63_000.0}
    passos = [(c["data"], c["estacao"]) for c in topo["cronologia"]]
    assert passos == sorted(passos, key=lambda p: p[0])
    assert ("2025-07-25", "liquidacao") in passos and ("2025-09-05", "pagamento") in passos

    class Ex:          # o bastante da execução da pasta para a seção do parecer
        rotulo = "Saúde"
        valores = {}
        inicial = None
        notas = []
        por_fonte = []
    Ex.valores = {k: type("V", (), {"certificacao": type("C", (), {"vias": [], "divergencia": False})(),
                                    "selo": None})() for k in ("autorizado", "empenhado", "liquidado", "pago")}
    html = PD.secao_execucao(Ex, {"item_a_item": linhas, "matriz": [], "falta": ""}, None)
    assert "HOSPCOM" in html and "sem valor" in html and "não o ato da ordem de pagamento em separado" in html


def test_entrada_da_execucao_liga_o_orgao_e_o_contrato_e_o_triangulo_fecha_a_prestacao():
    """Requisitos 33 e 61: com o banco cheio, cada empenho vai à tela Trilha com o CNPJ do órgão (para o recorte
    da secretaria) e o contrato do PNCP do credor em vigor na data, do mesmo órgão; o vértice da prestação do
    triângulo sai conferido, ausente ou aguardando. Antes de 28/11/2026 nenhum empenho levava o contrato e os
    2.118 contratos do banco real saíam todos como ausentes."""
    from onisciente.telas import dados as D
    from onisciente.telas import entradas as E
    con, r = _banco_do_recorte_real()
    y = E.execucao(con)
    por = {e["numero"]: e for e in y["empenhos"]}
    hosp = por["20252150049510002"]
    assert hosp["orgao_cnpj"] == "25141524000123" and hosp["contrato"] == "25141524000123-2-000038/2025"
    assert por["20252150021810180"]["contrato"] == ""             # empenhado antes da assinatura (07/04/2025)
    assert por["20265501007010002"]["orgao_cnpj"] == "17577524000142"
    assert por["20265501007010002"]["contrato"] == ""             # empenho de 11/03, contrato de 23/03/2026
    vertice = D.vertice_da_prestacao(y)
    estados = {c["pncp_id"]: vertice(c["pncp_id"], c["orgao_cnpj"], c["data_assinatura"]) for c in r["contratos_pncp"]}
    assert estados == {"25141524000123-2-000038/2025": "conferido",        # HOSPCOM: empenho ligado e liquidado
                       "25141524000123-2-001009/2026": "ausente",          # FLEXIBASE: empenho ligado, sem liquidação
                       "17577524000142-2-000005/2026": "ausente",          # CS Brasil: nenhum empenho depois dele
                       "00001727000193-2-000010/2025": "aguardando",       # Câmara: fora do portal da Prefeitura
                       "00001727000193-2-000012/2025": "aguardando",
                       "01414440000158-2-000027/2026": "aguardando"}       # PGM: nenhum empenho do órgão no recorte
    assert D.vertice_da_prestacao({})("x", "25141524000123", "2026-01-01") == "aguardando"

    class Originais:
        def externo(self, chave, *a, **k):
            return chave

    class Ctx:
        originais = Originais()
    lista, total = D._execucao_entrada(Ctx(), y)
    assert total["2025-12"]["o:25141524000123:*"] == 1 and total["2025-12"]["o:25141524000123:10"] == 1
    assert {x["orgao"] for x in lista if x["numero"] == "20252150049510002"} == {"25141524000123"}
