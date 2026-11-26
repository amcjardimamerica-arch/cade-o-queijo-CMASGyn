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
        if m.regra.id not in ("PESSOAL-EXECUTIVO", "DIVIDA-CONSOLIDADA", "OPERACOES-CREDITO"):
            continue                       # os pisos têm testes próprios
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
        assert {"Receita corrente líquida", "Receita corrente líquida ajustada para a despesa com pessoal",
                "Dívida consolidada líquida"} <= {c.titulo for c in independentes}, (ex, q)
        assert all(c.selo is Selo.VERDE for c in independentes), (ex, q)
        assert len(f.certificacoes()) == len(independentes)


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


def test_camara_pelo_art_29a_com_duas_vias():
    f = fiscal.medir_municipio(date(2026, 10, 31))
    camara = next(m for m in f.medidas if m.regra.id == "CAMARA")
    # 2025 (último exercício fechado) sobre a base de 2024, faixa IV do alvo: 4,5%
    assert camara.limite == 4.5 and camara.situacao == "cumpre"
    assert camara.percentual == pytest.approx(4.28, abs=0.01)
    assert camara.selo is Selo.VERDE
    vias = {c.titulo: c for c in f.conferencias if "Câmara" in c.titulo}
    assert set(vias) == {"Despesa liquidada da Câmara em 2025", "Base do limite da Câmara (2024)"}
    assert all(c.selo is Selo.VERDE for c in vias.values())
    assert "intraorçamentárias" in f.memoria["CAMARA"] and "faixa IV" in f.memoria["CAMARA"]


def test_camara_sem_base_do_ano_anterior_fica_sem_dado():
    # Em 2025 o exercício fechado é 2024 e a base de 2023 não está no banco.
    f = fiscal.medir_municipio(date(2025, 6, 30))
    camara = next(m for m in f.medidas if m.regra.id == "CAMARA")
    assert camara.situacao == "sem_dado" and camara.selo is Selo.ROXO
    assert any("6º bimestre de 2023" in n for n in f.notas)


def test_liquidado_na_funcao_so_fora_das_intraorcamentarias():
    valor, per = fiscal.liquidado_na_funcao("Assistência Social", date(2026, 10, 31))
    assert per.rotulo == "RREO do 4º bimestre de 2026"
    assert valor == pytest.approx(16041780.89)


# --- O parecer com os números do banco ---------------------------------------------------

@pytest.fixture(scope="module")
def panorama():
    return cadeoqueijo.montar("2026-10")


def test_parecer_traz_o_municipio_e_as_duas_vias(panorama):
    assert panorama.fiscal is not None and len(panorama.fiscal.medidas) >= 4
    pagina = html.gerar(panorama, hoje=date(2026, 11, 26))
    assert "O Município: RGF do 2º quadrimestre de 2026" in pagina
    assert "Duas vias" in pagina and "RREO Anexo 3" in pagina
    d = panorama.como_dict()
    assert {t["regra"] for t in d["municipio"]["tetos"]} >= {
        "PESSOAL-EXECUTIVO", "DIVIDA-CONSOLIDADA", "OPERACOES-CREDITO", "CAMARA"}


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


# --- Saúde: o Anexo 12 homologado no SIOPS, com a base refeita pelo RREO e pela DCA ---------

DADOS = RAIZ / "testes" / "dados"


def _banco_com_siops(tmp_path, *, exercicio=2025, periodo=6, ajuste=None):
    """Cópia do banco com o demonstrativo da saúde de 2025 (6º bimestre) lido da página do SIOPS."""
    from onisciente import historico
    from onisciente.coletores import siops
    copia = tmp_path / "historico.db"
    shutil.copy(BANCO, copia)
    b = historico.Banco.abrir(copia)
    d = siops.ler((DADOS / "siops_goiania_2025_6bim.html").read_text(encoding="utf-8"))
    for linha in d.linhas:
        for coluna, valor in enumerate(linha.valores):
            if valor is not None:
                b.inserir("externos_itens", dict(
                    fonte="SIOPS", exercicio=exercicio, periodo=periodo, quadro=linha.quadro,
                    titulo_quadro=linha.titulo_quadro, ordem=linha.ordem, rotulo=linha.rotulo,
                    coluna=coluna, valor=valor))
    b.inserir("externos_periodos", dict(fonte="SIOPS", exercicio=exercicio, periodo=periodo,
                                        homologado=d.homologado, situacao="homologado",
                                        linhas=len(d.linhas), erro=None))
    if ajuste:
        b.con.execute(ajuste)
    b.con.commit()
    b.con.close()
    return copia


