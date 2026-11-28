"""Requisito 162: o rio do Município fecha com a receita realizada do RREO dentro de 1%, em todo período
do banco, e o parecer marca em vermelho quando não fecha."""

from __future__ import annotations

import dataclasses

import pytest

from onisciente import RAIZ
from onisciente.fiscal import Leitor
from onisciente.nucleo import Selo
from onisciente.nucleo.selos import Via, selar
from onisciente.parecer import html
from onisciente.rio import municipio

BANCO = RAIZ / "dados" / "onisciente" / "historico.db"
pytestmark = pytest.mark.skipif(not BANCO.exists(), reason="banco histórico ausente")


def test_rio_e_rreo_dentro_de_um_por_cento_em_todo_periodo():
    lt = Leitor(BANCO)
    try:
        periodos = lt.periodos("RREO")
        assert len(periodos) >= 10
        for per in periodos:
            rm = municipio.montar(lt, per, ate=per.termina)
            assert rm.realizado_declarado, per
            c = selar([Via("rio", rm.liquido), Via("RREO", rm.realizado_declarado)],
                      tolerancia=html.TOLERANCIA_RIO_RREO)
            assert not c.divergencia, (per.rotulo, rm.liquido, rm.realizado_declarado)
    finally:
        lt.fechar()


def test_parecer_marca_em_vermelho_o_rio_que_nao_fecha():
    lt = Leitor(BANCO)
    try:
        rm = municipio.montar(lt, lt.periodos("RREO")[-1], ate=lt.periodos("RREO")[-1].termina)
    finally:
        lt.fechar()
    certo = "".join(html._rio_municipal(rm))
    assert "se separam em mais de 1%" not in certo
    assert f'class="selo s-{Selo.AZUL.value}"' in certo
    errado = dataclasses.replace(rm, realizado_declarado=rm.liquido * 1.02)
    pagina = "".join(html._rio_municipal(errado))
    assert "se separam em mais de 1%" in pagina
    assert f'<span class="selo s-{Selo.VERMELHO.value}"' in pagina
