"""O dinheiro que deveria ter saído (família PES).

A trilha também corre ao contrário: o sistema procura o pagamento que a lei
manda fazer e não foi feito. O valor devido pertence a servidores e aposentados
e aparece separado do resto. Só dado público e agregado: cargo e valor, nunca
CPF nem matrícula.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..legal.mapa import MapaLegal, carregar
from ..nucleo.indicios import Familia, Ficha, emitir
from ..nucleo.provas import Nivel


@dataclass(frozen=True)
class RevisaoGeral:
    ano: int
    indice_concedido: float      # % aplicado pela lei de revisão
    inflacao_do_periodo: float   # IPCA acumulado do período de referência (%)
    lei: str
    categorias_excluidas: tuple[str, ...] = ()


def conferir_revisao_geral(r: RevisaoGeral) -> Ficha | None:
    """Revisão abaixo da inflação, ou que deixa categorias de fora (CF, art. 37, X)."""
    problemas = []
    if r.indice_concedido + 1e-9 < r.inflacao_do_periodo:
        problemas.append(f"índice de {r.indice_concedido:.2f}% contra inflação de "
                         f"{r.inflacao_do_periodo:.2f}% no período")
    if r.categorias_excluidas:
        problemas.append("ficaram de fora: " + ", ".join(r.categorias_excluidas))
    if not problemas:
        return None
    return emitir(
        codigo=f"PES-REVISAO-{r.ano}",
        familia=Familia.PES,
        titulo=f"Revisão geral de {r.ano} com perda ou distinção entre categorias",
        gravidade="alta",
        como_deveria="Revisão geral anual, sempre na mesma data e sem distinção de índices.",
        norma="CF, art. 37, X",
        como_esta=f"{r.lei}: " + "; ".join(problemas) + ".",
        niveis=[Nivel.C, Nivel.D],
        providencia="Pedir o estudo de impacto e a justificativa da exclusão ou da perda.",
    )


def atraso_de_folha(competencia: str, pago_em: date, *, mapa: MapaLegal | None = None) -> int:
    """Dias de atraso da folha em relação ao dia limite do mês seguinte (Lei Orgânica, art. 30)."""
    dia = int((mapa or carregar()).regra("FOLHA-DIA-5").valor or 5)
    ano, mes = (int(x) for x in competencia.split("-"))
    ano_seg, mes_seg = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
    limite = date(ano_seg, mes_seg, dia)
    return max(0, (pago_em - limite).days)


def atraso_previdencia(competencia: str, repassado_em: date, *, mapa: MapaLegal | None = None) -> int:
    """Dias de atraso do repasse ao regime próprio em relação ao dia 20 do mês seguinte."""
    dia = int((mapa or carregar()).regra("PREVIDENCIA-DIA-20").valor or 20)
    ano, mes = (int(x) for x in competencia.split("-"))
    ano_seg, mes_seg = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
    return max(0, (repassado_em - date(ano_seg, mes_seg, dia)).days)
