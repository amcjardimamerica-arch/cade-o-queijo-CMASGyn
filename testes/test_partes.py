"""Travas do banco em partes (28/11/2026).

O historico.db chegou a 98,6 MB (o GitHub recusa arquivo acima de 100 MiB). ``precos_referencia`` vai
para dados/onisciente/precos.db e ``sancoes`` (CEIS e CNEP) para dados/onisciente/sancoes.db, anexados
à mesma conexão: quem lê e grava não percebe; um banco antigo tem as tabelas movidas ao abrir, sem
perder linhas, e o principal é compactado; o rastreio continua selando as tabelas das partes.
"""

import sqlite3

from onisciente import agenda, historico, partes, rastreio
from onisciente.conferencias import compras, federais
from onisciente.telas import base as telas

PRECO = {"catalogo": 1, "semestre": "2026-1", "id_item": "I-1", "preco": 10.5, "descricao": "arroz"}
SANCAO = {"cnpj_cpf": "11222333000181", "cadastro": "CEIS", "inicio": "2025-01-01", "nome": "Empresa X",
          "arquivo": "20261126"}


def _coleta(b, motor, url):
    b.inserir("coletas", {"motor": motor, "alvo": "teste", "mes": "2026-11", "url": url, "ok": 1, "http": 200,
                          "tentativas": 1, "bytes": 10, "sha256": "c" * 64})


def _no_principal(caminho) -> set[str]:
    con = sqlite3.connect(caminho)
    try:
        return {n for (n,) in con.execute("SELECT name FROM sqlite_master")}
    finally:
        con.close()


def test_tabelas_grandes_ficam_nas_partes_e_o_codigo_nao_percebe(tmp_path):
    caminho = tmp_path / "historico.db"
    b = historico.Banco(caminho)
    rid = rastreio.abrir_rodada(b.con, ["precos_compras", "sancoes"], "teste")
    _coleta(b, "precos_compras", "https://exemplo.gov.br/precos")
    b.inserir("precos_referencia", PRECO)
    _coleta(b, "sancoes", "https://exemplo.gov.br/ceis")
    b.inserir("sancoes", SANCAO)
    rastreio.fechar_rodada(b.con, rid)
    # O rastreio sela as linhas das partes com a resposta de onde saíram (gatilho TEMP da conexão).
    for tabela, url in (("precos_referencia", "precos"), ("sancoes", "ceis")):
        rowid, = b.con.execute(f"SELECT rowid FROM {tabela}").fetchone()
        r = rastreio.registro(b.con, tabela, rowid)
        assert r["confere"] and r["selo"]["origem"]["url"].endswith(url), tabela
    assert rastreio.verificar(b.con)["integro"]
    b.fechar()
    assert (tmp_path / "precos.db").exists() and (tmp_path / "sancoes.db").exists()
    assert not _no_principal(caminho) & {"precos_referencia", "sancoes", "sancoes_cnpj_cpf"}
    # Quem só lê (telas, conferências, parecer) abre o historico.db e enxerga as partes.
    con = telas.abrir(caminho)
    assert telas.tabela_existe(con, "precos_referencia") and telas.tabela_existe(con, "sancoes")
    assert compras._tabela(con, "precos_referencia") and federais._tabela(con, "sancoes")
    assert con.execute("SELECT preco FROM precos_referencia").fetchone() == (10.5,)
    assert con.execute("SELECT nome FROM sancoes WHERE cnpj_cpf = ?", (SANCAO["cnpj_cpf"],)).fetchone() == ("Empresa X",)
    assert rastreio.verificar(con)["integro"]
    con.close()
    # Abrir de novo (sem refazer) mantém tudo nas partes; refazer do zero apaga as partes também.
    b = historico.Banco.abrir(caminho)
    assert b.con.execute("SELECT count(*) FROM sancoes").fetchone() == (1,)
    b.fechar()
    assert not _no_principal(caminho) & {"precos_referencia", "sancoes"}


def test_banco_antigo_tem_as_tabelas_movidas_sem_perder_linhas_e_encolhe(tmp_path):
    caminho = tmp_path / "historico.db"
    con = sqlite3.connect(caminho)
    con.executescript(historico.ESQUEMA)              # o banco de antes: tudo dentro do historico.db
    con.executemany("INSERT INTO precos_referencia (catalogo, semestre, id_item, preco, descricao) "
                    "VALUES (?, ?, ?, ?, ?)", [(1, "2026-1", f"I-{i}", float(i), "x" * 200) for i in range(3000)])
    con.executemany("INSERT INTO sancoes (cnpj_cpf, cadastro, nome) VALUES (?, ?, ?)",
                    [(f"{i:014d}", "CEIS", "y" * 200) for i in range(2000)])
    con.execute("INSERT INTO contratos_pncp (pncp_id, mes, valor_global) VALUES ('C-1', '2025-01', 1.0)")
    con.commit()
    con.close()
    antes = caminho.stat().st_size
    b = historico.Banco.abrir(caminho)
    assert b.con.execute("SELECT count(*) FROM precos_referencia").fetchone() == (3000,)
    assert b.con.execute("SELECT count(*) FROM sancoes").fetchone() == (2000,)
    assert partes.esquema_da_tabela(b.con, "precos_referencia") == "precos"
    assert partes.esquema_da_tabela(b.con, "sancoes") == "sancoes"
    assert b.con.execute("SELECT name FROM sancoes.sqlite_master WHERE type = 'index'").fetchall() == [
        ("sancoes_cnpj_cpf",)]
    assert rastreio.verificar(b.con)["integro"]           # a migração do rastreio selou as partes
    selos = b.con.execute("SELECT t.nome, sum(s.n) FROM rastreio_selos s JOIN rastreio_tabelas t ON t.id = s.tabela "
                          "WHERE t.nome IN ('precos_referencia', 'sancoes') GROUP BY t.nome").fetchall()
    assert dict(selos) == {"precos_referencia": 3000, "sancoes": 2000}
    b.fechar()
    assert not _no_principal(caminho) & {"precos_referencia", "sancoes", "sancoes_cnpj_cpf"}
    assert caminho.stat().st_size < antes / 3             # o principal foi compactado (VACUUM)


def test_banco_com_outro_nome_fica_inteiro():
    assert not partes.divide("/tmp/janela.db") and partes.divide("/x/dados/onisciente/historico.db")


def test_soma_da_janela_grava_na_parte_do_principal(tmp_path):
    principal = historico.Banco(tmp_path / "historico.db")
    principal.inserir("sancoes", {**SANCAO, "nome": "Antiga"})
    principal.con.commit()
    janela = historico.Banco(tmp_path / "janela.db")          # a janela fica inteira
    janela.inserir("sancoes", {**SANCAO, "cnpj_cpf": "99888777000166", "nome": "Nova"})
    janela.con.commit()
    janela.con.close()
    agenda.somar_janela(principal, tmp_path / "janela.db", ["2026-11"])
    assert partes.esquema_da_tabela(principal.con, "sancoes") == "sancoes"
    assert {n for (n,) in principal.con.execute("SELECT nome FROM sancoes")} >= {"Nova"}
    assert not principal.con.execute("SELECT 1 FROM main.sqlite_master WHERE name = 'sancoes'").fetchone()
    principal.fechar()
