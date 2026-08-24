"""Banco de busca local em SQLite com FTS5.

Substitui a consulta a sítios externos. Uma vez construído, responder a
qualquer pergunta sobre o acervo do CMASGyn custa zero token e zero rede:
é uma consulta local de texto integral.

Uso:
    python src/busca_local.py indexar
    python src/busca_local.py buscar "IGD NEAR/10 controle social"
    python src/busca_local.py buscar "inscrição de entidade" --ano 2025
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import sqlite3
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
BANCO = RAIZ / "dados" / "cmasgyn.db"
TXT = RAIZ / "acervo" / "historico" / "txt"
TXTGZ = RAIZ / "acervo" / "historico" / "txt_gz"
REGISTRO = RAIZ / "estado" / "historico_registro.json"

ESQUEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS documentos (
    nome        TEXT PRIMARY KEY,
    data        TEXT NOT NULL,
    ano         INTEGER,
    tipo        TEXT,
    edicao      INTEGER,
    url         TEXT NOT NULL,
    sha256      TEXT NOT NULL,
    bytes       INTEGER,
    caracteres  INTEGER,
    ocr         INTEGER,
    termos      TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS busca USING fts5(
    nome UNINDEXED,
    data UNINDEXED,
    conteudo,
    tokenize = "unicode61 remove_diacritics 2"
);

CREATE TABLE IF NOT EXISTS trechos (
    id          INTEGER PRIMARY KEY,
    nome        TEXT NOT NULL,
    data        TEXT NOT NULL,
    grupos      TEXT,
    termos      TEXT,
    peso        INTEGER,
    texto       TEXT NOT NULL,
    sha_trecho  TEXT UNIQUE
);
CREATE INDEX IF NOT EXISTS ix_trechos_data ON trechos(data);

CREATE VIRTUAL TABLE IF NOT EXISTS busca_trechos USING fts5(
    nome UNINDEXED, data UNINDEXED, texto,
    tokenize = "unicode61 remove_diacritics 2"
);

CREATE TABLE IF NOT EXISTS achados (
    id           INTEGER PRIMARY KEY,
    regra        TEXT, severidade TEXT, titulo TEXT, detalhe TEXT,
    documento    TEXT, data_ref TEXT, detectado_em TEXT,
    fundamento   TEXT, chave TEXT UNIQUE
);

CREATE TABLE IF NOT EXISTS cobertura (
    data       TEXT PRIMARY KEY,
    dia_semana INTEGER,
    situacao   TEXT,     -- coletado | sem_edicao | ausente_no_indice | falha
    nome       TEXT,
    verificado_em TEXT
);
"""


def conectar() -> sqlite3.Connection:
    BANCO.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(BANCO)
    c.executescript(ESQUEMA)
    return c


def _texto_de(nome: str) -> str:
    base = nome[:-4] if nome.endswith(".pdf") else nome
    p = TXT / f"{base}.txt"
    if p.exists():
        return p.read_text(encoding="utf-8", errors="ignore")
    pg = TXTGZ / f"{base}.txt.gz"
    if pg.exists():
        return gzip.decompress(pg.read_bytes()).decode("utf-8", errors="ignore")
    return ""


def indexar() -> dict:
    reg = json.loads(REGISTRO.read_text(encoding="utf-8")) if REGISTRO.exists() else {}
    c = conectar()
    n_doc = n_txt = 0
    for nome, meta in reg.items():
        if meta.get("erro"):
            continue
        m = re.match(r"([a-z]+)_(\d{8})_(\d+)", nome, re.I)
        tipo = m.group(1).lower() if m else "outro"
        edicao = int(m.group(3)) if m else None
        c.execute(
            "INSERT OR REPLACE INTO documentos VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (nome, meta["data"], int(meta["data"][:4]), tipo, edicao, meta["url"],
             meta["sha256"], meta.get("bytes"), meta.get("caracteres"),
             int(bool(meta.get("ocr"))), json.dumps(meta.get("termos", []), ensure_ascii=False)),
        )
        n_doc += 1
        ja = c.execute("SELECT 1 FROM busca WHERE nome=?", (nome,)).fetchone()
        if not ja:
            t = _texto_de(nome)
            if t:
                c.execute("INSERT INTO busca (nome,data,conteudo) VALUES (?,?,?)",
                          (nome, meta["data"], t))
                n_txt += 1
    c.commit()
    tam = BANCO.stat().st_size / 1e6
    c.close()
    return {"documentos": n_doc, "textos_indexados": n_txt, "banco_mb": round(tam, 1)}


def buscar(consulta: str, ano: int | None = None, limite: int = 20,
           trechos: bool = False) -> list[dict]:
    c = conectar()
    tabela = "busca_trechos" if trechos else "busca"
    campo = "texto" if trechos else "conteudo"
    sql = (f"SELECT nome, data, snippet({tabela}, 2, '»', '«', ' … ', 24) AS trecho, "
           f"bm25({tabela}) AS rank FROM {tabela} WHERE {tabela} MATCH ?")
    par: list = [consulta]
    if ano:
        sql += " AND data LIKE ?"
        par.append(f"{ano}%")
    sql += " ORDER BY rank LIMIT ?"
    par.append(limite)
    try:
        linhas = c.execute(sql, par).fetchall()
    except sqlite3.OperationalError as e:
        print(f"Consulta inválida: {e}", file=sys.stderr)
        return []
    saida = [{"nome": a, "data": b, "trecho": re.sub(r"\s+", " ", d), "rank": r}
             for a, b, d, r in linhas]
    c.close()
    return saida


def estatisticas() -> dict:
    c = conectar()
    q = lambda s: c.execute(s).fetchone()[0]
    est = {
        "documentos": q("SELECT COUNT(*) FROM documentos"),
        "textos": q("SELECT COUNT(*) FROM busca"),
        "trechos": q("SELECT COUNT(*) FROM trechos"),
        "achados": q("SELECT COUNT(*) FROM achados"),
        "periodo": c.execute("SELECT MIN(data), MAX(data) FROM documentos").fetchone(),
        "caracteres": q("SELECT COALESCE(SUM(caracteres),0) FROM documentos"),
        "por_ano": dict(c.execute(
            "SELECT ano, COUNT(*) FROM documentos GROUP BY ano ORDER BY ano").fetchall()),
    }
    c.close()
    return est


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Banco de busca local do CMASGyn")
    ap.add_argument("comando", choices=["indexar", "buscar", "stats"])
    ap.add_argument("consulta", nargs="?", default="")
    ap.add_argument("--ano", type=int)
    ap.add_argument("--limite", type=int, default=20)
    ap.add_argument("--trechos", action="store_true")
    a = ap.parse_args()

    if a.comando == "indexar":
        print(json.dumps(indexar(), ensure_ascii=False, indent=2))
    elif a.comando == "stats":
        print(json.dumps(estatisticas(), ensure_ascii=False, indent=2, default=str))
    else:
        for r in buscar(a.consulta, a.ano, a.limite, a.trechos):
            print(f"\n{r['data']}  {r['nome']}\n   {r['trecho'][:400]}")
