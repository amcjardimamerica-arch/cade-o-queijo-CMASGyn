"""O banco da coleta em partes: as tabelas grandes em arquivos próprios, anexados à mesma conexão.

O GitHub recusa arquivo acima de 100 MiB, e o historico.db chegou a 98,6 MB em 28/11/2026 (commit
8705c6a). Duas tabelas grandes e independentes saem dele para arquivos ao lado:

- ``precos.db``: ``precos_referencia`` (preços de referência do Compras.gov.br) e o seu índice;
- ``sancoes.db``: ``sancoes`` (CEIS e CNEP, a lista nacional) e o seu índice.

Cada arquivo é anexado à conexão com o nome da parte (``ATTACH 'precos.db' AS precos``). O SQLite
procura um nome de tabela sem esquema no banco principal e depois nos anexados, então quem lê e grava
(``SELECT ... FROM precos_referencia``, ``INSERT INTO sancoes``) não muda. Mudam só três coisas, que
este módulo resolve: criar a tabela (``CREATE TABLE IF NOT EXISTS`` sem esquema criaria uma cópia vazia
no principal, por isso o esquema é reescrito com ``esquema_com_partes``), saber se a tabela existe
(``sqlite_master`` é só o do principal; ``tem_tabela`` olha todos) e abrir para leitura
(``conectar_leitura`` anexa as partes que existirem, sem criar nada).

Só o banco chamado ``historico.db`` é dividido (o da coleta e os de teste com esse nome); a janela da
agenda e outros bancos de trabalho ficam inteiros, e a soma da janela grava cada tabela no esquema
onde ela está no banco principal (``esquema_da_tabela``).
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

PARTES: dict[str, tuple[str, ...]] = {
    "precos": ("precos_referencia",),
    "sancoes": ("sancoes",),
}
PARTE_DA_TABELA = {t: p for p, tabelas in PARTES.items() for t in tabelas}
NOME_DIVIDIDO = "historico.db"


def divide(caminho) -> bool:
    return bool(caminho) and str(caminho) != ":memory:" and Path(caminho).name == NOME_DIVIDIDO


def caminho_da_parte(caminho, parte: str) -> Path:
    return Path(caminho).with_name(f"{parte}.db")


def arquivos(caminho) -> list[Path]:
    """Os arquivos das partes de um banco (existam ou não)."""
    return [caminho_da_parte(caminho, p) for p in PARTES] if divide(caminho) else []


def _arquivo_principal(con) -> str:
    for _, nome, arquivo in con.execute("PRAGMA database_list"):
        if nome == "main":
            return arquivo or ""
    return ""


def anexadas(con) -> list[str]:
    nomes = {nome for _, nome, _ in con.execute("PRAGMA database_list")}
    return [p for p in PARTES if p in nomes]


def anexar(con, *, somente_leitura: bool = False) -> list[str]:
    """Anexa as partes do banco à conexão. Para gravar, cria os arquivos que faltarem; para ler, anexa
    só os que existem. Devolve as partes anexadas. Não pode ser chamada no meio de uma transação."""
    principal = _arquivo_principal(con)
    if not divide(principal):
        return anexadas(con)
    ja = set(anexadas(con))
    for parte in PARTES:
        if parte in ja:
            continue
        destino = caminho_da_parte(principal, parte)
        if somente_leitura and not destino.exists():
            continue
        try:
            con.execute(f"ATTACH DATABASE ? AS {parte}", (str(destino),))
        except sqlite3.Error:
            if not somente_leitura:
                raise
    return anexadas(con)


def conectar_leitura(caminho, **kw) -> sqlite3.Connection:
    """Conexão só de leitura com o banco e as partes dele."""
    con = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True, **kw)
    anexar(con, somente_leitura=True)
    return con


def esquemas(con) -> list[str]:
    """Os esquemas que guardam dados da coleta: o principal e as partes anexadas."""
    return ["main", *anexadas(con)]


def tem_tabela(con, nome: str) -> bool:
    """A tabela existe no banco ou numa parte anexada (o ``sqlite_master`` sozinho só vê o principal)."""
    return esquema_da_tabela(con, nome) is not None


def esquema_da_tabela(con, nome: str) -> str | None:
    for esquema in esquemas(con):
        if con.execute(f"SELECT 1 FROM {esquema}.sqlite_master WHERE type = 'table' AND name = ?",
                       (nome,)).fetchone():
            return esquema
    return None


def tabelas(con) -> dict[str, str]:
    """Nome -> esquema de cada tabela do banco e das partes (as do principal vêm primeiro)."""
    saida: dict[str, str] = {}
    for esquema in esquemas(con):
        for (nome,) in con.execute(f"SELECT name FROM {esquema}.sqlite_master WHERE type = 'table' "
                                   "AND name NOT LIKE 'sqlite_%'"):
            saida.setdefault(nome, esquema)
    return saida


_TABELA = re.compile(r"CREATE TABLE IF NOT EXISTS (\w+)")
_INDICE = re.compile(r"CREATE (UNIQUE )?INDEX IF NOT EXISTS (\w+) ON (\w+)")


def esquema_com_partes(con, sql: str) -> str:
    """O esquema (CREATE TABLE/INDEX IF NOT EXISTS) com as tabelas das partes no arquivo delas."""
    partes = set(anexadas(con))
    if not partes:
        return sql

    def tabela(m):
        parte = PARTE_DA_TABELA.get(m.group(1))
        return f"CREATE TABLE IF NOT EXISTS {parte}.{m.group(1)}" if parte in partes else m.group(0)

    def indice(m):
        parte = PARTE_DA_TABELA.get(m.group(3))
        if parte not in partes:
            return m.group(0)
        return f"CREATE {m.group(1) or ''}INDEX IF NOT EXISTS {parte}.{m.group(2)} ON {m.group(3)}"

    return _INDICE.sub(indice, _TABELA.sub(tabela, sql))


def mover_para_as_partes(con) -> dict[str, int]:
    """Banco antigo, com as tabelas das partes dentro dele: cada uma vai para o seu arquivo, com os
    índices e todas as linhas, e sai do principal. Devolve as linhas movidas por tabela (vazio quando
    não havia o que mover). Quem chama compacta o principal depois (VACUUM)."""
    movidas: dict[str, int] = {}
    partes = set(anexadas(con))
    for tabela, parte in PARTE_DA_TABELA.items():
        if parte not in partes:
            continue
        linha = con.execute("SELECT sql FROM main.sqlite_master WHERE type = 'table' AND name = ?",
                            (tabela,)).fetchone()
        if not linha:
            continue
        indices = [s for (s,) in con.execute("SELECT sql FROM main.sqlite_master WHERE type = 'index' "
                                             "AND tbl_name = ? AND sql IS NOT NULL", (tabela,))]
        sql = re.sub(r"^CREATE TABLE (IF NOT EXISTS )?\"?(\w+)\"?", f"CREATE TABLE IF NOT EXISTS {parte}.\\2",
                     linha[0], count=1)
        con.execute(sql)
        colunas = [c[1] for c in con.execute(f"PRAGMA main.table_info({tabela})")]
        lista = ", ".join(f'"{c}"' for c in colunas)
        antes = con.execute(f"SELECT count(*) FROM main.{tabela}").fetchone()[0]
        con.execute(f"INSERT OR IGNORE INTO {parte}.{tabela} ({lista}) SELECT {lista} FROM main.{tabela}")
        depois = con.execute(f"SELECT count(*) FROM {parte}.{tabela}").fetchone()[0]
        if depois < antes:
            con.rollback()
            raise RuntimeError(f"{tabela}: {depois} linhas na parte, {antes} no banco; nada foi movido")
        for s in indices:
            con.execute(re.sub(r"^CREATE (UNIQUE )?INDEX (IF NOT EXISTS )?\"?(\w+)\"?",
                               f"CREATE \\1INDEX IF NOT EXISTS {parte}.\\3", s, count=1))
        con.execute(f"DROP TABLE main.{tabela}")
        con.commit()
        movidas[tabela] = antes
    return movidas
