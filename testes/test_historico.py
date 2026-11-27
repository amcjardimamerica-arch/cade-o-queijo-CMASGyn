"""Coleta histórica e diagnóstico, sem rede: as fontes respondem por um leitor falso."""

import json
import re
from datetime import date
from urllib.parse import parse_qs, urlparse

import pytest

from onisciente import diagnostico, historico
from onisciente.coletores import base


def test_meses_e_periodos():
    assert historico.meses("2024-11", "2025-02") == ["2024-11", "2024-12", "2025-01", "2025-02"]
    with pytest.raises(ValueError):
        historico.meses("2025-02", "2024-11")
    p = historico.Periodo("RREO", 2025, 6)
    assert p.meses == ["2025-11", "2025-12"] and p.prazo == date(2026, 1, 30)
    assert historico.Periodo("RGF", 2026, 2).meses[-1] == "2026-08"
    assert historico.Periodo("DCA", 2024, 1).prazo == date(2025, 4, 30)
    rotulos = [p.rotulo for p in historico.periodos_do_intervalo(
        historico.meses("2024-11", "2026-11"), date(2026, 11, 26))]
    assert "RREO 2024, 6º bimestre" in rotulos and "RREO 2024, 5º bimestre" not in rotulos
    assert "RREO 2026, 5º bimestre" in rotulos and "RREO 2026, 6º bimestre" not in rotulos
    assert "RGF 2026, 3º quadrimestre" not in rotulos and "DCA 2025" in rotulos
    assert "DCA 2026" not in rotulos


def test_anexos_guardados():
    assert historico._anexo_guardado("RREO", "RREO-Anexo 12")
    assert historico._anexo_guardado("RREO", "RREO-Anexo 08")
    assert not historico._anexo_guardado("RREO", "RREO-Anexo 07")
    assert historico._anexo_guardado("DCA", "DCA-Anexo I-E")
    assert not historico._anexo_guardado("DCA", "DCA-Anexo I-AB")


def test_planilhas_achadas_na_pagina_do_fnas():
    html = ('<a href="https://fnas.mds.gov.br/wp-content/uploads/2026/02/REPASSES_ANO_2025.xlsx">25</a>'
            "<a href='https://fnas.mds.gov.br/wp-content/uploads/2026/10/REPASSES_ANO_2026.xlsx'>26</a>")
    assert sorted(historico.planilhas_fnas(html)) == [2025, 2026]


def test_enderecos_configurados_sao_achados():
    enderecos = historico.enderecos_configurados()
    urls = {u for _, _, u, _ in enderecos}
    assert "https://fnas.mds.gov.br/extracao-dos-valores-repassados-fundo-a-fundo/" in urls
    assert not any("{" in u for u in urls)
    assert any(esp == "MORTO" for _, _, _, esp in enderecos)


# --- Uma rodada inteira com fontes falsas ------------------------------------------------

def _resposta(url):
    """Simula as APIs: o SICONFI tem o RREO e paginação; o Querido Diário tem edições; o SILEG falha."""
    u = urlparse(url)
    q = {k: v[0] for k, v in parse_qs(u.query).items()}
    if "apidatalake" in u.netloc:
        if u.path.endswith("/rreo") and q.get("an_exercicio") == "2025":
            if q.get("offset") == "0":
                return 200, {"items": [{"anexo": "RREO-Anexo 12", "conta": "ASPS", "coluna": "%",
                                        "valor": 17.5}], "hasMore": True}
            return 200, {"items": [{"anexo": "RREO-Anexo 08", "conta": "MDE", "valor": 26.1},
                                   {"anexo": "RREO-Anexo 07", "conta": "x", "valor": 1}],
                         "hasMore": False}
        return 200, {"items": [], "hasMore": False}
    if "apidatatransparencia" in u.netloc or "apidados" in u.netloc:
        return 404, None
    if "queridodiario" in u.netloc:
        if "querystring" in q:
            return 200, {"total_gazettes": 1, "gazettes": [
                {"date": q["published_since"], "edition": "1", "url": "https://x/1.pdf"}]}
        return 200, {"total_gazettes": 2, "gazettes": [
            {"date": q["published_since"], "edition": "1", "url": "https://x/1.pdf"},
            {"date": q["published_until"], "edition": "2", "url": "https://x/2.pdf"}]}
    if "sileg" in u.netloc:
        return None, "URLError: sem rota"
    if "pncp" in u.netloc:
        if "contratacoes" in u.path:
            return 200, {"data": [{"numeroControlePNCP": f"C-{q['dataInicial']}-{q['codigoModalidadeContratacao']}",
                                   "orgaoEntidade": {"cnpj": "01612092000123", "esferaId": "M",
                                                     "razaoSocial": "MUNICIPIO DE GOIANIA"},
                                   "objetoCompra": "material"}], "totalPaginas": 1}
        if q["dataInicial"].startswith("202501"):
            return 200, {"data": [{"numeroControlePNCP": "K-1", "objetoContrato":
                                   "Serviço da Secretaria de Assistência Social", "valorGlobal": 10}],
                         "totalPaginas": 1}
        return 204, None
    return 404, None


def _ler_falso(url, **_):
    codigo, corpo = _resposta(url)
    if codigo is None:
        return base.Leitura(False, url, erro=corpo)
    if codigo == 204:
        return base.Leitura(True, url, b"", http=204)
    if codigo >= 400:
        return base.Leitura(False, url, erro=f"HTTP {codigo}", http=codigo)
    texto = json.dumps(corpo).encode()
    return base.Leitura(True, url, texto, http=codigo,
                        original=base.Original(url, "2026-11-26", "0" * 64))


@pytest.fixture(scope="module")
def rodada(tmp_path_factory):
    caminho = tmp_path_factory.mktemp("hist") / "historico.db"
    banco = historico.rodar("2024-12", "2025-01", caminho=caminho, hoje=date(2026, 11, 26),
                            motores=("siconfi", "querido_diario", "sileg", "pncp"),
                            ler_url=_ler_falso, dormir=lambda s: None, pausa=0)
    yield banco
    banco.fechar()


def test_siconfi_segue_a_paginacao_e_guarda_so_os_anexos_escolhidos(rodada):
    itens = rodada.consultar("SELECT anexo, valor FROM siconfi_itens WHERE exercicio = 2025 "
                             "AND demonstrativo = 'RREO' AND periodo = 1")
    assert sorted(itens) == [("RREO-Anexo 08", 26.1), ("RREO-Anexo 12", 17.5)]
    contados = rodada.consultar("SELECT SUM(itens) FROM siconfi_anexos WHERE exercicio = 2025 "
                                "AND demonstrativo = 'RREO' AND periodo = 1")
    assert contados == [(3,)]                      # o anexo 07 é contado, não guardado
    situacoes = dict(rodada.consultar("SELECT rotulo, situacao FROM siconfi_periodos"))
    assert situacoes["RREO 2025, 1º bimestre"] == "entregue"
    assert situacoes["RREO 2024, 6º bimestre"] == "ausente"   # a API respondeu vazio e o prazo venceu


def test_cada_chamada_fica_registrada(rodada):
    motores = {m for (m,) in rodada.consultar("SELECT DISTINCT motor FROM coletas")}
    assert {"siconfi", "siconfi-antiga", "qd", "sileg", "pncp"} <= motores
    [(tentativas,)] = rodada.consultar("SELECT MAX(tentativas) FROM coletas WHERE motor = 'sileg'")
    assert tentativas == 2                          # tentou de novo antes de desistir


def test_diario_oficial_por_mes(rodada):
    qd = dict(rodada.consultar("SELECT mes, edicoes FROM diario_oficial_mes WHERE fonte = 'querido_diario'"))
    assert qd == {"2024-12": 2, "2025-01": 2}
    [(com_termos,)] = rodada.consultar("SELECT SUM(com_termos) FROM diario_oficial WHERE mes = '2025-01'")
    assert com_termos == 1
    erros = rodada.consultar("SELECT erro FROM diario_oficial_mes WHERE fonte = 'sileg'")
    assert all(e and "URLError" in e for (e,) in erros)


