"""Conferências das compras e contratos no banco histórico (bloco 4 do desenho original)."""

from __future__ import annotations

from pathlib import Path

import pytest

from onisciente import historico
from onisciente.conferencias import compras
from onisciente.nucleo.indicios import Familia

FMAS = ("01393989000103", "FUNDO MUNICIPAL DE ASSISTENCIA SOCIAL-FMAS")
SMS = ("01234567000100", "SECRETARIA MUNICIPAL DE SAUDE")


def _compra(b, pid, mes, mod, orgao, objeto, valor, amparo=None):
    b.inserir("contratacoes_pncp", {"pncp_id": pid, "mes": mes, "modalidade": mod, "orgao_cnpj": orgao[0],
                                    "orgao": orgao[1], "unidade": orgao[1], "objeto": objeto,
                                    "valor_estimado": valor, "valor_homologado": valor, "situacao": "Divulgada"})
    if amparo:
        b.inserir("pncp_amparos", {"compra_id": pid, "codigo": 0, "nome": amparo})


def _contrato(b, pid, mes, orgao, forn_ni, forn, objeto, valor, **detalhe):
    b.inserir("contratos_pncp", {"pncp_id": pid, "mes": mes, "data_assinatura": mes + "-10", "orgao_cnpj": orgao[0],
                                 "orgao": orgao[1], "unidade": orgao[1], "fornecedor_ni": forn_ni,
                                 "fornecedor": forn, "objeto": objeto, "valor_global": valor, "da_pasta": 0})
    if detalhe:
        b.inserir("pncp_contratos_detalhe", {"contrato_id": pid, **detalhe})


