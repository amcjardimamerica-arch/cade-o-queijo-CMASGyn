"""Travas do rastreio por hash (frente H, 28/11/2026).

Pedido da titular: "Ao coletar as informações gere um código hash para rastreio dos dados e validação
de cada informação obtida". Cada trava falha se uma das garantias deixar de valer: toda resposta com
o seu SHA-256 e toda coleta com o hash da requisição; todo registro com o seu hash e a ligação com a
resposta de origem; cada rodada encadeada na anterior; a verificação apontando a linha, a rodada ou o
elo alterado; o banco antigo migrado sem perder linhas; o parecer com o hash em cada achado.
"""

from __future__ import annotations

import json
import sqlite3
import urllib.request
from datetime import date
from pathlib import Path

import pytest

from onisciente import historico, rastreio
from onisciente.coletores import base
from onisciente.nucleo.custodia import Original, impressao
from onisciente.nucleo.indicios import Familia, emitir

HOJE = date(2026, 11, 26)


def _ler_generico(url: str, **_):
    """Responde tudo sem a impressão da custódia (o sha256 tem de sair dos bytes): 200 com JSON vazio,
    404 com corpo para algumas fontes, 204 vazio para outras, e falha de rede para o resto do PNCP."""
    if "fora-do-ar" in url:
        return base.Leitura(False, url, erro="URLError: sem rede")
    if "siconfi" in url and "rgf" in url:
        return base.Leitura(False, url, b'{"erro": "nao encontrado"}', erro="HTTP 404", http=404)
    if "queridodiario" in url:
        return base.Leitura(True, url, b"", http=204)
    return base.Leitura(True, url, b'{"items": [], "data": [], "hasMore": false, "count": 0}', http=200)


@pytest.fixture()
def sem_rede(monkeypatch):
    def proibido(*a, **k):
        raise AssertionError("a trava não pode sair para a rede")
    monkeypatch.setattr(urllib.request, "urlopen", proibido)
    from onisciente.coletores import motor_cnpj
    original = motor_cnpj.motor_cnpj
    monkeypatch.setattr(historico._mcnpj, "motor_cnpj", lambda ctx, **kw: original(
        ctx, portas=[], listar_url=lambda p, c="": ("", "sem rede"), baixar_url=lambda *a, **k: (False, 0, "x")))


def _rodar(caminho, motores, ler=_ler_generico, **kw):
    return historico.rodar("2025-01", "2025-02", motores=motores, caminho=caminho, hoje=HOJE, ler_url=ler,
                           dormir=lambda s: None, pausa=0, tempo_limitado=False, **kw)


def test_nenhum_motor_grava_sha256_nulo_quando_houve_resposta(tmp_path, sem_rede):
    banco = _rodar(tmp_path / "h.db", historico.MOTORES)
    try:
        con = banco.con
        linhas = con.execute("SELECT motor, url, ok, http, bytes, sha256, requisicao, sem_resposta FROM coletas"
                             ).fetchall()
        motores = {m for m, *_ in linhas}
        assert len(motores) >= 15, motores                   # quase todo motor leu alguma coisa
        for motor, url, ok, http, b, sha, req, sem in linhas:
            if ok or http is not None or b:
                assert sha and len(sha) == 64, (motor, url, ok, http, b)
            assert req and len(req) == 64, (motor, url)       # toda coleta tem o hash da requisição
            assert sem == (0 if sha else 1), (motor, url)     # a ausência de resposta fica marcada
        # A resposta vazia (204) também tem impressão: a do vazio.
        assert (impressao(b""),) in con.execute("SELECT sha256 FROM coletas WHERE motor = 'qd'").fetchall()
        assert not rastreio.respostas_sem_impressao(con)["novas"]
        meta = dict(con.execute("SELECT chave, valor FROM meta"))
        assert "rastreio_erro" not in meta, meta.get("rastreio_erro")
        v = rastreio.verificar(con)
        assert v["integro"], v
    finally:
        banco.fechar()


