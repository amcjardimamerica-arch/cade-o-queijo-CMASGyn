"""Bloco 5 (Frente D1), sétima rodada: as respostas da sondagem de 28/11/2026 (índice
``indice_d1_fns_d1_sancoes_d1_tcu_d1_tcm_d1_transferegov``, sobrescrito).

Respostas reais em ``testes/dados/federais/``:
- ``fns_detalhe_acao_fundo_2025_real.json``: as 40 ações do Fundo Municipal de Saúde de Goiânia em 2025,
  inteiras;
- ``fns_detalhe_pagamento_fundo_2025_p1_real.json``: a página 1 de 7 das ordens do Fundo em 2025 (``acoes``
  vazio, 100 de 676); os números das contas correntes foram trocados por fictícios;
- ``fns_entidades_goiania_2024_real.json``: a página 1 das entidades de Goiânia em 2024 (100 de 197); nas
  pessoas físicas, nome e CPF trocados;
- ``tcu_pesquisa_inicio100_real.json``: a pesquisa do TCU com ``inicio=100`` e 50 por página, que respondeu.

A resposta de ``buscar`` da jurisprudência do TCM-GO ainda não foi vista: a deste teste é fictícia,
montada com os campos que a tela (``jurisprudencia-page-*.js``, real) usa.
"""

from __future__ import annotations

import json
import urllib.parse
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from onisciente import historico
from onisciente.coletores import base, fns, tcm, tcu
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


def _com_o_fundo(ctx):
    ctx.banco.con.execute("INSERT INTO fns_entidades VALUES (2025, ?, 0, 'FUNDO MUNICIPAL DE SAUDE', 'MUNICIPAL', "
                          "'520870', 0)", (FUNDO,))


def _query(url: str) -> dict:
    return urllib.parse.parse_qs(urllib.parse.urlparse(url).query, keep_blank_values=True)


# --- FNS: o valor pago ao Fundo Municipal de Saúde (requisitos 146 e 164) -------------------------

def test_fns_entidades_de_2024_reais_respeitam_o_municipio():
    linhas, total, paginas = fns.entidades(_bytes("fns_entidades_goiania_2024_real.json"), "520870")
    assert (len(linhas), total, paginas) == (100, 197, 2)
    assert all(l["municipio_ibge"] == "520870" for l in linhas)
    assert all(l["cpf_cnpj"].startswith("***") for l in linhas if l["pessoa_fisica"])


def test_fns_acoes_reais_do_fundo_fecham_com_o_total_geral():
    acoes, total = fns.acoes(_bytes("fns_detalhe_acao_fundo_2025_real.json"))
    assert (len(acoes), total) == (40, 40)
    assert acoes[0] == {"id": "68903", "bloco": "Estruturação da Rede de Serviços Públicos de Saúde",
                        "grupo": "ATENÇÃO ESPECIALIZADA",
                        "componente": "ESTRUTURAÇÃO DE UNIDADES DE ATENÇÃO ESPECIALIZADA EM SAÚDE",
                        "descricao": "EMENDA - ESTRUTURAÇÃO DE UNIDADES DE ATENÇÃO ESPECIALIZADA EM SAÚDE",
                        "valor_total": 1141400.0, "valor_desconto": 0.0, "valor_liquido": 1141400.0}
    # O desconto vem de valorDescontoTotal e a soma das ações é o total geral que a resposta declara.
    assert round(sum(a["valor_total"] for a in acoes), 2) == 1030381073.26
    assert round(sum(a["valor_desconto"] for a in acoes), 2) == 69478347.99
    assert round(sum(a["valor_liquido"] for a in acoes), 2) == 960902725.27


def test_fns_pagamentos_reais_dizem_a_acao_o_mes_e_o_documento():
    ordens, total = fns.pagamentos(_bytes("fns_detalhe_pagamento_fundo_2025_p1_real.json"))
    assert (len(ordens), total) == (100, 676)
    ids = {a["id"] for a in fns.acoes(_bytes("fns_detalhe_acao_fundo_2025_real.json"))[0]}
    assert all(o["programa_id"] in ids for o in ordens)                  # cada ordem diz a sua ação
    descontada = ordens[0]                                               # valor inteiro descontado
    assert (descontada["mes"], descontada["data"], descontada["ordem_bancaria"], descontada["valor_liquido"]) == (
        "2025-01", None, "", 0.0)
    assert descontada["situacao"].endswith("parcela 10/12 em 2025")
    ob = next(o for o in ordens if o["ordem_bancaria"] == "2025OB000028")
    assert (ob["data"], ob["mes"], ob["competencia"], ob["programa_id"], ob["valor_liquido"]) == (
        "2025-01-02", "2025-01", "2024-12", "67918", 3037784.71)
    fora = [o for o in ordens if not o["fundo_a_fundo"]]                 # documento PF, conta UNICA
    assert len(fora) == 26 and all(o["conta"] == "UNICA" and "PF" in o["ordem_bancaria"] for o in fora)
    assert {o["mes"] for o in ordens} == {"2025-01", "2025-02", "2025-03"}
    assert [fns.competencia(t) for t in ("NOV de 2024", "12 em 2024", "01/12 em 2025", "Única em 2024")] == [
        "2024-11", "2024-12", None, None]


