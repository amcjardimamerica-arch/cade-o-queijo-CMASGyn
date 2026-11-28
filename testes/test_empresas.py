"""Empresas contratadas: o coletor do CNPJ (base mensal e via secundária), os impedimentos e as conferências.

Tudo sem rede: a base mensal da Receita é montada aqui em zips pequenos com o layout oficial, e as APIs
respondem por leitores falsos com as respostas guardadas em ``testes/dados/empresas``.
"""

from __future__ import annotations

import io
import json
import types
import zipfile
from datetime import date
from pathlib import Path

import pytest
import yaml

from onisciente import historico
from onisciente.__main__ import main
from onisciente.coletores import base
from onisciente.coletores import cnpj as rf
from onisciente.coletores import impedimentos as imp
from onisciente.coletores import motor_cnpj
from onisciente.conferencias import empresas
from onisciente.nucleo.selos import Verificacao

DADOS = Path(__file__).parent / "dados" / "empresas"
FMAS = ("01393989000103", "FUNDO MUNICIPAL DE ASSISTENCIA SOCIAL-FMAS")
SMS = ("01234567000100", "SECRETARIA MUNICIPAL DE SAUDE")
A, B, C, D = "11111111000191", "22222222000191", "33333333000191", "44444444000191"
E, F, G, H = "55555555000191", "66666666000191", "77777777000191", "88888888000191"
I, J = "12345678000195", "87654321000198"
COMPRA_X = "01393989000103-1-000050/2025"


# --- Fixtures: a base mensal da Receita em miniatura ----------------------------------------------

def _zip(linhas: list[list[str]], nome: str = "K3241.K03200Y0.D51108.CSV") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(nome, "\n".join(";".join(f'"{c}"' for c in l) for l in linhas).encode("latin-1"))
    return buf.getvalue()


def _estab(cnpj, abertura, cnae, sec="", situacao="02", data_sit=None, logradouro="DAS FLORES", numero="10",
           complemento="", cep="74000000", tel="33334444", email=""):
    return [cnpj[:8], cnpj[8:12], cnpj[12:], "1", "FANTASIA", situacao, data_sit or abertura, "00", "", "",
            abertura, cnae, sec, "RUA", logradouro, numero, complemento, "CENTRO", cep, "GO", "9373", "62", tel,
            "", "", "", "", email, "", ""]


ARQUIVOS_BASE = {
    "Empresas0.zip": _zip([["11111111", "EMPRESA ALVO LTDA", "2062", "49", "10000,00", "01", ""],
                           ["33333333", "OUTRA QUE NAO INTERESSA LTDA", "2062", "49", "5,00", "05", ""]]),
    "Estabelecimentos0.zip": _zip([_estab(A, "20250210", "4120400", "4399103,4330404", complemento="APTO 302",
                                          email="alvo@exemplo.invalid"),
                                   _estab(C, "20000101", "4711302")]),
    "Socios0.zip": _zip([["11111111", "2", "JOÃO DA SILVA", "***123456**", "49", "20250210", "", "***000000**",
                          "", "00", "4"],
                         ["33333333", "2", "NINGUEM", "***000111**", "49", "20000101", "", "", "", "00", "5"]]),
    "Simples.zip": _zip([["11111111", "S", "20250210", "00000000", "N", "00000000", "00000000"]]),
    "Cnaes.zip": _zip([["4120400", "Construção de edifícios"], ["4711302", "Comércio varejista de mercadorias"]]),
    "Qualificacoes.zip": _zip([["49", "Sócio-Administrador"]]),
    "Motivos.zip": _zip([["00", "SEM MOTIVO"]]),
    "Naturezas.zip": _zip([["2062", "Sociedade Empresária Limitada"]]),
    "Municipios.zip": _zip([["9373", "GOIANIA"]]),
}
PROPFIND = ('<?xml version="1.0"?><d:multistatus xmlns:d="DAV:">'
            '<d:response><d:href>/public.php/webdav/Dados/Cadastros/CNPJ/</d:href></d:response>'
            '<d:response><d:href>/public.php/webdav/Dados/Cadastros/CNPJ/2026-10/</d:href></d:response>'
            '<d:response><d:href>/public.php/webdav/Dados/Cadastros/CNPJ/2026-11/</d:href></d:response>'
            '</d:multistatus>')


class Rede:
    """A porta falsa da Receita: lista as pastas e os arquivos e entrega os zips."""

    def __init__(self, arquivos=None):
        self.arquivos = dict(ARQUIVOS_BASE if arquivos is None else arquivos)
        self.baixados: list[str] = []

    def listar(self, porta, caminho=""):
        if not caminho:
            return PROPFIND, ""
        return "".join(f"<d:href>/{caminho}{n}</d:href>" for n in self.arquivos), ""

    def baixar(self, url, destino, cabecalhos=None):
        nome = url.rsplit("/", 1)[-1]
        self.baixados.append(nome)
        if nome not in self.arquivos:
            return False, 0, "HTTP 404"
        Path(destino).write_bytes(self.arquivos[nome])
        return True, len(self.arquivos[nome]), ""


