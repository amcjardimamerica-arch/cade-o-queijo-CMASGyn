"""Bloco 5 (Frente D1), segunda rodada: os coletores diante das respostas reais da sondagem de 27/11/2026.

As respostas reais ficam em ``testes/dados/federais/*_real.*``, reduzidas ao trecho que importa (sem o
cabeçalho da sondagem). Na lista do FNDE, os nomes de pessoas físicas foram trocados por nomes
fictícios e a lista foi cortada a seis entidades; no bloqueio do Estado, o código do bloqueio foi
zerado. O resto é como veio. Onde a fonte ainda não respondeu com dado (FNS, liberações por
entidade, sanções), as respostas dos testes são fictícias e o teste diz isso.
"""

from __future__ import annotations

import io
import zipfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from onisciente import historico
from onisciente.coletores import base, economia_go, fnde, fns, motores_federais as mf, sancoes, tcm, tcu
from onisciente.conferencias import federais

DADOS = Path(__file__).parent / "dados" / "federais"
ALVO = SimpleNamespace(ibge=5208707, uf="GO", municipio="Goiânia", pncp_cnpjs=())


def _bytes(nome: str) -> bytes:
    return (DADOS / nome).read_bytes()


def _ok(url, conteudo: bytes) -> base.Leitura:
    return base.Leitura(True, url, conteudo, http=200)


def _nao(url, codigo=404) -> base.Leitura:
    return base.Leitura(False, url, erro=f"HTTP {codigo}", http=codigo)


def _rede(url) -> base.Leitura:
    return base.Leitura(False, url, erro="URLError: [Errno 104] Connection reset by peer")


def _ctx(tmp_path, leitor, meses=("2025-01", "2025-12"), hoje=date(2026, 11, 27)):
    banco = historico.Banco(tmp_path / "h.db")
    mf.preparar(banco)
    return historico.Contexto(banco, historico.meses(*meses), hoje, ler_url=leitor,
                              dormir=lambda s: None, pausa=0)


def _situacao(ctx, motor):
    return ctx.banco.consultar("select alvo, situacao, erro from fontes_federais where motor = ? order by alvo",
                               motor)


# --- FNDE: a lista real de entidades de Goiânia em 2025 -------------------------------------------

def test_fnde_lista_real_de_goiania_e_o_formulario_oculto_por_cnpj():
    pagina = (DADOS / "fnde_entidades_real.html").read_text(encoding="utf-8")
    ents = fnde.entidades(pagina)
    assert len(ents) == 6                                   # as pessoas físicas (sem CNPJ) ficam de fora
    nomes = {e["cnpj"]: e["nome"] for e in ents}
    assert nomes["01612092000123"] == "PREF MUN DE GOIANIA"
    assert nomes["02439034000102"] == "CONSELHO ESCOLAR GIRASSOL"
    assert not any("PESSOA" in n for n in nomes.values()) and all(nomes.values())
    pref = next(e for e in ents if e["cnpj"] == "01612092000123")
    assert pref["url"] == ("https://www.fnde.gov.br/pls/simad/internet_fnde.liberacoes_result_pc?p_ano=2025"
                           "&p_programa=&p_uf=GO&p_municipio=520870&p_tp_entidade=&p_cgc=01612092000123")
    assert "liberacoes_01_result_pc" not in fnde.url_liberacoes(2025, "01612092000123", "GO", "520870")


def test_motor_fnde_com_a_lista_real_pede_cada_cnpj_pelo_formulario_oculto(tmp_path):
    pedidos = []

    def leitor(url, formulario=None, **_):
        pedidos.append(url)
        if url == fnde.ENTIDADES and formulario:
            return _ok(url, _bytes("fnde_entidades_real.html"))
        if "p_cgc=01612092000123" in url:                   # liberações: resposta fictícia (ainda não lida)
            return _ok(url, _bytes("fnde_liberacoes_prefeitura.html"))
        return _ok(url, b"<html><body>NENHUMA LIBERACAO ENCONTRADA</body></html>")

    ctx = _ctx(tmp_path, leitor, meses=("2025-01", "2025-12"))
    mf.motor_fnde(ctx, "GO", "520870")
    por_cnpj = [u for u in pedidos if "p_cgc=" in u]
    assert len(por_cnpj) == 6 and all(u.startswith(fnde.LIBERACOES + "?p_ano=2025&") for u in por_cnpj)
    assert ctx.banco.consultar("select count(*) from fnde_entidades where ano = 2025") == [(6,)]
    assert ctx.banco.consultar("select sum(valor) from liberacoes_fnde") == [(1_353_368.0,)]
    assert _situacao(ctx, "fnde")[0][1] == "lido"


# --- TCU: a resposta real da pesquisa ------------------------------------------------------------

