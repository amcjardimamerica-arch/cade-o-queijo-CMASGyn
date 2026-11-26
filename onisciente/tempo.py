"""Máquina do tempo: de 2019 até o fim do PPA.

Para trás: previsto, pago e prestado. Para a frente: o que o PPA promete e a
projeção do próprio Onisciente pela execução média dos últimos três anos. A
projeção aparece sempre como projeção, com a régua usada.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class Exercicio:
    ano: int
    previsto: float
    pago: float | None = None

    @property
    def execucao(self) -> float | None:
        if self.pago is None or not self.previsto:
            return None
        return self.pago / self.previsto


def taxa_media(historico: list[Exercicio], anos: int = 3) -> float | None:
    taxas = [e.execucao for e in sorted(historico, key=lambda e: e.ano) if e.execucao is not None]
    ultimas = taxas[-anos:]
    if len(ultimas) < anos:
        return None
    return sum(ultimas) / len(ultimas)


def projetar(historico: list[Exercicio], promessa_ppa: Mapping[int, float], anos: int = 3) -> list[dict]:
    """Projeta o pago de cada ano futuro pela execução média dos últimos ``anos``."""
    taxa = taxa_media(historico, anos)
    saida = []
    for ano in sorted(promessa_ppa):
        prometido = promessa_ppa[ano]
        linha = {"ano": ano, "prometido": prometido, "tipo": "projeção",
                 "regua": f"execução média dos últimos {anos} anos"}
        if taxa is None:
            linha.update(projetado=None, diferenca=None,
                         nota="série insuficiente para projetar")
        else:
            projetado = round(prometido * taxa, 2)
            linha.update(projetado=projetado, taxa=round(taxa, 4),
                         diferenca=round(prometido - projetado, 2))
        saida.append(linha)
    return saida