PORTA = rf.Porta("webdav", "https://receita.invalid/webdav/", {}, propfind=True)


# --- Coletor do CNPJ --------------------------------------------------------------------------------

def test_cnpj_valido_numerico_e_alfanumerico():
    assert rf.cnpj_valido("16.826.800/0001-04") and rf.cnpj_valido("12.ABC.345/01DE-35")
    assert not rf.cnpj_valido("16826800000105") and not rf.cnpj_valido("11111111111111")
    assert rf.data_iso("20250210") == "2025-02-10" and rf.data_iso("00000000") is None
    assert rf.capital("10.000,50") == 10000.5


def test_meses_da_listagem_no_webdav_e_no_indice_antigo():
    assert rf.meses_da_listagem(PROPFIND) == ["2026-10", "2026-11"]
    html = '<a href="2025-05/">2025-05/</a> <a href="2025-06/">2025-06/</a> <a href="temp/">temp</a>'
    assert rf.meses_da_listagem(html) == ["2025-05", "2025-06"]
    assert rf.arquivos_da_listagem("<a href='Empresas0.zip'>x</a> <a href=\"Simples.zip\">") == [
        "Empresas0.zip", "Simples.zip"]


def test_base_mensal_filtra_em_fluxo_so_os_cnpjs_do_banco(tmp_path):
    # O leitor é um gerador: o CSV nunca é carregado inteiro.
    gerador = rf.linhas_do_zip(io.BytesIO(ARQUIVOS_BASE["Empresas0.zip"]), rf.EMPRESAS, {"11111111"})
    assert isinstance(gerador, types.GeneratorType)
    assert [l["razao"] for l in gerador] == ["EMPRESA ALVO LTDA"]
    rede = Rede()
    cad = rf.coletar_base([A, B], mes="2026-11", porta=PORTA, pasta=tmp_path, baixar_url=rede.baixar,
                          listar_url=rede.listar, hoje="2026-11-27")
    assert set(cad.empresas) == {A} and C not in cad.empresas
    e = cad.empresas[A]
    assert e["razao"] == "EMPRESA ALVO LTDA" and e["situacao"] == "ATIVA" and e["data_abertura"] == "2025-02-10"
    assert e["natureza"] == "Sociedade Empresária Limitada" and e["porte"] == "MICRO EMPRESA"
    assert e["capital_social"] == 10000.0 and e["cnae_principal"] == "4120400"
    assert e["cnaes_secundarios"] == "4399103,4330404" and e["municipio"] == "GOIANIA"
    assert e["simples"] == "S" and e["mei"] == "N" and e["telefone"] == "6233334444"
    assert e["fonte"] == rf.FONTE_BASE and e["data_base"] == "2026-11"          # selo de fonte
    assert [(s["nome"], s["cpf_cnpj"], s["qualificacao"]) for s in cad.socios] == [
        ("JOAO DA SILVA", "***123456**", "Sócio-Administrador")]
    assert cad.ausentes == {B: "não consta na base mensal da Receita"} and cad.completa
    assert cad.codigos["Cnaes"]["4120400"] == "Construção de edifícios"
    assert list(tmp_path.iterdir()) == []             # cada zip apagado depois de lido


def test_base_mensal_incompleta_nao_declara_ausente(tmp_path):
    rede = Rede({k: v for k, v in ARQUIVOS_BASE.items() if k != "Socios0.zip"})
    rede.listar = lambda porta, caminho="": ("", "HTTP 500")       # sem listagem: os nomes oficiais
    cad = rf.coletar_base([A, B], mes="2026-11", porta=PORTA, pasta=tmp_path, baixar_url=rede.baixar,
                          listar_url=rede.listar)
    assert "Socios0.zip" in rede.baixados and "Estabelecimentos9.zip" in rede.baixados
    assert not cad.completa and cad.ausentes == {} and A in cad.empresas


def test_brasilapi_vira_registro_com_selo_de_fonte():
    reg, socios = rf.de_api((DADOS / "brasilapi_exemplo.json").read_bytes(), hoje="2026-11-27")
    assert reg["cnpj"] == I and reg["razao"] == "EXEMPLO VIAGENS FICTICIAS LTDA" and reg["situacao"] == "ATIVA"
    assert reg["data_abertura"] == "2012-08-01" and reg["cnae_principal"] == "7911200"
    assert reg["cnaes_secundarios"] == "7912100,7990200" and reg["capital_social"] == 50000.0
    assert reg["simples"] == "S" and reg["mei"] == "N" and reg["porte"] == "MICRO EMPRESA"
    assert reg["fonte"] == rf.FONTE_BRASILAPI and reg["data_base"] is None and reg["consultado_em"] == "2026-11-27"
    assert socios[0]["nome"] == "FULANO DE TAL EXEMPLO" and socios[0]["cpf_cnpj"] == "***456789**"
    assert socios[0]["faixa_etaria"] == "5"
    with pytest.raises(ValueError):
        rf.de_api(b'{"message": "CNPJ 1 inv\\u00e1lido."}')


