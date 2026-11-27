"""Bloco 5 (Frente D1): coletores federais e estaduais, os motores e as conferências, offline.

Toda leitura de rede é falsa: cada teste dá ao ``Contexto`` do historico um leitor que devolve as
respostas guardadas em ``testes/dados/federais/``. As respostas são fictícias: empresas, CNPJs,
sanções e números de acórdão inventados só para exercitar o código. Os endereços reais são confirmados pela sondagem
(chaves ``d1_`` de ``onisciente/sondagem.py``) e pela coleta no GitHub.
"""

from __future__ import annotations

import io
import zipfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from onisciente import historico
from onisciente.coletores import base, comum_federal as cf
from onisciente.coletores import economia_go, fnde, fns, motores_federais as mf, sancoes, tcm, tcu, transferegov
from onisciente.conferencias import federais
from onisciente.nucleo.selos import Selo

DADOS = Path(__file__).parent / "dados" / "federais"
ALVO = SimpleNamespace(ibge=5208707, uf="GO", municipio="Goiânia", pncp_cnpjs=())


def _bytes(nome: str) -> bytes:
    return (DADOS / nome).read_bytes()


def _zip(nome: str) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr(nome, _bytes(nome))
    return b.getvalue()


def _ok(url, conteudo: bytes) -> base.Leitura:
    return base.Leitura(True, url, conteudo, http=200)


def _nao(url, codigo=404) -> base.Leitura:
    return base.Leitura(False, url, erro=f"HTTP {codigo}", http=codigo)


def _ctx(tmp_path, leitor, meses=("2025-01", "2025-12"), hoje=date(2026, 11, 26)):
    banco = historico.Banco(tmp_path / "h.db")
    mf.preparar(banco)
    return historico.Contexto(banco, historico.meses(*meses), hoje, ler_url=leitor,
                              dormir=lambda s: None, pausa=0)


# --- Auxiliares ---------------------------------------------------------------------------------

def test_auxiliares_acham_campos_pelo_sentido():
    assert cf.numero("R$ 1.234,56") == 1234.56 and cf.numero("1234.5") == 1234.5 and cf.numero("") is None
    assert cf.data("15/10/2025") == "2025-10-15" and cf.data("2025-10-15T00:00:00") == "2025-10-15"
    assert cf.mes_de("01/2025") == "2025-01" and cf.mes_de("202502") == "2025-02"
    assert cf.campo({"valorLiquido": 3}, "valor_liquido") == 3
    assert cf.registros_json({"pagina": 1, "dados": {"content": [{"a": 1}]}}) == [{"a": 1}]


# --- FNS (requisito 146) -------------------------------------------------------------------------

def test_fns_le_repasses_pelo_sentido_dos_campos_e_pagina():
    linhas, mais = fns.ler(_bytes("fns_pagina0.json"))
    assert mais is True and len(linhas) == 2
    primeiro = linhas[0]
    assert (primeiro["data"], primeiro["mes"], primeiro["valor_liquido"], primeiro["cnpj"], primeiro["banco"],
            primeiro["agencia"], primeiro["conta"], primeiro["ordem_bancaria"]) == \
        ("2025-01-15", "2025-01", 1_000_000.0, "37623352000103", "001", "1234", "55555-1", "2025OB000123")
    assert linhas[1]["valor_bruto"] == 500_000.0 and linhas[1]["desconto"] == 20_000.0
    assert fns.ler(_bytes("fns_pagina1.json"))[1] is False
    with pytest.raises(ValueError, match="HTML"):
        fns.ler(b"<!DOCTYPE html><html>manutencao</html>")
    with pytest.raises(ValueError, match="data e valor"):
        fns.ler(b'[{"nome": "sem nada"}]')


