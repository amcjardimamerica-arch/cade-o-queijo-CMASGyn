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


def _eventos(ano: int, n: int) -> list[dict]:
    return [{"tipo": "empenho", "empenho": f"{ano}NE{i:05d}", "ordem": "", "data": f"{ano}-03-{1 + i % 28:02d}",
             "orgao": "SECRETARIA MUNICIPAL DE TESTE", "credor": "Fornecedor", "documento": "***.123.456-**",
             "valor": 100.0 + i, "historico": "objeto do empenho", "consulta": "lista", "url": "https://exemplo"}
            for i in range(n)]


def test_despesa_vai_comprimida_por_ano_e_volta_igual(tmp_path):
    """A despesa de 2019 a 2026 não cabe em SQLite de até 70 MB com o limite de 10 anexos: no ramo ela fica
    em .jsonl.gz por ano, e a conexão anexa um SQLite de trabalho refeito deles."""
    from onisciente.coletores import goiania_transweb as gt
    caminho = tmp_path / "historico.db"
    b = historico.Banco(caminho)
    rid = rastreio.abrir_rodada(b.con, ["execucao_goiania"], "teste")
    _coleta(b, "execucao_goiania", "https://exemplo.gov.br/despesa")
    assert gt.gravar(b.con, _eventos(2025, 30) + _eventos(2026, 50)) == 80   # o motor cria a tabela e grava
    assert gt.gravar(b.con, _eventos(2026, 50)) == 0                         # o índice único vale na parte
    assert partes.esquema_da_tabela(b.con, "despesa_eventos") == "despesa"
    assert not b.con.execute("SELECT 1 FROM main.sqlite_master WHERE name = 'despesa_eventos'").fetchone()
    rastreio.fechar_rodada(b.con, rid)
    b.fechar()
    pasta = tmp_path / "despesa"
    gz = sorted(p.name for p in pasta.glob("*.jsonl.gz"))
    assert gz == ["despesa_eventos_2025.jsonl.gz", "despesa_eventos_2026.jsonl.gz"]
    bytes_antes = {p.name: p.read_bytes() for p in pasta.glob("*.jsonl.gz")}
    # Sem o SQLite de trabalho (o clone do ramo não o tem), quem lê enxerga a despesa refeita dos .gz.
    (pasta / "despesa.sqlite").unlink()
    con = partes.conectar_leitura(caminho)
    assert con.execute("SELECT count(*), sum(valor) FROM despesa_eventos").fetchone() == (
        80, sum(100.0 + i for i in range(30)) + sum(100.0 + i for i in range(50)))
    assert telas.tabela_existe(con, "despesa_eventos")
    assert rastreio.verificar(con)["integro"]                  # os selos valem para a despesa refeita
    con.close()
    # Reabrir e fechar sem mudar nada não muda os .gz (o git não vê mudança); um ano novo ganha arquivo.
    b = historico.Banco.abrir(caminho)
    b.fechar()
    assert {p.name: p.read_bytes() for p in pasta.glob("*.jsonl.gz")} == bytes_antes
    b = historico.Banco.abrir(caminho)
    gt.gravar(b.con, _eventos(2019, 5))
    b.con.commit()
    b.fechar()
    assert (pasta / "despesa_eventos_2019.jsonl.gz").exists()
    assert {p.name: p.read_bytes() for p in pasta.glob("*_202?.jsonl.gz")} == bytes_antes


def test_series_ficam_numa_parte_propria(tmp_path):
    caminho = tmp_path / "historico.db"
    b = historico.Banco(caminho)
    for tabela in ("siconfi_itens", "msc_itens", "externos_itens"):
        assert partes.esquema_da_tabela(b.con, tabela) == "series", tabela
    b.fechar()
    assert (tmp_path / "series.db").exists()


# --- A despesa nunca fica só no SQLite de trabalho (28/11/2026) ----------------------------------------
# O SQLite de trabalho (despesa/despesa.sqlite) não vai ao ramo. Um caminho que abre o banco pelo Banco.abrir
# e grava sem chamar Banco.fechar (o rastreio, o parecer, as telas, a soma da janela) não pode deixar o
# historico.db sem a despesa e sem os .gz: o commit regrava os .gz dos anos mudados, e a tabela antiga só sai
# do principal depois de os .gz conferirem com ela.