def test_requisicao_tem_metodo_parametros_e_data_e_a_falha_guarda_so_a_requisicao(tmp_path):
    banco = historico.Banco(tmp_path / "h.db")
    ctx = historico.Contexto(banco, ["2025-01"], HOJE, ler_url=_ler_generico, dormir=lambda s: None, pausa=0)
    ctx.ler("siops", "form", "https://exemplo.gov.br/siops", formulario={"ano": "2025", "bim": "6"})
    ctx.ler("pncp", "rede", "https://fora-do-ar.gov.br/x", tentativas=1)
    ctx.ler("siconfi", "recusa", "https://apidatalake.tesouro.gov.br/ords/siconfi/tt/rgf?x=1", tentativas=1)
    linhas = banco.con.execute("SELECT url, metodo, parametros, quando, requisicao, sha256, sem_resposta, http "
                               "FROM coletas ORDER BY rowid").fetchall()
    form, rede, recusa = linhas
    assert form[1] == "POST" and json.loads(form[2]) == {"ano": "2025", "bim": "6"}
    for url, metodo, parametros, quando, req, *_ in linhas:
        assert req == rastreio.hash_requisicao(metodo, url, parametros, quando)
    assert form[5] == impressao(b'{"items": [], "data": [], "hasMore": false, "count": 0}') and form[6] == 0
    assert rede[5] is None and rede[6] == 1 and rede[4]          # sem resposta: só a requisição
    assert recusa[7] == 404 and recusa[5] == impressao(b'{"erro": "nao encontrado"}')   # a recusa tem corpo
    banco.con.close()


def test_hash_do_registro_e_canonico_e_muda_quando_um_campo_muda():
    a = rastreio.hash_registro("contratos_pncp", {"pncp_id": "X", "valor_global": 10.0, "objeto": None})
    b = rastreio.hash_registro("contratos_pncp", {"valor_global": 10.0, "pncp_id": "X"})
    assert a == b and len(a) == 64          # a ordem dos campos e os nulos não mudam o hash
    assert rastreio.hash_registro("contratos_pncp", {"pncp_id": "X", "valor_global": 10.01}) != a
    assert rastreio.hash_registro("contratacoes_pncp", {"pncp_id": "X", "valor_global": 10.0}) != a


def test_cada_registro_tem_selo_com_a_resposta_de_origem(tmp_path, sem_rede):
    from test_historico import _ler_falso
    banco = _rodar(tmp_path / "h.db", ("siconfi", "pncp"), ler=_ler_falso)
    con = banco.con
    rowid, = con.execute("SELECT rowid FROM siconfi_itens WHERE anexo = 'RREO-Anexo 08' LIMIT 1").fetchone()
    r = rastreio.registro(con, "siconfi_itens", rowid)
    assert r["confere"] and len(r["hash"]) == 64
    origem = r["selo"]["origem"]
    assert origem["motor"] == "siconfi" and "rreo" in origem["url"].lower()
    assert len(origem["resposta"]) == 64 and len(origem["requisicao"]) == 64
    # A ligação aponta para a linha da coleta que trouxe o registro: o hash dela confere.
    assert origem["coleta"] == rastreio.registro_da_coleta(con, origem["linha"])[0]
    # Todo registro de dado tem selo (nenhuma linha sem hash).
    v = rastreio.verificar_registros(con)
    assert v["conferidos"] > 0 and not v["sem_selo"] and not v["sumidos"]
    banco.fechar()


