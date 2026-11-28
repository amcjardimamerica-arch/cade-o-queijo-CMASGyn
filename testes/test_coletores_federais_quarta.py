"""Bloco 5 (Frente D1), quarta rodada: os coletores diante das respostas reais da sondagem de 28/11/2026
(branch claude/project-thread-m40l41, índice ``indice_d1_fns_d1_sancoes_d1_economia_go_d1_tcu_d1_tcm_d1_transferegov``).

Respostas reais, reduzidas, em ``testes/dados/federais/``:
- ``economia_go_conciliacao_2025_real.xlsx``: a Conciliação das Distribuições de 2025 da Economia com as
  abas reais (Resoluções, Agregado e uma aba de ICMS), só três municípios em cada;
- ``economia_go_transf_2024_real.xlsx``: o demonstrativo de 2024 (``transf-municipios``) com as abas
  reais por mês (01-2024, 02-2024, 03-2024 e o acumulado), só três municípios;
- ``cnep_real.csv`` e ``sancoes_indice_cnep_real.html``: o cabeçalho real do CNEP de 27/11/2026 com sete
  linhas reais de pessoa jurídica, e o trecho da página de download com a data publicada;
- ``fns_repasse_dia_consultar_real.json``, ``fns_ultimo_pagamento_real.json``: as respostas inteiras do
  repasse do dia (15/01/2025) e da data do último pagamento;
- ``fns_detalhada_service_real.js``: o serviço da consulta detalhada do FNS, inteiro;
- ``tcm_contas_irregulares_real.csv``: o cabeçalho real dos dados abertos de contas irregulares do TCM-GO
  com nove linhas reais; nome e os dois dígitos do CPF mascarado foram trocados por fictícios.
"""

from __future__ import annotations

import io
import zipfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from onisciente import historico
from onisciente.coletores import (
    base,
    cnpj,
    economia_go,
    emendas,
    fns,
    sancoes,
    tcm,
    transferegov,
)
from onisciente.coletores import motores_federais as mf
from onisciente.conferencias import federais

DADOS = Path(__file__).parent / "dados" / "federais"
ALVO = SimpleNamespace(ibge=5208707, uf="GO", municipio="Goiânia", pncp_cnpjs=())


def _bytes(nome: str) -> bytes:
    return (DADOS / nome).read_bytes()


def _ok(url, conteudo: bytes) -> base.Leitura:
    return base.Leitura(True, url, conteudo, http=200)


def _nao(url, codigo=404) -> base.Leitura:
    return base.Leitura(False, url, erro=f"HTTP {codigo}", http=codigo)


def _zip(nome: str, conteudo: bytes) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(nome, conteudo)
    return b.getvalue()


def _ctx(tmp_path, leitor, meses=("2025-01", "2025-12"), hoje=date(2026, 11, 28)):
    banco = historico.Banco(tmp_path / "h.db")
    mf.preparar(banco)
    return historico.Contexto(banco, historico.meses(*meses), hoje, ler_url=leitor,
                              dormir=lambda s: None, pausa=0)


def _situacoes(ctx, motor):
    return {a: (s, e) for a, s, e in ctx.banco.consultar(
        "select alvo, situacao, erro from fontes_federais where motor = ?", motor)}


# --- Economia GO: as planilhas reais (requisitos 145 e 149) ---------------------------------------

def test_conciliacao_real_le_a_aba_agregado_mes_a_mes():
    linhas = economia_go.ler_planilha(_bytes("economia_go_conciliacao_2025_real.xlsx"), "Goiânia", 2025)
    assert len(linhas) == 36                                        # 12 meses x ICMS, IPVA e IPI
    por = {(l["mes"], l["tributo"]): l["valor"] for l in linhas}
    assert por[("2025-01", "ICMS")] == 65_536_440.65
    assert por[("2025-01", "IPVA")] == 92_903_230.14
    assert por[("2025-01", "IPI")] == 371_219.44
    assert {l["mes"] for l in linhas} == {f"2025-{m:02d}" for m in range(1, 13)}
    # Aparecida de Goiânia está na mesma aba e não se mistura.
    aparecida = economia_go.ler_planilha(_bytes("economia_go_conciliacao_2025_real.xlsx"), "Aparecida de Goiânia", 2025)
    assert aparecida and all(l["valor"] != por[(l["mes"], l["tributo"])] for l in aparecida)


