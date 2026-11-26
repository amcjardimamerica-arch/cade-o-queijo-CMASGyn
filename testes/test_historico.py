"""Coleta histórica e diagnóstico, sem rede: as fontes respondem por um leitor falso."""

import json
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
    assert [f["cmbPeriodo"] for f in postados] == ["20", "2"]          # 5º e 6º bimestres
    assert all(f["cmbMunicipio[]"] == "520870" and f["cmbUF"] == "52" for f in postados)
    periodos = banco.consultar("SELECT periodo, situacao, homologado FROM externos_periodos ORDER BY periodo")
    assert periodos == [(5, "nao_entregue", None), (6, "homologado", "06/02/26 10:00:59")]
    pct = banco.consultar("SELECT coluna, valor FROM externos_itens WHERE rotulo LIKE 'PERCENTUAL DA RECEITA%' "
                          "ORDER BY coluna")
    assert pct == [(0, 21.54), (1, 21.33), (2, 21.23)]
    d = diagnostico.diagnosticar(banco)
    siops = [(a["tipo"], a["titulo"]) for a in d["achados"] if a["motor"] == "siops"]
    assert siops == [("lacuna", "Saúde: 5º bimestre de 2025 sem demonstrativo homologado no SIOPS")]
    assert d["contagens"]["siops_bimestres"] == {"homologado": 1, "nao_entregue": 1}
    banco.fechar()
