"""Agenda própria: os fluxos do GitHub com relógio, a coleta incremental, a falha do parecer
como falha do sistema, a série desde 2019, o Diário Oficial, a tempestividade e o SQLite."""

import json
import re
import sqlite3
import time
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
import yaml

from onisciente import RAIZ, agenda, historico, partes, tempo
from onisciente.coletores import base

FLUXOS = RAIZ / ".github" / "workflows"
BANCO_REAL = RAIZ / "dados" / "onisciente" / "historico.db"
CADENCIA = {"diaria": "diario", "precos": "semanal", "mensal": "mensal", "leis": "semanal",
            "serie": "mensal", "parecer": "semanal"}
# Comandos do Onisciente que nunca podem ter o erro engolido num fluxo.
COMANDOS = re.compile(r"python\s+-m\s+onisciente(\.agenda\b|\s+(parecer|historico|coletar|diagnostico)\b)")
ENGOLE = re.compile(r"\|\|\s*(true|echo|:|exit\s+0)\b")


def _fluxo(nome: str) -> dict:
    d = yaml.safe_load((FLUXOS / nome).read_text(encoding="utf-8"))
    d["on"] = d.pop(True, d.get("on"))          # o PyYAML lê a chave "on" como verdadeiro
    return d


def _passos(d: dict) -> list[dict]:
    return [p for job in d["jobs"].values() for p in job["steps"]]


def _cadencia(cron: str) -> str:
    _, _, dia, mes, semana = cron.split()
    if dia == "*" and semana == "*":
        return "diario"
    if dia == "*" and mes == "*":
        return "semanal"
    if semana == "*" and mes == "*" and dia != "*":
        return "mensal"
    return "outra"


# --- Os fluxos ---------------------------------------------------------------------------

def test_cada_rodada_tem_fluxo_com_relogio_proprio():
    for nome, rodada in agenda.RODADAS.items():
        assert rodada.fluxo == f"onisciente-agenda-{nome}.yml", nome
        d = _fluxo(rodada.fluxo)
        crons = [c["cron"] for c in d["on"]["schedule"]]
        assert crons, nome
        assert CADENCIA[nome] in {_cadencia(c) for c in crons}, (nome, crons)
        assert "workflow_dispatch" in d["on"]
        comandos = [p.get("run", "") for p in _passos(d)]
        assert any(re.search(rf"python -m onisciente\.agenda {nome}\b", c) for c in comandos), nome


def test_agenda_cobre_os_motores_e_as_fontes_pedidas():
    motores = {nome: {m for g in r.grupos for m in g.motores} for nome, r in agenda.RODADAS.items()}
    assert {"pncp", "pncp_detalhe", "sileg", "querido_diario"} <= motores["diaria"]       # 151, 140
    assert {"siops", "siope", "tesouro", "msc", "siconfi"} <= motores["mensal"]            # 143, 144
    assert "normas" in motores["leis"]                                                    # 94
    precos = agenda.RODADAS["precos"].grupos
    assert any("pncp_detalhe" in g.motores and "precos" in g.reabrir for g in precos)    # 152
    assert {"pncp", "sileg", "siconfi"} <= motores["serie"]                               # 119
    todos = set().union(*motores.values())
    assert todos <= set(historico.MOTORES)
    # Funciona sozinho: nenhum motor fica sem relógio.
    assert set(historico.MOTORES) <= todos, set(historico.MOTORES) - todos
    for r in agenda.RODADAS.values():
        for g in r.grupos:
            assert g.modo in ("janela", "continuar")
            # PNCP e detalhe continuam de onde pararam; os demais somam só a janela.
            assert (g.modo == "continuar") == bool(set(g.motores) & {"pncp", "pncp_detalhe"}), g


def test_fluxos_que_gravam_o_banco_nao_se_atropelam():
    nomes = [r.fluxo for r in agenda.RODADAS.values()] + ["onisciente-historico.yml"]
    for nome in nomes:
        c = _fluxo(nome)["concurrency"]
        assert c == {"group": "onisciente-banco", "cancel-in-progress": False}, nome