def test_motor_fns_tenta_os_modelos_e_guarda_o_que_respondeu(tmp_path):
    pedidos = []

    def leitor(url, **_):
        pedidos.append(url)
        if url.startswith(fns.API + "v1/repasses?"):
            return _nao(url)                                      # o primeiro modelo não existe
        if url.startswith(fns.API + "repasses?"):
            pagina = parse_qs(urlparse(url).query)["pagina"][0]
            return _ok(url, _bytes("fns_pagina0.json" if pagina == "1" else "fns_pagina1.json"))
        return _nao(url)

    ctx = _ctx(tmp_path, leitor, meses=("2025-01", "2025-12"))
    mf.motor_fns(ctx, 5208707)
    assert "municipio_ibge=520870&ano=2025" in pedidos[0]
    linhas = ctx.banco.consultar("select ano, mes, valor_liquido, via from repasses_fns order by data")
    assert [l[2] for l in linhas] == [1_000_000.0, 480_000.0, 20_000.0]
    assert {l[3] for l in linhas} == {fns.MODELOS[1]}
    assert ctx.banco.consultar("select situacao, registros from fontes_federais where motor='fns'") == [("lido", 3)]


def test_motor_fns_sem_nenhum_modelo_vira_falha_do_sistema(tmp_path):
    ctx = _ctx(tmp_path, lambda url, **_: _nao(url))
    mf.motor_fns(ctx, 5208707)
    assert ctx.banco.consultar("select situacao from fontes_federais where motor='fns'") == [("nao_publicado",)]
    r = federais.conferir(ctx.banco.con, ate=date(2025, 12, 31))
    assert "fns" in r.cobertura["problemas"]
    assert any(f.codigo == "SIS-FEDERAL-FNS" for f in r.fichas("2025-12"))


# --- FNDE (requisito 147) ------------------------------------------------------------------------

def test_fnde_entidades_e_liberacoes_fecham_com_o_total():
    ents = fnde.entidades((DADOS / "fnde_entidades.html").read_text())
    assert [(e["cnpj"], e["nome"]) for e in ents] == [("01612092000123", "PREFEITURA MUNICIPAL DE GOIANIA"),
                                                     ("02439034000102", "CONSELHO ESCOLAR GIRASSOL")]
    libs, total = fnde.liberacoes((DADOS / "fnde_liberacoes_prefeitura.html").read_text())
    assert total == 1_353_368.0 and sum(l["valor"] for l in libs) == total
    assert [l["programa"][:5] for l in libs] == ["PNAE ", "PNAE ", "PNATE"]
    with pytest.raises(ValueError, match="não fecha"):
        fnde.liberacoes((DADOS / "fnde_liberacoes_total_errado.html").read_text())


def test_motor_fnde_posta_o_formulario_e_le_cada_entidade(tmp_path):
    vistos = []

    def leitor(url, formulario=None, **_):
        vistos.append((url, formulario))
        if url == fnde.ENTIDADES:
            assert formulario == {"p_ano": "2025", "p_programa": "", "p_uf": "GO", "p_municipio": "520870",
                                  "p_tp_entidade": ""}
            return _ok(url, _bytes("fnde_entidades.html"))
        if "p_cgc=01612092000123" in url:
            return _ok(url, _bytes("fnde_liberacoes_prefeitura.html"))
        if "p_cgc=02439034000102" in url:
            return _ok(url, _bytes("fnde_liberacoes_conselho.html"))
        return _nao(url)

    ctx = _ctx(tmp_path, leitor)
    mf.motor_fnde(ctx, "GO", "520870")
    assert ctx.banco.consultar("select count(*), sum(valor) from liberacoes_fnde") == [(4, 1_379_275.0)]
    assert ctx.banco.consultar("select cnpj, total_declarado, situacao from fnde_entidades order by cnpj") == [
        ("01612092000123", 1_353_368.0, "lido"), ("02439034000102", 25_907.0, "lido")]


# --- Transferegov e emendas especiais (requisitos 150 e 48) --------------------------------------

