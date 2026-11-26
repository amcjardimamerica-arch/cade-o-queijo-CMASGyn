"""Bloco 1: nota de integridade honesta e o Município medido pelo RGF e pelo RREO do banco.

Os testes rodam sobre o banco histórico real (``dados/onisciente/historico.db``), sem rede.
As divergências são provocadas numa cópia do banco, nunca no original.
"""

import shutil
import sqlite3
from datetime import date

import pytest

from onisciente import RAIZ, fiscal
from onisciente.adaptadores import cadeoqueijo
from onisciente.nucleo import IndiceIntegridade, Selo
from onisciente.nucleo.indicios import Familia
from onisciente.parecer import html

BANCO = RAIZ / "dados" / "onisciente" / "historico.db"
pytestmark = pytest.mark.skipif(not BANCO.exists(), reason="banco histórico ausente")


# --- Integridade: o não medido não vira zero -------------------------------------------

def test_nao_medido_nao_conta_como_zero():
    i = IndiceIntegridade(cobertura=None, coerencia=1, tempestividade=1, vinculo=1, prestacao=1,
                          motivos={"cobertura": "o sistema não leu"})
    assert i.nao_medidas == ["cobertura"] and not i.completo
    assert i.nota == 60 and i.pontos_medidos == 60 and i.nota_maxima == 100
    assert not i.gera_pedido_de_acesso
    assert "60 de 60 pontos medidos" in i.frase()
    d = i.como_dict()
    assert d["partes"]["cobertura"] is None and d["motivos"]["cobertura"] == "o sistema não leu"


def test_pedido_de_acesso_so_quando_nem_o_maximo_chega_ao_minimo():
    # 40 pontos não medidos: com o resto zerado, o máximo seria 40 < 50, então o pedido sai.
    assert IndiceIntegridade(None, 0, 0, 0, 0).gera_pedido_de_acesso
    # 25 de coerência medidos + 40 não medidos: o máximo chega a 65, então nenhum ofício sai.
    assert not IndiceIntegridade(None, 1, 0, 0, 0).gera_pedido_de_acesso
    # completo e abaixo do mínimo: sai, como antes
    assert IndiceIntegridade(0, 1, 0, 0, 0).gera_pedido_de_acesso


# --- O Município pelos demonstrativos do banco -----------------------------------------

def test_tetos_de_2025_batem_com_o_declarado():
    f = fiscal.medir_municipio(date(2025, 12, 31))
    assert f.rgf.rotulo == "RGF do 3º quadrimestre de 2025"
    assert f.rreo.rotulo == "RREO do 6º bimestre de 2025"
    por = {m.regra.id: m for m in f.medidas}
    assert por["PESSOAL-EXECUTIVO"].percentual == pytest.approx(45.97, abs=0.01)
    assert por["DIVIDA-CONSOLIDADA"].percentual == pytest.approx(8.06, abs=0.01)
    assert por["OPERACOES-CREDITO"].percentual == pytest.approx(1.34, abs=0.01)
    for m in f.medidas:
        assert m.selo is Selo.VERDE and not m.divergencia and m.situacao == "cumpre"
        assert f.memoria[m.regra.id]
    # memória de cálculo com a despesa bruta dos doze meses publicados
    assert "soma dos doze meses publicados" in f.memoria["PESSOAL-EXECUTIVO"]
    assert f.fichas("2025-12") == []


def test_duas_vias_rgf_contra_rreo_em_todos_os_quadrimestres():
    con = sqlite3.connect(BANCO)
    periodos = con.execute("select exercicio, periodo, termina from siconfi_periodos where "
                           "demonstrativo='RGF' and situacao='entregue'").fetchall()
    con.close()
    assert periodos
    for ex, q, termina in periodos:
        f = fiscal.medir_municipio(date.fromisoformat(termina))
        independentes = [c for c in f.conferencias if c.entre_demonstrativos]
        assert {c.titulo for c in independentes} == {
            "Receita corrente líquida", "Receita corrente líquida ajustada para a despesa com pessoal",
            "Dívida consolidada líquida"}, (ex, q)
        assert all(c.selo is Selo.VERDE for c in independentes), (ex, q)
        assert len(f.certificacoes()) == 3


