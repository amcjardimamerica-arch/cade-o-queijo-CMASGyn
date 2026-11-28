"""Bloco 5 (Frente D1), sexta rodada: as respostas da sondagem de 28/11/2026 (índice
``indice_d1_fns_d1_sancoes_d1_tcu_d1_tcm_d1_transferegov``, sobrescrito).

Respostas reais em ``testes/dados/federais/``:
- ``fns_entidades_goiania_p2_real.json``: a página 2 das entidades de Goiânia com 100 por página (91
  linhas, com o Fundo Municipal e o Fundo Estadual de Saúde); nas 22 pessoas físicas, nome e CPF trocados.

As respostas de ``detalhe-acao`` e ``detalhe-pagamento`` ainda não foram vistas: as deste teste são
fictícias, montadas com os campos que ``acaoController.js`` e ``pagamentoController.js`` (reais) usam.
"""

from __future__ import annotations

import json
import urllib.parse
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from onisciente import historico
from onisciente.coletores import base, fns, tcu
from onisciente.coletores import motores_federais as mf

DADOS = Path(__file__).parent / "dados" / "federais"
ALVO = SimpleNamespace(ibge=5208707, uf="GO", municipio="Goiânia", pncp_cnpjs=())
FUNDO = "37623352000103"


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


def _resposta(dados: list[dict]) -> bytes:
    return json.dumps({"resultado": {"dados": dados, "pagina": 0, "itensPorPagina": 100, "total": len(dados),
                                     "totalPaginas": 1}}).encode()


ACOES = [
    {"id": 101, "descricao": "INCREMENTO TEMPORARIO AO CUSTEIO", "valorTotal": 1000.0, "valorDesconto": 0,
     "valorLiquido": 1000.0, "blocoPacto": {"nome": "MANUTENCAO"}, "grupoAcao": {"nome": "ATENCAO PRIMARIA"},
     "componenteBloco": {"nome": "PAB"}, "valorTotalGeral": 1000.0},
    {"id": 102, "descricao": "SEM REPASSE", "valorTotal": 0, "valorDesconto": 0, "valorLiquido": 0,
     "blocoPacto": {"nome": "MANUTENCAO"}, "grupoAcao": {"nome": "VIGILANCIA"}, "componenteBloco": {}},
]
PAGAMENTOS = [
    {"id": {"processo": "25000.1", "indicadorFundoAFundo": "S"}, "numeroDocumentoSiafi": "2025OB000001",
     "valorTotal": 600.0, "valorDescontoTotal": 0, "valorLiquido": 600.0, "codigoBanco": "001",
     "codigoAgencia": "1234", "contaCorrente": "99999", "nuPortaria": "10", "dataPagamento": "15/03/2025"},
    {"id": {"processo": "25000.2"}, "numeroDocumentoSiafi": "2025OB000002", "valorTotal": 400.0,
     "valorDescontoTotal": 0, "valorLiquido": 400.0, "codigoBanco": "001", "codigoAgencia": "1234",
     "contaCorrente": "99999", "dataPagamento": "20/04/2025"},
]


# --- FNS: as entidades fecham e o valor por entidade (requisitos 146 e 164) -----------------------

def test_fns_entidades_pagina_2_real_fecha_as_191_e_traz_o_fundo():
    linhas, total, paginas = fns.entidades(_bytes("fns_entidades_goiania_p2_real.json"), "520870")
    assert (len(linhas), total, paginas) == (91, 191, 2)                  # 100 + 91
    fundos = {l["nome"]: (l["cpf_cnpj"], l["esfera"]) for l in linhas if "FUNDO" in l["nome"]}
    assert fundos["FUNDO MUNICIPAL DE SAUDE"] == (FUNDO, "MUNICIPAL")
    assert fundos["FUNDO ESTADUAL DE SAUDE"][1] == "ESTADUAL"
    assert all(l["cpf_cnpj"].startswith("***") for l in linhas if l["pessoa_fisica"])


def test_fns_detalhe_com_os_parametros_dos_controladores():
    acao = urllib.parse.urlparse(fns.url_detalhe("detalhe-acao", 5208707, 2025, "37.623.352/0001-03"))
    q = urllib.parse.parse_qs(acao.query, keep_blank_values=True)
    assert acao.path.endswith("/recursos/consulta-detalhada/detalhe-acao")
    assert q["cpfCnpjUg"] == [FUNDO] and q["estado"] == ["GO"] and q["municipio"] == ["520870"]
    assert q["planoOrcamentario"] == [""] and q["count"] == ["100"]
    pag = urllib.parse.parse_qs(urllib.parse.urlparse(
        fns.url_detalhe("detalhe-pagamento", 5208707, 2025, FUNDO, acao="101")).query, keep_blank_values=True)
    assert pag["acoes"] == ["101"] and "grupo" not in pag and pag["cpfCnpjUg"] == [FUNDO]
    acoes, total = fns.acoes(_resposta(ACOES))
    assert total == 2 and acoes[0] == {"id": "101", "bloco": "MANUTENCAO", "grupo": "ATENCAO PRIMARIA",
                                       "componente": "PAB", "descricao": "INCREMENTO TEMPORARIO AO CUSTEIO",
                                       "valor_total": 1000.0, "valor_desconto": 0.0, "valor_liquido": 1000.0}
    ordens, _ = fns.pagamentos(_resposta(PAGAMENTOS))
    assert ordens[0]["ordem_bancaria"] == "2025OB000001" and ordens[0]["mes"] == "2025-03"
    assert ordens[0]["situacao"] == "processo 25000.1 portaria 10" and ordens[1]["conta"] == "99999"
    for torto in (b'{"resultado":{"total":1}}', b"<html><body>erro</body></html>", _resposta([{"id": 1}])):
        try:
            fns.acoes(torto)
        except ValueError:
            pass
        else:
            raise AssertionError("formato mudado passou")


