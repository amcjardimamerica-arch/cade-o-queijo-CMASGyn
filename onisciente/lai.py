"""Ofícios da Lei de Acesso e a escada contra a não resposta.

Toda inconsistência que depende de um documento não publicado gera um ofício
pronto, com o fundamento, o que falta e dois pedidos: publicação em
transparência ativa, em formato aberto, e envio do mesmo conteúdo por e-mail
enquanto não for publicado. O protocolo e o envio ficam com quem assina; o
sistema nunca protocola nada sozinho.

Em Goiânia a Lei de Acesso é regulamentada pela Lei municipal 9.262/2013
(atendimento pela Controladoria Geral do Município). Não cabe recurso à CGU.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Iterable

from .nucleo.ausencias import Ausencia


@dataclass(frozen=True)
class Degrau:
    numero: int
    nome: str
    fundamento: str
    prazo_para_agir: int | None     # dias para recorrer ou propor
    prazo_para_decidir: int | None  # dias que o órgão tem para responder
    observacao: str = ""


ESCADA = (
    Degrau(1, "Pedido de acesso", "Lei 12.527/2011, art. 11; Lei 9.262/2013, arts. 15 e 16",
           None, 20, "prorrogável por mais 10 dias com justificativa; silêncio vale como negativa"),
    Degrau(2, "Recurso à Comissão Mista de Reavaliação de Informações",
           "Lei 9.262/2013, arts. 21, 24 e 27; Lei 12.527/2011, art. 15", 10, 10),
    Degrau(3, "Recurso ao Prefeito", "Lei 9.262/2013, art. 21, parágrafo único", 10, 10,
           "última instância no município; recusa ou demora sujeita o agente a suspensão (art. 40)"),
    Degrau(4, "Denúncia ao Tribunal de Contas dos Municípios",
           "Lei estadual 15.958/2007, arts. 26, § 3º, 33 e 34; CF, art. 74, § 2º", None, None,
           "o município fica sujeito a perder transferências voluntárias (LC 101/2000, arts. 73-A e 73-C)"),
    Degrau(5, "Representação ao Ministério Público",
           "Lei 8.429/1992, art. 11, IV e VI; Lei 7.347/1985; Lei 4.717/1965", None, None,
           "ação civil pública ou de improbidade exige dolo"),
    Degrau(6, "Mandado de segurança", "Lei 12.016/2009, art. 23", 120, None,
           "120 dias da negativa ou do fim do prazo"),
    Degrau(7, "Habeas data", "Lei 9.507/1997", None, None,
           "só quando a informação é sobre o próprio requerente; não serve para gasto público"),
)

AVISO_ILICITO = ("Recusar, retardar de propósito ou fornecer informação incompleta é conduta "
                 "ilícita do agente público (Lei 12.527/2011, art. 32; Lei 9.262/2013, art. 40).")


@dataclass
class Pedido:
    """Um pedido acompanhado pelo sistema. As datas vêm de quem protocolou."""

    assunto: str
    protocolado_em: date
    prorrogado: bool = False
    respondido_em: date | None = None
    resposta_satisfatoria: bool | None = None
    degrau: int = 1
    recurso_em: date | None = None


def vencimento(pedido: Pedido) -> date:
    """Data em que o órgão precisa responder no degrau atual."""
    if pedido.degrau == 1:
        dias = 20 + (10 if pedido.prorrogado else 0)
        return pedido.protocolado_em + timedelta(days=dias)
    degrau = ESCADA[pedido.degrau - 1]
    base = pedido.recurso_em or pedido.protocolado_em
    return base + timedelta(days=degrau.prazo_para_decidir or 0)


def proximo_passo(pedido: Pedido, hoje: date) -> dict:
    """Diz em que pé está o pedido e qual o próximo degrau, com o prazo."""
    venc = vencimento(pedido)
    if pedido.respondido_em and pedido.resposta_satisfatoria:
        return {"situacao": "atendido", "degrau": pedido.degrau}
    negado = (pedido.respondido_em is not None and pedido.resposta_satisfatoria is False) or hoje > venc
    if not negado:
        return {"situacao": "no prazo", "degrau": pedido.degrau, "vence_em": venc.isoformat(),
                "dias_restantes": (venc - hoje).days}
    proximo = ESCADA[min(pedido.degrau, len(ESCADA) - 1)]
    marco = pedido.respondido_em or venc
    passo = {"situacao": "negado ou sem resposta", "degrau_atual": pedido.degrau,
             "proximo": proximo.nome, "fundamento": proximo.fundamento,
             "desde": marco.isoformat()}
    if proximo.prazo_para_agir:
        passo["agir_ate"] = (marco + timedelta(days=proximo.prazo_para_agir)).isoformat()
    passo["mandado_de_seguranca_ate"] = (marco + timedelta(days=120)).isoformat()
    return passo


@dataclass
class Oficio:
    destinatario: str
    assunto: str
    itens: list[Ausencia] = field(default_factory=list)
    signatario: str = "[nome de quem assina]"

    def texto(self, local: str = "Goiânia", hoje: date | None = None) -> str:
        hoje = hoje or date.today()
        linhas = [
            f"{local}, {hoje:%d/%m/%Y}.",
            "",
            f"À {self.destinatario}",
            "",
            f"Assunto: {self.assunto}",
            "",
            "Com fundamento no art. 5º, XXXIII, da Constituição Federal, nos arts. 8º e 10 da "
            "Lei 12.527/2011, nos arts. 48 e 48-A da Lei Complementar 101/2000 e na Lei municipal "
            "9.262/2013, solicito:",
            "",
            "1. a publicação, em transparência ativa no portal oficial e em formato aberto, dos "
            "documentos listados abaixo;",
            "2. enquanto não publicados, o envio do mesmo conteúdo por meio eletrônico.",
            "",
            "Documentos e informações:",
        ]
        for i, a in enumerate(self.itens, 1):
            periodo = f" ({a.periodo})" if a.periodo else ""
            linhas.append(f"  {i}. {a.o_que_falta}{periodo}. Sem ele fica impedida a conferência: "
                          f"{a.conferencia_impedida}. Deveria estar em: {a.onde_deveria_estar}. "
                          f"Fundamento: {a.fundamento}.")
        linhas += [
            "",
            "O prazo de resposta é de 20 dias, prorrogável por mais 10 mediante justificativa "
            "(Lei 12.527/2011, art. 11). " + AVISO_ILICITO,
            "",
            "Atenciosamente,",
            "",
            self.signatario,
        ]
        return "\n".join(linhas)


def oficios_por_orgao(ausencias: Iterable[Ausencia], assunto: str) -> list[Oficio]:
    """Agrupa as ausências por órgão destinatário, um ofício para cada."""
    grupos: dict[str, list[Ausencia]] = {}
    for a in ausencias:
        grupos.setdefault(a.orgao or "Controladoria Geral do Município de Goiânia", []).append(a)
    return [Oficio(destinatario=o, assunto=assunto, itens=itens) for o, itens in sorted(grupos.items())]