def test_pncp_descobre_o_orgao_e_le_os_contratos(rodada):
    orgaos = json.loads(dict(rodada.consultar("SELECT chave, valor FROM meta"))["pncp_orgaos"])
    assert "01612092000123" in orgaos
    [(n, pasta)] = rodada.consultar("SELECT COUNT(*), SUM(da_pasta) FROM contratos_pncp")
    assert (n, pasta) == (1, 1)


def test_diagnostico_separa_falha_lacuna_e_melhoria(rodada, tmp_path):
    d = diagnostico.diagnosticar(rodada)
    por_tipo = {}
    for a in d["achados"]:
        por_tipo.setdefault(a["tipo"], []).append(a["titulo"])
    assert any("SILEG" in t or "sileg" in t.lower() for t in por_tipo["falha"])
    # o coletor antigo já usa a apidatalake: as bases mortas deixam de ser falha do sistema
    assert not any("endereços que não respondem" in t for t in por_tipo["falha"])
    assert any("não estão no SICONFI" in t for t in por_tipo["lacuna"])
    assert any("contrato do Município no PNCP" in t for t in por_tipo["lacuna"])
    assert any("RREO-Anexo 8" in t for t in por_tipo["melhoria"])      # nome do anexo da educação
    assert d["cobertura"]["2025-01"]["querido_diario"] == "✓"
    assert d["cobertura"]["2025-01"]["sileg"] == "✗"
    assert d["cobertura"]["2025-01"]["pncp"] == "✓" and d["cobertura"]["2024-12"]["pncp"] == "·"
    arq_json, arq_md = diagnostico.gravar(d, tmp_path)
    texto = arq_md.read_text(encoding="utf-8")
    for titulo in ("Onde o sistema falha", "Onde a fonte respondeu sem o dado",
                   "Onde o sistema pode melhorar", "Cobertura mês a mês"):
        assert f"## {titulo}" in texto
    assert json.loads(arq_json.read_text(encoding="utf-8"))["intervalo"] == "2024-12 a 2025-01"


def test_faixas_de_meses():
    assert diagnostico._faixas(["2024-11", "2024-12", "2025-01", "2025-03"]) == \
        "2024-11 a 2025-01, 2025-03"
    assert diagnostico._faixas([]) == ""


def test_disjuntor_para_de_chamar_fonte_fora_do_ar(tmp_path):
    chamadas = []

    def fora_do_ar(url, **_):
        chamadas.append(url)
        return base.Leitura(False, url, erro="TimeoutError: timed out")
    ctx = historico.Contexto(historico.Banco(tmp_path / "h.db"), ["2025-01"], date(2026, 1, 1),
                             ler_url=fora_do_ar, dormir=lambda s: None, pausa=0, disjuntor=3)
    for n in range(10):
        ctx.ler("sileg", "x", f"https://sileg/{n}", tentativas=2)
    assert len(chamadas) == 6                     # 3 leituras de 2 tentativas, depois mais nada
    erros = [e for (e,) in ctx.banco.consultar("SELECT erro FROM coletas")]
    assert erros[3].startswith("não tentado") and len(erros) == 10
    ctx.fim_do_motor = 0                          # tempo esgotado: nem o site novo é chamado
    ctx.ler("fontes", "y", "https://outro/", disjuntor=False)
    assert len(chamadas) == 6


def test_somar_refaz_so_o_motor_pedido(tmp_path):
    caminho = tmp_path / "h.db"
    comum = dict(caminho=caminho, hoje=date(2026, 11, 26), ler_url=_ler_falso,
                 dormir=lambda s: None, pausa=0)
    historico.rodar("2025-01", "2025-01", motores=("siconfi", "querido_diario"), **comum).fechar()
    banco = historico.rodar("2025-01", "2025-01", motores=("querido_diario",), somar=True, **comum)
    assert banco.consultar("SELECT COUNT(*) FROM siconfi_periodos")[0][0] > 0   # ficou
    assert banco.consultar("SELECT COUNT(*) FROM diario_oficial_mes")[0][0] == 1  # refeito, sem dobrar
    banco.fechar()
    with pytest.raises(ValueError):
        historico.rodar("2024-01", "2025-01", motores=("sileg",), somar=True, **comum)


# --- Correções da segunda rodada ---------------------------------------------------------

def test_fnas_bloqueado_usa_o_arquivo_ja_guardado(tmp_path):
    def bloqueado(url, **_):                     # 247 bytes: página de bloqueio, não a planilha
        return base.Leitura(True, url, b"<html>" + b"x" * 241, http=200)
    banco = historico.rodar("2024-11", "2024-12", caminho=tmp_path / "h.db", motores=("fnas",),
                            hoje=date(2026, 11, 26), ler_url=bloqueado,
                            dormir=lambda s: None, pausa=0)
    erros = [e for (e,) in banco.consultar("SELECT erro FROM coletas WHERE ok = 0")]
    assert any("devolveu uma página de 247 bytes" in e for e in erros)
    assert not any("não publicada" in e for e in erros)       # bloqueio não é falta de publicação
    origens = dict(banco.consultar("SELECT origem, COUNT(*) FROM repasses_fnas GROUP BY origem"))
    assert set(origens) == {historico.ORIGEM_ARQUIVO} and origens[historico.ORIGEM_ARQUIVO] > 0
    d = diagnostico.diagnosticar(banco)
    titulos = {a["tipo"] + ": " + a["titulo"] for a in d["achados"]}
    assert "falha: O site do FNAS devolveu uma página curta no lugar do conteúdo" in titulos
    assert any(t.startswith("melhoria: Repasses de 2024") for t in titulos)
    assert d["contagens"]["repasses_fnas_arquivo"] == origens[historico.ORIGEM_ARQUIVO]
    banco.fechar()


def test_pncp_le_por_ano_e_refaz_mes_a_mes_quando_recusado(tmp_path):
    pedidos = []

    def pncp(url, **_):
        q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        pedidos.append((q.get("cnpjOrgao"), q["dataInicial"], q["dataFinal"]))
        if "contratacoes" in url:
            return base.Leitura(True, url, b"", http=204)
        if q["dataInicial"][:6] != q["dataFinal"][:6]:          # janela anual: a API recusa
            return base.Leitura(False, url, erro="HTTP 422", http=422)
        if q["dataInicial"].startswith("202502"):
            corpo = {"data": [{"numeroControlePNCP": "K-2", "dataPublicacaoPncp": "2025-02-10",
                               "objetoContrato": "Acolhimento - Assistência Social"}],
                     "totalPaginas": 1}
            return base.Leitura(True, url, json.dumps(corpo).encode(), http=200)
        if q["dataInicial"].startswith("202503"):
            return base.Leitura(False, url, erro="TimeoutError: timed out")
        return base.Leitura(True, url, b"", http=204)
    banco = historico.Banco(tmp_path / "h.db")
    ctx = historico.Contexto(banco, historico.meses("2025-01", "2025-03"), date(2026, 11, 26),
                             ler_url=pncp, dormir=lambda s: None, pausa=0)
    historico.motor_pncp(ctx, 5208707, "Goiânia", {"01393989000103": "FUNDO MUNICIPAL DE "
                                                   "ASSISTENCIA SOCIAL-FMAS"})
    contratos = [(cnpj, d1, d2) for cnpj, d1, d2 in pedidos if cnpj]
    assert contratos[0] == ("01393989000103", "20250101", "20250331")   # primeiro, o ano inteiro
    assert ("01393989000103", "20250201", "20250228") in contratos       # depois, mês a mês
    [(mes, pasta)] = banco.consultar("SELECT mes, da_pasta FROM contratos_pncp")
    assert (mes, pasta) == ("2025-02", 1)
    lidos, _ = diagnostico.meses_pncp_lidos(banco, ctx.meses)
    assert lidos == {"2025-01", "2025-02"}                  # março não respondeu
    cobertura = diagnostico.cobertura_mensal(banco, ctx.meses)
    assert [cobertura[m]["pncp"] for m in ctx.meses] == ["·", "✓", "✗"]
    achados = {a.tipo: a for a in diagnostico._pncp(banco, ctx.meses)}
    assert "1 meses" in achados["falha"].titulo and "2025-03" in achados["falha"].detalhe
    assert achados["lacuna"].detalhe.startswith("Meses: 2025-01.")      # só o mês lido e vazio


