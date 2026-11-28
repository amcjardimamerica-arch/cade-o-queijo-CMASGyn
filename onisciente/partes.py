"""O banco da coleta em partes: as tabelas grandes em arquivos próprios, anexados à mesma conexão.

O GitHub recusa arquivo acima de 100 MiB. O historico.db chegou a 98,6 MB em 28/11/2026 (commit
8705c6a) e, depois da primeira divisão, voltou a 88,7 MB com a despesa de Goiânia (07e130c). As tabelas
grandes saem dele para partes, cada uma num arquivo ao lado:

- ``precos.db``: ``precos_referencia`` (preços de referência do Compras.gov.br) e o seu índice;
- ``sancoes.db``: ``sancoes`` (CEIS e CNEP, a lista nacional) e o seu índice;
- ``series.db``: ``siconfi_itens``, ``msc_itens`` e ``externos_itens``, as séries que crescem com cada
  ano trazido (a agenda vai buscar até 2019);
- ``despesa/``: ``despesa_eventos`` (a execução de Goiânia, evento a evento). É uma parte comprimida:
  no ramo ficam só arquivos ``despesa_eventos_AAAA.jsonl.gz``, um por ano (cerca de 3,5 MB por ano de
  eventos), e a conexão anexa um SQLite de trabalho (``despesa/despesa.sqlite``, fora do git) refeito a
  partir deles quando faltar ou estiver velho. Oito anos de despesa (2019 a 2026) dariam uns 360 MB em
  SQLite, e o SQLite só anexa 10 arquivos por conexão: um arquivo por ano não cabe; comprimido, cabe.

Cada parte é anexada com o seu nome (``ATTACH 'precos.db' AS precos``). O SQLite procura um nome de
tabela sem esquema no banco principal e depois nos anexados, então quem lê e grava (``SELECT ... FROM
precos_referencia``, ``INSERT INTO despesa_eventos``, ``ALTER TABLE ... ADD COLUMN``) não muda. Este
módulo resolve o resto: criar a tabela (``CREATE TABLE IF NOT EXISTS`` sem esquema criaria uma cópia
vazia no principal; o esquema é reescrito com ``esquema_com_partes``, e a conexão do ``Banco`` é uma
``Conexao`` que reescreve sozinha todo CREATE que passa por ela, inclusive o dos motores), saber se a
tabela existe (``tem_tabela`` olha todos os esquemas) e abrir para leitura (``conectar_leitura``).

Só o banco chamado ``historico.db`` é dividido (o da coleta e os de teste com esse nome); a janela da
agenda e outros bancos de trabalho ficam inteiros, e a soma da janela grava cada tabela no esquema
onde ela está no banco principal (``esquema_da_tabela``).
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import re
import sqlite3
from pathlib import Path

PARTES: dict[str, tuple[str, ...]] = {
    "precos": ("precos_referencia",),
    "sancoes": ("sancoes",),
    "series": ("siconfi_itens", "msc_itens", "externos_itens"),
    "despesa": ("despesa_eventos",),
}
# Partes comprimidas: no ramo, um .jsonl.gz por tabela e ano (a coluna diz o ano); na conexão, um SQLite
# de trabalho refeito a partir deles.
COMPRIMIDAS: dict[str, dict[str, str]] = {"despesa": {"despesa_eventos": "data"}}
PARTE_DA_TABELA = {t: p for p, tabelas in PARTES.items() for t in tabelas}
NOME_DIVIDIDO = "historico.db"
CONTROLE = "partes_comprimidas"     # no SQLite de trabalho: os .gz de que ele foi feito (arquivo, sha256)
INTERNAS = (CONTROLE,)
SEM_ANO = "sem_ano"
NIVEL_GZIP = 6


def divide(caminho) -> bool:
    return bool(caminho) and str(caminho) != ":memory:" and Path(caminho).name == NOME_DIVIDIDO


def pasta_da_parte(caminho, parte: str) -> Path:
    """A pasta de uma parte comprimida (``dados/onisciente/despesa``)."""
    return Path(caminho).with_name(parte)


def caminho_da_parte(caminho, parte: str) -> Path:
    if parte in COMPRIMIDAS:
        return pasta_da_parte(caminho, parte) / f"{parte}.sqlite"
    return Path(caminho).with_name(f"{parte}.db")


def comprimidos(caminho, parte: str) -> list[Path]:
    """Os .jsonl.gz de uma parte comprimida, em ordem."""
    pasta = pasta_da_parte(caminho, parte)
    return sorted(pasta.glob("*.jsonl.gz")) if pasta.is_dir() else []


def arquivos(caminho) -> list[Path]:
    """Os arquivos das partes de um banco que existem (os SQLite e os comprimidos)."""
    if not divide(caminho):
        return []
    saida = []
    for p in PARTES:
        c = caminho_da_parte(caminho, p)
        saida += [Path(str(c) + s) for s in ("", "-journal", ".tmp") if Path(str(c) + s).exists()]
        if p in COMPRIMIDAS:
            saida += comprimidos(caminho, p)
    return saida


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
    só os que existem (a parte comprimida é refeita dos .gz quando o SQLite de trabalho falta ou está
    velho). Devolve as partes anexadas. Não pode ser chamada no meio de uma transação."""
    principal = _arquivo_principal(con)
    if not divide(principal):
        return anexadas(con)
    ja = set(anexadas(con))
    for parte in PARTES:
        if parte in ja:
            continue
        destino = caminho_da_parte(principal, parte)
        if parte in COMPRIMIDAS:
            refazer_se_preciso(principal, parte)
            if not somente_leitura:
                destino.parent.mkdir(parents=True, exist_ok=True)
        if somente_leitura and not destino.exists():
            continue
        try:
            con.execute(f"ATTACH DATABASE ? AS {parte}", (str(destino),))
        except sqlite3.Error:
            if not somente_leitura:
                raise
            continue
        if parte in COMPRIMIDAS and not somente_leitura:
            sqlite3.Connection.execute(
                con, f"CREATE TABLE IF NOT EXISTS {parte}.{CONTROLE} (arquivo TEXT PRIMARY KEY, sha256 TEXT)")
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
            if nome not in INTERNAS:
                saida.setdefault(nome, esquema)
    return saida


