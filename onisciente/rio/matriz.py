"""Leitura da Matriz de Saldos Contábeis (MSC) guardada no banco histórico.

A MSC é a segunda via do RREO: o Município a entrega todo mês, conta a conta, e o Tesouro a homologa
em separado. Aqui se leem dela a receita realizada por natureza (com as deduções que não são do
FUNDEB, como faz o RREO na receita líquida de cada imposto) e a despesa empenhada, liquidada e paga
por fonte, função e natureza.

Contas (PCASP, classe 6, movimento do mês):

* 6.2.1.2 receita realizada; 6.2.1.3.1.01 dedução para o FUNDEB; 6.2.1.3.9 outras deduções
  (restituições, descontos); a natureza começa por 7 ou 8 nas intraorçamentárias.
* 6.2.2.1.3 crédito empenhado: .01 a liquidar, .02 em liquidação, .03 liquidado a pagar, .04 pago;
  no encerramento do exercício, .05 inscrito em restos a pagar não processados e .07 liquidado e
  inscrito em restos a pagar processados. O movimento líquido (crédito menos débito) da conta inteira
  é o empenhado do mês; o de .03, .04 e .07 é o liquidado; o de .04 é o pago. A modalidade 91 da
  natureza da despesa é intraorçamentária.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

_SOMA = "sum(case when natureza_conta = 'C' then valor else -valor end)"


@dataclass(frozen=True)
class Natureza:
    """Uma espécie de receita na MSC: os prefixos da natureza que entram e os que saem."""

    entram: tuple[str, ...]
    saem: tuple[str, ...] = ()


def meses_entregues(con: sqlite3.Connection) -> set[str]:
    try:
        return {m for (m,) in con.execute("select mes from msc_meses where situacao = 'entregue'")}
    except sqlite3.OperationalError:
        return set()


def _filtro(n: Natureza) -> tuple[str, list[str]]:
    dentro = " or ".join("natureza_receita like ?" for _ in n.entram)
    sql = f"({dentro})"
    args = [p + "%" for p in n.entram]
    for p in n.saem:
        sql += " and natureza_receita not like ?"
        args.append(p + "%")
    return sql, args


def receita(con: sqlite3.Connection, n: Natureza, meses: list[str] | set[str]) -> dict[str, float]:
    """Receita realizada por mês, líquida das deduções que não são do FUNDEB (como no RREO)."""
    if not meses:
        return {}
    filtro, args = _filtro(n)
    marcas = ",".join("?" for _ in meses)
    linhas = con.execute(
        f"select mes, {_SOMA} from msc_itens where (conta_contabil like '6212%' or conta_contabil like '62139%') "
        f"and {filtro} and mes in ({marcas}) group by mes", [*args, *sorted(meses)])
    return {m: v or 0.0 for m, v in linhas}


def receita_realizada(con: sqlite3.Connection, meses: list[str] | set[str]) -> float | None:
    """A receita realizada exceto intraorçamentária, menos todas as deduções (a do Anexo 1 do RREO)."""
    if not meses:
        return None
    marcas = ",".join("?" for _ in meses)
    bruta = con.execute(
        f"select {_SOMA} from msc_itens where conta_contabil like '6212%' and natureza_receita not like '7%' "
        f"and natureza_receita not like '8%' and mes in ({marcas})", sorted(meses)).fetchone()[0]
    deducoes = con.execute(
        f"select {_SOMA} from msc_itens where conta_contabil like '6213%' and natureza_receita not like '7%' "
        f"and natureza_receita not like '8%' and mes in ({marcas})", sorted(meses)).fetchone()[0]
    if bruta is None:
        return None
    return bruta + (deducoes or 0.0)


def deducao_fundeb(con: sqlite3.Connection, meses: list[str] | set[str]) -> float:
    if not meses:
        return 0.0
    marcas = ",".join("?" for _ in meses)
    v = con.execute(f"select {_SOMA} from msc_itens where conta_contabil like '6213101%' and mes in ({marcas})",
                    sorted(meses)).fetchone()[0]
    return -(v or 0.0)


@dataclass(frozen=True)
class Execucao:
    empenhado: float
    liquidado: float
    pago: float


def despesa(con: sqlite3.Connection, meses: list[str] | set[str]) -> Execucao | None:
    """A despesa exceto intraorçamentária: empenhada, liquidada e paga nos meses."""
    if not meses:
        return None
    marcas = ",".join("?" for _ in meses)
    soma = {}
    for chave, prefixo in (("emp", "62213%"), ("liq3", "6221303%"), ("liq7", "6221307%"), ("pago", "6221304%")):
        soma[chave] = con.execute(
            f"select {_SOMA} from msc_itens where conta_contabil like ? and substr(natureza_despesa, 3, 2) != '91' "
            f"and mes in ({marcas})", [prefixo, *sorted(meses)]).fetchone()[0]
    if soma["emp"] is None:
        return None
    pago = soma["pago"] or 0.0
    return Execucao(soma["emp"], (soma["liq3"] or 0.0) + (soma["liq7"] or 0.0) + pago, pago)


@dataclass(frozen=True)
class Empenho:
    """O empenhado (movimento líquido) de uma fonte numa função, subfunção e natureza da despesa."""

    fonte: str
    funcao: str
    subfuncao: str
    natureza: str
    valor: float


def empenhos_por_fonte(con: sqlite3.Connection, meses: list[str] | set[str]) -> list[Empenho]:
    if not meses:
        return []
    marcas = ",".join("?" for _ in meses)
    linhas = con.execute(
        f"select fonte_recursos, funcao, subfuncao, natureza_despesa, {_SOMA} from msc_itens "
        f"where conta_contabil like '62213%' and substr(natureza_despesa, 3, 2) != '91' and mes in ({marcas}) "
        f"group by 1, 2, 3, 4", sorted(meses))
    return [Empenho(str(f or ""), str(fn or "").zfill(2), str(sf or ""), str(nd or ""), v or 0.0)
            for f, fn, sf, nd, v in linhas]


def receitas_do_mes(con: sqlite3.Connection, mes: str, prefixos: tuple[str, ...]) -> list[tuple[str, str, float]]:
    """(natureza, fonte, valor) de um mês, nas naturezas dos prefixos: para achar onde um valor foi parar."""
    dentro = " or ".join("natureza_receita like ?" for _ in prefixos)
    linhas = con.execute(
        f"select natureza_receita, fonte_recursos, {_SOMA} from msc_itens where conta_contabil like '6212%' "
        f"and mes = ? and ({dentro}) group by 1, 2", [mes, *(p + "%" for p in prefixos)])
    return [(str(n), str(f), v or 0.0) for n, f, v in linhas]


def receita_por_fonte(con: sqlite3.Connection, n: Natureza, meses: list[str] | set[str]) -> dict[str, float]:
    """Receita realizada nos meses, por fonte de recursos (código de quatro dígitos)."""
    out: dict[str, float] = {}
    for (f, _m), v in receita_por_fonte_e_mes(con, n, meses).items():
        out[f] = out.get(f, 0.0) + v
    return out


def receita_por_fonte_e_mes(con: sqlite3.Connection, n: Natureza, meses: list[str] | set[str]
                            ) -> dict[tuple[str, str], float]:
    if not meses:
        return {}
    filtro, args = _filtro(n)
    marcas = ",".join("?" for _ in meses)
    linhas = con.execute(
        f"select fonte_recursos, mes, {_SOMA} from msc_itens where (conta_contabil like '6212%' or "
        f"conta_contabil like '62139%') and {filtro} and mes in ({marcas}) group by 1, 2", [*args, *sorted(meses)])
    return {(str(f or ""), m): v or 0.0 for f, m, v in linhas}