def test_transferegov_raiz_planos_e_paginas(tmp_path):
    assert transferegov.tabelas_com_cnpj(_bytes("transferegov_raiz.json")) == {
        "plano_acao_especial": "cnpj_beneficiario_plano_acao"}
    url = transferegov.url_tabela("transferenciasespeciais", "plano_acao_especial",
                                  {"cnpj_beneficiario_plano_acao": "eq.01612092000123"})
    assert url.endswith("plano_acao_especial?cnpj_beneficiario_plano_acao=eq.01612092000123&limit=1000&offset=0")
    pedidos = []

    def leitor(url, **_):
        pedidos.append(url)
        if url == transferegov.url_raiz("transferenciasespeciais"):
            return _ok(url, _bytes("transferegov_raiz.json"))
        if "plano_acao_especial?" in url:
            return _ok(url, _bytes("transferegov_planos.json"))
        if url.endswith("/"):
            return _nao(url, 503)
        return _ok(url, b"[]")

    ctx = _ctx(tmp_path, leitor)
    mf.motor_transferegov(ctx, ["01612092000123"])
    planos = ctx.banco.consultar("select codigo, custeio, investimento, total from transferegov_planos_especiais "
                                 "order by codigo")
    assert planos == [("09032025-001", 100_000.0, 900_000.0, 1_000_000.0),
                      ("09032025-002", 400_000.0, 600_000.0, 1_000_000.0)]
    situ = dict(ctx.banco.consultar("select alvo, situacao from fontes_federais where motor='transferegov'"))
    assert situ["transferenciasespeciais"] == "lido"
    assert situ["fundoafundo"] == "vazio"           # raiz fora do ar: tabelas padrão, consultadas sem registro


def test_emendas_70_por_cento_em_capital_plano_a_plano_e_no_ano(tmp_path):
    ctx = _ctx(tmp_path, lambda url, **_: _nao(url))
    for p in transferegov.pagina(_bytes("transferegov_planos.json")):
        ctx.banco.inserir("transferegov_planos_especiais", transferegov.plano(p))
    r = federais.conferir(ctx.banco.con, ate=date(2026, 1, 31))
    tipos = [(a.tipo, a.chave) for a in r.alertas]
    # O total do ano tem 75% em capital (passa), mas o plano 002 tem 60%: alerta mesmo assim.
    assert tipos == [("emenda_capital_plano", "PLANO-09032025-002")]
    alerta = r.alertas[0]
    assert alerta.gravidade == "alta" and alerta.valor == 100_000.0 and "60.0%" in alerta.descricao
    ficha = federais.ficha(alerta, "2025-12")
    assert ficha.familia.value == "PISO" and "166-A" in ficha.norma


# --- CEIS e CNEP (requisito 153) -----------------------------------------------------------------

def test_sancoes_le_ceis_e_cnep_e_grava_a_tabela_que_a_frente_f_le(tmp_path):
    def leitor(url, **_):
        if url.endswith("/ceis/20261126"):
            return _nao(url)                                      # o arquivo do dia ainda não saiu
        if url.endswith("/ceis/20261125"):
            return _ok(url, _zip("ceis.csv"))
        if url.endswith("/cnep/20261126"):
            return _ok(url, _zip("cnep.csv"))
        return _nao(url)

    ctx = _ctx(tmp_path, leitor)
    mf.motor_sancoes(ctx)
    colunas = [c[1] for c in ctx.banco.consultar("pragma table_info(sancoes)")]
    assert colunas[:6] == ["cnpj_cpf", "cadastro", "inicio", "fim", "orgao", "tipo"]
    linhas = ctx.banco.consultar("select cnpj_cpf, cadastro, inicio, fim, arquivo from sancoes order by cnpj_cpf")
    assert ("11222333000181", "CEIS", "2025-06-01", "2027-06-01", "20261125") in linhas
    assert ("77888999000100", "CNEP", "2025-07-10", "2025-07-10", "20261126") in linhas
    assert dict(ctx.banco.consultar("select alvo, situacao from fontes_federais where motor='sancoes'")) == {
        "CEIS": "lido", "CNEP": "lido"}
    with pytest.raises(ValueError, match="cabeçalho mudou"):
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w") as z:
            z.writestr("x.csv", "A;B\n1;2\n".encode("latin-1"))
        sancoes.ler(b.getvalue(), "CEIS")