# Sem esquema (o nome não vem seguido de ponto): um CREATE já qualificado não é reescrito de novo.
_TABELA = re.compile(r"CREATE TABLE IF NOT EXISTS \"?(\w+)\"?(?![\w.])")
_INDICE = re.compile(r"CREATE (UNIQUE )?INDEX IF NOT EXISTS \"?(\w+)\"? ON \"?(\w+)\"?")


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


def _cria(sql) -> bool:
    return isinstance(sql, str) and "CREATE" in sql.upper()


class Conexao(sqlite3.Connection):
    """A conexão do ``Banco``: todo CREATE TABLE/INDEX IF NOT EXISTS que passa por ela vai para a parte
    da tabela, inclusive o dos motores que criam as próprias tabelas (o de Goiânia cria
    ``despesa_eventos`` a cada gravação)."""

    def execute(self, sql, *args, **kw):
        if _cria(sql) and sql.lstrip()[:6].upper() == "CREATE":
            sql = esquema_com_partes(self, sql)
        return super().execute(sql, *args, **kw)

    def executescript(self, sql):
        if _cria(sql):
            sql = esquema_com_partes(self, sql)
        return super().executescript(sql)


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
        sqlite3.Connection.execute(con, sql)
        colunas = [c[1] for c in con.execute(f"PRAGMA main.table_info({tabela})")]
        da_parte = {c[1] for c in con.execute(f"PRAGMA {parte}.table_info({tabela})")}
        for c in colunas:
            if c not in da_parte:                       # a parte veio de uma versão anterior da tabela
                con.execute(f'ALTER TABLE {parte}.{tabela} ADD COLUMN "{c}"')
        lista = ", ".join(f'"{c}"' for c in colunas)
        antes = con.execute(f"SELECT count(*) FROM main.{tabela}").fetchone()[0]
        ja = con.execute(f"SELECT count(*) FROM {parte}.{tabela}").fetchone()[0]
        con.execute(f"INSERT OR IGNORE INTO {parte}.{tabela} ({lista}) SELECT {lista} FROM main.{tabela}")
        depois = con.execute(f"SELECT count(*) FROM {parte}.{tabela}").fetchone()[0]
        if ja == 0 and depois < antes:
            con.rollback()
            raise RuntimeError(f"{tabela}: {depois} linhas na parte, {antes} no banco; nada foi movido")
        for s in indices:
            sqlite3.Connection.execute(con, re.sub(r"^CREATE (UNIQUE )?INDEX (IF NOT EXISTS )?\"?(\w+)\"?",
                                                   f"CREATE \\1INDEX IF NOT EXISTS {parte}.\\3", s, count=1))
        con.execute(f"DROP TABLE main.{tabela}")
        con.commit()
        movidas[tabela] = antes
    return movidas


# --- Partes comprimidas ------------------------------------------------------------------------------

def _sha(arquivo: Path) -> str:
    return hashlib.sha256(arquivo.read_bytes()).hexdigest()


def _de_que_foi_feito(cache: Path) -> dict[str, str] | None:
    if not cache.exists():
        return None
    try:
        con = sqlite3.connect(f"file:{cache}?mode=ro", uri=True)
        try:
            return dict(con.execute(f"SELECT arquivo, sha256 FROM {CONTROLE}"))
        finally:
            con.close()
    except sqlite3.Error:
        return None


def _valor(v):
    return {"$hex": v.hex()} if isinstance(v, bytes) else v


def _de_volta(v):
    return bytes.fromhex(v["$hex"]) if isinstance(v, dict) and "$hex" in v else v


