"""Leis de Goiânia pelo Sileg, procura das não localizadas, ofício e a decisão do leis-mcp."""

import json
import re
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from onisciente import RAIZ, historico
from onisciente.coletores import base, leis
from onisciente.legal import normas
from onisciente.legal.mapa import carregar

PAGINA_LEI = ("<html><head><meta charset='utf-8'></head><body><p>LEI Nº 9.262, DE 22 DE MAIO DE 2013</p>"
              "<p>Dispõe sobre o acesso a informações previsto no inciso XXXIII do art. 5º da Constituição "
              "Federal e dá outras providências.</p><p>Art. 1º Esta Lei dispõe sobre os procedimentos.</p>"
              "</body></html>")
FORA_DO_AR = "lo_20100407_000008902.html"           # Lei 8.902/2010: o endereço do mapa devolve 404


def _leitura(url, codigo, corpo=b""):
    if codigo >= 400:
        return base.Leitura(False, url, corpo, erro=f"HTTP {codigo}", http=codigo)
    return base.Leitura(True, url, corpo, http=codigo, original=base.Original(url, "2026-11-27", "a" * 64))


class FonteFalsa:
    """ctresb/leis, as páginas do Sileg e o índice do Sileg, com o que cada um responde."""

    def __init__(self):
        self.lidas: list[str] = []

    def __call__(self, url, **_):
        self.lidas.append(url)
        u = urlparse(url)
        if u.netloc == "raw.githubusercontent.com":
            return _leitura(url, 200, b"---\ntitulo: Norma\nrevogada: false\n---\n\nArt. 1\n")
        if u.netloc == "sileg.goiania.go.gov.br" and u.path.endswith("/select"):
            q = parse_qs(u.query)["q"][0]
            docs = []
            if "000000963" in q:
                docs = [{"id": "./dec_20220315_000000963.html"}]
            elif "Quadro de Detalhamento da Despesa" in q:
                docs = [{"id": "./do_20260115_000009001.pdf"}]
            return _leitura(url, 200, json.dumps({"response": {"numFound": len(docs), "docs": docs}}).encode())
        if u.netloc == "www.goiania.go.gov.br":
            if u.path.endswith(FORA_DO_AR):
                return _leitura(url, 404)
            if u.path.endswith(".pdf"):
                return _leitura(url, 200, b"%PDF-1.4 conteudo")
            return _leitura(url, 200, PAGINA_LEI.encode("utf-8"))
        return _leitura(url, 404)


@pytest.fixture(scope="module")
def rodada_de_normas(tmp_path_factory):
    caminho = tmp_path_factory.mktemp("normas") / "historico.db"
    fonte = FonteFalsa()
    banco = historico.rodar("2026-11", "2026-11", motores=("normas",), caminho=caminho,
                            hoje=date(2026, 11, 27), ler_url=fonte, dormir=lambda s: None, pausa=0)
    banco.fechar()
    return caminho, fonte


def test_normas_municipais_da_lista_sao_baixadas_do_sileg(rodada_de_normas):
    caminho, _ = rodada_de_normas
    banco = historico.Banco.abrir(caminho)
    linhas = banco.consultar("SELECT norma_id, ok, formato, sha256, inicio FROM normas_municipais")
    banco.con.close()
    esperadas = leis.normas_municipais()
    assert len(linhas) == len(esperadas) >= 40
    baixadas = {n for n, ok, *_ in linhas if ok}
    # A lista do requisito 97: PPA, LDO, LOA, Estatuto, LC 335, previdência e Lei 9.262.
    for norma in ("ppa-2026-2029-lei-11-510-2025", "ldo-2026-lei-11-589-2026", "loa-2026-lei-11-590-2026",
                  "lc-011-1992", "lc-335-2021", "lc-312-2018-e-lc-336-2021", "lei-9-262-2013"):
        assert norma in baixadas, norma
    lei_acesso = next(l for l in linhas if l[0] == "lei-9-262-2013" and l[2] == "html")
    assert lei_acesso[3] == "a" * 64 and "acesso a informações" in lei_acesso[4]
    assert any(f == "pdf" for _, ok, f, *_ in linhas if ok)        # decreto publicado só em PDF
    assert ("lei-8-902-2010", 0) in {(n, ok) for n, ok, *_ in linhas}