def _clone(caminho):
    """O que o ramo guarda: sem o SQLite de trabalho, a despesa vem só dos .gz."""
    for sobra in (caminho.parent / "despesa").glob("despesa.sqlite*"):
        sobra.unlink()
    return partes.conectar_leitura(caminho)


def test_banco_antigo_aberto_pelo_rastreio_sem_fechar_nao_perde_a_despesa(tmp_path):
    import subprocess
    import sys
    from pathlib import Path

    from onisciente.coletores import goiania_transweb as gt
    caminho = tmp_path / "historico.db"
    antigo = sqlite3.connect(caminho)                 # banco de antes das partes: a despesa dentro dele
    gt.gravar(antigo, _eventos(2025, 30) + _eventos(2026, 40))
    antigo.commit()
    antigo.close()
    raiz = Path(__file__).resolve().parent.parent
    r = subprocess.run([sys.executable, "-m", "onisciente", "rastreio", "--banco", str(caminho)], cwd=raiz,
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    assert "despesa_eventos" not in _no_principal(caminho)
    assert sorted(p.name for p in (tmp_path / "despesa").glob("*.jsonl.gz")) == [
        "despesa_eventos_2025.jsonl.gz", "despesa_eventos_2026.jsonl.gz"]
    con = _clone(caminho)
    assert con.execute("SELECT count(*) FROM despesa_eventos").fetchone() == (70,)
    con.close()


def test_gravacao_na_despesa_sem_fechar_vai_aos_gz_no_commit(tmp_path):
    from onisciente.coletores import goiania_transweb as gt
    caminho = tmp_path / "historico.db"
    b = historico.Banco(caminho)
    gt.gravar(b.con, _eventos(2025, 10) + _eventos(2026, 20))
    b.con.commit()
    b.con.close()                                     # sem fechar
    con = _clone(caminho)
    assert con.execute("SELECT count(*) FROM despesa_eventos").fetchone() == (30,)
    con.close()
    # Só o ano mudado é regravado; o ano que ficou sem linhas perde o .gz.
    pasta = tmp_path / "despesa"
    antes_2026 = (pasta / "despesa_eventos_2026.jsonl.gz").read_bytes()
    b = historico.Banco.abrir(caminho)
    b.con.execute("DELETE FROM despesa_eventos WHERE data LIKE '2025%'")
    gt.gravar(b.con, _eventos(2019, 3))
    b.con.commit()
    b.con.close()
    assert sorted(p.name for p in pasta.glob("*.jsonl.gz")) == ["despesa_eventos_2019.jsonl.gz",
                                                               "despesa_eventos_2026.jsonl.gz"]
    assert (pasta / "despesa_eventos_2026.jsonl.gz").read_bytes() == antes_2026
    con = _clone(caminho)
    assert con.execute("SELECT substr(data, 1, 4), count(*) FROM despesa_eventos GROUP BY 1").fetchall() == [
        ("2019", 3), ("2026", 20)]
    con.close()
    # Desfeito (rollback), nada vai aos .gz.
    b = historico.Banco.abrir(caminho)
    b.con.execute("DELETE FROM despesa_eventos")
    b.con.rollback()
    b.con.commit()
    b.con.close()
    con = _clone(caminho)
    assert con.execute("SELECT count(*) FROM despesa_eventos").fetchone() == (23,)
    con.close()


def test_soma_da_janela_troca_so_os_empenhos_e_os_meses_relidos_da_despesa(tmp_path):
    """O grupo execucao_goiania roda em janela: a soma não pode refazer a despesa só com os meses da janela."""
    from onisciente.coletores import goiania_transweb as gt
    caminho = tmp_path / "historico.db"
    principal = historico.Banco(caminho)
    gt.gravar(principal.con, _eventos(2025, 5) + _eventos(2026, 5))
    for mes in ("2025-03", "2026-03"):
        principal.con.execute("INSERT INTO despesa_consultas VALUES (?,?,?,?,?,?,?,?,?)",
                              ("lista", mes, "", "lida", 5, 1, "https://exemplo", "", "2026-11-01"))
    principal.con.commit()
    janela = historico.Banco(tmp_path / "janela.db")
    relidos = [{**e, "valor": e["valor"] + 1000} for e in _eventos(2026, 3)]     # 3 empenhos de 2026 relidos
    gt.gravar(janela.con, relidos)
    janela.con.execute("INSERT INTO despesa_consultas VALUES (?,?,?,?,?,?,?,?,?)",
                       ("lista", "2026-03", "", "lida", 3, 1, "https://exemplo", "", "2026-11-28"))
    janela.con.commit()
    janela.con.close()
    agenda.somar_janela(principal, tmp_path / "janela.db", ["2026-03"])
    principal.con.close()                             # sem fechar
    con = _clone(caminho)
    por_ano = con.execute("SELECT substr(data, 1, 4), count(*), sum(valor > 1000) FROM despesa_eventos "
                          "GROUP BY 1").fetchall()
    assert por_ano == [("2025", 5, 0), ("2026", 5, 3)]   # 2025 fica; dos 5 empenhos de 2026, 3 trocados
    assert con.execute("SELECT dia, quando FROM despesa_consultas ORDER BY dia").fetchall() == [
        ("2025-03", "2026-11-01"), ("2026-03", "2026-11-28")]
    con.close()


# --- Cópia do banco inteiro (28/11/2026, divisão do banco em partes) ----------------------------------
# Um teste que copiava só o historico.db (shutil.copy) ficou sem siconfi_itens, msc_itens, externos_itens,
# sancoes e a despesa: partes.copiar_banco copia o principal e todas as partes, e partes.conectar grava nelas.

def test_copia_do_banco_leva_todas_as_partes_e_a_conexao_grava_nelas(tmp_path):
    from onisciente.coletores import goiania_transweb as gt
    origem = tmp_path / "a" / "historico.db"
    origem.parent.mkdir()
    b = historico.Banco(origem)
    b.inserir("precos_referencia", PRECO)
    b.inserir("sancoes", SANCAO)
    b.inserir("msc_itens", {"mes": "2026-03", "conta_contabil": "621200000", "valor": 10.0})
    gt.gravar(b.con, _eventos(2025, 3) + _eventos(2026, 4))
    b.con.commit()
    b.fechar()
    copia = partes.copiar_banco(origem, tmp_path / "b" / "historico.db", rastreio=True)
    assert sorted(p.name for p in (tmp_path / "b").rglob("*") if p.is_file()) == sorted(
        p.name for p in (tmp_path / "a").rglob("*") if p.is_file() and not p.name.endswith(("-journal", ".tmp")))
    con = partes.conectar(copia)
    for tabela, n in (("precos_referencia", 1), ("sancoes", 1), ("msc_itens", 1), ("despesa_eventos", 7)):
        assert con.execute(f"SELECT count(*) FROM {tabela}").fetchone()[0] == n, tabela
    con.execute("UPDATE msc_itens SET valor = valor * 2")
    con.execute("DELETE FROM despesa_eventos WHERE data LIKE '2025%'")
    con.commit()
    con.close()
    # A adulteração chegou às partes da cópia (e aos .gz da despesa); a origem ficou como estava.
    assert _clone(copia).execute("SELECT (SELECT valor FROM msc_itens), (SELECT count(*) FROM despesa_eventos)"
                                 ).fetchone() == (20.0, 4)
    assert _clone(origem).execute("SELECT (SELECT valor FROM msc_itens), (SELECT count(*) FROM despesa_eventos)"
                                  ).fetchone() == (10.0, 7)
    # Copiar só o principal: as tabelas das partes não existem (o que quebrava os testes antigos).
    so = tmp_path / "c" / "historico.db"
    so.parent.mkdir()
    so.write_bytes(origem.read_bytes())
    sozinho = sqlite3.connect(so)
    assert not sozinho.execute("SELECT 1 FROM sqlite_master WHERE name = 'msc_itens'").fetchone()
    sozinho.close()