def test_pncp_conhecidos_vem_antes_da_procura_e_assistencia_primeiro(tmp_path):
    ordem = []

    def pncp(url, **_):
        q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        ordem.append("procura" if "contratacoes" in url else q["cnpjOrgao"])
        return base.Leitura(True, url, b"", http=204)
    ctx = historico.Contexto(historico.Banco(tmp_path / "h.db"), ["2025-01"], date(2026, 1, 1),
                             ler_url=pncp, dormir=lambda s: None, pausa=0)
    historico.motor_pncp(ctx, 5208707, "Goiânia", {"00000000000001": "SECRETARIA DE OBRAS",
                                                   "00000000000002": "SECRETARIA DE ASSISTENCIA SOCIAL"})
    assert ordem[:3] == ["00000000000002", "00000000000001", "procura"]


def test_leitor_repete_com_cifras_compativeis_quando_o_servidor_recusa_o_tls(monkeypatch):
    import ssl
    import urllib.error
    contextos = []

    class Resposta:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"{}"

    def abrir(pedido, timeout, context=None):
        contextos.append(context)
        if context is None:
            raise urllib.error.URLError(ssl.SSLError(1, "[SSL: SSLV3_ALERT_HANDSHAKE_FAILURE] sslv3 "
                                                        "alert handshake failure"))
        return Resposta()
    monkeypatch.setattr(base.urllib.request, "urlopen", abrir)
    leitura = base.ler("https://api.queridodiario.ok.org.br/gazettes")
    assert leitura.ok and len(contextos) == 2
    assert contextos[1].verify_mode == ssl.CERT_REQUIRED and contextos[1].check_hostname
    assert not base._aperto_de_mao_recusado("[SSL: CERTIFICATE_VERIFY_FAILED] certificate")


def test_proposta_depende_do_tipo_de_falha():
    assert "TLS" in diagnostico._proposta_de_rede("URLError: [SSL: SSLV3_ALERT_HANDSHAKE_FAILURE]")
    assert "GitHub" not in diagnostico._proposta_de_rede("URLError: [SSL: SSLV3_ALERT_HANDSHAKE_FAILURE]")
    assert "tempo" in diagnostico._proposta_de_rede("TimeoutError: timed out")


def test_anexo_sem_par_no_siconfi_aponta_a_fonte_propria(tmp_path):
    banco = historico.Banco(tmp_path / "h.db")
    banco.inserir("siconfi_periodos", {"demonstrativo": "RREO", "exercicio": 2025, "periodo": 1,
                                       "rotulo": "RREO 2025, 1º bimestre", "situacao": "entregue"})
    banco.inserir("siconfi_anexos", {"demonstrativo": "RREO", "exercicio": 2025, "periodo": 1,
                                     "anexo": "RREO-Anexo 01", "itens": 3, "guardado": 1})
    [a] = diagnostico._siconfi(banco, {"educacao": "RREO-Anexo 8"})
    assert "SIOPE" in a.detalhe and "SIOPE" in a.proposta and "outro nome" not in a.detalhe


def test_pncp_somado_continua_de_onde_parou(tmp_path):
    """Na segunda rodada, o que já foi lido por inteiro não é pedido de novo (salvo o mês corrente)."""
    pedidos = []

    def pncp(url, **_):
        q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        pedidos.append(("procura" if "contratacoes" in url else q["cnpjOrgao"], q["dataInicial"]))
        if "contratacoes" in url:
            return base.Leitura(True, url, b"", http=204)
        corpo = {"data": [{"numeroControlePNCP": f"K-{q['cnpjOrgao']}-{q['dataInicial']}",
                           "dataPublicacaoPncp": "2026-10-05", "objetoContrato": "Obra"}],
                 "totalPaginas": 1}
        return base.Leitura(True, url, json.dumps(corpo).encode(), http=200)
    banco = historico.Banco(tmp_path / "h.db")
    ctx = historico.Contexto(banco, ["2026-10", "2026-11"], date(2026, 11, 26),
                             ler_url=pncp, dormir=lambda s: None, pausa=0)
    anterior = {"janelas": [{"cnpj": "1", "meses": ["2026-10", "2026-11"], "lida": True},
                            {"cnpj": "2", "meses": ["2026-10"], "lida": False}],
                "procura": ["2026-10", "2026-11"]}
    historico.motor_pncp(ctx, 5208707, "Goiânia", {"1": "", "2": ""}, anterior)
    assert ("1", "20261101") in pedidos and ("1", "20261001") not in pedidos  # só o mês corrente
    assert ("2", "20261001") in pedidos                                        # o que faltou
    assert [p for p in pedidos if p[0] == "procura"] and all(
        d == "20261101" for o, d in pedidos if o == "procura")
    lidos, _ = diagnostico.meses_pncp_lidos(banco, ctx.meses)
    assert lidos == {"2026-10", "2026-11"}
    assert json.loads(dict(banco.consultar("SELECT chave, valor FROM meta"))["pncp_procura"]) == [
        "2026-10", "2026-11"]


def test_pagina_do_banco_tem_os_dados_e_o_indice_liga_ela(rodada, tmp_path):
    from onisciente import painel_banco
    from onisciente.parecer import html as parecer_html
    d = diagnostico.diagnosticar(rodada)
    arquivos = painel_banco.gerar(rodada, d, tmp_path / "banco")
    assert [a.name for a in arquivos] == ["index.html", "dados.json", "contratos.json",
                                          "contratacoes.json"]
    pagina = arquivos[0].read_text(encoding="utf-8")
    assert pagina.startswith("<!doctype html>") and 'fetch("dados.json")' in pagina
    resumo = json.loads(arquivos[1].read_text(encoding="utf-8"))
    assert resumo["intervalo"] == "2024-12 a 2025-01" and resumo["meses"] == ["2024-12", "2025-01"]
    assert resumo["pncp"]["meses_completos"] == ["2024-12", "2025-01"]
    contratos = json.loads(arquivos[2].read_text(encoding="utf-8"))
    assert [c[0] for c in contratos] == ["K-1"] and contratos[0][8] == 1   # da pasta
    assert len(json.loads(arquivos[3].read_text(encoding="utf-8"))) >= 1
    assert 'href="banco/index.html"' in parecer_html.indice([], "Goiânia", banco=True)
    assert "banco/index.html" not in parecer_html.indice([], "Goiânia")


# --- Tesouro: transferências constitucionais, a segunda via do rio ------------------------