def _banco_com_contratos(tmp_path, cnpjs) -> historico.Banco:
    b = historico.Banco(tmp_path / "h.db")
    for n, ni in enumerate(cnpjs):
        _contrato(b, f"01393989000103-2-{n:06d}/2025", "2025-04-10", FMAS, ni, f"EMPRESA {n}",
                  "Gêneros alimentícios", 1000.0)
    return b


def _leitor(respostas: dict):
    chamadas = []

    def ler(url, tempo=60, cabecalhos=None, **_):
        chamadas.append(url)
        for chave, (codigo, corpo) in respostas.items():
            if chave in url:
                return base.Leitura(codigo == 200, url, corpo, http=codigo, erro="" if codigo == 200 else
                                    f"HTTP {codigo}")
        return base.Leitura(False, url, b"", http=404, erro="HTTP 404")
    ler.chamadas = chamadas
    return ler


def test_motor_cnpj_le_a_base_e_depois_so_o_incremental_pela_api(tmp_path):
    b = _banco_com_contratos(tmp_path, [A, B])
    rede = Rede()
    ler = _leitor({"brasilapi.com.br/api/cnpj/v1/" + I: (200, (DADOS / "brasilapi_exemplo.json").read_bytes())})
    ctx = historico.Contexto(b, ["2026-11"], date(2026, 11, 27), ler_url=ler, dormir=lambda s: None, pausa=0)
    r = motor_cnpj.motor_cnpj(ctx, portas=[PORTA], listar_url=rede.listar, baixar_url=rede.baixar, pasta=tmp_path)
    assert r["base"] == "2026-11" and r["da_base"] == 1 and r["da_api"] == 0 and ler.chamadas == []
    assert b.consultar("SELECT cnpj, fonte, data_base FROM cnpj_empresas") == [(A, rf.FONTE_BASE, "2026-11")]
    assert b.consultar("SELECT cnpj FROM cnpj_ausentes") == [(B,)]
    assert b.consultar("SELECT count(*) FROM coletas WHERE motor = 'cnpj' AND ok = 1")[0][0] >= 10
    # Um contrato novo com um CNPJ que a base do mês ainda não trazia: vai pela via secundária.
    _contrato(b, "01393989000103-2-000099/2025", "2025-05-10", FMAS, I, "EXEMPLO", "Passagens", 1000.0)
    rede.baixados.clear()
    r = motor_cnpj.motor_cnpj(ctx, portas=[PORTA], listar_url=rede.listar, baixar_url=rede.baixar, pasta=tmp_path)
    assert rede.baixados == [] and r["da_api"] == 1
    assert b.consultar("SELECT fonte FROM cnpj_empresas WHERE cnpj = ?", I) == [(rf.FONTE_BRASILAPI,)]
    assert b.consultar("SELECT nome FROM cnpj_socios WHERE cnpj = ?", I) == [("FULANO DE TAL EXEMPLO",)]


def test_motor_cnpj_sem_a_base_usa_a_api_e_a_reserva(tmp_path):
    b = _banco_com_contratos(tmp_path, [I])
    fora = Rede()
    fora.listar = lambda porta, caminho="": ("", "URLError: recusada")
    ler = _leitor({"brasilapi.com.br": (503, b""),
                   "minhareceita.org/" + I: (200, (DADOS / "brasilapi_exemplo.json").read_bytes())})
    ctx = historico.Contexto(b, ["2026-11"], date(2026, 11, 27), ler_url=ler, dormir=lambda s: None, pausa=0)
    r = motor_cnpj.motor_cnpj(ctx, portas=[PORTA], listar_url=fora.listar, baixar_url=fora.baixar)
    assert r["base"] is None and r["da_api"] == 1
    assert b.consultar("SELECT fonte FROM cnpj_empresas") == [(rf.FONTE_MINHARECEITA,)]
    assert b.consultar("SELECT count(*) FROM coletas WHERE motor = 'cnpj' AND ok = 0")[0][0] >= 1


# --- Impedimentos ---------------------------------------------------------------------------------

def _cepim_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("20261126_CEPIM.csv", ('"CNPJ ENTIDADE";"NOME ENTIDADE";"NÚMERO CONVÊNIO";"ÓRGÃO CONCEDENTE";'
                                         '"MOTIVO DO IMPEDIMENTO"\n"66.666.666/0001-91";"ASSOCIACAO EXEMPLO";'
                                         '"123456";"MINISTERIO EXEMPLO";"Omissão no dever de prestar contas"\n')
                   .encode("latin-1"))
    return buf.getvalue()


