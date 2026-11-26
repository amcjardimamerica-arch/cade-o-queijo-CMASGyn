"""Preço pago contra a referência nacional (família PRC).

O preço unitário do contrato é comparado à mediana nacional do mesmo item no
semestre (PNCP e painel de preços do Compras.gov.br). Destoa quando passa da
mediana em mais que o limite do mapa legal (40%) ou fica acima do percentil 95
das compras do país.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Sequence

from ..legal.mapa import MapaLegal, carregar
from ..nucleo.indicios import Familia, Ficha, emitir
from ..nucleo.provas import Nivel


def percentil(valores: Sequence[float], p: float) -> float:
    """Percentil por interpolação linear (p entre 0 e 100)."""
    ordenados = sorted(valores)
    if not ordenados:
        raise ValueError("sem valores de referência")
    if len(ordenados) == 1:
        return ordenados[0]
    pos = (len(ordenados) - 1) * p / 100.0
    baixo = int(pos)
    alto = min(baixo + 1, len(ordenados) - 1)
    return ordenados[baixo] + (ordenados[alto] - ordenados[baixo]) * (pos - baixo)


@dataclass(frozen=True)
class ComparacaoDePreco:
    item: str
    preco: float
    mediana: float
    p95: float
    amostra: int
    excesso_pct: float
    destoa: bool
    motivo: str


def comparar(item: str, preco: float, referencia: Sequence[float], *,
             mapa: MapaLegal | None = None, amostra_minima: int = 5) -> ComparacaoDePreco | None:
    """Compara um preço unitário com a referência. ``None`` se a amostra é pequena demais."""
    if len(referencia) < amostra_minima:
        return None
    regra = (mapa or carregar()).regra("PRECO-MEDIANA")
    limite = regra.valor or 40.0
    corte = float(regra.get("percentil", 95))
    med = median(referencia)
    p = percentil(referencia, corte)
    excesso = (preco / med - 1.0) * 100.0 if med else 0.0
    motivos = []
    if excesso > limite:
        motivos.append(f"{excesso:.1f}% acima da mediana nacional (limite {limite:g}%)")
    if preco > p:
        motivos.append(f"acima do percentil {corte:g} das compras do país")
    return ComparacaoDePreco(item, preco, med, p, len(referencia), round(excesso, 2),
                             bool(motivos), "; ".join(motivos))


def ficha_de_sobrepreco(c: ComparacaoDePreco, *, contrato: str, competencia: str | None = None) -> Ficha:
    return emitir(
        codigo=f"PRC-SOB02-{contrato}",
        familia=Familia.PRC,
        titulo=f"Preço de {c.item} fora da curva nacional",
        gravidade="alta",
        como_deveria="O preço contratado deve ficar na faixa praticada no país para o mesmo item, "
                     "com pesquisa de preço publicada.",
        norma="Lei 14.133/2021, art. 23",
        como_esta=f"Preço unitário {c.preco:,.2f}; mediana nacional {c.mediana:,.2f} "
                  f"em {c.amostra} compras; {c.motivo}.",
        niveis=[Nivel.C, Nivel.B],
        providencia="Pedir a pesquisa de preços do processo e a justificativa do valor contratado.",
        competencia=competencia,
    )