def test_coleta_agendada_publica_banco_e_relatorios_e_e_incremental():
    for nome, rodada in agenda.RODADAS.items():
        d = _fluxo(rodada.fluxo)
        passos = _passos(d)
        publicar = [p for p in passos if "git commit" in p.get("run", "")]
        assert len(publicar) == 1, nome
        assert "cancelled()" in publicar[0].get("if", ""), nome     # publica também depois de falha
        assert "relatorios/onisciente" in publicar[0]["run"] and "docs/onisciente" in publicar[0]["run"]
        if nome != "parecer":
            assert "dados/onisciente/historico.db" in publicar[0]["run"], nome
        for p in passos:                       # a agenda nunca refaz o banco do zero
            assert "onisciente historico" not in p.get("run", ""), nome
    historico_yml = _fluxo("onisciente-historico.yml")
    assert set(historico_yml["on"]) == {"workflow_dispatch"}      # a reconstrução só roda à mão


def test_nenhum_fluxo_engole_o_erro_do_parecer_nem_da_coleta():
    vistos = 0
    for arq in sorted(FLUXOS.glob("*.yml")):
        d = _fluxo(arq.name)
        for p in _passos(d):
            run = p.get("run", "")
            if not COMANDOS.search(run):
                continue
            vistos += 1
            assert not p.get("continue-on-error"), (arq.name, p.get("name"))
            for linha in run.splitlines():
                if COMANDOS.search(linha):
                    assert not ENGOLE.search(linha), (arq.name, linha)
    assert vistos >= 8
    parecer = [arq.name for arq in FLUXOS.glob("*.yml")
               if re.search(r"onisciente(\.agenda)? parecer", arq.read_text(encoding="utf-8"))]
    assert parecer == ["onisciente-agenda-parecer.yml"]


# --- Coleta incremental com fontes falsas ---------------------------------------------------

class QDFalso:
    """Querido Diário que responde uma edição por mês, com o valor do sufixo dado."""

    def __init__(self, sufixo="a"):
        self.sufixo, self.lidas = sufixo, []

    def __call__(self, url, **_):
        self.lidas.append(url)
        u = urlparse(url)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if "queridodiario" in u.netloc:
            corpo = {"total_gazettes": 1, "gazettes": [
                {"date": q["published_since"], "edition": "1", "url": f"https://x/{self.sufixo}.pdf"}]}
            return base.Leitura(True, url, json.dumps(corpo).encode(), http=200)
        return base.Leitura(False, url, erro="HTTP 404", http=404)


def _sem_pausa():
    return dict(dormir=lambda s: None, pausa=0)


def test_janela_soma_ao_banco_sem_refazer_o_que_ficou_fora(tmp_path):
    caminho = tmp_path / "historico.db"
    historico.rodar("2025-01", "2025-03", motores=("querido_diario",), caminho=caminho, hoje=date(2026, 1, 1),
                    ler_url=QDFalso("velho"), **_sem_pausa()).fechar()
    novo = QDFalso("novo")
    grupo = agenda.Grupo(("querido_diario",), janela=2)
    r = agenda.coletar_grupo(grupo, ("2025-03", "2025-04"), caminho=caminho, hoje=date(2026, 1, 1),
                             ler_url=novo, **_sem_pausa())
    assert r["quebrados"] == {}
    pedidos = {parse_qs(urlparse(u).query)["published_since"][0][:7] for u in novo.lidas}
    assert pedidos == {"2025-03", "2025-04"}                    # só a janela foi lida de novo
    banco = historico.Banco.abrir(caminho)
    urls = dict(banco.consultar("SELECT mes, url FROM diario_oficial WHERE fonte = 'querido_diario'"))
    meses = banco.consultar("SELECT mes, COUNT(*) FROM diario_oficial_mes GROUP BY mes ORDER BY mes")
    [(n_coletas,)] = banco.consultar("SELECT COUNT(*) FROM coletas WHERE motor = 'qd' AND mes = '2025-03'")
    assert agenda.intervalo_do_banco(banco) == ("2025-01", "2025-04")
    banco.con.close()
    assert urls == {"2025-01": "https://x/velho.pdf", "2025-02": "https://x/velho.pdf",
                    "2025-03": "https://x/novo.pdf", "2025-04": "https://x/novo.pdf"}
    assert meses == [("2025-01", 1), ("2025-02", 1), ("2025-03", 1), ("2025-04", 1)]   # sem dobrar
    assert n_coletas == 2                                       # as chamadas da janela trocadas, não somadas