def test_contratada_sancionada_em_qualquer_dia_do_contrato(tmp_path):
    ctx = _ctx(tmp_path, lambda url, **_: _nao(url))
    for s in sancoes.ler(_zip("ceis.csv"), "CEIS") + sancoes.ler(_zip("cnep.csv"), "CNEP"):
        ctx.banco.inserir("sancoes", {**s, "arquivo": "20261126"})
    contratos = [
        # Assinado antes da sanção do Município, que começa no meio da vigência: alerta (qualquer dia).
        ("C1", "2025-05", "2025-05-21", "11222333000181", "ALFA", "2025-05-21", "2026-05-21"),
        # Outra filial (mesma raiz), sanção de 2020 já encerrada: nada.
        ("C2", "2025-05", "2025-05-23", "44555666000187", "BETA", "2025-05-23", "2026-05-23"),
        # Multa do CNEP no meio da vigência: alerta médio (não impede, mas mostra a empresa sancionada).
        ("C3", "2025-05", "2025-05-28", "77888999000100", "GAMA", None, None),
        # Sem sanção: nada.
        ("C4", "2025-05", "2025-05-28", "11111111000111", "LIMPA", "2025-05-28", "2026-05-28"),
    ]
    for pid, mes, ass, ni, nome, ini, fim in contratos:
        ctx.banco.inserir("contratos_pncp", {"pncp_id": pid, "mes": mes, "data_assinatura": ass, "orgao_cnpj": "1",
                                             "orgao": "SECRETARIA MUNICIPAL DE SAUDE", "unidade": "", "fornecedor_ni": ni,
                                             "fornecedor": nome, "objeto": "objeto", "valor_global": 1000.0,
                                             "da_pasta": 0})
        if ini:
            ctx.banco.inserir("pncp_contratos_detalhe", {"contrato_id": pid, "vigencia_inicio": ini,
                                                         "vigencia_fim": fim})
    r = federais.conferir(ctx.banco.con, ate=date(2026, 11, 26))
    sanc = {a.chave.split("-")[0]: a for a in r.alertas if a.tipo == "contratada_sancionada"}
    assert set(sanc) == {"C1", "C3"}
    assert sanc["C1"].gravidade == "media"           # assinado antes da sanção: indício, não agravado
    assert "cruza a sanção do CEIS" in sanc["C1"].descricao
    assert sanc["C3"].gravidade == "media" and "vigência presumida" in sanc["C3"].descricao
    assert r.cobertura["contratos_conferidos_com_sancoes"] == 4
    # Assinado já durante a sanção do próprio Município: alerta alto.
    ctx.banco.inserir("contratos_pncp", {"pncp_id": "C5", "mes": "2025-08", "data_assinatura": "2025-08-01",
                                         "orgao_cnpj": "1", "orgao": "X", "unidade": "", "fornecedor_ni": "11222333000181",
                                         "fornecedor": "ALFA", "objeto": "o", "valor_global": 5.0, "da_pasta": 0})
    r = federais.conferir(ctx.banco.con, ate=date(2026, 11, 26))
    c5 = [a for a in r.alertas if a.chave.startswith("C5-")]
    assert c5 and c5[0].gravidade == "alta" and "assinado durante a sanção" in c5[0].descricao


# --- Economia GO (requisitos 149 e 145) -----------------------------------------------------------

def _msc(banco, mes: str, natureza: str, valor: float) -> None:
    banco.inserir("msc_itens", {"mes": mes, "conta_contabil": "621200000", "natureza_receita": natureza,
                                "fonte_recursos": "1500", "valor": valor, "natureza_conta": "C"})


def test_economia_go_le_forma_larga_e_longa():
    larga = economia_go.ler(_bytes("economia_go_largo.csv"), "Goiânia", 2025)
    assert larga == [{"mes": "2025-01", "tributo": "ICMS", "valor": 80_000_000.0},
                     {"mes": "2025-01", "tributo": "IPVA", "valor": 40_000_000.0},
                     {"mes": "2025-02", "tributo": "ICMS", "valor": 82_000_000.0},
                     {"mes": "2025-02", "tributo": "IPVA", "valor": 20_000_000.0}]
    longa = economia_go.ler(_bytes("economia_go_longo.html"), "Goiânia", 2025)
    assert longa == [{"mes": "2025-01", "tributo": "ICMS", "valor": 64_000_000.0},
                     {"mes": "2025-01", "tributo": "IPVA", "valor": 32_000_000.0}]


