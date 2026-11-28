"""Devolve ao banco o dado da fonte que o próprio sistema mascarou (decisão do usuário de 28/11/2026, P-01).

Entre ee68c14 e a decisão de 28/11/2026, 11:18Z (config/decisoes_usuario.yml), o sistema trocou o CPF que a fonte
publicou inteiro por ``***.NNN.NNN-**`` no banco (``Banco.inserir`` e a migração do ``Banco.abrir``), no coletor da
despesa de Goiânia (documento, credor e histórico) e, no rastreio, tirou o hash das folhas antigas (retirada por
privacidade). As versões do banco guardadas no git antes da máscara (07e130c é a última) têm o dado da fonte.

``python -m onisciente restaurar-fonte --de 07e130c`` lê o banco de cada versão do git a partir dessa (o commit
dado e os seguintes que mudaram ``dados/onisciente``) e:

1. acha cada linha do banco atual com a máscara do sistema e a linha antiga que, mascarada pela mesma regra, dá a
   mesma linha (chave: o conteúdo inteiro, sem as colunas de proveniência ``coletado_em`` e ``sha256``, que uma
   coleta seguinte refaz). Volta só o valor das colunas mascaradas;
2. prova cada restauração pelo rastreio antigo: o hash da linha refeita é uma folha de uma versão antiga do
   rastreio (``hash``), ou a linha antiga de onde vieram as colunas é uma folha antiga e a refeita só difere dela na
   proveniência (``linha_antiga``). Sem prova, sem ambiguidade nem conflito, a linha não muda e vai para a lista de
   reler da fonte;
3. devolve o hash das folhas retiradas do rastreio numa rodada nova (``restauracao_fonte``): para cada rodada e
   tabela que perdeu folhas, os hashes das versões antigas do rastreio só voltam se, somados aos selos que ficaram,
   refazem a raiz de Merkle e a contagem gravadas na rodada original. Nenhuma rodada antiga é reescrita; a marca da
   retirada fica e ganha o registro da devolução (``rastreio_devolvidas``), declarado no detalhe da rodada nova;
4. lista o que não tem original no git (coletado já mascarado depois de ee68c14): precisa ser lido de novo da fonte.

Sem ``--gravar`` só mostra os números. Com ``--gravar``, aplica no banco dado (``--banco``) dentro da rodada nova.
"""

from __future__ import annotations

import gzip
import json
import re
import sqlite3
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from . import RAIZ, mascara_banco, rastreio

MODO = "restauracao_fonte"
PADRAO = re.compile(r"\*\*\*\.\d{3}\.\d{3}-\*\*")
PROVENIENCIA = ("coletado_em", "sha256")
DADOS = "dados/onisciente"
# As versões do banco que interessam: o principal, a parte das sanções e a despesa (o rastreio à parte).
ARQUIVOS = ("historico.db", "sancoes.db", "rastreio.db")


def _documento_despesa(v):
    from .coletores.goiania_transweb import documento_gravavel
    return documento_gravavel(v) if v else v


def _texto(v):
    return mascara_banco.mascarar_texto(v)


# Tabela -> coluna -> a máscara que o sistema aplicava ali (só para reconhecer a linha mascarada).
COLUNAS: dict[str, dict] = {
    **{t: {c: (lambda v, _t=t, _c=c: mascara_banco.mascarar_valor(_t, _c, v)) for c in cols}
       for t, cols in mascara_banco.COLUNAS.items()},
    "despesa_eventos": {"documento": _documento_despesa, "credor": _texto, "historico": _texto},
}
# Tabelas cuja fonte publica o CPF inteiro (o git mostra o dado inteiro antes da máscara do sistema): ali, o
# padrão ``***.NNN.NNN-**`` é máscara do sistema. ``fns_entidades``: o FNS publica o ``cpfCnpj`` inteiro, e o
# coletor guardava o ``cpfCnpjFormatado`` mascarado (desde 51ea739; sem original no git).
FONTE_INTEIRA: dict[str, tuple[str, ...]] = {
    **{t: tuple(cols) for t, cols in mascara_banco.COLUNAS.items() if t != "impedimentos"},
    "despesa_eventos": ("documento", "credor", "historico"),
    "fns_entidades": ("cpf_cnpj",),
}
COMO_RELER = {
    "despesa_eventos": "python -m onisciente historico --desde 2024-11 --ate 2026-11 --motores execucao_goiania "
                       "--somar --releitura-completa",
    "fns_entidades": "o motor fns (entidades do Município), que agora guarda o cpfCnpj da fonte",
}


