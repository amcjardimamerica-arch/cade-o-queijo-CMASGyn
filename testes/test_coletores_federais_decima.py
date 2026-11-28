"""Bloco 5 (Frente D1), décima rodada: a sondagem de 28/11/2026, 06:50Z (commit a8761d9, índice
``indice_d2_transweb_popup_d1_fns_d1_tcm_d1_tcu``).

Respostas reais em ``testes/dados/federais/``:
- ``tcu_pesquisa_inicio150_real.json`` e ``tcu_pesquisa_inicio1300_real.json``: a pesquisa do TCU além dos
  100 primeiros resultados, inteiras (50 acórdãos cada, quantidadeEncontrada 1374);
- ``tcm_jurisprudencia_filtros_real.json``: os filtros da jurisprudência do TCM-GO, inteiros (246 municípios);
- ``tcm_jurisprudencia_buscar_p1_real.json``: a página 1 da busca pelo texto "Goiânia", com as 100 decisões
  reduzidas aos campos que o leitor usa;
- ``fns_detalhe_pagamento_acao_61659_2025_p1_real.json``: a página 1 de 2 das ordens da ação 61659 do Fundo
  Municipal de Saúde em 2025 (filtro ``acoes``), com os números das contas correntes trocados por fictícios.
"""

from __future__ import annotations

import json
import urllib.parse
from datetime import date
from itertools import pairwise
from pathlib import Path

from onisciente import historico
from onisciente.coletores import base, fns, tcm, tcu
from onisciente.coletores import motores_federais as mf

DADOS = Path(__file__).parent / "dados" / "federais"


def _bytes(nome: str) -> bytes:
    return (DADOS / nome).read_bytes()


def _ok(url, conteudo: bytes) -> base.Leitura:
    return base.Leitura(True, url, conteudo, http=200)


def _nao(url, codigo=404) -> base.Leitura:
    return base.Leitura(False, url, erro=f"HTTP {codigo}", http=codigo)


def _ctx(tmp_path, leitor, meses=("2025-01", "2025-12")):
    banco = historico.Banco(tmp_path / "h.db")
    mf.preparar(banco)
    return historico.Contexto(banco, historico.meses(*meses), date(2026, 11, 28), ler_url=leitor,
                              dormir=lambda s: None, pausa=0)


def _query(url):
    return urllib.parse.parse_qs(urllib.parse.urlsplit(url).query, keep_blank_values=True)


def _situacoes(ctx, motor):
    return {a: (s, e) for a, s, e in ctx.banco.consultar(
        "select alvo, situacao, erro from fontes_federais where motor = ?", motor)}


# --- TCU: a pesquisa passa de 100 (requisito 154) ---------------------------------------------------

def test_tcu_pesquisa_real_alem_de_100_vem_inteira_e_em_ordem():
    faixas = {}
    for nome, inicio in (("tcu_pesquisa_50_real.json", 50), ("tcu_pesquisa_inicio100_real.json", 100),
                         ("tcu_pesquisa_inicio150_real.json", 150), ("tcu_pesquisa_inicio1300_real.json", 1300)):
        conteudo = _bytes(nome)
        assert json.loads(conteudo)["inicio"] == inicio and tcu.encontrados(conteudo) == 1374
        datas = sorted(d["data"] for d in tcu.ler(conteudo, pesquisa=True))
        assert len(datas) == 50
        faixas[inicio] = (datas[0], datas[-1])
    assert faixas[150] == ("2021-06-30", "2022-10-19") and faixas[1300] == ("1994-04-06", "2000-06-14")
    ordem = [faixas[i] for i in (50, 100, 150, 1300)]
    assert all(mais_nova[0] >= mais_velha[1] for mais_nova, mais_velha in pairwise(ordem))
    assert tcu.LIMITE_PESQUISA is None
    assert tcu.encontrados(b'{"documentos": []}') is None and tcu.encontrados(b"<html>") is None


def _pagina_tcu(inicio: int) -> bytes:
    """A página real mais próxima do pedido; a de 1350 (a última) só com as 24 que faltam para 1374."""
    if inicio >= 1350:
        obj = json.loads(_bytes("tcu_pesquisa_inicio1300_real.json"))
        obj["inicio"], obj["documentos"] = inicio, obj["documentos"][:1374 - inicio]
        return json.dumps(obj).encode()
    nome = {100: "tcu_pesquisa_inicio100_real.json", 150: "tcu_pesquisa_inicio150_real.json"}.get(
        inicio, "tcu_pesquisa_50_real.json" if inicio < 150 else "tcu_pesquisa_inicio1300_real.json")
    return _bytes(nome)


