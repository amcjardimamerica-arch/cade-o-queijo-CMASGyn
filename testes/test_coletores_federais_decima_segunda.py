"""Bloco 5 (Frente D1), décima segunda rodada: a sondagem de 28/11/2026, 08:08Z (commit 079a72d, índice
``indice_d1_fns_d1_tcm_d1_tcu``), feita com o código da rodada 11.

Respostas reais em ``testes/dados/federais/``:
- ``fns_detalhe_pagamento_fundo_2025_count1000_real.json``: a listagem das ordens do Fundo Municipal de Saúde
  em 2025 com count=1000, agora guardada inteira (691.235 bytes, d1_fns entre as fontes grandes da
  sondagem): as 676 ordens, reduzidas aos campos que o leitor usa, com as contas trocadas por fictícias;
- ``tcm_jurisprudencia_exportar_goiania_2025_real.csv``: a exportação em CSV da jurisprudência do TCM-GO com
  municipio=GOIANIA e ano_votacao=2025, com as 918 linhas e as 17 colunas; a ementa (gerada por IA no
  próprio TCM-GO, sem nome de pessoa) cortada em 100 caracteres e o resumo esvaziado;
- ``tcm_jurisprudencia_buscar_municipio_goiania_2025_p1_real.json``: a página 1 da busca com o mesmo filtro
  (total_items 918), com as 100 decisões reduzidas a número, data, entidade, órgão, relator e resultado.
"""

from __future__ import annotations

import json
import urllib.parse
from datetime import date
from pathlib import Path

from onisciente import historico
from onisciente.coletores import base, fns, tcm, tcu
from onisciente.coletores import motores_federais as mf

DADOS = Path(__file__).parent / "dados" / "federais"
FUNDO = "37623352000103"
PAGINA_GRANDE = "fns_detalhe_pagamento_fundo_2025_count1000_real.json"
EXPORTAR_2025 = "tcm_jurisprudencia_exportar_goiania_2025_real.csv"
BUSCAR_2025 = "tcm_jurisprudencia_buscar_municipio_goiania_2025_p1_real.json"


def _bytes(nome: str) -> bytes:
    return (DADOS / nome).read_bytes()


def _ok(url, conteudo: bytes) -> base.Leitura:
    return base.Leitura(True, url, conteudo, http=200)


def _nao(url, codigo=404) -> base.Leitura:
    return base.Leitura(False, url, erro=f"HTTP {codigo}", http=codigo)


def _ctx(tmp_path, leitor, meses=("2025-01", "2025-12"), dormir=lambda s: None):
    banco = historico.Banco(tmp_path / "h.db")
    mf.preparar(banco)
    return historico.Contexto(banco, historico.meses(*meses), date(2026, 11, 28), ler_url=leitor,
                              dormir=dormir, pausa=0)


def _query(url):
    return urllib.parse.parse_qs(urllib.parse.urlsplit(url).query, keep_blank_values=True)


def _situacoes(ctx, motor):
    return {a: (s, e) for a, s, e in ctx.banco.consultar(
        "select alvo, situacao, erro from fontes_federais where motor = ?", motor)}


def _chave(ordem: dict) -> str:
    return json.dumps({k: v for k, v in ordem.items() if k not in ("conta", "programa", "bloco")},
                      sort_keys=True, default=str)


# --- FNS: a página de 1000 inteira fecha o ano (requisitos 146 e 164) -------------------------------

def test_fns_pagina_grande_real_traz_as_676_ordens_sem_repetir_e_fecha_as_40_acoes():
    conteudo = _bytes(PAGINA_GRANDE)
    resultado = json.loads(conteudo)["resultado"]
    assert (resultado["total"], resultado["totalPaginas"], resultado["itensPorPagina"]) == (676, 1, 1000)
    ordens, total = fns.pagamentos(conteudo)
    assert (len(ordens), total) == (676, 676)
    assert len({_chave(o) for o in ordens}) == 676                      # nenhuma ordem repetida
    p1, _ = fns.pagamentos(_bytes("fns_detalhe_pagamento_fundo_2025_p1_real.json"))
    assert [_chave(o) for o in p1] == [_chave(o) for o in ordens[:100]]
    # As 676 somam o valorTotalGeral do servidor; sem a rejeitada, o total das 40 ações de detalhe-acao.
    assert round(sum(o["valor_bruto"] for o in ordens), 2) == resultado["dados"][0]["valorTotalGeral"] == 1036219851.35
    assert [o["ordem_bancaria"] for o in ordens if o["rejeicao"]] == ["2025OB016558"]
    acoes, _ = fns.acoes(_bytes("fns_detalhe_acao_fundo_2025_real.json"))
    pago: dict[str, float] = {}
    for o in ordens:
        if not o["rejeicao"]:
            pago[o["programa_id"]] = round(pago.get(o["programa_id"], 0.0) + o["valor_bruto"], 2)
    assert len(acoes) == 40 and set(pago) == {a["id"] for a in acoes}
    assert all(abs(pago[a["id"]] - a["valor_total"]) <= 0.01 for a in acoes)
    assert round(sum(pago.values()), 2) == round(sum(a["valor_total"] for a in acoes), 2) == 1030381073.26


