"""Contrato, entrega e prestação de contas (famílias PRC, ENT e PCT).

Para o mesmo empenho juntam-se quanto se pagou, o que se recebeu e o que se
prestou em contas: três pontas de um triângulo que precisa fechar.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Iterable

from ..legal.mapa import MapaLegal, carregar
from ..nucleo.indicios import Familia, Ficha, emitir
from ..nucleo.provas import Nivel


# --- Aditivo acima do limite (Lei 14.133/2021, art. 125) --------------------

def excesso_de_aditivos(valor_original: float, aditivos: Iterable[float], *,
                        mapa: MapaLegal | None = None) -> float | None:
    """Percentual de acréscimo acima do limite legal, ou ``None`` se cabe no limite."""
    limite = (mapa or carregar()).regra("ADITIVO-LIMITE").valor or 25.0
    if valor_original <= 0:
        return None
    acrescimo = sum(a for a in aditivos if a > 0) / valor_original * 100.0
    return round(acrescimo, 2) if acrescimo > limite else None


def ficha_de_aditivo(contrato: str, valor_original: float, acrescimo_pct: float) -> Ficha:
    return emitir(
        codigo=f"PRC-SOB04-{contrato}",
        familia=Familia.PRC,
        titulo=f"Aditivos do contrato {contrato} passam do limite legal",
        gravidade="alta",
        como_deveria="Os acréscimos não podem passar de 25% do valor inicial atualizado.",
        norma="Lei 14.133/2021, art. 125",
        como_esta=f"Valor original {valor_original:,.2f}; acréscimos somam {acrescimo_pct:.2f}%.",
        niveis=[Nivel.C, Nivel.B],
        providencia="Pedir os termos aditivos e as justificativas técnicas.",
    )


# --- Fracionamento (Lei 14.133/2021, art. 75, § 1º) --------------------------

@dataclass(frozen=True)
class Compra:
    objeto: str
    valor: float
    data: date
    obra_ou_engenharia: bool = False
    por_dispensa: bool = True


def fracionamentos(compras: Iterable[Compra], *, mapa: MapaLegal | None = None) -> list[dict]:
    """Soma, por objeto e exercício, as dispensas que juntas passam do limite."""
    regra = (mapa or carregar()).regra("DISPENSA-LIMITE")
    grupos: dict[tuple, list[Compra]] = defaultdict(list)
    for c in compras:
        if c.por_dispensa:
            grupos[(c.objeto.strip().lower(), c.data.year, c.obra_ou_engenharia)].append(c)
    achados = []
    for (objeto, ano, obra), itens in grupos.items():
        limite = float(regra.get("obras" if obra else "outros"))
        soma = sum(c.valor for c in itens)
        if len(itens) > 1 and soma > limite:
            achados.append({"objeto": objeto, "ano": ano, "soma": round(soma, 2),
                            "limite": limite, "compras": len(itens),
                            "limite_vigencia": regra.get("vigencia")})
    return achados


# --- Entrega: liquidado contra contratado, medições ----------------------------

def liquidado_acima_do_contratado(contratado: float, liquidacoes: Iterable[float]) -> float | None:
    excesso = sum(liquidacoes) - contratado
    return round(excesso, 2) if excesso > 0.005 else None


def medicoes_repetidas(medicoes: Iterable[float], vezes: int = 3) -> bool:
    """Medições idênticas mês a mês (``vezes`` seguidas) são sinal de medição não medida."""
    seq = list(medicoes)
    corrida = 1
    for a, b in zip(seq, seq[1:]):
        corrida = corrida + 1 if a == b and a > 0 else 1
        if corrida >= vezes:
            return True
    return False


def ficha_de_ordem(chave: str, problemas: list[str], competencia: str | None = None) -> Ficha:
    return emitir(
        codigo=f"ENT-ORDEM-{chave}",
        familia=Familia.ENT,
        titulo="Despesa fora da ordem legal",
        gravidade="alta",
        como_deveria="Empenho, liquidação e pagamento, nesta ordem; o pagamento só depois da "
                     "liquidação que comprova a entrega.",
        norma="Lei 4.320/1964, arts. 60, 62 e 63",
        como_esta="; ".join(problemas).capitalize() + ".",
        niveis=[Nivel.B, Nivel.A] if "antes" in " ".join(problemas) else [Nivel.B],
        documento_faltante="sem liquidação publicada" in " ".join(problemas),
        providencia="Pedir as notas de liquidação, as medições e os atestos do empenho.",
        competencia=competencia,
    )


# --- Prestação de contas das parcerias (Lei 13.019/2014) -----------------------

@dataclass(frozen=True)
class Parceria:
    instrumento: str
    entidade: str
    valor: float
    prestacao_publicada: bool = False
    prestacao_individualizada: bool = True
    saldo_nao_devolvido: float = 0.0
    prazo_vencido: bool = False


def fichas_de_prestacao(parcerias: Iterable[Parceria], competencia: str | None = None) -> list[Ficha]:
    fichas = []
    for p in parcerias:
        problemas = []
        if p.prazo_vencido and not p.prestacao_publicada:
            problemas.append("prestação de contas vencida e não publicada")
        if p.prestacao_publicada and not p.prestacao_individualizada:
            problemas.append("prestação coletiva ou genérica, sem individualizar a parceria")
        if p.saldo_nao_devolvido > 0:
            problemas.append(f"saldo de {p.saldo_nao_devolvido:,.2f} sem devolução")
        if not problemas:
            continue
        fichas.append(emitir(
            codigo=f"PCT-{p.instrumento}",
            familia=Familia.PCT,
            titulo=f"Prestação de contas de {p.entidade} com problema",
            gravidade="alta",
            como_deveria="Cada parceria presta contas no prazo, de forma individualizada, e devolve "
                         "o saldo.",
            norma="Lei 13.019/2014, arts. 52, 63 e 69",
            como_esta="; ".join(problemas).capitalize() + ".",
            niveis=[Nivel.C],
            documento_faltante=not p.prestacao_publicada,
            providencia="Pedir a prestação de contas e o parecer técnico da parceria.",
            competencia=competencia,
        ))
    return fichas
