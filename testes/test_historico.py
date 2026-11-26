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
    assert any("endereços que não respondem" in t for t in por_tipo["falha"])
    assert any("não estão no SICONFI" in t for t in por_tipo["lacuna"])
    assert any("contrato do Município no PNCP" in t for t in por_tipo["lacuna"])
    assert any("RREO-Anexo 8" in t for t in por_tipo["melhoria"])      # nome do anexo da educação
    assert d["cobertura"]["2025-01"]["querido_diario"] == "✓"
    assert d["cobertura"]["2025-01"]["sileg"] == "✗"
    assert d["cobertura"]["2025-01"]["pncp"] == "✓" and d["cobertura"]["2024-12"]["pncp"] == "·"
    arq_json, arq_md = diagnostico.gravar(d, tmp_path)
    texto = arq_md.read_text(encoding="utf-8")
    for titulo in ("Onde o sistema falha", "Onde o município deixou lacuna",
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