def _com_o_fundo(ctx):
    ctx.banco.con.execute("INSERT INTO fns_entidades VALUES (2025, ?, 0, 'FUNDO MUNICIPAL DE SAUDE', 'MUNICIPAL', "
                          "'520870', 0)", (FUNDO,))


def test_motor_fns_com_as_respostas_reais_de_2025_fecha_todas_as_acoes_numa_leitura(tmp_path):
    pedidos: list[dict] = []

    def leitor(url, **_):
        if "detalhe-acao" in url:
            return _ok(url, _bytes("fns_detalhe_acao_fundo_2025_real.json"))
        if "detalhe-pagamento" in url:
            pedidos.append(_query(url))
            return _ok(url, _bytes(PAGINA_GRANDE))
        return _nao(url)

    ctx = _ctx(tmp_path, leitor)
    _com_o_fundo(ctx)
    mf.motor_fns_detalhe(ctx, 5208707)
    assert [(q["acoes"], q["page"], q["count"]) for q in pedidos] == [([""], ["1"], ["1000"])]
    acoes = ctx.banco.consultar("select id, pago, valor_total from fns_acoes")
    assert len(acoes) == 40 and all(abs(pago - total) <= 0.01 for _, pago, total in acoes)
    ordens, _ = fns.pagamentos(_bytes(PAGINA_GRANDE))
    fundo_a_fundo = [o for o in ordens if o["fundo_a_fundo"] and not o["rejeicao"]]
    assert ctx.banco.consultar("select count(*), round(sum(valor_bruto), 2) from repasses_fns") == [
        (len(fundo_a_fundo), round(sum(o["valor_bruto"] for o in fundo_a_fundo), 2))]
    situacao, erro = _situacoes(ctx, "fns")["detalhe 2025"]
    assert situacao == "lido" and "não fecham" not in erro and "a listagem de uma vez não serviu" not in erro
    assert "1 ordens rejeitadas ou canceladas (motivoRejeicao: 2025OB016558) somando 5838778.09" in erro


# --- TCM-GO: a exportação traz o ano inteiro, sem o limite de 1000 (requisito 154) ------------------

def test_tcm_exportacao_real_de_2025_traz_o_ano_inteiro_da_busca():
    busca = json.loads(_bytes(BUSCAR_2025))
    assert busca["pagination"]["total_items"] == 918 and busca["pagination"]["total_pages"] == 10
    linhas = _bytes(EXPORTAR_2025).decode("utf-8-sig").splitlines()
    assert linhas[0].split(";") == [
        "ID do documento (chave)", "Número do acórdão", "Número do processo", "Ano", "Data da sessão",
        "Órgão julgador", "Tipo de pauta", "Assunto", "Macroassunto", "Relator", "Revisor (IA)",
        "Entidade fiscalizada", "Resultado (IA)", "ODS (IA)", "Ementa (IA)", "Resumo (IA)", "Link do PDF"]
    decisoes = tcm.exportacao(_bytes(EXPORTAR_2025))
    assert len(decisoes) == 918                                  # o total da busca, sem parar em 1000
    assert {d["ano"] for d in decisoes} == {2025}
    assert (decisoes[0]["data"], min(d["data"] for d in decisoes)) == ("2025-12-17", "2025-01-14")
    # As 100 primeiras são as da página 1 da busca, na mesma ordem e com a mesma leitura.
    pdfs = [d["url"].rsplit("/", 1)[-1] for d in decisoes]
    assert pdfs[:100] == [d["document_id"] for d in busca["data"]]
    da_busca, _ = tcm.jurisprudencia(_bytes(BUSCAR_2025))
    assert [(d["chave"], d["data"], d["relator"], d["sobre_goiania"]) for d in decisoes[:100]] == [
        (d["chave"], d["data"], d["relator"], d["sobre_goiania"]) for d in da_busca]
    assert sum(d["sobre_goiania"] for d in decisoes) == 873
    assert len(set(pdfs)) == 918 and len({d["chave"] for d in decisoes}) == 917   # um acórdão com 2 PDFs
    for torto in (b'{"data": []}', b"<html>erro</html>", b""):
        try:
            tcm.exportacao(torto)
        except ValueError:
            pass
        else:
            raise AssertionError("formato mudado passou")


