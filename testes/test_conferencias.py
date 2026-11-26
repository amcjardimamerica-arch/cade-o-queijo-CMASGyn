"""Conferências: preço, contrato, entrega, prestação, padrões, devidos, contas, LAI e tempo."""

from datetime import date

from onisciente import contas, lai, tempo
from onisciente.conferencias import devidos, execucao, padroes, precos
from onisciente.nucleo import Ausencia, Verificacao


def test_percentil_e_sobrepreco():
    assert precos.percentil([1, 2, 3, 4, 5], 50) == 3
    ref = [100, 98, 102, 101, 99, 100, 103]
    c = precos.comparar("resma de papel", 150, ref)
    assert c.destoa and c.excesso_pct == 50.0
    assert not precos.comparar("resma de papel", 102, ref).destoa   # dentro do percentil 95
    assert precos.comparar("resma de papel", 110, ref).destoa       # acima do percentil 95
    assert precos.comparar("item raro", 999, [100, 100]) is None  # amostra pequena
    f = precos.ficha_de_sobrepreco(c, contrato="12-2026")
    assert f.verificacao is Verificacao.CONFIRMADO


def test_aditivo_acima_de_25_por_cento():
    assert execucao.excesso_de_aditivos(1000, [100, 100]) is None
    assert execucao.excesso_de_aditivos(1000, [200, 100]) == 30.0


def test_fracionamento_soma_o_mesmo_objeto_no_ano():
    compras = [execucao.Compra("Material de limpeza", 40000, date(2026, 2, 1)),
               execucao.Compra("material de limpeza ", 30000, date(2026, 5, 1)),
               execucao.Compra("Material de limpeza", 30000, date(2025, 5, 1)),
               execucao.Compra("Reforma", 100000, date(2026, 5, 1), obra_ou_engenharia=True)]
    achados = execucao.fracionamentos(compras)
    assert len(achados) == 1 and achados[0]["soma"] == 70000 and achados[0]["ano"] == 2026


def test_entrega():
    assert execucao.liquidado_acima_do_contratado(100, [60, 50]) == 10
    assert execucao.liquidado_acima_do_contratado(100, [60, 40]) is None
    assert execucao.medicoes_repetidas([10, 10, 10])
    assert not execucao.medicoes_repetidas([10, 10, 11, 10])


def test_ficha_de_ordem_sem_liquidacao_e_inconclusiva():
    f = execucao.ficha_de_ordem("E1", ["pagamento sem liquidação publicada (Lei 4.320/1964, art. 62)"])
    assert f.verificacao is Verificacao.INCONCLUSIVO


def test_prestacao_de_contas():
    ps = [execucao.Parceria("TF-1", "Entidade A", 100, prazo_vencido=True),
          execucao.Parceria("TF-2", "Entidade B", 100, prestacao_publicada=True),
          execucao.Parceria("TF-3", "Entidade C", 100, prestacao_publicada=True,
                            prestacao_individualizada=False, saldo_nao_devolvido=5)]
    fichas = execucao.fichas_de_prestacao(ps)
    assert [f.codigo for f in fichas] == ["PCT-TF-1", "PCT-TF-3"]


def test_padroes_de_gasto():
    pg = [padroes.Pagamento("A", 85, date(2026, 1, 5)), padroes.Pagamento("B", 5, date(2026, 1, 5)),
          padroes.Pagamento("C", 5, date(2026, 1, 5)), padroes.Pagamento("D", 5, date(2026, 1, 5))]
    c = padroes.concentracao(pg)
    assert c["levam_o_corte"] == 1 and c["concentrado"]
    sem = [padroes.Pagamento("X", 1, date(2026, m, 1), com_contrato=False) for m in (1, 2, 3)]
    assert padroes.recorrentes_sem_contrato(sem) == ["X"]
    emp = [padroes.Pagamento("Y", 30, date(2026, 12, 28)), padroes.Pagamento("Y", 70, date(2026, 6, 1))]
    assert padroes.empenhos_no_fim_do_ano(emp) == 0.3
    assert padroes.fora_da_serie(400, {2023: 100, 2024: 100, 2025: 100})
    assert not padroes.fora_da_serie(400, {2024: 100, 2025: 100})