def test_tcu_pesquisa_real_separa_goiania_de_aparecida_de_goiania():
    acordaos = tcu.ler(_bytes("tcu_pesquisa_real.json"), pesquisa=True)
    assert [(a["numero"], a["sobre_goiania"]) for a in acordaos] == [
        ("3212", 1), ("5550", 0), ("5931", 0), ("3019", 1), ("2999", 1)]
    contorno = next(a for a in acordaos if a["numero"] == "3019")
    assert contorno["processo"] == "TC 016.497/2026-0" and contorno["data"] == "2026-11-04"
    assert contorno["colegiado"] == "Plenário" and contorno["relator"] == "JHONATAN DE JESUS"
    assert contorno["url"].startswith("https://contas.tcu.gov.br/sagas/SvlVisualizarRelVotoAc?")   # o PDF
    relacao = next(a for a in acordaos if a["numero"] == "5550")
    assert "Trechos:" in relacao["sumario"] and "<em>" not in relacao["sumario"]


def test_motor_tcu_com_a_pesquisa_real_e_os_dados_abertos_fora_do_ar(tmp_path):
    def leitor(url, **_):
        if url.startswith(tcu.PESQUISA):
            return _ok(url, _bytes("tcu_pesquisa_real.json"))
        return _rede(url)                                   # dados abertos: conexão recusada, como na sondagem

    ctx = _ctx(tmp_path, leitor, meses=("2026-01", "2026-11"))
    mf.motor_tcu(ctx, "Goiânia")
    assert dict((a, s) for a, s, _ in _situacao(ctx, "tcu")) == {"dados_abertos": "falha", "pesquisa": "lido"}
    sobre = dict(ctx.banco.consultar("select numero, sobre_goiania from decisoes_controle"))
    assert sobre == {"3212": 1, "5550": 0, "5931": 0, "3019": 1, "2999": 1}
    r = federais.conferir(ctx.banco.con, ate=date(2026, 11, 30))
    alertas = {a.chave: a for a in r.alertas if a.tipo == "decisao_controle"}
    assert "TCU-ACORDAO-COMPLETO-2783093" in alertas                 # o contorno de Goiânia: determinação e cautelar
    assert alertas["TCU-ACORDAO-COMPLETO-2783093"].dados["familia"] == "PRC"
    assert not {"TCU-ACORDAO-COMPLETO-2785250", "TCU-ACORDAO-COMPLETO-2784459"} & set(alertas)   # Aparecida
    assert "tcu" in r.cobertura["problemas"]                         # a via dos dados abertos falhou


# --- TCM-GO: as páginas reais não pesquisam -------------------------------------------------------

def test_tcm_paginas_reais_sem_decisao_nao_viram_busca_vazia(tmp_path):
    for nome in ("tcm_jurisprudencia_real.html", "tcm_busca_real.html", "tcm_rest_real.html"):
        assert tcm.ler(_bytes(nome)) == [], nome

    def leitor(url, **_):
        if "wp-json" in url:
            return _nao(url)
        if "parecer-previo" in url:
            return _ok(url, _bytes("tcm_jurisprudencia_real.html"))
        return _ok(url, _bytes("tcm_busca_real.html"))

    ctx = _ctx(tmp_path, leitor)
    mf.motor_tcm(ctx, "Goiânia")
    [(_, situacao, erro)] = _situacao(ctx, "tcm")
    assert situacao == "nao_publicado" and "sem nenhuma decisão" in erro
    assert not any(c.startswith(d.split("?")[0]) for c in tcm.CANDIDATOS for d in tcm.DESCARTADOS)
    r = federais.conferir(ctx.banco.con, ate=date(2025, 12, 31))
    assert "tcm" in r.cobertura["problemas"]


# --- Economia GO: o portal real, o menu e o bloqueio ----------------------------------------------

def test_economia_go_acha_a_pagina_de_repasses_no_menu_real_e_reconhece_o_bloqueio():
    inicio = (DADOS / "economia_go_inicio_real.html").read_text(encoding="utf-8")
    assert "https://goias.gov.br/economia/repasse-aos-municipios/" in economia_go.links_de_repasse(
        inicio, "https://goias.gov.br/economia/")
    assert economia_go.bloqueado(_bytes("economia_go_bloqueio_real.html"))
    assert not economia_go.bloqueado(_bytes("economia_go_inicio_real.html"))
    assert economia_go.CANDIDATOS[0] == "https://goias.gov.br/economia/repasse-aos-municipios/"


