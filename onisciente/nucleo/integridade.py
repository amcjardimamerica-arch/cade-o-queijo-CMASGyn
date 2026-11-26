"""Índice de integridade da trilha.

Substitui o antigo índice de transparência por uma medida objetiva, de 0 a 100:

=================  =====  ===========================================================
Medida             Peso   Como se mede
=================  =====  ===========================================================
Cobertura          40     fração do valor pago que atravessa as nove estações
Coerência          25     fração dos valores em que as vias dizem o mesmo (selo verde)
Tempestividade     15     publicação no tempo exigido
Vínculo            10     fração do pago com contrato, termo ou folha publicados
Prestação          10     fração das parcerias com prestação individualizada publicada
=================  =====  ===========================================================

A nota abaixo do mínimo do mapa legal (50) já sai com o pedido de acesso.
"""

from __future__ import annotations

from dataclasses import dataclass

PESOS = {
    "cobertura": 40,
    "coerencia": 25,
    "tempestividade": 15,
    "vinculo": 10,
    "prestacao": 10,
}


def _fracao(valor: float) -> float:
    if valor is None:
        return 0.0
    return max(0.0, min(1.0, float(valor)))


@dataclass(frozen=True)
class IndiceIntegridade:
    cobertura: float
    coerencia: float
    tempestividade: float
    vinculo: float
    prestacao: float
    minimo: float = 50.0

    @property
    def partes(self) -> dict[str, float]:
        return {nome: round(_fracao(getattr(self, nome)) * peso, 2) for nome, peso in PESOS.items()}

    @property
    def nota(self) -> float:
        return round(sum(self.partes.values()), 1)

    @property
    def gera_pedido_de_acesso(self) -> bool:
        return self.nota < self.minimo

    def como_dict(self) -> dict:
        return {
            "nota": self.nota,
            "partes": self.partes,
            "fracoes": {nome: round(_fracao(getattr(self, nome)), 4) for nome in PESOS},
            "gera_pedido_de_acesso": self.gera_pedido_de_acesso,
        }
