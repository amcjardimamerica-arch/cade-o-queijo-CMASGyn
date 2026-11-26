"""Níveis de prova, herdados do Cadê o Queijo.

Cada documento oficial tem um nível, e o nível diz o que se pode afirmar com ele.
Três travas valem sempre:

* afirmar pagamento exige nível A ou B;
* afirmar vínculo exige pelo menos nível C;
* afirmar irregularidade exige duas fontes de níveis distintos.
"""

from __future__ import annotations

from enum import Enum
from typing import Iterable


class Nivel(Enum):
    """Nível de prova de um documento. O valor é o peso."""

    A = 5  # ordem bancária ou extrato
    B = 4  # execução publicada com credor identificado
    C = 3  # instrumento: contrato, termo, convênio, folha
    D = 2  # autorização: LOA, QDD, decreto de crédito
    E = 1  # menção em ato posterior
    F = 0  # ausência

    @property
    def peso(self) -> int:
        return self.value

    @property
    def descricao(self) -> str:
        return _DESCRICOES[self]

    @classmethod
    def de(cls, valor: "Nivel | str") -> "Nivel":
        if isinstance(valor, Nivel):
            return valor
        return cls[str(valor).strip().upper()]

    def __ge__(self, outro: "Nivel") -> bool:  # type: ignore[override]
        return self.peso >= outro.peso

    def __gt__(self, outro: "Nivel") -> bool:  # type: ignore[override]
        return self.peso > outro.peso

    def __le__(self, outro: "Nivel") -> bool:  # type: ignore[override]
        return self.peso <= outro.peso

    def __lt__(self, outro: "Nivel") -> bool:  # type: ignore[override]
        return self.peso < outro.peso


_DESCRICOES = {
    Nivel.A: "ordem bancária ou extrato",
    Nivel.B: "execução publicada com credor identificado",
    Nivel.C: "instrumento (contrato, termo, convênio, folha)",
    Nivel.D: "autorização (LOA, QDD, decreto de crédito)",
    Nivel.E: "menção em ato posterior",
    Nivel.F: "ausência",
}


def pode_afirmar_pagamento(nivel: Nivel | str) -> bool:
    """Pagamento só se afirma com ordem bancária, extrato ou execução publicada."""
    return Nivel.de(nivel) in (Nivel.A, Nivel.B)


def pode_afirmar_vinculo(nivel: Nivel | str) -> bool:
    """Vínculo só se afirma com o instrumento (nível C) ou prova mais forte."""
    return Nivel.de(nivel) >= Nivel.C


def pode_afirmar_irregularidade(niveis: Iterable[Nivel | str]) -> bool:
    """Irregularidade exige duas fontes de níveis distintos (ausência não conta)."""
    distintos = {Nivel.de(n) for n in niveis} - {Nivel.F}
    return len(distintos) >= 2