def test_tesouro_le_a_planilha_do_mes_e_guarda_so_o_municipio(tmp_path):
    pacote = {"result": {"resources": [
        {"name": "Transferencia_Mensal_Municipios_202410.csv", "url": "https://t/202410.csv"},
        {"name": "Transferencia_Mensal_Municipios_202411.csv", "url": "https://t/202411.csv"},
        {"name": "Metadados", "url": "https://t/m.pdf"}]}}
    planilha = ("Município;UF;ANO;Mês;1º Decêndio;2º Decêndio;3º Decêndio;Item transferência;"
                "Transferência;\n"
                "Goiânia;GO;2024;11;100.5;200;300;FPM;FPM;\n"
                "Goiânia;GO;2024;11;25;50;75;FPM;FUNDEB;\n"
                "Goiânia;SP;2024;11;9;9;9;FPM;FPM;\n"
                "Anápolis;GO;2024;11;1;2;3;FPM;FPM;\n").encode("latin-1")

    def leitor(url, **_):
        if "package_show" in url:
            return base.Leitura(True, url, json.dumps(pacote).encode(), http=200)
        return base.Leitura(True, url, planilha, http=200)

    banco = historico.rodar("2024-11", "2024-12", caminho=tmp_path / "h.db", motores=("tesouro",),
                            hoje=date(2026, 11, 26), ler_url=leitor, dormir=lambda s: None, pausa=0)
    linhas = banco.consultar("SELECT mes, item, destino, total FROM transferencias_tesouro ORDER BY destino")
    assert linhas == [("2024-11", "FPM", "FPM", 600.5), ("2024-11", "FPM", "FUNDEB", 150.0)]
    meses = json.loads(dict(banco.consultar("SELECT chave, valor FROM meta"))["tesouro_meses"])
    assert meses == {"lidos": ["2024-11"], "nao_publicados": ["2024-12"]}
    banco.fechar()


def test_tesouro_usa_a_busca_do_ckan_quando_o_pacote_cai(tmp_path):
    busca = {"result": {"count": 1, "results": [{"resources": [
        {"name": "Transferencia_Mensal_Municipios_202411.csv", "url": "https://t/202411.csv"}]}]}}
    planilha = ("Município;UF;ANO;Mês;1º Decêndio;2º Decêndio;3º Decêndio;Item transferência;Transferência;\n"
                "Goiânia;GO;2024;11;1;2;3;FPM;FPM;\n").encode("latin-1")
    pedidos = []

    def leitor(url, **_):
        pedidos.append(url)
        if "package_show" in url:
            return base.Leitura(False, url, erro="URLError: [Errno 104] Connection reset by peer")
        if "package_search" in url:
            return base.Leitura(True, url, json.dumps(busca).encode(), http=200)
        return base.Leitura(True, url, planilha, http=200)

    banco = historico.rodar("2024-11", "2024-11", caminho=tmp_path / "h.db", motores=("tesouro",),
                            hoje=date(2026, 11, 26), ler_url=leitor, dormir=lambda s: None, pausa=0)
    assert sum("package_show" in u for u in pedidos) == 4
    assert banco.consultar("SELECT mes, total FROM transferencias_tesouro") == [("2024-11", 6.0)]
    banco.fechar()


def test_numero_da_planilha_do_tesouro():
    assert historico._numero_br("1.234,56") == 1234.56
    assert historico._numero_br("94869121.13") == 94869121.13
    assert historico._numero_br("") == 0.0


# --- SIOPS: o demonstrativo da saúde, lido pelo formulário público -------------------------

DADOS = __import__("pathlib").Path(__file__).parent / "dados"


def test_siops_le_o_bimestre_pelo_formulario_e_guarda_linha_a_linha(tmp_path):
    escolha = (DADOS / "siops_escolha_go_2025.html").read_bytes()
    relatorio = (DADOS / "siops_goiania_2025_6bim.html").read_bytes()
    pedidos = []

    def leitor(url, formulario=None, **_):
        pedidos.append((url, formulario))
        if "consleirespfiscal" in url:
            return base.Leitura(True, url, escolha, http=200)
        if formulario and formulario["cmbPeriodo"] == "2":
            return base.Leitura(True, url, relatorio, http=200)
        return base.Leitura(True, url, "O Municipio não transmitiu".encode("latin-1"), http=200)

    banco = historico.rodar("2025-09", "2025-12", caminho=tmp_path / "h.db", motores=("siops",),
                            hoje=date(2026, 11, 26), ler_url=leitor, dormir=lambda s: None, pausa=0)
    postados = [f for _, f in pedidos if f]
    # Todos os bimestres de 2025 (o ritmo do ano é a régua do piso), mesmo com o intervalo no fim do ano.
    assert [f["cmbPeriodo"] for f in postados] == ["12", "14", "1", "18", "20", "2"]
    assert all(f["cmbMunicipio[]"] == "520870" and f["cmbUF"] == "52" for f in postados)
    periodos = banco.consultar("SELECT periodo, situacao, homologado FROM externos_periodos ORDER BY periodo")
    assert periodos == [(n, "nao_entregue", None) for n in range(1, 6)] + [(6, "homologado", "06/02/26 10:00:59")]
    pct = banco.consultar("SELECT coluna, valor FROM externos_itens WHERE rotulo LIKE 'PERCENTUAL DA RECEITA%' "
                          "ORDER BY coluna")
    assert pct == [(0, 21.54), (1, 21.33), (2, 21.23)]
    d = diagnostico.diagnosticar(banco)
    siops = [(a["tipo"], a["titulo"]) for a in d["achados"] if a["motor"] == "siops"]
    assert siops == [("lacuna", f"Saúde: {n}º bimestre de 2025 sem demonstrativo homologado no SIOPS")
                     for n in range(1, 6)]
    assert d["contagens"]["siops_bimestres"] == {"homologado": 1, "nao_entregue": 5}
    banco.fechar()


# --- SIOPE: o demonstrativo da educação (RREO Anexo 8), pelo PDF público do FNDE ------------

def test_siope_le_o_pdf_do_anexo_8_item_a_item():
    from onisciente.coletores import siope
    d = siope.ler((DADOS / "siope_goiania_2025_6bim.pdf").read_bytes())
    assert (d.exercicio, d.bimestre) == (2025, 6)
    assert len(d.itens) == 132
    assert d.item("3").valores == [6272968000.0, 6121934479.38]
    assert d.item("6.4").valores == [31179000.0, 50749514.66]
    assert d.item("15").valores[3] == 84.01
    assert d.item("18").valores[4] == 4.65
    assert d.item("29").valores == [1530483619.84, 1581461177.17, 25.83]
    assert d.item("33").valores[2] == 2068310203.86
    d1 = siope.ler((DADOS / "siope_goiania_2026_1bim.pdf").read_bytes())
    assert (d1.exercicio, d1.bimestre, d1.item("29").valores[2]) == (2026, 1, 7.5)
    assert siope.url_pdf("520870", 5, 2026).endswith("/RREO_Municipal_520870_5_2026.pdf")
    with pytest.raises(ValueError):
        siope.ler(b"<html>nada</html>")


