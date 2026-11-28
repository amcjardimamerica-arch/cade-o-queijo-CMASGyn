"""Travas das telas do Onisciente (docs/onisciente/app).

Um banco pequeno, montado aqui com o esquema do banco histórico, e um panorama de mentira bastam para
conferir o essencial: as treze páginas saem, cada número leva a chave da fonte e a fonte diz onde está o
original (ou que ele não está guardado), o rio tem os três modos e fecha, os filtros dos indícios e os
recortes globais funcionam sobre os dados embutidos, as telas que dependem das outras frentes mostram o
estado vazio e passam a mostrar o dado quando o arquivo de entrada chega, e nenhum CPF vai para as telas.
O desenho no navegador é conferido rodando o próprio app.js no Node, num documento de mentira.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import subprocess
from datetime import date
from pathlib import Path

import pytest

from onisciente import historico
from onisciente.telas import gerar
from onisciente.telas.base import sem_cpf
from onisciente.telas.graficos import series_do_parecer
from onisciente.telas.originais import SEM_ORIGINAL, _nome_bruto

AQUI = Path(__file__).parent
APP_JS = AQUI.parent / "onisciente" / "telas" / "estatico" / "app.js"
HARNESS = AQUI / "telas_harness.js"
NODE = shutil.which("node") or ("/opt/node22/bin/node" if Path("/opt/node22/bin/node").exists() else None)
precisa_node = pytest.mark.skipif(NODE is None, reason="Node não está instalado")

FMAS = "01393989000103"
OUTRO = "00000000000191"
SHA_MSC = hashlib.sha256(b"matriz de janeiro").hexdigest()
PAGINAS = ("index", "origem", "leis", "trilha", "secretarias", "pisos", "pessoal", "precos", "empresas", "contas",  # decisão do usuário de 28/11/2026: sem a metáfora do rio
           "indicios", "transparencia", "tempo")


# ---------------------------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------------------------

def _banco(caminho: Path) -> Path:
    con = sqlite3.connect(caminho)
    con.executescript(historico.ESQUEMA)
    ins = lambda t, linhas: con.executemany(  # noqa: E731
        f"INSERT INTO {t} VALUES ({','.join('?' * len(linhas[0]))})", linhas)
    ins("msc_meses", [("2026-01", "entregue", 10, "2026-02-28", ""), ("2026-02", "entregue", 10, "2026-03-31", "")])
    vazio = ""
    msc = []
    for mes, fator in (("2026-01", 1.0), ("2026-02", 2.0)):
        msc += [
            # receita: IPTU (livre, fonte 1500) e COSIP (vinculada, fonte 1751)
            (mes, "621200000", "10131", vazio, "1500", vazio, vazio, "11125001", vazio, vazio, vazio, "C", 1000 * fator),
            (mes, "621200000", "10131", vazio, "1751", vazio, vazio, "12400001", vazio, vazio, vazio, "C", 2000 * fator),
            # empenho: livre na administração, COSIP no leito (15) e fora dele (04)
            (mes, "622130100", "10131", vazio, "1500", "04", "122", vazio, "31901100", vazio, vazio, "C", 700 * fator),
            (mes, "622130100", "10131", vazio, "1751", "15", "452", vazio, "33903900", vazio, vazio, "C", 500 * fator),
            (mes, "622130100", "10131", vazio, "1751", "04", "122", vazio, "31901100", vazio, vazio, "C", 600 * fator),
            # liquidado e pago
            (mes, "622130300", "10131", vazio, "1500", "04", "122", vazio, "31901100", vazio, vazio, "C", 400 * fator),
            (mes, "622130400", "10131", vazio, "1500", "04", "122", vazio, "31901100", vazio, vazio, "C", 300 * fator),
        ]
    ins("msc_itens", msc)
    ins("coletas", [
        ("msc", "classe 6 +0", "2026-01", "https://exemplo.gov.br/msc?mes=1", 1, 200, "", 1, 0.1, 10, SHA_MSC,
         "2026-11-20T10:00:00"),
        ("msc", "classe 6 +0", "2026-02", "https://exemplo.gov.br/msc?mes=2", 1, 200, "", 1, 0.1, 10, "b" * 64,
         "2026-11-20T10:00:00"),
        ("pncp", f"contratos {FMAS} 2026-01 a 2026-02", "2026-02", "https://exemplo.gov.br/pncp", 1, 200, "", 1, 0.1,
         10, "c" * 64, "2026-11-20T10:00:00"),
        ("transferencias", "mes", "2026-02", "https://exemplo.gov.br/transf", 0, 500, "erro de leitura", 3, 1, 0, "",
         "2026-11-20T10:00:00"),
    ])
    ins("contratacoes_pncp", [
        (f"{FMAS}-1-000001/2026", "2026-01", "Pregão", FMAS, "FUNDO MUNICIPAL DE ASSISTENCIA SOCIAL - FMAS", "M",
         "FMAS", "Alimentação", 1000.0, 900.0, "homologada"),
        (f"{OUTRO}-1-000001/2026", "2026-02", "Pregão", OUTRO, "SECRETARIA MUNICIPAL DE SAUDE", "M", "SMS",
         "Medicamentos", 5000.0, 4000.0, "homologada"),
    ])
    ins("contratos_pncp", [
        (f"{FMAS}-2-000001/2026", "2026-01", "2026-01-10", FMAS, "FUNDO MUNICIPAL DE ASSISTENCIA SOCIAL - FMAS", "FMAS",
         "12345678000199", "EMPRESA DE ALIMENTOS LTDA", "Fornecimento de cestas", 120000.0, 1),
        (f"{FMAS}-2-000002/2026", "2026-02", "2026-02-10", FMAS, "FUNDO MUNICIPAL DE ASSISTENCIA SOCIAL - FMAS", "FMAS",
         "52998224725", "PESSOA FISICA PRESTADORA", "Oficina de música", 8000.0, 1),
        (f"{OUTRO}-2-000001/2026", "2026-02", "2026-02-12", OUTRO, "SECRETARIA MUNICIPAL DE SAUDE", "SMS",
         "98765432000155", "DISTRIBUIDORA DE REMEDIOS SA", "Medicamentos", 450000.0, 0),
    ])
    ins("siconfi_itens", [
        ("RREO", 2025, 6, "RREO-Anexo 01", "", "DOTAÇÃO ATUALIZADA (e)", "TotalDespesas", "Total", 5000.0),
        ("RREO", 2025, 6, "RREO-Anexo 01", "", "DESPESAS PAGAS ATÉ O BIMESTRE (j)", "TotalDespesas", "Total", 4500.0),
        ("RREO", 2025, 6, "RREO-Anexo 01", "", "PREVISÃO ATUALIZADA (a)", "TotalReceitas", "Total", 5200.0),
        ("RREO", 2025, 6, "RREO-Anexo 01", "", "Até o Bimestre (c)", "TotalReceitas", "Total", 5100.0),
    ])
    ins("siconfi_entregas", [(2025, "Relatório Resumido de Execução Orçamentária", 6, "B", "HO", "2026-02-15",
                              "P", "RREO")])
    con.commit()
    con.close()
    return caminho


def _ficha(codigo, familia, gravidade, titulo, origem="onisciente"):
    return {"codigo": codigo, "familia": familia, "titulo": titulo, "gravidade": gravidade,
            "verificacao": "INDICIARIO", "como_deveria": "Como deveria ser.", "como_esta": "Como está.",
            "norma": "Lei 4.320/1964", "providencia": "Pedir o documento.", "caso_semelhante": "",
            "observacao": "", "custodia": [{"url": "https://exemplo.gov.br/diario", "coletado_em": "2026-11-01",
                                            "sha256": "d" * 64}], "origem": origem}


PANORAMA = {
    "competencia": "2026-02", "dominio": "Assistência Social", "em_uma_frase": "Frase de teste do mês.",
    "contagem": {"critica": 1, "alta": 1, "media": 0},
    "integridade": {"nota": 30.0, "nota_maxima": 50.0},
    "fichas": [
        _ficha("PES-01", "PES", "critica", "Data-base não paga", origem="cadeoqueijo"),
        _ficha("VIN-DESVIO-751-04-2026-02", "VIN", "alta", "COSIP fora do leito"),
    ],
    "ausencias": [{"o_que_falta": "Ata da plenária de fevereiro", "conferencia_impedida": "controle social",
                   "onde_deveria_estar": "Diário Oficial", "fundamento": "Lei 12.527/2011", "periodo": "fevereiro de 2026",
                   "orgao": "Conselho Municipal de Assistência Social", "bloco": "CMAS"}],
    "pisos": [{"regra": "IGD-CONTROLE-SOCIAL", "titulo": "Piso do IGD ao controle social", "limite": 3.0,
               "situacao": "sem_dado", "selo": "roxo", "percentual": None}],
}

ENTRADAS = {
    "empresas": {"empresas": [{"cnpj": "12.345.678/0001-99", "razao": "EMPRESA DE ALIMENTOS LTDA",
                               "abertura": "2025-12-01", "situacao": "ATIVA", "capital": 10000, "cnae": "4639701",
                               "socios": [{"nome": "Sócia Administradora", "qualificacao": "Sócio-Administrador",
                                           "desde": "2025-12-01"}],
                               "sancoes": [], "alertas": [{"tipo": "empresa_recente", "gravidade": "alta",
                                                           "texto": "aberta 40 dias antes do contrato"}],
                               "url": "https://exemplo.gov.br/cnpj", "lido_em": "2026-11-27", "sha256": "e" * 64}]},
    "selo_transparencia": {"programa": "Programa de teste", "ciclo": "2026",
                           "declarado": {"nivel": "Diamante", "nota": 95, "url": "https://exemplo.gov.br/selo",
                                         "lido_em": "2026-11-27"},
                           "auditado": {"nivel": "Prata", "nota": 61},
                           "criterios": [{"id": "C1", "criterio": "Publica a execução diária", "peso": 10,
                                          "declarado": "cumpre", "auditado": "falha",
                                          "prova_url": "https://exemplo.gov.br/portal", "lido_em": "2026-11-27"}],
                           "por_orgao": [{"cnpj": FMAS, "orgao": "FMAS", "nota": 20, "nivel": "sem selo"}]},
    "federais": {"repasses": [{"origem": "FNS", "mes": "2026-02", "programa": "Atenção primária", "valor": 1000.0,
                               "fonte_destino": "1600", "registrado": 700.0, "url": "https://exemplo.gov.br/fns",
                               "lido_em": "2026-11-27"}]},
    "execucao": {"empenhos": [{"numero": "2026NE000123", "data": "2026-02-03", "orgao_cnpj": FMAS,
                               "credor": "EMPRESA DE ALIMENTOS LTDA", "credor_cnpj": "12345678000199", "fonte": "1500",
                               "funcao": "08", "natureza": "33903000", "valor": 5000.0,
                               "contrato": f"{FMAS}-2-000001/2026",
                               "eventos": [{"estacao": "empenho", "data": "2026-02-03", "valor": 5000.0,
                                            "documento": "NE 123", "url": "https://exemplo.gov.br/ne",
                                            "lido_em": "2026-11-27"},
                                           {"estacao": "liquidacao", "data": "2026-02-20", "valor": 5000.0,
                                            "documento": "NL 77", "url": "https://exemplo.gov.br/nl",
                                            "lido_em": "2026-11-27"}],
                               "url": "https://exemplo.gov.br/ne", "lido_em": "2026-11-27"}]},
}


@pytest.fixture(scope="module")
def banco(tmp_path_factory) -> Path:
    return _banco(tmp_path_factory.mktemp("banco") / "historico.db")


@pytest.fixture(scope="module")
def site(banco, tmp_path_factory) -> Path:
    destino = tmp_path_factory.mktemp("site")
    brutos = tmp_path_factory.mktemp("brutos")
    (brutos / _nome_bruto("msc", "classe 6 +0", "2026-01")).write_bytes(b"matriz de janeiro")
    (brutos / _nome_bruto("msc", "classe 6 +0", "2026-02")).write_bytes(b"outra coisa")   # não bate com o sha
    gerar(destino, banco=banco, panoramas={"2026-02": PANORAMA}, brutos=brutos, hoje=date(2026, 11, 27), entradas={})
    return destino


@pytest.fixture(scope="module")
def site_com_entradas(banco, tmp_path_factory) -> Path:
    destino = tmp_path_factory.mktemp("site2")
    gerar(destino, banco=banco, panoramas={"2026-02": PANORAMA}, hoje=date(2026, 11, 27), entradas=ENTRADAS)
    return destino


def _dados(pagina: Path) -> dict[str, object]:
    html = pagina.read_text(encoding="utf-8")
    return {m.group(1): json.loads(m.group(2).replace("<\\/", "</")) for m in
            re.finditer(r'<script type="application/json" id="([^"]+)">(.*?)</script>', html, re.S)}


def _numeros(obj, achados=None):
    achados = [] if achados is None else achados
    if isinstance(obj, dict):
        if "v" in obj and set(obj) <= {"v", "f", "s"}:
            achados.append(obj)
        for v in obj.values():
            _numeros(v, achados)
    elif isinstance(obj, list):
        for v in obj:
            _numeros(v, achados)
    return achados


def _js(script: str, dados: dict) -> object:
    """Roda um trecho de JavaScript com ``L`` (as funções puras do app.js) e ``D`` (os dados)."""
    prog = (f"const L = require({json.dumps(str(APP_JS))}); const D = {json.dumps(dados)};\n"
            f"process.stdout.write(JSON.stringify((function(){{ {script} }})()));")
    r = subprocess.run([NODE, "-e", prog], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _desenhar(pagina: Path, *recortes: str) -> dict:
    r = subprocess.run([NODE, str(HARNESS), str(pagina), str(pagina.parent / "app.js"), *recortes],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


# ---------------------------------------------------------------------------------------------
# As páginas e os seletores
# ---------------------------------------------------------------------------------------------

def test_gera_as_treze_telas_com_seletores_e_regua(site):
    for p in PAGINAS:
        html = (site / f"{p}.html").read_text(encoding="utf-8")
        for ident in ('id="sel-alvo"', 'id="sel-periodo"', 'id="sel-secretaria"', 'id="bt-apresentar"',
                      'class="regua"', 'id="d-comum"', 'id="d-fontes"', 'id="d-tela"', 'id="d-indice"'):
            assert ident in html, (p, ident)
        for outra in PAGINAS:
            assert f'href="{outra}.html"' in html, (p, outra)
        assert "—" not in html, f"travessão na página {p}"
    for estatico in ("app.css", "app.js", "escudo.webp"):
        assert (site / estatico).exists()
    comum = _dados(site / "index.html")["d-comum"]
    assert comum["competencias"] == ["2026-01", "2026-02"] and comum["padrao"] == "2026-02"
    ids = {s["id"]: s for s in comum["secretarias"]}
    assert ids[FMAS]["pasta"] is True and ids[OUTRO]["funcao"] == "10"


def test_todo_numero_tem_fonte_e_a_fonte_diz_onde_esta_o_original(site):
    total = 0
    for p in PAGINAS:
        d = _dados(site / f"{p}.html")
        fontes = d["d-fontes"]
        numeros = _numeros(d["d-tela"]) + _numeros(d["d-comum"])
        total += len(numeros)
        for n in numeros:
            assert n.get("f") in fontes, (p, n)
        for chave, f in fontes.items():
            assert f["r"], chave
            if not f.get("u"):
                assert SEM_ORIGINAL in f["n"].lower(), (p, chave, f)
    assert total > 100


def test_original_guardado_vai_junto_so_quando_a_impressao_digital_bate(site):
    fontes = _dados(site / "origem.html")["d-fontes"]  # decisão do usuário de 28/11/2026: sem a metáfora do rio
    janeiro, fevereiro = fontes["msc:2026-01"], fontes["msc:2026-02"]
    assert janeiro["c"] == 1 and janeiro["u"] == f"originais/{SHA_MSC}"
    assert (site / "originais" / SHA_MSC).read_bytes() == b"matriz de janeiro"
    assert "c" not in fevereiro and fevereiro["u"] == "https://exemplo.gov.br/msc?mes=2"
    assert janeiro["h"] == SHA_MSC and janeiro["q"] == "2026-11-20"


def test_nenhum_cpf_vai_para_as_telas(site):
    for p in PAGINAS:
        html = (site / f"{p}.html").read_text(encoding="utf-8")
        assert "52998224725" not in html and "529.982.247-25" not in html, p
    assert sem_cpf({"t": "Credor 529.982.247-25 recebeu"}) == {"t": "Credor CPF omitido recebeu"}


# ---------------------------------------------------------------------------------------------
# O rio
# ---------------------------------------------------------------------------------------------

def test_rio_tem_a_cosip_fora_do_leito_com_fonte(site):
    rio = _dados(site / "origem.html")["d-tela"]  # decisão do usuário de 28/11/2026: sem a metáfora do rio
    c = rio["por_c"]["2026-02"]
    assert c["cosip"]["receita"]["v"] == pytest.approx(6000.0)      # 2.000 + 4.000
    fora = {x[0]: x for x in c["cosip"]["empenhado"]}
    assert fora["04"][2] is False and fora["15"][2] is True and fora["04"][1]["v"] == pytest.approx(1800.0)
    assert any(d["fonte"] == "751" and d["funcao"] == "04" for d in c["desvios"])


@precisa_node
def test_sankey_tres_modos_fecham_e_separam_vinculada_de_livre(site):
    rio = _dados(site / "origem.html")["d-tela"]  # decisão do usuário de 28/11/2026: sem a metáfora do rio
    r = _js("""
      const out = {};
      for (const m of ['todo', 'vinculada', 'livre']) {
        const g = L.somarRio(D, '2026-02', m, null, {});
        const entra = {}, sai = {};
        g.links.forEach(l => { entra[l.para] = (entra[l.para] || 0) + l.v; sai[l.de] = (sai[l.de] || 0) + l.v; });
        out[m] = { total: g.total, classes: [...new Set(g.links.map(l => l.cl))].sort(),
                   leito: Object.keys(g.nos).filter(k => k[0] === 'l').sort(), entra, sai,
                   foz: Object.keys(g.nos).filter(k => k[0] === 'f').sort() };
      }
      const so04 = L.somarRio(D, '2026-02', 'todo', '04', {});
      out.funcao = Object.keys(so04.nos).filter(k => k[0] === 'f').sort();
      out.janeiro = L.somarRio(D, '2026-01', 'todo', null, {}).total;
      return out;
    """, rio)
    # receita de 9.000 (1.000 + 2.000 + 2.000 + 4.000); a água livre empenhou 4.200 (a conta 62213 soma o empenho
    # a liquidar, o liquidado e o pago) contra 3.000 arrecadados, e a diferença entra como saldo de anos anteriores
    assert r["todo"]["total"] == pytest.approx(10200.0)
    assert r["vinculada"]["total"] == pytest.approx(6000.0) and r["livre"]["total"] == pytest.approx(4200.0)
    assert r["vinculada"]["leito"] == ["lvinculada"] and r["livre"]["leito"] == ["llivre"]
    assert "livre" not in r["vinculada"]["classes"] and "vinculada" not in r["livre"]["classes"]
    for modo in ("todo", "vinculada", "livre"):     # o leito fecha: o que entra sai (empenho ou água parada)
        for no in r[modo]["leito"]:
            assert r[modo]["entra"][no] == pytest.approx(r[modo]["sai"][no])
    assert "fparada" in r["todo"]["foz"]                       # arrecadado e não empenhado
    assert r["funcao"] == ["f04", "fdemais", "fparada"]
    assert r["janeiro"] == pytest.approx(3400.0)          # 3.000 de receita e 400 de saldo anterior


@precisa_node
def test_tela_do_rio_desenha_os_tres_modos(site):
    saida = _desenhar(site / "origem.html", "2026-02|", "2026-02||modo=vinculada")  # decisão do usuário de 28/11/2026: sem a metáfora do rio
    tela = saida["2026-02|"]["tela"]
    for modo in ("todo", "vinculada", "livre"):
        assert f'data-modo="{modo}"' in tela
    assert 'aria-pressed="true">Vinculada' in saida["2026-02||modo=vinculada"]["tela"]
    assert "<svg class=\"sankey\"" in saida["2026-02|"]["sankey"]
    assert 'class="vinculada n"' in saida["2026-02|"]["sankey"] and 'class="livre n"' in saida["2026-02|"]["sankey"]
    assert 'class="livre n"' not in saida["2026-02||modo=vinculada"]["sankey"]
    assert not saida["2026-02|"]["erros"]


# ---------------------------------------------------------------------------------------------
# Indícios e recortes
# ---------------------------------------------------------------------------------------------

@precisa_node
def test_filtros_dos_indicios(site):
    d = _dados(site / "indicios.html")["d-tela"]
    codigos = {f["codigo"]: f for f in d["fichas"]}
    assert {"PES-01", "VIN-DESVIO-751-04-2026-02"} <= set(codigos)
    assert codigos["PES-01"]["secretarias"] == [FMAS]          # ficha do Cadê o Queijo é da pasta
    assert codigos["VIN-DESVIO-751-04-2026-02"]["secretarias"] == []   # do Município inteiro
    assert codigos["VIN-DESVIO-751-04-2026-02"]["tema"] == "cosip"
    r = _js("""
      const F = D.fichas, k = l => l.map(f => f.codigo).sort();
      return {
        familia: k(L.filtrar(F, {c: '2026-02', familias: ['PES']})),
        gravidade: k(L.filtrar(F, {c: '2026-02', gravidades: ['alta']})),
        secretaria: k(L.filtrar(F, {c: '2026-02', s: '%s'})),
        outra: k(L.filtrar(F, {c: '2026-02', s: '%s'})),
        janeiro: k(L.filtrar(F, {c: '2026-01'})),
        periodo: k(L.filtrar(F, {de: '2026-01', ate: '2026-02', familias: ['PES', 'VIN']})),
        tema: k(L.filtrar(F, {c: '2026-02', temas: ['cosip']})),
        estacao: k(L.filtrar(F, {c: '2026-02', estacao: 9, estacoesDaFamilia: D.estacoes_da_familia})),
        texto: k(L.filtrar(F, {c: '2026-02', texto: 'data-base'}))
      };
    """ % (FMAS, OUTRO), d)
    assert r["familia"] == ["PES-01"]
    assert r["gravidade"] == ["VIN-DESVIO-751-04-2026-02"]
    assert "PES-01" in r["secretaria"] and "VIN-DESVIO-751-04-2026-02" not in r["secretaria"]
    assert "PES-01" not in r["outra"]
    assert "PES-01" not in r["janeiro"]                        # a ficha do parecer é de fevereiro
    assert r["periodo"] == ["PES-01", "VIN-DESVIO-751-04-2026-02"]
    assert r["tema"] == ["VIN-DESVIO-751-04-2026-02"]
    assert "PES-01" not in r["estacao"]                        # PES mora na estação 8 (pagamento)
    assert r["texto"] == ["PES-01"]


@precisa_node
def test_tela_de_indicios_aplica_os_filtros_da_url(site):
    saida = _desenhar(site / "indicios.html", f"2026-02||fam=PES", "2026-02||g=alta", f"2026-02|{OUTRO}|")
    assert "PES-01" in saida["2026-02||fam=PES"]["fichas"]
    assert "VIN-DESVIO" not in saida["2026-02||fam=PES"]["fichas"]
    assert "VIN-DESVIO" in saida["2026-02||g=alta"]["fichas"] and "PES-01" not in saida["2026-02||g=alta"]["fichas"]
    assert "Nenhuma ficha" in saida[f"2026-02|{OUTRO}|"]["fichas"]
    for fam in ("PES", "PRC", "RIO", "SIS"):
        assert f'data-fam="{fam}"' in saida["2026-02||fam=PES"]["tela"]


@precisa_node
def test_seletores_de_periodo_e_secretaria_recortam_as_telas(site):
    sec = _desenhar(site / "secretarias.html", "2026-02|", f"2026-02|{FMAS}")
    assert 'class="clic marcada" data-sec="' + FMAS in sec[f"2026-02|{FMAS}"]["tela"]
    assert "Secretaria no recorte" in sec[f"2026-02|{FMAS}"]["tela"]
    assert "Secretaria no recorte" not in sec["2026-02|"]["tela"]
    precos = _desenhar(site / "precos.html", "2026-02|", f"2026-02|{FMAS}", "2026-01|")
    assert "3 contrato(s)" in precos["2026-02|"]["tela"]
    assert "2 contrato(s)" in precos[f"2026-02|{FMAS}"]["tela"]
    assert "1 contrato(s)" in precos["2026-01|"]["tela"]
    assert "DISTRIBUIDORA" not in precos[f"2026-02|{FMAS}"]["contratos"]
    r = _js("""
      return { tudo: L.contar(D.indice, '2026-02', ''), pasta: L.contar(D.indice, '2026-02', '%s'),
               jan: L.contar(D.indice, '2026-01', '') };
    """ % FMAS, {"indice": _dados(site / "index.html")["d-indice"]})
    assert r["tudo"]["pessoal"]["n"] == 1 and r["tudo"]["cosip"]["n"] == 1
    assert "cosip" not in r["pasta"] and r["pasta"]["pessoal"]["critica"] == 1
    assert "pessoal" not in r["jan"]


@precisa_node
def test_todas_as_telas_desenham_sem_erro(site):
    for p in PAGINAS:
        saida = _desenhar(site / f"{p}.html", "2026-02|", f"2026-02|{FMAS}", "2026-01|")
        for recorte, s in saida.items():
            assert s["tela"] and "não pôde ser desenhada" not in s["tela"], (p, recorte, s["tela"][:300])
            assert not s["erros"], (p, recorte, s["erros"])
            assert "Seguindo o dinheiro" in s["caminho"] or p == PAGINAS[-1]


# ---------------------------------------------------------------------------------------------
# Estado vazio e entradas das outras frentes
# ---------------------------------------------------------------------------------------------

@precisa_node
def test_estado_vazio_ate_a_coleta_e_dado_quando_a_entrada_chega(site, site_com_entradas):
    vazio = {p: _desenhar(site / f"{p}.html", "2026-02|")["2026-02|"]
             for p in ("empresas", "transparencia", "trilha", "origem")}  # decisão do usuário de 28/11/2026: sem a metáfora do rio
    assert "Aguardando a coleta das transferências federais" in vazio["origem"]["tela"]  # decisão do usuário de 28/11/2026: sem a metáfora do rio
    assert "Aguardando a coleta das empresas na Receita Federal" in vazio["empresas"]["tela"]
    assert "Aguardando a coleta do selo de transparência" in vazio["transparencia"]["tela"]
    assert "Aguardando a coleta da execução" in vazio["trilha"]["tela"]
    cheio = {p: _desenhar(site_com_entradas / f"{p}.html", "2026-02|")["2026-02|"]
             for p in ("empresas", "transparencia", "trilha", "precos", "origem")}  # decisão do usuário de 28/11/2026: sem a metáfora do rio
    assert "Atenção primária" in cheio["origem"]["tela"] and "diverge" in cheio["origem"]["tela"]  # decisão do usuário de 28/11/2026: sem a metáfora do rio
    assert "Aguardando a coleta das empresas" not in cheio["empresas"]["tela"]
    assert "Sócia Administradora" in cheio["empresas"]["tela"] and "aberta 40 dias antes" in cheio["empresas"]["tela"]
    assert "Diamante" in cheio["transparencia"]["tela"] and "Publica a execução diária" in cheio["transparencia"]["tela"]
    assert "2026NE000123" in cheio["trilha"]["tela"]
    assert "1 conferida(s)" in cheio["precos"]["tela"]
    fontes = _dados(site_com_entradas / "empresas.html")["d-fontes"]
    assert fontes["rf:12345678000199"]["u"] == "https://exemplo.gov.br/cnpj"


def test_pagina_de_contas_e_tempo_com_prazo_e_falta_da_serie(site):
    contas = _dados(site / "contas.html")["d-tela"]
    rreo = contas["entregas"][0]
    assert rreo["prazo"] == "2026-01-30" and rreo["no_prazo"] is False and rreo["atraso"]["v"] == 16
    tempo = _dados(site / "tempo.html")["d-tela"]
    anos = {a["ano"]: a for a in tempo["anos"]}
    assert anos[2025]["tipo"] == "fechado" and anos[2025]["pago"]["v"] == 4500.0
    assert anos[2019]["tipo"] == "sem_dado"
    assert tempo["falta"] and "três exercícios" in tempo["falta"]


# ---------------------------------------------------------------------------------------------
# Gráficos do parecer, linha de comando e sintaxe
# ---------------------------------------------------------------------------------------------

def test_series_do_parecer_em_svg_com_fonte(banco):
    html = series_do_parecer("2026-02", banco=banco)
    assert html.count("<figure>") == 3 and html.count("<svg") == 3
    assert "Fonte: <a href=\"https://exemplo.gov.br/msc?mes=2\"" in html
    titulos = re.findall(r"<title>([^<]+)</title>", html)
    assert titulos and all("Fonte:" in t for t in titulos)
    assert "Empenhado, fevereiro de 2026: R$ 5.000,00" in html       # toda a conta 62213 do mês
    assert series_do_parecer("2026-02", banco=banco.parent / "nao_existe.db") == ""


def test_linha_de_comando_gera_as_telas(banco, tmp_path):
    from onisciente.__main__ import main
    assert main(["telas", "--banco", str(banco), "--destino", str(tmp_path)]) == 0
    assert (tmp_path / "index.html").exists() and (tmp_path / "indicios.html").exists()


@precisa_node
def test_javascript_sem_erro_de_sintaxe():
    r = subprocess.run([NODE, "--check", str(APP_JS)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


# ---------------------------------------------------------------------------------------------
# Telas, uma a uma
# ---------------------------------------------------------------------------------------------

def test_trilha_tem_as_nove_estacoes_por_mes_e_funcao(site):
    t = _dados(site / "trilha.html")["d-tela"]
    assert [e["n"] for e in t["estacoes"]] == list(range(1, 10))
    fev = {x["n"]: x for x in t["exemplos"]["2026-02"]["*"]["linhas"]}
    assert len(fev) == 9
    assert fev[5]["acesa"] and fev[5]["valor"]["v"] == pytest.approx(5000.0)      # empenhado no mês (conta 62213)
    assert fev[8]["acesa"] and fev[8]["valor"]["v"] == pytest.approx(600.0)       # pago no mês
    assert fev[6]["contratos"] == 2                                               # contratos assinados em fevereiro
    assert not fev[9]["acesa"] and 9 in t["exemplos"]["2026-02"]["*"]["faltantes"]  # prestação não publicada
    so04 = {x["n"]: x for x in t["exemplos"]["2026-02"]["04"]["linhas"]}
    assert so04[5]["valor"]["v"] == pytest.approx(4000.0)                         # (700 + 600 + 400 + 300) x 2
    assert t["execucao"] is None


def test_transparencia_tem_ausencias_oficio_e_escada(site):
    t = _dados(site / "transparencia.html")["d-tela"]
    assert t["ausencias"][0]["o_que_falta"] == "Ata da plenária de fevereiro"
    oficio = t["oficios"]["2026-02"][0]
    assert "Ata da plenária de fevereiro" in oficio["texto"] and oficio["itens"] == 1
    assert [d["n"] for d in t["escada"]] == list(range(1, len(t["escada"]) + 1)) and len(t["escada"]) >= 3
    assert any(f["motor"] == "transferencias" for f in t["falhas"])               # leitura que falhou, em cinza
    assert t["selo"] is None


def test_leis_tem_a_regua_com_norma_e_link(site):
    leis = _dados(site / "leis.html")
    regras = {r["id"]: r for r in leis["d-tela"]["regras"]}
    assert regras["PESSOAL-EXECUTIVO"]["valor"]["v"] == 54.0
    assert leis["d-fontes"][regras["PESSOAL-EXECUTIVO"]["valor"]["f"]]["r"]
    assert any(n["links"] for n in leis["d-tela"]["normas"])


@precisa_node
def test_preco_e_entrega_desenha_o_triangulo(site):
    s = _desenhar(site / "precos.html", "2026-02|")["2026-02|"]
    assert "Triângulo preço, entrega e prestação de 3 contratos" in s["tela"]
    assert "aguardando a execução" in s["tela"]


BANCO_REAL = AQUI.parent / "dados" / "onisciente" / "historico.db"


@pytest.mark.skipif(not BANCO_REAL.exists(), reason="banco histórico real ausente")
def test_banco_real_rio_pisos_e_pessoal():
    """Com o banco real: a COSIP pagando a administração, o FNAS em duas vias e os percentuais do RGF."""
    from onisciente.config import carregar_alvo
    from onisciente.legal.mapa import carregar
    from onisciente.telas import dados as D
    from onisciente.telas import originais as og
    from onisciente.telas.base import abrir
    from onisciente import RAIZ
    con = abrir(BANCO_REAL)
    try:
        ctx = D.Contexto(con=con, banco=BANCO_REAL, alvo=carregar_alvo(RAIZ / "alvos" / "goiania.toml"),
                         alvo_id="goiania", mapa=carregar(), originais=og.Originais(con=con), hoje=date(2026, 11, 27))
        rio = D._rio_competencia(ctx, "2026-10", ctx.do_ano("2026-10"))
        cosip = {d["funcao"]: d["valor"]["v"] for d in rio["desvios"] if d["fonte"] == "751"}
        assert cosip["04"] == pytest.approx(14_660_790.97, abs=1)
        fnas = rio["fnas"]["origem"]
        assert fnas["vias"][0]["valor"]["v"] == pytest.approx(9_140_488.56, abs=1)
        assert fnas["vias"][1]["valor"]["v"] == pytest.approx(5_261_008.56, abs=1)
        medidas = {m["id"]: m for m in D._medidas(ctx, "2026-10")["medidas"]}
        assert medidas["PESSOAL-EXECUTIVO"]["percentual"]["v"] == pytest.approx(45.58, abs=0.01)
        assert medidas["PESSOAL-EXECUTIVO"]["percentual"]["f"].startswith("siconfi:RGF 2026, 2º quadrimestre")
        serie = D.pessoal(ctx)["serie"]
        assert serie and serie[-1]["rotulo"] == "RGF do 2º quadrimestre de 2026"
    finally:
        con.close()


# ---------------------------------------------------------------------------------------------
# As entradas das outras frentes (onisciente/telas/entradas.py)
# ---------------------------------------------------------------------------------------------

AUDITORIA = {
    "ciclo": 2026, "hoje": "2026-11-27",
    "declarado": {"selo": "Diamante", "ciclo": 2025, "indice": "acima de 95%", "fonte": "Notícia do selo",
                  "url": "https://exemplo.gov.br/noticia", "ciclo_2026": "Resultado de 2026 não conferido."},
    "veredito": {"oficial": "não confirmado", "restritiva": "cai", "frase": "Pela leitura oficial o selo não está confirmado."},
    "notas": {
        "oficial/comprovada": {"leitura": "oficial", "modo": "comprovada", "indice": 5.24, "essenciais_ok": False,
                               "nivel": "Inicial", "selo": False, "essenciais_em_falta": ["3.1", "4.1"]},
        "oficial/teto": {"leitura": "oficial", "modo": "teto", "indice": 100.0, "essenciais_ok": True,
                         "nivel": "Diamante", "selo": True, "essenciais_em_falta": []},
        "restritiva/comprovada": {"leitura": "restritiva", "modo": "comprovada", "indice": 4.62, "essenciais_ok": False,
                                  "nivel": "Inicial", "selo": False, "essenciais_em_falta": ["3.1", "4.1", "O.2"]},
        "restritiva/teto": {"leitura": "restritiva", "modo": "teto", "indice": 76.41, "essenciais_ok": False,
                            "nivel": "Elevado", "selo": False, "essenciais_em_falta": ["O.2"]}},
    "radar": {"lido": False, "motivo": "o Radar recusou a leitura"},
    "criterios": [
        {"id": "1.1", "dimensao": 1, "classe": "essencial", "texto": "Possui sítio oficial", "base_legal": "Lei 12.527/2011",
         "situacao": {"oficial": "atendido", "restritiva": "atendido"},
         "provas": [{"descricao": "o sítio respondeu", "fonte": "banco, tabela fontes: https://exemplo.gov.br/portal",
                     "leituras": "ambas", "nivel": "B"}], "notas": {"oficial": [], "restritiva": []}},
        {"id": "4.1", "dimensao": 4, "classe": "essencial", "texto": "Total das despesas empenhadas", "base_legal": "LC 101/2000",
         "situacao": {"oficial": "não verificável", "restritiva": "não atendido"}, "provas": [],
         "notas": {"oficial": ["fonte e_portal ainda não sondada"], "restritiva": []}}],
    "fundos": [
        {"id": f"F{i}", "orgao": "FMAS", "texto": f"Obrigação {i} do Fundo", "base": "LC 101/2000, art. 48-A",
         "pntp": "3.1", "estado": "em falta", "alerta": True, "provas": ["não publicado, segundo o parecer"],
         "valor_em_jogo": 1000.0 * i} for i in range(1, 6)] + [
        {"id": f"C{i}", "orgao": "CMAS", "texto": f"Obrigação {i} do Conselho", "base": "Lei 8.742/1993, art. 16",
         "pntp": "", "estado": "em falta", "alerta": True, "provas": [], "valor_em_jogo": 0.0} for i in range(1, 5)],
    "pendencias": ["Uma pendência da auditoria."],
    "fontes": [{"titulo": "Cartilha PNTP 2026", "url": "https://exemplo.gov.br/cartilha", "lida_em": "2026-11-27"}],
}


def _entradas_reais(banco: Path, tmp: Path) -> dict[str, dict]:
    from onisciente.telas import entradas as ent
    aud = tmp / "auditoria.json"
    aud.write_text(json.dumps(AUDITORIA, ensure_ascii=False), encoding="utf-8")
    arquivos = ent.escrever(banco, tmp / "entradas", hoje=date(2026, 11, 27), auditoria=aud)
    return {nome: json.loads(arq.read_text(encoding="utf-8")) for nome, arq in arquivos.items()}


@pytest.fixture(scope="module")
def entradas_reais(banco, tmp_path_factory) -> dict[str, dict]:
    return _entradas_reais(banco, tmp_path_factory.mktemp("entradas"))


@pytest.fixture(scope="module")
def site_entradas_reais(banco, entradas_reais, tmp_path_factory) -> Path:
    destino = tmp_path_factory.mktemp("site3")
    gerar(destino, banco=banco, panoramas={"2026-02": PANORAMA}, hoje=date(2026, 11, 27), entradas=entradas_reais)
    return destino


def test_entrada_do_selo_tem_as_duas_leituras_e_as_obrigacoes_do_fundo_e_do_conselho(entradas_reais, tmp_path):
    from onisciente.telas import entradas as ent
    s = entradas_reais["selo_transparencia"]
    assert s["situacao"] == "dado"
    assert s["declarado"]["nivel"] == "Diamante" and s["declarado"]["nota"] is None
    assert s["declarado"]["nota_texto"] == "acima de 95%" and s["declarado"]["ciclo"] == "2025"
    assert {(x["leitura"], x["modo"]) for x in s["leituras"]} == {("oficial", "comprovada"), ("oficial", "teto"),
                                                                 ("restritiva", "comprovada"), ("restritiva", "teto")}
    assert s["auditado"] == {"nivel": "Inicial", "nota": 5.24}
    orgaos = {o["sigla"]: o for o in s["por_orgao"]}
    assert [x["id"] for x in orgaos["FMAS"]["obrigacoes"]] == ["F1", "F2", "F3", "F4", "F5"]
    assert [x["id"] for x in orgaos["CMAS"]["obrigacoes"]] == ["C1", "C2", "C3", "C4"]
    assert orgaos["FMAS"]["cnpj"] == FMAS
    crit = {c["id"]: c for c in s["criterios"]}
    assert crit["1.1"]["auditado"] == "cumpre" and crit["1.1"]["prova_url"] == "https://exemplo.gov.br/portal"
    assert crit["4.1"]["auditado"] == "sem_dado" and crit["4.1"]["auditado_restritiva"] == "falha"
    # Sem a auditoria, a coleta não foi feita (cinza), nunca "o Município não publicou".
    assert ent.selo(tmp_path / "nao_existe.json")["situacao"] == "coleta_nao_feita"


def test_entrada_das_empresas_traz_cobertura_e_alertas_por_cnpj_e_nunca_cpf(entradas_reais):
    e = entradas_reais["empresas"]
    assert e["situacao"] == "dado"
    assert set(e["cobertura"]["sancoes_nao_conferidas"]) == {"CEIS", "CNEP", "CEPIM", "TCU-INIDONEOS"}
    assert e["cobertura"]["cadastro_coletado"] is False
    assert all(len(x["cnpj"]) == 14 for x in e["empresas"]) and e["empresas"]
    texto = json.dumps(e, ensure_ascii=False)
    assert "52998224725" not in texto and "529.982.247-25" not in texto


def test_entrada_da_execucao_vazia_sai_como_coleta_nao_feita(entradas_reais, banco, tmp_path):
    from onisciente.telas import entradas as ent
    x = entradas_reais["execucao"]
    assert x["situacao"] == "coleta_nao_feita" and x["empenhos"] == [] and "execucao_goiania" in x["motivo"]
    # Com eventos no banco, sai empenho a empenho, sem CPF nem nome de pessoa física.
    copia = tmp_path / "h.db"
    shutil.copyfile(banco, copia)
    con = sqlite3.connect(copia)
    from onisciente.coletores.goiania_transweb import criar_tabelas
    criar_tabelas(con)
    con.executemany("INSERT INTO despesa_eventos (tipo, empenho, data, orgao, credor, documento, valor, fonte, funcao, url, "
                    "coletado_em) VALUES (?,?,?,?,?,?,?,?,?,?,?)", [
                        ("empenho", "2026NE1", "2026-02-03", "SEMAS", "EMPRESA X", "12345678000199", 900.0, "1500", "08",
                         "https://exemplo.gov.br/e", "2026-11-27"),
                        ("liquidacao", "2026NE1", "2026-02-10", "SEMAS", "EMPRESA X", "12345678000199", 900.0, "1500", "08",
                         "https://exemplo.gov.br/l", "2026-11-27"),
                        ("empenho", "2026NE2", "2026-02-04", "SEMAS", "Fulana de Tal", "52998224725", 100.0, "1500", "08",
                         "https://exemplo.gov.br/e2", "2026-11-27")])
    con.commit()
    y = ent.execucao(con)
    con.close()
    assert y["situacao"] == "dado"
    por = {e["numero"]: e for e in y["empenhos"]}
    assert [ev["estacao"] for ev in por["2026NE1"]["eventos"]] == ["empenho", "liquidacao"]
    assert por["2026NE1"]["valor"] == 900.0 and por["2026NE1"]["credor_cnpj"] == "12345678000199"
    assert por["2026NE2"]["credor"] == "Pessoa física" and por["2026NE2"]["credor_cnpj"] == ""
    assert "52998224725" not in json.dumps(y)


def test_entrada_dos_federais_diz_que_fonte_nao_foi_lida(entradas_reais, banco, tmp_path):
    from onisciente.telas import entradas as ent
    f = entradas_reais["federais"]
    assert f["situacao"] == "coleta_nao_feita" and f["repasses"] == []
    assert all(f["origens"][o]["situacao"] == "coleta_nao_feita" for o in ("FNS", "FNDE", "Transferegov", "FNAS"))
    assert f["origens"]["FNS"]["motivo"]
    copia = tmp_path / "h.db"
    shutil.copyfile(banco, copia)
    con = sqlite3.connect(copia)
    con.execute("INSERT INTO repasses_fnas (competencia, tipo, bloco, programa, valor, planilha, origem) "
                "VALUES ('2026-01', 'SERVIÇOS', 'PSB', 'PISO BÁSICO FIXO', 2500.0, 2026, 'planilha do FNAS')")
    con.commit()
    g = ent.federais(con, hoje=date(2026, 11, 27))
    con.close()
    assert g["situacao"] == "dado" and g["origens"]["FNAS"]["linhas"] == 1
    assert g["repasses"][0] == {**g["repasses"][0], "origem": "FNAS", "mes": "2026-01", "valor": 2500.0}
    assert g["origens"]["FNS"]["situacao"] == "coleta_nao_feita"


@precisa_node
def test_coleta_nao_feita_aparece_em_cinza_e_nunca_em_roxo(site_entradas_reais):
    d = _dados(site_entradas_reais / "trilha.html")
    assert d["d-tela"]["execucao"] is None
    assert d["d-comum"]["coletas"]["execucao"]["situacao"] == "coleta_nao_feita"
    assert "execucao" not in d["d-comum"]["entradas"] and "federais" not in d["d-comum"]["entradas"]
    trilha = _desenhar(site_entradas_reais / "trilha.html", "2026-02|")["2026-02|"]["tela"]
    rio = _desenhar(site_entradas_reais / "origem.html", "2026-02|")["2026-02|"]["tela"]  # decisão do usuário de 28/11/2026: sem a metáfora do rio
    for tela, o_que in ((trilha, "execução, empenho a empenho"), (rio, "transferências federais")):
        i = tela.index("Coleta ainda não feita: " + o_que)
        quadro = tela[tela.rindex("<div class=\"vazio", 0, i):i]
        assert "roxo" not in quadro
        assert "falha do próprio sistema, não do Município" in tela
    assert "FNS: coleta ainda não feita" in rio
    # A prestação dos contratos continua "aguardando": sem execução lida, nada é cobrado do Município.
    precos = _dados(site_entradas_reais / "precos.html")["d-tela"]
    assert precos["contratos"] and {c[10] for c in precos["contratos"]} == {"aguardando"}


@precisa_node
def test_tela_do_selo_mostra_as_duas_leituras_e_as_obrigacoes(site_entradas_reais):
    tela = _desenhar(site_entradas_reais / "transparencia.html", "2026-02|")["2026-02|"]["tela"]
    assert "Diamante" in tela and "acima de 95%" in tela and "sem a nota exata publicada" in tela
    for x in ("Leitura oficial", "Leitura restritiva", "comprovada", "no teto", "5,24%", "76,41%"):
        assert x in tela
    for x in ("F1", "F5", "C1", "C4", "Fundo Municipal de Assistência Social", "Conselho Municipal de Assistência Social"):
        assert x in tela
    secs = _dados(site_entradas_reais / "secretarias.html")["d-tela"]["transparencia"]
    assert [o["id"] for o in secs[FMAS]["obrigacoes"]] == ["F1", "F2", "F3", "F4", "F5"]


@precisa_node
def test_tela_das_empresas_mostra_cobertura_e_sancoes_nao_conferidas(site_entradas_reais):
    d = _dados(site_entradas_reais / "empresas.html")
    assert set(d["d-tela"]["cobertura"]["sancoes_nao_conferidas"]) == {"CEIS", "CNEP", "CEPIM", "TCU-INIDONEOS"}
    tela = _desenhar(site_entradas_reais / "empresas.html", "2026-02|")["2026-02|"]["tela"]
    assert "O que a conferência das empresas já cobre" in tela and "CEIS não conferido" in tela
    assert "cadastro não coletado" in tela
    assert "Aguardando a coleta das empresas" not in tela
    assert "52998224725" not in json.dumps(d) and "529.982.247-25" not in json.dumps(d)


def test_comando_telas_escreve_as_entradas_ao_lado_do_banco_de_teste(banco, tmp_path):
    from onisciente.__main__ import main
    copia = tmp_path / "b" / "historico.db"
    copia.parent.mkdir()
    shutil.copyfile(banco, copia)
    assert main(["telas", "--banco", str(copia), "--destino", str(tmp_path / "site")]) == 0
    for nome in ("selo_transparencia", "empresas", "execucao", "federais"):
        assert (copia.parent / "entradas" / f"{nome}.json").is_file()
    d = _dados(tmp_path / "site" / "trilha.html")
    assert d["d-comum"]["coletas"]["execucao"]["situacao"] == "coleta_nao_feita"


# ---------------------------------------------------------------------------------------------
# Etapas, condições e linguagem direta (decisão do usuário de 28/11/2026: sem a metáfora do rio)
# ---------------------------------------------------------------------------------------------

def _visivel(html: str) -> str:
    """O texto que a pessoa lê: a página sem as marcas, com os dados embutidos (viram texto no navegador)."""
    return re.sub(r"<[^>]+>", " ", html)


@precisa_node
def test_nenhuma_metafora_nas_telas_nem_no_app(site, site_com_entradas):
    from onisciente.linguagem import metaforas
    for estatico in ("app.js", "app.css"):
        assert metaforas((site / estatico).read_text(encoding="utf-8")) == [], estatico
    for raiz in (site, site_com_entradas):
        for p in PAGINAS:
            html = (raiz / f"{p}.html").read_text(encoding="utf-8")
            assert metaforas(html) == [], (raiz.name, p, metaforas(html))
            for recorte, s in _desenhar(raiz / f"{p}.html", "2026-02|", f"2026-02|{FMAS}").items():
                for parte in ("tela", "sankey", "caminho"):
                    assert metaforas(_visivel(s[parte])) == [], (p, recorte, parte, metaforas(_visivel(s[parte])))
    assert not (site / "rio.html").exists() and (site / "origem.html").exists()


def _etapas_da_inicial(tela: str) -> dict[str, dict]:
    out = {}
    for m in re.finditer(r'<a class="etapa [a-z]+" data-etapa="([a-z]+)" href="([^"]+)"(.*?)</a>', tela, re.S):
        conds = dict(re.findall(r'<span class="cd (conforme|alerta|sem_dado)[^"]*">.*?<b>(\d+)</b>', m.group(3), re.S))
        out[m.group(1)] = {"href": m.group(2).replace("&amp;", "&"), **{k: int(v) for k, v in conds.items()}}
    return out


@precisa_node
def test_inicio_tem_o_diagrama_das_etapas_e_toda_ficha_a_dois_cliques(site):
    comum = _dados(site / "index.html")["d-comum"]
    ids = [e["id"] for e in comum["etapas"]]
    assert ids == ["origem", "orcamento", "contratacao", "liquidacao", "pagamento", "prestacao"]
    todas = {f["codigo"] for f in _dados(site / "indicios.html")["d-tela"]["fichas"]}
    for c, s in (("2026-02", ""), ("2026-02", FMAS), ("2026-01", "")):
        rec = f"{c}|{s}"
        tela = _desenhar(site / "index.html", rec)[rec]["tela"]
        etapas = _etapas_da_inicial(tela)
        assert list(etapas) == ids, rec                                  # as seis, na ordem do gasto
        sistema = re.search(r'<p class="etapa-sistema"><a href="([^"]+)">.*?<b>(\d+)</b>', tela, re.S)
        assert sistema and "tema=sistema" in sistema.group(1)
        # clique 1: a etapa abre a lista dela; clique 2: a ficha (details) abre com a prova
        alcancadas = set()
        destinos = {e: v["href"] for e, v in etapas.items()} | {"sistema": sistema.group(1).replace("&amp;", "&")}
        for nome, href in destinos.items():
            pagina, _, busca = href.partition("?")
            assert pagina == "indicios.html", href
            q = dict(x.split("=", 1) for x in busca.split("&"))
            assert q["c"] == c and q.get("s", "") == s
            extra = "&".join(f"{k}={v}" for k, v in q.items() if k not in ("c", "s"))
            lista = _desenhar(site / "indicios.html", f"{c}|{s}|{extra}")[f"{c}|{s}|{extra}"]
            assert not lista["erros"]
            codigos = re.findall(r'<details class="ficha [^"]*" id="[^"]+" data-codigo="([^"]+)"', lista["fichas"])
            assert "Mostrar mais" not in lista["fichas"]                   # a lista da etapa sai inteira
            esperado = int(sistema.group(2)) if nome == "sistema" else etapas[nome]["alerta"] + etapas[nome]["sem_dado"]
            assert len(codigos) == esperado, (rec, nome)
            alcancadas |= set(codigos)
        tudo = _desenhar(site / "indicios.html", rec)[rec]["fichas"]
        ativas = set(re.findall(r'data-codigo="([^"]+)"', tudo))
        assert ativas <= todas and ativas == alcancadas, rec               # nenhuma ficha fora das etapas


def test_cada_condicao_tem_o_seu_icone_igual_em_todas_as_paginas(site):
    simbolos = {}
    for p in PAGINAS:
        html = (site / f"{p}.html").read_text(encoding="utf-8")
        sprite = re.search(r'<svg[^>]*class="simbolos"[^>]*>(.*?)</svg>', html, re.S)
        assert sprite, p
        achados = dict(re.findall(r'<symbol id="i-([a-z]+)"[^>]*>(.*?)</symbol>', sprite.group(1), re.S))
        for cond in ("conforme", "alerta", "semdado"):
            assert html.count(f'<symbol id="i-{cond}"') == 1, (p, cond)
        for etapa in ("origem", "orcamento", "contratacao", "liquidacao", "pagamento", "prestacao"):
            assert etapa in achados, (p, etapa)
        simbolos.setdefault("primeira", achados)
        assert achados == simbolos["primeira"], p                        # o mesmo desenho em todas
    s = simbolos["primeira"]
    assert len({s["conforme"], s["alerta"], s["semdado"]}) == 3          # três desenhos diferentes
    assert len({s[e] for e in ("origem", "orcamento", "contratacao", "liquidacao", "pagamento", "prestacao")}) == 6


@precisa_node
def test_selos_e_fichas_usam_o_icone_da_condicao(site):
    r = _desenhar(site / "indicios.html", "2026-02|")["2026-02|"]
    for m in re.finditer(r'<details class="ficha [^"]*\b(alerta|sem_dado)\b[^"]*".*?<summary>(.*?)</summary>', r["fichas"], re.S):
        icone = "alerta" if m.group(1) == "alerta" else "semdado"
        assert f'<use href="#i-{icone}"/>' in m.group(2)
    assert r["fichas"].count("<details") >= 2
    origem = _desenhar(site / "origem.html", "2026-02|")["2026-02|"]["tela"]
    for cor, icone in (("verde", "conforme"), ("cinza", "semdado"), ("indicio", "alerta"), ("roxo", "semdado")):
        for m in re.finditer(rf'<span class="selo {cor}">(<svg.*?</svg>)', origem):
            assert f'href="#i-{icone}"' in m.group(1), (cor, m.group(1))
    inicio = _desenhar(site / "index.html", "2026-02|")["2026-02|"]["tela"]
    for cd, icone in (("conforme", "conforme"), ("alerta", "alerta"), ("sem_dado", "semdado")):
        assert re.search(rf'<svg class="ic cond {cd}[^"]*"[^>]*><use href="#i-{icone}"/>', inicio), cd
