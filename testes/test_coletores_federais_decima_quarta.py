"""Bloco 5 (Frente D1), décima quarta rodada: a sondagem d1_tcm d1_tcu de 28/11/2026, 09:11Z (run 46129272224,
índice ``indice_d1_tcm_d1_tcu``), conferida com a coleta 6c474b1.

Respostas reais em ``testes/dados/federais/``:
- ``tcm_jurisprudencia_buscar_municipio_goiania_2024_p1_real.json`` e ``..._2026_p1_real.json``: a página 1 da
  busca da jurisprudência do TCM-GO com municipio=GOIANIA e ano_votacao=2024 (total_items 747, 8 páginas) e
  2026 (total_items 851, 9 páginas), com as 100 decisões reduzidas a número, data, entidade, órgão, relator e
  resultado, como a de 2025 (total_items 918) da décima segunda rodada.

Na coleta 6c474b1 a exportação guardou 732 decisões de Goiânia em 2024 e 804 em 2026. As 99 de Goiânia da página
1 de 2024 e as 92 da de 2026 estão todas entre elas, e as outras da página (consórcios, o próprio TCM, o MP)
ficaram de fora; a sessão mais nova de 2026 é a mesma nas duas (22/10/2026).
"""

from __future__ import annotations

import json
import urllib.parse
from datetime import date
from pathlib import Path

from onisciente import historico, sondagem
from onisciente.coletores import base, tcm, tcu
from onisciente.coletores import motores_federais as mf

DADOS = Path(__file__).parent / "dados" / "federais"
BUSCAR = {2024: "tcm_jurisprudencia_buscar_municipio_goiania_2024_p1_real.json",
          2025: "tcm_jurisprudencia_buscar_municipio_goiania_2025_p1_real.json",
          2026: "tcm_jurisprudencia_buscar_municipio_goiania_2026_p1_real.json"}
EXPORTAR_2025 = "tcm_jurisprudencia_exportar_goiania_2025_real.csv"


def _bytes(nome: str) -> bytes:
    return (DADOS / nome).read_bytes()


def _ok(url, conteudo: bytes) -> base.Leitura:
    return base.Leitura(True, url, conteudo, http=200)


def _nao(url, codigo=404) -> base.Leitura:
    return base.Leitura(False, url, erro=f"HTTP {codigo}", http=codigo)


def _ctx(tmp_path, leitor, meses=("2024-11", "2026-11")):
    banco = historico.Banco(tmp_path / "h.db")
    mf.preparar(banco)
    return historico.Contexto(banco, historico.meses(*meses), date(2026, 11, 28), ler_url=leitor,
                              dormir=lambda s: None, pausa=0)


def _query(url):
    return urllib.parse.parse_qs(urllib.parse.urlsplit(url).query, keep_blank_values=True)


def _situacoes(ctx, motor):
    return {a: (s, e) for a, s, e in ctx.banco.consultar(
        "select alvo, situacao, erro from fontes_federais where motor = ?", motor)}


def _contagem(ctx):
    return dict(ctx.banco.consultar(
        "select ano, count(*) from decisoes_controle where tribunal = 'TCM-GO' group by ano"))


# --- TCM-GO: a busca de cada ano cabe no limite de 1000 sem chave (requisito 154) ---------------------

def test_busca_real_de_cada_ano_cabe_no_limite_sem_chave_e_separa_goiania():
    esperado = {2024: (747, 8, 99), 2025: (918, 10, 96), 2026: (851, 9, 92)}
    for ano, (total, paginas, de_goiania) in esperado.items():
        bruto = _bytes(BUSCAR[ano])
        paginacao = json.loads(bruto)["pagination"]
        assert (paginacao["total_items"], paginacao["total_pages"]) == (total, paginas)
        assert total <= tcm.RESULTADOS_SEM_CHAVE                    # o ano vem inteiro sem chave de API
        decisoes, mais = tcm.jurisprudencia(bruto)
        assert mais and len(decisoes) == 100
        assert {d["ano"] for d in decisoes} == {ano}
        assert all(d["data"].startswith(str(ano)) for d in decisoes)
        assert sum(d["sobre_goiania"] for d in decisoes) == de_goiania
        # De Goiânia são as da entidade GOIANIA (GOIANIA, GOIANIA - IPSM, ...); consórcios, o TCM e o MP não.
        entidades = [r["entidade_fiscalizada"] for r in json.loads(bruto)["data"]]
        assert [bool(d["sobre_goiania"]) for d in decisoes] == [e.split(" - ")[0] == "GOIANIA" for e in entidades]
    # A busca de um ano pede o filtro como a tela manda.
    q = _query(tcm.url_jurisprudencia("", 3, municipio="GOIANIA", ano=2024))
    assert (q["municipio"], q["ano_votacao"], q["page"], q["texto"]) == (["GOIANIA"], ["2024"], ["3"], [""])
    assert "ano_votacao" not in _query(tcm.url_jurisprudencia("", 1, municipio="GOIANIA"))