def test_cota_estadual_ausente_vira_alerta_roxo_com_oficio_ao_estado(tmp_path):
    ctx = _ctx(tmp_path, lambda url, **_: _ok(url, b"<!DOCTYPE html><html>pagina sem dado</html>"),
               meses=("2025-01", "2025-02"))
    for mes in ("2025-01", "2025-02"):
        ctx.banco.inserir("msc_meses", {"mes": mes, "situacao": "entregue", "itens": 2})
        _msc(ctx.banco, mes, "17215001", 80_000_000.0)
        _msc(ctx.banco, mes, "17215101", 30_000_000.0)
    mf.motor_economia_go(ctx, "Goiânia", 5208707)
    assert ctx.banco.consultar("select situacao from fontes_federais where motor='economia_go'") == [
        ("nao_publicado",)]
    r = federais.conferir(ctx.banco.con, ate=date(2025, 3, 31))
    assert len(r.ausencias) == 1 and r.ausencias[0].selo is Selo.ROXO
    assert r.ausencias[0].orgao == economia_go.ORGAO and "162" in r.ausencias[0].fundamento
    oficio = r.oficios()[0]
    assert oficio.destinatario == economia_go.ORGAO
    assert "cota-parte do ICMS, do IPVA e do IPI-exportação" in oficio.texto(hoje=date(2026, 1, 1))
    icms = next(c for c in r.conferencias if c.titulo == "Cota-parte do ICMS de 2025")
    assert icms.certificacao.selo is Selo.AZUL and icms.certificacao.valor == 160_000_000.0   # a via do Município
    assert "economia_go" not in r.cobertura["problemas"]      # ausência do Estado não é falha do sistema


def test_cota_estadual_publicada_e_conferida_com_a_matriz(tmp_path):
    def leitor(url, **_):
        if url == economia_go.urls(2025, 5208707)[0]:
            return _ok(url, _bytes("economia_go_largo.csv"))
        return _nao(url)

    ctx = _ctx(tmp_path, leitor, meses=("2025-01", "2025-02"))
    for mes, icms, ipva in (("2025-01", 100_000_000.0, 50_000_000.0), ("2025-02", 102_500_000.0, 26_000_000.0)):
        ctx.banco.inserir("msc_meses", {"mes": mes, "situacao": "entregue", "itens": 2})
        _msc(ctx.banco, mes, "17215001", icms)
        _msc(ctx.banco, mes, "17215101", ipva)
    mf.motor_economia_go(ctx, "Goiânia", 5208707)
    r = federais.conferir(ctx.banco.con, ate=date(2025, 3, 31))
    assert not r.ausencias
    icms = next(c for c in r.conferencias if c.titulo == "Cota-parte do ICMS de 2025")
    # O Estado publica o líquido do FUNDEB (80%): 162 mi / 0,8 = 202,5 mi, igual ao registrado.
    assert icms.certificacao.selo is Selo.VERDE and "0,8" in icms.referencia
    ipva = [a for a in r.alertas if a.tipo == "cota_estadual_divergencia"]
    assert [a.chave for a in ipva] == ["IPVA-2025"]            # 60 mi / 0,8 = 75 mi contra 76 mi registrados
    assert "2025-02" in ipva[0].descricao


def test_transferencias_do_tesouro_e_do_estado_tem_cada_uma_a_sua_segunda_via():
    """Requisito 145: FPM e ITR vêm da União (Tesouro e SIAFI, conferidos na origem do rio); ICMS, IPVA e
    IPI-exportação são do Estado e têm a conferência própria (Economia GO contra a matriz), que nunca
    fica em silêncio: sem a via do Estado, alerta roxo com ofício."""
    from onisciente.rio import municipio
    from onisciente.rio.fontes import Esfera
    federais_rio = {o.natureza.entram for o in municipio.ORIGENS}
    for e in municipio.CORRENTES:
        if e.nome in ("FPM", "Cota-parte do ITR"):
            assert any(any(p.startswith(n) or n.startswith(p) for p in e.natureza.entram for n in ns)
                       for ns in federais_rio), e.nome
        if e.esfera is Esfera.ESTADUAL:
            assert e.natureza in federais.NATUREZAS_ESTADUAIS.values(), e.nome
    assert set(federais.NATUREZAS_ESTADUAIS) == {"ICMS", "IPVA", "IPI"}


# --- SUS fundo a fundo: FNS x SIAFI x RREO (requisitos 146 e 164) ---------------------------------