def test_registro_alterado_e_apontado_pela_verificacao(tmp_path, sem_rede):
    from test_historico import _ler_falso
    caminho = tmp_path / "h.db"
    _rodar(caminho, ("siconfi",), ler=_ler_falso).fechar()
    con = sqlite3.connect(caminho)
    rowid, valor = con.execute("SELECT rowid, valor FROM siconfi_itens ORDER BY rowid LIMIT 1").fetchone()
    antes = rastreio.hash_do_registro(con, "siconfi_itens", rowid)
    assert rastreio.verificar(con)["integro"]
    con.execute("UPDATE siconfi_itens SET valor = ? WHERE rowid = ?", (valor + 1, rowid))
    con.commit()
    depois = rastreio.hash_do_registro(con, "siconfi_itens", rowid)
    assert depois != antes                                        # o hash muda com o campo
    v = rastreio.verificar(con)
    assert not v["integro"]
    alteradas = v["registros"]["alteradas"]
    assert [(x["tabela"], x["linha"], x["hash"]) for x in alteradas] == [("siconfi_itens", rowid, depois)]
    assert antes in alteradas[0]["selos_sem_linha"]               # e o selo anterior é mostrado
    # Na próxima rodada, a alteração feita fora de rodada fica registrada na abertura (e na cadeia).
    con.close()
    banco = _rodar(caminho, ("sileg",), ler=_ler_falso, somar=True)
    ultima = banco.con.execute("SELECT abertura FROM rastreio_rodadas ORDER BY id DESC LIMIT 1").fetchone()[0]
    assert ultima and json.loads(ultima)["sem_selo"]["exemplos"][0]["linha"] == rowid
    banco.fechar()


def test_cadeia_de_rodadas_detecta_alteracao_de_rodada_antiga(tmp_path, sem_rede):
    from test_historico import _ler_falso
    caminho = tmp_path / "h.db"
    _rodar(caminho, ("siconfi", "querido_diario"), ler=_ler_falso).fechar()
    _rodar(caminho, ("querido_diario",), ler=_ler_falso, somar=True).fechar()
    _rodar(caminho, ("sileg",), ler=_ler_falso, somar=True).fechar()
    con = sqlite3.connect(caminho)
    c = rastreio.verificar_cadeia(con)
    assert c["ok"] and c["rodadas"] == 3
    hashes = [h for (h,) in con.execute("SELECT hash FROM rastreio_rodadas ORDER BY id")]
    anteriores = [a for (a,) in con.execute("SELECT anterior FROM rastreio_rodadas ORDER BY id")]
    assert anteriores == [rastreio.ZERO, hashes[0], hashes[1]]    # cada rodada aponta a anterior

    # 1) Mexer no registro de uma rodada antiga: o hash dela não confere.
    con.execute("UPDATE rastreio_rodadas SET motores = '[\"outro\"]' WHERE id = 1")
    c = rastreio.verificar_cadeia(con)
    assert not c["ok"] and any(p["rodada"] == 1 and "hash não confere" in p["motivo"] for p in c["problemas"])
    con.rollback()

    # 2) Trocar um selo de uma rodada antiga: a raiz de Merkle dela não confere e a tabela é apontada.
    tid, h = con.execute("SELECT s.tabela, s.hash FROM rastreio_selos s JOIN rastreio_tabelas t ON t.id = s.tabela "
                         "WHERE s.rodada = 1 AND t.nome = 'siconfi_itens' LIMIT 1").fetchone()
    con.execute("UPDATE rastreio_selos SET hash = ? WHERE tabela = ? AND hash = ?", (b"\x00" * 32, tid, h))
    c = rastreio.verificar_cadeia(con)
    problema = next(p for p in c["problemas"] if p["rodada"] == 1 and "raiz" in p["motivo"])
    assert problema["tabelas"] == ["siconfi_itens"]
    con.rollback()

    # 3) Refazer a raiz e o hash da rodada antiga para esconder a troca: o elo da rodada seguinte quebra.
    r = dict(zip([d[0] for d in con.execute("SELECT * FROM rastreio_rodadas WHERE id = 1").description],
                 con.execute("SELECT * FROM rastreio_rodadas WHERE id = 1").fetchone()))
    r["motores"] = '["outro"]'
    con.execute("UPDATE rastreio_rodadas SET motores = ?, hash = ? WHERE id = 1", (r["motores"],
                                                                               rastreio._hash_rodada(r)))
    c = rastreio.verificar_cadeia(con)
    assert any(p["rodada"] == 2 and "elo quebrado" in p["motivo"] for p in c["problemas"])
    con.close()