def test_motor_impedimentos_le_cepim_e_inidoneos_do_tcu(tmp_path):
    b = historico.Banco(tmp_path / "h.db")
    ler = _leitor({"cepim/20261125": (200, _cepim_zip()),
                   "responsaveis-inidoneos": (200, (DADOS / "tcu_inidoneos_pagina0.json").read_bytes())})
    ctx = historico.Contexto(b, ["2026-11"], date(2026, 11, 27), ler_url=ler, dormir=lambda s: None, pausa=0)
    r = motor_cnpj.motor_impedimentos(ctx)
    assert r["cepim"] == {"dia": "2026-11-25", "linhas": 1} and r["tcu"] == {"linhas": 2}
    sancoes = {(s.cadastro, s.tipo_doc, s.doc) for s in imp.ler_sancoes(b.con)}
    assert ("CEPIM", "PJ", F) in sancoes and ("TCU-INIDONEOS", "PF6", "777888") in sancoes
    assert ("TCU-INIDONEOS", "PJ", "99999999000191") in sancoes
    tcu = [s for s in imp.ler_sancoes(b.con) if s.doc == "777888"][0]
    assert tcu.inicio == "2024-01-15" and tcu.fim == "2029-01-15" and tcu.nome == "CARLOS INIDONEO"
    assert tcu.vigente_em("2025-05-10") and not tcu.vigente_em("2023-12-31")


def test_ler_sancoes_junta_a_tabela_do_ceis_e_cnep_com_a_dos_impedimentos(tmp_path):
    b = historico.Banco(tmp_path / "h.db")
    # A tabela sancoes é a da frente D1 (já no ESQUEMA do histórico desde a integração do bloco 5).
    b.con.execute("CREATE TABLE IF NOT EXISTS sancoes (cnpj_cpf TEXT, cadastro TEXT, inicio TEXT, fim TEXT, "
                  "orgao TEXT, tipo TEXT)")
    b.con.execute("INSERT INTO sancoes (cnpj_cpf, cadastro, inicio, fim, orgao, tipo) VALUES ('44.444.444/0001-91', 'CEIS', '2025-01-01', '2026-12-31', "
                  "'Prefeitura X', 'Impedimento de licitar')")
    imp.gravar(b.con, [{"cnpj_cpf": F, "cadastro": "CEPIM", "inicio": None, "fim": None, "orgao": "M",
                        "tipo": "omissão", "nome": "ASSOC", "processo": "1", "fonte": "x",
                        "data_base": "2026-11-25"}], "CEPIM")
    lidas = imp.ler_sancoes(b.con)
    assert {(s.cadastro, s.doc) for s in lidas} == {("CEIS", D), ("CEPIM", F)}
    cepim = [s for s in lidas if s.cadastro == "CEPIM"][0]
    assert cepim.vigente_em("2026-11-26") and not cepim.vigente_em("2025-01-01")


# --- Conferências: o banco de fixtures --------------------------------------------------------------

def _contrato(b, pid, data, orgao, ni, forn, objeto, valor, compra=None, processo=None, vigencia_fim=None):
    b.inserir("contratos_pncp", {"pncp_id": pid, "mes": data[:7], "data_assinatura": data, "orgao_cnpj": orgao[0],
                                 "orgao": orgao[1], "unidade": orgao[1], "fornecedor_ni": ni, "fornecedor": forn,
                                 "objeto": objeto, "valor_global": valor, "da_pasta": 1})
    b.inserir("pncp_contratos_detalhe", {"contrato_id": pid, "compra_id": compra, "valor_inicial": valor,
                                         "valor_global": valor, "processo": processo,
                                         "vigencia_inicio": data, "vigencia_fim": vigencia_fim})


def _empresa(cnpj, razao, abertura, cnae, sec="", **extra):
    reg = {"cnpj": cnpj, "cnpj_basico": cnpj[:8], "razao": razao, "situacao": "ATIVA", "data_situacao": abertura,
           "data_abertura": abertura, "porte": "DEMAIS", "capital_social": 1_000_000.0, "cnae_principal": cnae,
           "cnaes_secundarios": sec, "logradouro": f"RUA {cnpj[:3]}", "numero": "1", "complemento": "",
           "cep": "74000" + cnpj[:3], "endereco": f"RUA {cnpj[:3]}, 1", "telefone": "62" + cnpj[:8],
           "email": None, "simples": "N", "mei": "N", "fonte": rf.FONTE_BASE, "data_base": "2026-11",
           "consultado_em": "2026-11-27"}
    reg.update(extra)
    return reg


def _socio(cnpj, nome, cpf, qualificacao="Sócio-Administrador", faixa="5"):
    return {"cnpj": cnpj, "nome": nome, "cpf_cnpj": cpf, "identificador": "PESSOA FISICA",
            "qualificacao": qualificacao, "data_entrada": "2015-01-01", "representante": None,
            "representante_cpf": None, "qualificacao_representante": None, "faixa_etaria": faixa,
            "fonte": rf.FONTE_BASE, "data_base": "2026-11"}


