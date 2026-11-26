"""Contas fiscalizadas e os prazos da Lei Orgânica (família CTA).

Para cada exercício: entrega ao Tribunal, parecer prévio, julgamento pela Câmara
e prazo final, e se a conferência dos dados daquele ano é possível.

Prazos (Lei Orgânica de Goiânia, arts. 64, XI, 103, 103-A, 103-B e 115, XXV):

* balancetes mensais ao Tribunal em 45 dias;
* contas anuais até 60 dias depois da abertura da sessão legislativa;
* parecer prévio do Tribunal em 60 dias;
* julgamento pela Câmara em 75 dias depois do parecer;
* tudo apreciado até o fim do exercício seguinte ao da entrega.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from .nucleo.indicios import Familia, Ficha, emitir
from .nucleo.provas import Nivel

NORMA_CONTAS = "Lei Orgânica de Goiânia, arts. 64, XI, 103, 103-A, 103-B e 115, XXV"


def prazo_balancete(competencia: str) -> date:
    """Último dia para o balancete do mês chegar ao Tribunal (45 dias após o mês)."""
    ano, mes = (int(x) for x in competencia.split("-"))
    fim = date(ano + (mes == 12), 1 if mes == 12 else mes + 1, 1) - timedelta(days=1)
    return fim + timedelta(days=45)


@dataclass
class Conta:
    exercicio: int
    orgao: str
    tipo: str = "governo"            # governo (prefeito) ou gestão (fundo, autarquia, estatal)
    entregue_em: date | None = None
    parecer_em: date | None = None
    julgada_em: date | None = None
    conferencia: str = "impossível"  # possível, parcial ou impossível
    atrasos: list[str] = field(default_factory=list)


def avaliar(conta: Conta, hoje: date, *, abertura_sessao: tuple[int, int] = (2, 1)) -> Conta:
    """Preenche os atrasos da conta, contando só o que já venceu em ``hoje``."""
    conta.atrasos = []
    abertura = date(conta.exercicio + 1, *abertura_sessao)
    prazo_entrega = abertura + timedelta(days=60)
    if conta.entregue_em is None:
        if hoje > prazo_entrega:
            conta.atrasos.append(f"contas não entregues; o prazo venceu em {prazo_entrega:%d/%m/%Y}")
        return conta
    if conta.entregue_em > prazo_entrega:
        conta.atrasos.append(f"entregues em {conta.entregue_em:%d/%m/%Y}, depois do prazo de "
                             f"{prazo_entrega:%d/%m/%Y}")
    prazo_parecer = conta.entregue_em + timedelta(days=60)
    if conta.parecer_em is None and hoje > prazo_parecer:
        conta.atrasos.append(f"parecer prévio não emitido; o prazo venceu em {prazo_parecer:%d/%m/%Y}")
    if conta.parecer_em is not None:
        prazo_julgamento = conta.parecer_em + timedelta(days=75)
        if conta.julgada_em is None and hoje > prazo_julgamento:
            conta.atrasos.append(f"contas não julgadas pela Câmara; o prazo venceu em "
                                 f"{prazo_julgamento:%d/%m/%Y}")
    limite_final = date(conta.entregue_em.year + 1, 12, 31)
    if conta.julgada_em is None and hoje > limite_final:
        conta.atrasos.append(f"contas não apreciadas até o fim do exercício seguinte "
                             f"({limite_final:%d/%m/%Y})")
    return conta


def fichas(contas: list[Conta]) -> list[Ficha]:
    saida = []
    for c in contas:
        if not c.atrasos:
            continue
        saida.append(emitir(
            codigo=f"CTA-{c.orgao.upper().replace(' ', '-')}-{c.exercicio}",
            familia=Familia.CTA,
            titulo=f"Contas de {c.exercicio} ({c.orgao}) fora dos prazos da Lei Orgânica",
            gravidade="alta",
            como_deveria="Entrega em 60 dias da abertura da sessão legislativa, parecer prévio em "
                         "60 dias e julgamento pela Câmara em 75 dias.",
            norma=NORMA_CONTAS,
            como_esta="; ".join(c.atrasos).capitalize() + ".",
            niveis=[Nivel.D],
            documento_faltante=c.entregue_em is None,
            providencia="Pedir à Câmara e ao Tribunal de Contas dos Municípios a situação das "
                        "contas e o calendário de julgamento.",
        ))
    return saida