@pytest.fixture()
def banco(tmp_path: Path):
    b = historico.Banco(tmp_path / "h.db")
    # Dispensa por valor acima do limite de 2025 (62.725,59 para compras).
    _compra(b, "01393989000103-1-000001/2025", "2025-03", "Dispensa", FMAS, "Aquisição de cestas básicas",
            80000.0, "Lei 14.133/2021, Art. 75, II")
    # Duas dispensas de alimentação que, somadas, passam do limite (fracionamento) e uma no teto.
    _compra(b, "01393989000103-1-000002/2025", "2025-04", "Dispensa", FMAS, "Gêneros alimentícios para o CRAS",
            40000.0, "Lei 14.133/2021, Art. 75, II")
    _compra(b, "01393989000103-1-000003/2025", "2025-06", "Dispensa", FMAS, "Kit lanche para eventos do CREAS",
            62000.0, "Lei 14.133/2021, Art. 75, II")
    # Emergencial (art. 75, VIII) acima do limite não é dispensa por valor: não entra no fracionamento.
    _compra(b, "01393989000103-1-000004/2025", "2025-02", "Dispensa", FMAS, "Refeições para o abrigo",
            900000.0, "Lei 14.133/2021, Art. 75, VIII")
    _compra(b, "01393989000103-1-000005/2026", "2026-02", "Dispensa", FMAS, "Refeições para o abrigo",
            900000.0, "Lei 14.133/2021, Art. 75, VIII")
    # Obra: limite maior (art. 75, I), 125.451,15 em 2025: 100 mil cabe.
    _compra(b, "01393989000103-1-000006/2025", "2025-05", "Dispensa", FMAS, "Reforma da sede do CRAS Leste",
            100000.0, "Lei 14.133/2021, Art. 75, I")
    # Contratos: emergencial de 2 anos e recontratado; reforma com aditivo de 40% (cabe nos 50%);
    # serviço com aditivo de 30% (passa dos 25%); notas fiscais acima do contrato.
    _contrato(b, "01393989000103-2-000010/2025", "2025-02", FMAS, "111", "Cozinha Boa Ltda", "Refeições para o abrigo",
              900000.0, compra_id="01393989000103-1-000004/2025", valor_inicial=900000.0, valor_global=900000.0,
              vigencia_inicio="2025-02-10", vigencia_fim="2027-02-10")
    _contrato(b, "01393989000103-2-000011/2026", "2026-02", FMAS, "111", "Cozinha Boa Ltda", "Refeições para o abrigo",
              900000.0, compra_id="01393989000103-1-000005/2026", valor_inicial=900000.0, valor_global=900000.0,
              vigencia_inicio="2026-02-10", vigencia_fim="2027-01-10")
    _contrato(b, "01393989000103-2-000012/2025", "2025-05", FMAS, "222", "Obras Já Ltda", "Reforma da sede do CRAS Leste",
              100000.0, compra_id="01393989000103-1-000006/2025", valor_inicial=100000.0, valor_global=140000.0,
              vigencia_inicio="2025-05-10", vigencia_fim="2026-05-10")
    b.inserir("pncp_termos", {"contrato_id": "01393989000103-2-000012/2025", "sequencial": 1, "valor_acrescido": 40000.0,
                              "acrescimo_supressao": 1, "data_assinatura": "2025-09-01"})
    _contrato(b, "01393989000103-2-000013/2025", "2025-07", FMAS, "333", "Limpa Tudo Ltda", "Serviço de limpeza",
              1000000.0, valor_inicial=1000000.0, valor_global=1300000.0, vigencia_inicio="2025-07-01",
              vigencia_fim="2026-07-01")
    b.inserir("pncp_termos", {"contrato_id": "01393989000103-2-000013/2025", "sequencial": 1,
                              "valor_acrescido": 300000.0, "acrescimo_supressao": 1, "data_assinatura": "2025-11-03"})
    b.inserir("pncp_termos", {"contrato_id": "01393989000103-2-000013/2025", "sequencial": 2,
                              "valor_acrescido": 50000.0, "qualif_reajuste": 1, "acrescimo_supressao": 0,
                              "data_assinatura": "2025-12-03"})   # reajuste: fora do limite
    b.inserir("pncp_cobrancas", {"contrato_id": "01393989000103-2-000012/2025", "sequencial": 1, "valor_nf": 90000.0,
                                 "data_emissao": "2025-10-01"})
    b.inserir("pncp_cobrancas", {"contrato_id": "01393989000103-2-000012/2025", "sequencial": 2, "valor_nf": 60000.0,
                                 "data_emissao": "2025-11-01"})
    b.inserir("pncp_cobrancas", {"contrato_id": "01393989000103-2-000012/2025", "sequencial": 3, "valor_nf": 99999.0,
                                 "data_emissao": "2025-11-02", "evento": "Cancelamento"})
    # Concentração: na Saúde, 12 fornecedores, 2 levam mais de 80%.
    for i in range(12):
        valor = 5_000_000.0 if i < 2 else 100_000.0
        _contrato(b, f"01234567000100-2-{i:06d}/2025", "2025-08", SMS, f"9{i:02d}", f"Fornecedor {i}",
                  "Serviço", valor)
    # Preço: item com catálogo contra 6 compras do país.
    b.inserir("pncp_itens", {"compra_id": "01393989000103-1-000002/2025", "numero_item": 1, "orgao_cnpj": FMAS[0],
                             "descricao": "Arroz tipo 1, pacote 5 kg", "catalogo": 440744, "classe": 8920,
                             "unidade_medida": "Pacote", "unitario_resultado": 60.0, "data_resultado": "2025-04-20",
                             "total_resultado": 40000.0})
    for i, preco in enumerate([25.0, 26.0, 27.0, 28.0, 29.0, 30.0]):
        b.inserir("precos_referencia", {"catalogo": 440744, "semestre": "2025-1", "id_item": str(i), "preco": preco,
                                        "unidade": "PACOTE", "municipio": "Anápolis", "esfera": "M"})
    b.inserir("precos_referencia", {"catalogo": 440744, "semestre": "2025-1", "id_item": "x", "preco": 500.0,
                                    "unidade": "CAIXA", "municipio": "Recife", "esfera": "M"})  # outra unidade: fora
    b.con.commit()
    yield tmp_path / "h.db"
    b.con.close()


