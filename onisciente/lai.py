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

import json
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

from . import RAIZ
from .nucleo.ausencias import Ausencia

CGM = "Controladoria Geral do Município de Goiânia"


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
AVISO_ILICITO_GERAL = ("Recusar, retardar de propósito ou fornecer informação incompleta é conduta "
                       "ilícita do agente público (Lei 12.527/2011, art. 32).")


# --- Órgão competente por documento -------------------------------------------------------
#
# Quem guarda o documento é quem responde por ele; o pedido corre pelo Serviço de Informação ao
# Cidadão (Controladoria), que recebe cópia. Um órgão explícito na ausência sempre vale; o
# destinatário padrão (a Controladoria, ou nenhum) é trocado pelo órgão do documento quando as
# palavras da ausência o indicam.

ORGAO_POR_DOCUMENTO: tuple[tuple[tuple[str, ...], str], ...] = (
    (("TEXTO OFICIAL", "SILEG", "DIARIO OFICIAL", "DECRETO", "NORMA"), "Casa Civil do Município de Goiânia"),
    (("PREVIDENC", "RPPS", "APOSENTADORIA", "PENS"), "Instituto de Previdência dos Servidores do Município de "
                                                    "Goiânia (GOIANIAPREV)"),
    (("MAGISTERIO", "FUNDEB", "EDUCACAO", "ESCOLA", "CRECHE"), "Secretaria Municipal de Educação de Goiânia"),
    (("SAUDE", "SUS", "SIOPS"), "Secretaria Municipal de Saúde de Goiânia (gestora do Fundo Municipal de Saúde)"),
    (("ASSISTENCIA", "CMAS", "CONSELHO MUNICIPAL DE ASSISTENCIA", "IGD", "FMAS", "SUAS", "PARCERIA"),
     "Secretaria Municipal de Desenvolvimento Humano e Social de Goiânia (gestora do Fundo Municipal de "
     "Assistência Social)"),
    (("FOLHA", "SERVIDOR", "REMUNERA", "DIARIA", "PASSAGE", "PESSOAL", "CARGO", "JETON"),
     "Secretaria Municipal de Administração de Goiânia"),
    (("EMPENHO", "LIQUIDA", "PAGAMENTO", "RECEITA", "ORCAMENT", "QDD", "EXECUCAO DA DESPESA", "RESTOS A PAGAR",
      "BALANC", "CONTABIL", "DESPESA"), "Secretaria Municipal de Finanças de Goiânia (SEFIN)"),
)

FEDERAIS = ("UNIAO", "MINISTERIO", "FUNDO NACIONAL", "TRIBUNAL DE CONTAS DA UNIAO", "CONTROLADORIA-GERAL DA UNIAO",
            "SECRETARIA DO TESOURO NACIONAL", "CAIXA ECONOMICA FEDERAL", "RECEITA FEDERAL")
ESTADUAIS = ("ESTADO DE GOIAS", "SECRETARIA DE ESTADO", "GOVERNO DO ESTADO", "TRIBUNAL DE CONTAS DOS MUNICIPIOS",
             "TRIBUNAL DE CONTAS DO ESTADO", "ASSEMBLEIA LEGISLATIVA")


def _sem_acento(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t or "") if unicodedata.category(c) != "Mn").upper()


def esfera(destinatario: str) -> str:
    """'federal', 'estadual' ou 'municipal': a lei de acesso citada depende de quem recebe."""
    d = _sem_acento(destinatario)
    if any(k in d for k in FEDERAIS):
        return "federal"
    if any(k in d for k in ESTADUAIS):
        return "estadual"
    return "municipal"


def lei_estadual_de_acesso() -> str:
    """A lei estadual de acesso, se o mapa legal a registra; senão, vazio (cita-se só a federal)."""
    try:
        from .legal.mapa import carregar
        for n in carregar().normas.values():
            if "acesso à informação" in n.assunto.lower() and n.norma.lower().startswith("lei estadual"):
                return n.norma
    except Exception:  # noqa: BLE001 - sem mapa, o ofício cita só a lei federal
        return ""
    return ""