def test_fonte_fora_do_ar_na_janela_nao_apaga_o_que_o_banco_ja_tinha(tmp_path):
    caminho = tmp_path / "historico.db"
    historico.rodar("2025-01", "2025-02", motores=("querido_diario",), caminho=caminho, hoje=date(2026, 1, 1),
                    ler_url=QDFalso("velho"), **_sem_pausa()).fechar()

    def fora_do_ar(url, **_):
        return base.Leitura(False, url, erro="URLError: sem rota")
    agenda.coletar_grupo(agenda.Grupo(("querido_diario",), janela=2), ("2025-02", "2025-03"), caminho=caminho,
                         hoje=date(2026, 1, 1), ler_url=fora_do_ar, **_sem_pausa())
    banco = historico.Banco.abrir(caminho)
    meses = dict(banco.consultar("SELECT mes, erro FROM diario_oficial_mes"))
    urls = dict(banco.consultar("SELECT mes, url FROM diario_oficial"))
    falhas = banco.consultar("SELECT COUNT(*) FROM coletas WHERE motor = 'qd' AND mes = '2025-02' AND ok = 0")
    banco.con.close()
    assert meses["2025-02"] is None and urls["2025-02"] == "https://x/velho.pdf"   # o dado bom ficou
    assert "URLError" in meses["2025-03"]                       # mês sem dado antigo: a falha aparece
    assert falhas[0][0] > 0                                     # e a tentativa falha fica registrada


def _pncp_falso(lidas):
    def ler(url, **_):
        lidas.append(url)
        u = urlparse(url)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if "pncp" in u.netloc and "contratos" in u.path:
            mes = q["dataInicial"][:6]
            corpo = {"data": [{"numeroControlePNCP": f"K-{mes}", "objetoContrato": "Serviço",
                               "valorGlobal": 1, "dataPublicacaoPncp": f"{mes[:4]}-{mes[4:]}-10"}],
                     "totalPaginas": 1}
            return base.Leitura(True, url, json.dumps(corpo).encode(), http=200)
        if "pncp" in u.netloc:
            return base.Leitura(True, url, b"", http=204)
        return base.Leitura(False, url, erro="HTTP 404", http=404)
    return ler


def test_pncp_continua_e_le_so_os_meses_novos_e_os_reabertos(tmp_path, monkeypatch):
    from onisciente import config
    alvo = config.carregar_alvo()
    monkeypatch.setattr(config, "carregar_alvo", lambda *a, **k: alvo.__class__(
        **{**alvo.__dict__, "pncp_cnpjs": ("11111111000111",)}))
    caminho = tmp_path / "historico.db"
    historico.rodar("2025-01", "2025-03", motores=("pncp",), caminho=caminho, hoje=date(2025, 6, 1),
                    ler_url=_pncp_falso([]), **_sem_pausa()).fechar()
    lidas: list[str] = []
    grupo = agenda.Grupo(("pncp",), janela=2, modo="continuar", reabrir=("meses",))
    agenda.coletar_grupo(grupo, ("2025-03", "2025-04"), caminho=caminho, hoje=date(2025, 6, 1),
                         ler_url=_pncp_falso(lidas), **_sem_pausa())
    meses_lidos = {parse_qs(urlparse(u).query)["dataInicial"][0][:6] for u in lidas}
    assert meses_lidos == {"202503", "202504"}                  # janeiro e fevereiro ficaram como estavam
    banco = historico.Banco.abrir(caminho)
    contratos = {m for (m,) in banco.consultar("SELECT mes FROM contratos_pncp")}
    assert agenda.intervalo_do_banco(banco) == ("2025-01", "2025-04")
    banco.con.close()
    # O ano lido de uma vez na primeira rodada guardou o contrato de janeiro; ficou, sem ser relido.
    assert contratos == {"2025-01", "2025-03", "2025-04"}


