"""Bloco 5 (Frente D1), décima terceira rodada: a coleta real dos motores federais de 28/11/2026 (run
46126887222, commit 6c474b1, intervalo 2024-11 a 2026-11).

- FNS: os 3 anos vieram inteiros pela consulta detalhada (526, 480 e 472 ordens), mas antes as 8 vias antigas
  de ``motor_fns`` falharam em todos os anos (12 chamadas sem DNS, 9 HTTP 400 e 3 HTTP 404) e deixaram uma
  linha "falha HTTP 400" por ano em ``fontes_federais``, que pesava na cobertura.
- TCM-GO: os 3 exportar vieram (2026, 2025 e 2024); o de 2025 é byte a byte o da sondagem 079a72d (sha256
  5bba7f5f...), e as 873 decisões de Goiânia gravadas em 2025 são as do CSV. O motor contou 2.411 e gravou
  2.409: a mesma chave veio duas vezes numa exportação.
- TCU: a pesquisa leu 150 (inicio=0, 50 e 100) e parou certo: a página de inicio=100 da coleta (sha256
  b6b7f274..., guardada em ``tcu_pesquisa_inicio100_coleta_real.json``, a mesma da sondagem 079a72d) vai de
  26/10/2022 a 02/04/2024, toda antes de 11/2024. Os dados abertos recusaram inicio=200 com HTTP 429 nas 3
  tentativas, em 106,6 s: as esperas sem Retry-After (15 + 30 + 60 s) mais as leituras.
"""

from __future__ import annotations

import json
import urllib.parse
from datetime import date
from pathlib import Path

from onisciente import historico
from onisciente.coletores import base, fns, tcm, tcu
from onisciente.coletores import motores_federais as mf
from onisciente.conferencias import federais

DADOS = Path(__file__).parent / "dados" / "federais"
ALVO = type("Alvo", (), {"ibge": 5208707, "uf": "GO", "municipio": "Goiânia"})()


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


# --- FNS: as vias antigas só para o ano que a consulta detalhada não trouxe (requisito 146) ---------

def _leitor_fns(antigas: list[str]):
    """As respostas reais de 2025 (entidades, ações e a página de 1000 ordens); as vias antigas, como na
    coleta, recusadas com HTTP 400."""
    def leitor(url, **_):
        q = _query(url)
        if ("consulta-detalhada/entidades" in url or "cpfCnpjUg" in q) and q.get("ano") != ["2025"]:
            return _nao(url)                                # só 2025 tem as respostas reais
        if "consulta-detalhada/entidades" in url:
            return _ok(url, _bytes("fns_entidades_goiania_real.json" if q["page"] == ["1"]
                                   else "fns_entidades_goiania_p2_real.json"))
        if "consulta-detalhada/detalhe-acao" in url and "cpfCnpjUg" in q:
            return _ok(url, _bytes("fns_detalhe_acao_fundo_2025_real.json"))
        if "consulta-detalhada/detalhe-pagamento" in url:
            return _ok(url, _bytes("fns_detalhe_pagamento_fundo_2025_count1000_real.json"))
        if "recuperar-data-ultimo-pagamento" in url:
            return _ok(url, _bytes("fns_ultimo_pagamento_real.json"))
        if "repasse-dia/consultar" in url:
            return _ok(url, b'{"resultado":[]}')
        antigas.append(url)
        return _nao(url, 400)
    return leitor


def test_chamada_do_fns_le_a_consulta_detalhada_antes_e_nao_tenta_as_vias_antigas_no_ano_lido(tmp_path):
    antigas: list[str] = []
    ctx = _ctx(tmp_path, _leitor_fns(antigas))
    mf.chamadas(ctx, ALVO, cnpjs=[])["fns"]()
    assert antigas == []                                   # nenhuma das 8 vias antigas foi tentada em 2025
    s = _situacoes(ctx, "fns")
    assert s["entidades 2025"][0] == "lido" and s["detalhe 2025"][0] == "lido"
    assert "2025" not in s                                 # sem a linha de falha das vias antigas
    assert ctx.banco.consultar("select count(*) from fns_acoes") == [(40,)]
    r = federais.conferir(ctx.banco.con, ate=date(2025, 12, 31))
    assert "fns" not in r.cobertura["problemas"]


def test_motor_fns_tira_a_linha_de_falha_do_ano_que_a_consulta_detalhada_leu(tmp_path):
    antigas: list[str] = []
    ctx = _ctx(tmp_path, _leitor_fns(antigas), meses=("2024-12", "2025-12"))
    mf.motor_fns_entidades(ctx, 5208707)
    mf.motor_fns_detalhe(ctx, 5208707)
    # A linha que a coleta 6c474b1 deixou (as vias antigas antes da consulta detalhada).
    mf._situacao(ctx, "fns", "2025", "falha", erro="HTTP 400")
    mf.motor_fns(ctx, 5208707)
    s = _situacoes(ctx, "fns")
    assert "2025" not in s
    # 2024 não tem resposta da consulta detalhada neste teste: as vias antigas são tentadas, como antes, e a
    # falha delas fica dita.
    assert s["2024"] == ("nao_publicado", "HTTP 400")     # a coleta, com o DNS caído também, dizia falha
    assert len(antigas) == len(fns.MODELOS_DE_REPASSE) and all("2024" in u for u in antigas)