def _pagina_2_de_2024() -> bytes:
    """A página 1 real de 2024 com outros números de acórdão, como a última página (has_next falso)."""
    obj = json.loads(_bytes(BUSCAR[2024]))
    for i, r in enumerate(obj["data"]):
        r["numero_acordao"] = f"{90000 + i}/24"
        r["document_id"] = f"pagina-2-{i}"
    obj["pagination"] = {**obj["pagination"], "page": 2, "has_next": False, "has_prev": True}
    return json.dumps(obj, ensure_ascii=False).encode()


def test_motor_tcm_cobre_o_ano_sem_exportacao_pela_busca_daquele_ano(tmp_path):
    pedidos: list[dict] = []
    so_cabecalho = _bytes(EXPORTAR_2025).decode("utf-8-sig").splitlines()[0].encode()

    def leitor(url, **kw):
        assert kw.get("cabecalhos") == {"X-Cliente": "portal"}
        q = _query(url)
        pedidos.append(q)
        if "/exportar?" in url:
            if q["ano_votacao"] == ["2024"]:
                return _nao(url, 503)
            return _ok(url, _bytes(EXPORTAR_2025) if q["ano_votacao"] == ["2025"] else so_cabecalho)
        assert q.get("ano_votacao") == ["2024"], "a busca geral não devia ser pedida"
        return _ok(url, _bytes(BUSCAR[2024]) if q["page"] == ["1"] else _pagina_2_de_2024())

    ctx = _ctx(tmp_path, leitor)
    mf.motor_tcm(ctx, "Goiânia")
    buscas = [q for q in pedidos if "page" in q]
    assert [(q["ano_votacao"], q["municipio"], q["page"]) for q in buscas] == [
        (["2024"], ["GOIANIA"], ["1"]), (["2024"], ["GOIANIA"], ["2"])]
    assert _contagem(ctx) == {2024: 99 + 99, 2025: 873}
    situacao, erro = _situacoes(ctx, "tcm")["decisoes"]
    assert situacao == "lido"
    assert erro == ("a exportação não veio em 1 de 3 anos (2024: HTTP 503); 2024 veio pela busca do ano "
                    "(198 decisões de Goiânia)")
    via = ctx.banco.consultar("select via from fontes_federais where motor = 'tcm' and alvo = 'decisoes'")
    assert via == [(tcm.JURISPRUDENCIA + "exportar",)]


def test_motor_tcm_nao_da_o_ano_por_coberto_se_o_filtro_do_ano_nao_valeu(tmp_path):
    so_cabecalho = _bytes(EXPORTAR_2025).decode("utf-8-sig").splitlines()[0].encode()
    pedidos: list[dict] = []

    def leitor(url, **_):
        q = _query(url)
        pedidos.append(q)
        if "/exportar?" in url:
            if q["ano_votacao"] == ["2024"]:
                return _nao(url, 503)
            return _ok(url, _bytes(EXPORTAR_2025) if q["ano_votacao"] == ["2025"] else so_cabecalho)
        return _ok(url, _bytes(BUSCAR[2025]))                    # um servidor que ignora o ano

    ctx = _ctx(tmp_path, leitor)
    mf.motor_tcm(ctx, "Goiânia")
    assert any("page" in q and "ano_votacao" not in q for q in pedidos)   # caiu na busca geral
    assert _contagem(ctx) == {2025: 873}                       # nada de 2025 contado em dobro
    situacao, erro = _situacoes(ctx, "tcm")["decisoes"]
    assert situacao == "lido"
    assert erro.startswith("a exportação não veio em 1 de 3 anos (2024: HTTP 503); a busca paginada cobriu o "
                           "intervalo; a busca do ano não fechou (2024: o filtro ano_votacao=2024 não valeu)")


# --- TCU: a sondagem pede as três páginas dos dados abertos em seguida (requisito 154) -----------------

def test_sondagem_pede_as_tres_paginas_dos_dados_abertos_do_tcu_como_o_motor():
    candidatos = sondagem.CANDIDATOS["d1_tcu"]
    paginas = [tcu.url_dados_abertos(i) for i in (0, 100, 200)]
    assert all(p in candidatos for p in paginas)
    posicoes = [candidatos.index(p) for p in paginas]
    assert posicoes == sorted(posicoes) and posicoes[-1] - posicoes[0] == 2   # uma atrás da outra