def _leitor_real(pedidos, pagamentos: bytes):
    def leitor(url, **_):
        pedidos.append(url)
        q = _query(url)
        if "detalhe-acao" in url and q.get("cpfCnpjUg") == [FUNDO]:
            return _ok(url, _bytes("fns_detalhe_acao_fundo_2025_real.json"))
        if "detalhe-pagamento" in url and q.get("acoes") == [""] and q.get("page") == ["1"]:
            return _ok(url, pagamentos)
        return _nao(url)
    return leitor


def test_motor_fns_detalhe_com_as_respostas_reais_le_as_ordens_de_uma_vez(tmp_path):
    # A página real com o total reduzido às 100 ordens lidas (as outras 6 páginas não foram sondadas).
    pagina = json.loads(_bytes("fns_detalhe_pagamento_fundo_2025_p1_real.json"))
    pagina["resultado"]["total"], pagina["resultado"]["totalPaginas"] = 100, 1
    pedidos: list[str] = []
    ctx = _ctx(tmp_path, _leitor_real(pedidos, json.dumps(pagina).encode()))
    _com_o_fundo(ctx)
    mf.motor_fns_detalhe(ctx, 5208707)
    assert not any(_query(u).get("acoes", [""]) != [""] for u in pedidos)     # nenhuma leitura por ação
    assert ctx.banco.consultar("select count(*) from fns_acoes") == [(40,)]
    assert ctx.banco.consultar("select pago from fns_acoes where id = '68903'") == [(1141400.0,)]
    # Só as 74 ordens fundo a fundo vão para repasses_fns, com a ação da lista e o CNPJ do Fundo.
    assert ctx.banco.consultar("select count(*), round(sum(valor_liquido), 2), count(distinct cnpj) "
                               "from repasses_fns") == [(74, 170471265.78, 1)]
    assert ctx.banco.consultar("select programa from repasses_fns where ordem_bancaria = '2025OB000028'") == [
        (("ASSISTÊNCIA FINANCEIRA COMPLEMENTAR AOS ESTADOS, DF E MUNICÍPIOS P/ O PAG DO PISO SALARIAL DOS "
          "PROFISSIONAIS DA ENFERMAGEM"),)]
    situacao, erro = _situacoes(ctx, "fns")["detalhe 2025"]
    assert situacao == "lido"
    assert "26 pagamentos fora do fundo a fundo" in erro and "não fecham com a ação" in erro


def test_motor_fns_detalhe_com_a_listagem_pela_metade_nao_grava_ordens(tmp_path):
    pedidos: list[str] = []
    ctx = _ctx(tmp_path, _leitor_real(pedidos, _bytes("fns_detalhe_pagamento_fundo_2025_p1_real.json")))
    _com_o_fundo(ctx)
    mf.motor_fns_detalhe(ctx, 5208707)                    # a página 2 de 7 não vem
    assert any(_query(u).get("page") == ["2"] for u in pedidos if "detalhe-pagamento" in u)
    assert ctx.banco.consultar("select count(*) from repasses_fns") == [(0,)]
    situacao, _erro = _situacoes(ctx, "fns")["detalhe 2025"]
    assert situacao != "lido"


# --- TCU: a ordem da pesquisa (requisito 154) ------------------------------------------------------

def test_tcu_pesquisa_real_vem_da_sessao_mais_nova_e_passa_de_100():
    datas = []
    for nome, inicio in (("tcu_pesquisa_50_real.json", 50), ("tcu_pesquisa_inicio100_real.json", 100)):
        assert json.loads(_bytes(nome))["inicio"] == inicio
        datas += [d["data"] for d in tcu.ler(_bytes(nome), pesquisa=True)]
    assert len(datas) == 100 and None not in datas
    assert datas == sorted(datas, reverse=True)           # a ordem padrão já é cronológica, da mais nova
    assert datas[50] == "2024-04-02" and datas[-1] == "2022-10-26"   # inicio=100 respondeu nesta rodada
    assert "DTRELEVANCIA+desc" in tcu.url_pesquisa("Goiânia")


# --- TCM-GO: a pesquisa da jurisprudência (requisito 154) -------------------------------------------

def _busca(dados, has_next=False) -> bytes:
    return json.dumps({"data": dados, "pagination": {"page": 1, "page_size": 100, "total_pages": 2 if has_next else 1,
                                                     "has_next": has_next, "has_prev": False},
                       "busca_id": "x"}).encode()


