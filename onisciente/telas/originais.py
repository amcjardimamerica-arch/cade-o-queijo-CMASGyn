"""Os selos dos números das telas: de onde veio cada número e onde está o original.

O banco histórico guarda, para cada leitura, o endereço exato que o motor leu, a data e a impressão
digital (sha256) do que veio (tabela ``coletas``). Esse é o original guardado: a dica de cada número
mostra a fonte, a data e a impressão digital, e o clique abre o endereço lido. Quando a coleta guardou
também a resposta crua (``--brutos`` da coleta histórica) e ela ainda bate com a impressão digital, a
cópia vai junto com as telas e o clique abre a cópia. Quando um número não tem original guardado, a
dica diz isso com todas as letras.

Quando o banco já tem o rastreio por hash (``rastreio.db`` ao lado do histórico), a dica mostra também o
hash do registro da coleta (a linha inteira de ``coletas``, no formato canônico do rastreio) e se ele
confere com o selo gravado na rodada em que a linha entrou.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from .. import rastreio

LIMITE_COPIA = 2_000_000   # bytes: respostas maiores ficam só com o endereço e a impressão digital
SEM_ORIGINAL = "o original deste número não está guardado no banco"

SELOS = {"verde", "azul", "roxo", "vermelho"}


@dataclass
class Original:
    rotulo: str                 # de onde veio, em português
    url: str = ""               # endereço lido (ou a cópia guardada)
    sha256: str = ""
    quando: str = ""
    selo: str = "azul"
    nota: str = ""
    copia: bool = False         # o clique abre a cópia guardada junto com as telas
    registro: str = ""          # hash do registro da coleta (rastreio), quando o banco tem rastreio
    confere: bool = False       # o registro confere com o selo gravado no rastreio

    def como_dict(self) -> dict:
        d = {"r": self.rotulo, "s": self.selo}
        if self.url:
            d["u"] = self.url
        if self.sha256:
            d["h"] = self.sha256
        if self.quando:
            d["q"] = self.quando[:10]
        if self.copia:
            d["c"] = 1
        if self.registro:
            d["hr"] = self.registro
            if self.confere:
                d["hv"] = 1
        nota = self.nota
        if not self.url and SEM_ORIGINAL not in nota:
            nota = (nota.rstrip(".") + ". " if nota else "") + SEM_ORIGINAL[:1].upper() + SEM_ORIGINAL[1:] + "."
        d["n"] = nota.replace(". " + SEM_ORIGINAL, ". O" + SEM_ORIGINAL[1:])
        return d


def _nome_bruto(motor: str, alvo: str, mes: str) -> str:
    """O mesmo nome que a coleta histórica dá à resposta crua (historico.Contexto.ler)."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", f"{motor}_{alvo}_{mes}")[:150]