def mascarar(tabela: str, linha: dict) -> dict:
    regras = COLUNAS.get(tabela, {})
    return {k: (regras[k](v) if k in regras and isinstance(v, str) else v) for k, v in linha.items()}


def _chave(linha: dict) -> str:
    return json.dumps({k: v for k, v in linha.items() if v is not None and k not in PROVENIENCIA},
                      sort_keys=True, ensure_ascii=False, default=str)


def tem_mascara(v) -> bool:
    return isinstance(v, str) and "***." in v and bool(PADRAO.search(v))


# --- As versões do git --------------------------------------------------------------------------

def _git(*args: str, binario: bool = False):
    r = subprocess.run(["git", *args], cwd=RAIZ, capture_output=True, check=True)
    return r.stdout if binario else r.stdout.decode()


def versoes(de: str) -> list[str]:
    """O commit dado e os seguintes que mudaram o banco, do mais antigo ao mais novo (hash curto)."""
    base = _git("rev-parse", "--short", de).strip()
    depois = _git("log", "--reverse", "--format=%h", f"{base}..HEAD", "--", DADOS).split()
    return [base, *depois]


def extrair(commit: str, cache: Path) -> Path:
    """Os arquivos do banco no commit, numa pasta do cache (uma vez por commit)."""
    pasta = cache / commit
    feito = pasta / ".feito"
    if feito.exists():
        return pasta
    pasta.mkdir(parents=True, exist_ok=True)
    for nome in _git("ls-tree", "-r", "--name-only", commit, DADOS).split("\n"):
        rel = nome[len(DADOS) + 1:] if nome.startswith(DADOS + "/") else ""
        if not rel or not (rel in ARQUIVOS or (rel.startswith("despesa/") and rel.endswith(".jsonl.gz"))):
            continue
        destino = pasta / rel
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(_git("show", f"{commit}:{nome}", binario=True))
    feito.write_text(commit)
    return pasta


def _db_da_tabela(pasta: Path, tabela: str) -> Path | None:
    for nome in ARQUIVOS:
        arq = pasta / nome
        if nome == "rastreio.db" or not arq.exists():
            continue
        con = sqlite3.connect(f"file:{arq}?mode=ro", uri=True)
        try:
            if con.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (tabela,)).fetchone():
                return arq
        finally:
            con.close()
    return None


def _de_volta(v):
    return bytes.fromhex(v["$hex"]) if isinstance(v, dict) and "$hex" in v else v


def linhas_da_pasta(pasta: Path, tabela: str):
    """As linhas de uma tabela numa pasta de banco (o .db, ou os .jsonl.gz da parte comprimida), como o SQLite as
    devolve (os .gz passam por um SQLite na memória, para os tipos saírem iguais aos do banco de trabalho)."""
    gz = sorted((pasta / "despesa").glob(f"{tabela}_*.jsonl.gz")) if (pasta / "despesa").is_dir() else []
    if gz:
        mem = sqlite3.connect(":memory:")
        criada = False
        for arq in gz:
            with gzip.open(arq, "rt", encoding="utf-8") as f:
                cab = json.loads(f.readline())
                if not criada:
                    mem.execute(cab["sql"])
                    criada = True
                existentes = [c[1] for c in mem.execute(f'PRAGMA table_info("{tabela}")')]
                for c in cab["colunas"]:
                    if c not in existentes:
                        mem.execute(f'ALTER TABLE "{tabela}" ADD COLUMN "{c}"')
                lista = ", ".join(f'"{c}"' for c in cab["colunas"])
                mem.executemany(f'INSERT INTO "{tabela}" ({lista}) VALUES ({", ".join("?" for _ in cab["colunas"])})',
                                ([_de_volta(v) for v in json.loads(linha)] for linha in f))
        yield from _ler(mem, tabela)
        mem.close()
        return
    arq = _db_da_tabela(pasta, tabela)
    if arq is None:
        return
    con = sqlite3.connect(f"file:{arq}?mode=ro", uri=True)
    try:
        yield from _ler(con, tabela)
    finally:
        con.close()