def test_demonstrativo_real_de_2024_le_as_abas_por_mes_pela_cota_bruta():
    linhas = economia_go.ler_planilha(_bytes("economia_go_transf_2024_real.xlsx"), "Goiânia", 2024)
    por = {(l["mes"], l["tributo"]): l["valor"] for l in linhas}
    assert len(linhas) == 6 and {l["mes"] for l in linhas} == {"2024-01", "2024-02"}   # março sem valor
    assert por[("2024-01", "ICMS")] == 75_103_392.63
    assert por[("2024-01", "IPVA")] == 72_338_748.9
    assert por[("2024-01", "IPI")] == 412_299.16
    assert por[("2024-02", "ICMS")] == 64_933_323.19
    # "acumulado no ano" não vira mês.
    assert not any(l["mes"] == "2024-13" for l in linhas)


def test_motor_economia_go_com_a_pagina_e_a_conciliacao_reais_baixa_uma_planilha(tmp_path):
    pedidos = []

    def leitor(url, **_):
        pedidos.append(url)
        if url == economia_go.CANDIDATOS[0]:
            return _ok(url, _bytes("economia_go_repasses_mensais_real.html"))
        if url.endswith("2026/05/Conciliacao_das_Distribuicoes-2025.xlsx"):
            return _ok(url, _bytes("economia_go_conciliacao_2025_real.xlsx"))
        return _nao(url)

    ctx = _ctx(tmp_path, leitor)
    mf.motor_economia_go(ctx, "Goiânia", 5208707)
    situacao, erro = _situacoes(ctx, "economia_go")["2025"]
    assert situacao == "lido" and erro is None
    assert ctx.banco.consultar("select count(*) from repasses_estado where mes like '2025-%'") == [(36,)]
    # A conciliação mais nova cobre o ano: as planilhas de janeiro a abril (15 MB cada) não são baixadas.
    assert [u for u in pedidos if u.endswith(".xlsx")] == [
        "https://goias.gov.br/economia/wp-content/uploads/sites/45/2026/05/Conciliacao_das_Distribuicoes-2025.xlsx"]


# --- CEIS e CNEP reais (requisito 153) ------------------------------------------------------------

def test_motor_sancoes_le_o_cnep_real_e_o_ceis_do_dia_publicado(tmp_path):
    def leitor(url, **_):
        if url == sancoes.url_indice("CEIS"):
            return _ok(url, _bytes("sancoes_indice_ceis_real.html"))
        if url == sancoes.url_indice("CNEP"):
            return _ok(url, _bytes("sancoes_indice_cnep_real.html"))
        if url == sancoes.url_cgu("CEIS", date(2026, 11, 27)):
            return _ok(url, _zip("20261127_CEIS.csv", _bytes("ceis_real.csv")))
        if url == sancoes.url_cgu("CNEP", date(2026, 11, 27)):
            return _ok(url, _zip("20261127_CNEP.csv", _bytes("cnep_real.csv")))
        return _nao(url, 403)                     # o CEIS de 28/11 ainda dava 403 na sondagem

    ctx = _ctx(tmp_path, leitor)
    mf.motor_sancoes(ctx)
    s = _situacoes(ctx, "sancoes")
    assert s["CEIS"][0] == "lido" and s["CNEP"][0] == "lido"
    assert ctx.banco.consultar("select cadastro, count(*), min(arquivo) from sancoes group by cadastro order by 1") == [
        ("CEIS", 10, "20261127"), ("CNEP", 7, "20261127")]
    cnep = {r[0]: r for r in ctx.banco.consultar(
        "select cnpj_cpf, tipo, inicio, fim, esfera, uf_orgao, abrangencia, orgao, fundamentacao, multa "
        "from sancoes where cadastro = 'CNEP'")}
    inid = cnep["29118884000165"]
    assert inid[1].startswith("Declaração de Inidoneidade") and inid[2:4] == ("2025-07-24", "2030-07-23")
    alcance = sancoes.alcanca_o_municipio({"orgao": inid[7], "esfera": inid[4], "abrangencia": inid[6],
                                           "tipo": inid[1], "fundamentacao": inid[8]})
    assert alcance == "todos"
    assert cnep["12574593000189"][9] == 813_870.96                     # a multa da Lei Anticorrupção