# --- TCM-GO: a chave repetida numa exportação conta uma vez (requisito 154) -------------------------

def test_tcm_exportacao_com_chave_repetida_conta_uma_vez_e_fica_a_de_goiania(tmp_path):
    linhas = _bytes("tcm_jurisprudencia_exportar_goiania_2025_real.csv").decode("utf-8-sig").splitlines()
    de_goiania = next(l for l in linhas[1:] if ";GOIANIA - IPSM;" in l)
    outra = de_goiania.replace(";GOIANIA - IPSM;", ";TRIBUNAL DE CONTAS DOS MUNICIPIOS;")
    csv = "\n".join([linhas[0], outra, *linhas[1:], de_goiania]).encode()   # a chave 3 vezes
    so_cabecalho = linhas[0].encode()

    def leitor(url, **_):
        if "/exportar?" in url:
            return _ok(url, csv if "ano_votacao=2025" in url else so_cabecalho)
        return _nao(url)

    ctx = _ctx(tmp_path, leitor)
    mf.motor_tcm(ctx, "Goiânia")
    assert ctx.banco.consultar("select count(*) from decisoes_controle where tribunal = 'TCM-GO'") == [(873,)]
    assert ctx.banco.consultar("select registros from fontes_federais where motor = 'tcm' and alvo = 'decisoes'"
                               ) == [(873,)]
    chave = tcm.exportacao("\n".join([linhas[0], de_goiania]).encode())[0]["chave"]
    escolhida = [d for d in tcm.exportacao(csv) if d["chave"] == chave]
    assert len(escolhida) == 3 and escolhida[0]["sobre_goiania"] == 0
    assert mf._novas(escolhida, set())[0]["sobre_goiania"] == 1


# --- TCU: a pesquisa da coleta parou no começo do intervalo; o 429 tem mais uma leitura (requisito 154)

def test_tcu_pagina_da_coleta_de_inicio_100_e_toda_anterior_ao_intervalo(tmp_path):
    pagina = _bytes("tcu_pesquisa_inicio100_coleta_real.json")
    assert json.loads(pagina)["inicio"] == 100 and tcu.encontrados(pagina) == 1374
    datas = sorted(d["data"] for d in tcu.ler(pagina, pesquisa=True))
    assert (len(datas), datas[0], datas[-1]) == (50, "2022-10-26", "2024-04-02")
    pedidos: list[int] = []

    def leitor(url, **_):
        if not url.startswith(tcu.PESQUISA):
            return _nao(url)
        inicio = int(_query(url)["inicio"][0])
        pedidos.append(inicio)
        return _ok(url, pagina if inicio == 100 else _bytes("tcu_pesquisa_50_real.json"))

    ctx = _ctx(tmp_path, leitor, meses=("2024-11", "2026-11"))
    mf.motor_tcu(ctx, "Goiânia")
    assert pedidos == [0, 50, 100]                      # as 3 páginas da coleta, e nada falta do intervalo
    assert _situacoes(ctx, "tcu")["pesquisa"] == ("lido", None)


def _pagina_de_dados_abertos(inicio: int) -> bytes:
    """100 acórdãos no formato real dos dados abertos (o real repetido com chaves novas), de 11/2026."""
    reais = json.loads(_bytes("tcu_dados_abertos_real.json"))
    pagina = []
    for i in range(100):
        r = dict(reais[i % len(reais)])
        r["key"] = f"ACORDAO-COMPLETO-{inicio + i}"
        r["numeroAcordao"] = str(9000 + inicio + i)
        pagina.append(r)
    return json.dumps(pagina).encode()


def test_tcu_dados_abertos_429_espera_dois_minutos_e_le_mais_uma_vez(tmp_path):
    esperas: list[float] = []
    vezes: dict[int, int] = {}

    def leitor(url, liberar_depois=None, **_):
        if not url.startswith(tcu.DADOS_ABERTOS):
            return _nao(url)
        inicio = int(_query(url)["inicio"][0])
        vezes[inicio] = vezes.get(inicio, 0) + 1
        if inicio == 200 and (liberar_depois is None or vezes[inicio] <= liberar_depois):
            return _nao(url, 429)                       # sem Retry-After, como na coleta
        if inicio >= 300:
            return _ok(url, b"[]")
        return _ok(url, _pagina_de_dados_abertos(inicio))

    ctx = _ctx(tmp_path, leitor, meses=("2026-11", "2026-11"), dormir=esperas.append)
    mf.motor_tcu(ctx, "Goiânia")
    assert vezes[200] == 6                              # 3 tentativas, 2 minutos, mais 3
    assert esperas.count(tcu.ESPERA_429) == 1 and tcu.ESPERA_429 == 120
    situacao, erro = _situacoes(ctx, "tcu")["dados_abertos"]
    assert situacao in ("falha", "vazio", "lido")
    assert erro == "HTTP 429 (sem Retry-After); a nova leitura depois de 120 s também foi recusada"

    # Se a recusa passar nos 2 minutos, a leitura segue.
    vezes.clear()
    ctx = _ctx(tmp_path / "b", lambda url, **kw: leitor(url, liberar_depois=3, **kw), meses=("2026-11", "2026-11"))
    mf.motor_tcu(ctx, "Goiânia")
    assert vezes[200] == 4 and vezes.get(300) == 1
    assert _situacoes(ctx, "tcu")["dados_abertos"][1] is None
