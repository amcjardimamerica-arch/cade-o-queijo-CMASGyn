"""Auditoria independente do Selo de Transparência (PNTP/Atricon): matriz, fórmula, verificadores,
provas, fundos e conselhos, saídas e o estudo da metodologia (Frente E)."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import date
from pathlib import Path

import pytest
import yaml

from onisciente import RAIZ, historico
from onisciente.nucleo.selos import Verificacao
from onisciente.selo import avaliar, fundos, relatorio
from onisciente.selo import provas as provas_mod
from onisciente.selo.avaliador import SUPLEMENTARES, combinar
from onisciente.selo.formula import calcular, fracao, indice, itens_da_leitura, nivel
from onisciente.selo.matriz import ITENS, Criterio, Matriz, carregar, escolhas
from onisciente.selo.verificadores import ler_sondagem, verificar

FIXTURES = Path(__file__).parent / "dados" / "selo" / "sondagem"
FMAS = ("01393989000103", "FUNDO MUNICIPAL DE ASSISTENCIA SOCIAL-FMAS")
SMS = ("01234567000100", "SECRETARIA MUNICIPAL DE SAUDE")
HOJE = date(2026, 11, 27)


@pytest.fixture(scope="module")
def matriz() -> Matriz:
    return carregar(2026)


def _tudo(m: Matriz, valor=True) -> dict:
    return {c.id: {i: valor for i in c.itens} for c in m.do_executivo()}


# --- Matriz -------------------------------------------------------------------------------------

def test_matriz_carrega_e_e_valida(matriz):
    assert matriz.ciclo == 2026 and matriz.problemas() == []
    met = matriz.metodologia
    assert met["pesos_exigibilidade"] == {"essencial": 2, "obrigatorio": 1.5, "recomendado": 1}
    assert met["itens"] == {"disponibilidade": 0.3, "atualidade": 0.3, "serie_historica": 0.2, "gravacao": 0.1,
                            "filtro": 0.1}
    assert met["gravacao_obrigatoria_no_ciclo"] is False
    faixas = {f["nivel"]: (f["minimo"], f["exige_essenciais"]) for f in met["faixas"]}
    assert faixas["Diamante"] == (95.0, True) and faixas["Ouro"] == (85.0, True) and faixas["Prata"] == (75.0, True)
    assert faixas["Elevado"][1] is False
    # Pesos das dimensões pela cartilha: receita, despesa e planejamento 4.
    assert {d: matriz.dimensoes[d]["peso"] for d in (3, 4, 11)} == {3: 4, 4: 4, 11: 4}
    # Cada fonte oficial com endereço e data de leitura.
    assert matriz.fontes and all(f["url"].startswith("https://") and f["lida_em"] for f in matriz.fontes)
    # Os essenciais da cartilha 2026 (4.3 passou a essencial em 2026).
    essenciais = {c.id for c in matriz.do_executivo() if c.essencial}
    assert {"1.1", "1.2", "3.1", "3.2", "4.1", "4.2", "4.3", "11.5", "11.6", "11.8", "11.9", "11.10"} <= essenciais
    assert matriz.criterio("19.4").classe == "recomendado"
    for c in matriz.criterios:
        assert c.itens and set(c.itens) <= set(ITENS) and c.base_legal


def test_totais_da_matriz_batem_com_a_cartilha_ou_viram_pendencia(matriz):
    """O que não bate com os totais oficiais fica registrado como pendência, nunca escondido."""
    for nome, tot in matriz.dados["totais_oficiais"].items():
        lista = [c for c in matriz.criterios if c.matriz == nome]
        for classe in ("essencial", "obrigatorio", "recomendado"):
            n = sum(1 for c in lista if c.classe == classe)
            if n != tot[classe]:
                assert any(nome in p and classe[:6] in p.lower() for p in matriz.pendencias), (nome, classe, n)


def test_escolhas_documentadas_tem_as_duas_leituras():
    e = escolhas()
    ids = [x["id"] for x in e]
    assert ids == [f"E{n:02d}" for n in range(1, len(ids) + 1)] and len(ids) >= 16
    for x in e:
        assert x["oficial"] and x["restritiva"] and x["justificativa"] and x["codigo"]


# --- Fórmula ------------------------------------------------------------------------------------

def _crit(cid, dim, classe, itens):
    return Criterio(cid, dim, classe, "comum", f"critério {cid}", tuple(itens), "lei")


def test_formula_reproduz_exemplo_feito_a_mao(matriz):
    """Duas dimensões, pesos 4 e 1. Na primeira, essencial (2) atendido e obrigatório (1,5) pela
    metade; na segunda, recomendado (1) zerado.
    índice = 100 x [4 x (2 x 1 + 1,5 x 0,5) / 3,5 + 1 x 0] / 5 = 62,857..."""
    cs = [_crit("1.1", 1, "essencial", ["disponibilidade", "atualidade"]),
          _crit("1.2", 1, "obrigatorio", ["disponibilidade", "atualidade"]),
          _crit("2.1", 2, "recomendado", ["disponibilidade"])]
    itens = {"1.1": {"disponibilidade": True, "atualidade": True},
             "1.2": {"disponibilidade": True, "atualidade": False},
             "2.1": {"disponibilidade": False}}
    dims = {1: {"peso": 4}, 2: {"peso": 1}}
    n = calcular(itens, cs, matriz, "oficial", otimista=False, dimensoes=dims)
    assert n.indice == 62.86 and n.nivel == "Intermediário" and n.essenciais_ok and not n.selo
    r = calcular(itens, cs, matriz, "restritiva", otimista=False, dimensoes=dims)
    assert r.indice == 62.85                                   # E13: a restritiva trunca, não arredonda


def test_itens_que_nao_se_aplicam_redistribuem_e_gravacao_fica_fora_da_oficial(matriz):
    pesos = matriz.metodologia["itens"]
    assert fracao({"disponibilidade": True, "atualidade": True}, ("disponibilidade", "atualidade"), pesos) == 1.0
    c = _crit("9.9", 9, "obrigatorio", ITENS)
    tudo_menos_gravar = {i: i != "gravacao" for i in ITENS}
    assert "gravacao" not in itens_da_leitura(c, matriz, "oficial")
    assert fracao(tudo_menos_gravar, itens_da_leitura(c, matriz, "oficial"), pesos) == 1.0
    assert fracao(tudo_menos_gravar, itens_da_leitura(c, matriz, "restritiva"), pesos) == pytest.approx(0.9)
    # Sem prova: zero na comprovada, máximo no teto.
    assert fracao({}, ("disponibilidade",), pesos) == 0.0
    assert fracao({}, ("disponibilidade",), pesos, otimista=True) == 1.0


def test_tudo_atendido_da_diamante_com_100(matriz):
    n = calcular(_tudo(matriz), matriz.do_executivo(), matriz, "oficial", otimista=False)
    assert n.indice == 100.0 and n.nivel == "Diamante" and n.selo


def test_essencial_em_falta_derruba_o_selo(matriz):
    """Índice alto com um essencial em falta não dá selo: o ente fica no nível Elevado."""
    itens = _tudo(matriz)
    itens["4.3"] = {i: (i != "disponibilidade") for i in itens["4.3"]}
    n = calcular(itens, matriz.do_executivo(), matriz, "oficial", otimista=True)
    assert n.indice >= 95 and n.nivel == "Elevado" and not n.selo and n.essenciais_em_falta == ["4.3"]
    assert nivel(96.0, False, matriz.metodologia["faixas"])["nivel"] == "Elevado"
    assert nivel(96.0, True, matriz.metodologia["faixas"])["nivel"] == "Diamante"
    assert nivel(70.0, False, matriz.metodologia["faixas"])["nivel"] == "Intermediário"


def test_essencial_na_restritiva_exige_todos_os_itens(matriz):
    """E02: na oficial basta a disponibilidade do essencial; na restritiva, todos os itens."""
    itens = _tudo(matriz)
    itens["3.1"]["atualidade"] = False
    assert calcular(itens, matriz.do_executivo(), matriz, "oficial", otimista=False).selo
    r = calcular(itens, matriz.do_executivo(), matriz, "restritiva", otimista=False)
    assert "3.1" in r.essenciais_em_falta and not r.selo


def test_indice_vazio_e_zero():
    assert indice({}, [], {}, {}) == 0.0


# --- Verificadores sobre páginas guardadas ------------------------------------------------------

def test_sondagem_guardada_e_lida_com_a_data_do_indice():
    paginas = ler_sondagem(FIXTURES)
    assert {p.arquivo for p in paginas} == {"e_portal__empenhos.txt", "e_portal__receitas.txt",
                                           "e_transweb__licitacoes.txt"}
    assert all(p.quando == date(2026, 11, 23) and p.ok for p in paginas)


def test_verificador_confere_os_cinco_itens_numa_consulta_completa(matriz):
    paginas = ler_sondagem(FIXTURES)
    for leitura in ("oficial", "restritiva"):
        itens, notas = verificar(matriz.criterio("4.3"), paginas, leitura)
        assert itens == {i: True for i in ITENS}, (leitura, itens, notas)


def test_link_presente_e_vazio_nao_vale_na_restritiva(matriz):
    """E08: o menu tem 'receita prevista e realizada', mas a página não traz o dado."""
    paginas = ler_sondagem(FIXTURES)
    of, _ = verificar(matriz.criterio("3.1"), paginas, "oficial")
    re_, notas = verificar(matriz.criterio("3.1"), paginas, "restritiva")
    assert of["disponibilidade"] is True and of["atualidade"] is False
    assert all(v is False for v in re_.values()) and any("vazio" in n for n in notas)


def test_pagina_so_com_javascript_nao_e_atendida_nem_reprovada_na_oficial(matriz):
    paginas = [p for p in ler_sondagem(FIXTURES) if p.fonte == "e_transweb"]
    of, notas = verificar(matriz.criterio("8.1"), paginas, "oficial")
    assert all(v is None for v in of.values()) and any("JavaScript" in n for n in notas)
    re_, _ = verificar(matriz.criterio("8.1"), paginas, "restritiva")
    assert re_["gravacao"] is False


def test_fonte_nao_sondada_fica_nao_verificavel(matriz):
    itens, notas = verificar(matriz.criterio("4.3"), [], "restritiva")
    assert all(v is None for v in itens.values()) and "não sondadas" in notas[0]


def test_na_restritiva_a_falta_provada_vence_a_presenca(matriz):
    c = matriz.criterio("4.3")
    ao_vivo = {i: True for i in c.itens}
    falta = provas_mod.Prova("4.3", "disponibilidade", False, "restritiva", "empenhos do FMAS não publicados", "x")
    assert all(v is False for v in combinar(c, ao_vivo, [falta], "restritiva").values())
    assert combinar(c, ao_vivo, [falta], "oficial") == ao_vivo           # a prova restritiva não vale na oficial
    sem = {i: None for i in c.itens}
    sim = provas_mod.Prova("4.3", "disponibilidade", True, "oficial", "visto", "x")
    assert combinar(c, sem, [sim], "oficial")["disponibilidade"] is True


# --- Provas sem rede: nota fiscal ausente --------------------------------------------------------

@pytest.fixture()
def banco(tmp_path: Path):
    b = historico.Banco(tmp_path / "h.db")
    for orgao in (FMAS, SMS):
        for i in range(3):
            b.inserir("contratos_pncp", {"pncp_id": f"{orgao[0]}-2-{i:06d}/2025", "mes": "2025-05",
                                         "data_assinatura": "2025-05-10", "orgao_cnpj": orgao[0], "orgao": orgao[1],
                                         "unidade": orgao[1], "fornecedor_ni": f"{i}", "fornecedor": f"F{i}",
                                         "objeto": "Serviço", "valor_global": 100000.0, "da_pasta": 0})
    lidos = [f"cobrancas {o[0]} 2025-{m:02d}" for o in (FMAS, SMS) for m in range(1, 13)]
    b.con.execute("insert or replace into meta (chave, valor) values ('pncp_detalhe_lidos', ?)", (json.dumps(lidos),))
    b.con.commit()
    yield tmp_path / "h.db"
    b.con.close()


def test_nf_ausente_entra_como_prova_de_falta_de_transparencia(banco, tmp_path):
    con = sqlite3.connect(banco)
    provas = provas_mod.do_banco(con)
    o1 = [p for p in provas if p.criterio == "O.1"]
    assert len(o1) == 1 and o1[0].valor is False and o1[0].leituras == "restritiva"
    assert o1[0].valor_em_jogo == 600000.0 and "Fundo Municipal de Assistência Social" in o1[0].descricao
    assert "R$ 300.000,00" in o1[0].descricao
    aud = avaliar(con, raiz=tmp_path, sondagem=tmp_path / "nada", hoje=HOJE)
    r = next(x for x in aud.resultados if x.criterio.id == "O.1")
    assert r.situacao("restritiva", aud.matriz) == "não atendido"
    assert r.situacao("oficial", aud.matriz) == "não verificável"   # a dimensão O não existe na oficial
    con.close()


# --- Fundo e Conselho ---------------------------------------------------------------------------

def test_fundo_e_conselho_sem_dado_viram_alerta(tmp_path):
    rep = {"total": 1000.0, "por_ano": {"2025": 1000.0}, "linhas": 1, "ultima": "2025-12"}
    sit = fundos.avaliar([], rep, [], tmp_path)
    assert {s.obrigacao.id for s in sit} == {o.id for o in fundos.OBRIGACOES}
    assert all(s.alerta and s.estado == "sem dado" for s in sit)
    ach = fundos.achados(sit, rep, "2026-11")
    tipos = {a.tipo for a in ach}
    assert tipos == {"fundo_sem_transparencia", "conselho_sem_transparencia"} and len(ach) == len(sit)
    f1 = next(a for a in ach if a.chave == "F1")
    assert f1.valor == 1000.0 and "R$ 1.000,00" in f1.descricao
    fichas = relatorio.fichas(_aud_minima(ach))
    assert all(f.verificacao is Verificacao.INCONCLUSIVO and f.observacao == "indício, não acusação" for f in fichas)
    assert {f.codigo[:8] for f in fichas} == {"PCT-FMAS", "PCT-CMAS"}


def test_ausencia_do_parecer_vira_falta_e_publicacao_vista_vira_publicado(tmp_path):
    from onisciente.selo.verificadores import Pagina
    rel = tmp_path / "relatorios" / "onisciente"
    rel.mkdir(parents=True)
    (rel / "panorama_2026-10.json").write_text(json.dumps({"competencia": "2026-10", "ausencias": [
        {"o_que_falta": "Empenhos do FMAS", "periodo": "2026-10", "onde_deveria_estar": "portal"}]}),
        encoding="utf-8")
    linhas = "".join(f"<tr><td>{i}</td></tr>" for i in range(6))
    pag = Pagina("e_cmas", "https://cmasgyn.com.br/regimento", True, 200,
                 f"<p>Regimento interno do Conselho</p><table>{linhas}</table>", HOJE)
    sit = {s.obrigacao.id: s for s in fundos.avaliar([], {}, [pag], tmp_path)}
    assert sit["F2"].estado == "em falta" and "Empenhos do FMAS" in sit["F2"].provas[0]
    assert sit["C4"].estado == "publicado" and not sit["C4"].alerta


def _aud_minima(achados):
    class A:
        pass
    a = A()
    a.achados = achados
    a.matriz = carregar(2026)
    return a


# --- Auditoria inteira, saídas e parecer --------------------------------------------------------

@pytest.fixture(scope="module")
def auditoria(tmp_path_factory):
    raiz = tmp_path_factory.mktemp("raiz")
    return avaliar(None, raiz=raiz, sondagem=FIXTURES, hoje=HOJE)


def test_auditoria_gera_quatro_notas_e_veredito(auditoria):
    assert set(auditoria.notas) == {"oficial/comprovada", "oficial/teto", "restritiva/comprovada", "restritiva/teto"}
    for n in auditoria.notas.values():
        assert 0 <= n.indice <= 100
    assert auditoria.nota("oficial", "comprovada").indice <= auditoria.nota("oficial", "teto").indice
    assert auditoria.nota("restritiva", "teto").indice <= auditoria.nota("oficial", "teto").indice + 1e-9
    v = auditoria.veredito
    assert v["oficial"] in ("confirmado", "não confirmado", "não se sustenta")
    assert v["restritiva"] in ("mantém", "cai")
    assert "—" not in v["frase"] and not re.search(r"\d\.\d{2}%", v["frase"])     # vírgula decimal
    # Sem nenhuma prova do Fundo, a dimensão O derruba o essencial O.2 na restritiva.
    assert "O.2" in auditoria.nota("restritiva", "teto").essenciais_em_falta and v["restritiva"] == "cai"
    assert {c.id for c in SUPLEMENTARES} <= {r.criterio.id for r in auditoria.resultados}


def test_pagina_e_secao_do_parecer(auditoria):
    html = relatorio.pagina(auditoria)
    assert html.startswith("<!doctype html>") and "—" not in html
    for trecho in ("Selo declarado e selo encontrado", "Critério por critério", "Fundo e Conselho Municipal",
                   "indício, não acusação", "Radar da Transparência"):
        assert trecho in html, trecho
    dados = dict(auditoria.como_dict(), fichas=[f.como_dict() for f in relatorio.fichas(auditoria)])
    secao = relatorio.secao_parecer(dados)
    assert secao.startswith('<h2 id="selo">Selo de transparência: auditoria independente</h2>')
    assert "indício, não acusação" in secao and "—" not in secao
    assert relatorio.secao_parecer(caminho=Path("/nao/existe.json")) == ""


def test_oficios_pedem_os_papeis_ao_tribunal_e_a_publicacao_a_controladoria(auditoria):
    cgm, tcm = relatorio.oficios(auditoria)
    assert "Controladoria" in cgm.destinatario and "Tribunal de Contas dos Municípios" in tcm.destinatario
    assert any("Fundo" in a.o_que_falta for a in cgm.itens)
    assert "papéis de trabalho" in tcm.itens[0].o_que_falta.lower()
    assert "—" not in cgm.texto(hoje=HOJE) + tcm.texto(hoje=HOJE)


def test_linha_de_comando_registra_o_selo():
    from onisciente.__main__ import main
    with pytest.raises(SystemExit):
        main(["selo", "--help"])


# --- Estudo e propostas -------------------------------------------------------------------------

ESTUDO = RAIZ / "docs" / "onisciente" / "selo" / "estudo_pntp.md"


def test_estudo_cobre_fontes_avaliacao_metricas_replicacao_e_falhas():
    t = ESTUDO.read_text(encoding="utf-8")
    assert "—" not in t
    for trecho in ("https://", "lida em", "autoavaliação", "validação", "garantia da qualidade", "Disponibilidade",
                   "Atualidade", "Série histórica", "Gravação", "Filtro", "essencial", "Diamante", "Elevado",
                   "Como replicar", "Onde a metodologia permite falhas e como o Onisciente valida cada uma",
                   "PNCP", "SICONFI", "MSC", "amostra", "autodeclaração", "formato aberto", "fundos", "conselhos"):
        assert trecho.lower() in t.lower(), trecho
    # Cada falha nomeia o módulo ou o critério que a valida.
    falhas = t.split("Onde a metodologia permite falhas e como o Onisciente valida cada uma", 1)[1]
    assert falhas.count("onisciente/selo/") >= 6


def test_propostas_de_requisitos_tem_trava_que_existe():
    itens = yaml.safe_load((RAIZ / "config" / "requisitos_propostas" / "e-selo.yml").read_text(encoding="utf-8"))
    ids = [i["id"] for i in itens]
    assert ids == list(range(184, 184 + len(ids)))
    nomes = set(re.findall(r"^def (test_\w+)", Path(__file__).read_text(encoding="utf-8"), re.M))
    for i in itens:
        assert i["bloco"] == "Selo de transparência (PNTP)" and i["situacao"] in ("cumprido", "parcial")
        assert i["evidencia"].strip()
        if i["situacao"] != "cumprido":
            assert i["falta"].strip()
        arquivo, _, funcao = i["trava"].partition("::")
        assert arquivo == "testes/test_selo.py" and funcao in nomes, i["trava"]