def test_siope_guarda_o_bimestre_e_o_ftp_sem_arquivo_vira_lacuna(tmp_path):
    pdf = (DADOS / "siope_goiania_2025_6bim.pdf").read_bytes()
    pedidos = []

    def leitor(url, **_):
        pedidos.append(url)
        if url.endswith("_6_2025.pdf"):
            return base.Leitura(True, url, pdf)
        if url.endswith("_4_2025.pdf"):
            return base.Leitura(False, url, b"", erro="URLError: timed out")
        if url.endswith("_1_2025.pdf"):
            return base.Leitura(True, url, pdf)          # o PDF do 6º bimestre no lugar do 1º: formato
        return base.Leitura(False, url, b"", erro="URLError: ftp error: 550 Failed to open file.")

    banco = historico.rodar("2025-07", "2025-12", caminho=tmp_path / "h.db", motores=("siope",),
                            hoje=date(2026, 11, 26), ler_url=leitor, dormir=lambda s: None, pausa=0)
    # Todos os bimestres do exercício; a rede caída tenta 3 vezes, o 550 é resposta e não repete.
    bims = [int(u.rsplit("/", 1)[1].split("_")[3]) for u in pedidos]
    assert bims == [1, 2, 3, 4, 4, 4, 5, 6]
    periodos = banco.consultar("SELECT periodo, situacao, linhas FROM externos_periodos WHERE fonte = 'SIOPE' "
                               "ORDER BY periodo")
    assert periodos == [(1, "formato", 0), (2, "nao_entregue", 0), (3, "nao_entregue", 0), (4, "falha", 0),
                        (5, "nao_entregue", 0), (6, "homologado", 132)]
    pct = banco.consultar("SELECT coluna, valor FROM externos_itens WHERE fonte = 'SIOPE' AND rotulo LIKE '29-%' "
                          "ORDER BY coluna")
    assert pct == [(0, 1530483619.84), (1, 1581461177.17), (2, 25.83)]
    d = diagnostico.diagnosticar(banco)
    achados = [(a["tipo"], a["titulo"]) for a in d["achados"] if a["motor"] == "siope"]
    assert achados == [("falha", "Educação: 1º bimestre de 2025 não foi lido"),
                       ("lacuna", "Educação: 2º bimestre de 2025 sem demonstrativo no SIOPE"),
                       ("lacuna", "Educação: 3º bimestre de 2025 sem demonstrativo no SIOPE"),
                       ("falha", "Educação: 4º bimestre de 2025 não foi lido"),
                       ("lacuna", "Educação: 5º bimestre de 2025 sem demonstrativo no SIOPE")]
    assert d["contagens"]["siope_bimestres"] == {"falha": 1, "formato": 1, "homologado": 1, "nao_entregue": 3}
    banco.fechar()
    # O 5º bimestre de 2026 terminou em 31/10: em 26/11 o prazo de 30 dias ainda corre.
    banco = historico.rodar("2026-09", "2026-10", caminho=tmp_path / "p.db", motores=("siope",),
                            hoje=date(2026, 11, 26), ler_url=leitor, dormir=lambda s: None, pausa=0)
    assert banco.consultar("SELECT periodo, situacao FROM externos_periodos ORDER BY periodo") == [
        (1, "nao_entregue"), (2, "nao_entregue"), (3, "nao_entregue"), (4, "nao_entregue"), (5, "no_prazo")]
    d = diagnostico.diagnosticar(banco)
    assert [(a["tipo"], a["titulo"]) for a in d["achados"] if a["motor"] == "siope"][-1] == (
        "melhoria", "Educação: 5º bimestre de 2026 ainda não publicado no SIOPE")
    banco.fechar()


# --- Transferências federais: o arquivo do mês do Portal da Transparência ------------------

def _zip_transferencias(linhas: list[list[str]]) -> bytes:
    import io
    import zipfile
    cab = ["ANO / MÊS", "TIPO TRANSFERÊNCIA", "TIPO FAVORECIDO", "UF", "CÓDIGO MUNICÍPIO SIAFI", "NOME MUNICÍPIO",
           "CÓDIGO ÓRGÃO SIAFI", "NOME ÓRGÃO", "NOME FUNÇÃO", "NOME PROGRAMA", "AÇÃO", "NOME AÇÃO",
           "CÓDIGO FAVORECIDO", "NOME FAVORECIDO", "VALOR TRANSFERIDO"]
    texto = "\n".join(";".join(f'"{c}"' for c in linha) for linha in [cab, *linhas])
    saida = io.BytesIO()
    with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("202501_Transferencias.csv", texto.encode("latin-1"))
    return saida.getvalue()


def test_transferencias_federais_do_mes_so_do_municipio(tmp_path):
    fpm = ["202501", "Constitucionais e Royalties", "Administração Pública Municipal", "GO", "9373", "GOIANIA",
           "-1", "Sem informação", "Encargos especiais", "TRANSFERENCIAS", "0044",
           "TRANSFERENCIA AO FUNDO DE PARTICIPACAO DOS MUNICIPIOS - FPM", "01612092000123", "MUNICIPIO DE GOIANIA"]
    arquivo = _zip_transferencias([
        fpm + ["1000,50"], fpm + ["2000,25"],                                       # somadas
        ["202501", "Legais, Voluntárias e Específicas", "Fundo Público", "GO", "9373", "GOIÂNIA", "36000",
         "Ministério da Saúde", "Saúde", "SUS", "8585", "MEDIA E ALTA COMPLEXIDADE", "11111111000111",
         "FUNDO MUNICIPAL DE SAUDE", "500"],
        ["202501", "Constitucionais e Royalties", "Administração Pública Municipal", "GO", "9227",
         "APARECIDA DE GOIANIA", "-1", "x", "x", "x", "0044", "FPM", "1", "MUNICIPIO DE APARECIDA", "9"],
        ["202501", "Constitucionais e Royalties", "Administração Pública Municipal", "SP", "1", "GOIANIA",
         "-1", "x", "x", "x", "0044", "FPM", "1", "outro", "9"]])
    pedidos = []

    def leitor(url, **_):
        pedidos.append(url)
        if url.endswith("/202501"):
            return base.Leitura(True, url, arquivo, http=200)
        return base.Leitura(True, url, b"<!DOCTYPE html><html>sem arquivo</html>", http=200)

    banco = historico.rodar("2025-01", "2025-02", caminho=tmp_path / "h.db", motores=("transferencias",),
                            hoje=date(2026, 11, 26), ler_url=leitor, dormir=lambda s: None, pausa=0)
    assert [u.rsplit("/", 1)[1] for u in pedidos] == ["202501", "202502"]
    linhas = banco.consultar("SELECT mes, nome_acao, nome_favorecido, valor FROM transferencias_federais "
                             "ORDER BY valor DESC")
    assert linhas == [("2025-01", "TRANSFERENCIA AO FUNDO DE PARTICIPACAO DOS MUNICIPIOS - FPM",
                       "MUNICIPIO DE GOIANIA", 3000.75),
                      ("2025-01", "MEDIA E ALTA COMPLEXIDADE", "FUNDO MUNICIPAL DE SAUDE", 500.0)]
    d = diagnostico.diagnosticar(banco)
    assert ("melhoria", "O Portal da Transparência ainda não publicou 2025-02") in [
        (a["tipo"], a["titulo"]) for a in d["achados"] if a["motor"] == "transferencias"]
    assert d["contagens"]["transferencias_federais"] == (1, 3500.75)
    banco.fechar()


def test_arquivo_de_transferencias_com_cabecalho_mudado_e_formato():
    from onisciente.coletores import transparencia
    with pytest.raises(ValueError, match="não é zip"):
        transparencia.linhas_do_municipio(b"nada", "Goiânia", "GO")


def _item_msc(conta, natureza, valor, **extra):
    base_item = {"tipo_matriz": "MSCC", "cod_ibge": 5208707, "classe_conta": 6, "conta_contabil": conta,
                 "poder_orgao": "10131", "ano_fonte_recursos": 1, "fonte_recursos": "1500", "funcao": None,
                 "subfuncao": None, "exercicio": 2025, "mes_referencia": 1, "educacao_saude": None,
                 "natureza_despesa": None, "ano_inscricao": None, "natureza_receita": None,
                 "valor": valor, "natureza_conta": natureza, "tipo_valor": "period_change"}
    base_item.update(extra)
    return base_item