def test_norma_nao_localizada_e_procurada_no_indice_do_sileg(rodada_de_normas):
    caminho, _ = rodada_de_normas
    banco = historico.Banco.abrir(caminho)
    achadas = {a: (achada, confirmada, url) for a, achada, confirmada, url in banco.consultar(
        "SELECT alvo, achada, confirmada, url FROM normas_procura")}
    banco.con.close()
    achada, confirmada, url = achadas["Decreto 963/2022"]
    assert (achada, confirmada) == (1, 1)
    assert url.endswith("/legis/2022/dc_20220315_000000963.html")   # índice diz dec, o endereço é dc
    assert achadas["Decreto 967/2022"][0] == 0
    assert achadas["QDD 2026 no Diário Oficial"][:2] == (1, 1)
    assert achadas["QDD 2026 no Diário Oficial"][2].endswith("do_20260115_000009001.pdf")


def test_norma_nao_localizada_vira_item_de_oficio_sem_banco(tmp_path):
    itens = normas.ausencias(banco=tmp_path / "sem_banco.db")
    mapa = carregar()
    nomes = " | ".join(a.o_que_falta for a in itens)
    assert len(mapa.nao_localizadas()) == 5
    for n in mapa.nao_localizadas():
        assert n.norma in nomes, n.norma
    assert "Quadro de Detalhamento da Despesa (QDD) de 2026" in nomes
    assert all(a.bloco == "Normas" and "Lei 12.527/2011" in a.fundamento for a in itens)


def test_oficio_cita_so_o_que_a_procura_nao_achou(rodada_de_normas):
    caminho, _ = rodada_de_normas
    itens = normas.ausencias(banco=caminho)
    faltas = [a.o_que_falta for a in itens]
    assert any("Decreto 967/2022" in f for f in faltas)
    assert any("Decreto 3.182/2023" in f for f in faltas)
    assert not any("Decreto 963/2022" in f for f in faltas)          # achado e confirmado: sai do ofício
    assert not any("QDD" in f for f in faltas)
    assert any("Lei 8.902/2010" in f and "fora do ar" in f for f in faltas)
    texto = normas.oficio(hoje=date(2026, 11, 27), banco=caminho)
    assert "Controladoria Geral do Município de Goiânia" in texto
    assert "Decreto 967/2022" in texto and "Lei 12.527/2011" in texto
    assert "—" not in texto


def test_leis_vem_do_ctresb_e_do_sileg_sem_leis_mcp(rodada_de_normas):
    """Requisito 95: o leis-mcp não é preciso (decisão em docs/onisciente/decisoes.md)."""
    _, fonte = rodada_de_normas
    federais = [u for u in fonte.lidas if "ctresb" in u]
    assert federais and all(u.startswith(leis.RAW_CTRESB) for u in federais)
    caminhos = {c for n in carregar().normas.values() for c in n.ctresb}
    assert {u[len(leis.RAW_CTRESB):] for u in federais} == caminhos
    municipais = [u for u in fonte.lidas if "goiania.go.gov.br" in u]
    assert municipais and all(urlparse(u).netloc.endswith("goiania.go.gov.br") for u in municipais)
    for arq in (RAIZ / "onisciente").rglob("*.py"):
        assert not re.search(r"\bmcp\b", arq.read_text(encoding="utf-8"), flags=re.I), arq
    decisoes = (RAIZ / "docs" / "onisciente" / "decisoes.md").read_text(encoding="utf-8")
    assert "leis-mcp" in decisoes and "requisito 95" in decisoes


def test_achados_do_indice_e_consultas():
    q = leis.consulta_por_numero("dc", 3182, 2023)
    assert "id:*dc_2023*_000003182*" in q and "id:*dec_2023*_000003182*" in q
    assert leis.consulta_por_texto('Plano "Municipal"', 2026) == 'attr_content:"Plano  Municipal" AND id:*_2026*'
    achados = leis.achados_do_indice({"response": {"docs": [{"id": "./lc_20210101_000000335.html"},
                                                             {"id": "lixo"}]}})
    assert achados == [{"id": "./lc_20210101_000000335.html", "tipo": "lc", "data": "2021-01-01",
                        "numero": 335, "nome": "lc_20210101_000000335.html"}]


def test_pagina_de_erro_do_sileg_nao_vale_como_norma():
    r = leis.ler_norma_municipal("https://www.goiania.go.gov.br/x.html",
                                 ler_url=lambda url, **_: _leitura(url, 200, b"<html>erro</html>"))
    assert r["ok"] == 0 and "sem o texto" in r["erro"]
