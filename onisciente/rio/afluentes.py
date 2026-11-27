"""O rio: afluentes, água vinculada e água livre, e as margens do que não chegou."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..nucleo.selos import Selo
from .fontes import Esfera, classificar


@dataclass(frozen=True)
class Afluente:
    nome: str
    esfera: Esfera
    valor: float
    fonte: str | None = None
    selo: Selo | None = None
    origem: str = ""

    @property
    def vinculado(self) -> bool | None:
        return classificar(self.fonte).vinculada if self.fonte else None


@dataclass
class Rio:
    competencia: str
    afluentes: list[Afluente] = field(default_factory=list)

    def total(self) -> float:
        return sum(a.valor for a in self.afluentes)

    def por_esfera(self) -> dict[Esfera, float]:
        soma: dict[Esfera, float] = {}
        for a in self.afluentes:
            soma[a.esfera] = soma.get(a.esfera, 0.0) + a.valor
        return soma

    def vinculada_e_livre(self) -> dict[str, float]:
        out = {"vinculada": 0.0, "livre": 0.0, "sem_fonte": 0.0}
        for a in self.afluentes:
            v = a.vinculado
            out["sem_fonte" if v is None else ("vinculada" if v else "livre")] += a.valor
        return out


@dataclass(frozen=True)
class Margens:
    """As águas que não chegam: é nas margens que o parecer começa.

    ``pago_com_vinculo`` é ``None`` quando o pago ainda não se cruzou com os instrumentos (contrato,
    termo, folha) item a item: a quarta margem fica sem medida, e nunca zero.
    """

    previsto: float
    empenhado: float
    liquidado: float
    pago: float
    pago_com_vinculo: float | None

    @property
    def previsto_nao_empenhado(self) -> float:
        return max(0.0, self.previsto - self.empenhado)

    @property
    def empenhado_nao_liquidado(self) -> float:
        return max(0.0, self.empenhado - self.liquidado)

    @property
    def liquidado_nao_pago(self) -> float:
        return max(0.0, self.liquidado - self.pago)

    @property
    def pago_sem_vinculo(self) -> float | None:
        if self.pago_com_vinculo is None:
            return None
        return max(0.0, self.pago - self.pago_com_vinculo)

    def como_dict(self) -> dict[str, float | None]:
        return {
            "previsto_nao_empenhado": self.previsto_nao_empenhado,
            "empenhado_nao_liquidado": self.empenhado_nao_liquidado,
            "liquidado_nao_pago": self.liquidado_nao_pago,
            "pago_sem_vinculo": self.pago_sem_vinculo,
        }