def _leitor_detalhe(pagamentos=PAGAMENTOS, pedidos=None):
    def leitor(url, **_):
        if pedidos is not None:
            pedidos.append(url)
        if "detalhe-acao" in url and f"cpfCnpjUg={FUNDO}" in url:
            return _ok(url, _resposta(ACOES))
        if "detalhe-pagamento" in url and "acoes=101" in url:
            return _ok(url, _resposta(pagamentos))
        return _nao(url, 400)
    return leitor


def _com_o_fundo(ctx):
    ctx.banco.con.execute("INSERT INTO fns_entidades VALUES (2025, ?, 0, 'FUNDO MUNICIPAL DE SAUDE', 'MUNICIPAL', "
                          "'520870', 0)", (FUNDO,))
    ctx.banco.con.execute("INSERT INTO fns_entidades VALUES (2025, '00544963000156', 0, 'FUNDO ESTADUAL DE SAUDE', "
                          "'ESTADUAL', '520870', 0)")


def test_motor_fns_detalhe_le_acoes_e_ordens_do_fundo_e_confere_a_soma(tmp_path):
    pedidos: list[str] = []
    ctx = _ctx(tmp_path, _leitor_detalhe(pedidos=pedidos))
    _com_o_fundo(ctx)
    mf.motor_fns_detalhe(ctx, 5208707)
    assert not any("00544963000156" in u for u in pedidos)          # o Fundo Estadual não é do Município
    assert not any("acoes=102" in u for u in pedidos)                # ação sem repasse não pede pagamento
    assert ctx.banco.consultar("select id, valor_total, pago from fns_acoes order by id") == [
        ("101", 1000.0, 1000.0), ("102", 0.0, None)]
    assert ctx.banco.consultar("select mes, cnpj, bloco, programa, valor_liquido, ordem_bancaria from repasses_fns "
                               "order by data") == [
        ("2025-03", FUNDO, "MANUTENCAO", "INCREMENTO TEMPORARIO AO CUSTEIO", 600.0, "2025OB000001"),
        ("2025-04", FUNDO, "MANUTENCAO", "INCREMENTO TEMPORARIO AO CUSTEIO", 400.0, "2025OB000002")]
    situacao, erro = _situacoes(ctx, "fns")["detalhe 2025"]
    assert situacao == "lido" and erro is None


def test_motor_fns_detalhe_que_nao_fecha_anota_e_outra_via_nao_duplica(tmp_path):
    ctx = _ctx(tmp_path, _leitor_detalhe(pagamentos=PAGAMENTOS[:1]))
    _com_o_fundo(ctx)
    ctx.banco.inserir("repasses_fns", {"ano": 2025, "mes": "2025-03", "valor_liquido": 5.0, "via": "apifns"})
    mf.motor_fns_detalhe(ctx, 5208707)
    situacao, erro = _situacoes(ctx, "fns")["detalhe 2025"]
    assert situacao == "lido" and "ordens 600.00 contra 1000.00" in erro and "outra via" in erro
    assert ctx.banco.consultar("select via, count(*) from repasses_fns group by via") == [("apifns", 1)]
    assert ctx.banco.consultar("select pago from fns_acoes where id = '101'") == [(600.0,)]


def test_motor_fns_detalhe_recusado_e_falta_da_fonte(tmp_path):
    ctx = _ctx(tmp_path, lambda url, **_: _nao(url, 400))
    _com_o_fundo(ctx)
    mf.motor_fns_detalhe(ctx, 5208707)
    situacao, erro = _situacoes(ctx, "fns")["detalhe 2025"]
    assert situacao == "nao_publicado" and "HTTP 400" in erro
    assert ctx.banco.consultar("select count(*) from fns_acoes") == [(0,)]


# --- TCU: a pesquisa para em 100 resultados (requisito 154) ---------------------------------------

def test_tcu_pesquisa_nao_pede_alem_de_100_e_diz_por_que(tmp_path):
    pedidos = []

    def leitor(url, **_):
        pedidos.append(url)
        if url.startswith(tcu.PESQUISA):
            return _ok(url, _bytes("tcu_pesquisa_50_real.json"))      # páginas cheias
        return _nao(url)

    ctx = _ctx(tmp_path, leitor, meses=("2020-01", "2026-11"))
    mf.motor_tcu(ctx, "Goiânia")
    feitas = [u for u in pedidos if u.startswith(tcu.PESQUISA)]
    assert len(feitas) == 2 and not any("inicio=100" in u for u in feitas)
    situacao, erro = _situacoes(ctx, "tcu")["pesquisa"]
    assert situacao == "lido" and "além de 100" in erro


# --- Sondagem da sétima rodada ----------------------------------------------------------------------

def test_sondagem_da_sexta_rodada_pede_as_respostas_do_detalhe_e_a_tela_da_jurisprudencia():
    from onisciente import sondagem
    c = {k: [u if isinstance(u, str) else u[0] for u in v] for k, v in sondagem.CANDIDATOS.items()
         if k.startswith("d1_")}
    assert any("detalhe-acao" in u and f"cpfCnpjUg={FUNDO}" in u for u in c["d1_fns"])
    assert any("detalhe-pagamento" in u and f"cpfCnpjUg={FUNDO}" in u for u in c["d1_fns"])
    assert any("jurisprudencia-page-" in u for u in c["d1_tcm"])
    assert any("ordenacao=ANOACORDAO" in u for u in c["d1_tcu"])
