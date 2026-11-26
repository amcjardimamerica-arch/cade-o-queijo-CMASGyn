"""Ausência é descumprimento.

Onde a trilha se interrompe por falta de publicação, o buraco é o dado. Todo
alerta roxo responde a três perguntas: o que falta, que conferência ficou
impedida e onde deveria estar (com o fundamento).
"""

from __future__ import annotations

from dataclasses import dataclass

from .selos import Selo

FUNDAMENTO_PADRAO = (
    "LC 101/2000, arts. 48 e 48-A; Lei 12.527/2011, art. 8º; "
    "Lei municipal 9.262/2013, art. 7º, § 3º"
)


@dataclass(frozen=True)
class Ausencia:
    o_que_falta: str
    conferencia_impedida: str
    onde_deveria_estar: str
    fundamento: str = FUNDAMENTO_PADRAO
    periodo: str = ""
    orgao: str = ""
    bloco: str = ""

    selo: Selo = Selo.ROXO

    def como_dict(self) -> dict:
        return {
            "o_que_falta": self.o_que_falta,
            "periodo": self.periodo,
            "conferencia_impedida": self.conferencia_impedida,
            "onde_deveria_estar": self.onde_deveria_estar,
            "fundamento": self.fundamento,
            "orgao": self.orgao,
            "bloco": self.bloco,
            "selo": self.selo.value,
        }