def test_reabrir_meses_e_precos_so_tira_a_janela(tmp_path):
    banco = historico.Banco(tmp_path / "h.db")
    agenda._guardar_meta(banco, "pncp_janelas", [{"cnpj": "1", "meses": ["2026-01", "2026-10", "2026-11"],
                                                  "lida": True}, {"cnpj": "2", "meses": ["2026-11"], "lida": True}])
    agenda._guardar_meta(banco, "pncp_procura", ["2026-09", "2026-10", "2026-11"])
    agenda._guardar_meta(banco, "pncp_detalhe_lidos", [
        "cobrancas 1 2026-10", "cobrancas 1 2026-09", "itens 1 2026", "itens 1 2025", "itens 1 2026-10 inteiro",
        "itens 1 2026-03", "amparos 6 2026-11", "compra X", "preco 10 2026-2", "preco 10 2026-1",
        "preco 10 2025-2", "preco 10 2025-1"])
    r = agenda.reabrir_meses(banco, ["2026-10", "2026-11"])
    assert r == {"janelas_reabertas": 3, "detalhe_reaberto": 4}
    assert agenda._meta_json(banco, "pncp_janelas", None) == [{"cnpj": "1", "meses": ["2026-01"], "lida": True}]
    assert agenda._meta_json(banco, "pncp_procura", None) == ["2026-09"]
    assert agenda.reabrir_precos(banco, date(2026, 11, 27)) == 2
    assert sorted(agenda._meta_json(banco, "pncp_detalhe_lidos", None)) == [
        "cobrancas 1 2026-09", "compra X", "itens 1 2025", "itens 1 2026-03", "preco 10 2025-1", "preco 10 2025-2"]
    banco.con.close()


def test_serie_estende_para_tras_ate_2019(tmp_path, monkeypatch):
    assert agenda.inicio_da_serie() == "2019-01"                # primeiro_exercicio do alvo
    caminho = tmp_path / "historico.db"
    historico.rodar("2020-06", "2020-08", motores=("querido_diario",), caminho=caminho, hoje=date(2026, 1, 1),
                    ler_url=QDFalso(), **_sem_pausa()).fechar()
    assert agenda.proxima_janela_da_serie(caminho, "2019-01") == ("2019-06", "2020-05")
    monkeypatch.setitem(agenda.RODADAS, "serie", agenda.Rodada(
        "serie", "Série", "teste", 31, (agenda.Grupo(("querido_diario",), janela=12),)))
    for _ in range(3):
        agenda.coletar("serie", caminho=caminho, hoje=date(2026, 1, 1), ler_url=QDFalso(), **_sem_pausa())
    banco = historico.Banco.abrir(caminho)
    assert agenda.intervalo_do_banco(banco) == ("2019-01", "2020-08")
    [(n,)] = banco.consultar("SELECT COUNT(DISTINCT mes) FROM diario_oficial_mes")
    banco.con.close()
    assert n == 20                                              # 2019-01 a 2020-08, sem buraco
    assert agenda.coletar("serie", caminho=caminho, hoje=date(2026, 1, 1), ler_url=QDFalso(),
                          **_sem_pausa())["nota"].startswith("série completa")


# --- Falha é falha do sistema --------------------------------------------------------------

def _destinos(tmp_path):
    return dict(estado=tmp_path / "agenda_estado.json", estado_coleta=tmp_path / "coleta.json",
                pagina_destino=tmp_path / "agenda.html")


