"""A matriz do PNTP guardada em ``regras/pntp/`` e a conferência de que ela está inteira.

A matriz é dado versionado: cada critério com dimensão, classificação (essencial, obrigatório ou
recomendado), matriz de origem, itens de verificação, base legal e onde se verifica. ``problemas()``
diz o que torna a matriz imprestável para o cálculo (peso faltando, classificação desconhecida,
totais diferentes dos oficiais sem pendência registrada).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from .. import RAIZ

PASTA = RAIZ / "regras" / "pntp"
CLASSES = ("essencial", "obrigatorio", "recomendado")
ITENS = ("disponibilidade", "atualidade", "serie_historica", "gravacao", "filtro")
SIGLAS = {"D": "disponibilidade", "A": "atualidade", "S": "serie_historica", "G": "gravacao", "F": "filtro"}
ROTULO_ITEM = {"disponibilidade": "disponibilidade", "atualidade": "atualidade",
               "serie_historica": "série histórica", "gravacao": "gravação", "filtro": "filtro"}
ROTULO_CLASSE = {"essencial": "essencial", "obrigatorio": "obrigatório", "recomendado": "recomendado"}


@dataclass(frozen=True)
class Criterio:
    id: str
    dimensao: int | str
    classe: str
    matriz: str
    texto: str
    itens: tuple[str, ...]
    base_legal: str
    onde: tuple[str, ...] = ()
    termos: tuple[tuple[str, ...], ...] = ()
    aplica: bool = True
    automatico: bool = True
    atualidade_dias: int | None = None

    @property
    def essencial(self) -> bool:
        return self.classe == "essencial"

    @property
    def ordem(self) -> tuple:
        partes = str(self.id).split(".")
        return tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in partes)


@dataclass
class Matriz:
    ciclo: int
    dados: dict
    criterios: list[Criterio] = field(default_factory=list)

    @property
    def metodologia(self) -> dict:
        return self.dados["metodologia"]

    @property
    def dimensoes(self) -> dict:
        return {int(k): v for k, v in self.dados["dimensoes"].items()}

    @property
    def fontes(self) -> list[dict]:
        return self.dados.get("fontes") or []

    @property
    def pendencias(self) -> list[str]:
        return self.dados.get("pendencias") or []

    def do_executivo(self) -> list[Criterio]:
        """Os critérios que valem para a Prefeitura (matriz comum, do Executivo e Executivo e Consórcios)."""
        matrizes = set(self.dados.get("matrizes_do_executivo") or [])
        return [c for c in self.criterios if c.aplica and c.matriz in matrizes]

    def criterio(self, cid: str) -> Criterio:
        for c in self.criterios:
            if c.id == cid:
                return c
        raise KeyError(cid)

    def problemas(self) -> list[str]:
        erros: list[str] = []
        met = self.metodologia
        if set(met.get("pesos_exigibilidade", {})) != set(CLASSES):
            erros.append("pesos de exigibilidade incompletos")
        if set(met.get("itens", {})) != set(ITENS):
            erros.append("pesos dos itens de verificação incompletos")
        if abs(sum(met.get("itens", {}).values()) - 1.0) > 1e-9:
            erros.append("pesos dos itens não somam 100%")
        if not met.get("faixas"):
            erros.append("faixas dos níveis ausentes")
        vistos = set()
        for c in self.criterios:
            if c.id in vistos:
                erros.append(f"{c.id}: critério repetido")
            vistos.add(c.id)
            if c.classe not in CLASSES:
                erros.append(f"{c.id}: classificação desconhecida {c.classe!r}")
            if c.aplica and int(c.dimensao) not in self.dimensoes:
                erros.append(f"{c.id}: dimensão {c.dimensao} sem peso")
            if not c.itens or any(i not in ITENS for i in c.itens):
                erros.append(f"{c.id}: itens de verificação inválidos")
            if c.aplica and not c.base_legal:
                erros.append(f"{c.id}: sem base legal")
            if c.aplica and c.automatico and not c.termos:
                erros.append(f"{c.id}: sem termos para a verificação")
        for matriz, oficial in (self.dados.get("totais_oficiais") or {}).items():
            daqui = [c for c in self.criterios if c.matriz == matriz]
            for classe in CLASSES:
                n = sum(1 for c in daqui if c.classe == classe)
                if n != oficial[classe] and not any(matriz in p and str(n) in p for p in self.pendencias):
                    erros.append(f"matriz {matriz}: {n} critérios {classe}, oficial {oficial[classe]}, sem pendência")
        return erros


def _criterio(d: dict) -> Criterio:
    return Criterio(
        id=str(d["id"]), dimensao=d["dim"], classe=d["classe"], matriz=d["matriz"], texto=d["texto"],
        itens=tuple(SIGLAS.get(i, i) for i in d.get("itens") or ()), base_legal=d.get("base_legal") or "",
        onde=tuple(d.get("onde") or ()), termos=tuple(tuple(str(t).lower() for t in g) for g in d.get("termos") or ()),
        aplica=bool(d.get("aplica", True)), automatico=bool(d.get("automatico", True)),
        atualidade_dias=d.get("atualidade_dias"))


def ler(caminho: Path) -> Matriz:
    dados = yaml.safe_load(caminho.read_text(encoding="utf-8"))
    return Matriz(ciclo=int(dados["ciclo"]), dados=dados,
                  criterios=[_criterio(c) for c in dados.get("criterios") or []])


@lru_cache(maxsize=4)
def carregar(ciclo: int = 2026) -> Matriz:
    return ler(PASTA / f"matriz_{ciclo}.yml")


@lru_cache(maxsize=1)
def escolhas() -> list[dict]:
    return yaml.safe_load((PASTA / "escolhas.yml").read_text(encoding="utf-8"))["escolhas"]