DECISOES = [
    {"document_id": "doc-1", "numero_acordao": "00123/2025", "ano_votacao": 2025, "data_sessao": "2025-03-12",
     "tipo_decisao": "Acórdão", "numero_processo": "01234/24", "assunto": "Denúncia",
     "ementa": "Denúncia sobre pregão do Fundo Municipal de Saúde.", "resultado": "Procedente",
     "conselheiro_relator": "CONSELHEIRO FICTICIO", "orgao_julgador": "1ª Turma",
     "entidade_fiscalizada": "FUNDO MUNICIPAL DE SAÚDE DE GOIÂNIA"},
    {"document_id": "doc-2", "numero_acordao": "00456/2025", "ano_votacao": 2025, "data_sessao": "2025-02-10",
     "tipo_decisao": "Parecer Prévio", "numero_processo": "05678/24", "ementa": "Contas de governo.",
     "conselheiro_relator": "CONSELHEIRA FICTICIA", "orgao_julgador": "Tribunal Pleno",
     "entidade_fiscalizada": "PREFEITURA MUNICIPAL DE APARECIDA DE GOIÂNIA"},
    {"document_id": "doc-3", "numero_acordao": "", "ano_votacao": None, "ementa": "Sem número."},
]


def test_tcm_jurisprudencia_pela_api_da_tela():
    q = _query(tcm.url_jurisprudencia("Goiânia", 2))
    assert tcm.url_jurisprudencia().startswith(
        "https://virtual.tcmgo.tc.br/jurisprudencia/api/v1/acordao/jurisprudencia/buscar?")
    assert q == {"texto": ["Goiânia"], "page": ["2"], "page_size": ["100"], "sort_by": ["data_sessao"],
                 "sort_order": ["desc"]}
    decisoes, mais = tcm.jurisprudencia(_busca(DECISOES, has_next=True))
    assert mais and len(decisoes) == 2                    # sem número não vira decisão
    d = decisoes[0]
    assert (d["chave"], d["data"], d["relator"], d["colegiado"], d["processo"], d["sobre_goiania"]) == (
        "TCMGO-acordao-123-2025", "2025-03-12", "CONSELHEIRO FICTICIO", "1ª Turma", "01234/24", 1)
    assert d["url"].endswith("/jurisprudencia/pdf/doc-1") and "Resultado: Procedente" in d["sumario"]
    assert decisoes[1]["tipo"] == "Parecer prévio" and decisoes[1]["sobre_goiania"] == 0   # Aparecida
    for torto in (b'{"items": []}', b"<html>erro</html>", b"[]"):
        try:
            tcm.jurisprudencia(torto)
        except ValueError:
            pass
        else:
            raise AssertionError("formato mudado passou")


def test_motor_tcm_le_a_api_com_o_cabecalho_e_so_cai_nos_candidatos_se_ela_falhar(tmp_path):
    cabecalhos = {}

    def leitor(url, **kw):
        # Rodada 12 (28/11/2026): a sondagem 079a72d provou o exportar em CSV, que o motor agora lê primeiro.
        # Este servidor de teste é o de antes dele: recusa o exportar (404) e a trava segue provando a busca
        # paginada, que ficou de reserva. As asserções não mudaram.
        if "/exportar?" in url:
            return _nao(url)
        if url.startswith(tcm.JURISPRUDENCIA):
            cabecalhos.update(kw.get("cabecalhos") or {})
            return _ok(url, _busca(DECISOES))
        raise AssertionError(f"candidato lido com a API no ar: {url}")

    ctx = _ctx(tmp_path, leitor)
    mf.motor_tcm(ctx, "Goiânia")
    assert cabecalhos == {"X-Cliente": "portal"}
    assert ctx.banco.consultar("select chave from decisoes_controle where tribunal = 'TCM-GO'") == [
        ("TCMGO-acordao-123-2025",)]
    assert _situacoes(ctx, "tcm")["decisoes"] == ("lido", None)

    candidatos = []

    def sem_api(url, **_):
        if url.startswith(tcm.JURISPRUDENCIA):
            return _nao(url, 403)
        candidatos.append(url)
        return _nao(url)

    ctx2 = _ctx(tmp_path / "b", sem_api)
    mf.motor_tcm(ctx2, "Goiânia")
    situacao, erro = _situacoes(ctx2, "tcm")["decisoes"]
    assert candidatos and situacao == "nao_publicado" and erro.startswith("jurisprudência: HTTP 403")


# --- Sondagem da oitava rodada -----------------------------------------------------------------------

def test_sondagem_da_setima_rodada_pede_o_resto_das_ordens_e_a_busca_do_tcm():
    from onisciente import sondagem
    c = {k: [u if isinstance(u, str) else u[0] for u in v] for k, v in sondagem.CANDIDATOS.items()
         if k.startswith("d1_")}
    pags = [_query(u) for u in c["d1_fns"] if "detalhe-pagamento" in u]
    assert any(q["page"] == ["7"] and q["acoes"] == [""] for q in pags)
    assert any(q["acoes"] == ["61659"] for q in pags)
    assert any("/jurisprudencia/buscar?" in u for u in c["d1_tcm"])
    assert any(u.endswith("/jurisprudencia/filtros") for u in c["d1_tcm"])
    assert any("inicio=1300" in u for u in c["d1_tcu"])
    url = next(u for u in c["d1_tcm"] if "/buscar?" in u)
    assert next(v for k, v in sondagem.CABECALHOS.items() if url.startswith(k)) == {"X-Cliente": "portal"}