def _ler(con, tabela: str):
    cur = con.execute(f'SELECT rowid, * FROM "{tabela}"')
    nomes = [d[0] for d in cur.description][1:]
    for r in cur:
        yield r[0], dict(zip(nomes, r[1:]))


@dataclass
class Antigos:
    """O que as versões antigas guardam: as linhas que o sistema depois mascarou e as folhas do rastreio."""
    linhas: dict[str, dict[str, list[tuple[str, dict]]]] = field(default_factory=dict)   # tabela -> chave -> [(commit, linha)]
    folhas: dict[str, set[bytes]] = field(default_factory=dict)                          # tabela -> hashes
    selos: dict[tuple[str, int], dict[bytes, tuple]] = field(default_factory=dict)       # (tabela, rodada) -> hash -> (origem, n)
    rodadas: dict[int, str] = field(default_factory=dict)                                # id -> hash
    descartadas: list[str] = field(default_factory=list)                                 # versões com cadeia diferente


def ler_antigos(pastas: dict[str, Path], rodadas_atuais: dict[int, str]) -> Antigos:
    """As linhas e as folhas das versões antigas (versão -> pasta com os arquivos do banco)."""
    a = Antigos()
    vistos: dict[str, set[str]] = defaultdict(set)
    for commit, pasta in pastas.items():
        rast = pasta / "rastreio.db"
        if rast.exists():
            con = sqlite3.connect(f"file:{rast}?mode=ro", uri=True)
            try:
                rod = dict(con.execute("SELECT id, hash FROM rastreio_rodadas WHERE hash IS NOT NULL"))
                if any(rodadas_atuais.get(i) not in (None, h) for i, h in rod.items()):
                    a.descartadas.append(commit)      # outra cadeia: as folhas dela não provam nada aqui
                    rod = {}
                else:
                    a.rodadas.update(rod)
                    for nome, h, rodada, origem, n in con.execute(
                            "SELECT t.nome, s.hash, s.rodada, s.origem, s.n FROM rastreio_selos s "
                            "JOIN rastreio_tabelas t ON t.id = s.tabela"):
                        a.folhas.setdefault(nome, set()).add(bytes(h))
                        a.selos.setdefault((nome, rodada), {})[bytes(h)] = (origem, n)
            finally:
                con.close()
        for tabela in COLUNAS:
            for _rowid, linha in linhas_da_pasta(pasta, tabela):
                if not any(tem_cpf_inteiro(tabela, c, linha.get(c)) for c in COLUNAS[tabela]):
                    continue
                m = mascarar(tabela, linha)
                if m == linha:
                    continue
                inteira = json.dumps(linha, sort_keys=True, ensure_ascii=False, default=str)
                if inteira in vistos[tabela]:
                    continue
                vistos[tabela].add(inteira)
                a.linhas.setdefault(tabela, {}).setdefault(_chave(m), []).append((commit, linha))
    return a


def tem_cpf_inteiro(tabela: str, coluna: str, v) -> bool:
    regra = COLUNAS.get(tabela, {}).get(coluna)
    return regra is not None and isinstance(v, str) and any(ch.isdigit() for ch in v) and regra(v) != v


# --- O plano: o que volta, com qual prova ----------------------------------------------------------

