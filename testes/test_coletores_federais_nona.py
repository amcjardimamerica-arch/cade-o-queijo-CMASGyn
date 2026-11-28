"""Bloco 5 (Frente D1), nona rodada: o que a coleta de 28/11/2026 (d532c1d) mostrou.

- FNS: a listagem das ordens do Fundo (``detalhe-pagamento`` com ``acoes`` vazio) veio em 7 páginas
  diferentes que somaram as 676 ordens do total, mas com ordens repetidas entre páginas e outras faltando.
  Em 2025 a ação 68058 somou 1.309.828,83 a mais que o total dela, exatamente duas ordens repetidas.
  As respostas destes testes são fictícias, no formato real (``fns_detalhe_pagamento_fundo_2025_p1_real``).
- TCM-GO: a busca da jurisprudência respondeu; 5 páginas (500 decisões) só cobriram 03/09 a 27/10/2026.
  O motor agora segue até a sessão mais antiga do intervalo.
- Sondagem: o fluxo passou as fontes num argumento só, separadas por vírgula, e a sondagem 1e36935 saiu
  vazia (``indice_d2_transweb_popup,d1_fns,d1_tcm,d1_tcu.json`` sem leituras).
"""

from __future__ import annotations

import json
import urllib.parse
from datetime import date

from onisciente import historico
from onisciente.coletores import base, fns, tcm
from onisciente.coletores import motores_federais as mf

FUNDO = "37623352000103"


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


# --- FNS: a paginação da listagem repete e perde ordens ---------------------------------------------

ACOES = [{"id": 61659, "descricao": "MAC", "valorTotal": 400.0, "valorDesconto": 0, "valorLiquido": 400.0,
          "blocoPacto": {"nome": "MANUTENCAO"}, "grupoAcao": {"nome": "MAC"}, "componenteBloco": {"nome": "MAC"}}]


def _ordem(n: int, valor: float = 100.0) -> dict:
    return {"id": {"processo": f"25000.{n}", "indicadorFundoAFundo": "S", "programaFundo": {"id": 61659}},
            "numeroDocumentoSiafi": f"00000{n}", "tipoDocumentoPagamento": "OB", "valorTotal": valor,
            "valorDescontoTotal": 0, "valorLiquido": valor, "codigoBanco": "001", "codigoAgencia": "1234",
            "contaCorrente": "99999", "anoPagamento": "2025", "mesPagamento": f"{n:02d}"}