@pytest.fixture()
def banco(tmp_path: Path):
    b = historico.Banco(tmp_path / "h.db")
    b.inserir("pncp_amparos", {"compra_id": COMPRA_X, "codigo": 6, "nome": "Pregão", "data_publicacao": "2025-03-01"})
    # A: aberta 2 meses antes da assinatura (e 3 semanas antes da publicação), CNAE de obra para alimentos,
    # capital de 10 mil num contrato de 200 mil. B: concorrente na mesma compra, com sócio em comum com A.
    _contrato(b, "01393989000103-2-000001/2025", "2025-04-10", FMAS, A, "EMPRESA ALVO LTDA",
              "Aquisição de gêneros alimentícios para o CRAS", 200000.0, compra=COMPRA_X)
    _contrato(b, "01393989000103-2-000002/2025", "2025-04-10", FMAS, B, "ALIMENTOS BOM LTDA",
              "Gêneros alimentícios, lote 2", 150000.0, compra=COMPRA_X)
    _contrato(b, "01234567000100-2-000001/2024", "2024-12-05", SMS, B, "ALIMENTOS BOM LTDA",
              "Fornecimento de alimentação (lanches)", 30000.0)
    # C: MEI com dois contratos no ano que somam 90 mil (teto do MEI: 81 mil).
    _contrato(b, "01393989000103-2-000003/2025", "2025-03-10", FMAS, C, "C MEI", "Água mineral em garrafão",
              50000.0)
    _contrato(b, "01393989000103-2-000004/2025", "2025-06-10", FMAS, C, "C MEI", "Água mineral em garrafão",
              40000.0)
    # D: no CEIS desde janeiro e baixada desde 15/01 na data do contrato.
    _contrato(b, "01393989000103-2-000005/2025", "2025-05-10", FMAS, D, "SANCIONADA LTDA",
              "Material de limpeza", 30000.0)
    # E: sócia servidora do Município e sócio no cadastro de inidôneos do TCU.
    _contrato(b, "01393989000103-2-000006/2025", "2025-05-10", FMAS, E, "SERVIDORA COMERCIO LTDA",
              "Material de expediente", 20000.0)
    # F e G: mesmo apartamento como sede; G com a razão social trocada; F, G e I com o mesmo sócio.
    _contrato(b, "01393989000103-2-000007/2025", "2025-05-10", FMAS, F, "F COMERCIO LTDA",
              "Material de expediente", 10000.0)
    _contrato(b, "01393989000103-2-000008/2025", "2025-05-10", FMAS, G, "ANTIGA COMERCIAL LTDA",
              "Material de expediente", 10000.0)
    # I e J: mesmo telefone, revezando a limpeza da Saúde em compras diferentes; J ganhou a atividade de
    # limpeza no cadastro pouco antes.
    _contrato(b, "01234567000100-2-000002/2025", "2025-02-10", SMS, I, "LIMPA I LTDA",
              "Serviços de limpeza e higiene", 80000.0, compra="01234567000100-1-000010/2025")
    _contrato(b, "01234567000100-2-000003/2025", "2025-07-10", SMS, J, "LIMPA J LTDA",
              "Serviços de limpeza e higiene", 90000.0, compra="01234567000100-1-000020/2025")
    # H: CNPJ que a base da Receita não traz.
    _contrato(b, "01393989000103-2-000009/2025", "2025-05-10", FMAS, H, "FANTASMA LTDA", "Material de limpeza",
              5000.0)

    cad = rf.Cadastro(fonte=rf.FONTE_BASE, data_base="2026-11", completa=True)
    cad.empresas = {
        A: _empresa(A, "EMPRESA ALVO LTDA", "2025-02-10", "4120400", "4399103", capital_social=10000.0),
        B: _empresa(B, "ALIMENTOS BOM LTDA", "2015-01-01", "4639701"),
        C: _empresa(C, "C MEI", "2018-01-01", "4723700", mei="S", data_opcao_mei="2019-01-01", porte="MICRO EMPRESA",
                    capital_social=5000.0),
        D: _empresa(D, "SANCIONADA LTDA", "2010-01-01", "4649408", situacao="BAIXADA", data_situacao="2025-01-15",
                    motivo="EXTINCAO POR ENCERRAMENTO"),
        E: _empresa(E, "SERVIDORA COMERCIO LTDA", "2010-01-01", "4761003"),
        F: _empresa(F, "F COMERCIO LTDA", "2010-01-01", "4761003", logradouro="RUA DAS PALMEIRAS", numero="50",
                    complemento="APTO 302", cep="74110010", endereco="RUA DAS PALMEIRAS, 50, APTO 302"),
        G: _empresa(G, "NOVA DISTRIBUIDORA LTDA", "2010-01-01", "4761003", logradouro="RUA DAS PALMEIRAS",
                    numero="50", complemento="APTO 101", cep="74110010", endereco="RUA DAS PALMEIRAS, 50, APTO 101"),
        I: _empresa(I, "LIMPA I LTDA", "2010-01-01", "8121400", telefone="6233334444"),
        J: _empresa(J, "LIMPA J LTDA", "2010-01-01", "4120400", "8121400", telefone="6233334444"),
    }
    cad.socios = [
        _socio(A, "JOAO DA SILVA", "***123456**"), _socio(B, "JOAO DA SILVA", "***123456**"),
        _socio(E, "MARIA SERVIDORA", "***654321**"), _socio(E, "CARLOS INIDONEO", "***777888**"),
        _socio(F, "PEDRO LARANJA", "***999000**"), _socio(G, "PEDRO LARANJA", "***999000**"),
        _socio(I, "PEDRO LARANJA", "***999000**"), _socio(G, "MENINO SOCIO", "***555444**", "Sócio", faixa="2"),
    ]
    cad.ausentes = {H: "não consta na base mensal da Receita"}
    cad.codigos = {"Cnaes": {"4120400": "Construção de edifícios", "4639701": "Comércio atacadista de produtos "
                             "alimentícios em geral", "8121400": "Limpeza em prédios e em domicílios"}}
    # J: a primeira fotografia (2024-06) não tinha a atividade de limpeza; ela aparece na de 2025-05.
    antes = rf.Cadastro(empresas={J: _empresa(J, "LIMPA J LTDA", "2010-01-01", "4120400", data_base="2024-06")},
                        fonte=rf.FONTE_BASE, data_base="2024-06")
    rf.gravar(b.con, antes)
    meio = rf.Cadastro(empresas={J: _empresa(J, "LIMPA J LTDA", "2010-01-01", "4120400", "8121400",
                                             data_base="2025-05")}, fonte=rf.FONTE_BASE, data_base="2025-05")
    rf.gravar(b.con, meio)
    rf.gravar(b.con, cad)
    b.con.execute("CREATE TABLE IF NOT EXISTS sancoes (cnpj_cpf TEXT, cadastro TEXT, inicio TEXT, fim TEXT, "
                  "orgao TEXT, tipo TEXT, nome TEXT)")
    b.con.execute("INSERT INTO sancoes (cnpj_cpf, cadastro, inicio, fim, orgao, tipo, nome) VALUES (?, 'CEIS', '2025-01-01', '2026-12-31', 'Prefeitura X', "
                  "'Impedimento de licitar e contratar', 'SANCIONADA LTDA')", (D,))
    imp.gravar(b.con, [{"cnpj_cpf": "***.777.888-**", "cadastro": "TCU-INIDONEOS", "inicio": "2024-01-15",
                        "fim": "2029-01-15", "orgao": "TCU", "tipo": "inidoneidade", "nome": "CARLOS INIDONEO",
                        "processo": "TC 1", "fonte": "TCU", "data_base": "2026-11-27"}], "TCU-INIDONEOS")
    b.con.execute("CREATE TABLE servidores (nome TEXT, cpf TEXT, cargo TEXT, orgao TEXT, inicio TEXT, fim TEXT)")
    b.con.execute("INSERT INTO servidores VALUES ('MARIA SERVIDORA', '111.654.321-00', 'Assessor Especial', "
                  "'SEMASDH', '2020-01-01', NULL)")
    b.con.commit()
    return b


