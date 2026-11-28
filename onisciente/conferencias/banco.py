"""As conferências do Município sobre o banco histórico, todas de uma vez.

Cada conferência lê só o que já está em ``dados/onisciente/historico.db`` (RREO, RGF, DCA, matriz
de saldos contábeis, extrato de entregas do SICONFI, contratos e termos do PNCP, registro das
coletas) e devolve uma ``Parte``: quadros para o parecer (cada linha com selo e, quando há, o
original de onde o número saiu), fichas e ausências. Onde o dado não existe, a conferência roda
assim mesmo: a falta vira ausência com o órgão que tem o documento, e o ofício sai pronto.

Os limiares vêm do mapa legal (``regras/mapa_legal.yml``), cada um com valor, justificativa e
base. Alerta é indício, não acusação: a ficha afirma só o que os níveis de prova permitem.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from .. import RAIZ
from ..legal.mapa import MapaLegal
from ..nucleo.ausencias import Ausencia
from ..nucleo.custodia import Original
from ..nucleo.indicios import Ficha
from ..nucleo.selos import Certificacao, Selo
from ..rastreio import registro_da_coleta, resumo_da_cadeia

if TYPE_CHECKING:
    from ..contas import Conta
    from ..fiscal import Leitor

SOMA = "sum(case when natureza_conta = 'C' then valor else -valor end)"

# Órgãos que guardam cada documento (Lei 9.262/2013: o pedido corre pelo Serviço de Informação
# ao Cidadão, mas quem tem o documento é quem responde por ele).
SEMAD = "Secretaria Municipal de Administração de Goiânia"
FAZENDA = "Secretaria Municipal de Finanças de Goiânia (SEFIN)"
EDUCACAO = "Secretaria Municipal de Educação de Goiânia"
PREVIDENCIA = "Instituto de Previdência dos Servidores do Município de Goiânia (GOIANIAPREV)"
CAMARA = "Câmara Municipal de Goiânia"
TCM = "Tribunal de Contas dos Municípios do Estado de Goiás"
CGM = "Controladoria Geral do Município de Goiânia"
CASA_CIVIL = "Casa Civil do Município de Goiânia"


@dataclass
class Linha:
    """Uma linha de quadro: todo número sai com selo e, quando há, com o original."""

    rotulo: str
    valores: list
    selo: Selo | None
    original: Original | None = None

    def como_dict(self) -> dict:
        return {"rotulo": self.rotulo, "valores": self.valores,
                "selo": self.selo.value if self.selo else None,
                "original": self.original.como_dict() if self.original else None}


@dataclass
class Quadro:
    """Um quadro do parecer. ``secao`` diz em qual das nove seções ele entra."""

    secao: int
    titulo: str
    explica: str
    colunas: list[str]
    linhas: list[Linha] = field(default_factory=list)
    regra: str = ""
    notas: list[str] = field(default_factory=list)

    def como_dict(self) -> dict:
        return {"secao": self.secao, "titulo": self.titulo, "explica": self.explica,
                "colunas": self.colunas, "regra": self.regra, "notas": self.notas,
                "linhas": [linha.como_dict() for linha in self.linhas]}


@dataclass
class Parte:
    quadros: list[Quadro] = field(default_factory=list)
    fichas: list[Ficha] = field(default_factory=list)
    ausencias: list[Ausencia] = field(default_factory=list)
    certificacoes: list[Certificacao] = field(default_factory=list)
    notas: list[str] = field(default_factory=list)
    contas: list["Conta"] = field(default_factory=list)
    parcerias: list = field(default_factory=list)          # as parcerias medidas uma a uma (prestacao.py)
    exercicio_das_parcerias: int | None = None


@dataclass
class Auditoria:
    """O resultado de todas as conferências sobre o banco até uma data."""

    ate: date
    quadros: list[Quadro] = field(default_factory=list)
    fichas_base: list[Ficha] = field(default_factory=list)
    ausencias: list[Ausencia] = field(default_factory=list)
    certificacoes: list[Certificacao] = field(default_factory=list)
    contas: list["Conta"] = field(default_factory=list)
    custodia: list[Original] = field(default_factory=list)
    custodia_por_motor: list[dict] = field(default_factory=list)
    notas: list[str] = field(default_factory=list)
    parcerias: list = field(default_factory=list)
    exercicio_das_parcerias: int | None = None
    # A cadeia do rastreio por hash no banco (última rodada, hash, raiz e se a cadeia confere).
    rastreio: dict = field(default_factory=dict)

    def juntar(self, parte: Parte) -> None:
        self.quadros += parte.quadros
        self.fichas_base += parte.fichas
        self.ausencias += parte.ausencias
        self.certificacoes += parte.certificacoes
        self.notas += parte.notas
        self.contas += parte.contas
        if parte.parcerias:
            self.parcerias += parte.parcerias
            self.exercicio_das_parcerias = parte.exercicio_das_parcerias

    def fichas(self, competencia: str) -> list[Ficha]:
        vistos: set[str] = set()
        saida = []
        for f in self.fichas_base:
            if f.codigo in vistos:
                continue
            vistos.add(f.codigo)
            saida.append(replace(f, competencia=competencia))
        return saida

    def da_secao(self, secao: int) -> list[Quadro]:
        return [q for q in self.quadros if q.secao == secao]

    def como_dict(self) -> dict:
        return {"ate": self.ate.isoformat(), "quadros": [q.como_dict() for q in self.quadros],
                "ausencias": [a.como_dict() for a in self.ausencias],
                "contas": [{"exercicio": c.exercicio, "orgao": c.orgao, "tipo": c.tipo,
                            "conferencia": c.conferencia, "atrasos": c.atrasos} for c in self.contas],
                "custodia_por_motor": self.custodia_por_motor, "notas": self.notas, "rastreio": self.rastreio}


class Base:
    """O banco lido até uma data: nada depois de ``ate`` entra na conferência."""

    def __init__(self, lt: "Leitor", ate: date, mapa: MapaLegal, raiz: Path = RAIZ):
        self.lt = lt
        self.con: sqlite3.Connection = lt.con
        self.ate = ate
        self.mapa = mapa
        self.raiz = Path(raiz)
        self._tabelas = {n for (n,) in self.con.execute("select name from sqlite_master where type='table'")}

    def tem(self, tabela: str) -> bool:
        return tabela in self._tabelas

    @property
    def mes_limite(self) -> str:
        return f"{self.ate.year:04d}-{self.ate.month:02d}"

    def meses_msc(self) -> list[str]:
        if not self.tem("msc_meses"):
            return []
        return [m for (m,) in self.con.execute(
            "select mes from msc_meses where situacao = 'entregue' and mes <= ? order by mes", (self.mes_limite,))]

    def coleta(self, motor: str, alvo: str | None = None, mes: str | None = None) -> Original | None:
        """O original de uma coleta (endereço, data e impressão digital), se o banco o registrou, com o
        hash da linha da coleta (o registro em que o achado se apoia) e o da requisição."""
        if not self.tem("coletas"):
            return None
        sql = ("select url, quando, sha256, alvo, rowid from coletas where motor = ? and ok = 1 "
               "and sha256 is not null")
        args: list = [motor]
        if alvo is not None:
            sql += " and alvo = ?"
            args.append(alvo)
        if mes is not None:
            sql += " and mes = ?"
            args.append(mes)
        linha = self.con.execute(sql + " order by quando desc limit 1", args).fetchone()
        if not linha:
            return None
        url, quando, sha, nome, rowid = linha
        registro, requisicao = registro_da_coleta(self.con, rowid)
        return Original(url=url, coletado_em=(quando or "")[:10], sha256=sha, fonte=f"{motor}: {nome}",
                        registro=registro or "", requisicao=requisicao or "")

    def original_do_periodo(self, demonstrativo: str, exercicio: int, periodo: int) -> Original | None:
        if demonstrativo == "RREO":
            return self.coleta("siconfi", f"RREO {exercicio}, {periodo}º bimestre")
        if demonstrativo == "RGF":
            return self.coleta("siconfi", f"RGF {exercicio}, {periodo}º quadrimestre")
        return self.coleta("siconfi", f"{demonstrativo} {exercicio}")

    def original_msc(self, mes: str) -> Original | None:
        return self.coleta("msc", mes=mes)


def moeda(v: float | None) -> str:
    from ..fiscal import _moeda
    return _moeda(v)


def pct(v: float | None, casas: int = 1) -> str:
    if v is None:
        return "sem dado"
    return f"{v:.{casas}f}".replace(".", ",") + "%"


def custodia_do_banco(base: Base) -> tuple[list[Original], list[dict]]:
    """Os originais de cada coleta guardada: endereço, data e impressão digital de cada leitura.

    O banco guarda o trecho que interessa e a impressão digital do que foi lido; o original
    completo fica na fonte. Para as coletas muito numerosas (PNCP), o parecer mostra a contagem e a
    impressão digital do conjunto, que muda se qualquer leitura mudar.
    """
    from ..nucleo.custodia import impressao
    if not base.tem("coletas"):
        return [], []
    originais: list[Original] = []
    resumo: list[dict] = []
    motores = [m for (m,) in base.con.execute("select distinct motor from coletas order by motor")]
    for motor in motores:
        linhas = base.con.execute(
            "select alvo, mes, url, quando, sha256, rowid from coletas where motor = ? and ok = 1 "
            "and sha256 is not null and (mes is null or mes = '' or mes <= ?) order by mes, alvo",
            (motor, base.mes_limite)).fetchall()
        if not linhas:
            continue
        conjunto = impressao("\n".join(sorted(s for *_, s, _r in linhas)))
        resumo.append({"motor": motor, "leituras": len(linhas), "impressao_do_conjunto": conjunto,
                       "primeira": min((q or "")[:10] for *_, q, _s, _r in linhas),
                       "ultima": max((q or "")[:10] for *_, q, _s, _r in linhas)})
        if len(linhas) <= 60:
            for a, _m, u, q, s, rowid in linhas:
                registro, requisicao = registro_da_coleta(base.con, rowid)
                originais.append(Original(url=u, coletado_em=(q or "")[:10], sha256=s, fonte=f"{motor}: {a}",
                                          registro=registro or "", requisicao=requisicao or ""))
    return originais, resumo


CONFERENCIAS: list[Callable[[Base], Parte]] = []


def conferir(lt: "Leitor", ate: date, mapa: MapaLegal, *, raiz: Path = RAIZ) -> Auditoria:
    """Roda todas as conferências sobre o banco até ``ate``."""
    from . import (contas_unidades, custo_fixo, genericas, gestores, heranca, lei_organica, mandato,
                   pessoal, prestacao, restos, serie)
    base = Base(lt, ate, mapa, raiz)
    auditoria = Auditoria(ate=ate)
    for conferencia in (restos.conferir, genericas.conferir, custo_fixo.conferir, pessoal.conferir,
                        mandato.conferir, gestores.conferir, contas_unidades.conferir, prestacao.conferir,
                        lei_organica.conferir, serie.conferir, heranca.conferir, *CONFERENCIAS):
        auditoria.juntar(conferencia(base))
    auditoria.custodia, auditoria.custodia_por_motor = custodia_do_banco(base)
    auditoria.rastreio = resumo_da_cadeia(base.con)
    return auditoria