@dataclass
class Plano:
    restaurar: list[dict] = field(default_factory=list)        # {tabela, rowid, valores, prova, commit}
    reler: dict[str, Counter] = field(default_factory=dict)    # tabela -> motivo/coluna/mês -> linhas
    exemplos_reler: dict[str, list] = field(default_factory=dict)
    ambiguas: Counter = field(default_factory=Counter)
    sem_prova: Counter = field(default_factory=Counter)

    def resumo(self) -> dict:
        por = defaultdict(Counter)
        for r in self.restaurar:
            por[r["tabela"]][r["prova"]] += 1
        return {"restauradas": {t: dict(c, total=sum(c.values())) for t, c in sorted(por.items())},
                "ambiguas": dict(self.ambiguas), "sem_prova": dict(self.sem_prova),
                "reler": {t: dict(c) for t, c in sorted(self.reler.items())}}


def _mes(linha: dict) -> str:
    return str(linha.get("data") or "")[:7] or "sem data"


def planejar(con, antigos: Antigos) -> Plano:
    """Para cada linha atual com a máscara do sistema, a linha antiga e a prova (ou o motivo para reler)."""
    p = Plano()
    for tabela, colunas in FONTE_INTEIRA.items():
        if not _existe(con, tabela):
            continue
        cols = [d[0] for d in con.execute(f'SELECT * FROM "{tabela}" LIMIT 0').description]
        presentes = [c for c in colunas if c in cols]
        if not presentes:
            continue
        filtro = " OR ".join(f'"{c}" LIKE \'%***.%\'' for c in presentes)
        indice = antigos.linhas.get(tabela, {})
        folhas = antigos.folhas.get(tabela, set())
        for rowid, linha in _ler_filtrado(con, tabela, filtro):
            mascaradas = [c for c in presentes if tem_mascara(linha.get(c))]
            if not mascaradas:
                continue
            candidatos = indice.get(_chave(mascarar(tabela, linha)), [])
            valores_possiveis = {}
            for commit, antiga in candidatos:
                novos = {c: antiga.get(c) for c in COLUNAS.get(tabela, {})
                         if linha.get(c) != antiga.get(c) and isinstance(linha.get(c), str)
                         and mascarar(tabela, {c: antiga.get(c)})[c] == mascarar(tabela, {c: linha.get(c)})[c]}
                if novos:
                    valores_possiveis.setdefault(json.dumps(novos, sort_keys=True, ensure_ascii=False),
                                                 (novos, commit, antiga))
            if not valores_possiveis:
                motivo = "sem original no git" if tabela in COLUNAS else "mascarada pelo coletor, sem original no git"
                _para_reler(p, tabela, rowid, linha, mascaradas, motivo)
                continue
            opcoes = list(valores_possiveis.values())
            escolha = None
            if len(opcoes) > 1:
                # Uma versão antiga pode devolver mais colunas que outra (coletada antes da primeira máscara ou
                # entre uma e outra). Se uma devolve tudo o que as outras devolvem, com os mesmos valores, e tem
                # prova, é ela: senão a linha voltaria em parte e uma segunda rodada acharia o resto.
                maior = max(opcoes, key=lambda o: len(o[0]))
                if all(maior[0].get(c) == v for o in opcoes for c, v in o[0].items()) and \
                        _prova(tabela, linha, maior, folhas):
                    escolha = maior
                else:
                    # Mais de um original possível (o mesmo miolo e o resto igual): vale só o que o rastreio
                    # antigo prova pelo hash da linha refeita; senão, a linha fica e vai para a releitura.
                    provados = [o for o in opcoes if rastreio._digest(tabela, {**linha, **o[0]}) in folhas]
                    if len(provados) != 1:
                        p.ambiguas[tabela] += 1
                        _para_reler(p, tabela, rowid, linha, mascaradas, "mais de um original possível")
                        continue
                    escolha = provados[0]
            else:
                escolha = opcoes[0]
            novos, commit, _antiga = escolha
            refeita = {**linha, **novos}
            prova = _prova(tabela, linha, escolha, folhas)
            if prova is None:
                p.sem_prova[tabela] += 1
                _para_reler(p, tabela, rowid, linha, mascaradas, "sem prova no rastreio antigo")
                continue
            p.restaurar.append({"tabela": tabela, "rowid": rowid, "valores": novos, "prova": prova,
                                "commit": commit, "hash": rastreio._digest(tabela, refeita)})
            # A linha antiga pode já ter vindo com uma coluna mascarada (coletada entre uma máscara e a seguinte):
            # o que ela devolve volta; a coluna que segue mascarada também vai para a releitura.
            restam = [c for c in mascaradas if tem_mascara(refeita.get(c))]
            if restam:
                _para_reler(p, tabela, rowid, refeita, restam, "voltou em parte; o resto sem original no git")
    return p