@pytest.fixture()
def conf(banco):
    return empresas.conferir(banco.con, hoje=date(2026, 11, 27))


def _de(conf, tipo):
    return [a for a in conf.achados if a.tipo == tipo]


def test_empresa_aberta_dois_meses_antes_tem_pouco_tempo_e_perto_da_licitacao(conf):
    pouco = [a for a in _de(conf, "pouco_tempo") if a.dados["cnpj"] == A]
    assert len(pouco) == 1 and pouco[0].dados["meses"] == 2 and pouco[0].limite == 12
    perto = [a for a in _de(conf, "perto_da_licitacao") if a.dados["cnpj"] == A]
    assert len(perto) == 1 and perto[0].dados["dias"] == 19
    assert not [a for a in _de(conf, "pouco_tempo") if a.dados["cnpj"] == B]


def test_cnae_incompativel_com_o_objeto(conf):
    inc = {a.dados["cnpj"] for a in _de(conf, "cnae_incompativel")}
    assert A in inc                     # construção civil vendendo alimentos
    assert B not in inc and I not in inc and E not in inc


def test_cnae_compativel_incluido_pouco_antes(conf):
    assert [a.dados["cnpj"] for a in _de(conf, "cnae_recente")] == [J]


def test_capital_social_abaixo_de_dez_por_cento(conf):
    assert [a.dados["cnpj"] for a in _de(conf, "capital_baixo")] == [A]


