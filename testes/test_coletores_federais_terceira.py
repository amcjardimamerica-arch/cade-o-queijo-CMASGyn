"""Bloco 5 (Frente D1), terceira rodada: os coletores diante das páginas reais da sondagem de 28/11/2026
(run 46085340244).

Respostas reais, reduzidas, em ``testes/dados/federais/``:
- ``fnde_liberacoes_*_real.html``: as liberações de 2025 da Prefeitura e de um conselho escolar de
  Goiânia, inteiras (só estilos e scripts retirados);
- ``ceis_real.csv`` e ``sancoes_indice_ceis_real.html``: o cabeçalho real do CEIS de 27/11/2026 com dez
  linhas reais de pessoa jurídica, e o trecho da página de download que diz a data publicada;
- ``emendas_unico_real.zip``: as seis planilhas do arquivo único de emendas do Portal, cada uma com o
  cabeçalho real e linhas reais (de Goiânia e de fora); na linha de pessoa física, nome e CPF
  mascarado foram trocados;
- ``economia_go_repasses_mensais_real.html``: a tabela das planilhas mensais da Economia, só 2026,
  2025 e 2020;
- ``tcu_dados_abertos_real.json``: os cinco acórdãos dos dados abertos do TCU;
- ``tcm_listas_*_real.html``: o corpo das duas páginas das listas do TCM-GO;
- ``fns_repasse_dia_service_real.js`` e ``fns_municipios_go_real.json``: o serviço do repasse dia e
  cinco municípios da lista real de Goiás.

Onde a fonte ainda não mostrou o dado (a planilha da Economia, a lista de contas do TCM, o CNEP), a
resposta do teste é fictícia e o teste diz isso.
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
    economia_go,
    emendas,
    fnde,
    fns,
    sancoes,
    tcm,
    tcu,
)
from onisciente.coletores import comum_federal as cf
from onisciente.coletores import motores_federais as mf

DADOS = Path(__file__).parent / "dados" / "federais"
ALVO = SimpleNamespace(ibge=5208707, uf="GO", municipio="Goiânia", pncp_cnpjs=())


def _bytes(nome: str) -> bytes:
    return (DADOS / nome).read_bytes()


def _ok(url, conteudo: bytes) -> base.Leitura:
    return base.Leitura(True, url, conteudo, http=200)


def _nao(url, codigo=404) -> base.Leitura:
    return base.Leitura(False, url, erro=f"HTTP {codigo}", http=codigo)


def _ctx(tmp_path, leitor, meses=("2025-01", "2025-12"), hoje=date(2026, 11, 28)):
    banco = historico.Banco(tmp_path / "h.db")
    mf.preparar(banco)
    return historico.Contexto(banco, historico.meses(*meses), hoje, ler_url=leitor,
                              dormir=lambda s: None, pausa=0)


def _situacoes(ctx, motor):
    return {a: (s, e) for a, s, e in ctx.banco.consultar(
        "select alvo, situacao, erro from fontes_federais where motor = ?", motor)}


# --- FNDE: as liberações reais -------------------------------------------------------------------

def test_fnde_liberacoes_reais_fecham_com_o_total_da_pagina():
    pagina = cf.decodificar(_bytes("fnde_liberacoes_prefeitura_real.html"))
    libs, total = fnde.liberacoes(pagina)
    assert len(libs) == 68
    assert round(sum(l["valor"] for l in libs), 2) == round(total, 2) == 77_224_595.71
    primeira = libs[0]
    assert primeira["data"] == "2025-02-06" and primeira["ordem_bancaria"] == "001163"
    assert primeira["banco"] == "BANCO DO BRASIL" and primeira["agencia"] == "0086"
    assert primeira["programa"].startswith("PNAE") and "ALIMENTAÇÃO ESCOLAR" in primeira["programa"]
    assert all(l["data"].startswith("2025-") for l in libs)
    conselho, total_c = fnde.liberacoes(cf.decodificar(_bytes("fnde_liberacoes_conselho_real.html")))
    assert len(conselho) == 4 and round(total_c, 2) == 36_448.00


def test_fnde_tabela_que_nao_fecha_com_o_total_e_formato():
    pagina = cf.decodificar(_bytes("fnde_liberacoes_conselho_real.html")).replace("4.045,00", "4.046,00", 1)
    try:
        fnde.liberacoes(pagina)
    except ValueError as e:
        assert "não fecha" in str(e)
    else:
        raise AssertionError("a soma diferente do total devia ser recusada")


def test_motor_fnde_com_a_lista_e_as_liberacoes_reais(tmp_path):
    def leitor(url, formulario=None, **_):
        if url == fnde.ENTIDADES and formulario:
            return _ok(url, _bytes("fnde_entidades_real.html"))
        if "p_cgc=01612092000123" in url:
            return _ok(url, _bytes("fnde_liberacoes_prefeitura_real.html"))
        if "p_cgc=02439034000102" in url:
            return _ok(url, _bytes("fnde_liberacoes_conselho_real.html"))
        return _ok(url, b"<html><body>NENHUMA LIBERACAO ENCONTRADA</body></html>")   # fictício

    ctx = _ctx(tmp_path, leitor)
    mf.motor_fnde(ctx, "GO", "520870")
    assert ctx.banco.consultar("select round(sum(valor), 2) from liberacoes_fnde") == [(77_261_043.71,)]
    assert ctx.banco.consultar("select count(*) from liberacoes_fnde where cnpj = '01612092000123'") == [(68,)]
    assert ctx.banco.consultar("select count(*) from liberacoes_fnde where banco is null or agencia is null "
                               "or conta is null or data is null") == [(0,)]
    assert _situacoes(ctx, "fnde")["2025"][0] == "lido"


# --- Sanções: o CEIS real de 27/11 ---------------------------------------------------------------

def _zip(nome_no_zip: str, conteudo: bytes) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(nome_no_zip, conteudo)
    return b.getvalue()


def test_sancoes_ceis_real_pela_data_da_pagina_e_403_no_dia_anterior(tmp_path):
    pedidos = []

    def leitor(url, **_):
        pedidos.append(url)
        if url == sancoes.url_indice("CEIS"):
            return _ok(url, _bytes("sancoes_indice_ceis_real.html"))
        if url == sancoes.url_cgu("CEIS", date(2026, 11, 27)):
            return _ok(url, _zip("20261127_CEIS.csv", _bytes("ceis_real.csv")))
        return _nao(url, 403)                 # o dia anterior e o CNEP: 403, como na sondagem

    ctx = _ctx(tmp_path, leitor)
    mf.motor_sancoes(ctx)
    s = _situacoes(ctx, "sancoes")
    assert s["CEIS"][0] == "lido" and s["CNEP"][0] == "nao_publicado" and "403" in s["CNEP"][1]
    assert sancoes.url_cgu("CEIS", date(2026, 11, 26)) not in pedidos      # a data da página veio primeiro
    linhas = ctx.banco.consultar("select cnpj_cpf, orgao, esfera, abrangencia, tipo, fundamentacao, inicio, fim "
                                 "from sancoes where cadastro = 'CEIS'")
    assert len(linhas) == 10 and all(l[3] for l in linhas)             # a abrangência ("ABRAGÊNCIA") lida
    alcance = {}
    for cnpj, orgao, esfera, abr, tipo, fund, *_ in linhas:
        alcance.setdefault(sancoes.alcanca_o_municipio(
            {"orgao": orgao, "esfera": esfera, "abrangencia": abr, "tipo": tipo, "fundamentacao": fund}), set()).add(cnpj)
    assert alcance["municipio"] == {"26395502000152", "34565467000109", "10708841000101", "36395041000171"}
    assert "05925429000103" in alcance["todos"]                       # inidoneidade
    assert "16970999000131" in alcance["outro_ente"]                  # suspensão de outro ente


def test_sancoes_sem_a_pagina_recua_de_hoje_dia_a_dia(tmp_path):
    pedidos = []

    def leitor(url, **_):
        pedidos.append(url)
        if url == sancoes.url_cgu("CEIS", date(2026, 11, 27)):
            return _ok(url, _zip("20261127_CEIS.csv", _bytes("ceis_real.csv")))
        return _nao(url, 403)

    ctx = _ctx(tmp_path, leitor)
    mf.motor_sancoes(ctx)
    assert _situacoes(ctx, "sancoes")["CEIS"][0] == "lido"
    ceis = [u for u in pedidos if "/ceis/2026" in u.lower() or "_CEIS" in u]
    assert any("20261128" in u for u in ceis)                         # hoje foi tentado antes
    assert ctx.banco.consultar("select distinct arquivo from sancoes") == [("20261127",)]


# --- Emendas: o arquivo único do Portal, em fluxo ------------------------------------------------

class _AosPedacos:
    """Um fluxo que entrega poucos bytes por vez, como a rede."""

    def __init__(self, dados: bytes, passo: int = 997):
        self.dados, self.pos, self.passo, self.maior = dados, 0, passo, 0
        self.status = 200

    def read(self, n: int = -1) -> bytes:
        n = self.passo if n < 0 else min(n, self.passo)
        parte = self.dados[self.pos:self.pos + n]
        self.pos += len(parte)
        self.maior = max(self.maior, len(parte))
        return parte

    def close(self):
        pass


def _filtro():
    return emendas.Filtro("Goiânia", "GO", 5208707, ["01612092000123"])


def test_emendas_reais_filtradas_por_goiania_em_fluxo():
    fluxo = _AosPedacos(_bytes("emendas_unico_real.zip"))
    achadas = list(emendas.filtrar(fluxo, _filtro()))
    por = {}
    for planilha, linha in achadas:
        por.setdefault(planilha, []).append(linha)
    assert {k: len(v) for k, v in por.items()} == {
        "emendas": 4, "convenios": 4, "parcerias": 4, "plano_parcerias": 4, "plano_especiais": 4, "favorecidos": 4}
    # Lido aos pedaços, uma vez só, até o diretório central (que não é preciso).
    assert fluxo.pos >= fluxo.dados.index(b"PK\x01\x02") and fluxo.maior <= 997
    # Pessoa física fica de fora; Aragoiânia não é Goiânia.
    assert not any("PESSOA FISICA" in (l["nome"] or "") or "***" in (l["cnpj"] or "")
                   for l in por["favorecidos"])
    assert all(l["cnpj"] == "01612092000123" for l in por["plano_especiais"])
    assert all("GOIÂNIA" in l["nome"] for l in por["emendas"])
    assert all(isinstance(l["valor"], float) for _, l in achadas)


def test_emendas_com_descritor_de_dados_e_membro_desconhecido():
    original = zipfile.ZipFile(io.BytesIO(_bytes("emendas_unico_real.zip")))

    class SemVolta(io.RawIOBase):            # zip escrito num fluxo sem volta: tamanhos no descritor
        def __init__(self):
            self.b = bytearray()

        def writable(self):
            return True

        def write(self, d):
            self.b.extend(d)
            return len(d)

    saida = SemVolta()
    with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("LEIAME.txt", b"membro novo, descartado")
        for nome in original.namelist():
            with z.open(nome, "w") as m:
                m.write(original.read(nome))
    dados = bytes(saida.b)
    assert zipfile.ZipFile(io.BytesIO(dados)).infolist()[1].flag_bits & 0x08
    achadas = list(emendas.filtrar(_AosPedacos(dados, 513), _filtro()))
    assert len(achadas) == 24


def test_emendas_sem_planilha_conhecida_e_formato():
    try:
        list(emendas.filtrar(io.BytesIO(_zip("outra.csv", b'"a";"b"\r\n"1";"2"\r\n')), _filtro()))
    except emendas.Formato:
        pass
    else:
        raise AssertionError("zip sem as planilhas de emendas devia ser formato")
    try:
        list(emendas.filtrar(io.BytesIO(b"<html>erro</html>"), _filtro()))
    except emendas.Formato:
        pass
    else:
        raise AssertionError("página no lugar do zip devia ser formato")


def test_motor_transferegov_le_as_emendas_e_troca_a_tabela(tmp_path):
    def leitor(url, **_):
        if url == emendas.URL:
            return _ok(url, _bytes("emendas_unico_real.zip"))
        return _nao(url, 503)

    ctx = _ctx(tmp_path, leitor)
    ctx.banco.inserir("emendas_municipio", {"planilha": "velha", "valor": 1.0})
    mf.chamadas(ctx, ALVO, cnpjs=["01612092000123"])["transferegov"]()
    assert ctx.banco.consultar("select count(*), count(distinct planilha) from emendas_municipio") == [(24, 6)]
    situacao, erro = _situacoes(ctx, "transferegov")["emendas"]
    assert situacao == "lido" and "favorecidos: 4" in erro


def test_motor_emendas_pela_rede_le_em_fluxo_e_registra_a_coleta(tmp_path, monkeypatch):
    dados = _bytes("emendas_unico_real.zip")
    abertos = []

    def abrir(url, tempo=300):
        abertos.append(url)
        return _AosPedacos(dados, 4096)

    monkeypatch.setattr(emendas, "abrir", abrir)
    ctx = _ctx(tmp_path, base.ler)                 # o leitor de verdade: o motor usa o fluxo
    mf.motor_transferegov(ctx, [], municipio="Goiânia", uf="GO", ibge=520870)
    assert abertos == [emendas.URL]
    assert ctx.banco.consultar("select count(*) from emendas_municipio") == [(24,)]
    assert ctx.banco.consultar("select ok, bytes from coletas where alvo like 'emendas%'") == [(1, len(dados))]


def test_motor_emendas_cortado_no_meio_mantem_a_tabela_anterior(tmp_path, monkeypatch):
    dados = _bytes("emendas_unico_real.zip")
    monkeypatch.setattr(emendas, "abrir", lambda url, tempo=300: _AosPedacos(dados[:len(dados) // 2]))
    ctx = _ctx(tmp_path, base.ler)
    ctx.banco.inserir("emendas_municipio", {"planilha": "anterior", "valor": 1.0})
    mf.motor_emendas(ctx, "Goiânia", "GO", "5208707")
    assert ctx.banco.consultar("select planilha from emendas_municipio") == [("anterior",)]
    assert _situacoes(ctx, "transferegov")["emendas"][0] == "formato"


# --- Economia GO: as planilhas mensais -----------------------------------------------------------

def _planilha(linhas) -> bytes:
    import openpyxl
    livro = openpyxl.Workbook()
    for l in linhas:
        livro.active.append(l)
    b = io.BytesIO()
    livro.save(b)
    return b.getvalue()


def test_economia_go_le_os_meses_da_tabela_real():
    pagina = (DADOS / "economia_go_repasses_mensais_real.html").read_text(encoding="utf-8")
    arqs = economia_go.arquivos_mensais(pagina, economia_go.CANDIDATOS[0])
    meses_2025 = [a["mes"] for a in arqs if a["mes"].startswith("2025")]
    assert meses_2025 == [f"2025-{m:02d}" for m in range(1, 13)]
    assert {a["url"] for a in arqs if a["mes"] >= "2025-05" and a["mes"] < "2026"} == {
        "https://goias.gov.br/economia/wp-content/uploads/sites/45/2026/05/Conciliacao_das_Distribuicoes-2025.xlsx"}
    assert all(a["url"].endswith(".xls") for a in arqs if a["mes"].startswith("2020"))
    assert economia_go.links_de_repasse(pagina, economia_go.CANDIDATOS[0]) == [economia_go.CANDIDATOS[0]]


def test_motor_economia_go_pelas_planilhas_mensais(tmp_path):
    # A página é real; a planilha é fictícia (o formato das colunas ainda não foi lido).
    cumulada = _planilha([["Repasse aos Municípios - 2025"], [],
                          ["Município", "Mês", "ICMS", "IPVA"],
                          ["GOIÂNIA", "2025-05", "1.000,00", "500,00"],
                          ["APARECIDA DE GOIÂNIA", "2025-05", "9,00", "9,00"],
                          ["GOIÂNIA", "2025-06", "1.100,00", "550,00"]])
    mensal = _planilha([["Município", "ICMS", "IPVA"], ["GOIÂNIA", 900.0, 450.0]])

    def leitor(url, **_):
        if url == economia_go.CANDIDATOS[0]:
            return _ok(url, _bytes("economia_go_repasses_mensais_real.html"))
        if url.endswith("Conciliacao_das_Distribuicoes-2025.xlsx"):
            return _ok(url, cumulada)
        if url.endswith("2025/02/Conciliacao-das-Distribuicoes-2025.xlsx"):
            return _ok(url, mensal)
        return _nao(url)

    ctx = _ctx(tmp_path, leitor)
    mf.motor_economia_go(ctx, "Goiânia", 5208707)
    linhas = ctx.banco.consultar("select mes, tributo, valor from repasses_estado order by mes, tributo")
    assert linhas == [("2025-01", "ICMS", 900.0), ("2025-01", "IPVA", 450.0),
                      ("2025-05", "ICMS", 1000.0), ("2025-05", "IPVA", 500.0),
                      ("2025-06", "ICMS", 1100.0), ("2025-06", "IPVA", 550.0)]
    assert _situacoes(ctx, "economia_go")["2025"][0] == "lido"


def test_motor_economia_go_planilha_sem_o_municipio_e_formato_nao_ausencia(tmp_path):
    outra = _planilha([["Coluna A", "Coluna B"], ["x", "y"]])      # fictícia

    def leitor(url, **_):
        if url == economia_go.CANDIDATOS[0]:
            return _ok(url, _bytes("economia_go_repasses_mensais_real.html"))
        if url.endswith(".xlsx"):
            return _ok(url, outra)
        return _nao(url)

    ctx = _ctx(tmp_path, leitor)
    mf.motor_economia_go(ctx, "Goiânia", 5208707)
    situacao, erro = _situacoes(ctx, "economia_go")["2025"]
    assert situacao == "formato" and "formato a confirmar" in erro


# --- TCU: os dados abertos reais -----------------------------------------------------------------

def test_tcu_dados_abertos_reais_sem_goiania_ficam_vazios(tmp_path):
    decisoes = tcu.ler(_bytes("tcu_dados_abertos_real.json"))
    assert len(decisoes) == 5 and decisoes[0]["numero"] == "3239" and decisoes[0]["data"] == "2026-11-25"
    assert not any(d["sobre_goiania"] for d in decisoes)

    def leitor(url, **_):
        if url.startswith(tcu.DADOS_ABERTOS):
            return _ok(url, _bytes("tcu_dados_abertos_real.json"))
        return _ok(url, _bytes("tcu_pesquisa_real.json"))

    ctx = _ctx(tmp_path, leitor)
    mf.motor_tcu(ctx, "Goiânia", paginas=1)
    s = _situacoes(ctx, "tcu")
    assert s["dados_abertos"][0] == "vazio" and s["pesquisa"][0] == "lido"


# --- TCM-GO: as páginas das listas ---------------------------------------------------------------

def test_tcm_paginas_reais_das_listas_apontam_os_enderecos():
    parecer = (DADOS / "tcm_listas_parecer_real.html").read_text(encoding="utf-8")
    links = tcm.links_das_listas(parecer)
    assert tcm.DADOS_ABERTOS in links
    assert set(links) <= set(tcm.LISTAS.values())
    assert not any(u.endswith(".pdf") for u in links)                 # o menu fica de fora
    camaras = (DADOS / "tcm_listas_camaras_real.html").read_text(encoding="utf-8")
    assert tcm.links_das_listas(camaras) == [tcm.LISTAS["painel_camaras"]]


def test_motor_listas_tcm_fica_com_goiania_e_diz_o_que_faltou(tmp_path):
    # As páginas são reais; a resposta dos dados abertos é fictícia (ainda não lida).
    dados = (b'[{"municipio":"GOIANIA","orgao":"FUNDO MUNICIPAL DE SAUDE","responsavel":"GESTOR FICTICIO",'
             b'"processo":"12345/2020","exercicio":"2019","dataTransitoJulgado":"2021-03-01"},'
             b'{"municipio":"APARECIDA DE GOIANIA","orgao":"PREFEITURA","responsavel":"OUTRO"}]')

    def leitor(url, **_):
        if url == tcm.PAGINAS_DAS_LISTAS[0]:
            return _ok(url, _bytes("tcm_listas_parecer_real.html"))
        if url == tcm.PAGINAS_DAS_LISTAS[1]:
            return _ok(url, _bytes("tcm_listas_camaras_real.html"))
        if url == tcm.DADOS_ABERTOS:
            return _ok(url, dados)
        return _nao(url, 403)                       # o acesso à informação deu 403 na sondagem

    ctx = _ctx(tmp_path, leitor)
    mf.chamadas(ctx, ALVO, cnpjs=[])["tcm"]()
    assert ctx.banco.consultar("select lista, municipio, entidade, processo, transito from contas_irregulares_tcm") == [
        ("dados_abertos", "GOIANIA", "FUNDO MUNICIPAL DE SAUDE", "12345/2020", "2021-03-01")]
    situacao, erro = _situacoes(ctx, "tcm")["listas"]
    assert situacao == "lido" and "ausente" in erro and "tipo_id" not in erro


def test_motor_listas_tcm_tudo_recusado_nao_inventa_lista(tmp_path):
    ctx = _ctx(tmp_path, lambda url, **_: base.Leitura(False, url, erro="URLError: recusada"))
    mf.motor_listas_tcm(ctx, "Goiânia")
    assert _situacoes(ctx, "tcm")["listas"][0] == "falha"
    assert ctx.banco.consultar("select count(*) from contas_irregulares_tcm") == [(0,)]


# --- FNS: o serviço real do repasse dia ---------------------------------------------------------

def test_fns_servico_real_do_repasse_dia_e_municipios_de_goias():
    servicos = fns.servicos_do_js(_bytes("fns_repasse_dia_service_real.js").decode("utf-8"))
    assert servicos["ultimoPagamentoDia"] == ("GET", "recursos/repasse-dia/recuperar-data-ultimo-pagamento")
    assert servicos["consultar"] == ("GET", "recursos/repasse-dia/consultar")
    assert servicos["buscarDetalhePagamentoEmenda"] == ("GET", "recursos/repasse-dia/detalhar-pagamento-emenda")
    assert servicos["gerarPlanilhaDetalhadaFinal"] == ("POST", "recursos/repasse-dia/planilha-detalhada-final")
    assert len(servicos) == 9                       # o método comentado (cGet) não conta
    assert fns.url_repasse_dia("consultar", ano=2025, mes=1, dia=15) == (
        "https://consultafns.saude.gov.br/recursos/repasse-dia/consultar?ano=2025&mes=1&dia=15")
    municipios = fns.municipios(_bytes("fns_municipios_go_real.json"))
    assert municipios["520870"] == "GOIANIA" and len(municipios) == 5


# --- A próxima sondagem --------------------------------------------------------------------------

def test_sondagem_da_terceira_rodada():
    from onisciente import sondagem
    c = {k: [u if isinstance(u, str) else u[0] for u in v] for k, v in sondagem.CANDIDATOS.items()
         if k.startswith("d1_")}
    assert "https://dadosabertos-download.cgu.gov.br/PortalDaTransparencia/saida/cnep/20261127_CNEP.zip" in c["d1_sancoes"]
    assert any("detalhada" in u for u in c["d1_fns"]) and any("consolidada" in u for u in c["d1_fns"])
    assert any(u.endswith("Conciliacao_das_Distribuicoes-2025.xlsx") for u in c["d1_economia_go"])
    assert tcm.DADOS_ABERTOS in c["d1_tcm"]
    assert emendas.URL not in c["d1_transferegov"]                  # já é lido pelo motor