def _prova(tabela: str, linha: dict, opcao: tuple, folhas: set) -> str | None:
    """A prova da linha refeita: o hash dela no rastreio antigo, ou o da linha antiga que só difere na proveniência."""
    novos, _commit, antiga = opcao
    refeita = {**linha, **novos}
    if rastreio._digest(tabela, refeita) in folhas:
        return "hash"
    if rastreio._digest(tabela, antiga) in folhas and \
            {k for k in set(refeita) | set(antiga) if refeita.get(k) != antiga.get(k)} <= set(PROVENIENCIA):
        return "linha_antiga"
    return None


def _para_reler(p: Plano, tabela: str, rowid: int, linha: dict, mascaradas: list[str], motivo: str) -> None:
    p.reler.setdefault(tabela, Counter())[motivo] += 1
    p.reler[tabela]["coluna " + "+".join(mascaradas)] += 1
    if tabela == "despesa_eventos":
        p.reler[tabela][f"mês {_mes(linha)}"] += 1
        p.reler[tabela][f"consulta {linha.get('consulta') or ''}"] += 1
    ex = p.exemplos_reler.setdefault(tabela, [])
    if len(ex) < 5:
        ex.append({"linha": rowid, **{c: linha.get(c) for c in mascaradas},
                   **({"empenho": linha.get("empenho"), "data": linha.get("data")}
                      if tabela == "despesa_eventos" else {})})


def _existe(con, tabela: str) -> bool:
    try:
        con.execute(f'SELECT 1 FROM "{tabela}" LIMIT 0')
        return True
    except sqlite3.OperationalError:
        return False


def _ler_filtrado(con, tabela: str, filtro: str):
    cur = con.execute(f'SELECT rowid, * FROM "{tabela}" WHERE {filtro}')
    nomes = [d[0] for d in cur.description][1:]
    for r in cur:
        yield r[0], dict(zip(nomes, r[1:]))


# --- As folhas retiradas do rastreio ---------------------------------------------------------------