def _tipos(c, tipo):
    return [a for a in c.achados if a.tipo == tipo]


def test_dispensa_acima_do_limite_do_ano_e_no_teto(banco):
    c = compras.conferir(banco)
    acima = _tipos(c, "dispensa_acima")
    assert [a.chave for a in acima] == ["01393989000103-1-000001/2025"]
    assert acima[0].limite == pytest.approx(62725.59)
    teto = _tipos(c, "dispensa_no_teto")
    assert [a.chave for a in teto] == ["01393989000103-1-000003/2025"]       # 62.000 = 98,8% do limite
    assert all(a.chave != "01393989000103-1-000006/2025" for a in acima)      # obra: limite do art. 75, I


def test_fracionamento_soma_o_mesmo_ramo_e_ignora_emergencial(banco):
    frac = _tipos(compras.conferir(banco), "fracionamento")
    assert len(frac) == 1
    a = frac[0]
    assert a.mes == "2025-04" and a.valor == pytest.approx(80000 + 40000 + 62000)
    assert "01393989000103-1-000004/2025" not in a.dados["compras"]


def test_compra_sem_resultado_homologado_nao_entra_na_soma(tmp_path):
    b = historico.Banco(tmp_path / "h.db")
    _compra(b, "01393989000103-1-000001/2025", "2025-03", "Dispensa", FMAS, "Água mineral em galões", 59000.0)
    b.con.execute("update contratacoes_pncp set valor_homologado = null")          # não homologada: refeita
    _compra(b, "01393989000103-1-000002/2025", "2025-04", "Dispensa", FMAS, "Água mineral em galões", 61000.0)
    b.con.commit()
    c = compras.conferir(tmp_path / "h.db")
    assert not _tipos(c, "fracionamento") and c.cobertura["dispensas_sem_resultado"] == 1


def test_emergencial_mais_de_um_ano_e_recontratado(banco):
    emerg = {a.chave: a for a in _tipos(compras.conferir(banco), "emergencial")}
    assert "acima de um ano" in emerg["01393989000103-2-000010/2025"].descricao
    assert "recontratação" in emerg["01393989000103-2-000011/2026"].descricao


def test_aditivo_25_por_cento_e_reforma_50(banco):
    adit = {a.chave: a for a in _tipos(compras.conferir(banco), "aditivo")}
    assert "01393989000103-2-000012/2025" not in adit                     # reforma: 40% cabe nos 50%
    assert adit["01393989000103-2-000013/2025"].dados["pct"] == pytest.approx(30.0)   # reajuste não conta


def test_concentracao_e_notas_acima_do_contrato(banco):
    c = compras.conferir(banco)
    conc = _tipos(c, "concentracao")
    assert len(conc) == 1 and conc[0].orgao == SMS[1] and conc[0].dados["levam_o_corte"] == 2
    nota = _tipos(c, "nota_acima")
    assert len(nota) == 1 and nota[0].valor == pytest.approx(150000 - 140000)    # a cancelada não conta


def test_preco_contra_a_mediana_nacional_na_mesma_unidade(banco):
    preco = _tipos(compras.conferir(banco), "preco")
    assert len(preco) == 1
    cmp = preco[0].dados["comparacao"]
    assert cmp.amostra == 6 and cmp.mediana == pytest.approx(27.5)