def orgao_competente(a: Ausencia) -> str:
    if a.orgao and a.orgao != CGM:
        return a.orgao
    texto = _sem_acento(f"{a.o_que_falta} {getattr(a, 'bloco', '') or ''} {a.onde_deveria_estar}")
    for chaves, orgao in ORGAO_POR_DOCUMENTO:
        if any(k in texto for k in chaves):
            return orgao
    return CGM


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
        ]
        if esfera(self.destinatario) == "municipal" and self.destinatario != CGM:
            linhas += [f"Com cópia à {CGM}, que atende os pedidos de acesso pelo Serviço de Informação ao "
                       "Cidadão (Lei municipal 9.262/2013).", ""]
        else:
            linhas.append("")
        linhas += [
            f"Assunto: {self.assunto}",
            "",
            "Com fundamento no art. 5º, XXXIII, da Constituição Federal, nos arts. 8º e 10 da "
            "Lei 12.527/2011, nos arts. 48 e 48-A da Lei Complementar 101/2000"
            + {"municipal": " e na Lei municipal 9.262/2013",
               "estadual": f" e na {lei_estadual_de_acesso()}" if lei_estadual_de_acesso() else "",
               "federal": ""}[esfera(self.destinatario)] + ", solicito:",
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
            "(Lei 12.527/2011, art. 11). " + (AVISO_ILICITO if esfera(self.destinatario) == "municipal"
                                               else AVISO_ILICITO_GERAL),
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
        grupos.setdefault(orgao_competente(a), []).append(a)
    return [Oficio(destinatario=o, assunto=assunto, itens=itens) for o, itens in sorted(grupos.items())]


# --- Recurso pré-redigido -----------------------------------------------------------------

def texto_recurso(pedido: Pedido, degrau: int, hoje: date | None = None, *, destinatario: str = "",
                  signatario: str = "[nome de quem assina]") -> str:
    """O texto pronto do degrau 2 a 5 da escada, a partir do pedido negado ou sem resposta.

    O texto narra só o que o registro diz (datas e assunto) e cita o fundamento do degrau; quem
    assina confere, completa e protocola. O sistema nunca protocola nada sozinho.
    """
    if not 2 <= degrau <= 5:
        raise ValueError("há texto pronto para os degraus 2 a 5; os demais pedem advogado")
    hoje = hoje or date.today()
    d = ESCADA[degrau - 1]
    venc = vencimento(Pedido(pedido.assunto, pedido.protocolado_em, pedido.prorrogado))
    if pedido.respondido_em and pedido.resposta_satisfatoria is False:
        fato = (f"O pedido foi respondido em {pedido.respondido_em:%d/%m/%Y} sem entregar o que foi pedido, o que "
                "equivale a negativa de acesso.")
    else:
        fato = (f"O prazo de resposta venceu em {venc:%d/%m/%Y} sem resposta, e o silêncio vale como negativa de "
                "acesso.")
    para = destinatario or {2: "Comissão Mista de Reavaliação de Informações do Município de Goiânia",
                            3: "Prefeito de Goiânia",
                            4: "Tribunal de Contas dos Municípios do Estado de Goiás",
                            5: "Promotoria de Justiça do Patrimônio Público de Goiânia"}[degrau]
    pede = {2: "a reforma da decisão e a entrega integral da informação no prazo legal",
            3: "a reforma da decisão e a entrega integral da informação, em última instância no Município",
            4: ("a apuração do descumprimento do dever de transparência e a determinação de publicação, com as "
                "sanções cabíveis"),
            5: ("a instauração de procedimento para apurar o descumprimento do dever de transparência e a "
                "responsabilidade de quem recusou ou retardou a informação")}[degrau]
    linhas = [
        f"Goiânia, {hoje:%d/%m/%Y}.", "", f"À {para}", "",
        f"Assunto: {d.nome} sobre o pedido de acesso \"{pedido.assunto}\"", "",
        f"Em {pedido.protocolado_em:%d/%m/%Y} foi protocolado pedido de acesso à informação sobre "
        f"\"{pedido.assunto}\". {fato}", "",
        f"Com fundamento em {d.fundamento}, peço {pede}.", "",
        AVISO_ILICITO + (f" Observação: {d.observacao}." if d.observacao else ""), "",
        "Seguem em anexo o pedido original e o comprovante de protocolo.", "",
        "Atenciosamente,", "", signatario,
    ]
    return "\n".join(linhas)


# --- Registro dos protocolos e acompanhamento dos prazos -----------------------------------

REGISTRO = RAIZ / "estado" / "protocolos_lai.json"


def carregar_registro(caminho: Path | None = None) -> list[Pedido]:
    """Os pedidos protocolados, com as datas que quem protocolou registrou. Sem arquivo, nenhum."""
    try:
        dados = json.loads((caminho or REGISTRO).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return []
    saida = []
    for p in dados.get("protocolos", []):
        d = lambda k: date.fromisoformat(p[k]) if p.get(k) else None  # noqa: E731
        saida.append(Pedido(assunto=p["assunto"], protocolado_em=d("protocolado_em"),
                            prorrogado=bool(p.get("prorrogado")), respondido_em=d("respondido_em"),
                            resposta_satisfatoria=p.get("resposta_satisfatoria"), degrau=int(p.get("degrau", 1)),
                            recurso_em=d("recurso_em")))
    return saida


def salvar_registro(pedidos: Iterable[Pedido], caminho: Path | None = None) -> None:
    def _iso(v):
        return v.isoformat() if isinstance(v, date) else v
    itens = [{k: _iso(v) for k, v in asdict(p).items()} for p in pedidos]
    (caminho or REGISTRO).parent.mkdir(parents=True, exist_ok=True)
    (caminho or REGISTRO).write_text(json.dumps({"protocolos": itens}, ensure_ascii=False, indent=1) + "\n",
                                     encoding="utf-8")


def acompanhar(pedidos: Iterable[Pedido], hoje: date) -> list[dict]:
    """Cada protocolo com a situação e o próximo passo; os vencidos trazem o recurso pronto."""
    saida = []
    for p in pedidos:
        passo = proximo_passo(p, hoje)
        linha = {"assunto": p.assunto, "protocolado_em": p.protocolado_em.isoformat(), **passo}
        if passo["situacao"] == "negado ou sem resposta" and p.degrau + 1 <= 5:
            linha["recurso"] = texto_recurso(p, p.degrau + 1, hoje)
        saida.append(linha)
    return saida