def _siafi(banco, mes, valor, orgao="Ministério da Saúde - Unidades com vínculo direto", acao="8585",
           favorecido="37623352000103"):
    banco.inserir("transferencias_federais", {"mes": mes, "tipo": "Legais, Voluntárias e Específicas",
                                              "tipo_favorecido": "Administração Pública", "orgao": orgao,
                                              "funcao": "", "programa": "", "acao": acao, "nome_acao": acao,
                                              "favorecido": favorecido, "nome_favorecido": "FUNDO", "valor": valor})


def test_fns_conferido_com_siafi_e_rreo_anexo_12(tmp_path):
    ctx = _ctx(tmp_path, lambda url, **_: _nao(url))
    for linha in fns.ler(_bytes("fns_pagina0.json"))[0] + fns.ler(_bytes("fns_pagina1.json"))[0]:
        ctx.banco.inserir("repasses_fns", {"ano": 2025, **linha, "via": "x"})
    _siafi(ctx.banco, "2025-01", 1_000_000.0)
    _siafi(ctx.banco, "2025-02", 480_000.0)                    # falta o investimento de 20 mil no SIAFI
    ctx.banco.inserir("externos_periodos", {"fonte": "SIOPS", "exercicio": 2025, "periodo": 1,
                                            "situacao": "homologado", "linhas": 1})
    for col, valor in enumerate((9.0, 9.0, 1_500_000.0)):
        ctx.banco.inserir("externos_itens", {"fonte": "SIOPS", "exercicio": 2025, "periodo": 1, "quadro": 8,
                                             "titulo_quadro": "RECEITAS ADICIONAIS PARA O FINANCIAMENTO DA SAÚDE",
                                             "ordem": 74, "rotulo": "Provenientes da União", "coluna": col,
                                             "valor": valor})
    r = federais.conferir(ctx.banco.con, ate=date(2025, 3, 31))
    sus = next(c for c in r.conferencias if c.titulo == "SUS fundo a fundo")
    assert [v.valor for v in sus.certificacao.vias] == [1_500_000.0, 1_480_000.0, 1_500_000.0]
    assert sus.certificacao.divergencia and "1º bimestre" in sus.referencia
    alerta = next(a for a in r.alertas if a.tipo == "fns_divergencia")
    assert alerta.valor == 20_000.0 and "2025-02" in alerta.descricao
    f = federais.ficha(alerta, "2025-02")
    assert f.verificacao.value == "CONFIRMADO"                # duas fontes de níveis distintos (A e B)


def test_fnde_conferido_com_siafi_por_programa(tmp_path):
    ctx = _ctx(tmp_path, lambda url, **_: _nao(url))
    libs, _ = fnde.liberacoes((DADOS / "fnde_liberacoes_prefeitura.html").read_text())
    for l in libs:
        ctx.banco.inserir("liberacoes_fnde", {"ano": 2025, "mes": l["data"][:7], "cnpj": "01612092000123",
                                              "entidade": "PREFEITURA", **l})
    fnde_orgao = "Fundo Nacional de Desenvolvimento da Educação"
    _siafi(ctx.banco, "2025-03", 676_440.0, orgao=fnde_orgao, acao="00PI", favorecido="01612092000123")
    _siafi(ctx.banco, "2025-04", 676_440.0, orgao=fnde_orgao, acao="00PI", favorecido="01612092000123")
    _siafi(ctx.banco, "2025-03", 400.0, orgao=fnde_orgao, acao="0969", favorecido="01612092000123")
    r = federais.conferir(ctx.banco.con, ate=date(2025, 12, 31))
    pnae = next(c for c in r.conferencias if "PNAE" in c.titulo)
    assert pnae.certificacao.selo is Selo.VERDE
    assert [a.chave for a in r.alertas if a.tipo == "fnde_divergencia"] == ["FNDE-2025-0969"]


# --- TCU e TCM-GO (requisito 154) ----------------------------------------------------------------