def planejar_devolucao(con, antigos: Antigos) -> dict:
    """Por rodada e tabela que perdeu folhas: os hashes que voltam, só se refazem a raiz e a contagem gravadas."""
    if "rastreio_retiradas" not in rastreio._tabelas_rastreio(con):
        return {"grupos": [], "provados": 0, "sem_prova": {}}
    ja = rastreio.devolvidas(con)
    nomes = rastreio._nomes_das_tabelas(con)
    origens = {i: (bytes(c) if c is not None else None, r) for i, c, r in
               con.execute("SELECT id, coleta, resposta FROM rastreio_origens")}
    rodadas = {i: (json.loads(t or "{}"), bool(h)) for i, t, h in
               con.execute("SELECT id, tabelas, herdada FROM rastreio_rodadas")}
    marcas: dict[tuple[str, int], list[tuple]] = defaultdict(list)
    for mid, tid, rodada, origem, n, descartada in con.execute(
            "SELECT id, tabela, rodada, origem, n, descartada FROM rastreio_retiradas ORDER BY id"):
        if mid not in ja:
            marcas[(nomes.get(tid, str(tid)), rodada)].append((mid, tid, origem, n, descartada))
    grupos, sem_prova = [], Counter()
    for (nome, rodada), ms in sorted(marcas.items()):
        tid = ms[0][1]
        gravado, herdada = rodadas.get(rodada, ({}, True))
        if herdada or nome not in gravado:
            sem_prova[f"{nome}: rodada {rodada} herdada ou sem raiz gravada"] += len(ms)
            continue
        ficaram = {bytes(h): o for h, o in con.execute(
            "SELECT hash, origem FROM rastreio_selos WHERE tabela = ? AND rodada = ?", (tid, rodada))}
        presentes = {bytes(h) for (h,) in con.execute("SELECT hash FROM rastreio_selos WHERE tabela = ?", (tid,))}
        cand = {h: o for h, o in antigos.selos.get((nome, rodada), {}).items() if h not in ficaram}
        if len(cand) != len(ms) or any(h in presentes for h in cand):
            sem_prova[f"{nome}: rodada {rodada} sem as {len(ms)} folhas nas versões antigas "
                      f"(achadas {len(cand)})"] += len(ms)
            continue
        folhas = [rastreio._folha(nome, h, *origens.get(o, (None, None))) for h, o in ficaram.items()]
        folhas += [rastreio._folha(nome, h, *origens.get(o, (None, None))) for h, (o, _n) in cand.items()]
        total, raiz = gravado[nome]
        if len(folhas) != total or rastreio.merkle(sorted(folhas)).hex() != raiz:
            sem_prova[f"{nome}: rodada {rodada} não refaz a raiz gravada"] += len(ms)
            continue
        # Cada marca volta com um hash da mesma origem (a folha só depende da tabela, do hash e da origem).
        livres = defaultdict(list)
        for h, (o, n) in sorted(cand.items()):
            livres[o].append((h, n))
        pares = []
        for mid, _tid, origem, n, descartada in ms:
            if not livres.get(origem):
                break
            h, _n = livres[origem].pop()
            pares.append((mid, h, origem, n, descartada))
        if len(pares) != len(ms):
            sem_prova[f"{nome}: rodada {rodada} com origens que não casam"] += len(ms)
            continue
        grupos.append({"tabela": nome, "tid": tid, "rodada": rodada, "pares": pares})
    return {"grupos": grupos, "provados": sum(len(g["pares"]) for g in grupos), "sem_prova": dict(sem_prova)}


# --- Aplicar --------------------------------------------------------------------------------------

def aplicar(banco, plano: Plano, devolucao: dict) -> dict:
    """Numa rodada ``restauracao_fonte``: devolve as folhas provadas e refaz as linhas com o dado da fonte."""
    con = banco.con
    rid = rastreio.abrir_rodada(con, ["restauracao_fonte"], MODO, detalhe={
        "nota": "decisão do usuário de 28/11/2026 (P-01): o dado da fonte volta; as folhas retiradas pela máscara "
                "voltam provadas pela raiz de Merkle da rodada original"})
    rastreio.devolver(con, rid, [(mid, tid, h, rodada, origem, n, descartada)
                                 for g in devolucao["grupos"] for (mid, h, origem, n, descartada) in g["pares"]
                                 for tid, rodada in [(g["tid"], g["rodada"])]])
    feitas, conflitos = Counter(), Counter()
    for r in plano.restaurar:
        sets = ", ".join(f'"{c}" = ?' for c in r["valores"])
        try:
            con.execute(f'UPDATE "{r["tabela"]}" SET {sets} WHERE rowid = ?', [*r["valores"].values(), r["rowid"]])
            feitas[r["tabela"]] += 1
        except sqlite3.IntegrityError:
            conflitos[r["tabela"]] += 1        # a linha inteira já existe (a mesma linha lida de novo da fonte)
    con.commit()
    fechada = rastreio.fechar_rodada(con, rid)
    return {"rodada": rid, "hash": fechada["hash"], "linhas": dict(feitas), "conflitos": dict(conflitos)}