def test_contrato_com_empresa_inidonea_do_cnep_vira_alerta_grave(tmp_path):
    def leitor(url, **_):
        if url == sancoes.url_indice("CNEP"):
            return _ok(url, _bytes("sancoes_indice_cnep_real.html"))
        if url == sancoes.url_cgu("CNEP", date(2026, 11, 27)):
            return _ok(url, _zip("20261127_CNEP.csv", _bytes("cnep_real.csv")))
        return _nao(url, 403)

    ctx = _ctx(tmp_path, leitor)
    mf.motor_sancoes(ctx)
    # O contrato é fictício; a sanção é a real do CNEP (inidoneidade de 24/07/2025 a 23/07/2030).
    ctx.banco.inserir("contratos_pncp", {"pncp_id": "C-CNEP", "mes": "2025-09", "data_assinatura": "2025-09-01",
                                         "orgao_cnpj": "1", "orgao": "SECRETARIA FICTICIA",
                                         "fornecedor_ni": "29118884000165", "fornecedor": "EMPRESA",
                                         "objeto": "serviço", "valor_global": 50_000.0})
    r = federais.conferir(ctx.banco.con, ate=date(2026, 11, 28))
    alertas = [a for a in r.alertas if a.tipo == "contratada_sancionada"]
    assert len(alertas) == 1 and alertas[0].gravidade == "alta" and "CNEP" in alertas[0].descricao


# --- FNS: o repasse do dia (requisitos 146 e 164) -------------------------------------------------

def test_fns_repasse_dia_real_achatado_e_somado():
    assert fns.data_ultimo_pagamento(_bytes("fns_ultimo_pagamento_real.json")) == "2026-11-26"
    nos = fns.arvore_repasse_dia(_bytes("fns_repasse_dia_consultar_real.json"), "2025-01-15")
    assert len(nos) == 7
    blocos = {n["nome"]: n["valor_total"] for n in nos if n["nivel"] == 0}
    assert blocos == {"Manutenção das Ações e Serviços Públicos de Saúde": 2_285_109.0,
                      "OUTRAS TRANSFERÊNCIAS": 881_486.75}
    folhas = [n for n in nos if n["folha"]]
    assert round(sum(n["valor_total"] for n in folhas), 2) == 3_166_595.75
    judicial = next(n for n in folhas if n["codigo"] == "61861")
    assert judicial["caminho"] == "OUTRAS TRANSFERÊNCIAS > DEMANDAS JUDICIAIS > AÇÃO JUDICIAL (SCTIE)"
    assert judicial["competencia"] == "Única em 2025" and judicial["processos"] == 12


def test_fns_repasse_dia_que_nao_fecha_e_formato():
    torto = (b'{"resultado":[{"codigo":"A","nome":"A","vlTotal":10,"repasses":[{"codigo":"B","nome":"B",'
             b'"vlTotal":7}]}]}')
    try:
        fns.arvore_repasse_dia(torto, "2025-01-15")
    except ValueError as e:
        assert "não fecham" in str(e)
    else:
        raise AssertionError("a soma que não fecha passou")
    assert fns.arvore_repasse_dia(b'{"resultado":[]}', "2025-01-16") == []


def test_fns_servico_real_da_consulta_detalhada_e_o_modelo_do_municipio():
    servicos = fns.servicos_do_js(_bytes("fns_detalhada_service_real.js").decode("utf-8"))
    assert servicos["recuperarEntidades"] == ("GET", "recursos/consulta-detalhada/entidades")
    assert servicos["recuperarPagamentos"] == ("GET", "recursos/consulta-detalhada/detalhe-pagamento")
    assert servicos["gerarPlanilhaDetalhada"] == ("POST", "recursos/consulta-detalhada/planilha-detalhada")
    assert "cGet" not in servicos                     # o recurso vem por parâmetro
    modelo = next(m for m in fns.MODELOS if "consulta-detalhada/entidades" in m)
    url = fns.url(modelo, 5208707, 2025)
    assert url.startswith(fns.CONSULTA + "consulta-detalhada/entidades?page=1&count=100&ano=2025&")
    assert "&estado=GO&municipio=520870&" in url
    # O serviço antigo continua igual (trava da terceira rodada).
    antigo = fns.servicos_do_js(_bytes("fns_repasse_dia_service_real.js").decode("utf-8"))
    assert antigo["consultar"] == ("GET", "recursos/repasse-dia/consultar") and len(antigo) == 9


