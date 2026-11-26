"""Padrões de gasto, sempre numa série para que o normal da própria pasta seja a régua."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Iterable, Mapping

from ..legal.mapa import MapaLegal, carregar


@dataclass(frozen=True)
class Pagamento:
    credor: str
    valor: float
    data: date
    com_contrato: bool = True


def concentracao(pagamentos: Iterable[Pagamento], *, mapa: MapaLegal | None = None) -> dict:
    """Quantos credores levam a fatia do pago que o mapa legal marca (80%)."""
    regra = (mapa or carregar()).regra("CONCENTRACAO")
    corte = (regra.valor or 80.0) / 100.0
    max_credores = int(regra.get("credores", 5))
    por_credor: Counter = Counter()
    for p in pagamentos:
        por_credor[p.credor] += p.valor
    total = sum(por_credor.values())
    if total <= 0:
        return {"total": 0.0, "credores": 0, "levam_o_corte": 0, "concentrado": False}
    acumulado, n = 0.0, 0
    for _, valor in por_credor.most_common():
        acumulado += valor
        n += 1
        if acumulado / total >= corte:
            break
    return {"total": round(total, 2), "credores": len(por_credor), "levam_o_corte": n,
            "corte_pct": corte * 100, "concentrado": len(por_credor) > n and n <= max_credores}


def recorrentes_sem_contrato(pagamentos: Iterable[Pagamento], minimo_de_meses: int = 3) -> list[str]:
    meses: dict[str, set] = defaultdict(set)
    for p in pagamentos:
        if not p.com_contrato:
            meses[p.credor].add((p.data.year, p.data.month))
    return sorted(c for c, m in meses.items() if len(m) >= minimo_de_meses)


def empenhos_no_fim_do_ano(empenhos: Iterable[Pagamento], dias: int = 15) -> float:
    """Fração do valor empenhado nos últimos ``dias`` do ano."""
    total = fim = 0.0
    for e in empenhos:
        total += e.valor
        if e.data.month == 12 and e.data.day > 31 - dias:
            fim += e.valor
    return round(fim / total, 4) if total else 0.0


def fora_da_serie(valor_atual: float, serie: Mapping[int, float], fator: float = 1.5) -> bool:
    """O valor do ano passa ``fator`` vezes a média dos três anos anteriores."""
    anos = sorted(serie)[-3:]
    if len(anos) < 3:
        return False
    media = sum(serie[a] for a in anos) / 3
    return media > 0 and valor_atual > fator * media