def test_tcu_e_tcm_leem_decisoes_sobre_goiania_e_viram_alerta(tmp_path):
    acordaos = tcu.ler(_bytes("tcu_acordaos.json"))
    assert [(a["numero"], a["sobre_goiania"]) for a in acordaos] == [("1234", 1), ("1300", 0), ("1301", 0)]
    decisoes = tcm.ler(_bytes("tcm_busca.html"))
    assert {d["chave"]: d["sobre_goiania"] for d in decisoes} == {
        "TCMGO-acordao-1234-2025": 1, "TCMGO-parecerprevio-77-2025": 1, "TCMGO-resolucao-10-2025": 0}

    def leitor(url, **_):
        if url.startswith(tcu.DADOS_ABERTOS) and "inicio=0&" in url:
            return _ok(url, _bytes("tcu_acordaos.json"))
        if url.startswith(tcu.PESQUISA):
            return _ok(url, b'{"documentos": []}')
        if url == tcm.urls("Goiânia", 1)[0]:
            return _nao(url)
        if url == tcm.urls("Goiânia", 1)[1]:
            return _ok(url, _bytes("tcm_busca.html"))
        return _ok(url, b"<html><body>sem resultado</body></html>")

    ctx = _ctx(tmp_path, leitor, meses=("2025-01", "2025-12"))
    mf.motor_tcu(ctx, "Goiânia")
    mf.motor_tcm(ctx, "Goiânia")
    guardadas = ctx.banco.consultar("select tribunal, numero from decisoes_controle order by tribunal, numero")
    assert guardadas == [("TCM-GO", "1234"), ("TCM-GO", "77"), ("TCU", "1234")]
    r = federais.conferir(ctx.banco.con, ate=date(2026, 1, 31))
    alertas = {a.chave: a for a in r.alertas if a.tipo == "decisao_controle"}
    assert set(alertas) == {"TCU-ACORDAO-COMPLETO-2600001", "TCM-GO-TCMGO-acordao-1234-2025",
                            "TCM-GO-TCMGO-parecerprevio-77-2025"}
    assert alertas["TCU-ACORDAO-COMPLETO-2600001"].gravidade == "alta"
    assert alertas["TCM-GO-TCMGO-parecerprevio-77-2025"].dados["familia"] == "CTA"
    assert alertas["TCM-GO-TCMGO-acordao-1234-2025"].dados["familia"] == "PRC"


# --- Ligação, limiares e sondagem ----------------------------------------------------------------

def test_limiares_documentados_com_valor_justificativa_e_base():
    for nome, l in federais.LIMIARES.items():
        assert l["valor"] is not None and len(l["justificativa"]) > 20 and l["base"], nome
    assert federais.LIMIARES["capital_minimo_emenda"]["valor"] == 70.0
    assert federais.LIMIARES["sancao_qualquer_dia"]["valor"] == 1


def test_motores_prontos_para_o_historico(tmp_path):
    assert set(mf.MOTORES) == set(mf.TABELAS_DO_MOTOR) == set(mf.TEMPO_DO_MOTOR) == set(mf.CICLO_DIAS)
    assert set(mf.MOTORES) <= set(historico.MOTORES)          # ligados ao historico (integração do bloco 5)
    assert set(mf.TEMPO_DO_MOTOR.items()) <= set(historico.TEMPO_DO_MOTOR.items())
    assert all(t in historico.ESQUEMA for t in ('repasses_fns', 'sancoes', 'liberacoes_fnde'))
    ctx = _ctx(tmp_path, lambda url, **_: _nao(url))
    assert set(mf.chamadas(ctx, ALVO, cnpjs=[])) == set(mf.MOTORES)
    for motor in mf.MOTORES:                     # cada motor roda sem rede e deixa a situação registrada
        mf.chamadas(ctx, ALVO, cnpjs=[])[motor]()
    feitos = {m for (m,) in ctx.banco.consultar("select distinct motor from fontes_federais")}
    assert feitos == set(mf.MOTORES)
    for tabela, filtro in [t for m in mf.MOTORES for t in mf.TABELAS_DO_MOTOR[m]]:
        ctx.banco.con.execute(f"DELETE FROM {tabela}" + (f" WHERE {filtro}" if filtro else ""))
    assert ctx.banco.consultar("select count(*) from fontes_federais") == [(0,)]


def test_sondagem_tem_os_candidatos_da_frente_d1():
    from onisciente import sondagem
    chaves = {k for k in sondagem.CANDIDATOS if k.startswith("d1_")}
    assert chaves == {"d1_fns", "d1_fnde", "d1_transferegov", "d1_sancoes", "d1_economia_go", "d1_tcu", "d1_tcm"}