def test_banco_antigo_ganha_o_rastreio_sem_perder_linhas(tmp_path):
    caminho = tmp_path / "antigo.db"
    con = sqlite3.connect(caminho)
    con.executescript(historico.ESQUEMA)                 # o banco de antes: sem as colunas nem os selos
    con.execute("INSERT INTO coletas VALUES ('pncp', 'a', '2025-01', 'https://pncp.gov.br/x', 1, 200, NULL, 1, "
                "0.5, 10, ?, '2026-11-20T10:00:00+00:00')", ("b" * 64,))
    con.executemany("INSERT INTO contratos_pncp (pncp_id, mes, valor_global) VALUES (?, ?, ?)",
                    [(f"C-{i}", "2025-01", float(i)) for i in range(50)])
    con.executemany("INSERT INTO msc_itens (mes, conta_contabil, valor) VALUES (?, ?, ?)",
                    [("2025-01", "621200000", 1.0)] * 3)            # linhas iguais também contam
    con.commit()
    con.close()
    banco = historico.Banco.abrir(caminho)
    con = banco.con
    assert con.execute("SELECT count(*) FROM contratos_pncp").fetchone() == (50,)
    assert con.execute("SELECT count(*) FROM msc_itens").fetchone() == (3,)
    assert con.execute("SELECT count(*) FROM coletas").fetchone() == (1,)
    colunas = {c[1] for c in con.execute("PRAGMA table_info(coletas)")}
    assert {"requisicao", "metodo", "parametros", "sem_resposta"} <= colunas
    modo, registros = con.execute("SELECT modo, registros FROM rastreio_rodadas").fetchone()
    assert modo == rastreio.MODO_MIGRACAO and registros == 51      # 50 contratos e 1 linha (x3) da matriz
    r = rastreio.registro(con, "contratos_pncp", 1)
    assert r["confere"] and r["selo"]["origem"]["situacao"] == rastreio.ANTERIOR_AO_RASTREIO
    assert rastreio.verificar(con)["integro"]
    banco.con.close()
    # Abrir de novo não migra outra vez.
    banco = historico.Banco.abrir(caminho)
    assert banco.con.execute("SELECT count(*) FROM rastreio_rodadas").fetchone() == (1,)
    banco.con.close()


def test_banco_refeito_do_zero_continua_a_cadeia(tmp_path, sem_rede):
    from test_historico import _ler_falso
    caminho = tmp_path / "h.db"
    _rodar(caminho, ("sileg",), ler=_ler_falso).fechar()
    primeira = sqlite3.connect(rastreio.caminho_do_rastreio(caminho)).execute(
        "SELECT hash FROM rastreio_rodadas").fetchone()[0]
    banco = _rodar(caminho, ("sileg",), ler=_ler_falso)            # sem somar: o banco é refeito
    rodadas = banco.con.execute("SELECT herdada, hash, anterior FROM rastreio_rodadas ORDER BY id").fetchall()
    assert rodadas[0][:2] == (1, primeira) and rodadas[1][2] == primeira
    assert rastreio.verificar(banco.con)["integro"]
    banco.fechar()


