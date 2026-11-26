"""Fontes de recurso: onde a água do rio se junta.

Código de destinação padronizado pela Secretaria do Tesouro Nacional. O primeiro
dígito diz o exercício (1 = corrente, 2 = exercícios anteriores); os três
seguintes dizem a destinação. Água vinculada só pode correr para o seu leito
(as funções orçamentárias permitidas); água livre vai para onde o gestor
quiser, desde que os pisos se cumpram.

Regra do rio: água vinculada num leito que não é o seu é desvio de finalidade.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Esfera(Enum):
    FEDERAL = "federal"
    ESTADUAL = "estadual"
    MUNICIPAL = "municipal"
    MISTA = "mista"

    @property
    def cor(self) -> str:
        return {
            Esfera.FEDERAL: "#15803D",    # verde
            Esfera.ESTADUAL: "#2563EB",   # azul
            Esfera.MUNICIPAL: "#E07B00",  # laranja
            Esfera.MISTA: "#64748B",
        }[self]


@dataclass(frozen=True)
class Destinacao:
    codigo: str               # três dígitos, sem o do exercício
    nome: str
    esfera: Esfera
    vinculada: bool
    leito: tuple[str, ...] = ()   # funções orçamentárias permitidas
    norma: str = ""
    conta_no_piso: bool = False   # água livre que forma a base dos pisos


# Funções orçamentárias (Portaria MOG 42/1999): 06 segurança pública, 08 assistência social,
# 09 previdência social, 10 saúde, 12 educação, 13 cultura, 15 urbanismo, 25 energia, 26 transporte.
_TABELA = [
    Destinacao("500", "Recursos não vinculados de impostos", Esfera.MUNICIPAL, False,
               norma="CF, arts. 156, 158 e 159", conta_no_piso=True),
    Destinacao("501", "Outros recursos não vinculados", Esfera.MUNICIPAL, False),
    Destinacao("540", "Transferências do Fundeb (impostos)", Esfera.MISTA, True, ("12",),
               "CF, art. 212-A; Lei 14.113/2020"),
    Destinacao("541", "Fundeb, complementação da União (VAAF)", Esfera.FEDERAL, True, ("12",),
               "Lei 14.113/2020"),
    Destinacao("542", "Fundeb, complementação da União (VAAT)", Esfera.FEDERAL, True, ("12",),
               "Lei 14.113/2020"),
    Destinacao("543", "Fundeb, complementação da União (VAAR)", Esfera.FEDERAL, True, ("12",),
               "Lei 14.113/2020"),
    Destinacao("550", "Salário-educação", Esfera.FEDERAL, True, ("12",), "CF, art. 212, § 5º"),
    Destinacao("551", "FNDE: Programa Dinheiro Direto na Escola", Esfera.FEDERAL, True, ("12",)),
    Destinacao("552", "FNDE: alimentação escolar", Esfera.FEDERAL, True, ("12",), "Lei 11.947/2009"),
    Destinacao("553", "FNDE: transporte escolar", Esfera.FEDERAL, True, ("12",)),
    Destinacao("569", "Outras transferências do FNDE", Esfera.FEDERAL, True, ("12",)),
    # O grupo 540 a 599 é todo da educação (Portaria STN 710/2021, anexo das fontes padronizadas).
    Destinacao("546", "Outro recurso vinculado à educação (grupo 540 a 599)", Esfera.MISTA, True, ("12",)),
    Destinacao("570", "Convênios da União vinculados à educação", Esfera.FEDERAL, True, ("12",)),
    Destinacao("571", "Convênios do Estado vinculados à educação", Esfera.ESTADUAL, True, ("12",)),
    Destinacao("574", "Outro recurso vinculado à educação (grupo 540 a 599)", Esfera.MISTA, True, ("12",)),
    Destinacao("600", "SUS federal, bloco de manutenção", Esfera.FEDERAL, True, ("10",),
               "LC 141/2012, art. 2º"),
    Destinacao("601", "SUS federal, bloco de estruturação", Esfera.FEDERAL, True, ("10",),
               "LC 141/2012, art. 2º"),
    Destinacao("604", "SUS federal, agentes comunitários de saúde e de combate às endemias", Esfera.FEDERAL,
               True, ("10",), "CF, art. 198, § 9º; Lei 11.350/2006"),
    Destinacao("605", "SUS federal, piso salarial da enfermagem", Esfera.FEDERAL, True, ("10",),
               "CF, art. 198, §§ 12 a 15; Lei 14.434/2022"),
    Destinacao("621", "SUS estadual", Esfera.ESTADUAL, True, ("10",), "LC 141/2012, art. 2º"),
    # O grupo 600 a 659 é todo da saúde.
    Destinacao("632", "Outro recurso vinculado à saúde (grupo 600 a 659)", Esfera.MISTA, True, ("10",)),
    Destinacao("634", "Outro recurso vinculado à saúde (grupo 600 a 659)", Esfera.MISTA, True, ("10",)),
    Destinacao("660", "Fundo Nacional de Assistência Social", Esfera.FEDERAL, True, ("08",),
               "Lei 8.742/1993, art. 30"),
    Destinacao("661", "Fundo Estadual de Assistência Social", Esfera.ESTADUAL, True, ("08",),
               "Lei 8.742/1993, art. 30"),
    Destinacao("665", "Programas estaduais de assistência social", Esfera.ESTADUAL, True, ("08",),
               "LOA 2026, receita 1.7.1.7.52.0.1"),
    Destinacao("700", "Convênios da União", Esfera.FEDERAL, True, norma="objeto pactuado"),
    Destinacao("701", "Convênios do Estado", Esfera.ESTADUAL, True, norma="objeto pactuado"),
    Destinacao("704", "Royalties do petróleo e gás natural", Esfera.FEDERAL, True,
               norma="Lei 7.990/1989, art. 8º; Lei 9.478/1997"),
    Destinacao("706", "Transferência especial da União (emendas)", Esfera.FEDERAL, True,
               norma="CF, art. 166-A"),
    Destinacao("708", "Compensação financeira pela exploração mineral (CFEM)", Esfera.FEDERAL, True,
               norma="Lei 8.001/1990, art. 2º; Lei 7.990/1989, art. 8º"),
    Destinacao("710", "Transferência especial do Estado", Esfera.ESTADUAL, True),
    Destinacao("715", "Lei Paulo Gustavo, audiovisual", Esfera.FEDERAL, True, ("13",), "LC 195/2022, art. 5º"),
    Destinacao("716", "Lei Paulo Gustavo, demais setores da cultura", Esfera.FEDERAL, True, ("13",),
               "LC 195/2022, art. 8º"),
    Destinacao("719", "Política Nacional Aldir Blanc (cultura)", Esfera.FEDERAL, True, ("13",),
               "Lei 14.399/2022"),
    Destinacao("749", "Outras vinculações de transferências", Esfera.MISTA, True),
    Destinacao("750", "CIDE-combustíveis", Esfera.FEDERAL, True, ("26",), "CF, art. 177, § 4º"),
    # Iluminação pública e, desde a EC 132/2023, monitoramento para segurança dos logradouros.
    Destinacao("751", "Contribuição de iluminação pública", Esfera.MUNICIPAL, True, ("25", "15", "06"),
               "CF, art. 149-A"),
    Destinacao("752", "Multas de trânsito", Esfera.MUNICIPAL, True, norma="CTB, art. 320"),
    Destinacao("754", "Operações de crédito", Esfera.MUNICIPAL, True, norma="objeto do financiamento"),
    Destinacao("755", "Alienação de bens", Esfera.MUNICIPAL, True, norma="LC 101/2000, art. 44"),
    Destinacao("800", "Previdência própria, fundo em capitalização", Esfera.MUNICIPAL, True, ("09",),
               "CF, art. 40; Lei 9.717/1998, art. 1º, III"),
    Destinacao("801", "Previdência própria, fundo em repartição", Esfera.MUNICIPAL, True, ("09",),
               "CF, art. 40; Lei 9.717/1998, art. 1º, III"),
]
DESTINACOES = {d.codigo: d for d in _TABELA}


@dataclass(frozen=True)
class Fonte:
    codigo: str
    destinacao: Destinacao | None
    exercicio: str  # "corrente", "anteriores" ou "desconhecido"

    @property
    def conhecida(self) -> bool:
        return self.destinacao is not None

    @property
    def vinculada(self) -> bool | None:
        return self.destinacao.vinculada if self.destinacao else None

    @property
    def nome(self) -> str:
        return self.destinacao.nome if self.destinacao else "fonte não catalogada"


def classificar(codigo: str | int) -> Fonte:
    """Classifica um código de fonte (ex.: ``1660``, ``2660``, ``660``)."""
    texto = "".join(c for c in str(codigo) if c.isdigit())
    if len(texto) >= 4:
        exercicio = {"1": "corrente", "2": "anteriores"}.get(texto[0], "desconhecido")
        nucleo = texto[1:4]
    else:
        exercicio, nucleo = "desconhecido", texto.zfill(3)
    return Fonte(codigo=texto, destinacao=DESTINACOES.get(nucleo), exercicio=exercicio)


def desvio_de_finalidade(codigo_fonte: str | int, funcao: str | int) -> bool | None:
    """True se água vinculada corre num leito que não é o seu.

    ``None`` quando não dá para dizer (fonte fora do catálogo ou vinculada a um
    objeto pactuado, que se confere pelo instrumento e não pela função).
    """
    fonte = classificar(codigo_fonte)
    if not fonte.conhecida:
        return None
    assert fonte.destinacao is not None
    if not fonte.vinculada:
        return False
    if not fonte.destinacao.leito:
        return None
    return str(funcao).zfill(2) not in fonte.destinacao.leito
