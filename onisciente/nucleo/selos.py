"""Selos: a fonte se certifica.

Nenhum dado precisa de atestado humano. O selo diz de onde o dado veio e
quantas vias o confirmam:

* verde: duas vias independentes dizem o mesmo valor;
* azul: uma via oficial (prova, mas não sustenta sozinha uma irregularidade);
* roxo: a lei manda publicar e não está publicado;
* vermelho: o dado existe, mas a leitura automática não o alcançou.

A divergência entre vias não vai para fila nenhuma: o selo cai de verde para
azul e a própria divergência vira indício.

O selo não é a gravidade, que tem escala própria (crítica, alta, média), nem a
verificação da ficha (CONFIRMADO, INDICIÁRIO, INCONCLUSIVO).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable

from .custodia import Original
from .provas import Nivel


class Selo(Enum):
    VERDE = "verde"
    AZUL = "azul"
    ROXO = "roxo"
    VERMELHO = "vermelho"

    @property
    def significado(self) -> str:
        return {
            Selo.VERDE: "confirmado em duas vias independentes",
            Selo.AZUL: "confirmado em uma via oficial",
            Selo.ROXO: "a lei manda publicar e não está publicado",
            Selo.VERMELHO: "o dado existe, mas a leitura automática não o alcançou",
        }[self]

    @property
    def cor(self) -> str:
        return {
            Selo.VERDE: "#15803D",
            Selo.AZUL: "#2563EB",
            Selo.ROXO: "#7E22CE",
            Selo.VERMELHO: "#C81E1E",
        }[self]


class Gravidade(Enum):
    CRITICA = "critica"
    ALTA = "alta"
    MEDIA = "media"

    @property
    def ordem(self) -> int:
        return {Gravidade.CRITICA: 0, Gravidade.ALTA: 1, Gravidade.MEDIA: 2}[self]

    @property
    def rotulo(self) -> str:
        return {Gravidade.CRITICA: "crítica", Gravidade.ALTA: "alta", Gravidade.MEDIA: "média"}[self]

    @property
    def cor(self) -> str:
        return {Gravidade.CRITICA: "#E01B0E", Gravidade.ALTA: "#E07B00", Gravidade.MEDIA: "#A16207"}[self]

    @classmethod
    def de(cls, valor: "Gravidade | str") -> "Gravidade":
        if isinstance(valor, Gravidade):
            return valor
        t = str(valor).strip().lower().replace("í", "i").replace("é", "e")
        return cls(t)


class Verificacao(Enum):
    CONFIRMADO = "CONFIRMADO"      # duas vias
    INDICIARIO = "INDICIARIO"      # uma via
    INCONCLUSIVO = "INCONCLUSIVO"  # documento faltante, que também é achado

    @classmethod
    def de(cls, valor: "Verificacao | str") -> "Verificacao":
        if isinstance(valor, Verificacao):
            return valor
        t = str(valor).strip().upper().replace("Á", "A")
        if t.startswith("INCONCLUSIVO"):
            return cls.INCONCLUSIVO
        return cls(t)

    @property
    def rotulo(self) -> str:
        return {
            Verificacao.CONFIRMADO: "CONFIRMADO",
            Verificacao.INDICIARIO: "INDICIÁRIO",
            Verificacao.INCONCLUSIVO: "INCONCLUSIVO",
        }[self]


@dataclass(frozen=True)
class Via:
    """Uma via oficial que informa um valor."""

    fonte: str
    valor: float | None
    nivel: Nivel = Nivel.B
    original: Original | None = None


@dataclass
class Certificacao:
    selo: Selo | None
    valor: float | None = None
    vias: list[Via] = field(default_factory=list)
    divergencia: bool = False
    nota: str = ""


def _concordam(a: float, b: float, tolerancia: float) -> bool:
    maior = max(abs(a), abs(b))
    if maior == 0:
        return True
    return abs(a - b) / maior <= tolerancia


def selar(
    vias: Iterable[Via],
    *,
    exigido_por_lei: bool = False,
    leitura_falhou: bool = False,
    tolerancia: float = 0.01,
) -> Certificacao:
    """Certifica um dado a partir das vias oficiais que o informam.

    ``tolerancia`` é a diferença relativa aceita entre vias (padrão 1%).
    """
    lidas = [v for v in vias if v.valor is not None]
    if not lidas:
        if leitura_falhou:
            return Certificacao(Selo.VERMELHO, nota=Selo.VERMELHO.significado)
        if exigido_por_lei:
            return Certificacao(Selo.ROXO, nota=Selo.ROXO.significado)
        return Certificacao(None, nota="sem via e sem obrigação de publicar")

    fontes = {v.fonte for v in lidas}
    referencia = lidas[0].valor
    assert referencia is not None
    if len(fontes) < 2:
        return Certificacao(Selo.AZUL, referencia, lidas, nota=Selo.AZUL.significado)

    divergem = any(not _concordam(referencia, v.valor, tolerancia) for v in lidas[1:])  # type: ignore[arg-type]
    if divergem:
        return Certificacao(
            Selo.AZUL,
            referencia,
            lidas,
            divergencia=True,
            nota="as vias divergem; o selo cai para azul e a divergência vira indício",
        )
    return Certificacao(Selo.VERDE, referencia, lidas, nota=Selo.VERDE.significado)