def test_parecer_mostra_o_hash_em_cada_achado(tmp_path):
    from onisciente.conferencias.banco import Auditoria
    from onisciente.panorama import Panorama
    from onisciente.parecer import html
    from onisciente.rio import Afluente, Esfera, Rio
    from onisciente.nucleo import Selo
    rio = Rio("2026-10", [Afluente("Fonte", Esfera.MUNICIPAL, 100.0, "1500", Selo.AZUL, "")])
    p = Panorama(competencia="2026-10", alvo="Alvo de teste", dominio="Teste", rio=rio)
    registro = "c" * 64
    com = emitir(codigo="PRC-T-1", familia=Familia.PRC, titulo="Com apoio", gravidade="alta", como_deveria="a",
                 norma="n", como_esta="b", niveis=["A"],
                 custodia=[Original("https://pncp.gov.br/x", "2026-11-20", "d" * 64, registro=registro)])
    sem = emitir(codigo="PCT-T-2", familia=Familia.PCT, titulo="Sem apoio", gravidade="media", como_deveria="a",
                 norma="n", como_esta="falta o documento", documento_faltante=True)
    p.fichas = [com, sem]
    p.auditoria = Auditoria(ate=date(2026, 10, 31), rastreio={
        "rastreado": True, "rodadas": 2, "ok": True, "problemas": [],
        "ultima": {"id": 2, "modo": "somar", "inicio": "2026-11-28T00:00:00+00:00",
                   "fim": "2026-11-28T00:10:00+00:00", "raiz": "e" * 64, "hash": "f" * 64, "anterior": "1" * 64}})
    pagina = html.gerar(p, hoje=date(2026, 11, 27))
    for f in (com, sem):
        bloco = pagina[pagina.index(f'id="{f.codigo}"'):]
        bloco = bloco[:bloco.index("</article>")]
        # O hash curto na linha e o inteiro ao passar o mouse.
        assert f'title="hash do achado {f.hash_achado}">{f.hash_achado[:12]}<' in bloco
    bloco = pagina[pagina.index('id="PRC-T-1"'):]
    assert f'title="registro de apoio {registro}">{registro[:12]}<' in bloco[:bloco.index("</article>")]
    # Na tabela do rastreio, inteiros; e no fim, o hash da rodada e da cadeia.
    assert f'<td class="hash">{com.hash_achado}</td>' in pagina and f'<td class="hash">{registro}</td>' in pagina
    assert "f" * 64 in pagina and "e" * 64 in pagina and "a cadeia confere" in pagina
    assert com.como_dict()["rastreio"]["hash_apoio"] == registro


def test_linha_de_comando_verifica_e_mostra_o_registro_com_a_origem(tmp_path, sem_rede, capsys):
    from onisciente.__main__ import main
    from test_historico import _ler_falso
    caminho = tmp_path / "h.db"
    _rodar(caminho, ("siconfi",), ler=_ler_falso).fechar()
    assert main(["rastreio", "--banco", str(caminho)]) == 0
    saida = capsys.readouterr().out
    assert "cadeia: confere" in saida and "Íntegro." in saida
    con = sqlite3.connect(caminho)
    rowid, = con.execute("SELECT rowid FROM siconfi_itens LIMIT 1").fetchone()
    h = rastreio.hash_do_registro(con, "siconfi_itens", rowid)
    con.close()
    assert main(["rastreio", "--banco", str(caminho), "--hash", h[:10]]) == 0
    saida = capsys.readouterr().out
    assert h in saida and "sha256 da resposta" in saida and "hash da requisição" in saida