def test_siops_lido_linha_a_linha():
    from onisciente.coletores import siops
    escolha = (DADOS / "siops_escolha_go_2025.html").read_text(encoding="utf-8")
    assert siops.periodos(escolha) == {1: "12", 2: "14", 3: "1", 4: "18", 5: "20", 6: "2"}
    assert siops.codigo_municipio(escolha, "Goiânia") == "520870"
    d = siops.ler((DADOS / "siops_goiania_2025_6bim.html").read_text(encoding="utf-8"))
    assert (d.exercicio, d.bimestre, d.homologado) == (2025, 6, "06/02/26 10:00:59")
    assert d.procurar(r"^PERCENTUAL DA RECEITA").valores == [21.54, 21.33, 21.23]
    assert d.procurar(r"^COTA-PARTE FPM").valores[2] == 648304218.84
    with pytest.raises(ValueError):
        siops.ler("<html>O Municipio não transmitiu</html>")


def test_piso_da_saude_de_2025_com_base_propria_e_duas_vias(tmp_path):
    f = fiscal.medir_municipio(date(2025, 12, 31), banco=_banco_com_siops(tmp_path))
    saude = next(m for m in f.medidas if m.regra.id == "PISO-SAUDE")
    assert saude.situacao == "cumpre" and saude.selo is Selo.VERDE and not saude.divergencia
    assert saude.declarado == 21.54 and saude.percentual == pytest.approx(21.56, abs=0.01)
    assert saude.numerador == pytest.approx(1301828372.25)          # empenhado: fim do exercício
    vias = {c.titulo: c for c in f.conferencias if "saúde" in c.titulo}
    assert set(vias) == {"Receita da base da saúde (6º bimestre de 2025)",
                         "Despesa liquidada com saúde (6º bimestre de 2025)"}
    assert all(c.selo is Selo.VERDE and c.entre_demonstrativos for c in vias.values())
    assert "cota mensal" in f.memoria["PISO-SAUDE"] and "DCA" in f.fontes["PISO-SAUDE"]


def test_saude_declarada_diferente_do_calculo_vira_ficha(tmp_path):
    banco = _banco_com_siops(tmp_path, ajuste="update externos_itens set valor = 25.0 where rotulo like "
                                              "'PERCENTUAL DA RECEITA%' and coluna = 0")
    f = fiscal.medir_municipio(date(2025, 12, 31), banco=banco)
    saude = next(m for m in f.medidas if m.regra.id == "PISO-SAUDE")
    assert saude.divergencia and saude.selo is Selo.AZUL
    assert "PISO-DIV-PISO-SAUDE-2025-12" in {x.codigo for x in f.fichas("2025-12")}


def test_saude_abaixo_de_15_antes_do_fim_do_ano_e_alerta(tmp_path):
    # O mesmo demonstrativo posto no 2º bimestre de 2026, com o liquidado reduzido a R$ 100 milhões.
    banco = _banco_com_siops(tmp_path, exercicio=2026, periodo=2, ajuste=(
        "update externos_itens set valor = 100000000 where rotulo like '(=) VALOR APLICADO EM ASPS%' "
        "and coluna = 1"))
    f = fiscal.medir_municipio(date(2026, 4, 30), banco=banco)
    saude = next(m for m in f.medidas if m.regra.id == "PISO-SAUDE")
    assert saude.percentual < 15 and saude.situacao == "alerta"
    assert saude.numerador == 100000000                              # liquidado: antes do fim do ano
    assert "acompanhamento" in f.memoria["PISO-SAUDE"]
    assert not any(x.titulo.endswith("limite descumprido") for x in f.fichas("2026-04"))


def test_saude_sem_siops_fica_sem_dado():
    f = fiscal.medir_municipio(date(2023, 12, 31))
    saude = next(m for m in f.medidas if m.regra.id == "PISO-SAUDE")
    assert saude.situacao == "sem_dado"