def test_socio_em_comum_em_duas_propostas_da_mesma_compra(conf):
    lig = _de(conf, "vinculo_mesma_compra")
    assert len(lig) == 1 and COMPRA_X in lig[0].chave
    assert "JOAO DA SILVA" in lig[0].descricao and set(lig[0].dados["contratos"]) == {
        "01393989000103-2-000001/2025", "01393989000103-2-000002/2025"}


def test_rodizio_e_endereco_em_comum_e_socio_laranja(conf):
    rod = {tuple(sorted(a.chave.split("-")[-2:])): a for a in _de(conf, "rodizio")}
    assert set(rod) == {(I, J), (F, G)}
    assert "mesmo telefone: 6233334444" in rod[(I, J)].descricao and "PEDRO LARANJA" in rod[(F, G)].descricao
    end = _de(conf, "endereco_comum")
    assert len(end) == 1 and F in end[0].chave and G in end[0].chave and "residencial" in end[0].descricao
    assert {a.dados["cnpj"] for a in _de(conf, "endereco_residencial")} == {F, G}
    laranjas = {a.chave: a for a in _de(conf, "socio_laranja")}
    assert any("PEDRO LARANJA" in k and a.dados["empresas"] == 3 for k, a in laranjas.items())
    assert any("MENINO SOCIO" in k for k in laranjas)     # 13 a 20 anos no quadro de contratada


def test_socio_servidor_do_municipio(conf):
    serv = _de(conf, "socio_servidor")
    assert len(serv) == 1 and "MARIA SERVIDORA" in serv[0].descricao and serv[0].dados["cnpj"] == E
    assert not _de(conf, "folha_ausente")


def test_sem_folha_a_conferencia_roda_e_vira_alerta_de_transparencia(banco):
    banco.con.execute("DROP TABLE servidores")
    c = empresas.conferir(banco.con, hoje=date(2026, 11, 27))
    falta = _de(c, "folha_ausente")
    assert len(falta) == 1 and not _de(c, "socio_servidor")
    f = empresas.ficha(falta[0], "2025-06")
    assert f.verificacao is Verificacao.INCONCLUSIVO and "LAI" in f.providencia
    assert any(x.codigo.startswith("EMP-SERV00") for x in c.fichas("2025-06"))


def test_sancionada_na_data_e_socio_inidoneo(conf):
    sanc = _de(conf, "sancionada")
    assert [(a.dados["cnpj"], a.dados["cadastro"], a.dados["gravidade"]) for a in sanc] == [(D, "CEIS", "critica")]
    soc = _de(conf, "socio_sancionado")
    assert len(soc) == 1 and soc[0].dados["cnpj"] == E and "CARLOS INIDONEO" in soc[0].descricao


def test_sancao_fora_da_vigencia_nao_conta(banco):
    banco.con.execute("UPDATE sancoes SET inicio = '2026-01-01', fim = '2026-06-30'")
    c = empresas.conferir(banco.con, hoje=date(2026, 11, 27))
    assert not _de(c, "sancionada")


def test_situacao_baixada_na_data_e_cnpj_que_nao_existe(conf):
    sit = _de(conf, "situacao_irregular")
    assert [(a.dados["cnpj"], a.dados["na_data"]) for a in sit] == [(D, True)]
    assert [a.dados["cnpj"] for a in _de(conf, "cnpj_nao_encontrado")] == [H]


def test_mei_acima_do_limite_do_ano(conf):
    porte = _de(conf, "porte_acima")
    assert len(porte) == 1 and porte[0].dados["regime"] == "MEI" and porte[0].valor == 90000.0
    assert porte[0].limite == 81000.0 and len(porte[0].dados["contratos"]) == 2


def test_razao_social_trocada(conf):
    raz = _de(conf, "razao_alterada")
    assert [a.dados["cnpj"] for a in raz] == [G] and "NOVA DISTRIBUIDORA" in raz[0].descricao


def test_falta_de_experiencia_no_ramo(conf):
    sem = {a.dados["cnpj"] for a in _de(conf, "sem_experiencia")}
    assert A in sem and C in sem
    # B já tinha fornecido alimentação à Saúde antes do contrato da FMAS; o segundo contrato de C já tem o primeiro.
    assert [a.chave for a in _de(conf, "sem_experiencia") if a.dados["cnpj"] == B] == [
        "01234567000100-2-000001/2024"]
    assert [a.chave for a in _de(conf, "sem_experiencia") if a.dados["cnpj"] == C] == [
        "01393989000103-2-000003/2025"]


def test_toda_ficha_e_indicio_e_nunca_acusacao(conf):
    fichas = [empresas.ficha(a, "2025-06") for a in conf.achados]
    assert fichas and all("indício para apuração, não acusação" in f.como_esta for f in fichas)
    assert all(f.verificacao is not Verificacao.CONFIRMADO for f in fichas)
    assert {a.tipo for a in conf.achados} >= set(empresas.TITULOS) - {"folha_ausente"}