def _leitor_fns(pedidos, dia_com_pagamento="2026-11-26", falha=None):
    def leitor(url, **_):
        pedidos.append(url)
        if "recuperar-data-ultimo-pagamento" in url:
            return _ok(url, _bytes("fns_ultimo_pagamento_real.json"))
        if "repasse-dia/consultar" in url:
            if falha:
                return _nao(url, falha)
            a, m, d = dia_com_pagamento.split("-")
            if url.endswith(f"ano={a}&mes={int(m)}&dia={int(d)}"):
                return _ok(url, _bytes("fns_repasse_dia_consultar_real.json"))
            return _ok(url, b'{"resultado":[]}')
        return _nao(url)
    return leitor


def test_motor_fns_repasse_dia_le_os_dias_do_periodo_uma_vez(tmp_path):
    pedidos: list[str] = []
    ctx = _ctx(tmp_path, _leitor_fns(pedidos), meses=("2026-11", "2026-11"))
    mf.motor_fns_repasse_dia(ctx)
    dias = [u for u in pedidos if "consultar" in u]
    assert dias[0].endswith("ano=2026&mes=11&dia=26")                 # do último pagamento para trás
    assert len(dias) == 19                                            # os dias úteis de 02 a 26/11
    assert not any(u.endswith(("dia=27", "dia=28")) for u in dias)
    assert ctx.banco.consultar("select count(*), count(distinct data) from repasse_dia_fns") == [(7, 1)]
    assert ctx.banco.consultar("select count(*) from repasse_dia_fns_dias") == [(19,)]
    situacao, _ = _situacoes(ctx, "fns")["repasse_dia"]
    assert situacao == "lido"
    # Segunda rodada: nenhum dia é lido de novo.
    pedidos.clear()
    mf.motor_fns_repasse_dia(ctx)
    assert [u for u in pedidos if "consultar" in u] == []
    assert _situacoes(ctx, "fns")["repasse_dia"][0] == "lido"


def test_motor_fns_repasse_dia_fora_do_ar_para_e_e_falha(tmp_path):
    pedidos: list[str] = []
    ctx = _ctx(tmp_path, _leitor_fns(pedidos, falha=503), meses=("2026-11", "2026-11"))
    mf.motor_fns_repasse_dia(ctx)
    assert len({u for u in pedidos if "consultar" in u}) == 3          # três dias seguidos e para
    situacao, erro = _situacoes(ctx, "fns")["repasse_dia"]
    assert situacao == "falha" and "503" in erro
    assert ctx.banco.consultar("select count(*) from repasse_dia_fns_dias") == [(0,)]


def test_chamada_do_fns_roda_os_repasses_e_o_repasse_do_dia(tmp_path):
    pedidos: list[str] = []
    ctx = _ctx(tmp_path, _leitor_fns(pedidos), meses=("2026-11", "2026-11"))
    mf.chamadas(ctx, ALVO, cnpjs=[])["fns"]()
    s = _situacoes(ctx, "fns")
    assert s["repasse_dia"][0] == "lido" and s["2026"][0] == "nao_publicado"
    assert any("consulta-detalhada/entidades" in u and "municipio=520870" in u for u in pedidos)


# --- TCM-GO: contas irregulares dos dados abertos (requisito 154) ---------------------------------

