"""Integração: o adaptador do Cadê o Queijo, o parecer, os coletores e a linha de comando.

Nada aqui usa a rede: os coletores recebem um leitor falso.
"""

import json
import re
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone

import pytest

from onisciente import RAIZ
from onisciente.__main__ import competencias_disponiveis, main
from onisciente.adaptadores import cadeoqueijo
from onisciente.coletores import base, leis, siconfi
from onisciente.nucleo import Selo, Verificacao
from onisciente.parecer import html


@pytest.fixture(scope="module")
def competencia():
    disponiveis = competencias_disponiveis()
    assert disponiveis, "o repositório deve ter verificações mensais do Cadê o Queijo"
    return disponiveis[-1]


@pytest.fixture(scope="module")
def panorama(competencia):
    return cadeoqueijo.montar(competencia)


def test_adaptador_le_o_cade_o_queijo(panorama, competencia):
    verif = json.loads((RAIZ / "relatorios" / "mensal" / f"verificacao_{competencia}.json")
                       .read_text(encoding="utf-8"))
    codigos = {f.codigo for f in panorama.fichas}
    assert {a["codigo"] for a in verif["achados"]} <= codigos  # nenhum achado do mês se perde
    assert len(codigos) == len(panorama.fichas)                 # nenhum código repetido
    # As fichas do Cadê o Queijo chegam marcadas; as outras são do próprio Onisciente (pisos e duas vias).
    proprias = {f.codigo for f in panorama.fiscal.fichas(competencia)} if panorama.fiscal else set()
    assert all(f.origem == "cadeoqueijo" or (f.origem == "onisciente" and f.codigo in proprias)
               for f in panorama.fichas)
    assert {a["codigo"] for a in verif["achados"]} <= {f.codigo for f in panorama.fichas if f.origem == "cadeoqueijo"}
    assert panorama.integridade is not None
    assert all(a.selo is Selo.ROXO for a in panorama.ausencias)


def test_selo_antigo_preservado(panorama, competencia):
    verif = json.loads((RAIZ / "relatorios" / "mensal" / f"verificacao_{competencia}.json")
                       .read_text(encoding="utf-8"))
    por_codigo = {f.codigo: f for f in panorama.fichas}
    for a in verif["achados"]:
        assert por_codigo[a["codigo"]].verificacao is Verificacao.de(a["selo"])


def test_textos_publicos_sem_marcador_interno(panorama):
    tudo = json.dumps(panorama.como_dict(), ensure_ascii=False)
    assert "URL_TRANSPARENCIA" not in tudo


def test_competencia_sem_verificacao_falha_as_claras(tmp_path):
    with pytest.raises(FileNotFoundError):
        cadeoqueijo.montar("2026-10", raiz=tmp_path)


def test_parecer_tem_as_nove_secoes_e_e_autonomo(panorama):
    pagina = html.gerar(panorama, hoje=date(2026, 11, 26))
    for n, titulo in enumerate(["Em uma frase", "O rio", "Pisos e tetos", "As contas, uma a uma",
                                "Preço e entrega", "Prestação de contas", "Fichas", "Ausências",
                                "Custódia"], 1):
        assert f"{n}. {titulo}" in pagina
    assert "O que está em ordem foi omitido." in pagina
    assert not re.search(r'<(script|link)\b', pagina)          # nenhuma biblioteca externa
    assert "<svg" in pagina
    assert pagina.count('class="ficha ') == len(panorama.fichas)


def test_parecer_escapa_o_texto_das_fontes(panorama):
    from onisciente.nucleo.indicios import Familia, emitir
    panorama.fichas.append(emitir(codigo="T-1", familia=Familia.VIN, titulo="<script>x</script>",
                                  gravidade="media", como_deveria="d", norma="n", como_esta="e",
                                  niveis=["B"]))
    try:
        pagina = html.gerar(panorama)
        assert "<script>x</script>" not in pagina and "&lt;script&gt;" in pagina
    finally:
        panorama.fichas.pop()


def test_indice_de_pareceres():
    pagina = html.indice([("2026-09", "parecer_2026-09.html"), ("2026-10", "parecer_2026-10.html")],
                         "Prefeitura de Goiânia")
    assert pagina.index("Outubro de 2026") < pagina.index("Setembro de 2026")


# --- Coletores, sem rede ------------------------------------------------------------

def _leitor(respostas):
    def ler(url, **_):
        for chave, valor in respostas.items():
            if chave in url:
                if valor is None:
                    return base.Leitura(False, url, erro="HTTP 404")
                return base.Leitura(True, url, valor.encode(),
                                    original=base.Original(url, "2026-11-26", "0" * 64))
        return base.Leitura(False, url, erro="sem rede")
    return ler


def test_cabecalho_do_ctresb():
    md = "---\ntitulo: \"Lei X\"\nrevogada: true\n---\n# Lei X\n"
    assert leis.cabecalho(md) == {"titulo": "Lei X", "revogada": True}
    assert leis.cabecalho("sem cabeçalho") == {}


def test_conferir_ctresb_marca_revogada_e_falha():
    falso = _leitor({"lcp-101": "---\nrevogada: false\n---\n", "lei-12527": "---\nrevogada: true\n---\n"})
    resultado = {r["caminho"]: r for r in leis.conferir_ctresb(ler_url=falso)}
    lrf = next(r for c, r in resultado.items() if "lcp-101" in c)
    lai_ = next(r for c, r in resultado.items() if "lei-12527" in c)
    assert lrf["ok"] and lrf["revogada"] is False
    assert lai_["revogada"] is True
    assert any(not r["ok"] for r in resultado.values())