def _pagina(dados, total, pagina=0) -> bytes:
    return json.dumps({"resultado": {"dados": dados, "pagina": pagina, "itensPorPagina": 2, "total": total,
                                     "totalPaginas": (total + 1) // 2}}).encode()


def _com_o_fundo(ctx):
    ctx.banco.con.execute("INSERT INTO fns_entidades VALUES (2025, ?, 0, 'FUNDO MUNICIPAL DE SAUDE', 'MUNICIPAL', "
                          "'520870', 0)", (FUNDO,))


def _leitor(paginas_por_leitura, pedidos):
    """``paginas_por_leitura``: para cada página da listagem, a lista do que vem a cada vez que é lida."""
    vezes: dict[str, int] = {}

    def leitor(url, **_):
        pedidos.append(url)
        q = _query(url)
        if "detalhe-acao" in url:
            return _ok(url, _pagina(ACOES, 1))
        if "detalhe-pagamento" in url and q["acoes"] == [""]:
            pagina = q["page"][0]
            respostas = paginas_por_leitura[pagina]
            i = vezes.get(pagina, 0)
            vezes[pagina] = i + 1
            return _ok(url, _pagina(respostas[min(i, len(respostas) - 1)], 4))
        if "detalhe-pagamento" in url and q["acoes"] == ["61659"]:
            return _ok(url, _pagina([_ordem(n) for n in (1, 2, 3, 4)], 4))
        return _nao(url)
    return leitor


def test_fns_ordem_repetida_em_outra_pagina_nao_conta_e_a_releitura_traz_a_que_faltou(tmp_path):
    # 1ª leitura: a página 2 repete a ordem 2 e perde a 4 (como na coleta); a releitura traz a 4.
    pedidos: list[str] = []
    paginas = {"1": [[_ordem(1), _ordem(2)]], "2": [[_ordem(2), _ordem(3)], [_ordem(3), _ordem(4)]]}
    ctx = _ctx(tmp_path, _leitor(paginas, pedidos))
    _com_o_fundo(ctx)
    mf.motor_fns_detalhe(ctx, 5208707)
    assert ctx.banco.consultar("select ordem_bancaria from repasses_fns order by ordem_bancaria") == [
        ("2025OB000001",), ("2025OB000002",), ("2025OB000003",), ("2025OB000004",)]
    assert ctx.banco.consultar("select pago from fns_acoes") == [(400.0,)]     # sem os 100 da repetida
    assert not any(_query(u).get("acoes") == ["61659"] for u in pedidos)        # a listagem bastou
    assert ctx.banco.consultar("select count(*) from coletas where alvo like '%releitura 1'") == [(2,)]
    assert _situacoes(ctx, "fns")["detalhe 2025"] == ("lido", None)


def test_fns_listagem_que_segue_repetindo_falha_e_as_ordens_vem_por_acao(tmp_path):
    pedidos: list[str] = []
    paginas = {"1": [[_ordem(1), _ordem(2)]], "2": [[_ordem(2), _ordem(3)]]}     # a 4 nunca vem
    ctx = _ctx(tmp_path, _leitor(paginas, pedidos))
    _com_o_fundo(ctx)
    mf.motor_fns_detalhe(ctx, 5208707)
    lidas = [u for u in pedidos if "detalhe-pagamento" in u and _query(u)["acoes"] == [""]]
    assert len(lidas) == 2 * (1 + mf.RELEITURAS_FNS)                             # leu e releu, e parou
    assert ctx.banco.consultar("select count(*), sum(valor_bruto) from repasses_fns") == [(4, 400.0)]
    situacao, erro = _situacoes(ctx, "fns")["detalhe 2025"]
    assert situacao == "lido"
    assert "a listagem de uma vez não serviu (3 de 4 linhas; a paginação repetiu 1 linhas" in erro
    assert "as ordens vêm por ação" in erro


def test_fns_linhas_iguais_na_mesma_pagina_contam(tmp_path):
    linhas = [{"a": 1}, {"a": 1}, {"a": 2}]
    ctx = _ctx(tmp_path, lambda url, **_: _ok(url, b"{}"))
    lidas, sit, erro = mf._paginas_fns(ctx, "x", "2025-01", lambda p: f"https://x/{p}",
                                       lambda c: (linhas, 3))
    assert (len(lidas), sit, erro) == (3, None, None)


def test_fns_listagem_curta_sem_repeticao_falha_sem_reler(tmp_path):
    pedidos: list[str] = []
    ctx = _ctx(tmp_path, lambda url, **_: (pedidos.append(url), _ok(url, b"{}"))[1])
    lidas, sit, erro = mf._paginas_fns(ctx, "x", "2025-01", lambda p: f"https://x/{p}",
                                       lambda c: ([], 5))
    assert (lidas, sit, erro) == (None, "falha", "0 de 5 linhas") and len(pedidos) == 1


# --- TCM-GO: até a sessão mais antiga do intervalo --------------------------------------------------

def _decisao(n: int, data: str, goiania=True) -> dict:
    return {"document_id": f"doc-{n}", "numero_acordao": f"{n:05d}/{data[:4]}", "ano_votacao": int(data[:4]),
            "data_sessao": data, "tipo_decisao": "Acórdão", "numero_processo": f"{n}/24",
            "ementa": "Denúncia.", "conselheiro_relator": "CONSELHEIRO FICTICIO", "orgao_julgador": "1ª Turma",
            "entidade_fiscalizada": "PREFEITURA DE GOIÂNIA" if goiania else "PREFEITURA DE ANÁPOLIS"}


def _busca(dados, pagina) -> bytes:
    return json.dumps({"data": dados, "pagination": {"page": pagina, "page_size": 100, "total_pages": 99,
                                                     "has_next": True}}).encode()


def test_tcm_segue_as_paginas_ate_passar_do_comeco_do_intervalo(tmp_path):
    datas = {1: ["2025-11-20", "2025-09-01"], 2: ["2025-06-10", "2025-02-03"], 3: ["2025-01-15", "2024-12-10"]}
    pedidas: list[int] = []

    def leitor(url, **_):
        # Rodada 12 (28/11/2026): a sondagem 079a72d provou o exportar em CSV, que o motor agora lê primeiro.
        # Este servidor de teste é o de antes dele: recusa o exportar (404) e a trava segue provando a busca
        # paginada, que ficou de reserva. As asserções não mudaram.
        if "/exportar?" in url:
            return _nao(url)
        if url.startswith(tcm.JURISPRUDENCIA):
            p = int(_query(url)["page"][0])
            pedidas.append(p)
            ds = datas.get(p, ["2024-01-01"])
            return _ok(url, _busca([_decisao(10 * p + i, d, goiania=i == 0) for i, d in enumerate(ds)], p))
        raise AssertionError(f"candidato lido com a API no ar: {url}")

    ctx = _ctx(tmp_path, leitor)
    mf.motor_tcm(ctx, "Goiânia")
    assert pedidas == [1, 2, 3]                       # parou na página que passou de 01/2025
    assert ctx.banco.consultar("select count(*) from decisoes_controle where tribunal = 'TCM-GO'") == [(3,)]
    assert _situacoes(ctx, "tcm")["decisoes"] == ("lido", None)


def test_tcm_no_teto_de_paginas_diz_ate_onde_chegou(tmp_path, monkeypatch):
    monkeypatch.setattr(tcm, "PAGINAS_JURISPRUDENCIA", 2)

    def leitor(url, **_):
        # Rodada 12 (28/11/2026): a sondagem 079a72d provou o exportar em CSV, que o motor agora lê primeiro.
        # Este servidor de teste é o de antes dele: recusa o exportar (404) e a trava segue provando a busca
        # paginada, que ficou de reserva. As asserções não mudaram.
        if "/exportar?" in url:
            return _nao(url)
        p = int(_query(url)["page"][0])
        return _ok(url, _busca([_decisao(p, f"2025-1{p}-01")], p))

    ctx = _ctx(tmp_path, leitor)
    mf.motor_tcm(ctx, "Goiânia")
    situacao, erro = _situacoes(ctx, "tcm")["decisoes"]
    assert situacao == "lido"
    assert erro == "2 páginas lidas (o teto): as decisões chegam a 2025-11-01, e o intervalo começa em 2025-01-01"


# --- Sondagem: a lista de fontes do fluxo -----------------------------------------------------------

def test_sondagem_aceita_as_fontes_separadas_por_virgula_e_aponta_as_desconhecidas(tmp_path, monkeypatch):
    from onisciente import sondagem
    assert sondagem.fontes_pedidas(["d2_transweb_popup,d1_fns,d1_tcm,d1_tcu"]) == [
        "d2_transweb_popup", "d1_fns", "d1_tcm", "d1_tcu"]
    assert sondagem.fontes_pedidas(["d1_fns d1_tcu", "d1_fns"]) == ["d1_fns", "d1_tcu"]
    assert sondagem.fontes_pedidas([""]) is None and sondagem.fontes_pedidas([]) is None
    lidas: list[str] = []
    monkeypatch.setattr(sondagem, "install_opener", lambda _o: None)   # o abridor com cookie é global
    monkeypatch.setattr(sondagem, "PASTA", tmp_path)
    monkeypatch.setattr(sondagem, "CANDIDATOS", {"d1_tcm": ["https://x.example/a"], "d1_fns": ["https://x.example/b"]})
    monkeypatch.setattr(sondagem, "ler", lambda url, **_: (lidas.append(url), _nao(url))[1])
    sondagem.sondar(sondagem.fontes_pedidas(["d1_tcm,d1_nada"]))
    assert lidas == ["https://x.example/a"]
    indice = json.loads((tmp_path / "indice_d1_tcm_d1_nada.json").read_text(encoding="utf-8"))
    assert len(indice["leituras"]) == 1 and indice["fontes_desconhecidas"] == ["d1_nada"]


def test_sondagem_da_nona_rodada_pede_as_676_ordens_numa_pagina():
    from onisciente import sondagem
    pags = [_query(u) for u in sondagem.CANDIDATOS["d1_fns"] if isinstance(u, str) and "detalhe-pagamento" in u]
    assert any(q["count"] == ["1000"] and q["acoes"] == [""] for q in pags)
    assert fns.url_detalhe("detalhe-pagamento", 5208707, 2025, FUNDO, 1).startswith(fns.DETALHE)