@dataclass
class Originais:
    """Registro das fontes usadas nas telas, cada uma com uma chave curta."""

    con: sqlite3.Connection | None = None
    brutos: Path | None = None          # pasta das respostas cruas da coleta, se houver
    destino: Path | None = None         # pasta das cópias publicadas (docs/.../originais)
    prefixo_copia: str = "originais/"
    tabela: dict[str, Original] = field(default_factory=dict)
    _coletas: dict[tuple[str, str], list[tuple]] | None = None
    _rastreado: bool | None = None

    # --- leitura da tabela de coletas ---------------------------------------------------------
    def _carregar(self) -> dict[tuple[str, str], list[tuple]]:
        if self._coletas is None:
            self._coletas = {}
            if self.con is not None:
                try:
                    linhas = self.con.execute(
                        "SELECT motor, alvo, mes, url, sha256, quando, rowid FROM coletas WHERE ok = 1 "
                        "ORDER BY quando DESC").fetchall()
                except sqlite3.OperationalError:
                    linhas = []
                for motor, alvo, mes, url, sha, quando, rowid in linhas:
                    self._coletas.setdefault((motor, mes or ""), []).append((alvo or "", url, sha, quando, rowid))
        return self._coletas

    def rastreado(self) -> bool:
        """O banco tem o rastreio por hash anexado (só leitura; sem ``rastreio.db``, não)."""
        if self._rastreado is None:
            self._rastreado = False
            if self.con is not None:
                try:
                    self._rastreado = rastreio.anexar(self.con, somente_leitura=True) and rastreio.tem_rastreio(self.con)
                except sqlite3.Error:
                    self._rastreado = False
        return self._rastreado

    def registro_da_coleta(self, rowid: int | None) -> tuple[str, bool]:
        """(hash do registro da coleta, se confere com o selo); vazio quando o banco não tem rastreio."""
        if rowid is None or not self.rastreado():
            return "", False
        try:
            r = rastreio.registro(self.con, "coletas", rowid)
        except (sqlite3.Error, ValueError, TypeError):
            return "", False
        if not r:
            return "", False
        return r["hash"], bool(r.get("confere"))

    def _de_linha(self, rotulo: str, url: str, sha: str, quando: str, rowid: int | None, *,
                  selo: str = "azul", nota: str = "", copia: str | None = None) -> Original:
        registro, confere = self.registro_da_coleta(rowid)
        return Original(rotulo, url=copia or url, sha256=sha or "", quando=quando or "", selo=selo, nota=nota,
                        copia=bool(copia), registro=registro, confere=confere)

    def coleta(self, motor: str, mes: str = "", alvo: str | None = None,
               contem: str | None = None) -> tuple | None:
        """A leitura mais recente de um motor num mês (e, se dado, com o alvo ou um trecho dele)."""
        for a, url, sha, quando, rowid in self._carregar().get((motor, mes or ""), []):
            if alvo is not None and a != alvo:
                continue
            if contem is not None and contem not in a:
                continue
            return a, url, sha, quando, rowid
        return None

    def _copiar(self, motor: str, alvo: str, mes: str, sha: str) -> str | None:
        if not (self.brutos and self.destino and sha):
            return None
        arq = self.brutos / _nome_bruto(motor, alvo, mes)
        if not arq.is_file() or arq.stat().st_size > LIMITE_COPIA:
            return None
        conteudo = arq.read_bytes()
        if hashlib.sha256(conteudo).hexdigest() != sha:
            return None   # a resposta crua não é mais a que o banco registrou
        self.destino.mkdir(parents=True, exist_ok=True)
        alvo_arq = self.destino / sha
        if not alvo_arq.exists():
            shutil.copyfile(arq, alvo_arq)
        return self.prefixo_copia + sha

    # --- registro ------------------------------------------------------------------------------
    def de_coleta(self, chave: str, rotulo: str, motor: str, mes: str = "", *, alvo: str | None = None,
                  contem: str | None = None, selo: str = "azul", nota: str = "") -> str:
        """Registra a fonte de um número a partir de uma leitura guardada; devolve a chave."""
        if chave in self.tabela:
            return chave
        achada = self.coleta(motor, mes, alvo, contem)
        if achada is None:
            self.tabela[chave] = Original(rotulo, selo=selo, nota=(nota + " " if nota else "")
                                          + SEM_ORIGINAL + ".")
            return chave
        a, url, sha, quando, rowid = achada
        copia = self._copiar(motor, a, mes, sha)
        self.tabela[chave] = self._de_linha(rotulo, url, sha, quando, rowid, selo=selo, nota=nota, copia=copia)
        return chave

    def externo(self, chave: str, rotulo: str, url: str = "", *, selo: str = "azul", nota: str = "",
                sha256: str = "", quando: str = "", registro: str = "", confere: bool = False) -> str:
        """Fonte que não passa direto pela tabela de coletas (uma norma, uma edição do Diário, uma soma de
        meses que abre o original do último mês, com o hash do registro dele)."""
        if chave not in self.tabela:
            self.tabela[chave] = Original(rotulo, url=url, sha256=sha256, quando=quando, selo=selo, nota=nota,
                                          registro=registro, confere=confere)
        return chave

    def sem_original(self, chave: str, rotulo: str, nota: str = "", selo: str = "azul") -> str:
        if chave not in self.tabela:
            self.tabela[chave] = Original(rotulo, selo=selo, nota=(nota + " " if nota else "")
                                          + SEM_ORIGINAL + ".")
        return chave

    def como_dict(self, chaves: set[str] | None = None) -> dict:
        return {k: o.como_dict() for k, o in sorted(self.tabela.items()) if chaves is None or k in chaves}