def test_tcu_pesquisa_le_ate_o_total_e_diz_o_que_faltou(tmp_path, monkeypatch):
    pedidos: list[int] = []

    def leitor(url, cair_em=None, **_):
        if not url.startswith(tcu.PESQUISA):
            return _nao(url)
        inicio = int(_query(url)["inicio"][0])
        pedidos.append(inicio)
        if inicio == cair_em:
            return base.Leitura(False, url, erro="URLError: [Errno 104] Connection reset by peer")
        return _ok(url, _pagina_tcu(inicio))

    # Intervalo que começa antes de tudo: vai até o total declarado (1374, 28 páginas de 50), sem nota.
    ctx = _ctx(tmp_path, leitor, meses=("1990-01", "2026-11"))
    mf.motor_tcu(ctx, "Goiânia")
    assert pedidos == list(range(0, 1374, 50))
    assert _situacoes(ctx, "tcu")["pesquisa"] == ("lido", None)

    # Uma página que cai no meio: as anteriores valem e a nota diz quantas foram lidas e de onde falta.
    pedidos.clear()
    ctx = _ctx(tmp_path / "b", lambda url, **kw: leitor(url, cair_em=200, **kw), meses=("1990-01", "2026-11"))
    mf.motor_tcu(ctx, "Goiânia")
    situacao, erro = _situacoes(ctx, "tcu")["pesquisa"]
    assert situacao == "lido" and sorted(set(pedidos)) == [0, 50, 100, 150, 200]   # 200: 3 tentativas
    assert erro == ("URLError: [Errno 104] Connection reset by peer; lidos 200 de 1374 resultados; "
                    "faltam os de inicio=200 em diante")

    # O teto de páginas também é dito.
    monkeypatch.setattr(tcu, "PAGINAS_MAX_PESQUISA", 3)
    ctx = _ctx(tmp_path / "c", leitor, meses=("1990-01", "2026-11"))
    mf.motor_tcu(ctx, "Goiânia")
    assert _situacoes(ctx, "tcu")["pesquisa"] == (
        "lido", "lidos 150 de 1374 resultados; faltam os de inicio=150 em diante (teto de 3 páginas)")


def test_tcu_pesquisa_para_quando_passa_do_comeco_do_intervalo(tmp_path):
    pedidos: list[int] = []

    def leitor(url, **_):
        if not url.startswith(tcu.PESQUISA):
            return _nao(url)
        inicio = int(_query(url)["inicio"][0])
        pedidos.append(inicio)
        return _ok(url, _pagina_tcu(inicio))

    # A página de inicio=100 real vai de 26/10/2022 a 02/04/2024, toda antes de 11/2024: o resto da pesquisa
    # é mais velho, nada falta e a leitura para ali (0 e 50 recebem a página real de inicio=50, até 28/10/2025).
    ctx = _ctx(tmp_path, leitor, meses=("2024-11", "2026-11"))
    mf.motor_tcu(ctx, "Goiânia")
    assert pedidos == [0, 50, 100]
    assert _situacoes(ctx, "tcu")["pesquisa"] == ("lido", None)


# --- TCM-GO: o filtro de município (requisito 154) --------------------------------------------------

def test_tcm_filtros_reais_trazem_goiania_e_a_busca_pelo_texto_traz_o_estado_todo():
    filtros = json.loads(_bytes("tcm_jurisprudencia_filtros_real.json"))["data"]
    municipios = {m["nome"]: m["valor"] for m in filtros["municipios"]}
    assert len(municipios) == 246
    assert municipios["Goiânia"] == tcm.valor_do_municipio("Goiânia") == "GOIANIA"
    assert municipios["Aparecida de Goiânia"] == "APARECIDA GOIANIA"
    assert _query(tcm.url_jurisprudencia("", 3, municipio="GOIANIA")) == {
        "texto": [""], "page": ["3"], "page_size": ["100"], "sort_by": ["data_sessao"], "sort_order": ["desc"],
        "municipio": ["GOIANIA"]}
    assert "municipio" not in _query(tcm.url_jurisprudencia("Goiânia", 1))
    pagina = _bytes("tcm_jurisprudencia_buscar_p1_real.json")
    assert json.loads(pagina)["pagination"]["total_items"] == 13493
    decisoes, mais = tcm.jurisprudencia(pagina)
    assert mais and len(decisoes) == 100 and sum(d["sobre_goiania"] for d in decisoes) == 27
    assert decisoes[0]["data"] == "2026-10-28"
    aparecida = [d for d in json.loads(pagina)["data"] if d["entidade_fiscalizada"].startswith("APARECIDA GOIANIA")]
    assert len(aparecida) == 8 and not any(tcu.sobre(d["entidade_fiscalizada"]) for d in aparecida)