# --- O que ainda está mascarado pelo sistema (a trava do banco real) ------------------------------

def mascarados_pelo_sistema(caminho) -> dict[tuple[str, str], int]:
    """(tabela, coluna) -> linhas com ``***.NNN.NNN-**`` nas tabelas cuja fonte publica o CPF inteiro. Só lê
    (os .db em modo de leitura e os .jsonl.gz da despesa direto, sem refazer o SQLite de trabalho)."""
    pasta = Path(caminho).parent
    saida: dict[tuple[str, str], int] = {}
    for tabela, colunas in FONTE_INTEIRA.items():
        for _rowid, linha in linhas_da_pasta(pasta, tabela):
            for c in colunas:
                if tem_mascara(linha.get(c)):
                    saida[(tabela, c)] = saida.get((tabela, c), 0) + 1
    return saida


# --- Os arquivos da sondagem ------------------------------------------------------------------------

SONDAGEM = "relatorios/onisciente/sondagem"


def _mascarar_arquivo(nome: str, dados: bytes) -> bytes:
    from . import mascara_cpf
    from .coletores.goiania_transweb import mascarar_cpfs_no_texto
    if nome.endswith(".zip.b64"):
        import base64
        return base64.b64encode(mascara_cpf.mascarar_zip(base64.b64decode(dados))[0])
    texto = dados.decode("utf-8", errors="surrogateescape")
    texto = mascarar_cpfs_no_texto(mascara_cpf.mascarar_texto(texto)[0])
    return texto.encode("utf-8", errors="surrogateescape")


def _molde(atual: str):
    """Uma expressão que casa o texto antigo com o atual: igual, menos onde o atual tem a máscara do sistema, que
    no antigo pode ser o CPF (formatado, só dígitos ou com 000 na frente) ou a própria máscara. A máscara antiga
    regravava o arquivo em modo texto e trocava o fim de linha CRLF da fonte por LF: o antigo pode ter o CR."""
    def literal(trecho: str) -> str:
        return r"\r?\n".join(re.escape(s) for s in trecho.split("\n"))

    partes_, fim = [], 0
    for m in PADRAO.finditer(atual):
        partes_.append(literal(atual[fim:m.start()]))
        meio = m.group(0)[4:11]                       # "NNN.NNN"
        a, b = meio.split(".")
        partes_.append(rf"(?:\d{{3}}\.{a}\.{b}-\d{{2}}|(?:000)?\d{{3}}{a}{b}\d{{2}}|\*\*\*\.{a}\.{b}-\*\*)")
        fim = m.end()
    partes_.append(literal(atual[fim:]))
    return re.compile("".join(partes_), re.S)


def _mascaras(nome: str, dados: bytes) -> int:
    """Quantas máscaras ``***.NNN.NNN-**`` há no arquivo (no zip, nos arquivos de dentro)."""
    if nome.endswith(".zip.b64"):
        import base64
        import io
        import zipfile
        try:
            with zipfile.ZipFile(io.BytesIO(base64.b64decode(dados))) as z:
                return sum(len(PADRAO.findall(z.read(n).decode("latin-1"))) for n in z.namelist())
        except (zipfile.BadZipFile, ValueError):
            return 0
    return len(PADRAO.findall(dados.decode("utf-8", errors="replace")))