def test_motor_tcm_le_a_exportacao_ano_a_ano_sem_a_busca(tmp_path):
    pedidos: list[dict] = []
    so_cabecalho = _bytes(EXPORTAR_2025).decode("utf-8-sig").splitlines()[0].encode()

    def leitor(url, **kw):
        assert kw.get("cabecalhos") == {"X-Cliente": "portal"}
        q = _query(url)
        pedidos.append(q)
        if "/exportar?" in url:
            return _ok(url, _bytes(EXPORTAR_2025) if q["ano_votacao"] == ["2025"] else so_cabecalho)
        return _ok(url, _bytes(BUSCAR_2025))

    ctx = _ctx(tmp_path, leitor, meses=("2024-11", "2026-11"))
    mf.motor_tcm(ctx, "Goiânia")
    assert [(q["ano_votacao"], q["municipio"], q["formato"]) for q in pedidos] == [
        (["2026"], ["GOIANIA"], ["csv"]), (["2025"], ["GOIANIA"], ["csv"]), (["2024"], ["GOIANIA"], ["csv"])]
    assert ctx.banco.consultar("select count(*) from decisoes_controle where tribunal = 'TCM-GO'") == [(873,)]
    assert _situacoes(ctx, "tcm")["decisoes"] == ("lido", None)

    # Um ano que não vem: a busca paginada cobre o intervalo, o que já veio não conta de novo, e a nota diz.
    pedidos.clear()
    ctx = _ctx(tmp_path / "b", lambda url, **kw: _nao(url, 503) if "ano_votacao=2024" in url else leitor(url, **kw),
               meses=("2024-11", "2026-11"))
    mf.motor_tcm(ctx, "Goiânia")
    assert any("page" in q for q in pedidos)
    assert ctx.banco.consultar("select count(*) from decisoes_controle where tribunal = 'TCM-GO'") == [(873,)]
    situacao, erro = _situacoes(ctx, "tcm")["decisoes"]
    assert situacao == "lido"
    assert erro.startswith("a exportação não veio em 1 de 3 anos (2024: HTTP 503); a busca paginada cobriu o "
                           "intervalo")


# --- TCU: as 3 tentativas do Contexto, com espera, cobrem a conexão encerrada (requisito 154) ---------

def test_tcu_conexao_encerrada_e_lida_de_novo_com_espera_crescente(tmp_path):
    vezes: dict[int, int] = {}
    esperas: list[float] = []

    def leitor(url, **_):
        if not url.startswith(tcu.PESQUISA):
            return _nao(url)
        inicio = int(_query(url)["inicio"][0])
        vezes[inicio] = vezes.get(inicio, 0) + 1
        if inicio in (0, 150) and vezes[inicio] <= 2:          # como na sondagem: inicio=0 e 150 caem
            return base.Leitura(False, url, erro="URLError: [Errno 104] Connection reset by peer")
        nome = {0: "tcu_pesquisa_50_real.json", 50: "tcu_pesquisa_50_real.json",
                100: "tcu_pesquisa_inicio100_real.json"}.get(inicio, "tcu_pesquisa_inicio150_real.json")
        return _ok(url, _bytes(nome))

    ctx = _ctx(tmp_path, leitor, meses=("2022-01", "2026-11"), dormir=esperas.append)
    mf.motor_tcu(ctx, "Goiânia")
    assert vezes[0] == 3 and vezes[150] == 3                     # a 3ª tentativa leu
    assert esperas.count(5) >= 2 and esperas.count(10) >= 2      # 5 s e 10 s antes de cada nova tentativa
    assert _situacoes(ctx, "tcu")["pesquisa"] == ("lido", None)