def test_msc_guarda_as_paginas_do_mes_e_separa_prazo_de_lacuna(tmp_path):
    import json as _json
    pagina1 = {"items": [_item_msc("621200000", "C", 100.0, natureza_receita="17115111")] * 2,
               "hasMore": True, "count": 2}
    pagina2 = {"items": [_item_msc("622130400", "C", 40.0, fonte_recursos="1600", funcao="10",
                                   subfuncao="302", natureza_despesa="33903900")], "hasMore": False, "count": 1}
    pedidos = []

    def leitor(url, **_):
        pedidos.append(url)
        mes = re.search(r"me_referencia=(\d+)", url).group(1)
        ano = re.search(r"an_referencia=(\d+)", url).group(1)
        if (ano, mes) == ("2025", "1"):
            corpo = pagina2 if "offset=2" in url else pagina1
        elif (ano, mes) == ("2025", "2"):
            corpo = {"items": [], "hasMore": False, "count": 0}       # depois do prazo: lacuna
        elif (ano, mes) == ("2026", "10"):
            corpo = {"items": [], "hasMore": False, "count": 0}       # ainda no prazo
        else:
            return base.Leitura(True, url, b"<html>erro</html>", http=200)
        return base.Leitura(True, url, _json.dumps(corpo).encode(), http=200)

    banco = historico.rodar("2025-01", "2025-03", caminho=tmp_path / "h.db", motores=("msc",),
                            hoje=date(2026, 11, 26), ler_url=leitor, dormir=lambda s: None, pausa=0)
    assert banco.consultar("SELECT mes, situacao, itens FROM msc_meses ORDER BY mes") == [
        ("2025-01", "entregue", 3), ("2025-02", "nao_entregue", 0), ("2025-03", "formato", 0)]
    assert banco.consultar("SELECT conta_contabil, fonte_recursos, funcao, natureza_receita, natureza_conta, "
                           "sum(valor) FROM msc_itens GROUP BY 1, 2, 3, 4, 5 ORDER BY 1") == [
        ("621200000", "1500", None, "17115111", "C", 200.0),
        ("622130400", "1600", "10", None, "C", 40.0)]
    assert sum("offset=2" in u for u in pedidos) == 1
    achados = {(a["tipo"], a["titulo"]) for a in diagnostico.diagnosticar(banco)["achados"] if a["motor"] == "msc"}
    assert ("lacuna", "Matriz de saldos contábeis não enviada ao SICONFI: 2025-02") in achados
    assert ("falha", "Matriz de saldos contábeis não lida: 2025-03") in achados
    banco.fechar()

    banco = historico.rodar("2026-10", "2026-10", caminho=tmp_path / "h2.db", motores=("msc",),
                            hoje=date(2026, 11, 26), ler_url=leitor, dormir=lambda s: None, pausa=0)
    assert banco.consultar("SELECT mes, situacao, prazo FROM msc_meses") == [("2026-10", "no_prazo", "2026-11-30")]
    banco.fechar()


def test_pncp_detalhe_le_amparo_itens_contrato_termos_preco_e_notas(tmp_path):
    """O motor de detalhe parte do que já está no banco e guarda cada via; a segunda rodada não repete."""
    pedidos = []
    item = {"numeroControlePNCPCompra": "04973965000111-1-000043/2024", "numeroItemPncp": 1,
            "orgaoEntidadeCnpj": "04973965000111", "descricaoResumida": "Aparelho Ar Condicionado",
            "materialOuServico": "M", "codigoClasse": 4120, "codItemCatalogo": 440744, "codigoPdm": "13768",
            "unidadeMedida": "Unidade  ", "quantidade": 9.0, "valorUnitarioEstimado": 2347.22,
            "valorTotal": 21124.98, "codFornecedor": "23528340000195", "quantidadeResultado": 9.0,
            "valorUnitarioResultado": 2116.99, "valorTotalResultado": 19052.91,
            "dataInclusaoPncp": "2024-11-12T11:22:08", "dataResultado": "2024-12-05 00:00:00.0000000"}

    def rede(url, **_):
        pedidos.append(url)
        if "2_consultarItens" in url:
            q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
            if q["dataInclusaoPncpInicial"][:7] != q["dataInclusaoPncpFinal"][:7]:
                return base.Leitura(False, url, erro="TimeoutError: timed out")   # ano inteiro: lento demais
            corpo = {"resultado": [item] if q["dataInclusaoPncpInicial"].startswith("2024-11") else [],
                     "totalPaginas": 1}
            return base.Leitura(True, url, json.dumps(corpo).encode(), http=200)
        if "/compras/2024/43" in url:
            corpo = {"amparoLegal": {"codigo": 19, "nome": "Lei 14.133/2021, Art. 75, II"}, "srp": False,
                     "valorTotalEstimado": 21124.98, "valorTotalHomologado": 19052.91}
            return base.Leitura(True, url, json.dumps(corpo).encode(), http=200)
        if url.endswith("/contratos/2024/47"):
            corpo = {"numeroControlePncpCompra": "04973965000111-1-000043/2024", "valorInicial": 100.0,
                     "valorGlobal": 140.0, "tipoContrato": {"nome": "Contrato (termo inicial)"},
                     "dataVigenciaInicio": "2024-11-19", "dataVigenciaFim": "2025-11-19"}
            return base.Leitura(True, url, json.dumps(corpo).encode(), http=200)
        if url.endswith("/contratos/2024/47/termos"):
            corpo = [{"sequencialTermoContrato": 1, "tipoTermoContratoNome": "Termo Aditivo",
                      "valorAcrescido": 40.0, "qualificacaoAcrescimoSupressao": True}]
            return base.Leitura(True, url, json.dumps(corpo).encode(), http=200)
        if "1_consultarMaterial" in url:
            assert "dataCompraInicio=2024-07-01" in url and "codigo=440744" in url
            corpo = {"resultado": [{"idCompraItem": f"X{n}", "precoUnitario": 1500.0 + n, "dataCompra": "2024-10-01",
                                    "estado": "MG"} for n in range(3)], "totalPaginas": 1}
            return base.Leitura(True, url, json.dumps(corpo).encode(), http=200)
        if "instrumentoscobranca" in url and "dataInicial=20241101" in url:
            corpo = {"data": [{"cnpj": "04973965000111", "ano": 2024, "sequencialContrato": 47,
                               "sequencialInstrumentoCobranca": 1, "tipoInstrumentoCobranca": {"nome": "Nota Fiscal"},
                               "notaFiscalEletronica": {"valorNotaFiscal": "19052.91", "itens": [
                                   {"numeroItem": "1", "descricaoProdutoServico": "AR SPLIT", "quantidade": "9",
                                    "valorUnitario": "2116.99", "valorTotal": "19052.91"}]}}],
                     "totalPaginas": 1}
            return base.Leitura(True, url, json.dumps(corpo).encode(), http=200)
        return base.Leitura(True, url, b"", http=204)

    banco = historico.Banco(tmp_path / "h.db")
    banco.inserir("contratacoes_pncp", {"pncp_id": "04973965000111-1-000043/2024", "mes": "2024-11",
                                        "modalidade": "Dispensa", "orgao_cnpj": "04973965000111"})
    banco.inserir("contratos_pncp", {"pncp_id": "04973965000111-2-000047/2024", "mes": "2024-11",
                                     "orgao_cnpj": "04973965000111", "valor_global": 140.0})
    ctx = historico.Contexto(banco, historico.meses("2024-11", "2024-12"), date(2026, 11, 26),
                             ler_url=rede, dormir=lambda s: None, pausa=0)
    historico.motor_pncp_detalhe(ctx)
    assert banco.consultar("SELECT catalogo, unitario_resultado FROM pncp_itens") == [(440744, 2116.99)]
    assert banco.consultar("SELECT codigo, nome FROM pncp_amparos") == [(19, "Lei 14.133/2021, Art. 75, II")]
    assert banco.consultar("SELECT compra_id, valor_inicial FROM pncp_contratos_detalhe") == [
        ("04973965000111-1-000043/2024", 100.0)]
    assert banco.consultar("SELECT valor_acrescido, acrescimo_supressao FROM pncp_termos") == [(40.0, 1)]
    assert banco.consultar("SELECT COUNT(*), MIN(semestre) FROM precos_referencia") == [(3, "2024-2")]
    assert banco.consultar("SELECT contrato_id, valor_nf FROM pncp_cobrancas") == [
        ("04973965000111-2-000047/2024", 19052.91)]
    assert banco.consultar("SELECT unitario FROM pncp_nf_itens") == [(2116.99,)]
    antes = len(pedidos)
    historico.motor_pncp_detalhe(ctx)                      # tudo lido por inteiro: nada de novo
    assert len(pedidos) == antes


