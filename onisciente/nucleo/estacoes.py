"""As nove estações da trilha.

Cada real é seguido por nove estações. Uma estação só se acende com documento
oficial, e o nível de prova do documento diz o que se pode afirmar nela.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum

from .custodia import Original
from .provas import Nivel


class Estacao(Enum):
    ORIGEM = 1
    FONTE = 2
    PREVISAO = 3
    DOTACAO = 4
    EMPENHO = 5
    VINCULO = 6
    LIQUIDACAO = 7
    PAGAMENTO = 8
    PRESTACAO = 9

    @property
    def numero(self) -> int:
        return self.value

    @property
    def nome(self) -> str:
        return _INFO[self][0]

    @property
    def prova(self) -> str:
        return _INFO[self][1]

    @property
    def onde_nasce(self) -> str:
        return _INFO[self][2]

    @property
    def nivel_minimo(self) -> Nivel:
        return _INFO[self][3]

    def acende_com(self, nivel: Nivel | str) -> bool:
        """A estação só se acende com documento no nível mínimo dela."""
        return Nivel.de(nivel) >= self.nivel_minimo

    @classmethod
    def de(cls, valor: "Estacao | str | int") -> "Estacao":
        if isinstance(valor, Estacao):
            return valor
        if isinstance(valor, int):
            return cls(valor)
        t = str(valor).strip().upper()
        return cls[_SINONIMOS.get(t, t)]


_INFO = {
    Estacao.ORIGEM: ("Origem", "quanto entrou, de qual tributo ou repasse",
                     "execução da receita, Tesouro Nacional, FNS, FNDE, Estado", Nivel.B),
    Estacao.FONTE: ("Fonte", "se o recurso é livre ou vinculado",
                    "código de destinação no QDD e no SICONFI", Nivel.B),
    Estacao.PREVISAO: ("Previsão", "que o gasto foi autorizado na LOA", "LOA, QDD", Nivel.D),
    Estacao.DOTACAO: ("Dotação", "para onde a autorização foi movida",
                      "créditos adicionais e decretos no Diário Oficial", Nivel.D),
    Estacao.EMPENHO: ("Empenho", "que o dinheiro foi reservado a um credor",
                      "nota de empenho no portal e no Diário", Nivel.B),
    Estacao.VINCULO: ("Vínculo", "por que aquele credor tem direito",
                      "contrato, ata, termo de fomento, convênio, folha (PNCP, Diário)", Nivel.C),
    Estacao.LIQUIDACAO: ("Liquidação", "que o serviço ou bem foi entregue (Lei 4.320/1964, art. 63)",
                         "nota fiscal, medição, atesto publicados", Nivel.B),
    Estacao.PAGAMENTO: ("Pagamento", "que o dinheiro saiu da conta",
                        "ordem bancária, extrato, execução paga", Nivel.B),
    Estacao.PRESTACAO: ("Prestação de contas", "o que o dinheiro virou e se sobrou saldo",
                        "prestação da parceria ou do convênio, relatório de execução, RREO", Nivel.C),
}

# Nomes das estações do Cadê o Queijo, para ler os dados antigos.
_SINONIMOS = {
    "REPASSE": "ORIGEM",
    "ORCAMENTO": "PREVISAO",
    "CREDITO": "DOTACAO",
    "DELIBERACAO": "DOTACAO",
    "ENTIDADE": "VINCULO",
    "PRESTACAO_DE_CONTAS": "PRESTACAO",
}


@dataclass(frozen=True)
class Evento:
    """Um documento oficial que acende (ou tenta acender) uma estação."""

    estacao: Estacao
    nivel: Nivel
    valor: float | None = None
    data: date | None = None
    credor: str | None = None
    fonte_recurso: str | None = None
    funcao: str | None = None
    original: Original | None = None

    @property
    def acende(self) -> bool:
        return self.estacao.acende_com(self.nivel)


@dataclass
class Percurso:
    """O caminho de um empenho (ou de um repasse) pelas nove estações."""

    chave: str
    eventos: list[Evento] = field(default_factory=list)

    def acesas(self) -> set[Estacao]:
        return {e.estacao for e in self.eventos if e.acende}

    def faltantes(self) -> list[Estacao]:
        return [s for s in Estacao if s not in self.acesas()]

    @property
    def completo(self) -> bool:
        return not self.faltantes()

    def valor_pago(self) -> float:
        pagos = [e.valor or 0.0 for e in self.eventos
                 if e.estacao is Estacao.PAGAMENTO and e.acende]
        return sum(pagos)

    def _data(self, estacao: Estacao) -> date | None:
        datas = [e.data for e in self.eventos if e.estacao is estacao and e.data and e.acende]
        return min(datas) if datas else None

    def ordem_violada(self) -> list[str]:
        """Pagamento antes da liquidação, liquidação antes do empenho (Lei 4.320/1964)."""
        problemas = []
        emp, liq, pag = (self._data(Estacao.EMPENHO), self._data(Estacao.LIQUIDACAO),
                         self._data(Estacao.PAGAMENTO))
        if pag and liq and pag < liq:
            problemas.append("pagamento antes da liquidação (Lei 4.320/1964, art. 62)")
        if pag and not liq:
            problemas.append("pagamento sem liquidação publicada (Lei 4.320/1964, art. 62)")
        if liq and emp and liq < emp:
            problemas.append("liquidação antes do empenho (Lei 4.320/1964, art. 60)")
        return problemas


def integridade_da_trilha(percursos: list[Percurso]) -> float:
    """Fração do dinheiro pago que atravessa as nove estações com documento."""
    total = sum(p.valor_pago() for p in percursos)
    if total == 0:
        return 0.0
    completo = sum(p.valor_pago() for p in percursos if p.completo)
    return completo / total