def refazer_se_preciso(principal, parte: str) -> bool:
    """Refaz o SQLite de trabalho de uma parte comprimida a partir dos .gz quando ele falta ou foi feito
    de outros arquivos (outra rodada gravou no ramo). Devolve se refez."""
    gz = comprimidos(principal, parte)
    cache = caminho_da_parte(principal, parte)
    atual = {p.name: _sha(p) for p in gz}
    feito = _de_que_foi_feito(cache)
    if feito == atual or (feito is None and not atual):
        return False
    tmp = Path(str(cache) + ".tmp")
    if tmp.exists():
        tmp.unlink()
    cache.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(tmp)
    try:
        con.execute(f"CREATE TABLE {CONTROLE} (arquivo TEXT PRIMARY KEY, sha256 TEXT)")
        indices: dict[str, str] = {}
        criadas: set[str] = set()
        for arquivo in gz:
            with gzip.open(arquivo, "rt", encoding="utf-8") as f:
                cab = json.loads(f.readline())
                tabela = cab["tabela"]
                if tabela not in criadas:
                    con.execute(cab["sql"])
                    criadas.add(tabela)
                    indices.update({s: s for s in cab.get("indices", [])})
                existentes = [c[1] for c in con.execute(f'PRAGMA table_info("{tabela}")')]
                for c in cab["colunas"]:
                    if c not in existentes:
                        con.execute(f'ALTER TABLE "{tabela}" ADD COLUMN "{c}"')
                lista = ", ".join(f'"{c}"' for c in cab["colunas"])
                marcas = ", ".join("?" for _ in cab["colunas"])
                con.executemany(f'INSERT INTO "{tabela}" ({lista}) VALUES ({marcas})',
                                ([_de_volta(v) for v in json.loads(linha)] for linha in f))
            con.execute(f"INSERT INTO {CONTROLE} VALUES (?, ?)", (arquivo.name, atual[arquivo.name]))
        for s in indices:
            con.execute(s)
        con.commit()
    finally:
        con.close()
    os.replace(tmp, cache)
    return True


def _ano(coluna: str) -> str:
    return (f"CASE WHEN \"{coluna}\" GLOB '[0-9][0-9][0-9][0-9]*' THEN substr(\"{coluna}\", 1, 4) "
            f"ELSE '{SEM_ANO}' END")


def exportar(con) -> dict[str, int]:
    """Grava os .jsonl.gz das partes comprimidas a partir do SQLite de trabalho: um por tabela e ano,
    em ordem estável e sem data no cabeçalho do gzip (ano que não mudou dá o mesmo arquivo, e o git não
    vê mudança). Tira o .gz de um ano que ficou sem linhas. Devolve as linhas gravadas por arquivo."""
    principal = _arquivo_principal(con)
    gravados: dict[str, int] = {}
    if not divide(principal):
        return gravados
    for parte, tabelas_ in COMPRIMIDAS.items():
        if parte not in anexadas(con):
            continue
        pasta = pasta_da_parte(principal, parte)
        pasta.mkdir(parents=True, exist_ok=True)
        feitos: dict[str, str] = {}
        for tabela, coluna in tabelas_.items():
            linha = con.execute(f"SELECT sql FROM {parte}.sqlite_master WHERE type = 'table' AND name = ?",
                                (tabela,)).fetchone()
            if not linha:
                continue
            indices = [s for (s,) in con.execute(f"SELECT sql FROM {parte}.sqlite_master WHERE type = 'index' "
                                                 "AND tbl_name = ? AND sql IS NOT NULL ORDER BY name", (tabela,))]
            colunas = [c[1] for c in con.execute(f"PRAGMA {parte}.table_info({tabela})")]
            ordem = ", ".join(f'"{c}"' for c in colunas)
            anos = [a for (a,) in con.execute(f"SELECT DISTINCT {_ano(coluna)} FROM {parte}.{tabela} ORDER BY 1")]
            for ano in anos:
                cab = {"tabela": tabela, "ano": ano, "sql": linha[0], "indices": indices, "colunas": colunas}
                buf = io.BytesIO()
                n = 0
                with gzip.GzipFile(filename="", fileobj=buf, mode="wb", mtime=0, compresslevel=NIVEL_GZIP) as g:
                    g.write((json.dumps(cab, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))
                    for r in con.execute(f"SELECT {ordem} FROM {parte}.{tabela} WHERE {_ano(coluna)} = ? "
                                         f"ORDER BY {ordem}", (ano,)):
                        g.write((json.dumps([_valor(v) for v in r], ensure_ascii=False,
                                            separators=(",", ":")) + "\n").encode("utf-8"))
                        n += 1
                dados = buf.getvalue()
                destino = pasta / f"{tabela}_{ano}.jsonl.gz"
                if not destino.exists() or destino.read_bytes() != dados:
                    destino.write_bytes(dados)
                feitos[destino.name] = hashlib.sha256(dados).hexdigest()
                gravados[destino.name] = n
        for velho in comprimidos(principal, parte):
            if velho.name not in feitos:
                velho.unlink()                          # o ano ficou sem linhas
        con.execute(f"DELETE FROM {parte}.{CONTROLE}")
        con.executemany(f"INSERT INTO {parte}.{CONTROLE} VALUES (?, ?)", sorted(feitos.items()))
        con.commit()
    return gravados
