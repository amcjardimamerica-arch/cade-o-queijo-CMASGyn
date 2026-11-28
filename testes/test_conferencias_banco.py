"""As conferências sobre o banco histórico (Frente C): cada requisito com a sua trava.

Os números reais vêm de ``dados/onisciente/historico.db`` (nada de rede). As situações que o banco
não tem (registro de contas do Tribunal, alertas do Rato, protocolos) rodam em pastas temporárias.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import date

import pytest

from onisciente import RAIZ, contas, lai
from onisciente.conferencias import banco, contas_unidades, heranca, mandato, serie
from onisciente.fiscal import Leitor
from onisciente.historico import ESQUEMA
from onisciente.legal.mapa import carregar
from onisciente.nucleo import Selo, Verificacao
from onisciente.nucleo.ausencias import Ausencia
from onisciente.nucleo.indicios import Familia, emitir
from onisciente.parecer import html

BANCO = RAIZ / "dados" / "onisciente" / "historico.db"
pytestmark = pytest.mark.skipif(not BANCO.exists(), reason="banco histórico ausente")
OUT = date(2026, 10, 31)


@pytest.fixture(scope="module")
def mapa():
    return carregar()


@pytest.fixture(scope="module")
def auditoria(mapa):
    lt = Leitor(BANCO)
    try:
        return banco.conferir(lt, OUT, mapa)
    finally:
        lt.fechar()


@pytest.fixture(scope="module")
def fichas(auditoria):
    return {f.codigo: f for f in auditoria.fichas("2026-10")}


def _quadro(auditoria, inicio):
    return next(q for q in auditoria.quadros if q.titulo.startswith(inicio))


def _base(mapa, ate=OUT, raiz=RAIZ):
    return banco.Base(Leitor(BANCO), ate, mapa, raiz)


# --- Requisitos 1 e 37: cada número com fonte, selo e original --------------------------------------

def test_despesa_por_funcao_selada_conta_a_conta_com_original(auditoria):
    q = _quadro(auditoria, "A despesa por função, conta a conta")
    assert len(q.linhas) >= 15
    for linha in q.linhas:
        assert linha.selo is Selo.VERDE, linha.rotulo           # RREO Anexo 2 = matriz, conta a conta
        assert linha.valores[0] == linha.valores[1]
        assert linha.original and re.fullmatch(r"[0-9a-f]{64}", linha.original.sha256)
        assert linha.original.url.startswith("https://")


def test_toda_linha_de_quadro_tem_selo(auditoria):
    for q in auditoria.quadros:
        for linha in q.linhas:
            assert isinstance(linha.selo, Selo), (q.titulo, linha.rotulo)
    pagina = "".join(html._quadro(q) for q in auditoria.quadros)
    linhas = re.findall(r"<tr><td>(.*?)</td>", pagina)
    assert linhas and all('class="selo s-' in x for x in linhas)


def test_margens_e_leito_do_parecer_com_selo(panorama_html):
    _, pagina = panorama_html
    for rotulo in ("Espécies de receita somadas", "Receita realizada pela soma das espécies", "Empenhado e não liquidado"):  # decisão do usuário de 28/11/2026: sem a metáfora do rio
        trecho = pagina[pagina.index(rotulo) - 120:pagina.index(rotulo)]
        assert 'class="selo s-' in trecho, rotulo


# --- Requisito 65: ação genérica ----------------------------------------------------------------------

def test_acao_generica_em_duas_vias(auditoria, fichas, mapa):
    q = _quadro(auditoria, "Administração geral dentro das funções finalísticas")
    meio = set(mapa.regra("ACAO-GENERICA").get("funcoes_meio"))
    assert not any(x.rotulo[:2] in meio for x in q.linhas)
    saude = next(x for x in q.linhas if x.rotulo.startswith("10"))
    assert saude.selo is Selo.VERDE
    f = fichas["ORC-ACAO-GENERICA-2026"]
    assert f.verificacao is Verificacao.INDICIARIO and "Saúde" in f.como_esta


# --- Requisito 67: restos a pagar nunca liquidados ------------------------------------------------------

def test_restos_cancelados_sem_liquidar_e_parados(auditoria, fichas):
    q = _quadro(auditoria, "Restos a pagar não processados: inscritos")
    linha_2025 = next(x for x in q.linhas if x.rotulo == "2025")
    assert linha_2025.selo is Selo.VERDE and linha_2025.valores[1] == linha_2025.valores[2]
    assert fichas["ENT-RPNP-CANCELADOS-2025"].gravidade.value == "alta"
    parados = _quadro(auditoria, "Restos a pagar não processados ainda a liquidar")
    assert all(not x.valores[0].startswith("-") for x in parados.linhas)   # saldo a liquidar nunca negativo
    assert "ENT-RPNP-PARADOS-2026" in fichas


# --- Requisito 68: custo fixo mudando sem aditivo ------------------------------------------------------

def test_custo_fixo_que_nao_fecha_com_o_termo(fichas):
    f = fichas["PRC-CUSTOFIXO-00001727000193-2-000031/2025"]
    assert f.gravidade.value == "alta" and "347.240,00" in f.como_esta


# --- Requisito 49: fim de mandato (LRF, arts. 21 e 42) -----------------------------------------------

def test_fim_de_mandato_no_banco(fichas):
    assert "PISO-MANDATO-CAIXA-2024" in fichas and "PISO-MANDATO-PESSOAL-2024" in fichas
    assert "Recursos Não Vinculados de Impostos" in fichas["PISO-MANDATO-CAIXA-2024"].como_esta


def test_fim_de_mandato_sintetico_so_marca_a_destinacao_negativa(tmp_path, mapa):
    caminho = tmp_path / "h.db"
    con = sqlite3.connect(caminho)
    con.executescript(ESQUEMA)
    con.execute("insert into siconfi_periodos values ('RGF', 2024, 3, '3º quadrimestre', '2024-12-31', "
                "'2025-01-30', 'entregue', 3, 1, '')")
    for conta_, v in (("Recursos Livres", 1000.0), ("Saúde", -0.01), ("TOTAL GERAL", 999.99)):
        con.execute("insert into siconfi_itens values ('RGF', 2024, 3, 'RGF-Anexo 05', '', "
                    "'DISPONIBILIDADE DE CAIXA LÍQUIDA (APÓS A INSCRIÇÃO EM RESTOS A PAGAR NÃO PROCESSADOS)', "
                    "'x', ?, ?)", (conta_, v))
    con.commit()
    con.close()
    parte = mandato.conferir(banco.Base(Leitor(caminho), date(2025, 1, 31), mapa, tmp_path))
    [f] = [f for f in parte.fichas if f.codigo == "PISO-MANDATO-CAIXA-2024"]
    assert "Saúde" in f.como_esta and "Recursos Livres" not in f.como_esta


# --- Requisitos 107, 110 a 118: pessoal, benefícios e o valor devido ------------------------------------

def test_pessoal_atrasos_e_valor_devido(auditoria, fichas):
    for grupo in ("ATIVOS", "INATIVOS", "RPPS"):
        assert f"PES-ATRASO-{grupo}-2026" in fichas, grupo
    q = _quadro(auditoria, "Pessoal liquidado e não pago")
    assert "Valor devido estimado" in q.colunas
    assert any("Valor devido estimado hoje" in n for n in q.notas)


def test_aposentadorias_duas_vias_e_queda(auditoria, fichas):
    q = _quadro(auditoria, "Aposentadorias")
    assert q.linhas[0].selo is Selo.VERDE
    assert "PES-APOSENTADORIAS-QUEDA-2025" in fichas


def test_revisao_geral_fica_indiciaria_e_pede_as_tabelas(fichas, auditoria):
    for ano in (2024, 2025):
        f = fichas[f"PES-REVISAO-{ano}"]
        assert f.verificacao is Verificacao.INDICIARIO and "magistério" in f.como_esta
    assert any("Tabelas de vencimento" in a.o_que_falta for a in auditoria.ausencias)


@pytest.mark.parametrize("regra, palavra", [
    ("PISO-MAGISTERIO", "magistério"), ("QUINQUENIO", "quinquênio"), ("JETON", "jetons"),
    ("FOLHA-DIA-5", "Data de crédito"), ("PREVIDENCIA-DIA-20", "regime próprio"), ("FGTS-DIA-20", "FGTS"),
    ("VALOR-DEVIDO", "Folha de pagamento por competência")])
def test_cada_regra_da_folha_vira_pedido_ao_orgao_que_tem_a_folha(auditoria, regra, palavra):
    itens = [a for a in auditoria.ausencias if regra in a.conferencia_impedida]
    assert itens and any(palavra in a.o_que_falta for a in itens), regra
    assert all(a.orgao and a.selo is Selo.ROXO for a in itens)


def test_beneficios_dos_gestores(auditoria):
    q = _quadro(auditoria, "Benefícios dos gestores")
    assert {"Diárias", "Passagens e locomoção"} <= {x.rotulo for x in q.linhas}
    assert any(x.selo is Selo.ROXO for x in q.linhas)       # o que não está publicado aparece roxo


# --- Requisito 54: aluguel por metro quadrado ----------------------------------------------------------

def test_aluguel_por_metro_quadrado(auditoria, fichas, mapa):
    q = _quadro(auditoria, "Locações de imóveis")
    assert len(q.linhas) >= mapa.regra("ALUGUEL-M2").get("minimo_de_locacoes")
    com_area = [x for x in q.linhas if x.valores[1] != "não publicada"]
    assert len(com_area) >= 3 and all(x.valores[3].startswith("R$") for x in com_area)
    assert all(x.selo is Selo.ROXO for x in q.linhas if x not in com_area)
    assert any(c.startswith("PRC-ALUGUEL-") for c in fichas)
    assert any("laudo de avaliação" in a.o_que_falta for a in auditoria.ausencias)


# --- Requisitos 89, 100, 101, 102 e 104: contas, prazos e a família CTA ----------------------------------

def test_prazo_do_rgf_homologado_depois_vira_ficha_cta(fichas):
    f = fichas["CTA-PRAZO-RGF-2025-3"]
    assert f.familia is Familia.CTA
    assert contas.prazo_demonstrativo("RGF", 2025, 3) == date(2026, 1, 30)
    assert contas.prazo_demonstrativo("DCA", 2025, 1) == date(2026, 4, 30)


def test_conferencia_possivel_parcial_ou_impossivel():
    assert contas.conferencia_possivel({"a": True, "b": True}) == "possível"
    assert contas.conferencia_possivel({"a": True, "b": False}) == "parcial"
    assert contas.conferencia_possivel({"a": False}) == "impossível"


def test_cadastro_de_contas_de_governo_e_de_gestao(auditoria):
    q = _quadro(auditoria, "Contas de governo e de gestão")
    tipos = {x.valores[0] for x in q.linhas}
    assert tipos == {"governo", "gestão"}
    assert {x.valores[-1] for x in q.linhas} <= {"possível", "parcial", "impossível"}
    nomes = " ".join(x.rotulo for x in q.linhas).upper()
    assert "FUNDO" in nomes and ("INSTITUTO" in nomes or "AGENCIA" in nomes)
    orgaos = {a.orgao for a in auditoria.ausencias}
    assert banco.TCM in orgaos and banco.CAMARA in orgaos


def test_registro_do_tribunal_vira_ficha_de_prazo_da_lei_organica(tmp_path, mapa):
    (tmp_path / "estado").mkdir()
    (tmp_path / "estado" / "contas_tcm.json").write_text(json.dumps({"contas": [
        {"exercicio": 2024, "unidade": "Município", "entregue_em": "2025-06-30"}]}), encoding="utf-8")
    parte = contas_unidades.conferir(_base(mapa, raiz=tmp_path))
    assert any(f.familia is Familia.CTA and "2024" in f.codigo for f in parte.fichas
               if not f.codigo.startswith("CTA-PRAZO-"))
    assert not any("Datas de entrega das contas de governo e de gestão de 2024" in a.o_que_falta
                   for a in parte.ausencias)


# --- Requisitos 34, 60, 80 e 134: prestação das parcerias ---------------------------------------------

def test_prestacao_de_cada_parceria(auditoria):
    q = _quadro(auditoria, "Prestação de contas de cada parceria")
    assert q.linhas and all(len(x.valores) == 4 for x in q.linhas)
    assert any("13.019/2014" in a.fundamento and "parceria" in a.o_que_falta for a in auditoria.ausencias)


# --- Requisitos 87 e 90: Lei Orgânica (arts. 28 e 104) ------------------------------------------------

def test_lei_organica_quinquenio_e_controle_interno(auditoria):
    q = _quadro(auditoria, "Lei Orgânica de Goiânia")
    rotulos = " ".join(x.rotulo for x in q.linhas)
    assert "art. 28" in rotulos and "art. 104" in rotulos and "art. 29" in rotulos
    assert any(a.orgao == banco.CGM and "CONTROLE-INTERNO" in a.conferencia_impedida for a in auditoria.ausencias)


# --- Requisito 120: a máquina do tempo ligada ao banco ----------------------------------------------

def test_serie_do_previsto_e_do_pago_com_projecao_marcada(auditoria, mapa):
    q = _quadro(auditoria, "Máquina do tempo")
    anos = [x.rotulo for x in q.linhas]
    assert anos[:2] == ["2024", "2025"] and anos[-1] == "2026"
    assert q.linhas[-1].valores[-1].startswith("projeção (provisória")
    assert any("2023" in n for n in q.notas)                     # pede o exercício que falta
    lt = Leitor(BANCO)
    try:
        hist = serie.historico(banco.Base(lt, OUT, mapa))
    finally:
        lt.fechar()
    assert [e.ano for e in hist] == [2024, 2025]
    assert hist[1].previsto == pytest.approx(11_344_530_368.31) and hist[1].pago == pytest.approx(9_251_388_580.97)


# --- Requisitos 10 e 70: Rato e Mato ligados às fichas --------------------------------------------------

def test_rato_vira_ficha_vin_por_coincidencia_de_nome(tmp_path):
    (tmp_path / "referencias" / "vinculos").mkdir(parents=True)
    (tmp_path / "referencias" / "vinculos" / "alertas.json").write_text(json.dumps({"alertas": [
        {"tipo": "A1_HOMONIMIA_SOCIO_SERVIDOR", "socio": "FULANO DE TAL", "empresa": "EMPRESA X"}]}),
        encoding="utf-8")
    [f] = heranca.fichas_do_rato(tmp_path)
    assert f.codigo == "VIN-RATO-001" and f.familia is Familia.VIN
    assert f.verificacao is not Verificacao.CONFIRMADO        # nome igual não prova que é a mesma pessoa


def test_mato_da_caso_semelhante_que_inspira_e_nao_fundamenta():
    itens = heranca.precedentes(RAIZ)
    assert itens
    f = emitir(codigo="PRC-X", familia=Familia.PRC, titulo="Contrato com aditivo acima do limite",
               gravidade="media", como_deveria="d", norma="Lei 14.133/2021", como_esta="e", niveis=["B"])
    caso = heranca.caso_semelhante(f, itens)
    assert caso and "não fundamenta" in caso


# --- Requisitos 124 a 128: ofícios, protocolos, recurso, escada e órgão competente -----------------------

def test_orgao_competente_por_documento():
    folha = Ausencia("Folha de pagamento de março", "x", "Portal", orgao=lai.CGM)
    assert lai.orgao_competente(folha) == banco.SEMAD
    explicito = Ausencia("Folha", "x", "Portal", orgao=banco.TCM)
    assert lai.orgao_competente(explicito) == banco.TCM
    assert lai.orgao_competente(Ausencia("Algo sem palavra-chave", "x", "Portal")) == lai.CGM


def test_oficio_ao_orgao_com_copia_a_cgm_e_sem_lei_municipal_para_o_estado():
    [o] = lai.oficios_por_orgao([Ausencia("Empenhos de março", "x", "Portal", orgao=lai.CGM)], "Assunto")
    texto = o.texto(hoje=date(2026, 11, 27))
    assert o.destinatario != lai.CGM and f"Com cópia à {lai.CGM}" in texto and "9.262" in texto
    [e] = lai.oficios_por_orgao([Ausencia("Cota do ICMS", "x", "Portal",
                                          orgao="Secretaria de Estado da Economia de Goiás")], "Assunto")
    texto_e = e.texto(hoje=date(2026, 11, 27))
    assert "9.262" not in texto_e and "Lei 12.527/2011" in texto_e and "Com cópia" not in texto_e
    assert lai.esfera("Fundo Nacional de Saúde") == "federal"


def test_registro_dos_protocolos_e_recurso_pronto(tmp_path):
    caminho = tmp_path / "protocolos.json"
    pedido = lai.Pedido("Folha de março", protocolado_em=date(2026, 9, 1))
    lai.salvar_registro([pedido], caminho)
    [lido] = lai.carregar_registro(caminho)
    assert lido == pedido
    [linha] = lai.acompanhar([lido], date(2026, 11, 27))
    assert linha["situacao"] == "negado ou sem resposta"
    assert "Comissão Mista" in linha["recurso"] and "21/09/2026" in linha["recurso"]
    for degrau in (2, 3, 4, 5):
        texto = lai.texto_recurso(lido, degrau, date(2026, 11, 27))
        assert lai.ESCADA[degrau - 1].fundamento in texto and "—" not in texto
    with pytest.raises(ValueError):
        lai.texto_recurso(lido, 6)
    assert len(lai.ESCADA) == 7


def test_pagina_publica_dos_oficios(tmp_path):
    from onisciente import oficios
    rel = tmp_path / "relatorios" / "onisciente"
    rel.mkdir(parents=True)
    (rel / "panorama_2026-10.json").write_text(json.dumps({"dominio": "Assistência Social", "ausencias": [
        Ausencia("Folha de pagamento de outubro", "conferir a folha", "Portal", orgao=lai.CGM).como_dict()]}),
        encoding="utf-8")
    escritos = oficios.publicar(raiz=tmp_path, hoje=date(2026, 11, 27))
    pagina = (tmp_path / "docs" / "onisciente" / "oficios" / "oficios_2026-10.html").read_text(encoding="utf-8")
    assert banco.SEMAD in pagina and "mailto:" in pagina and "transparência ativa" in pagina
    indice = (tmp_path / "docs" / "onisciente" / "oficios" / "index.html").read_text(encoding="utf-8")
    assert "oficios_2026-10.html" in indice and len(escritos) == 2


# --- Requisito 137: custódia dos originais ------------------------------------------------------------

def test_custodia_dos_originais_do_banco(auditoria):
    motores = {m["motor"]: m for m in auditoria.custodia_por_motor}
    assert {"siconfi", "msc", "pncp"} <= set(motores)
    assert all(re.fullmatch(r"[0-9a-f]{64}", m["impressao_do_conjunto"]) for m in motores.values())
    assert auditoria.custodia and all(o.url and len(o.sha256) == 64 for o in auditoria.custodia)


# --- O parecer inteiro: quadros, ofícios, CTA, custódia e o ponto de extensão --------------------------

@pytest.fixture(scope="module")
def panorama_html():
    from onisciente.__main__ import competencias_disponiveis
    from onisciente.adaptadores import cadeoqueijo
    comp = competencias_disponiveis()[-1]
    p = cadeoqueijo.montar(comp)
    marca = lambda pan, hoje: '<h2 id="externa">Seção de teste</h2>'  # noqa: E731
    html.registrar_secao(marca)
    try:
        pagina = html.gerar(p, hoje=date(2026, 11, 27))
    finally:
        html.SECOES_EXTERNAS.remove(marca)
    return p, pagina


def test_parecer_com_quadros_oficios_custodia_e_secao_externa(panorama_html):
    p, pagina = panorama_html
    assert p.auditoria is not None and p.completo
    assert pagina.count('class="ficha ') == len(p.fichas)
    assert len({f.codigo for f in p.fichas}) == len(p.fichas)
    assert "A despesa por função, conta a conta" in pagina
    assert "Os originais das coletas do banco histórico" in pagina
    assert f'href="oficios/oficios_{p.competencia}.html"' in pagina
    assert pagina.index("9. Custódia") < pagina.index('id="externa"')
    assert not re.search(r"<(script|link)\b", pagina)
    secao6 = pagina[pagina.index("6. Prestação de contas"):pagina.index("7. Fichas")]
    assert "Demonstrativos homologados depois do prazo" in secao6
    assert all(a.selo is Selo.ROXO for a in p.ausencias)
    # completar é idempotente
    n = len(p.fichas)
    p.completar()
    assert len(p.fichas) == n


def test_familia_cta_no_parecer(panorama_html):
    p, pagina = panorama_html
    cta = [f for f in p.fichas if f.familia is Familia.CTA]
    assert cta
    secao6 = pagina[pagina.index("6. Prestação de contas"):pagina.index("7. Fichas")]
    assert all(f'href="#{f.codigo}"' in secao6 for f in cta)


# --- Ajustes pedidos pelo coordenador: prestação no índice e um único alerta sócio e servidor ------------

def test_prestacao_entra_no_indice_parceria_a_parceria(auditoria, panorama_html):
    """Requisitos 34 e 80: a prestação do índice de integridade é a fração das parcerias em dia."""
    from onisciente.conferencias.execucao import Parceria
    from onisciente.nucleo.integridade import IndiceIntegridade, com_prestacao_por_parceria, fracao_de_prestacao
    lista = [Parceria("T-1", "A", 10, prestacao_publicada=True),
             Parceria("T-2", "B", 10, prestacao_publicada=True, prestacao_individualizada=False),
             Parceria("T-3", "C", 10, prestacao_publicada=True, saldo_nao_devolvido=1.0),
             Parceria("T-4", "D", 10)]
    assert fracao_de_prestacao(lista) == 0.25 and fracao_de_prestacao([]) is None
    ind = IndiceIntegridade(cobertura=1, coerencia=1, tempestividade=1, vinculo=1, prestacao=1.0)
    novo = com_prestacao_por_parceria(ind, lista, 2026)
    assert novo.prestacao == 0.25 and novo.partes["prestacao"] == 2.5
    assert "1 de 4 parcerias de 2026" in novo.motivos["prestacao"]
    assert com_prestacao_por_parceria(ind, [], 2026) is ind
    # No banco: as parcerias medidas uma a uma chegam ao índice do panorama.
    assert auditoria.parcerias and auditoria.exercicio_das_parcerias
    p, _ = panorama_html
    assert p.integridade.prestacao == fracao_de_prestacao(auditoria.parcerias)
    assert "medidas uma a uma" in p.integridade.motivos["prestacao"]


def test_alerta_a1_do_rato_e_cruzamento_de_empresas_viram_um_so(tmp_path):
    """O mesmo sócio servidor apontado pelo Rato (A1) e pela conferência de empresas: uma ficha, duas fontes."""
    (tmp_path / "referencias" / "vinculos").mkdir(parents=True)
    (tmp_path / "referencias" / "vinculos" / "alertas.json").write_text(json.dumps({"alertas": [
        {"tipo": "A1_HOMONIMIA_SOCIO_SERVIDOR", "socio": "Fulano de Tál", "empresa": "Empresa X Ltda"},
        {"tipo": "A1_HOMONIMIA_SOCIO_SERVIDOR", "socio": "Beltrano", "empresa": "Empresa Y"}]}), encoding="utf-8")
    rato = heranca.fichas_do_rato(tmp_path)
    emp = emitir(codigo="EMP-SERV01-C1-FULANO DE TAL", familia=Familia.VIN, titulo="Sócio servidor",
                 gravidade="alta", como_deveria="d", norma="Lei 14.133/2021, art. 14, IV",
                 como_esta="FULANO DE TAL (sócio) da contratada EMPRESA X LTDA (CNPJ 1) tem o mesmo nome de servidor.",
                 niveis=["C"], por_coincidencia_de_nome=True)
    saida = heranca.unificar_socio_servidor(rato + [emp], tmp_path)
    codigos = [f.codigo for f in saida]
    assert "VIN-RATO-001" not in codigos and "VIN-RATO-002" in codigos      # Beltrano só no Rato: fica
    [unica] = [f for f in saida if f.codigo.startswith("EMP-SERV01-")]
    assert heranca.RATO in unica.como_esta and heranca.EMPRESAS in unica.como_esta and "VIN-RATO-001" in unica.como_esta
    assert unica.verificacao is not Verificacao.CONFIRMADO
    assert emp.como_esta.endswith("servidor.")                               # a ficha original não muda
    assert heranca.unificar_socio_servidor(rato, tmp_path) == rato           # sem o cruzamento, nada muda