def test_limiares_versionados_com_valor_justificativa_e_base(banco):
    cfg = empresas.carregar_limiares()
    assert cfg["versao"] and len(cfg["limiares"]) >= 12
    for nome, item in cfg["limiares"].items():
        assert set(item) >= {"valor", "justificativa", "base"} and item["justificativa"] and item["base"], nome
    assert cfg["limiares"]["meses_minimos_de_funcionamento"]["valor"] >= 12
    assert cfg["limiares"]["fracao_minima_capital_social"]["valor"] == 0.10
    assert cfg["limiares"]["socios_em_comum_minimos"]["valor"] == 1
    # O código lê o arquivo: com o limiar de funcionamento em 1 mês, a empresa de 2 meses passa.
    frouxo = yaml.safe_load(empresas.LIMIARES.read_text(encoding="utf-8"))
    frouxo["limiares"]["meses_minimos_de_funcionamento"]["valor"] = 1
    c = empresas.conferir(banco.con, limiares=frouxo, hoje=date(2026, 11, 27))
    assert not _de(c, "pouco_tempo")
    for ramo in set(cfg["cnae_por_ramo"]):
        assert cfg["cnae_por_ramo"][ramo], ramo


def test_fichas_do_parecer_e_cobertura(conf, banco):
    fichas = conf.fichas("2025-06")
    codigos = {f.codigo.split("-")[0] + "-" + f.codigo.split("-")[1] for f in fichas}
    assert {"EMP-TEMPO01", "EMP-CNAE01", "EMP-LIG01", "EMP-IMP01", "EMP-SERV01", "EMP-PORTE01"} <= codigos
    rodizios = [f for f in fichas if f.codigo.startswith("EMP-LIG02")]
    assert rodizios and not any(J in f.como_esta for f in rodizios)       # o da Saúde fica fora da pasta
    assert conf.cobertura["cnpjs"] == 10 and conf.cobertura["cnpjs_com_cadastro"] == 9
    assert "CNEP" in conf.cobertura["lacunas"][0]
    assert any(f.codigo == "SIS-EMPRESAS-COBERTURA" for f in fichas)
    html = empresas.secao_parecer(conf, "2025-06")
    assert "empresas.html" in html and "Empresas ligadas na mesma compra" in html


def test_pagina_das_empresas_pelo_subcomando(banco, tmp_path):
    banco.con.commit()
    saida = tmp_path / "empresas.html"
    assert main(["empresas", "--banco", str(banco.caminho), "--saida", str(saida)]) == 0
    html = saida.read_text(encoding="utf-8")
    assert "01393989000103-2-000001/2025" in html and "JOAO DA SILVA" in html
    assert "Empresas ligadas na mesma compra" in html and "não acusação" in html
    assert "meses minimos de funcionamento" in html and "—" not in html


def test_propostas_de_requisitos_tem_trava_que_existe():
    raiz = Path(__file__).parent.parent
    itens = yaml.safe_load((raiz / "config" / "requisitos_propostas" / "f-empresas.yml").read_text(encoding="utf-8"))
    assert itens and all(i["id"] >= 200 and i["bloco"] == "Empresas contratadas" for i in itens)
    for i in itens:
        assert i["evidencia"].strip(), i["id"]
        if i["situacao"] != "cumprido":
            assert i["falta"].strip(), i["id"]
        arquivo, _, funcao = i["trava"].partition("::")
        assert f"def {funcao}(" in (raiz / arquivo).read_text(encoding="utf-8"), i["id"]


def test_sancoes_sem_linhas_sao_nao_conferidas_e_nunca_empresa_limpa(banco, tmp_path):
    banco.con.execute("DELETE FROM sancoes")
    banco.inserir("coletas", {"motor": "sancoes", "alvo": "ceis", "mes": "2026-11", "ok": 0, "http": 403,
                              "url": "https://portaldatransparencia.gov.br/download-de-dados/ceis/20261126",
                              "erro": "HTTP 403", "tentativas": 1, "segundos": 0, "bytes": 0,
                              "quando": "2026-11-27T03:00:00+00:00"})
    banco.con.commit()
    c = empresas.conferir(banco.con, hoje=date(2026, 11, 27))
    assert not _de(c, "sancionada")
    falta = c.cobertura["sancoes_nao_conferidas"]
    assert set(falta) == {"CEIS", "CNEP", "CEPIM"} and "HTTP 403" in falta["CEIS"]
    assert falta["CNEP"] == "nenhuma coleta registrada no banco"
    f = [x for x in c.fichas("2025-06") if x.codigo == "SIS-EMPRESAS-SANCOES"]
    assert len(f) == 1 and f[0].verificacao is Verificacao.INCONCLUSIVO
    assert "ausência de dado" in f[0].como_esta and "HTTP 403" in f[0].como_esta
    assert "não conferidos" in empresas.pagina(c) and "não conferidos" in empresas.secao_parecer(c, "2025-06")
