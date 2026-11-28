"""Bloco 5 (Frente D1), décima primeira rodada: a sondagem de 28/11/2026, 07:40Z (commit 9cc559c, índice
``indice_d1_fns_d1_tcm_d1_tcu``).

Respostas reais em ``testes/dados/federais/``:
- ``fns_detalhe_pagamento_fundo_2025_count1000_recorte_real.json``: a listagem das ordens do Fundo
  Municipal de Saúde em 2025 com count=1000. Veio numa página só, de 691.235 bytes; a sondagem guardou os
  primeiros 600 KB, e o recorte traz as 587 ordens inteiras desse começo, reduzidas aos campos que o leitor
  usa, com as contas correntes trocadas por fictícias;
- ``fns_detalhe_pagamento_acao_61659_2025_p2_real.json``: a página 2 de 2 das ordens da ação 61659 (filtro
  ``acoes``, 100 por página), também com contas fictícias;
- ``tcm_jurisprudencia_buscar_municipio_goiania_p1_real.json``: a página 1 da busca com municipio=GOIANIA,
  com as 100 decisões reduzidas aos campos que o leitor usa (ementa cortada em 160 caracteres);
- ``tcm_jurisprudencia_buscar_municipio_goiania_p20_422_real.json``: a recusa (HTTP 422) da página 20, inteira.
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
_IGNORADAS = ("conta", "programa", "bloco")   # as contas fictícias dos dois recortes não são as mesmas


def _bytes(nome: str) -> bytes:
    return (DADOS / nome).read_bytes()


def _ok(url, conteudo: bytes) -> base.Leitura:
    return base.Leitura(True, url, conteudo, http=200)


def _nao(url, codigo=404, conteudo=b"") -> base.Leitura:
    return base.Leitura(False, url, conteudo, erro=f"HTTP {codigo}", http=codigo)


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


def _chave(ordem: dict) -> str:
    return json.dumps({k: v for k, v in ordem.items() if k not in _IGNORADAS}, sort_keys=True, default=str)


# --- FNS: as ordens do ano numa página só (requisitos 146 e 164) ------------------------------------

def test_fns_count_1000_real_vem_numa_pagina_sem_repetir_e_contem_as_paginas_de_100():
    recorte, total = fns.pagamentos(_bytes("fns_detalhe_pagamento_fundo_2025_count1000_recorte_real.json"))
    assert (len(recorte), total) == (587, 587)          # o recorte não traz o total (o fim não coube)
    chaves = [_chave(o) for o in recorte]
    assert len(set(chaves)) == 587                       # nenhuma ordem repetida
    p1, total_p1 = fns.pagamentos(_bytes("fns_detalhe_pagamento_fundo_2025_p1_real.json"))
    assert total_p1 == 676
    assert [_chave(o) for o in p1] == chaves[:100]       # começa pelas 100 da página 1, na mesma ordem
    assert fns.POR_PAGINA_PAGAMENTOS == 1000
    assert _query(fns.url_detalhe("detalhe-pagamento", 5208707, 2025, FUNDO, 1,
                                  por_pagina=fns.POR_PAGINA_PAGAMENTOS))["count"] == ["1000"]
    assert _query(fns.url_detalhe("detalhe-acao", 5208707, 2025, FUNDO))["count"] == ["100"]


def _ordens_da_acao_61659() -> tuple[list[dict], list[dict]]:
    """As 166 ordens da ação 61659: as das duas páginas do filtro por ação, sem as repetidas, e as que só a
    página de 1000 trouxe. Devolve também as duas páginas do filtro."""
    p1, _ = fns.pagamentos(_bytes("fns_detalhe_pagamento_acao_61659_2025_p1_real.json"))
    p2, _ = fns.pagamentos(_bytes("fns_detalhe_pagamento_acao_61659_2025_p2_real.json"))
    recorte, _ = fns.pagamentos(_bytes("fns_detalhe_pagamento_fundo_2025_count1000_recorte_real.json"))
    unicas = {_chave(o): o for o in p1 + p2}
    so_no_recorte = [o for o in recorte if o["programa_id"] == "61659" and _chave(o) not in unicas]
    return list(unicas.values()) + so_no_recorte, p1 + p2


def test_fns_acao_61659_fecha_com_o_total_quando_a_ordem_rejeitada_sai():
    p2, total = fns.pagamentos(_bytes("fns_detalhe_pagamento_acao_61659_2025_p2_real.json"))
    assert (len(p2), total) == (66, 166)
    ordens, paginas = _ordens_da_acao_61659()
    # Com 100 por página, o filtro por ação também repete: 6 ordens nas duas páginas, e 6 outras faltam.
    assert len(paginas) == 166 and len({_chave(o) for o in paginas}) == 160
    assert len(ordens) == 166 and {o["programa_id"] for o in ordens} == {"61659"}
    # As 166 somam o valorTotalGeral do servidor; sem a ordem rejeitada, o total que detalhe-acao declara.
    assert round(sum(o["valor_bruto"] for o in ordens), 2) == 669552284.15
    rejeitadas = [o for o in ordens if o["rejeicao"]]
    assert [(o["ordem_bancaria"], o["valor_bruto"]) for o in rejeitadas] == [("2025OB016558", 5838778.09)]
    assert rejeitadas[0]["rejeicao"].startswith("10 CANCELAMENTO PARCIAL DA 2025OB016558")
    acoes, _ = fns.acoes(_bytes("fns_detalhe_acao_fundo_2025_real.json"))
    total_da_acao = next(a["valor_total"] for a in acoes if a["id"] == "61659")
    assert total_da_acao == 663713506.06
    assert round(sum(o["valor_bruto"] for o in ordens if not o["rejeicao"]), 2) == total_da_acao


def _so_a_acao_61659() -> bytes:
    obj = json.loads(_bytes("fns_detalhe_acao_fundo_2025_real.json"))
    obj["resultado"]["dados"] = [a for a in obj["resultado"]["dados"] if str(a["id"]) == "61659"]
    obj["resultado"]["total"], obj["resultado"]["totalPaginas"] = 1, 1
    return json.dumps(obj).encode()


def _pagina_das_ordens_reais() -> bytes:
    """As 166 ordens reais da ação 61659 numa página só, no formato bruto de ``detalhe-pagamento``."""
    _, paginas = _ordens_da_acao_61659()
    brutos = []
    for nome in ("fns_detalhe_pagamento_acao_61659_2025_p1_real.json",
                 "fns_detalhe_pagamento_acao_61659_2025_p2_real.json",
                 "fns_detalhe_pagamento_fundo_2025_count1000_recorte_real.json"):
        brutos.extend(json.loads(_bytes(nome))["resultado"]["dados"])
    vistos, dados = set(), []
    for d in brutos:
        o = fns.pagamentos(json.dumps({"resultado": {"dados": [d], "total": 1}}).encode())[0][0]
        if o["programa_id"] == "61659" and _chave(o) not in vistos:
            vistos.add(_chave(o))
            dados.append(d)
    assert len(dados) == 166 and paginas
    return json.dumps({"resultado": {"dados": dados, "pagina": 0, "itensPorPagina": 1000, "total": 166,
                                     "totalPaginas": 1}}).encode()


def _com_o_fundo(ctx):
    ctx.banco.con.execute("INSERT INTO fns_entidades VALUES (2025, ?, 0, 'FUNDO MUNICIPAL DE SAUDE', 'MUNICIPAL', "
                          "'520870', 0)", (FUNDO,))


def test_motor_fns_pede_as_ordens_do_ano_numa_pagina_e_tira_a_rejeitada(tmp_path):
    pedidos: list[dict] = []
    ordens = _pagina_das_ordens_reais()

    def leitor(url, listagem=True, **_):
        q = _query(url)
        if "detalhe-pagamento" in url:
            pedidos.append(q)
        if "detalhe-acao" in url:
            return _ok(url, _so_a_acao_61659())
        if "detalhe-pagamento" in url and (q["acoes"] == [""]) == listagem:
            return _ok(url, ordens)
        return _nao(url)

    ctx = _ctx(tmp_path, leitor)
    _com_o_fundo(ctx)
    mf.motor_fns_detalhe(ctx, 5208707)
    listagem = [q for q in pedidos if q.get("acoes") == [""]]
    assert [(q["page"], q["count"]) for q in listagem] == [(["1"], ["1000"])]   # uma leitura, sem releitura
    assert ctx.banco.consultar("select pago, valor_total from fns_acoes") == [(663713506.06, 663713506.06)]
    assert ctx.banco.consultar("select count(*) from repasses_fns where ordem_bancaria = '2025OB016558'") == [(0,)]
    situacao, erro = _situacoes(ctx, "fns")["detalhe 2025"]
    assert situacao == "lido" and "as ordens não fecham" not in erro
    assert ("1 ordens rejeitadas ou canceladas (motivoRejeicao: 2025OB016558) somando 5838778.09 ficam fora "
            "do pago e de repasses_fns") in erro

    # Pelo caminho de reserva (a listagem recusada, as ordens por ação), a rejeitada também sai e é dita.
    pedidos.clear()
    ctx = _ctx(tmp_path / "b", lambda url, **kw: leitor(url, listagem=False, **kw))
    _com_o_fundo(ctx)
    mf.motor_fns_detalhe(ctx, 5208707)
    por_acao = [q for q in pedidos if q.get("acoes") == ["61659"]]
    assert [(q["page"], q["count"]) for q in por_acao] == [(["1"], ["1000"])]
    assert ctx.banco.consultar("select pago from fns_acoes") == [(663713506.06,)]
    situacao, erro = _situacoes(ctx, "fns")["detalhe 2025"]
    assert situacao == "lido" and "as ordens não fecham" not in erro
    assert "ação 61659: 1 ordens rejeitadas ou canceladas (motivoRejeicao: 2025OB016558)" in erro


# --- TCM-GO: o filtro de município vale; sem chave, a busca para no resultado 1000 (requisito 154) ---

def test_tcm_filtro_municipio_real_traz_goiania_sem_aparecida():
    pagina = _bytes("tcm_jurisprudencia_buscar_municipio_goiania_p1_real.json")
    obj = json.loads(pagina)
    assert obj["pagination"]["total_items"] == 5491 and obj["pagination"]["total_pages"] == 55
    entidades = [d["entidade_fiscalizada"] for d in obj["data"]]
    assert sum(e.startswith("GOIANIA") for e in entidades) == 92
    assert not any("APARECIDA" in e for e in entidades)
    decisoes, mais = tcm.jurisprudencia(pagina)
    assert mais and len(decisoes) == 100 and sum(d["sobre_goiania"] for d in decisoes) == 92
    assert (decisoes[0]["data"], decisoes[-1]["data"]) == ("2026-10-22", "2026-09-15")


def test_tcm_recusa_real_da_pagina_20_diz_o_limite_de_1000():
    recusa = _bytes("tcm_jurisprudencia_buscar_municipio_goiania_p20_422_real.json")
    motivo = tcm.recusa_da_jurisprudencia(recusa)
    assert motivo.startswith("Sem chave de API, a busca pagina ate o resultado 1000.")
    assert "/acordao/jurisprudencia/exportar" in motivo
    assert tcm.recusa_da_jurisprudencia(b"<html>erro</html>") == ""
    assert tcm.RESULTADOS_SEM_CHAVE == 1000


def _leitor_tcm(pedidas: list[int], recusar_de: int | None = None):
    """A página real do filtro em toda página pedida (sempre com mais páginas e só decisões de 2026); a
    recusa real a partir de ``recusar_de``."""
    real = _bytes("tcm_jurisprudencia_buscar_municipio_goiania_p1_real.json")
    recusa = _bytes("tcm_jurisprudencia_buscar_municipio_goiania_p20_422_real.json")

    def leitor(url, **_):
        q = _query(url)
        p = int(q["page"][0])
        pedidas.append(p)
        assert q["municipio"] == ["GOIANIA"] and q["texto"] == [""]
        if recusar_de and p >= recusar_de:
            return _nao(url, 422, recusa)
        obj = json.loads(real)
        for d in obj["data"]:
            d["document_id"] = f"{d['document_id']}-p{p}"
            d["numero_acordao"] = f"{p:02d}{d['numero_acordao']}"
        return _ok(url, json.dumps(obj).encode())
    return leitor


def test_motor_tcm_para_na_pagina_10_e_diz_por_que(tmp_path, monkeypatch):
    pedidas: list[int] = []
    ctx = _ctx(tmp_path, _leitor_tcm(pedidas), meses=("2025-01", "2026-11"))
    mf.motor_tcm(ctx, "Goiânia")
    assert pedidas == list(range(1, 11))                 # não pede a 11ª: o servidor recusaria
    situacao, erro = _situacoes(ctx, "tcm")["decisoes"]
    assert situacao == "lido"
    assert erro == ("10 páginas lidas (a busca sem chave de API só pagina até o resultado 1000): as decisões "
                    "chegam a 2026-09-15, e o intervalo começa em 2025-01-01")

    # Se o servidor recusar antes (o limite mudou), as páginas lidas valem e a nota traz o motivo real.
    monkeypatch.setattr(tcm, "RESULTADOS_SEM_CHAVE", 2000)
    pedidas.clear()
    ctx = _ctx(tmp_path / "b", _leitor_tcm(pedidas, recusar_de=4), meses=("2025-01", "2026-11"))
    mf.motor_tcm(ctx, "Goiânia")
    assert pedidas == [1, 2, 3, 4]
    situacao, erro = _situacoes(ctx, "tcm")["decisoes"]
    assert situacao == "lido"
    assert erro.startswith("página 4: Sem chave de API, a busca pagina ate o resultado 1000.")
    assert ctx.banco.consultar("select count(*) from decisoes_controle where tribunal = 'TCM-GO'") == [(3 * 92,)]


# --- TCU: o motor pede na ordem pela data, a que deixa parar no começo do intervalo (requisito 154) ---

def test_tcu_motor_pede_na_ordem_pela_data_e_a_sondagem_prova_o_inicio_0_dela():
    from onisciente import sondagem
    q = _query(tcu.url_pesquisa("Goiânia", 0))
    assert q["ordenacao"] == ["DTRELEVANCIA desc, NUMACORDAOINT desc"] and q["inicio"] == ["0"]
    candidatos = sondagem.CANDIDATOS["d1_tcu"]
    assert tcu.url_pesquisa("Goiânia", 0) in candidatos
    # O inicio=0 que encerra a conexão nas sondagens é o da ordem por ano (a trava da sexta rodada o guarda).
    assert any(_query(u)["ordenacao"] == ["ANOACORDAO desc, NUMACORDAOINT desc"] for u in candidatos)


def test_sondagem_da_decima_primeira_rodada_guarda_a_pagina_inteira_e_pede_o_exportar():
    from onisciente import sondagem
    assert {"d1_fns", "d1_tcm"} <= sondagem.GRANDES
    assert sondagem.LIMITE_GRANDE > 691_235
    tcm_urls = sondagem.CANDIDATOS["d1_tcm"]
    exportar = [u for u in tcm_urls if "/jurisprudencia/exportar?" in u]
    assert len(exportar) == 1
    q = _query(exportar[0])
    assert q["formato"] == ["csv"] and q["municipio"] == ["GOIANIA"] and "page" not in q
    assert any(_query(u).get("ano_votacao") == ["2025"] and "/buscar?" in u for u in tcm_urls)