def test_texto_do_sileg_sem_html():
    pagina = "<html><style>x{}</style><body><p>Art. 1º&nbsp;Fica&#160;criado</p><br>Art. 2º</body></html>"
    assert leis.texto_do_html(pagina) == "Art. 1º Fica criado\nArt. 2º"


def test_url_e_leitura_do_siconfi():
    u = siconfi.url("rreo", ente=5208707, exercicio=2025, periodo=6, anexo="RREO-Anexo 12")
    assert "co_tipo_demonstrativo=RREO" in u and "id_ente=5208707" in u and "Anexo+12" in u
    itens = [{"conta": "Percentual de aplicação em ASPS sobre a receita", "coluna": "%", "valor": 17.2}]
    assert siconfi.valor_da_conta(itens, "percentual", "ASPS") == 17.2
    assert siconfi.valor_da_conta(itens, "inexistente") is None


def test_estado_da_coleta_e_fonte_parada(tmp_path):
    arq = tmp_path / "estado.json"
    base.registrar("siconfi", base.Leitura(False, "https://x", erro="HTTP 404"), caminho=arq)
    estado = json.loads(arq.read_text(encoding="utf-8"))
    [ficha] = base.fontes_paradas(estado, date.today())
    assert ficha.familia.value == "SIS" and "nunca" in ficha.como_esta
    ontem = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    estado["fontes"]["siconfi"]["ultimo_sucesso"] = ontem
    estado["fontes"]["siconfi"].pop("erro")          # a última leitura deu certo
    assert base.fontes_paradas(estado, date.today()) == []


def test_fonte_mensal_nao_e_parada_no_meio_do_mes(tmp_path):
    arq = tmp_path / "estado.json"
    base.registrar("ctresb", base.Leitura(True, "https://x"), caminho=arq, ciclo_dias=31)
    estado = json.loads(arq.read_text(encoding="utf-8"))
    vinte_dias = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
    estado["fontes"]["ctresb"]["ultimo_sucesso"] = vinte_dias
    assert base.fontes_paradas(estado, date.today()) == []
    quarenta_dias = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    estado["fontes"]["ctresb"]["ultimo_sucesso"] = quarenta_dias
    assert len(base.fontes_paradas(estado, date.today())) == 1


def test_fonte_que_falhou_na_ultima_leitura_e_parada_na_hora(tmp_path):
    arq = tmp_path / "estado.json"
    base.registrar("ctresb", base.Leitura(True, "https://x"), caminho=arq, ciclo_dias=31)
    base.registrar("ctresb", base.Leitura(False, "https://x", erro="HTTP 500"), caminho=arq,
                   ciclo_dias=31)
    estado = json.loads(arq.read_text(encoding="utf-8"))
    [ficha] = base.fontes_paradas(estado, date.today())
    assert "HTTP 500" in ficha.como_esta


def test_siconfi_registra_cada_anexo_separado(tmp_path, monkeypatch):
    arq = tmp_path / "estado.json"
    monkeypatch.setattr(base, "ESTADO", arq)
    monkeypatch.setattr(siconfi, "registrar",
                        lambda fonte, leitura, **kw: base.registrar(fonte, leitura, caminho=arq, **kw))
    falha = _leitor({"Anexo+12": None})
    siconfi.coletar("rreo", ente=1, exercicio=2025, periodo=6, anexo="RREO-Anexo 12",
                    ler_url=falha, pasta=tmp_path)
    siconfi.coletar("rreo", ente=1, exercicio=2025, periodo=6, anexo="RREO-Anexo 8",
                    ler_url=_leitor({"Anexo+8": '{"items": []}'}), pasta=tmp_path)
    fontes = json.loads(arq.read_text(encoding="utf-8"))["fontes"]
    assert set(fontes) == {"siconfi-rreo-rreo-anexo-12", "siconfi-rreo-rreo-anexo-8"}
    assert fontes["siconfi-rreo-rreo-anexo-12"]["erro"] == "HTTP 404"
    assert [f.codigo for f in base.fontes_paradas({"fontes": fontes}, date.today())] == \
        ["SIS-COLETA-SICONFI-RREO-RREO-ANEXO-12"]


def test_vinculo_conta_so_entidades_do_exercicio():
    assert cadeoqueijo._ativa_no_ano({"primeiro": "2025-03-01", "ultimo": "2026-02-01"}, "2026")
    assert not cadeoqueijo._ativa_no_ano({"primeiro": "2024-03-01", "ultimo": "2025-12-30"}, "2026")
    assert not cadeoqueijo._ativa_no_ano({}, "2026")


def test_ler_sem_rede_nao_levanta_excecao():
    leitura = base.ler("http://127.0.0.1:9/inexistente", tempo=2)
    assert not leitura.ok and leitura.erro


# --- Linha de comando e o motor antigo ------------------------------------------------

def test_comando_verificar_passa(capsys):
    assert main(["verificar"]) == 0
    assert "Tudo conferido." in capsys.readouterr().out


def test_regressao_do_cade_o_queijo():
    """Os sete erros históricos do Cadê o Queijo são testes obrigatórios do Onisciente."""
    r = subprocess.run([sys.executable, str(RAIZ / "testes" / "regressao_cadeoqueijo.py")],
                       capture_output=True, text=True, cwd=RAIZ, timeout=600)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    assert "7/7" in r.stdout


def test_motor_antigo_compila():
    pasta = RAIZ / "cadeoqueijo"
    arquivos = sorted(pasta.glob("*.py"))
    assert len(arquivos) > 60
    for arq in arquivos:
        compile(arq.read_text(encoding="utf-8"), str(arq), "exec")
