"""Indícios: famílias e a ficha única.

Todo indício sai numa ficha no formato do parecer do Cadê o Queijo:

1. título e gravidade;
2. como deveria ser (a regra, com o dispositivo legal);
3. como está (o dado, com selo e nível de prova);
4. verificação (CONFIRMADO, INDICIÁRIO ou INCONCLUSIVO);
5. providência (o que pedir e a quem);
6. caso semelhante (um julgado da trilha do Mato, que inspira e não fundamenta);
7. custódia (endereço, data e impressão digital de cada original).

A ficha afirma apenas o que os níveis de prova permitem.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable

from .custodia import Original
from .estacoes import Estacao
from .provas import Nivel, pode_afirmar_irregularidade
from .selos import Gravidade, Selo, Verificacao


class Familia(Enum):
    RIO = "RIO"    # origem e fonte
    PISO = "PISO"  # fonte até liquidação: pisos e tetos
    ORC = "ORC"    # previsão e dotação
    VIN = "VIN"    # empenho e vínculo
    PRC = "PRC"    # preço, contrato
    ENT = "ENT"    # liquidação e pagamento
    PCT = "PCT"    # prestação de contas
    PES = "PES"    # dinheiro que deveria ter saído
    CTA = "CTA"    # contas não julgadas no prazo
    SIS = "SIS"    # falha do próprio sistema (nunca silêncio do município)

    @property
    def descricao(self) -> str:
        return _FAMILIAS[self][0]

    @property
    def estacoes(self) -> tuple[Estacao, ...]:
        return _FAMILIAS[self][1]

    @property
    def rotulo(self) -> str:
        """O nome curto da família para quem lê (o código continua o mesmo nas fichas)."""
        return _ROTULOS[self]


_FAMILIAS = {
    Familia.RIO: ("Origem e fonte: recurso vinculado fora da finalidade, receita sem fonte",
                  (Estacao.ORIGEM, Estacao.FONTE)),
    Familia.PISO: ("Pisos e tetos constitucionais e legais",
                   (Estacao.FONTE, Estacao.EMPENHO, Estacao.LIQUIDACAO)),
    Familia.ORC: ("Orçamento: suplementação, remanejamento, meta reduzida",
                  (Estacao.PREVISAO, Estacao.DOTACAO)),
    Familia.VIN: ("Vínculo: pagamento sem contrato, parceria sem chamamento",
                  (Estacao.EMPENHO, Estacao.VINCULO)),
    Familia.PRC: ("Preço e contrato: sobrepreço, fracionamento, aditivo",
                  (Estacao.VINCULO,)),
    Familia.ENT: ("Entrega: liquidado acima do contratado, pago antes de liquidar",
                  (Estacao.LIQUIDACAO, Estacao.PAGAMENTO)),
    Familia.PCT: ("Prestação de contas ausente, coletiva ou com saldo",
                  (Estacao.PRESTACAO,)),
    Familia.PES: ("Dinheiro que a lei manda pagar e não foi pago",
                  (Estacao.PAGAMENTO,)),
    Familia.CTA: ("Contas não julgadas no prazo da Lei Orgânica",
                  (Estacao.PRESTACAO,)),
    Familia.SIS: ("Falha do próprio sistema", ()),
}

_ROTULOS = {
    Familia.RIO: "Origem e fonte", Familia.PISO: "Pisos e tetos", Familia.ORC: "Orçamento",
    Familia.VIN: "Vínculo", Familia.PRC: "Preço e contrato", Familia.ENT: "Entrega",
    Familia.PCT: "Prestação de contas", Familia.PES: "Pessoal", Familia.CTA: "Contas",
    Familia.SIS: "Falha do sistema",
}

# Catálogo SOB do Cadê o Queijo, mantido com o mesmo código.
LEGADO_SOB = {
    "SOB-01": Familia.PRC,  # mesmo objeto com valores díspares
    "SOB-02": Familia.PRC,  # valor muito acima da mediana
    "SOB-03": Familia.PRC,  # fracionamento
    "SOB-04": Familia.PRC,  # aditivo acima de 25%
    "SOB-05": Familia.PCT,  # concentração em poucas entidades
    "SOB-06": Familia.VIN,  # repasse sem vínculo formal
    "SOB-07": Familia.VIN,  # repasse sem chamamento
}

# Prefixos dos demais códigos do Cadê o Queijo.
LEGADO_PREFIXOS = {
    "IGD": Familia.PISO, "EMD": Familia.PISO,
    "REC": Familia.RIO, "FMAS": Familia.RIO,
    "CMAS": Familia.ORC, "LEG": Familia.ORC,
    "DES": Familia.VIN, "EXE": Familia.ENT,
    "ATA": Familia.PCT, "PES": Familia.PES,
    "CTA": Familia.CTA, "SYS": Familia.SIS, "PUB": Familia.SIS,
}


def familia_do_legado(codigo: str) -> Familia:
    codigo = codigo.strip().upper()
    if codigo in LEGADO_SOB:
        return LEGADO_SOB[codigo]
    prefixo = codigo.split("-")[0]
    if prefixo in LEGADO_PREFIXOS:
        return LEGADO_PREFIXOS[prefixo]
    try:
        return Familia(prefixo)
    except ValueError:
        return Familia.ORC


@dataclass(frozen=True)
class Dado:
    """Um número de 'como está', sempre com selo e nível de prova."""

    rotulo: str
    valor: float | str | None
    selo: Selo | None = None
    nivel: Nivel | None = None


@dataclass
class Ficha:
    codigo: str
    familia: Familia
    titulo: str
    gravidade: Gravidade
    como_deveria: str
    norma: str
    como_esta: str
    verificacao: Verificacao
    providencia: str = ""
    caso_semelhante: str = ""
    dados: list[Dado] = field(default_factory=list)
    custodia: list[Original] = field(default_factory=list)
    competencia: str | None = None
    origem: str = "onisciente"
    observacao: str = ""

    @property
    def ordem(self) -> tuple:
        return (self.gravidade.ordem, self.familia.value, self.codigo)

    def como_dict(self) -> dict:
        return {
            "codigo": self.codigo,
            "familia": self.familia.value,
            "titulo": self.titulo,
            "gravidade": self.gravidade.value,
            "como_deveria": self.como_deveria,
            "norma": self.norma,
            "como_esta": self.como_esta,
            "verificacao": self.verificacao.value,
            "providencia": self.providencia,
            "caso_semelhante": self.caso_semelhante,
            "dados": [
                {"rotulo": d.rotulo, "valor": d.valor,
                 "selo": d.selo.value if d.selo else None,
                 "nivel": d.nivel.name if d.nivel else None}
                for d in self.dados
            ],
            "custodia": [o.como_dict() for o in self.custodia],
            "competencia": self.competencia,
            "origem": self.origem,
            "observacao": self.observacao,
        }


def emitir(
    *,
    codigo: str,
    familia: Familia,
    titulo: str,
    gravidade: Gravidade | str,
    como_deveria: str,
    norma: str,
    como_esta: str,
    niveis: Iterable[Nivel | str] = (),
    documento_faltante: bool = False,
    por_coincidencia_de_nome: bool = False,
    **resto,
) -> Ficha:
    """Emite uma ficha decidindo a verificação pelas travas, nunca por opinião.

    * documento faltante: INCONCLUSIVO, que também é achado;
    * duas fontes de níveis distintos: CONFIRMADO;
    * uma fonte: INDICIÁRIO;
    * coincidência de nomes nunca passa de INDICIÁRIO, porque homônimos existem.
    """
    niveis = [Nivel.de(n) for n in niveis]
    if documento_faltante or not [n for n in niveis if n is not Nivel.F]:
        verificacao = Verificacao.INCONCLUSIVO
    elif pode_afirmar_irregularidade(niveis) and not por_coincidencia_de_nome:
        verificacao = Verificacao.CONFIRMADO
    else:
        verificacao = Verificacao.INDICIARIO
    return Ficha(
        codigo=codigo,
        familia=familia,
        titulo=titulo,
        gravidade=Gravidade.de(gravidade),
        como_deveria=como_deveria,
        norma=norma,
        como_esta=como_esta,
        verificacao=verificacao,
        **resto,
    )


def ordenar(fichas: Iterable[Ficha]) -> list[Ficha]:
    return sorted(fichas, key=lambda f: f.ordem)
