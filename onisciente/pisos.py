"""Pisos e tetos: a validação constitucional.

O Onisciente recalcula cada percentual a partir da própria trilha, sem aceitar o
número declarado pelo município, e depois compara com o declarado no RREO, no
RGF, no SIOPS e no SIOPE. Se os dois baterem, o selo é verde. Se divergirem além
da tolerância do mapa legal (1%), a divergência é um indício por si só.

Três cuidados de cálculo são regras do motor, não escolhas de quem lê:

* só conta como gasto de piso o que foi liquidado com a fonte correta;
* restos a pagar entram apenas até o limite de caixa;
* água vinculada (SUS, FNDE) nunca entra na conta do piso.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .legal.mapa import MapaLegal, Regra, carregar
from .nucleo.indicios import Familia, Ficha, emitir
from .nucleo.provas import Nivel
from .nucleo.selos import Selo
from .rio.fontes import classificar


@dataclass(frozen=True)
class Lancamento:
    """Uma despesa candidata a entrar no piso."""

    valor_liquidado: float
    fonte: str
    funcao: str
    restos_a_pagar: float = 0.0


def gasto_de_piso(
    lancamentos: Iterable[Lancamento],
    funcao: str,
    *,
    caixa_para_restos: float = 0.0,
) -> float:
    """Soma o que pode contar no piso da função, pelas três regras do motor."""
    liquidado, restos = 0.0, 0.0
    for l in lancamentos:
        if str(l.funcao).zfill(2) != str(funcao).zfill(2):
            continue
        fonte = classificar(l.fonte)
        if not fonte.conhecida or fonte.vinculada:
            continue  # vinculada nunca conta; fonte desconhecida não se presume livre
        liquidado += max(0.0, l.valor_liquidado)
        restos += max(0.0, l.restos_a_pagar)
    return liquidado + min(restos, max(0.0, caixa_para_restos))


@dataclass(frozen=True)
class Medida:
    regra: Regra
    numerador: float
    denominador: float
    percentual: float | None
    limite: float
    situacao: str                     # cumpre, alerta, prudencial, descumpre, sem_dado
    declarado: float | None = None
    divergencia: bool = False
    selo: Selo | None = None

    @property
    def cumpre(self) -> bool:
        return self.situacao in {"cumpre", "alerta", "prudencial"}


def _limite(regra: Regra, faixa: str | None) -> float:
    if regra.valor is not None:
        return regra.valor
    faixas = regra.get("faixas")
    if faixas and faixa:
        return float(faixas[faixa])
    raise ValueError(f"regra {regra.id} precisa da faixa populacional do alvo")


def medir(
    regra_id: str,
    numerador: float | None,
    denominador: float | None,
    *,
    declarado: float | None = None,
    faixa: str | None = None,
    mapa: MapaLegal | None = None,
) -> Medida:
    """Mede um piso ou teto e compara o cálculo próprio com o declarado."""
    mapa = mapa or carregar()
    regra = mapa.regra(regra_id)
    limite = _limite(regra, faixa)
    if numerador is None or not denominador:
        selo = Selo.ROXO
        return Medida(regra, numerador or 0.0, denominador or 0.0, None, limite, "sem_dado",
                      declarado, False, selo)

    pct = 100.0 * numerador / denominador
    if regra.tipo == "minimo":
        situacao = "cumpre" if pct >= limite else "descumpre"
    elif regra.tipo == "maximo":
        if pct > limite:
            situacao = "descumpre"
        elif regra.get("prudencial") is not None and pct > float(regra.get("prudencial")):
            situacao = "prudencial"
        elif regra.get("alerta") is not None and pct > float(regra.get("alerta")):
            situacao = "alerta"
        else:
            situacao = "cumpre"
    else:
        raise ValueError(f"regra {regra.id} não é piso nem teto")

    tolerancia = mapa.regra("DIVERGENCIA-DECLARADO").valor or 1.0
    divergencia = False
    selo = Selo.AZUL
    if declarado is not None:
        base = max(abs(declarado), abs(pct)) or 1.0
        divergencia = abs(pct - declarado) / base * 100.0 > tolerancia
        selo = Selo.AZUL if divergencia else Selo.VERDE
    return Medida(regra, numerador, denominador, round(pct, 4), limite, situacao, declarado,
                  divergencia, selo)


def fichas_da_medida(m: Medida, *, competencia: str, ente: str = "o Município") -> list[Ficha]:
    """Transforma uma medida em fichas: descumprimento e divergência são indícios."""
    fichas: list[Ficha] = []
    r = m.regra
    if m.situacao == "sem_dado":
        return fichas  # vira ausência no parecer, não ficha
    comparador = "pelo menos" if r.tipo == "minimo" else "no máximo"
    deveria = f"{r.titulo}: {comparador} {m.limite:g}{r.unidade} da {r.base}."
    esta = f"Cálculo próprio a partir da trilha: {m.percentual:.2f}{r.unidade}."
    if m.declarado is not None:
        esta += f" Declarado por {ente}: {m.declarado:.2f}{r.unidade}."
    niveis = [Nivel.B] + ([Nivel.D] if m.declarado is not None else [])
    if m.situacao in {"descumpre", "alerta", "prudencial"}:
        gravidade = r.gravidade if m.situacao == "descumpre" else "alta" if m.situacao == "prudencial" else "media"
        fichas.append(emitir(
            codigo=f"PISO-{r.id}-{competencia}",
            familia=Familia.PISO,
            titulo=f"{r.titulo}: {'limite descumprido' if m.situacao == 'descumpre' else 'limite de ' + m.situacao + ' atingido'}",
            gravidade=gravidade,
            como_deveria=deveria,
            norma=r.norma,
            como_esta=esta,
            niveis=niveis,
            providencia=f"Pedir a memória de cálculo e a documentação de origem a {ente} e "
                        "comunicar o Tribunal de Contas dos Municípios.",
            competencia=competencia,
        ))
    if m.divergencia:
        fichas.append(emitir(
            codigo=f"PISO-DIV-{r.id}-{competencia}",
            familia=Familia.PISO,
            titulo=f"{r.titulo}: o declarado diverge do cálculo próprio",
            gravidade="alta",
            como_deveria="O percentual declarado deve bater com o calculado a partir da execução "
                         "publicada, dentro da tolerância do mapa legal.",
            norma="LC 101/2000, arts. 48 e 52",
            como_esta=esta,
            niveis=niveis,
            providencia="Pedir a conciliação entre o demonstrativo declarado e a execução.",
            competencia=competencia,
        ))
    return fichas
