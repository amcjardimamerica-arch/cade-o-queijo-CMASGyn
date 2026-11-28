"""Rastreio por hash: cada resposta, cada registro e cada rodada de coleta com a sua impressão digital.

Pedido da titular (28/11/2026): "Ao coletar as informações gere um código hash para rastreio dos
dados e validação de cada informação obtida". São três camadas, todas SHA-256:

1. **Resposta** (tabela ``coletas``). ``sha256`` é o hash dos bytes recebidos, inclusive o corpo de
   uma recusa (404, 500) e a resposta vazia (204). ``requisicao`` é o hash do pedido: método, URL,
   parâmetros ou corpo, data e hora da coleta em UTC (``quando``). Coleta sem resposta (rede caiu,
   não tentada) guarda só a requisição e fica com ``sem_resposta = 1``: a ausência fica marcada.
2. **Registro** (toda linha de toda tabela de dados). O hash é do conteúdo canônico da linha: o JSON
   ordenado dos campos não nulos, com o nome da tabela (``canonico``). O hash não fica na linha, fica
   no selo (``rastreio_selos``): as tabelas de dados não mudam de forma, e nenhum leitor antigo
   quebra. O selo guarda a rodada em que o registro apareceu e a coleta de onde ele saiu
   (``rastreio_origens``: o hash da linha da coleta e o sha256 da resposta).
3. **Rodada** (``rastreio_rodadas``). Cada execução de motores (``historico.rodar``) e cada soma de
   janela da agenda é uma rodada: início, fim, motores, a raiz de Merkle dos selos novos (respostas
   e registros) e o hash da rodada anterior. As rodadas formam uma cadeia.

``verificar`` recalcula tudo: o hash de cada linha contra os selos, a raiz de cada rodada contra os
seus selos e o elo de cada rodada com a anterior, e aponta onde algo foi alterado. Na linha de
comando: ``python -m onisciente rastreio``.

Onde fica: os selos, as origens e as rodadas ficam num arquivo SQLite à parte, ao lado do banco
(``dados/onisciente/rastreio.db`` ao lado de ``historico.db``), anexado à mesma conexão (``ATTACH ...
AS rastreio``). O banco da coleta já beira o limite de 100 MiB por arquivo do GitHub; o rastreio não
pode empurrá-lo para fora. No banco da coleta ficam só as colunas novas de ``coletas``, os gatilhos e
as pendências (``rastreio_pendentes`` e ``rastreio_cursor``: o SQLite não deixa um gatilho gravar em
banco anexado), e as pendências são esvaziadas ao fechar cada rodada.

Privacidade (28/11/2026): o hash de uma linha com CPF completo permite refazer o CPF por força bruta
(com a máscara ``***.NNN.NNN-**`` faltam três dígitos livres). Toda rodada de máscara (modo
``mascara_cpf``) retira, ao fechar, os selos descartados das tabelas que ela mascarou: o hash sai de
``rastreio_selos`` e fica em ``rastreio_retiradas`` só a marca (a tabela, a rodada em que o selo
entrou, a origem, a rodada que retirou, o motivo e o hash do selo novo da linha mascarada). A raiz e o
hash de cada rodada ficam como estão: a cadeia continua conferindo, a raiz das tabelas com folhas
retiradas passa a valer pelo hash da rodada, e o resumo das retiradas entra no detalhe da rodada que
retirou (uma retirada que não está lá é acusada). Rodadas de máscara de antes desta regra têm as
folhas retiradas numa rodada própria (modo ``retirada_privacidade``).

Como a origem chega ao selo: cada tabela de dados tem gatilhos (``AFTER INSERT`` e ``AFTER UPDATE``)
que anotam a linha em ``rastreio_pendentes`` com a coleta corrente (``rastreio_cursor``), que o
``Banco.inserir`` de ``coletas`` atualiza a cada resposta. Assim o motor que grava direto pela conexão
(``con.execute``) também fica rastreado. O ``selar`` transforma as pendências em selos ao fim de cada
motor; o que mudou fora de uma rodada aparece na abertura da rodada seguinte e fica registrado nela.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from . import partes

ZERO = "0" * 64
# Tabelas que não são dados coletados: o próprio rastreio e as anotações de estado da rodada.
FORA = ("meta",)
PREFIXO = "rastreio_"
COLUNAS_COLETAS = {"requisicao": "TEXT", "metodo": "TEXT", "parametros": "TEXT", "sem_resposta": "INTEGER"}
MODO_MIGRACAO = "migracao"
MODO_MASCARA = "mascara_cpf"
MODO_RETIRADA = "retirada_privacidade"
RETIRADO = "retirado por privacidade"
# A raiz guardada de uma tabela que perdeu só k folhas deixa testar 1000^k combinações de CPF (três dígitos
# livres por linha): até 8 (cerca de 2^80) a verificação avisa, sem acusar adulteração.
POUCAS_RETIRADAS = 8
# O selo que a própria rodada de máscara descartou: a linha tinha o CPF completo e foi substituída pela
# mascarada. Os demais selos descartados da mesma tabela, de antes da máscara, saem por precaução: a
# linha já não existe e não há como saber se tinha CPF completo.
MOTIVO_MASCARA = (f"{RETIRADO}: o hash era de uma linha com CPF completo, substituída pela linha com a máscara "
                  "***.NNN.NNN-**")
MOTIVO_PRECAUCAO = (f"{RETIRADO}: selo descartado antes da máscara numa tabela que guardava CPF completo; a linha "
                    "já não existe e o hash sai por precaução")
ANTERIOR_AO_RASTREIO = "anterior ao rastreio"

ESQ = "rastreio"            # o nome do arquivo anexado na conexão (ATTACH ... AS rastreio)
# No arquivo do rastreio (rastreio.db). O hash do selo é BLOB de 32 bytes; a exibição é sempre em hex.
ESQUEMA_RASTREIO = {
    "rastreio_tabelas": "(id INTEGER PRIMARY KEY, nome TEXT UNIQUE NOT NULL)",
    "rastreio_origens": "(id INTEGER PRIMARY KEY, coleta BLOB UNIQUE NOT NULL, resposta TEXT, requisicao TEXT)",
    "rastreio_selos": "(tabela INTEGER NOT NULL, hash BLOB NOT NULL, rodada INTEGER NOT NULL, origem INTEGER, "
                      "n INTEGER NOT NULL DEFAULT 1, descartada INTEGER, PRIMARY KEY (tabela, hash)) WITHOUT ROWID",
    "rastreio_retiradas": "(id INTEGER PRIMARY KEY, tabela INTEGER NOT NULL, rodada INTEGER NOT NULL, origem INTEGER, "
                          "n INTEGER NOT NULL, descartada INTEGER, retirada_por INTEGER NOT NULL, motivo TEXT NOT NULL, "
                          "novo BLOB)",
    "rastreio_rodadas": "(id INTEGER PRIMARY KEY, inicio TEXT, fim TEXT, modo TEXT, motores TEXT, respostas INTEGER, "
                        "registros INTEGER, raiz TEXT, tabelas TEXT, abertura TEXT, descartes TEXT, detalhe TEXT, "
                        "anterior TEXT, hash TEXT, herdada INTEGER NOT NULL DEFAULT 0)",
}
# No banco da coleta (os gatilhos só gravam no próprio banco). Vazias fora de rodada.
ESQUEMA_LOCAL = {
    "rastreio_pendentes": "(tabela TEXT NOT NULL, linha INTEGER NOT NULL, origem INTEGER, "
                          "PRIMARY KEY (tabela, linha)) WITHOUT ROWID",
    "rastreio_cursor": "(chave TEXT PRIMARY KEY, valor INTEGER)",
}


def agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- Hash canônico -----------------------------------------------------------------------------

def _valor(v):
    if isinstance(v, (bytes, bytearray, memoryview)):
        return {"$hex": bytes(v).hex()}
    return v


def canonico(tabela: str, campos: dict) -> bytes:
    """A forma canônica de um registro: JSON ordenado dos campos não nulos, com o nome da tabela.

    Os nulos ficam de fora para que uma coluna nova (que chega nula nas linhas antigas) não mude o
    hash do que já foi coletado; um campo que passa de um valor a nulo continua mudando o hash."""
    corpo = {k: _valor(v) for k, v in campos.items() if v is not None}
    return json.dumps({"tabela": tabela, "campos": corpo}, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=True).encode("utf-8")


def _digest(tabela: str, campos: dict) -> bytes:
    return hashlib.sha256(canonico(tabela, campos)).digest()


def hash_registro(tabela: str, campos: dict) -> str:
    """O hash (hex) de um registro, como o selo o guarda."""
    return _digest(tabela, campos).hex()


def hash_requisicao(metodo: str | None, url: str | None, parametros: str | None, quando: str | None) -> str:
    """O hash do pedido: método, URL, parâmetros (ou corpo) e data e hora da coleta em UTC."""
    texto = json.dumps({"metodo": metodo or "GET", "url": url or "", "parametros": parametros, "quando": quando},
                       sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def parametros_canonicos(parametros) -> str | None:
    """Os parâmetros ou o corpo de um pedido numa forma estável (JSON ordenado), ou None."""
    if parametros in (None, "", {}, b""):
        return None
    if isinstance(parametros, (bytes, bytearray)):
        return json.dumps({"$hex": bytes(parametros).hex()})
    if isinstance(parametros, str):
        return parametros
    return json.dumps(parametros, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def merkle(folhas: Iterable[bytes]) -> bytes:
    """Raiz de Merkle (SHA-256) das folhas em ordem; sem folhas, o hash do vazio."""
    nivel = list(folhas)
    if not nivel:
        return hashlib.sha256(b"").digest()
    while len(nivel) > 1:
        if len(nivel) % 2:
            nivel.append(nivel[-1])
        nivel = [hashlib.sha256(nivel[i] + nivel[i + 1]).digest() for i in range(0, len(nivel), 2)]
    return nivel[0]


def raiz_de(hashes: Iterable[str]) -> str:
    """A raiz (hex) de uma lista de hashes hex, em ordem: o resumo de um conjunto de registros."""
    return merkle(bytes.fromhex(h) for h in sorted(set(h for h in hashes if h))).hex()


def _folha(tabela: str, h: bytes, coleta: bytes | None, resposta: str | None) -> bytes:
    """A folha de um selo: a tabela, o hash do registro e a ligação com a origem."""
    return hashlib.sha256(tabela.encode() + b"\0" + h + b"\0" + (coleta or b"") + b"\0"
                          + (resposta or "").encode()).digest()


def _hash_rodada(r: dict) -> str:
    campos = {k: r.get(k) for k in ("id", "inicio", "fim", "modo", "motores", "respostas", "registros", "raiz",
                                     "tabelas", "abertura", "descartes", "detalhe", "anterior")}
    texto = json.dumps(campos, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def hash_achado(ficha: dict) -> str:
    """O hash de um achado (ficha) no formato de ``Ficha.como_dict`` sem a chave ``rastreio``."""
    corpo = {k: v for k, v in ficha.items() if k != "rastreio"}
    texto = json.dumps(corpo, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def curto(h: str | None, n: int = 12) -> str:
    return (h or "")[:n]


# --- Esquema ------------------------------------------------------------------------------------

def _tabelas(con) -> dict[str, str]:
    return {n: (s or "") for n, s in con.execute(
        "SELECT name, sql FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")}


def _tabelas_rastreio(con) -> set[str]:
    """As tabelas do rastreio que a conexão enxerga: as do arquivo anexado (e as de um banco antigo,
    de antes da separação, que ainda as tenha dentro de si)."""
    nomes = {n for n in _tabelas(con) if n in ESQUEMA_RASTREIO}
    if anexado(con):
        nomes |= {n for (n,) in con.execute(f"SELECT name FROM {ESQ}.sqlite_master WHERE type = 'table'")}
    return nomes


def caminho_do_rastreio(caminho) -> Path:
    """O arquivo do rastreio de um banco: ``rastreio.db`` ao lado de ``historico.db``; para outro nome
    (a janela da agenda, um teste), ``<nome>.rastreio.db`` ao lado dele."""
    p = Path(caminho)
    if p.name == "historico.db":
        return p.with_name("rastreio.db")
    return p.with_name(f"{p.stem}.rastreio{p.suffix or '.db'}")


def _arquivo_principal(con) -> str:
    for _, nome, arquivo in con.execute("PRAGMA database_list"):
        if nome == "main":
            return arquivo or ""
    return ""


def anexado(con) -> bool:
    return any(nome == ESQ for _, nome, _ in con.execute("PRAGMA database_list"))


def anexar(con, *, somente_leitura: bool = False) -> bool:
    """Anexa à conexão o arquivo do rastreio do banco (``ATTACH ... AS rastreio``). Para gravar, cria o
    arquivo se faltar; para ler, só anexa o que existe. Devolve se ficou anexado."""
    if anexado(con):
        return True
    principal = _arquivo_principal(con)
    if principal:
        destino = caminho_do_rastreio(principal)
        if somente_leitura and not destino.exists():
            return False
        alvo = str(destino)
    elif somente_leitura:
        return False
    else:
        alvo = ":memory:"                       # banco em memória: o rastreio também
    try:
        con.execute(f"ATTACH DATABASE ? AS {ESQ}", (alvo,))
    except sqlite3.Error:
        if somente_leitura:
            return False
        raise
    return True


def _ler(con) -> None:
    """Antes de uma leitura: anexa o rastreio se a conexão ainda não o tem (conexão só de leitura)."""
    if not anexado(con):
        try:
            anexar(con, somente_leitura=True)
        except sqlite3.Error:
            pass


def _tabelas_de_dados_com_esquema(con) -> dict[str, str]:
    """Nome -> esquema de cada tabela de dados: as do banco e as das partes anexadas (precos.db,
    sancoes.db), menos o próprio rastreio e ``meta``."""
    saida: dict[str, str] = {}
    for esquema in partes.esquemas(con):
        for nome, sql in con.execute(f"SELECT name, sql FROM {esquema}.sqlite_master WHERE type = 'table' "
                                     "AND name NOT LIKE 'sqlite_%'"):
            if nome.startswith(PREFIXO) or nome in FORA or nome in partes.INTERNAS or nome in saida:
                continue
            s = (sql or "").upper()
            if "VIRTUAL TABLE" in s or "WITHOUT ROWID" in s:
                continue
            saida[nome] = esquema
    return dict(sorted(saida.items()))


def tabelas_de_dados(con) -> list[str]:
    """Toda tabela de dados do banco (e das partes): todas, menos o próprio rastreio e ``meta``."""
    return list(_tabelas_de_dados_com_esquema(con))


def tem_rastreio(con) -> bool:
    return "rastreio_selos" in _tabelas_rastreio(con)


def _colunas(con, tabela: str) -> list[str]:
    return [c[1] for c in con.execute(f'PRAGMA table_info("{tabela}")')]


def _gatilho(t: str, quando: str) -> str:
    # Só anota com a rodada aberta: o que muda fora de rodada não deixa pendência no banco (e aparece
    # como "sem selo" na conferência da abertura seguinte).
    return (f'AFTER {quando} ON "{t}" WHEN (SELECT valor FROM rastreio_cursor WHERE chave = \'rodada\') IS NOT NULL '
            f"BEGIN INSERT OR REPLACE INTO rastreio_pendentes (tabela, linha, origem) VALUES ('{t}', NEW.rowid, "
            "(SELECT valor FROM rastreio_cursor WHERE chave = 'origem')); END")


def _gatilho_temporario(esquema: str, t: str, quando: str) -> str:
    # Tabela numa parte anexada (precos.db, sancoes.db): o SQLite não deixa um gatilho guardado num
    # arquivo gravar noutro, mas o gatilho TEMP (da conexão) pode. O Banco o recria a cada abertura.
    return (f'AFTER {quando} ON {esquema}."{t}" WHEN (SELECT valor FROM rastreio_cursor WHERE chave = \'rodada\') '
            f"IS NOT NULL BEGIN INSERT OR REPLACE INTO rastreio_pendentes (tabela, linha, origem) VALUES ('{t}', "
            "NEW.rowid, (SELECT valor FROM rastreio_cursor WHERE chave = 'origem')); END")


def _separar_banco_antigo(con) -> None:
    """Banco de antes da separação, com o rastreio dentro de si: as tabelas vão para o arquivo do
    rastreio e saem do banco da coleta."""
    tabelas = _tabelas(con)
    for nome in ESQUEMA_RASTREIO:
        if nome in tabelas:
            con.execute(f"INSERT OR IGNORE INTO {ESQ}.{nome} SELECT * FROM main.{nome}")
            con.execute(f"DROP TABLE main.{nome}")
    con.commit()


def preparar(con) -> None:
    """Anexa o arquivo do rastreio e cria nele as tabelas; cria no banco as pendências, as colunas novas
    de ``coletas`` e os gatilhos de cada tabela de dados. Idempotente: pode (e deve) ser chamado de novo
    quando um motor cria uma tabela."""
    anexar(con)
    no_rastreio = {n for (n,) in con.execute(f"SELECT name FROM {ESQ}.sqlite_master WHERE type = 'table'")}
    for nome, corpo in ESQUEMA_RASTREIO.items():
        if nome not in no_rastreio:
            con.execute(f"CREATE TABLE IF NOT EXISTS {ESQ}.{nome} {corpo}")
    tabelas = _tabelas(con)
    if any(n in tabelas for n in ESQUEMA_RASTREIO):
        _separar_banco_antigo(con)
        tabelas = _tabelas(con)
    for nome, corpo in ESQUEMA_LOCAL.items():
        if nome not in tabelas:
            con.execute(f"CREATE TABLE IF NOT EXISTS main.{nome} {corpo}")
    if "coletas" in tabelas:
        existentes = set(_colunas(con, "coletas"))
        for coluna, tipo in COLUNAS_COLETAS.items():
            if coluna not in existentes:
                con.execute(f"ALTER TABLE coletas ADD COLUMN {coluna} {tipo}")
    gatilhos = dict(con.execute("SELECT name, sql FROM main.sqlite_master WHERE type = 'trigger'"))
    temporarios = {n for (n,) in con.execute("SELECT name FROM temp.sqlite_master WHERE type = 'trigger'")}
    for t, esquema in _tabelas_de_dados_com_esquema(con).items():
        for quando, sufixo in (("INSERT", "i"), ("UPDATE", "u")):
            nome = f"rastreio_{sufixo}_{t}"
            if esquema != "main":
                if nome not in temporarios:
                    con.execute(f'CREATE TEMP TRIGGER "{nome}" {_gatilho_temporario(esquema, t, quando)}')
                continue
            corpo = _gatilho(t, quando)
            if nome in gatilhos:
                if corpo in (gatilhos[nome] or ""):
                    continue
                con.execute(f'DROP TRIGGER "{nome}"')          # gatilho de uma versão anterior
            con.execute(f'CREATE TRIGGER "{nome}" {corpo}')


def versao_do_esquema(con) -> int:
    return con.execute("PRAGMA schema_version").fetchone()[0]


def _id_tabela(con, nome: str) -> int:
    linha = con.execute("SELECT id FROM rastreio_tabelas WHERE nome = ?", (nome,)).fetchone()
    if linha:
        return linha[0]
    return con.execute("INSERT INTO rastreio_tabelas (nome) VALUES (?)", (nome,)).lastrowid


def _nomes_das_tabelas(con) -> dict[int, str]:
    return dict(con.execute("SELECT id, nome FROM rastreio_tabelas"))


def _linhas(con, tabela: str):
    """(rowid, campos) de cada linha da tabela."""
    cur = con.execute(f'SELECT rowid, * FROM "{tabela}"')
    nomes = [d[0] for d in cur.description][1:]
    for linha in cur:
        yield linha[0], dict(zip(nomes, linha[1:]))


def linha(con, tabela: str, rowid: int) -> dict | None:
    cur = con.execute(f'SELECT * FROM "{tabela}" WHERE rowid = ?', (rowid,))
    r = cur.fetchone()
    return dict(zip([d[0] for d in cur.description], r)) if r else None


# --- Coletas: a resposta e a requisição ---------------------------------------------------------

def completar_coleta(linha: dict, colunas: Iterable[str], respostas: dict[str, str] | None = None) -> dict:
    """Completa uma linha de ``coletas`` com o rastreio: método, parâmetros, hash da requisição e a
    marca de ausência. Uma anotação sobre uma resposta já registrada (falha de formato, que vem sem
    bytes) herda o sha256 dessa resposta pela URL."""
    colunas = set(colunas)
    linha = dict(linha)
    metodo = linha.pop("metodo", None)
    parametros = parametros_canonicos(linha.pop("parametros", None))
    if linha.get("sha256") is None and respostas and not linha.get("bytes") and not linha.get("ok") \
            and linha.get("http") is None and linha.get("url") in respostas:
        linha["sha256"] = respostas[linha["url"]]       # anotação sobre a resposta já lida
    linha.setdefault("quando", agora())
    metodo = metodo or ("POST" if parametros else "GET")
    extra = {"metodo": metodo, "parametros": parametros,
             "requisicao": hash_requisicao(metodo, linha.get("url"), parametros, linha.get("quando")),
             "sem_resposta": 0 if linha.get("sha256") else 1}
    linha.update({k: v for k, v in extra.items() if k in colunas})
    return linha


def registrar_origem(con, rowid: int) -> int | None:
    """Depois de gravada uma linha de ``coletas``: guarda a origem (hash da linha da coleta e sha256 da
    resposta) e aponta o cursor para ela, para os registros que o motor gravar em seguida. Coleta sem
    resposta zera o cursor (nada do que vier depois sai dela). Devolve o id da origem."""
    campos = linha(con, "coletas", rowid)
    if campos is None:
        return None
    resposta = campos.get("sha256")
    anotacao = not campos.get("tentativas") and not campos.get("bytes") and not campos.get("ok") \
        and campos.get("http") is None
    if anotacao and resposta:
        return None                                   # anotação sobre a resposta anterior: o cursor fica
    origem = None
    if resposta:
        h = _digest("coletas", campos)
        con.execute("INSERT OR IGNORE INTO rastreio_origens (coleta, resposta, requisicao) VALUES (?, ?, ?)",
                    (h, resposta, campos.get("requisicao")))
        origem = con.execute("SELECT id FROM rastreio_origens WHERE coleta = ?", (h,)).fetchone()[0]
    con.execute("INSERT OR REPLACE INTO rastreio_cursor (chave, valor) VALUES ('origem', ?)", (origem,))
    return origem


# --- Selos --------------------------------------------------------------------------------------

def selar(con, rodada: int, *, todas: bool = False) -> dict[str, int]:
    """Sela o que mudou desde o último selo: registro novo ganha selo (com a origem anotada pelo
    gatilho), selo cujo registro saiu fica marcado como descartado por esta rodada, e a contagem de
    linhas iguais é atualizada. Só as tabelas que mudaram são lidas por inteiro."""
    preparar(con)
    pend: dict[str, dict[int, int | None]] = {}
    for t, linha_, origem in con.execute("SELECT tabela, linha, origem FROM rastreio_pendentes"):
        pend.setdefault(t, {})[linha_] = origem
    novos = descartados = 0
    for t in tabelas_de_dados(con):
        tid = _id_tabela(con, t)
        selados = con.execute("SELECT coalesce(sum(n), 0) FROM rastreio_selos WHERE tabela = ? AND descartada IS NULL",
                              (tid,)).fetchone()[0]
        total = con.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
        if not todas and t not in pend and total == selados:
            continue
        ativos = dict(con.execute("SELECT hash, n FROM rastreio_selos WHERE tabela = ? AND descartada IS NULL",
                                  (tid,)))
        contagem: Counter = Counter()
        origem_de: dict[bytes, int | None] = {}
        anotadas = pend.get(t, {})
        for rowid, campos in _linhas(con, t):
            h = _digest(t, campos)
            contagem[h] += 1
            if origem_de.get(h) is None:
                origem_de[h] = anotadas.get(rowid)
        for h, n in contagem.items():
            if h not in ativos:
                con.execute("INSERT INTO rastreio_selos (tabela, hash, rodada, origem, n) VALUES (?, ?, ?, ?, ?) "
                            "ON CONFLICT (tabela, hash) DO UPDATE SET descartada = NULL, n = excluded.n",
                            (tid, h, rodada, origem_de.get(h), n))
                novos += 1
            elif ativos[h] != n:
                con.execute("UPDATE rastreio_selos SET n = ? WHERE tabela = ? AND hash = ?", (n, tid, h))
        for h in ativos.keys() - contagem.keys():
            con.execute("UPDATE rastreio_selos SET descartada = ? WHERE tabela = ? AND hash = ?", (rodada, tid, h))
            descartados += 1
    con.execute("DELETE FROM main.rastreio_pendentes")
    return {"novos": novos, "descartados": descartados}


def _rodada_aberta(con) -> int | None:
    linha_ = con.execute("SELECT id FROM rastreio_rodadas WHERE fim IS NULL AND herdada = 0 "
                         "ORDER BY id DESC LIMIT 1").fetchone()
    return linha_[0] if linha_ else None


def abrir_rodada(con, motores: Iterable[str] = (), modo: str = "coleta", *, detalhe: dict | None = None,
                 conferir: bool = True) -> int:
    """Abre uma rodada. Antes, confere o banco inteiro (``conferir``): o que mudou desde a rodada
    anterior, fora de qualquer rodada, fica registrado na abertura desta e entra na cadeia."""
    preparar(con)
    aberta = _rodada_aberta(con)
    if aberta is not None:
        fechar_rodada(con, aberta, nota="rodada interrompida, fechada na abertura da seguinte")
    abertura = None
    if conferir and con.execute("SELECT 1 FROM rastreio_rodadas LIMIT 1").fetchone():
        abertura = _resumo_abertura(verificar_registros(con, pendentes=False))
    # O que foi gravado fora de rodada não tem origem conhecida: fica na abertura e é selado sem origem.
    con.execute("DELETE FROM main.rastreio_pendentes")
    rid = con.execute(
        "INSERT INTO rastreio_rodadas (inicio, modo, motores, abertura, detalhe) VALUES (?, ?, ?, ?, ?)",
        (agora(), modo, json.dumps(list(motores), ensure_ascii=False),
         json.dumps(abertura, ensure_ascii=False, sort_keys=True) if abertura else None,
         json.dumps(detalhe, ensure_ascii=False, sort_keys=True) if detalhe else None)).lastrowid
    con.execute("INSERT OR REPLACE INTO rastreio_cursor (chave, valor) VALUES ('origem', NULL)")
    con.execute("INSERT OR REPLACE INTO rastreio_cursor (chave, valor) VALUES ('rodada', ?)", (rid,))
    if modo == MODO_MASCARA:
        _guardar_antes(con)
    con.commit()
    return rid


# --- Retirada por privacidade -------------------------------------------------------------------

def _guardar_antes(con) -> None:
    """Rodada de máscara: gatilhos TEMP guardam, de cada linha alterada, o conteúdo de antes (só na
    memória da conexão), para a retirada apontar o selo novo de cada selo retirado. Saem ao fechar."""
    con.execute("CREATE TEMP TABLE IF NOT EXISTS rastreio_antes (tabela TEXT, linha INTEGER, campos TEXT, "
                "PRIMARY KEY (tabela, linha))")
    for t, esquema in _tabelas_de_dados_com_esquema(con).items():
        cols = _colunas_em(con, esquema, t)
        if not cols:
            continue
        pares = ", ".join(f"'{c}', json_array(typeof(OLD.\"{c}\"), CASE typeof(OLD.\"{c}\") WHEN 'blob' "
                          f"THEN hex(OLD.\"{c}\") WHEN 'real' THEN printf('%!.17g', OLD.\"{c}\") "
                          f"ELSE OLD.\"{c}\" END)" for c in cols)
        con.execute(f'DROP TRIGGER IF EXISTS temp."rastreio_a_{t}"')
        con.execute(f'CREATE TEMP TRIGGER "rastreio_a_{t}" AFTER UPDATE ON {esquema}."{t}" BEGIN '
                    f"INSERT OR IGNORE INTO rastreio_antes VALUES ('{t}', OLD.rowid, json_object({pares})); END")


def _colunas_em(con, esquema: str, tabela: str) -> list[str]:
    return [c[1] for c in con.execute(f'PRAGMA {esquema}.table_info("{tabela}")')]


def _soltar_antes(con) -> dict[str, dict[int, dict]]:
    """O conteúdo de antes das linhas alteradas na rodada de máscara, por tabela e linha; e limpa."""
    antes: dict[str, dict[int, dict]] = {}
    try:
        linhas = con.execute("SELECT tabela, linha, campos FROM temp.rastreio_antes").fetchall()
    except sqlite3.OperationalError:
        return antes
    for t, rowid, campos in linhas:
        valores = {}
        for c, (tipo, v) in json.loads(campos).items():
            valores[c] = (None if tipo == "null" else bytes.fromhex(v) if tipo == "blob" else int(v)
                          if tipo == "integer" else float(v) if tipo == "real" else v)
        antes.setdefault(t, {})[rowid] = valores
    con.execute("DELETE FROM temp.rastreio_antes")
    for (nome,) in con.execute("SELECT name FROM temp.sqlite_master WHERE type = 'trigger' "
                               "AND name LIKE 'rastreio_a_%'").fetchall():
        con.execute(f'DROP TRIGGER temp."{nome}"')
    return antes


def _retirar(con, rid: int, modo: str) -> dict | None:
    """Retira os selos descartados das tabelas que a rodada de máscara mascarou: o hash sai de
    ``rastreio_selos`` e fica em ``rastreio_retiradas`` só a marca. Saem o que a própria rodada
    descartou (a linha com CPF completo) e, por precaução, os descartados antes dela na mesma tabela.
    Na rodada de retirada (``retirada_privacidade``), o mesmo para as tabelas que rodadas de máscara
    anteriores a esta regra mascararam. Devolve o resumo que entra no detalhe da rodada (None se nada saiu)."""
    antes = _soltar_antes(con) if modo == MODO_MASCARA else {}
    mascaras = {rid} if modo == MODO_MASCARA else {
        i for (i,) in con.execute("SELECT id FROM rastreio_rodadas WHERE modo = ?", (MODO_MASCARA,))}
    alvo = sorted({tid for (tid,) in con.execute(
        f"SELECT DISTINCT tabela FROM rastreio_selos WHERE descartada IN ({','.join('?' * len(mascaras))})",
        sorted(mascaras))}) if mascaras else []
    if not alvo:
        return None
    nomes = _nomes_das_tabelas(con)
    novo_de: dict[tuple[int, bytes], bytes] = {}
    for t, linhas in antes.items():
        tid = _id_tabela(con, t)
        for rowid, campos in linhas.items():
            atual = linha(con, t, rowid)
            if atual is not None:
                novo_de[(tid, _digest(t, campos))] = _digest(t, atual)
    # O SQLite deixa o conteúdo apagado nas páginas livres do arquivo: com secure_delete, os bytes do hash
    # retirado são zerados no próprio arquivo (o rastreio.db vai ao repositório público).
    con.execute(f"PRAGMA {ESQ if anexado(con) else 'main'}.secure_delete = ON")
    marcas: list[str] = []
    por_tabela: Counter = Counter()
    por_motivo: Counter = Counter()
    for tid in alvo:
        selos = con.execute("SELECT hash, rodada, origem, n, descartada FROM rastreio_selos WHERE tabela = ? "
                            "AND descartada IS NOT NULL AND descartada <= ? ORDER BY hash", (tid, rid)).fetchall()
        for h, rodada, origem, n, descartada in selos:
            novo = novo_de.get((tid, h))
            motivo = MOTIVO_MASCARA if descartada in mascaras else MOTIVO_PRECAUCAO
            con.execute("INSERT INTO rastreio_retiradas (tabela, rodada, origem, n, descartada, retirada_por, motivo, "
                        "novo) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (tid, rodada, origem, n, descartada, rid, motivo, novo))
            con.execute("DELETE FROM rastreio_selos WHERE tabela = ? AND hash = ?", (tid, h))
            nome = nomes.get(tid, str(tid))
            marcas.append(_linha_retirada(nome, rodada, origem, n, descartada, motivo, novo))
            por_tabela[nome] += 1
            por_motivo[motivo] += 1
    if not marcas:
        return None
    return {"total": len(marcas), "por_tabela": dict(sorted(por_tabela.items())),
            "motivos": dict(sorted(por_motivo.items())), "resumo": _resumo_das_marcas(marcas)}


def _linha_retirada(nome: str, rodada, origem, n, descartada, motivo, novo) -> str:
    return f"{nome}|{rodada}|{origem}|{n}|{descartada}|{motivo}|{novo.hex() if novo else ''}"


def _resumo_das_marcas(marcas: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(marcas)).encode("utf-8")).hexdigest()


def retiradas(con) -> list[dict]:
    """As marcas das folhas retiradas (sem hash): tabela, rodada do selo, rodada que retirou, motivo e
    o hash do selo novo da linha mascarada (quando a retirada foi na própria rodada da máscara)."""
    _ler(con)
    if "rastreio_retiradas" not in _tabelas_rastreio(con):
        return []
    nomes = _nomes_das_tabelas(con)
    cur = con.execute("SELECT id, tabela, rodada, origem, n, descartada, retirada_por, motivo, novo "
                      "FROM rastreio_retiradas ORDER BY id")
    campos = [d[0] for d in cur.description]
    saida = []
    for r in cur:
        x = dict(zip(campos, r))
        x["tabela"] = nomes.get(x["tabela"], str(x["tabela"]))
        x["novo"] = x["novo"].hex() if x["novo"] else None
        saida.append(x)
    return saida


def _resumo_abertura(v: dict) -> dict | None:
    """O que a conferência da abertura achou fora do lugar (vazio quando nada mudou fora de rodada)."""
    saida = {}
    for chave in ("sem_selo", "sumidos"):
        itens = v.get(chave) or []
        if itens:
            saida[chave] = {"total": len(itens), "exemplos": [
                {k: x[k] for k in ("tabela", "linha", "hash", "rodada") if k in x} for x in itens[:10]]}
    return saida or None


def _folhas_por_rodada(con) -> dict[int, dict[str, list[bytes]]]:
    nomes = _nomes_das_tabelas(con)
    saida: dict[int, dict[str, list[bytes]]] = {}
    for tid, h, rodada, coleta, resposta in con.execute(
            "SELECT s.tabela, s.hash, s.rodada, o.coleta, o.resposta FROM rastreio_selos s "
            "LEFT JOIN rastreio_origens o ON o.id = s.origem"):
        nome = nomes.get(tid, str(tid))
        saida.setdefault(rodada, {}).setdefault(nome, []).append(_folha(nome, h, coleta, resposta))
    return saida


def _raizes(folhas: dict[str, list[bytes]]) -> tuple[str, dict[str, list]]:
    todas = sorted(f for fs in folhas.values() for f in fs)
    por_tabela = {t: [len(fs), merkle(sorted(fs)).hex()] for t, fs in sorted(folhas.items())}
    return merkle(todas).hex(), por_tabela


def _folhas_da_rodada(con, rid: int) -> dict[str, list[bytes]]:
    nomes = _nomes_das_tabelas(con)
    saida: dict[str, list[bytes]] = {}
    for tid, h, coleta, resposta in con.execute(
            "SELECT s.tabela, s.hash, o.coleta, o.resposta FROM rastreio_selos s "
            "LEFT JOIN rastreio_origens o ON o.id = s.origem WHERE s.rodada = ?", (rid,)):
        nome = nomes.get(tid, str(tid))
        saida.setdefault(nome, []).append(_folha(nome, h, coleta, resposta))
    return saida


def fechar_rodada(con, rid: int, *, nota: str | None = None) -> dict:
    """Fecha a rodada: sela o que falta, calcula a raiz de Merkle dos selos novos, liga a rodada à
    anterior pelo hash e grava o hash da própria rodada."""
    selar(con, rid)
    modo = con.execute("SELECT modo FROM rastreio_rodadas WHERE id = ?", (rid,)).fetchone()[0]
    retiradas = _retirar(con, rid, modo) if modo in (MODO_MASCARA, MODO_RETIRADA) else None
    folhas = _folhas_da_rodada(con, rid)
    raiz, por_tabela = _raizes(folhas)
    respostas = len(folhas.get("coletas", []))
    registros = sum(len(v) for k, v in folhas.items() if k != "coletas")
    nomes = _nomes_das_tabelas(con)
    descartes: dict[str, dict[str, int]] = {}
    for tid, origem, n in con.execute("SELECT tabela, rodada, count(*) FROM rastreio_selos WHERE descartada = ? "
                                      "GROUP BY tabela, rodada", (rid,)):
        descartes.setdefault(str(origem), {})[nomes.get(tid, str(tid))] = n
    linha_ = con.execute("SELECT hash FROM rastreio_rodadas WHERE id < ? AND hash IS NOT NULL ORDER BY id DESC "
                         "LIMIT 1", (rid,)).fetchone()
    anterior = linha_[0] if linha_ else ZERO
    r = dict(zip(("id", "inicio", "modo", "motores", "abertura", "detalhe"), con.execute(
        "SELECT id, inicio, modo, motores, abertura, detalhe FROM rastreio_rodadas WHERE id = ?", (rid,)).fetchone()))
    if nota or retiradas:
        det = json.loads(r["detalhe"]) if r["detalhe"] else {}
        if nota:
            det["nota"] = nota
        if retiradas:
            det["retiradas"] = retiradas
        r["detalhe"] = json.dumps(det, ensure_ascii=False, sort_keys=True)
    r.update(fim=agora(), respostas=respostas, registros=registros, raiz=raiz,
             tabelas=json.dumps(por_tabela, sort_keys=True), descartes=json.dumps(descartes, sort_keys=True),
             anterior=anterior)
    r["hash"] = _hash_rodada(r)
    con.execute("UPDATE rastreio_rodadas SET fim = ?, respostas = ?, registros = ?, raiz = ?, tabelas = ?, "
                "descartes = ?, detalhe = ?, anterior = ?, hash = ? WHERE id = ?",
                (r["fim"], respostas, registros, raiz, r["tabelas"], r["descartes"], r["detalhe"], anterior,
                 r["hash"], rid))
    con.execute("DELETE FROM rastreio_cursor WHERE chave = 'rodada'")
    con.execute("INSERT OR REPLACE INTO rastreio_cursor (chave, valor) VALUES ('origem', NULL)")
    con.commit()
    if retiradas:
        # A árvore do índice guarda cópias de chaves nas páginas internas (divisórias), que o DELETE não
        # apaga nem o secure_delete zera: o VACUUM refaz o arquivo só com o que ficou.
        con.execute(f"VACUUM {ESQ if anexado(con) else 'main'}")
    return r


def rodada_corrente(con) -> int | None:
    linha_ = con.execute("SELECT valor FROM rastreio_cursor WHERE chave = 'rodada'").fetchone() \
        if "rastreio_cursor" in _tabelas(con) else None
    return linha_[0] if linha_ else None


def migrar(con) -> int | None:
    """Banco anterior ao rastreio: cada linha que já existe ganha o seu selo, numa rodada de migração
    que abre a cadeia. A ligação com a origem fica vazia ("anterior ao rastreio"): não há como saber
    de qual resposta a linha saiu. Devolve o id da rodada de migração (None se não havia o que migrar)."""
    preparar(con)
    if con.execute("SELECT 1 FROM rastreio_rodadas LIMIT 1").fetchone():
        return None
    if not any(con.execute(f'SELECT 1 FROM "{t}" LIMIT 1').fetchone() for t in tabelas_de_dados(con)):
        return None
    con.execute("DELETE FROM main.rastreio_pendentes")      # nada do que existe tem origem conhecida
    rid = abrir_rodada(con, (), MODO_MIGRACAO, conferir=False,
                       detalhe={"nota": "linhas gravadas antes do rastreio: o hash de cada registro foi calculado "
                                        "na migração e a origem ficou vazia (anterior ao rastreio)"})
    selar(con, rid, todas=True)
    fechar_rodada(con, rid)
    return rid


def _abrir_rastreio_de(caminho):
    """Uma conexão só de leitura com o rastreio de um banco (o arquivo à parte; num banco antigo, o
    próprio banco). None quando não há rastreio."""
    for arquivo in (caminho_do_rastreio(caminho), Path(caminho)):
        if not arquivo.exists():
            continue
        try:
            con = sqlite3.connect(f"file:{arquivo}?mode=ro", uri=True)
            if "rastreio_selos" in _tabelas(con):
                return con
            con.close()
        except sqlite3.Error:
            pass
    return None


def apagar_rastreio(caminho) -> None:
    """Apaga o arquivo do rastreio de um banco que vai ser refeito do zero (a cadeia já foi lida)."""
    for sufixo in ("", "-journal", "-wal", "-shm"):
        arq = Path(str(caminho_do_rastreio(caminho)) + sufixo)
        if arq.exists():
            arq.unlink()


def cadeia_para_herdar(caminho) -> list[dict]:
    """As rodadas de um banco que vai ser refeito do zero, para a cadeia continuar no banco novo."""
    con = _abrir_rastreio_de(caminho)
    if con is None:
        return []
    try:
        if "rastreio_rodadas" not in _tabelas(con):
            return []
        cur = con.execute("SELECT * FROM rastreio_rodadas WHERE hash IS NOT NULL ORDER BY id")
        nomes = [d[0] for d in cur.description]
        return [dict(zip(nomes, r)) for r in cur]
    except sqlite3.Error:
        return []
    finally:
        con.close()


def herdar(con, rodadas: list[dict]) -> None:
    """Grava as rodadas herdadas (só o elo da cadeia: os registros delas não estão neste banco)."""
    preparar(con)
    for r in rodadas:
        r = {**r, "herdada": 1}
        colunas = [c for c in r if c in set(_colunas(con, "rastreio_rodadas"))]
        con.execute(f"INSERT OR REPLACE INTO rastreio_rodadas ({', '.join(colunas)}) VALUES "
                    f"({', '.join('?' * len(colunas))})", [r[c] for c in colunas])
    con.commit()


def importar_selos(con, outro, rid: int) -> int:
    """Traz os selos e as origens de outro banco (a janela da agenda) para esta rodada, para o que a
    janela coletou chegar ao banco principal com a origem certa. Só entra o selo que o principal ainda
    não tem ativo; o ``selar`` seguinte descarta o que a soma não trouxe."""
    preparar(con)
    origem = _abrir_rastreio_de(outro)
    if origem is None:
        return 0
    trazidos = 0
    try:
        nomes = _nomes_das_tabelas(origem)
        origens = {i: (c, r, q) for i, c, r, q in origem.execute(
            "SELECT id, coleta, resposta, requisicao FROM rastreio_origens")}
        mapa: dict[int, int] = {}
        for i, (c, r, q) in origens.items():
            con.execute("INSERT OR IGNORE INTO rastreio_origens (coleta, resposta, requisicao) VALUES (?, ?, ?)",
                        (c, r, q))
            mapa[i] = con.execute("SELECT id FROM rastreio_origens WHERE coleta = ?", (c,)).fetchone()[0]
        for tid, h, o, n in origem.execute("SELECT tabela, hash, origem, n FROM rastreio_selos "
                                           "WHERE descartada IS NULL"):
            nome = nomes.get(tid)
            if nome is None:
                continue
            novo = _id_tabela(con, nome)
            cur = con.execute("INSERT INTO rastreio_selos (tabela, hash, rodada, origem, n) VALUES (?, ?, ?, ?, ?) "
                              "ON CONFLICT (tabela, hash) DO UPDATE SET descartada = NULL "
                              "WHERE rastreio_selos.descartada IS NOT NULL",
                              (novo, h, rid, mapa.get(o), n))
            trazidos += cur.rowcount
    finally:
        origem.close()
    return trazidos


def antes_de_compactar(con) -> None:
    """Antes do VACUUM (que pode renumerar as linhas): sela as pendências da rodada aberta, ou as
    descarta quando não há rodada (o que foi gravado fora de rodada aparece na abertura seguinte)."""
    if not tem_rastreio(con):
        return
    rid = rodada_corrente(con)
    if rid is not None:
        selar(con, rid)
    else:
        con.execute("DELETE FROM main.rastreio_pendentes")


def compactar(con) -> None:
    """VACUUM do arquivo do rastreio (o do banco da coleta é feito pelo ``Banco.fechar``)."""
    if anexado(con):
        con.execute(f"VACUUM {ESQ}")


# --- Verificação --------------------------------------------------------------------------------

def _identificacao(campos: dict, n: int = 4) -> dict:
    """Alguns campos da linha para a pessoa achá-la (os primeiros não nulos)."""
    return {k: v for k, v in list((k, v) for k, v in campos.items() if v not in (None, ""))[:n]}


def verificar_registros(con, *, limite: int = 200, pendentes: bool = True) -> dict:
    """Recalcula o hash de cada linha de cada tabela de dados e confronta com os selos ativos.

    ``sem_selo``: linha cujo hash não tem selo (alterada ou incluída fora de rodada).
    ``sumidos``: selo ativo sem a linha (removida ou alterada fora de rodada).
    ``pendentes``: linhas da rodada em curso que ainda não foram seladas."""
    saida = {"conferidos": 0, "tabelas": 0, "sem_selo": [], "sumidos": [], "pendentes": 0, "alteradas": []}
    _ler(con)
    if not tem_rastreio(con):
        saida["sem_rastreio"] = True
        return saida
    ids = {n: i for i, n in _nomes_das_tabelas(con).items()}
    pend: dict[str, set[int]] = {}
    # Pendência só vale com a rodada aberta: fora dela, a linha anotada pelo gatilho foi mexida fora de
    # rodada e aparece como sem selo.
    pendentes = pendentes and rodada_corrente(con) is not None
    for t, l in (con.execute("SELECT tabela, linha FROM main.rastreio_pendentes") if pendentes else ()):
        pend.setdefault(t, set()).add(l)
    for t in tabelas_de_dados(con):
        saida["tabelas"] += 1
        tid = ids.get(t)
        ativos = dict(con.execute("SELECT hash, n FROM rastreio_selos WHERE tabela = ? AND descartada IS NULL",
                                  (tid,))) if tid is not None else {}
        rodada_de = dict(con.execute("SELECT hash, rodada FROM rastreio_selos WHERE tabela = ?", (tid,))) \
            if tid is not None else {}
        contagem: Counter = Counter()
        sem: list[dict] = []
        for rowid, campos in _linhas(con, t):
            saida["conferidos"] += 1
            h = _digest(t, campos)
            contagem[h] += 1
            if contagem[h] > ativos.get(h, 0):
                if rowid in pend.get(t, ()):
                    saida["pendentes"] += 1
                else:
                    sem.append({"tabela": t, "linha": rowid, "hash": h.hex(), "campos": _identificacao(campos)})
        sumidos = [{"tabela": t, "hash": h.hex(), "rodada": rodada_de.get(h), "faltam": n - contagem.get(h, 0)}
                   for h, n in ativos.items() if contagem.get(h, 0) < n]
        if sem and sumidos:
            for x in sem:
                saida["alteradas"].append({**x, "selos_sem_linha": [s["hash"] for s in sumidos[:5]]})
        saida["sem_selo"] += sem
        saida["sumidos"] += sumidos
    for chave in ("sem_selo", "sumidos", "alteradas"):
        if len(saida[chave]) > limite:
            saida[f"{chave}_total"] = len(saida[chave])
            saida[chave] = saida[chave][:limite]
    return saida


def _rodadas(con) -> list[dict]:
    _ler(con)
    if "rastreio_rodadas" not in _tabelas_rastreio(con):
        return []
    cur = con.execute("SELECT * FROM rastreio_rodadas ORDER BY id")
    nomes = [d[0] for d in cur.description]
    return [dict(zip(nomes, r)) for r in cur]


def _retiradas_por_rodada(con) -> tuple[dict[int, Counter], dict[int, list[str]]]:
    """Das marcas: quantas folhas cada rodada perdeu, por tabela; e as linhas das marcas por rodada que
    retirou (para conferir com o resumo declarado nela)."""
    perdidas: dict[int, Counter] = {}
    marcas: dict[int, list[str]] = {}
    for x in retiradas(con):
        perdidas.setdefault(x["rodada"], Counter())[x["tabela"]] += 1
        novo = bytes.fromhex(x["novo"]) if x["novo"] else None
        marcas.setdefault(x["retirada_por"], []).append(
            _linha_retirada(x["tabela"], x["rodada"], x["origem"], x["n"], x["descartada"], x["motivo"], novo))
    return perdidas, marcas


def verificar_cadeia(con, *, raizes: bool = True) -> dict:
    """Confere cada rodada: o hash recalculado, o elo com a anterior e (``raizes``) a raiz de Merkle
    recalculada dos selos dela. Aponta a rodada e a tabela onde algo mudou.

    Folhas retiradas por privacidade: a tabela que perdeu folhas numa rodada não tem a raiz refeita
    (o hash que faltaria é justamente o que saiu); ela confere pela contagem (as que ficaram mais as
    retiradas dão o total gravado), e a raiz gravada vale pelo hash da rodada, que a cobre. As demais
    tabelas da rodada são refeitas como sempre. Cada retirada tem de estar declarada (total e resumo)
    no detalhe da rodada que retirou: marca a mais, a menos ou alterada é acusada."""
    rodadas = _rodadas(con)
    problemas: list[dict] = []
    folhas = _folhas_por_rodada(con) if raizes and rodadas else {}
    perdidas, marcas = _retiradas_por_rodada(con) if rodadas else ({}, {})
    declaradas: dict[int, dict] = {}
    anterior = None
    for r in rodadas:
        if r.get("hash") is None:
            problemas.append({"rodada": r["id"], "motivo": "rodada aberta (não fechada)", "grave": False})
            continue
        if _hash_rodada(r) != r["hash"]:
            problemas.append({"rodada": r["id"], "motivo": "o registro da rodada foi alterado (hash não confere)",
                              "grave": True})
        if anterior is not None and r.get("anterior") != anterior:
            problemas.append({"rodada": r["id"], "motivo": "elo quebrado: o hash da rodada anterior não confere",
                              "grave": True})
        anterior = r["hash"]
        det = json.loads(r.get("detalhe") or "{}") if (r.get("detalhe") or "").startswith("{") else {}
        if det.get("retiradas"):
            declaradas[r["id"]] = det["retiradas"]
        if raizes and not r.get("herdada"):
            raiz, por_tabela = _raizes(folhas.get(r["id"], {}))
            gravado = json.loads(r.get("tabelas") or "{}")
            menos = perdidas.get(r["id"], Counter())
            if not menos:
                if raiz != r.get("raiz"):
                    tabelas = sorted(t for t in set(gravado) | set(por_tabela) if gravado.get(t) != por_tabela.get(t))
                    problemas.append({"rodada": r["id"], "motivo": "os selos da rodada foram alterados (raiz de "
                                      "Merkle não confere)", "tabelas": tabelas, "grave": True})
                continue
            poucas = sorted(t for t, k in menos.items() if k <= POUCAS_RETIRADAS)
            if poucas:
                problemas.append({"rodada": r["id"], "motivo": f"tabela com até {POUCAS_RETIRADAS} folhas retiradas: "
                                  "a raiz guardada dela ainda deixa testar candidatos ao CPF", "tabelas": poucas,
                                  "grave": False})
            tabelas = []
            for t in sorted(set(gravado) | set(por_tabela) | set(menos)):
                if t in menos:
                    total = (gravado.get(t) or [0])[0]
                    if (por_tabela.get(t) or [0])[0] + menos[t] != total:
                        tabelas.append(t)
                elif gravado.get(t) != por_tabela.get(t):
                    tabelas.append(t)
            if tabelas:
                problemas.append({"rodada": r["id"], "motivo": "os selos da rodada foram alterados (raiz de Merkle "
                                  "ou contagem com as folhas retiradas não confere)", "tabelas": tabelas,
                                  "grave": True})
    for rid in sorted(set(marcas) | set(declaradas)):
        d = declaradas.get(rid) or {}
        linhas = marcas.get(rid, [])
        if d.get("total") != len(linhas) or d.get("resumo") != (_resumo_das_marcas(linhas) if linhas else None):
            problemas.append({"rodada": rid, "motivo": "as marcas das folhas retiradas não conferem com o que a "
                              "rodada que retirou declarou", "grave": True})
    ultima = next((r for r in reversed(rodadas) if r.get("hash")), None)
    return {"rodadas": len(rodadas), "herdadas": sum(1 for r in rodadas if r.get("herdada")),
            "problemas": problemas, "ok": not any(p["grave"] for p in problemas),
            "ultima": _resumo_rodada(ultima) if ultima else None,
            "retiradas": _resumo_das_retiradas(perdidas, declaradas, marcas)}


def _resumo_das_retiradas(perdidas: dict[int, Counter], declaradas: dict[int, dict],
                          marcas: dict[int, list[str]]) -> dict:
    """Quantas folhas foram retiradas, em qual rodada (a que retirou e as que perderam) e por quê."""
    if not marcas and not declaradas:
        return {"total": 0}
    return {"total": sum(len(v) for v in marcas.values()),
            "por_rodada_que_retirou": {str(rid): {k: d.get(k) for k in ("total", "por_tabela", "motivos")}
                                       for rid, d in sorted(declaradas.items())},
            "por_rodada_do_selo": {str(r): dict(sorted(c.items())) for r, c in sorted(perdidas.items())}}


def _resumo_rodada(r: dict) -> dict:
    return {"id": r["id"], "modo": r.get("modo"), "inicio": r.get("inicio"), "fim": r.get("fim"),
            "motores": json.loads(r.get("motores") or "[]"), "respostas": r.get("respostas"),
            "registros": r.get("registros"), "raiz": r.get("raiz"), "hash": r.get("hash"),
            "anterior": r.get("anterior"), "herdada": bool(r.get("herdada"))}


def respostas_sem_impressao(con) -> dict:
    """Coletas que tiveram resposta (ok, código HTTP ou bytes) e ficaram sem sha256: falha do rastreio.
    As anteriores ao rastreio (seladas na migração) são contadas à parte."""
    if "coletas" not in _tabelas(con):
        return {"novas": [], "anteriores": 0}
    tem_req = "requisicao" in _colunas(con, "coletas")
    sql = ("SELECT rowid, motor, alvo, url, http, bytes" + (", requisicao" if tem_req else ", NULL")
           + " FROM coletas WHERE sha256 IS NULL AND (ok = 1 OR http IS NOT NULL OR bytes > 0)")
    novas, anteriores = [], 0
    for rowid, motor, alvo, url, http, b, req in con.execute(sql):
        if req is None:
            anteriores += 1
        else:
            novas.append({"linha": rowid, "motor": motor, "alvo": alvo, "url": url, "http": http, "bytes": b})
    return {"novas": novas, "anteriores": anteriores}


def verificar(con, *, registros: bool = True) -> dict:
    """A verificação inteira: cadeia de rodadas, raízes, registro a registro e respostas sem hash."""
    cadeia = verificar_cadeia(con)
    regs = verificar_registros(con) if registros else None
    resp = respostas_sem_impressao(con)
    integro = cadeia["ok"] and not resp["novas"] and (
        regs is None or not (regs["sem_selo"] or regs["sumidos"]))
    return {"integro": integro, "cadeia": cadeia, "registros": regs, "respostas": resp,
            "sem_rastreio": not tem_rastreio(con)}


# --- Consulta: o hash de um registro e a sua origem ---------------------------------------------

def _origem(con, origem_id: int | None, modo: str | None = None) -> dict:
    if origem_id is None:
        if modo == MODO_MIGRACAO:
            return {"situacao": ANTERIOR_AO_RASTREIO}
        return {"situacao": "sem resposta de origem (gravado sem leitura de rede, ou a própria coleta)"}
    o = con.execute("SELECT coleta, resposta, requisicao FROM rastreio_origens WHERE id = ?", (origem_id,)).fetchone()
    if not o:
        return {"situacao": "origem não encontrada"}
    saida = {"coleta": o[0].hex(), "resposta": o[1], "requisicao": o[2]}
    for rowid, campos in _linhas(con, "coletas") if "coletas" in _tabelas(con) else ():
        if campos.get("sha256") == o[1] and _digest("coletas", campos) == o[0]:
            saida.update(linha=rowid, motor=campos.get("motor"), alvo=campos.get("alvo"), url=campos.get("url"),
                         quando=campos.get("quando"), metodo=campos.get("metodo"))
            break
    else:
        saida["situacao"] = "a linha da coleta já não está no banco (refeita numa rodada posterior)"
    return saida


def _selo(con, tabela: str, h: bytes) -> dict | None:
    s = con.execute("SELECT s.rodada, s.origem, s.n, s.descartada FROM rastreio_selos s JOIN rastreio_tabelas t "
                    "ON t.id = s.tabela WHERE t.nome = ? AND s.hash = ?", (tabela, h)).fetchone()
    if not s:
        return None
    r = con.execute("SELECT id, modo, inicio, fim, hash FROM rastreio_rodadas WHERE id = ?", (s[0],)).fetchone()
    rodada = dict(zip(("id", "modo", "inicio", "fim", "hash"), r)) if r else {"id": s[0]}
    saida = {"rodada": rodada, "origem": _origem(con, s[1], rodada.get("modo")), "iguais": s[2],
             "descartada_na_rodada": s[3]}
    if "rastreio_retiradas" in _tabelas_rastreio(con):
        substituiu = [dict(zip(("rodada", "retirada_por", "motivo"), x)) for x in con.execute(
            "SELECT r.rodada, r.retirada_por, r.motivo FROM rastreio_retiradas r JOIN rastreio_tabelas t "
            "ON t.id = r.tabela WHERE t.nome = ? AND r.novo = ?", (tabela, h))]
        if substituiu:
            saida["substituiu_retirados"] = substituiu
    return saida


def registro(con, tabela: str, rowid: int) -> dict | None:
    """O hash de uma linha, o selo dela (rodada e origem) e se o conteúdo atual confere com o selo."""
    campos = linha(con, tabela, rowid)
    if campos is None:
        return None
    h = _digest(tabela, campos)
    _ler(con)
    selo = _selo(con, tabela, h) if tem_rastreio(con) else None
    return {"tabela": tabela, "linha": rowid, "hash": h.hex(), "campos": campos, "selo": selo,
            "confere": bool(selo) and selo.get("descartada_na_rodada") is None}


def hash_do_registro(con, tabela: str, rowid: int) -> str | None:
    campos = linha(con, tabela, rowid)
    return hash_registro(tabela, campos) if campos is not None else None


def localizar(con, prefixo: str, *, limite: int = 5) -> list[dict]:
    """Os registros cujo hash começa com ``prefixo`` (hex), com a linha atual, a rodada e a origem."""
    prefixo = "".join(ch for ch in prefixo.lower() if ch in "0123456789abcdef")
    _ler(con)
    if len(prefixo) < 4 or not tem_rastreio(con):
        return []
    baixo = bytes.fromhex(prefixo.ljust(64, "0")[:64])
    alto = bytes.fromhex(prefixo.ljust(64, "f")[:64])
    achados = []
    for tid, nome in sorted(_nomes_das_tabelas(con).items()):
        for (h,) in con.execute("SELECT hash FROM rastreio_selos WHERE tabela = ? AND hash BETWEEN ? AND ?",
                                (tid, baixo, alto)):
            item = {"tabela": nome, "hash": h.hex(), "selo": _selo(con, nome, h), "linha": None}
            if partes.tem_tabela(con, nome):
                for rowid, campos in _linhas(con, nome):
                    if _digest(nome, campos) == h:
                        item.update(linha=rowid, campos=campos)
                        break
            achados.append(item)
            if len(achados) >= limite:
                return achados
    return achados


def resumo_da_cadeia(con) -> dict:
    """Para o parecer e as telas: a última rodada (hash, raiz), o tamanho da cadeia e se ela confere.
    Só lê (serve para conexões somente leitura)."""
    try:
        _ler(con)
        if not tem_rastreio(con):
            return {"rastreado": False}
        c = verificar_cadeia(con)
    except sqlite3.Error as e:
        return {"rastreado": False, "erro": str(e)}
    return {"rastreado": True, "rodadas": c["rodadas"], "ok": c["ok"], "ultima": c["ultima"],
            "problemas": c["problemas"][:10]}


def registro_da_coleta(con, rowid: int) -> tuple[str | None, str | None]:
    """(hash da linha da coleta, hash da requisição) de uma linha de ``coletas``."""
    campos = linha(con, "coletas", rowid)
    if campos is None:
        return None, None
    return hash_registro("coletas", campos), campos.get("requisicao")
