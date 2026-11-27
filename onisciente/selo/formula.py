"""A fórmula do índice do PNTP, os níveis e a regra dos essenciais.

Pela cartilha do ciclo 2026 (Atricon): o peso de cada dimensão (4, 3, 2 ou 1) se reparte entre os
critérios dela na proporção do peso de exigibilidade (essencial 2, obrigatório 1,5, recomendado 1);
dentro de cada critério, os itens de verificação valem disponibilidade 30%, atualidade 30%, série
histórica 20%, gravação 10% e filtro 10%, e o item que não se aplica tem o percentual redistribuído
entre os demais. O índice vai de 0 a 100. Diamante, Ouro e Prata exigem 100% dos essenciais; com um
essencial em falta o ente fica no nível Elevado, mesmo com índice de 75% ou mais.

Cada item chega como ``True`` (comprovado), ``False`` (comprovadamente em falta) ou ``None`` (sem
prova). A nota comprovada conta ``None`` como zero; o teto conta ``None`` como atendido. Assim o teto
diz o máximo que o ente pode ter com o que já se provou contra ele.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

from .matriz import Criterio, Matriz

LEITURAS = ("oficial", "restritiva")


def itens_da_leitura(c: Criterio, matriz: Matriz, leitura: str) -> tuple[str, ...]:
    """Os itens que contam no critério. Na leitura oficial do ciclo 2026 a gravação fica fora (E03)."""
    itens = c.itens
    if leitura == "oficial" and not matriz.metodologia.get("gravacao_obrigatoria_no_ciclo", True):
        sem = tuple(i for i in itens if i != "gravacao")
        itens = sem or itens
    return itens


def fracao(itens: dict[str, bool | None], aplicaveis: tuple[str, ...], pesos: dict[str, float],
           *, otimista: bool = False) -> float:
    """Fração atendida do critério, com redistribuição proporcional dos itens que não se aplicam."""
    total = sum(pesos[i] for i in aplicaveis)
    if not total:
        return 0.0
    obtido = 0.0
    for i in aplicaveis:
        v = itens.get(i)
        if v is True or (v is None and otimista):
            obtido += pesos[i]
    return obtido / total


def essencial_atendido(itens: dict[str, bool | None], aplicaveis: tuple[str, ...], leitura: str,
                       *, otimista: bool = False) -> bool:
    """E02: na leitura oficial basta a disponibilidade; na restritiva todos os itens aplicáveis."""
    def ok(v):
        return v is True or (v is None and otimista)
    if leitura == "oficial":
        return ok(itens.get("disponibilidade"))
    return all(ok(itens.get(i)) for i in aplicaveis)


def indice(fracoes: dict[str, float], criterios: list[Criterio], dimensoes: dict, pesos_exig: dict,
           *, truncar: bool = False) -> float:
    """Índice de 0 a 100: soma_d [peso_d x soma_c(e_c x f_c) / soma_c(e_c)] / soma_d(peso_d)."""
    por_dim: dict = defaultdict(list)
    for c in criterios:
        por_dim[c.dimensao].append(c)
    num = den = 0.0
    for d, lista in por_dim.items():
        peso_d = float(dimensoes[d]["peso"])
        soma_e = sum(pesos_exig[c.classe] for c in lista)
        num += peso_d * sum(pesos_exig[c.classe] * fracoes.get(c.id, 0.0) for c in lista) / soma_e
        den += peso_d
    valor = 100.0 * num / den if den else 0.0
    if truncar:
        return math.floor(valor * 100 + 1e-9) / 100
    return round(valor, 2)


def nivel(valor: float, essenciais_ok: bool, faixas: list[dict]) -> dict:
    """O nível e o selo pelo índice e pela regra dos essenciais."""
    for f in faixas:
        if f["exige_essenciais"] and not essenciais_ok:
            continue
        if not f["exige_essenciais"] and f["nivel"] == "Elevado" and essenciais_ok:
            continue
        if f["minimo"] <= valor < f["maximo"] or (f["maximo"] >= 100 and valor >= f["minimo"]):
            return {"nivel": f["nivel"], "selo": bool(f["selo"])}
    return {"nivel": "Inexistente", "selo": False}


@dataclass
class Nota:
    leitura: str
    modo: str                      # comprovada ou teto
    indice: float
    essenciais_ok: bool
    nivel: str
    selo: bool
    essenciais_em_falta: list[str] = field(default_factory=list)

    def como_dict(self) -> dict:
        return {"leitura": self.leitura, "modo": self.modo, "indice": self.indice,
                "essenciais_ok": self.essenciais_ok, "nivel": self.nivel, "selo": self.selo,
                "essenciais_em_falta": self.essenciais_em_falta}


def calcular(itens_por_criterio: dict[str, dict[str, bool | None]], criterios: list[Criterio], matriz: Matriz,
             leitura: str, *, otimista: bool, dimensoes: dict | None = None,
             pesos_exig: dict | None = None) -> Nota:
    """A nota de uma leitura num modo (comprovada ou teto) a partir dos itens de cada critério."""
    met = matriz.metodologia
    pesos = met["itens"]
    pesos_exig = pesos_exig or met["pesos_exigibilidade"]
    dimensoes = dimensoes or matriz.dimensoes
    fr: dict[str, float] = {}
    em_falta: list[str] = []
    for c in criterios:
        aplic = itens_da_leitura(c, matriz, leitura)
        itens = itens_por_criterio.get(c.id, {})
        fr[c.id] = fracao(itens, aplic, pesos, otimista=otimista)
        if c.essencial and not essencial_atendido(itens, aplic, leitura, otimista=otimista):
            em_falta.append(c.id)
    valor = indice(fr, criterios, dimensoes, pesos_exig, truncar=(leitura == "restritiva"))
    n = nivel(valor, not em_falta, met["faixas"])
    return Nota(leitura, "teto" if otimista else "comprovada", valor, not em_falta, n["nivel"], n["selo"],
                sorted(em_falta, key=lambda x: [(0, int(p), "") if p.isdigit() else (1, 0, p) for p in x.split(".")]))