def test_divergencia_entre_rgf_e_rreo_vira_ficha(tmp_path):
    copia = tmp_path / "historico.db"
    shutil.copy(BANCO, copia)
    con = sqlite3.connect(copia)
    con.execute("update siconfi_itens set valor = valor * 1.05 where demonstrativo='RREO' and "
                "exercicio=2025 and periodo=6 and anexo='RREO-Anexo 03' and "
                "cod_conta='RREO3ReceitaCorrenteLiquida' and coluna like 'TOTAL%'")
    con.commit()
    con.close()
    f = fiscal.medir_municipio(date(2025, 12, 31), banco=copia)
    rcl = next(c for c in f.conferencias if c.titulo == "Receita corrente líquida")
    assert rcl.selo is Selo.AZUL and rcl.certificacao.divergencia
    fichas = f.fichas("2025-12")
    assert [x.codigo for x in fichas] == ["VIAS-RECEITA-CORRENTE-LIQUIDA-2025-12"]
    assert fichas[0].familia is Familia.PISO


def test_declarado_diferente_do_calculo_proprio_vira_ficha(tmp_path):
    copia = tmp_path / "historico.db"
    shutil.copy(BANCO, copia)
    con = sqlite3.connect(copia)
    con.execute("update siconfi_itens set valor = 40.0 where demonstrativo='RGF' and exercicio=2025 and "
                "periodo=3 and anexo='RGF-Anexo 01' and cod_conta='DespesaComPessoalTotal' and "
                "coluna='% sobre a RCL Ajustada'")
    con.commit()
    con.close()
    f = fiscal.medir_municipio(date(2025, 12, 31), banco=copia)
    pessoal = next(m for m in f.medidas if m.regra.id == "PESSOAL-EXECUTIVO")
    assert pessoal.divergencia and pessoal.selo is Selo.AZUL
    assert "PISO-DIV-PESSOAL-EXECUTIVO-2025-12" in {x.codigo for x in f.fichas("2025-12")}


def test_liquidado_na_funcao_so_fora_das_intraorcamentarias():
    valor, per = fiscal.liquidado_na_funcao("Assistência Social", date(2026, 10, 31))
    assert per.rotulo == "RREO do 4º bimestre de 2026"
    assert valor == pytest.approx(16041780.89)


# --- O parecer com os números do banco ---------------------------------------------------

@pytest.fixture(scope="module")
def panorama():
    return cadeoqueijo.montar("2026-10")


def test_parecer_traz_o_municipio_e_as_duas_vias(panorama):
    assert panorama.fiscal is not None and len(panorama.fiscal.medidas) == 3
    pagina = html.gerar(panorama, hoje=date(2026, 11, 26))
    assert "O Município: RGF do 2º quadrimestre de 2026" in pagina
    assert "Duas vias" in pagina and "RREO Anexo 3" in pagina
    d = panorama.como_dict()
    assert {t["regra"] for t in d["municipio"]["tetos"]} == {
        "PESSOAL-EXECUTIVO", "DIVIDA-CONSOLIDADA", "OPERACOES-CREDITO"}


def test_nenhuma_parte_da_nota_e_zero_fixo(panorama):
    ind = panorama.integridade
    # Cada parte medida tem a evidência; a não medida tem o motivo.
    for nome in ("cobertura", "coerencia", "tempestividade", "vinculo", "prestacao"):
        assert ind.motivos.get(nome), nome
    assert ind.coerencia == 1.0 and "RGF e no RREO" in ind.motivos["coerencia"]
    assert "liquidados na Assistência Social" in ind.motivos["cobertura"]


def test_leituras_do_diario_que_divergem_nao_pesam_contra_o_municipio(panorama):
    ind = panorama.integridade
    assert ind.tempestividade is None
    assert "divergem" in ind.motivos["tempestividade"]
    assert any("Diário Oficial de 2026-10" in v for v in panorama.leitura_falhou)


def test_rreo_publicado_no_siconfi_nao_e_ausencia(panorama):
    assert all(a.o_que_falta != "Relatório Resumido da Execução Orçamentária" for a in panorama.ausencias)


def test_sem_banco_o_parecer_diz_que_a_leitura_falhou(tmp_path):
    p = cadeoqueijo.montar("2026-10", banco=tmp_path / "nao_existe.db")
    assert p.fiscal is None
    assert p.integridade.cobertura is None and p.integridade.coerencia is None
    assert any("Banco histórico" in v for v in p.leitura_falhou)