def test_parecer_que_falha_sai_com_erro_e_deixa_registro_visivel(tmp_path, monkeypatch):
    import onisciente.__main__ as cli

    def quebra(argv=None):
        raise RuntimeError("verificação mensal ilegível")
    monkeypatch.setattr(cli, "main", quebra)
    d = _destinos(tmp_path)
    assert agenda.executar("parecer", **d) == 1
    estado = json.loads(d["estado"].read_text(encoding="utf-8"))["rodadas"]["parecer"]
    assert estado["ok"] is False and "verificação mensal ilegível" in estado["erro"]
    pagina = d["pagina_destino"].read_text(encoding="utf-8")
    assert "falhou" in pagina and "verificação mensal ilegível" in pagina and "—" not in pagina
    fichas = base.fontes_paradas(json.loads(d["estado_coleta"].read_text(encoding="utf-8")), date.today())
    assert [f.codigo for f in fichas] == ["SIS-COLETA-AGENDA-PARECER"]

    monkeypatch.setattr(cli, "main", lambda argv=None: 0)        # o parecer volta: a ficha sai
    assert agenda.executar("parecer", **d) == 0
    assert base.fontes_paradas(json.loads(d["estado_coleta"].read_text(encoding="utf-8")), date.today()) == []


def test_motor_quebrado_deixa_a_rodada_vermelha(tmp_path, monkeypatch):
    def quebra(ctx):
        raise ValueError("formato novo")
    monkeypatch.setattr(historico, "motor_sileg", quebra)
    monkeypatch.setitem(agenda.RODADAS, "diaria", agenda.Rodada(
        "diaria", "Diário", "teste", 1, (agenda.Grupo(("sileg",), janela=1),), fluxo="x.yml"))
    d = _destinos(tmp_path)
    assert agenda.executar("diaria", caminho=tmp_path / "h.db", hoje=date(2026, 11, 27), **d) == 1
    estado = json.loads(d["estado"].read_text(encoding="utf-8"))["rodadas"]["diaria"]
    assert "motor sileg quebrou" in estado["erro"]


# --- Diário Oficial: a via que responde e os dias de publicação ------------------------------

def test_querido_diario_troca_para_a_via_que_responde(tmp_path):
    lidas = []

    def ler(url, **_):
        lidas.append(url)
        if url.startswith(historico.QUERIDO_DIARIO_VIAS[0]):
            return base.Leitura(False, url, erro="URLError: [SSL: SSLV3_ALERT_HANDSHAKE_FAILURE]")
        return QDFalso()(url)
    banco = historico.rodar("2025-01", "2025-02", motores=("querido_diario",), caminho=tmp_path / "h.db",
                            hoje=date(2026, 1, 1), ler_url=ler, **_sem_pausa())
    meses = dict(banco.consultar("SELECT mes, edicoes FROM diario_oficial_mes"))
    via = dict(banco.consultar("SELECT chave, valor FROM meta"))["qd_via"]
    banco.fechar()
    assert meses == {"2025-01": 1, "2025-02": 1}
    assert via == historico.QUERIDO_DIARIO_VIAS[1]
    ruins = [i for i, u in enumerate(lidas) if u.startswith(historico.QUERIDO_DIARIO_VIAS[0])]
    boas = [i for i, u in enumerate(lidas) if u.startswith(historico.QUERIDO_DIARIO_VIAS[1])]
    assert ruins and max(ruins) < min(boas)                     # a via que caiu não é tentada de novo
    assert historico.QUERIDO_DIARIO_VIAS[0] == "https://queridodiario.ok.org.br/api/gazettes"


def test_sileg_conta_os_dias_de_publicacao_no_coletor(tmp_path):
    ids = ["./do_20261103_000001.pdf", "./do_20261103_000002_suplemento.pdf", "./do_20261104_000003.pdf",
           "./do_20261110_000004.pdf"]

    def ler(url, **_):
        q = parse_qs(urlparse(url).query)
        docs = [{"id": i} for i in ids] if q.get("fl") else []
        n = len(ids) if "attr_content" not in q["q"][0] else 1
        return base.Leitura(True, url, json.dumps({"response": {"numFound": n, "docs": docs}}).encode(), http=200)
    banco = historico.rodar("2026-11", "2026-11", motores=("sileg",), caminho=tmp_path / "h.db",
                            hoje=date(2026, 11, 27), ler_url=ler, **_sem_pausa())
    dias = banco.consultar("SELECT data, edicoes FROM diario_oficial_dias ORDER BY data")
    assert dias == [("2026-11-03", 2), ("2026-11-04", 1), ("2026-11-10", 1)]
    assert tempo.dias_com_diario(banco, "2026-11") == 3
    pub = tempo.publicacao_do_mes(banco, "2026-11")
    assert pub["dias_uteis"] == 21 and pub["razao"] == round(3 / 21, 4)
    banco.fechar()