# --- chaves das fontes mais usadas ---------------------------------------------------------------

def msc(o: Originais, mes: str) -> str:
    return o.de_coleta(f"msc:{mes}", f"Matriz de saldos contábeis de {mes} (SICONFI, Tesouro Nacional)",
                       "msc", mes, contem="classe 6")


def siconfi(o: Originais, demonstrativo: str, exercicio: int, periodo: int, selo: str = "azul") -> str:
    if demonstrativo == "DCA":
        alvo, rotulo = f"DCA {exercicio}", f"Balanço anual (DCA) de {exercicio} (SICONFI)"
    else:
        unidade = "bimestre" if demonstrativo == "RREO" else "quadrimestre"
        alvo = f"{demonstrativo} {exercicio}, {periodo}º {unidade}"
        rotulo = f"{demonstrativo} do {periodo}º {unidade} de {exercicio} (SICONFI)"
    mes = _mes_do_periodo(demonstrativo, exercicio, periodo)
    return o.de_coleta(f"siconfi:{alvo}:{selo}", rotulo, "siconfi", mes, alvo=alvo, selo=selo)


def _mes_do_periodo(demonstrativo: str, exercicio: int, periodo: int) -> str:
    if demonstrativo == "DCA":
        return f"{exercicio}-12"
    passo = 2 if demonstrativo == "RREO" else 4
    return f"{exercicio}-{periodo * passo:02d}"


def externo_periodo(o: Originais, fonte: str, exercicio: int, periodo: int) -> str:
    """SIOPS e SIOPE: o bimestre declarado pelo Município ao Ministério."""
    motor = fonte.lower()
    mes = f"{exercicio}-{periodo * 2:02d}"
    return o.de_coleta(f"{motor}:{exercicio}-{periodo}", f"{fonte} do {periodo}º bimestre de {exercicio}",
                       motor, mes, alvo=f"{exercicio}-{periodo}")


def transferencias(o: Originais, mes: str) -> str:
    return o.de_coleta(f"transf:{mes}", f"Portal da Transparência: transferências da União em {mes}",
                       "transferencias", mes, alvo="mes")


def fnas(o: Originais, ano: str) -> str:
    return o.de_coleta(f"fnas:{ano}", f"Planilha de repasses do FNAS de {ano}", "fnas", f"{ano}-12",
                       contem="planilha")


def pncp(o: Originais, cnpj: str, mes: str, nome: str = "") -> str:
    """A leitura dos contratos de um órgão no PNCP que cobre o mês."""
    chave = f"pncp:{cnpj}:{mes}"
    if chave in o.tabela:
        return chave
    rotulo = f"PNCP: contratos de {nome.title() if nome else cnpj}"
    for (motor, m), linhas in o._carregar().items():
        if motor != "pncp":
            continue
        for a, url, sha, quando, rowid in linhas:
            if not a.startswith(f"contratos {cnpj} "):
                continue
            janela = re.findall(r"\d{4}-\d{2}", a)
            if janela and janela[0] <= mes <= janela[-1]:
                o.tabela[chave] = o._de_linha(rotulo, url, sha, quando, rowid)
                return chave
    return o.sem_original(chave, rotulo)