def test_dinheiro_que_deveria_ter_saido():
    f = devidos.conferir_revisao_geral(devidos.RevisaoGeral(
        2024, 3.69, 3.69, "Lei 11.248/2024", ("magistério", "agentes de saúde e de endemias")))
    assert f and "magistério" in f.como_esta
    assert devidos.conferir_revisao_geral(devidos.RevisaoGeral(2026, 5.0, 4.26, "Lei X")) is None
    assert devidos.atraso_de_folha("2026-12", date(2027, 1, 9)) == 4
    assert devidos.atraso_de_folha("2026-03", date(2026, 4, 5)) == 0
    assert devidos.atraso_previdencia("2026-03", date(2026, 4, 25)) == 5


def test_prazos_das_contas():
    assert contas.prazo_balancete("2026-01") == date(2026, 3, 17)
    assert contas.prazo_balancete("2026-12") == date(2027, 2, 14)
    c = contas.avaliar(contas.Conta(2024, "Prefeito"), date(2025, 6, 1))
    assert c.atrasos and "não entregues" in c.atrasos[0]
    ok = contas.avaliar(contas.Conta(2024, "Prefeito", entregue_em=date(2025, 3, 1),
                                     parecer_em=date(2025, 4, 20), julgada_em=date(2025, 6, 1)),
                        date(2026, 6, 1))
    assert ok.atrasos == []
    atrasada = contas.avaliar(contas.Conta(2023, "Prefeito", entregue_em=date(2024, 3, 1),
                                           parecer_em=date(2024, 4, 20)), date(2025, 2, 1))
    assert any("não julgadas" in a for a in atrasada.atrasos)
    assert contas.fichas([atrasada])[0].familia.value == "CTA"


def test_escada_da_lei_de_acesso():
    assert len(lai.ESCADA) == 7
    pedido = lai.Pedido("empenhos", protocolado_em=date(2026, 1, 5))
    assert lai.vencimento(pedido) == date(2026, 1, 25)
    assert lai.proximo_passo(pedido, date(2026, 1, 10))["situacao"] == "no prazo"
    passo = lai.proximo_passo(pedido, date(2026, 1, 26))
    assert passo["proximo"].startswith("Recurso à Comissão Mista")
    assert passo["agir_ate"] == "2026-02-04"
    assert passo["mandado_de_seguranca_ate"] == "2026-05-25"
    pedido.prorrogado = True
    assert lai.vencimento(pedido) == date(2026, 2, 4)


def test_oficio_pronto_com_os_dois_pedidos():
    a = Ausencia("Empenhos de março", "empenho e pagamento", "Portal da Transparência",
                 periodo="2026-03", orgao="Controladoria Geral do Município de Goiânia")
    [oficio] = lai.oficios_por_orgao([a], "Documentos não publicados")
    texto = oficio.texto(hoje=date(2026, 11, 26))
    assert "transparência ativa" in texto and "meio eletrônico" in texto
    assert "Empenhos de março (2026-03)" in texto
    assert "art. 32" in texto


def test_maquina_do_tempo_projeta_e_marca_como_projecao():
    hist = [tempo.Exercicio(2023, 100, 80), tempo.Exercicio(2024, 100, 90),
            tempo.Exercicio(2025, 100, 70), tempo.Exercicio(2022, 100, None)]
    [linha] = tempo.projetar(hist, {2027: 200})
    assert linha["tipo"] == "projeção" and linha["projetado"] == 160.0 and linha["diferenca"] == 40.0
    [curta] = tempo.projetar(hist[:1], {2027: 200})
    assert curta["projetado"] is None