def test_base_da_receita_e_impedimentos_tem_hash_de_cada_arquivo_e_registro_com_origem(tmp_path):
    from onisciente.coletores import motor_cnpj
    from test_empresas import A, B, DADOS, PORTA, Rede, _banco_com_contratos, _cepim_zip, _leitor
    b = _banco_com_contratos(tmp_path, [A, B])
    rid = rastreio.abrir_rodada(b.con, ["cnpj", "impedimentos"], "teste")
    rede = Rede()
    ctx = historico.Contexto(b, ["2026-11"], date(2026, 11, 27), ler_url=_leitor({
        "cepim/20261125": (200, _cepim_zip()),
        "responsaveis-inidoneos": (200, (DADOS / "tcu_inidoneos_pagina0.json").read_bytes())}),
        dormir=lambda s: None, pausa=0)
    motor_cnpj.motor_cnpj(ctx, portas=[PORTA], listar_url=rede.listar, baixar_url=rede.baixar, pasta=tmp_path)
    motor_cnpj.motor_impedimentos(ctx)
    arquivos = b.consultar("SELECT url, sha256, metodo FROM coletas WHERE motor = 'cnpj' AND ok = 1 AND url LIKE "
                           "'%.zip'")
    assert len(arquivos) == len(Rede().arquivos)
    for url, sha, _m in arquivos:                      # o hash é o do arquivo baixado, byte a byte
        assert sha == impressao(rede.arquivos[url.rsplit("/", 1)[-1]]), url
    listagens = b.consultar("SELECT sha256, metodo FROM coletas WHERE motor = 'cnpj' AND alvo LIKE 'listagem%'")
    assert listagens and all(s and m == "PROPFIND" for s, m in listagens)
    for motor, ok, http, n, sha in b.consultar("SELECT motor, ok, http, bytes, sha256 FROM coletas"):
        if ok or http is not None or n:
            assert sha, motor
    rastreio.fechar_rodada(b.con, rid)
    rowid, = b.con.execute("SELECT rowid FROM cnpj_empresas").fetchone()
    origem = rastreio.registro(b.con, "cnpj_empresas", rowid)["selo"]["origem"]
    assert origem["motor"] == "cnpj" and origem["resposta"]
    rowid, = b.con.execute("SELECT rowid FROM impedimentos LIMIT 1").fetchone()
    origem = rastreio.registro(b.con, "impedimentos", rowid)["selo"]["origem"]
    assert origem["motor"] == "impedimentos" and origem["resposta"]
    assert rastreio.verificar(b.con)["integro"]
    b.con.close()


def test_selos_ficam_num_arquivo_a_parte_e_o_banco_nao_guarda_pendencias(tmp_path, sem_rede):
    """O banco da coleta beira os 100 MiB do GitHub: selos, origens e rodadas ficam em rastreio.db, ao
    lado de historico.db; no banco ficam só as pendências da rodada, esvaziadas ao fechá-la."""
    from test_historico import _ler_falso
    caminho = tmp_path / "historico.db"
    _rodar(caminho, ("siconfi", "sileg"), ler=_ler_falso).fechar()
    arquivo = tmp_path / "rastreio.db"
    assert rastreio.caminho_do_rastreio(caminho) == arquivo and arquivo.exists()
    con = sqlite3.connect(caminho)
    no_banco = {n for (n,) in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert not no_banco & set(rastreio.ESQUEMA_RASTREIO)
    assert con.execute("SELECT count(*) FROM rastreio_pendentes").fetchone() == (0,)
    con.close()
    sep = sqlite3.connect(arquivo)
    assert sep.execute("SELECT count(*) FROM rastreio_selos").fetchone()[0] > 0
    assert len(sep.execute("SELECT hash FROM rastreio_selos LIMIT 1").fetchone()[0]) == 32   # BLOB de 32 bytes
    sep.close()
    # Uma conexão só de leitura (a do parecer) enxerga o rastreio sem criar nada.
    ro = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    assert rastreio.resumo_da_cadeia(ro)["ok"] and rastreio.verificar(ro)["integro"]
    ro.close()
    # Banco de antes da separação (rastreio dentro dele): ao abrir, as tabelas vão para o arquivo à parte.
    con = sqlite3.connect(caminho)
    con.execute("ATTACH DATABASE ? AS velho", (str(arquivo),))
    for nome in rastreio.ESQUEMA_RASTREIO:
        con.execute(f"CREATE TABLE main.{nome} AS SELECT * FROM velho.{nome}")
    con.commit()
    con.execute("DETACH DATABASE velho")
    con.close()
    rastreio.apagar_rastreio(caminho)
    banco = historico.Banco.abrir(caminho)
    no_banco = {n for (n,) in banco.con.execute("SELECT name FROM main.sqlite_master WHERE type = 'table'")}
    assert not no_banco & set(rastreio.ESQUEMA_RASTREIO) and arquivo.exists()
    assert banco.con.execute("SELECT count(*) FROM rastreio_rodadas").fetchone() == (1,)
    assert rastreio.verificar(banco.con)["integro"]
    banco.fechar()