def test_servico_por_lote_e_unidade_diferente_nao_viram_sobrepreco(banco):
    """27/11: 514 dos 770 sobrepreços do banco real eram um serviço contratado como "1 unidade" (o
    contrato inteiro) ou uma unidade diferente (lote, caixa) contra a mediana do item no país."""
    import sqlite3
    con = sqlite3.connect(banco)
    cols = "compra_id, numero_item, orgao_cnpj, descricao, catalogo, material_servico, unidade_medida, " \
           "quantidade, unitario_resultado, data_resultado"
    con.execute(f"insert into pncp_itens ({cols}) values (?,?,?,?,?,?,?,?,?,?)",
                ("01393989000103-1-000002/2025", 2, FMAS[0], "Lavanderia", 26000, "S", "Unidade", 1, 900000.0,
                 "2025-04-20"))   # um lote de serviço: 1 "unidade" de 900 mil
    con.execute(f"insert into pncp_itens ({cols}) values (?,?,?,?,?,?,?,?,?,?)",
                ("01393989000103-1-000002/2025", 3, FMAS[0], "Brinquedo", 150000, "M", "Unidade", 10, 3000.0,
                 "2025-04-20"))   # 3.000 a unidade contra 30 no país: o "item" é um kit
    for i in range(6):
        con.execute("insert into precos_referencia (catalogo, semestre, id_item, material_servico, preco, "
                    "quantidade, unidade, municipio, esfera) values (?,?,?,?,?,?,?,?,?)",
                    (26000, "2025-1", f"l{i}", "S", 20.0 + i, 500, "UNIDADE", "Anápolis", "M"))
        con.execute("insert into precos_referencia (catalogo, semestre, id_item, material_servico, preco, "
                    "quantidade, unidade, municipio, esfera) values (?,?,?,?,?,?,?,?,?)",
                    (150000, "2025-1", f"b{i}", "M", 28.0 + i, 20, "UNIDADE", "Anápolis", "M"))
    con.execute("insert into precos_referencia (catalogo, semestre, id_item, material_servico, preco, quantidade, "
                "unidade, municipio, esfera) values (26000, '2025-1', 'lote', 'S', 800000.0, 1, 'UNIDADE', 'Recife', 'M')")
    con.commit()
    con.close()
    c = compras.conferir(banco)
    precos = _tipos(c, "preco")
    assert [a.chave for a in precos] == ["01393989000103-1-000002/2025-1"]     # só o arroz, como antes
    assert c.cobertura["servicos_contratados_por_lote"] == 1
    assert c.cobertura["itens_com_unidade_incompativel"] == 1


def test_orgao_lido_no_pncp_sem_nenhuma_nota_fiscal_e_alerta_de_transparencia(banco):
    """A ausência do dado é o alerta: o órgão cujos meses foram lidos sem nenhuma nota fiscal de
    nenhum contrato não publicou o que a Lei 14.133/2021 (art. 174, § 2º, V) manda; mês não lido
    não acusa ninguém."""
    import json
    import sqlite3
    con = sqlite3.connect(banco)
    lidos = [f"cobrancas {SMS[0]} 2025-{m:02d}" for m in range(1, 13)] + \
            [f"cobrancas {FMAS[0]} 2025-{m:02d}" for m in range(1, 13)]
    con.execute("insert or replace into meta (chave, valor) values ('pncp_detalhe_lidos', ?)", (json.dumps(lidos),))
    con.commit()
    con.close()
    c = compras.conferir(banco)
    ausentes = _tipos(c, "nf_ausente")
    assert [a.orgao_cnpj for a in ausentes] == [SMS[0]]                  # o FMAS publicou notas
    assert ausentes[0].dados == {"meses": 12, "contratos": 12, "desde": "2025-01"} and ausentes[0].mes == "2025-12"
    assert ausentes[0] in c.da_competencia("2025-06", so_da_pasta=False)     # vale no período lido inteiro
    assert ausentes[0] not in c.da_competencia("2024-12", so_da_pasta=False)
    assert c.cobertura["orgaos_sem_nota_fiscal_publicada"] == 1
    f = compras.ficha(ausentes[0], "2025-12")
    assert f.codigo.startswith("ENT-NF00-") and f.familia is Familia.ENT


