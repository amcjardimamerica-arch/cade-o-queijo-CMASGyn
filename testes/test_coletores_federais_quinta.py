"""Bloco 5 (Frente D1), quinta rodada: as respostas reais da sondagem de 28/11/2026 (índice
``indice_d1_fns_d1_sancoes_d1_tcu_d1_tcm_d1_transferegov``).

Respostas reais em ``testes/dados/federais/``:
- ``fns_entidades_goiania_real.json``: a primeira página de ``consulta-detalhada/entidades`` com
  ``estado=GO&municipio=520870`` (10 de 191 entidades); nas duas pessoas físicas, nome e CPF trocados;
- ``fns_repasse_dia_20261126_real.json``: o repasse do dia 26/11/2026, inteiro;
- ``tcu_pesquisa_50_real.json``: a página da pesquisa do TCU com 50 acórdãos a partir do 50º, inteira.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from onisciente import historico
from onisciente.coletores import base, fns, tcu
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


def _entidades(total: int, paginas: int, dados: list[dict]) -> bytes:
    obj = json.loads(_bytes("fns_entidades_goiania_real.json"))
    obj["resultado"].update(total=total, totalPaginas=paginas, dados=dados)
    return json.dumps(obj, ensure_ascii=False).encode()


# --- FNS: as entidades do Município (requisitos 146 e 164) ----------------------------------------

def test_fns_entidades_reais_respeitam_o_filtro_e_mascaram_a_pessoa_fisica():
    linhas, total, paginas = fns.entidades(_bytes("fns_entidades_goiania_real.json"), "520870")
    assert (len(linhas), total, paginas) == (10, 191, 20)
    assert {l["municipio_ibge"] for l in linhas} == {"520870"}
    assert linhas[0] == {"cpf_cnpj": "13706030000160", "pessoa_fisica": 0, "nome": "ALENCAR E MOREIRA LTDA",
                         "esfera": "PRIVADA", "municipio_ibge": "520870", "sem_repasse": 0}
    pf = [l for l in linhas if l["pessoa_fisica"]]
    assert len(pf) == 2 and all(l["cpf_cnpj"].startswith("***") for l in pf)   # só o CPF mascarado do FNS
    # Uma entidade de outro Município quer dizer que o filtro foi ignorado: formato, não dado.
    outra = json.loads(_bytes("fns_entidades_goiania_real.json"))
    outra["resultado"]["dados"][3]["codigoMunicipioIBGE"] = "520140"
    try:
        fns.entidades(json.dumps(outra).encode(), "520870")
    except ValueError as e:
        assert "filtro do Município" in str(e)
    else:
        raise AssertionError("entidade de outro Município passou")
    assert fns.ENTIDADES not in fns.MODELOS_DE_REPASSE          # a lista não tem valor: não é repasse


def test_motor_fns_entidades_le_as_paginas_e_troca_o_ano(tmp_path):
    reais = json.loads(_bytes("fns_entidades_goiania_real.json"))["resultado"]["dados"]
    pedidos = []

    def leitor(url, **_):
        pedidos.append(url)
        if "consulta-detalhada/entidades" in url and "municipio=520870" in url:
            if "page=1&" in url:
                return _ok(url, _entidades(12, 2, reais))
            if "page=2&" in url:
                return _ok(url, _entidades(12, 2, [dict(reais[0], cpfCnpj="11222333000181", razaoSocial="X"),
                                                   dict(reais[1], cpfCnpj="44555666000199", razaoSocial="Y")]))
        return _nao(url)

    ctx = _ctx(tmp_path, leitor)
    ctx.banco.con.execute("INSERT INTO fns_entidades (ano, cpf_cnpj, nome) VALUES (2025, 'velha', 'velha')")
    mf.motor_fns_entidades(ctx, 5208707)
    assert ctx.banco.consultar("select count(*), sum(pessoa_fisica) from fns_entidades where ano = 2025") == [(12, 2)]
    assert ctx.banco.consultar("select count(*) from fns_entidades where cpf_cnpj = 'velha'") == [(0,)]
    assert not ctx.banco.consultar("select cpf_cnpj from fns_entidades where pessoa_fisica = 1 "
                                   "and cpf_cnpj not like '***%'")             # nenhum CPF inteiro guardado
    situacao, erro = _situacoes(ctx, "fns")["entidades 2025"]
    assert situacao == "lido" and erro is None
    assert all("count=100" in u and "estado=GO" in u for u in pedidos)


def test_motor_fns_entidades_com_filtro_ignorado_e_formato_e_mantem_a_tabela(tmp_path):
    outra = json.loads(_bytes("fns_entidades_goiania_real.json"))
    for d in outra["resultado"]["dados"]:
        d["codigoMunicipioIBGE"] = "520140"

    ctx = _ctx(tmp_path, lambda url, **_: _ok(url, json.dumps(outra).encode()))
    ctx.banco.con.execute("INSERT INTO fns_entidades (ano, cpf_cnpj, nome) VALUES (2025, 'anterior', 'a')")
    mf.motor_fns_entidades(ctx, 5208707)
    assert _situacoes(ctx, "fns")["entidades 2025"][0] == "formato"
    assert ctx.banco.consultar("select cpf_cnpj from fns_entidades") == [("anterior",)]


def test_chamada_do_fns_le_as_entidades_e_nao_as_toma_por_repasse(tmp_path):
    def leitor(url, **_):
        if "consulta-detalhada/entidades" in url:
            return _ok(url, _entidades(10, 1, json.loads(_bytes("fns_entidades_goiania_real.json"))
                                       ["resultado"]["dados"]))
        if "recuperar-data-ultimo-pagamento" in url:
            return _ok(url, _bytes("fns_ultimo_pagamento_real.json"))
        if "repasse-dia/consultar" in url:
            return _ok(url, b'{"resultado":[]}')
        return _nao(url)

    ctx = _ctx(tmp_path, leitor)
    mf.chamadas(ctx, ALVO, cnpjs=[])["fns"]()
    s = _situacoes(ctx, "fns")
    assert s["entidades 2025"][0] == "lido"
    assert s["2025"][0] == "nao_publicado"          # os repasses do ano não vieram da lista de entidades
    assert ctx.banco.consultar("select count(*) from repasses_fns") == [(0,)]


def test_fns_repasse_dia_real_de_26_11_2026_fecha():
    nos = fns.arvore_repasse_dia(_bytes("fns_repasse_dia_20261126_real.json"), "2026-11-26")
    assert len(nos) == 17
    blocos = {n["nome"]: n["valor_total"] for n in nos if n["nivel"] == 0}
    assert blocos["Estruturação da Rede de Serviços Públicos de Saúde"] == 19_204_116.0
    assert blocos["OUTRAS TRANSFERÊNCIAS"] == 3_932_510.08
    assert round(sum(n["valor_total"] for n in nos if n["folha"]), 2) == round(sum(blocos.values()), 2)


# --- TCU: a pesquisa de 50 em 50 (requisito 154) --------------------------------------------------

def test_tcu_pesquisa_real_de_50_e_a_paginacao_de_50_em_50(tmp_path):
    pagina = tcu.ler(_bytes("tcu_pesquisa_50_real.json"), pesquisa=True)
    assert len(pagina) == 50 and sum(d["sobre_goiania"] for d in pagina) == 42
    pedidos = []

    def leitor(url, **_):
        pedidos.append(url)
        if url == tcu.url_pesquisa("Goiânia", 0):
            return _ok(url, _bytes("tcu_pesquisa_50_real.json"))
        if url == tcu.url_pesquisa("Goiânia", 50):
            return _ok(url, _bytes("tcu_pesquisa_real.json"))    # cinco: a última página
        return _nao(url)

    ctx = _ctx(tmp_path, leitor, meses=("2020-01", "2026-11"))
    mf.motor_tcu(ctx, "Goiânia")
    feitas = [u for u in pedidos if u.startswith(tcu.PESQUISA)]
    assert len(feitas) == 2 and all("quantidade=50" in u for u in feitas)
    assert "inicio=50" in feitas[1]
    assert _situacoes(ctx, "tcu")["pesquisa"][0] == "lido"


def test_tcu_pagina_seguinte_que_cai_guarda_a_anterior_e_anota(tmp_path):
    def leitor(url, **_):
        if url == tcu.url_pesquisa("Goiânia", 0):
            return _ok(url, _bytes("tcu_pesquisa_50_real.json"))
        if url.startswith(tcu.PESQUISA):
            return base.Leitura(False, url, erro="URLError: [Errno 104] Connection reset by peer")
        return _nao(url)

    ctx = _ctx(tmp_path, leitor, meses=("2020-01", "2026-11"))
    mf.motor_tcu(ctx, "Goiânia")
    situacao, erro = _situacoes(ctx, "tcu")["pesquisa"]
    assert situacao == "lido" and "Connection reset" in erro
    assert ctx.banco.consultar("select count(*) from decisoes_controle where tribunal = 'TCU' "
                               "and sobre_goiania = 1") == [(42,)]


# --- Sondagem da sexta rodada ---------------------------------------------------------------------

def test_sondagem_da_quinta_rodada_e_o_corpo_do_erro(tmp_path, monkeypatch):
    from onisciente import sondagem
    c = {k: [u if isinstance(u, str) else u[0] for u in v] for k, v in sondagem.CANDIDATOS.items()
         if k.startswith("d1_")}
    assert any(u.endswith("detalhada/controllers/acaoController.js") for u in c["d1_fns"])
    assert any("quantidade=50&inicio=100" in u for u in c["d1_tcu"])
    assert any("/jurisprudencia/assets/" in u for u in c["d1_tcm"])
    # A mensagem do 400/500 fica guardada para as chaves d1_ (a do FNS não foi guardada na rodada 5).
    monkeypatch.setattr(sondagem, "PASTA", tmp_path)
    url = "https://consultafns.saude.gov.br/recursos/repasse-dia/detalhar-pagamento-dia?ano=2025"
    erro = base.Leitura(False, url, b'{"mensagem":"parametro codigoBloco obrigatorio"}', erro="HTTP 400", http=400)
    info = sondagem._guardar("d1_fns", url, erro)
    assert "codigoBloco obrigatorio" in (tmp_path / info["arquivo"]).read_text(encoding="utf-8")
    info = sondagem._guardar("outra", url, erro)
    assert "codigoBloco" not in (tmp_path / info["arquivo"]).read_text(encoding="utf-8")