def test_economia_go_bloqueio_nao_e_ausencia_e_pdf_nao_lido_e_falha_do_sistema(tmp_path):
    def todos_bloqueados(url, **_):
        return _ok(url, _bytes("economia_go_bloqueio_real.html"))

    ctx = _ctx(tmp_path, todos_bloqueados, meses=("2025-01", "2025-02"))
    mf.motor_economia_go(ctx, "Goiânia", 5208707)
    [(_, situacao, erro)] = _situacao(ctx, "economia_go")
    assert situacao == "falha" and "firewall" in erro
    assert not federais.conferir(ctx.banco.con, ate=date(2025, 3, 31)).ausencias   # sem ofício por bloqueio

    # A página de repasses (fictícia: ainda não lida) só tem o PDF do ano; o menu real leva até ela.
    pagina = (b'<!DOCTYPE html><html><body><a href="/economia/wp-content/uploads/2026/01/'
              b'repasse-icms-ipva-municipios-2025.pdf">Repasses de ICMS e IPVA aos munic\xc3\xadpios 2025</a>'
              b'</body></html>')

    def leitor(url, **_):
        if url == "https://goias.gov.br/economia/":
            return _ok(url, _bytes("economia_go_inicio_real.html"))
        if url == "https://goias.gov.br/economia/repasse-aos-municipios/":
            return _ok(url, pagina)
        if "dadosabertos" in url:
            return _ok(url, _bytes("economia_go_bloqueio_real.html"))
        return _nao(url)

    (tmp_path / "b").mkdir()
    ctx = _ctx(tmp_path / "b", leitor, meses=("2025-01", "2025-02"))
    mf.motor_economia_go(ctx, "Goiânia", 5208707)
    [(_, situacao, erro)] = _situacao(ctx, "economia_go")
    assert situacao == "formato" and "repasse-icms-ipva-municipios-2025.pdf" in erro
    r = federais.conferir(ctx.banco.con, ate=date(2025, 3, 31))
    assert not r.ausencias and "economia_go" in r.cobertura["problemas"]


# --- Sanções: a página de download e o repositório da CGU -----------------------------------------

def _zip(nome: str) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr(nome, _bytes(nome))
    return b.getvalue()


def test_sancoes_pela_data_da_pagina_de_download_e_pelo_repositorio_da_cgu(tmp_path):
    # Fictício: a página de download e o zip ainda não foram lidos; o 403 do portal é o da sondagem.
    def leitor(url, **_):
        if url == sancoes.url_indice("CEIS"):
            return _ok(url, b'<html><script>arquivos.push({"ano":"2026","mes":"11","dia":"24","origem":"CEIS"});'
                            b'</script></html>')
        if url == sancoes.url_cgu("CEIS", date(2026, 11, 24)):
            return _ok(url, _zip("ceis.csv"))
        if url == sancoes.url_cgu("CNEP", date(2026, 11, 27)):
            return _ok(url, _zip("cnep.csv"))
        return _nao(url, 403)

    ctx = _ctx(tmp_path, leitor)
    mf.motor_sancoes(ctx)
    assert {a: s for a, s, _ in _situacao(ctx, "sancoes")} == {"CEIS": "lido", "CNEP": "lido"}
    assert dict(ctx.banco.consultar("select cadastro, max(arquivo) from sancoes group by cadastro")) == {
        "CEIS": "20261124", "CNEP": "20261127"}
    vias = dict(ctx.banco.consultar("select alvo, via from fontes_federais where motor = 'sancoes'"))
    assert vias["CEIS"].startswith(sancoes.CGU)


def test_sancoes_403_em_todas_as_vias_fica_nao_conferido(tmp_path):
    ctx = _ctx(tmp_path, lambda url, **_: _nao(url, 403))
    mf.motor_sancoes(ctx)
    for _, situacao, erro in _situacao(ctx, "sancoes"):
        assert situacao == "nao_publicado" and "403" in erro and "CGU" in erro
    r = federais.conferir(ctx.banco.con, ate=date(2026, 11, 30))
    assert "sancoes" in r.cobertura["problemas"]


# --- FNS e a próxima sondagem ---------------------------------------------------------------------

def test_fns_sem_os_enderecos_descartados_e_com_o_periodo_em_datas():
    assert not set(fns.DESCARTADOS) & set(fns.MODELOS)
    novos = [fns.url(m, 5208707, 2025) for m in fns.MODELOS if m.startswith(fns.CONSULTA)]
    assert novos and all("520870" in u for u in novos)
    assert any("dataPagamentoInicial=01/01/2025&dataPagamentoFinal=31/12/2025" in u for u in novos)


def test_sondagem_da_segunda_rodada_pede_o_que_ficou_em_aberto():
    from onisciente import sondagem
    c = {k: [u if isinstance(u, str) else u[0] for u in v] for k, v in sondagem.CANDIDATOS.items()
         if k.startswith("d1_")}
    assert not any("apifns.saude.gov.br" in u for u in c["d1_fns"])          # não existe no DNS
    assert any(u.endswith("portalController.js") for u in c["d1_fns"])
    assert any("p_cgc=01612092000123" in u for u in c["d1_fnde"])
    assert any(u.startswith(sancoes.CGU) for u in c["d1_sancoes"])
    assert "https://virtual.tcmgo.tc.br/jurisprudencia/" in c["d1_tcm"]
    assert economia_go.CANDIDATOS[0] in c["d1_economia_go"]