def test_sem_meses_lidos_nao_ha_alerta_de_nota_fiscal(banco):
    assert not _tipos(compras.conferir(banco), "nf_ausente")


def test_fichas_so_da_pasta_na_janela_da_competencia(banco):
    c = compras.conferir(banco)
    fichas = c.fichas("2025-12")
    prefixos = {"PRC-DISP01", "PRC-DISP02", "PRC-FRAC01", "PRC-EMERG01", "PRC-SOB04", "ENT-NF01", "PRC-SOB02"}
    achados = {p for p in prefixos if any(f.codigo.startswith(p + "-") for f in fichas)}
    assert achados == prefixos
    assert not any("CONC" in f.codigo for f in fichas)                      # a Saúde não é da pasta
    assert all(f.competencia == "2025-12" for f in fichas)
    assert not [f for f in c.fichas("2024-12") if f.familia is not Familia.SIS]   # nada antes do fato


def test_cobertura_incompleta_da_pasta_vira_ficha_do_sistema(banco):
    c = compras.conferir(banco)
    assert c.cobertura["amparo_lido"] == 6
    assert c.cobertura["lacunas_da_pasta"] == []          # tudo da pasta tem amparo e detalhe no banco
    sis = [f for f in c.fichas("2025-12") if f.familia is Familia.SIS]
    assert len(sis) == (1 if c.cobertura["lacunas_da_pasta"] else 0)


def test_banco_sem_tabelas_do_detalhe_nao_quebra(tmp_path):
    import sqlite3
    con = sqlite3.connect(tmp_path / "v.db")
    con.execute("create table contratacoes_pncp (pncp_id, mes, modalidade, orgao_cnpj, orgao, esfera, unidade, "
                "objeto, valor_estimado, valor_homologado, situacao)")
    con.execute("insert into contratacoes_pncp values ('x-1-000001/2025', '2025-01', 'Dispensa', '1', "
                "'FUNDO MUNICIPAL DE ASSISTENCIA SOCIAL', 'M', '', 'Água mineral', 62000, 62000, '')")
    con.commit()
    c = compras.conferir(tmp_path / "v.db")
    assert [a.tipo for a in c.achados] == ["dispensa_no_teto"]
    assert c.cobertura["lacunas_da_pasta"]       # amparo não lido: a pasta fica sabendo pela ficha SIS


def test_classificador_de_ramo_e_inciso():
    assert compras.ramo("Aquisição de MATERIAIS DE CONSTRUÇÃO para reparos") == "material de construção"
    assert compras.ramo("Manutenção preventiva e corretiva de veículos da frota") == "manutenção de veículos"
    assert compras.ramo("Consultoria jurídica") is None
    assert compras.ramo("Fornecimento de água mineral em galões") == "água mineral"   # forneCIMENTO não é cimento
    assert compras.ramo("Eventual fornecimento de cobertores") is None                # EVENTUAL não é evento
    assert compras.ramo("Serviço de mão de obra terceirizada") is None                 # mão de obra não é obra
    assert compras.inciso("Lei 14.133/2021, Art. 75, II") == (75, "II")
    assert compras.inciso("Lei 14.133/2021, Art. 75, VIII") == (75, "VIII")
    assert compras.inciso("Lei 14.133/2021, Art. 74, I") == (74, "I")


def test_secao_preco_e_entrega_do_parecer_mostra_as_conferencias_e_a_base(banco):
    """Seção 5 do parecer: a tabela das conferências da pasta, o Município por órgão e a base lida."""
    from types import SimpleNamespace

    from onisciente.parecer import html
    c = compras.conferir(banco)
    texto = html._secao_compras(SimpleNamespace(compras=c, competencia="2025-12"))
    assert "Fracionamento de despesa" in texto and "Preço unitário acima da curva nacional" in texto
    assert "O Município inteiro" in texto and "Secretaria Municipal De Saude" in texto
    assert "itens comparados com o preço do país" in texto and "ficam fora da comparação" in texto
