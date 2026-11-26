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

Uma medida que o sistema não conseguiu apurar fica ``None`` ("não medida"), com o motivo.
Ela não conta como zero contra o Município, porque a falha é da leitura, não do ente.
A nota apurada soma só o que foi medido; a nota máxima supõe o não medido perfeito.

O pedido de acesso sai quando a nota fica abaixo do mínimo do mapa legal (50). Com
alguma medida não apurada, só sai se nem a nota máxima chega ao mínimo: nenhum ofício
nasce de uma nota que dependa do que o próprio sistema não leu.
"""

from __future__ import annotations

from dataclasses import dataclass, field

PESOS = {
    "cobertura": 40,
    "coerencia": 25,
    "tempestividade": 15,
    "vinculo": 10,
    "prestacao": 10,
}


def _fracao(valor: float | None) -> float | None:
    if valor is None:
        return None
    return max(0.0, min(1.0, float(valor)))


@dataclass(frozen=True)
class IndiceIntegridade:
    cobertura: float | None
    coerencia: float | None
    tempestividade: float | None
    vinculo: float | None
    prestacao: float | None
    minimo: float = 50.0
    # medida -> por que não foi medida, ou como foi medida (texto curto, público)
    motivos: dict[str, str] = field(default_factory=dict, compare=False, hash=False)

    @property
    def nao_medidas(self) -> list[str]:
        return [nome for nome in PESOS if getattr(self, nome) is None]

    @property
    def completo(self) -> bool:
        return not self.nao_medidas

    @property
    def partes(self) -> dict[str, float | None]:
        out: dict[str, float | None] = {}
        for nome, peso in PESOS.items():
            f = _fracao(getattr(self, nome))
            out[nome] = None if f is None else round(f * peso, 2)
        return out

    @property
    def nota(self) -> float:
        """Nota apurada: soma só o que foi medido."""
        return round(sum(v for v in self.partes.values() if v is not None), 1)

    @property
    def pontos_medidos(self) -> int:
        return sum(PESOS[n] for n in PESOS if getattr(self, n) is not None)

    @property
    def nota_maxima(self) -> float:
        """A nota se tudo o que não foi medido estivesse perfeito."""
        return round(self.nota + sum(PESOS[n] for n in self.nao_medidas), 1)

    @property
    def gera_pedido_de_acesso(self) -> bool:
        return self.nota_maxima < self.minimo

    def frase(self) -> str:
        if self.completo:
            return f"Integridade da trilha: {self.nota:.0f} de 100."
        nomes = ", ".join(ROTULOS[n].lower() for n in self.nao_medidas)
        return (f"Integridade da trilha: {self.nota:.0f} de {self.pontos_medidos} pontos medidos "
                f"({nomes} sem medida nesta competência).")

    def como_dict(self) -> dict:
        return {
            "nota": self.nota,
            "completo": self.completo,
            "pontos_medidos": self.pontos_medidos,
            "nota_maxima": self.nota_maxima,
            "partes": self.partes,
            "fracoes": {nome: (None if _fracao(getattr(self, nome)) is None
                               else round(_fracao(getattr(self, nome)), 4)) for nome in PESOS},
            "nao_medidas": self.nao_medidas,
            "motivos": dict(self.motivos),
            "gera_pedido_de_acesso": self.gera_pedido_de_acesso,
        }


ROTULOS = {"cobertura": "Cobertura", "coerencia": "Coerência", "tempestividade": "Tempestividade",
           "vinculo": "Vínculo", "prestacao": "Prestação de contas"}