def test_tcm_contas_irregulares_csv_real_fica_com_goiania_e_o_orgao():
    linhas = tcm.contas(_bytes("tcm_contas_irregulares_real.csv"), "Goiânia")
    assert len(linhas) == 5                       # não entram Aparecida, Goianira nem Aragoiânia
    entidades = [l["entidade"] for l in linhas]
    assert entidades == ["Prefeitura (Município)", "Prefeitura (Município)", "COMURG",
                         "FUNDO PREVIDENCIARIO - FUNPREV", "FMMDE"]
    primeira = linhas[0]
    assert primeira["processo"] == "5317/16 - 1" and primeira["exercicio"] == "3/2016"
    assert primeira["transito"] == "2024-05-15" and primeira["data_julgamento"] == "2024-04-03"
    assert primeira["decisao"] == "AC.(Leg)-1378/2024-IR" and primeira["cpf_parcial"] == "11***.***-***"
    assert primeira["url_processo"].endswith("/consulta-processo/5317/2016")
    assert linhas[-1]["tipo_lista"] == "Contas de Julgadas Irregulares com Débito"
    aparecida = tcm.contas(_bytes("tcm_contas_irregulares_real.csv"), "Aparecida de Goiânia")
    assert [l["responsavel"] for l in aparecida] == ["PEDRO ENSAIO FICTICIO"]   # o CSV escreve sem o "de"


def _leitor_tcm(url, **_):
    if url == tcm.DADOS_ABERTOS:
        return _ok(url, _bytes("tcm_contas_irregulares_real.csv"))
    if url in tcm.PAGINAS_DAS_LISTAS:
        return _ok(url, _bytes("tcm_listas_parecer_real.html"))
    return _nao(url, 403)                         # acesso à informação e painel das câmaras: 403


def test_motor_listas_tcm_le_o_csv_real_com_as_colunas_novas(tmp_path):
    ctx = _ctx(tmp_path, _leitor_tcm)
    mf.motor_listas_tcm(ctx, "Goiânia")
    linhas = ctx.banco.consultar("select lista, entidade, responsavel, cpf_parcial, assunto, decisao, "
                                 "data_julgamento, tipo_lista, url_processo from contas_irregulares_tcm "
                                 "order by processo")
    assert len(linhas) == 5 and {l[0] for l in linhas} == {"dados_abertos"}
    assert all(l[3] and l[4] and l[5] and l[6] and l[7] and l[8] for l in linhas)
    situacao, erro = _situacoes(ctx, "tcm")["listas"]
    assert situacao == "lido" and "ausente" in erro


def test_banco_antigo_das_contas_ganha_as_colunas_sem_perder_linhas(tmp_path):
    import sqlite3
    banco = SimpleNamespace(con=sqlite3.connect(tmp_path / "velho.db"))    # o banco de antes da rodada 4
    banco.con.execute("CREATE TABLE contas_irregulares_tcm (lista TEXT, municipio TEXT, entidade TEXT, "
                      "responsavel TEXT, processo TEXT, exercicio TEXT, transito TEXT, url TEXT, json TEXT)")
    banco.con.execute("INSERT INTO contas_irregulares_tcm (lista, processo) VALUES ('velha', '1/2020')")
    mf.preparar(banco)
    colunas = {c[1] for c in banco.con.execute("PRAGMA table_info(contas_irregulares_tcm)")}
    assert set(mf.COLUNAS_NOVAS["contas_irregulares_tcm"]) <= colunas
    assert banco.con.execute("select lista, processo, tipo_lista from contas_irregulares_tcm").fetchall() == [
        ("velha", "1/2020", None)]


def test_contas_irregulares_viram_alerta_e_o_socio_homonimo_e_indicio(tmp_path):
    ctx = _ctx(tmp_path, _leitor_tcm)
    mf.motor_listas_tcm(ctx, "Goiânia")
    cnpj.preparar(ctx.banco.con)
    ctx.banco.inserir("cnpj_empresas", {"cnpj": "11222333000181", "razao": "CONTRATADA FICTICIA LTDA"})
    ctx.banco.inserir("cnpj_socios", {"cnpj": "11222333000181", "nome": "Carlos Amostra Fictício",
                                      "cpf_cnpj": "***456789**", "qualificacao": "Sócio-Administrador"})
    ctx.banco.inserir("cnpj_socios", {"cnpj": "11222333000181", "nome": "PEDRO ENSAIO FICTICIO",
                                      "cpf_cnpj": "***111222**", "qualificacao": "Sócio"})
    r = federais.conferir(ctx.banco.con, ate=date(2026, 11, 28))
    contas = [a for a in r.alertas if a.tipo == "contas_irregulares_tcm"]
    assert len(contas) == 5
    debito = next(a for a in contas if "FMMDE" in a.descricao)
    assert debito.gravidade == "alta" and debito.mes == "2020-09"
    assert next(a for a in contas if "COMURG" in a.descricao).gravidade == "media"
    socios = [a for a in r.alertas if a.tipo == "socio_com_contas_irregulares"]
    assert len(socios) == 1                       # o sócio de Aparecida não cruza com Goiânia
    s = socios[0]
    assert "CONTRATADA FICTICIA LTDA" in s.descricao and "7304/22 - 1" in s.descricao
    assert "homônimo" in s.descricao and s.dados["possivel_homonimo"]
    f = federais.ficha(s, "2026-11")
    assert f.codigo.startswith("PRC-TCM01-") and "Alerta é indício, não acusação." in f.observacao
    f2 = federais.ficha(debito, "2026-11")
    assert f2.codigo.startswith("PCT-TC02-") and f2.familia.value == "PCT"
    assert r.por_tipo()["contas_irregulares_tcm"] == 5