def test_pncp_detalhe_le_a_pasta_primeiro_e_os_itens_dela_pela_via_rapida(tmp_path):
    """A pasta vem antes de tudo, e os itens dela saem da API do PNCP com o resultado homologado."""
    pedidos = []

    def rede(url, **_):
        pedidos.append(url)
        if url.endswith("/compras/2025/7/itens?pagina=1&tamanhoPagina=500"):
            corpo = [{"numeroItem": 1, "descricao": "Cesta básica", "materialOuServico": "M",
                      "catalogoCodigoItem": "461540", "ncmNbsCodigo": "19059090", "unidadeMedida": "Unidade",
                      "quantidade": 100, "valorUnitarioEstimado": 150.0, "valorTotal": 15000.0, "temResultado": True,
                      "dataInclusao": "2025-03-02T10:00:00"}]
            return base.Leitura(True, url, json.dumps(corpo).encode(), http=200)
        if url.endswith("/compras/2025/7/itens/1/resultados"):
            corpo = [{"niFornecedor": "11222333000144", "nomeRazaoSocialFornecedor": "Mercado X",
                      "quantidadeHomologada": 100, "valorUnitarioHomologado": 149.0,
                      "valorTotalHomologado": 14900.0, "dataResultado": "2025-03-10"}]
            return base.Leitura(True, url, json.dumps(corpo).encode(), http=200)
        return base.Leitura(True, url, b"", http=204)

    banco = historico.Banco(tmp_path / "h.db")
    banco.inserir("contratacoes_pncp", {"pncp_id": "25141524000123-1-000900/2025", "mes": "2025-03",
                                        "modalidade": "Dispensa", "orgao_cnpj": "25141524000123",
                                        "orgao": "SECRETARIA MUNICIPAL DE SAUDE", "valor_homologado": 9e6})
    banco.inserir("contratacoes_pncp", {"pncp_id": "01393989000103-1-000007/2025", "mes": "2025-03",
                                        "modalidade": "Pregão - Eletrônico", "orgao_cnpj": "01393989000103",
                                        "orgao": "FUNDO MUNICIPAL DE ASSISTENCIA SOCIAL-FMAS", "valor_homologado": 1.0})
    ctx = historico.Contexto(banco, historico.meses("2025-03", "2025-03"), date(2026, 11, 26),
                             ler_url=rede, dormir=lambda s: None, pausa=0)
    historico.motor_pncp_detalhe(ctx)
    assert "/orgaos/01393989000103/compras/2025/7" in pedidos[0]            # a pasta antes da compra maior
    assert banco.consultar("SELECT catalogo, ncm, fornecedor_ni, unitario_resultado FROM pncp_itens") == [
        (461540, "19059090", "11222333000144", 149.0)]
    assert not any("/compras/2025/900/itens" in u for u in pedidos)        # via rápida só para a pasta
    primeiro_lento = next(i for i, u in enumerate(pedidos) if "dadosabertos" in u)
    assert "01393989000103" in pedidos[primeiro_lento]                     # e na via lenta também


def test_pncp_detalhe_em_paralelo_guarda_o_mesmo_e_registra_cada_chamada_uma_vez(tmp_path):
    """As vias de detalhe esperam pelo servidor (uns 10 s por compra): a rede do bloco vai em
    linhas paralelas, mas o banco recebe o mesmo que na leitura em fila, cada chamada uma vez só."""
    import threading
    import time as relogio

    ao_mesmo_tempo, maximo, trava = [0], [0], threading.Lock()

    def rede(url, **_):
        with trava:
            ao_mesmo_tempo[0] += 1
            maximo[0] = max(maximo[0], ao_mesmo_tempo[0])
        relogio.sleep(0.02)
        with trava:
            ao_mesmo_tempo[0] -= 1
        if "/compras/" in url and "/itens" not in url:
            seq = int(url.rsplit("/", 1)[1])
            corpo = {"amparoLegal": {"codigo": 19, "nome": f"Art. 75, II ({seq})"}, "srp": False}
            return base.Leitura(True, url, json.dumps(corpo).encode(), http=200)
        if "/contratos/" in url and not url.endswith("/termos"):
            seq = int(url.rsplit("/", 1)[1])
            corpo = {"valorInicial": float(seq), "valorGlobal": float(seq)}
            return base.Leitura(True, url, json.dumps(corpo).encode(), http=200)
        return base.Leitura(True, url, b"", http=204)

    def rodada(paralelo):
        banco = historico.Banco(tmp_path / f"p{paralelo}.db")
        for n in range(1, 31):
            banco.inserir("contratacoes_pncp", {"pncp_id": f"04973965000111-1-{n:06d}/2025", "mes": "2025-03",
                                                "modalidade": "Dispensa" if n % 2 else "Inexigibilidade",
                                                "orgao_cnpj": "04973965000111", "valor_homologado": float(n)})
            banco.inserir("contratos_pncp", {"pncp_id": f"04973965000111-2-{n:06d}/2025", "mes": "2025-03",
                                             "orgao_cnpj": "04973965000111", "valor_global": float(n)})
        ctx = historico.Contexto(banco, ["2025-03"], date(2026, 11, 26), ler_url=rede,
                                 dormir=lambda s: None, pausa=0, paralelo=paralelo)
        historico.motor_pncp_detalhe(ctx)
        return banco

    fila, linhas = rodada(1), rodada(5)
    assert maximo[0] > 1                                          # a rede foi mesmo em paralelo
    for consulta in ("SELECT compra_id, nome FROM pncp_amparos ORDER BY 1",
                     "SELECT contrato_id, valor_inicial FROM pncp_contratos_detalhe ORDER BY 1"):
        assert linhas.consultar(consulta) == fila.consultar(consulta)
    assert len(linhas.consultar("SELECT * FROM pncp_amparos")) == 30
    repetidas = linhas.consultar("SELECT url, COUNT(*) FROM coletas WHERE motor = 'pncp_detalhe' "
                                 "AND url LIKE '%pncp.gov.br%' GROUP BY url HAVING COUNT(*) > 1")
    assert repetidas == []
    assert linhas.consultar("SELECT COUNT(*) FROM coletas WHERE motor = 'pncp_detalhe'") == \
        fila.consultar("SELECT COUNT(*) FROM coletas WHERE motor = 'pncp_detalhe'")
    # As dispensas vêm antes dos contratos; as inexigibilidades, depois deles.
    ordem = [u for (u,) in linhas.consultar("SELECT alvo FROM coletas WHERE motor = 'pncp_detalhe' ORDER BY rowid")]
    primeiro_contrato = next(i for i, a in enumerate(ordem) if a.startswith("contrato "))
    assert all(int(a.split("-")[2][:6]) % 2 for a in ordem[:primeiro_contrato])
    assert any(a.startswith("compra ") and int(a.split("-")[2][:6]) % 2 == 0 for a in ordem[primeiro_contrato:])