# --- Tempestividade: o prazo legal de cada documento ------------------------------------------

def test_prazo_legal_de_cada_documento():
    assert tempo.prazo_legal("RREO", 2025, 6)[0] == date(2026, 1, 30)
    assert tempo.prazo_legal("RGF", 2025, 3) == (date(2026, 1, 30), "Lei Complementar 101/2000, art. 55, § 2º")
    assert tempo.prazo_legal("DCA", 2025, 1)[0] == date(2026, 4, 30)
    assert tempo.prazo_legal("MSC", 2025, 12)[0] == date(2026, 1, 31)
    assert tempo.prazo_legal("MSC", 2026, 1)[0] == date(2026, 2, 28)
    assert tempo.prazo_legal("SIOPS", 2026, 1)[0] == date(2026, 3, 30)


def test_tempestividade_medida_no_banco_real(tmp_path):
    copia = tmp_path / "historico.db"
    # 28/11/2026, divisão do banco em partes: a cópia leva as partes (sem elas a abertura criaria partes vazias).
    partes.copiar_banco(BANCO_REAL, copia)
    banco = historico.Banco.abrir(copia)
    itens = {i["rotulo"]: i for i in tempo.tempestividade_dos_documentos(banco, date(2026, 11, 27))}
    banco.con.close()
    assert itens["RREO 2025, 1º bimestre"]["situacao"] == "no prazo"
    rgf = itens["RGF 2025, 3º quadrimestre"]
    assert (rgf["situacao"], rgf["dias_de_atraso"], rgf["prazo"]) == ("atrasado", 1, "2026-01-30")
    assert itens["RREO 2024, 1º bimestre"]["situacao"] == "não medida"     # só a data da retificação
    assert itens["MSC 2024-01"]["situacao"] == "não medida"                # reenvio em lote
    assert itens["DCA 2024"]["situacao"] == "no prazo"
    assert itens["RREO 2026, 5º bimestre"]["situacao"] == "ainda no prazo"
    assert 0 < tempo.indice_de_tempestividade(list(itens.values())) < 1


# --- Arquitetura: o SQLite atende (requisito 156) -------------------------------------------

def test_sqlite_atende_o_tamanho_e_a_consulta_de_referencia():
    """Decisão em docs/onisciente/decisoes.md: revê-la se o banco passar de 500 MB ou a consulta
    de referência passar de 2 segundos."""
    # 28/11/2026, divisão do banco em partes (onisciente/partes.py): precos_referencia, sancoes, as séries e a
    # despesa saíram do historico.db para arquivos anexados. O limite de 500 MB vale para o banco inteiro (o
    # principal somado às partes), e a consulta de referência passa pela conexão que anexa as partes.
    from onisciente import partes
    con = partes.conectar_leitura(BANCO_REAL)
    arquivos = [BANCO_REAL] + [partes.caminho_da_parte(BANCO_REAL, p) for p in partes.PARTES]
    assert sum(a.stat().st_size for a in arquivos if a.exists()) < 500 * 1024 * 1024
    inicio = time.perf_counter()
    linhas = con.execute(
        "SELECT i.catalogo, substr(COALESCE(i.data_resultado, i.data_inclusao), 1, 7), COUNT(*), "
        "AVG(i.unitario_resultado), (SELECT AVG(p.preco) FROM precos_referencia p WHERE p.catalogo = i.catalogo) "
        "FROM pncp_itens i WHERE i.catalogo IS NOT NULL AND i.unitario_resultado IS NOT NULL GROUP BY 1, 2"
    ).fetchall()
    segundos = time.perf_counter() - inicio
    con.close()
    assert len(linhas) > 1000
    assert segundos < 2.0, segundos
    assert "requisito 156" in (RAIZ / "docs" / "onisciente" / "decisoes.md").read_text(encoding="utf-8")