def restaurar_sondagem(*, gravar: bool = False, pasta: Path | None = None) -> dict:
    """Os arquivos da sondagem que o sistema mascarou voltam à versão do git que é o mesmo arquivo com o CPF no
    lugar da máscara (a com menos máscaras; no zip, a que mascarada pela mesma regra dá o atual). Os que não têm
    essa versão ficam como estão (listados); o que só tem uma versão com parte das máscaras volta a ela."""
    pasta = pasta or RAIZ / SONDAGEM
    feitos, sem_original = [], []
    for arq in sorted(pasta.iterdir()):
        if not arq.is_file():
            continue
        atual = arq.read_bytes()
        n_atual = _mascaras(arq.name, atual)
        if not n_atual:
            continue
        rel = arq.relative_to(RAIZ).as_posix()
        zipado = arq.name.endswith(".zip.b64")
        alvo = _mascarar_arquivo(arq.name, atual) if zipado else None
        molde = None if zipado else _molde(atual.decode("utf-8", errors="surrogateescape"))
        melhor = None
        for commit in _git("log", "--format=%h", "--", rel).split():
            try:
                antigo = _git("show", f"{commit}:{rel}", binario=True)
            except subprocess.CalledProcessError:
                continue
            if antigo == atual:
                continue
            if zipado:
                casa = _mascarar_arquivo(arq.name, antigo) == alvo
            else:
                casa = bool(molde.fullmatch(antigo.decode("utf-8", errors="surrogateescape")))
            n = _mascaras(arq.name, antigo)
            if casa and n < n_atual and (melhor is None or n < melhor[2]):
                melhor = (commit, antigo, n)
        if melhor is None:
            sem_original.append(arq.name)
            continue
        feitos.append({"arquivo": arq.name, "de": melhor[0], "mascaras_antes": n_atual, "mascaras_depois": melhor[2]})
        if gravar:
            arq.write_bytes(melhor[1])
    return {"restaurados": feitos, "sem_original": sem_original}


# --- O comando -------------------------------------------------------------------------------------

def rodar(caminho, de: str, *, cache: Path, gravar: bool = False, sondagem: bool = False) -> dict:
    from . import historico, partes
    commits = versoes(de)
    leitura = partes.conectar_leitura(caminho)
    rastreio.anexar(leitura, somente_leitura=True)
    atuais = dict(leitura.execute("SELECT id, hash FROM rastreio_rodadas WHERE hash IS NOT NULL")) \
        if rastreio.tem_rastreio(leitura) else {}
    leitura.close()
    antigos = ler_antigos({c: extrair(c, cache) for c in commits}, atuais)
    if gravar:
        banco = historico.Banco.abrir(caminho)
        con = banco.con
    else:
        banco = None
        con = partes.conectar_leitura(caminho)
        rastreio.anexar(con, somente_leitura=True)
    try:
        plano = planejar(con, antigos)
        devolucao = planejar_devolucao(con, antigos)
        saida = {"versoes": commits, "versoes_com_outra_cadeia": antigos.descartadas, **plano.resumo(),
                 "exemplos_reler": plano.exemplos_reler,
                 "folhas": {"retiradas": _total_retiradas(con), "ja_devolvidas": len(rastreio.devolvidas(con)),
                            "provadas_pela_raiz": devolucao["provados"], "sem_prova": devolucao["sem_prova"],
                            "por_tabela": dict(Counter(g["tabela"] for g in devolucao["grupos"]
                                                       for _ in g["pares"]))},
                 "como_reler": {t: COMO_RELER.get(t, "a coleta do motor da tabela")
                                for t in plano.reler}}
        if gravar:
            saida["aplicado"] = aplicar(banco, plano, devolucao)
            v = rastreio.verificar(con)
            saida["verificacao"] = {"integro": v["integro"], "cadeia_ok": v["cadeia"]["ok"],
                                    "problemas": [p for p in v["cadeia"]["problemas"] if p["grave"]][:10],
                                    "sem_selo": len(v["registros"]["sem_selo"]) if v["registros"] else None,
                                    "sumidos": len(v["registros"]["sumidos"]) if v["registros"] else None,
                                    "devolvidas": v["cadeia"].get("devolvidas")}
    finally:
        if banco is not None:
            banco.fechar()
        else:
            con.close()
    if sondagem:
        saida["sondagem"] = restaurar_sondagem(gravar=gravar)
    return saida


def _total_retiradas(con) -> int:
    if "rastreio_retiradas" not in rastreio._tabelas_rastreio(con):
        return 0
    return con.execute("SELECT count(*) FROM rastreio_retiradas").fetchone()[0]