def _so_goiania(conteudo: bytes) -> bytes:
    """A página real com só as decisões de Goiânia: o que o filtro de município deve devolver."""
    obj = json.loads(conteudo)
    obj["data"] = [d for d in obj["data"] if str(d["entidade_fiscalizada"]).startswith("GOIANIA")]
    obj["pagination"]["has_next"] = False
    return json.dumps(obj).encode()


def test_motor_tcm_pede_pelo_municipio_e_so_volta_ao_texto_se_o_filtro_nao_valer(tmp_path):
    real = _bytes("tcm_jurisprudencia_buscar_p1_real.json")
    pedidos: list[dict] = []

    def leitor(url, **_):
        # Rodada 12 (28/11/2026): a sondagem 079a72d provou o exportar em CSV, que o motor agora lê primeiro.
        # Este servidor de teste é o de antes dele: recusa o exportar (404) e a trava segue provando a busca
        # paginada, que ficou de reserva. As asserções não mudaram.
        if "/exportar?" in url:
            return _nao(url)
        q = _query(url)
        pedidos.append(q)
        if q.get("municipio") == ["GOIANIA"]:
            return _ok(url, _so_goiania(real))
        return _ok(url, real)

    ctx = _ctx(tmp_path, leitor, meses=("2026-01", "2026-11"))
    mf.motor_tcm(ctx, "Goiânia")
    assert [(q["texto"], q.get("municipio")) for q in pedidos] == [([""], ["GOIANIA"])]
    assert ctx.banco.consultar("select count(*) from decisoes_controle where tribunal = 'TCM-GO'") == [(27,)]
    assert _situacoes(ctx, "tcm")["decisoes"] == ("lido", None)

    # O servidor que ignora o filtro devolve o Estado todo: nada da primeira leitura é guardado, a busca
    # volta ao texto (só as 27 de Goiânia ficam) e a nota diz por quê.
    pedidos.clear()
    # Rodada 12 (28/11/2026): o mesmo servidor de antes do exportar (sondagem 079a72d), que o recusa (404).
    ctx = _ctx(tmp_path / "b", lambda url, **_: _nao(url) if "/exportar?" in url else (
                   pedidos.append(_query(url)), _ok(url, real if "page=1&" in url else _so_goiania(real)))[1],
               meses=("2026-01", "2026-11"))
    mf.motor_tcm(ctx, "Goiânia")
    assert [(q["texto"], q.get("municipio")) for q in pedidos][:2] == [([""], ["GOIANIA"]), (["Goiânia"], None)]
    assert ctx.banco.consultar("select count(*) from decisoes_controle where tribunal = 'TCM-GO'") == [(27,)]
    situacao, erro = _situacoes(ctx, "tcm")["decisoes"]
    assert situacao == "lido"
    assert erro.startswith("o filtro municipio=GOIANIA não valeu (27 de 100 decisões da primeira página")


# --- FNS: as páginas repetem de forma fixa, e o filtro por ação responde (requisitos 146 e 164) -------

def test_fns_filtro_por_acao_real_traz_so_a_acao_e_o_total_dela():
    ordens, total = fns.pagamentos(_bytes("fns_detalhe_pagamento_acao_61659_2025_p1_real.json"))
    assert (len(ordens), total) == (100, 166)
    assert {o["programa_id"] for o in ordens} == {"61659"}
    assert sum(1 for o in ordens if o["fundo_a_fundo"]) == 27
    assert round(sum(o["valor_bruto"] for o in ordens), 2) == 427949655.59
    assert mf.RELEITURAS_FNS == 1                      # a repetição da listagem é fixa: uma releitura só


def test_sondagem_da_decima_rodada_pede_a_pagina_2_da_acao_e_o_tcm_pelo_municipio():
    from onisciente import sondagem
    pags = [_query(u) for u in sondagem.CANDIDATOS["d1_fns"] if "detalhe-pagamento" in u]
    assert any(q["acoes"] == ["61659"] and q["page"] == ["2"] for q in pags)
    assert any(q["count"] == ["1000"] for q in pags)
    assert tcm.url_jurisprudencia("", 1, municipio="GOIANIA") in sondagem.CANDIDATOS["d1_tcm"]