def test_nota_fiscal_nenhuma_no_mes_e_lida_mas_endereco_errado_continua_falha(tmp_path):
    """O PNCP diz "nenhum instrumento de cobrança" com 404 e a mensagem no corpo: isso é o mês
    lido (o órgão não publicou nota fiscal), não falha. Um 404 sem essa mensagem continua falha."""
    def rede(url, **_):
        if "instrumentoscobranca" in url and "cnpjOrgao=01393989000103" in url:
            return base.Leitura(False, url, json.dumps({"message": "Nenhum instrumento de Cobrança encontrado."})
                                .encode(), erro="HTTP 404", http=404)
        if "instrumentoscobranca" in url:
            return base.Leitura(False, url, b'{"status":404,"error":"Not Found","path":"/v1/x"}',
                                erro="HTTP 404", http=404)
        return base.Leitura(True, url, b"", http=204)

    banco = historico.Banco(tmp_path / "h.db")
    for cnpj, orgao in (("01393989000103", "FUNDO MUNICIPAL DE ASSISTENCIA SOCIAL-FMAS"),
                        ("25141524000123", "SECRETARIA MUNICIPAL DE SAUDE")):
        banco.inserir("contratos_pncp", {"pncp_id": f"{cnpj}-2-000001/2025", "mes": "2025-03",
                                         "orgao_cnpj": cnpj, "orgao": orgao, "valor_global": 1.0})
    ctx = historico.Contexto(banco, ["2025-03", "2025-04"], date(2026, 11, 26), ler_url=rede,
                             dormir=lambda s: None, pausa=0)
    historico.motor_pncp_detalhe(ctx)
    lidos = json.loads(dict(banco.consultar("SELECT chave, valor FROM meta"))["pncp_detalhe_lidos"])
    assert {"cobrancas 01393989000103 2025-03", "cobrancas 01393989000103 2025-04"} <= set(lidos)
    assert not any(c.startswith("cobrancas 25141524000123") for c in lidos)


def test_fonte_que_pede_calma_sai_do_paralelo_e_depois_espera_a_proxima_rodada(tmp_path):
    """429 numa leitura antecipada tira a fonte do paralelo; lida uma a uma, se ela recusa de novo
    ``disjuntor`` vezes seguidas, o resto dela fica para a próxima rodada, e as outras fontes do
    mesmo motor seguem. A espera pedida pela fonte (Retry-After) é a usada."""
    esperas, consultas = [], []

    def rede(url, **_):
        if "/api/consulta/" in url:
            consultas.append(url)
            return base.Leitura(False, url, b"", erro="HTTP 429", http=429, espera=7.0)
        if "/contratos/" in url and not url.endswith("/termos"):
            return base.Leitura(True, url, json.dumps({"valorInicial": 1.0}).encode(), http=200)
        return base.Leitura(True, url, b"", http=204)

    banco = historico.Banco(tmp_path / "h.db")
    for n in range(1, 21):
        banco.inserir("contratacoes_pncp", {"pncp_id": f"04973965000111-1-{n:06d}/2025", "mes": "2025-03",
                                            "modalidade": "Dispensa", "orgao_cnpj": "04973965000111"})
        banco.inserir("contratos_pncp", {"pncp_id": f"04973965000111-2-{n:06d}/2025", "mes": "2025-03",
                                         "orgao_cnpj": "04973965000111", "valor_global": float(n)})
    ctx = historico.Contexto(banco, ["2025-03"], date(2026, 11, 26), ler_url=rede, dormir=esperas.append,
                             pausa=0, paralelo=4, disjuntor=3)
    historico.motor_pncp_detalhe(ctx)
    assert "pncp.gov.br/api/consulta" in ctx._lentas
    assert set(esperas) >= {7.0}
    # Antecipadas: o primeiro bloco (16), depois 3 leituras na fila de 3 tentativas cada; e mais nada.
    assert len(consultas) == 16 * 3 + 3 * 3
    erros = [e for (e,) in banco.consultar("SELECT erro FROM coletas WHERE alvo LIKE 'compra %' ORDER BY rowid")]
    assert erros[:3] == ["HTTP 429"] * 3 and all("pediu para esperar" in e for e in erros[3:])
    assert banco.consultar("SELECT COUNT(*) FROM pncp_contratos_detalhe") == [(20,)]   # outra fonte seguiu


def test_amparo_das_demais_contratacoes_vem_da_listagem_do_mes(tmp_path):
    """A listagem do PNCP traz o amparo legal de até 50 contratações por leitura: as que faltam
    saem dela, e só o que ela não trouxe é consultado uma a uma."""
    pedidos = []

    def rede(url, **_):
        pedidos.append(url)
        if "contratacoes/publicacao" in url and "codigoModalidadeContratacao=9" in url:
            corpo = {"data": [{"numeroControlePNCP": f"04973965000111-1-{n:06d}/2025",
                               "amparoLegal": {"codigo": 4, "nome": "Lei 14.133/2021, Art. 74, I"},
                               "srp": False, "processo": f"P{n}"} for n in (2, 4, 99)],
                     "totalPaginas": 1}
            return base.Leitura(True, url, json.dumps(corpo).encode(), http=200)
        if "/compras/2025/" in url:
            corpo = {"amparoLegal": {"codigo": 19, "nome": "Lei 14.133/2021, Art. 75, II"}}
            return base.Leitura(True, url, json.dumps(corpo).encode(), http=200)
        return base.Leitura(True, url, b"", http=204)

    banco = historico.Banco(tmp_path / "h.db")
    for n, modalidade in ((1, "Dispensa"), (2, "Inexigibilidade"), (4, "Inexigibilidade"), (6, "Inexigibilidade")):
        banco.inserir("contratacoes_pncp", {"pncp_id": f"04973965000111-1-{n:06d}/2025", "mes": "2025-03",
                                            "modalidade": modalidade, "orgao_cnpj": "04973965000111"})
    ctx = historico.Contexto(banco, ["2025-03"], date(2026, 11, 26), ler_url=rede, dormir=lambda s: None,
                             pausa=0)
    historico.motor_pncp_detalhe(ctx, ibge=5208707)
    assert banco.consultar("SELECT compra_id, codigo FROM pncp_amparos ORDER BY 1") == [
        ("04973965000111-1-000001/2025", 19), ("04973965000111-1-000002/2025", 4),
        ("04973965000111-1-000004/2025", 4), ("04973965000111-1-000006/2025", 19)]
    um_a_um = sorted(int(u.rsplit("/", 1)[1]) for u in pedidos if re.search(r"/compras/2025/\d+$", u))
    assert um_a_um == [1, 6]                       # a dispensa (etapa 1) e a que a listagem não trouxe
    assert not any("99" in a for (a,) in banco.consultar("SELECT compra_id FROM pncp_amparos"))


def test_disjuntor_desliga_so_a_fonte_fora_do_ar_e_nao_o_motor_inteiro(tmp_path):
    """Um motor que lê de três serviços (consulta e integração do PNCP, dados abertos) não para
    tudo quando um deles cai: só o serviço que falhou fica para a próxima rodada."""
    chamadas = []

    def rede(url, **_):
        chamadas.append(url)
        if "/api/consulta/" in url:
            return base.Leitura(False, url, erro="HTTP 503", http=503)
        return base.Leitura(True, url, b"{}", http=200)
    ctx = historico.Contexto(historico.Banco(tmp_path / "h.db"), ["2025-01"], date(2026, 1, 1),
                             ler_url=rede, dormir=lambda s: None, pausa=0, disjuntor=3)
    for n in range(6):
        ctx.ler("pncp_detalhe", "x", f"https://pncp.gov.br/api/consulta/v1/a/{n}", tentativas=1)
    for n in range(4):
        ctx.ler("pncp_detalhe", "y", f"https://pncp.gov.br/api/pncp/v1/b/{n}", tentativas=1)
        ctx.ler("pncp_detalhe", "z", f"https://dadosabertos.compras.gov.br/c/{n}", tentativas=1)
    assert sum("/api/consulta/" in u for u in chamadas) == 3
    assert sum("/api/pncp/" in u for u in chamadas) == 4 and sum("dadosabertos" in u for u in chamadas) == 4
    assert historico._fonte_da_url("https://pncp.gov.br/api/consulta/v1/x") == "pncp.gov.br/api/consulta"
    assert historico._fonte_da_url("https://dadosabertos.compras.gov.br/c/1") == "dadosabertos.compras.gov.br"