# --- Transferegov: API fora do ar (requisitos 150 e 48) -------------------------------------------

def test_transferegov_fora_do_ar_tenta_de_novo_no_fim_e_nao_insiste_em_cada_tabela(tmp_path):
    def leitor(url, **_):
        if url == emendas.URL:
            return _ok(url, _bytes("emendas_unico_real.zip"))
        return _nao(url, 503)                       # a API deu 503 na sondagem

    ctx = _ctx(tmp_path, leitor)
    mf.chamadas(ctx, ALVO, cnpjs=["01612092000123", "13063426000104"])["transferegov"]()
    s = _situacoes(ctx, "transferegov")
    assert s["emendas"][0] == "lido"                 # o arquivo do Portal não depende da API
    for modulo in transferegov.MODULOS:
        situacao, erro = s[modulo]
        assert situacao == "falha" and "API fora do ar" in erro and "próxima rodada" in erro
    # Por módulo: a raiz e a primeira consulta, duas vezes (a primeira passada e a nova tentativa).
    chamadas = ctx.banco.consultar("select count(*) from coletas where motor = 'transferegov' "
                                   "and alvo not like 'emendas%'")
    assert chamadas == [(len(transferegov.MODULOS) * 4,)]


def test_transferegov_que_volta_na_nova_tentativa_e_lido(tmp_path):
    estado = {"no_ar": False}

    def leitor(url, **_):
        if url == transferegov.url_raiz("ted"):
            estado["no_ar"] = True                  # a API volta enquanto o último módulo é lido
        if not estado["no_ar"]:
            return _nao(url, 503)
        if url == transferegov.url_raiz("transferenciasespeciais"):
            return _ok(url, _bytes("transferegov_raiz.json"))
        if "plano_acao_especial?" in url:
            return _ok(url, _bytes("transferegov_planos.json"))
        return _ok(url, b"[]")

    ctx = _ctx(tmp_path, leitor)
    mf.motor_transferegov(ctx, ["01612092000123"])
    s = _situacoes(ctx, "transferegov")
    assert s["transferenciasespeciais"][0] == "lido" and s["ted"][0] == "vazio"
    assert ctx.banco.consultar("select count(*) from transferegov_planos_especiais") == [(2,)]


# --- Sondagem da quinta rodada ----------------------------------------------------------------------

def test_sondagem_da_quarta_rodada_pede_so_o_que_depende_de_rede():
    from onisciente import sondagem
    c = {k: [u if isinstance(u, str) else u[0] for u in v] for k, v in sondagem.CANDIDATOS.items()
         if k.startswith("d1_")}
    assert any("consulta-detalhada/entidades" in u and "municipio=520870" in u for u in c["d1_fns"])
    assert any("detalhar-pagamento-dia" in u for u in c["d1_fns"])
    assert any("20261129_CEIS.zip" in u for u in c["d1_sancoes"])
    assert any("inicio=100" in u for u in c["d1_tcu"]) and any("inicio=50" in u for u in c["d1_tcu"])
    assert transferegov.url_raiz("transferenciasespeciais") in c["d1_transferegov"]
    # O que já é lido sai da sondagem.
    assert not any("repasse-dia/recuperar-data-ultimo-pagamento" in u for u in c["d1_fns"])
    assert not any("transf-municipios_2024" in u for u in c["d1_economia_go"])
