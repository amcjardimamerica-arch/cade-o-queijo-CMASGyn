"""Travas da decisão do usuário de 28/11/2026, 11:18Z (config/decisoes_usuario.yml, P-01): o dado fica como a
fonte publica.

Nenhum coletor, nem ``Banco.inserir``, nem a abertura do banco, nem a sondagem, nem as telas mascaram, cortam ou
trocam o CPF ou outro dado que a fonte publicou inteiro. O que a fonte já publica mascarado fica como veio. Estas
travas substituem as da máscara (test_mascara_banco, test_mascara_cpf, test_retirada_privacidade e partes de
test_execucao, test_coletores_federais_quinta e test_telas), revogadas pela mesma decisão.

Os CPFs destes testes são fictícios (dígitos verificadores calculados aqui) ou o número de exemplo dos validadores
públicos de CPF, sem dono.
"""

from __future__ import annotations

import ast
import base64
import io
import json
import re
import sqlite3
import zipfile
from pathlib import Path

import pytest
import yaml

from onisciente import historico, rastreio
from onisciente.coletores import motores_federais as mf

RAIZ = Path(__file__).resolve().parent.parent
REGISTRO = RAIZ / "config" / "decisoes_usuario.yml"


def _cpf(base9: str) -> str:
    d = [int(x) for x in base9]
    for k in (9, 10):
        d.append(sum(d[i] * (k + 1 - i) for i in range(k)) * 10 % 11 % 10)
    return "".join(map(str, d))


CPF_A = _cpf("123456789")
CPF_B = _cpf("987654321")
CPF_C = _cpf("111222333")
CPF_EXEMPLO = "52998224725"
CNPJ = "12345678000195"
FORMATADO_B = f"{CPF_B[:3]}.{CPF_B[3:6]}.{CPF_B[6:9]}-{CPF_B[9:]}"
FORMATADO_EX = "529.982.247-25"
MASCARA_DA_FONTE = "***.982.247-**"              # como o Portal da Transparência e o QSA publicam
TEXTO_LONGO = "Objeto da contratação" + " com descrição longa da fonte" * 40    # mais de 1.000 caracteres


# --- O registro da decisão ----------------------------------------------------------------------

def _decisao() -> dict:
    dados = yaml.safe_load(REGISTRO.read_text(encoding="utf-8"))
    return {d["id"]: d for d in dados["decisoes"]}["P-01"]


def test_decisao_registrada_com_data_texto_regra_e_travas():
    d = _decisao()
    assert d["data"] == "2026-11-28T11:18Z"
    assert d["texto_do_usuario"].startswith("Os dados devem ser públicos e não mascarar.")
    assert "não ter nenhum homônimo ou terceiro inocente" in d["texto_do_usuario"]
    assert "como a fonte o publica" in d["regra"]
    assert {r.get("commit") for r in d["revoga"]} >= {"b8bf2e6", "24fc099", "ee68c14", "91240af", "69017a5",
                                                      "e98f23e"}
    for trava in d["travas"]:
        assert (RAIZ / trava).exists(), trava
    assert "testes/test_dado_da_fonte.py" in d["travas"]


# --- Banco.inserir e Banco.abrir ----------------------------------------------------------------

def _banco(tmp_path: Path) -> historico.Banco:
    b = historico.Banco(tmp_path / "historico.db")
    mf.preparar(b)
    return b


LINHAS = {
    "sancoes": [{"cnpj_cpf": CPF_A, "cadastro": "CEIS", "nome": f"FULANO FICTICIO {CPF_A}",
                 "processo": f"processo {FORMATADO_B}", "inicio": "2025-01-01", "fundamentacao": TEXTO_LONGO},
                {"cnpj_cpf": "000" + CPF_B, "cadastro": "CNEP", "nome": "OUTRA PESSOA", "inicio": "2025-01-01"},
                {"cnpj_cpf": "123456", "cadastro": "CEIS", "nome": "PESSOA MASCARADA PELA FONTE",
                 "inicio": "2025-01-01"}],
    "pncp_itens": [{"compra_id": "c1", "numero_item": 1, "fornecedor_ni": FORMATADO_B,
                    "fornecedor": f"BELTRANO {FORMATADO_B}", "descricao": TEXTO_LONGO}],
    "contratos_pncp": [{"pncp_id": "k1", "fornecedor_ni": CPF_C, "fornecedor": f"CICLANO {CPF_C}",
                        "objeto": f"Locação do imóvel de CICLANO, CPF {CPF_C}. {TEXTO_LONGO}"},
                       {"pncp_id": "k2", "fornecedor_ni": MASCARA_DA_FONTE, "fornecedor": "MASCARADO PELA FONTE"}],
    "contratacoes_pncp": [{"pncp_id": "p1", "objeto": f"Locação de imóvel de {FORMATADO_B} e {CPF_A}"}],
    "emendas_municipio": [{"planilha": "x", "emenda": "1", "nome": f"FULANO {CPF_A}",
                           "json": json.dumps({"cpf": CPF_A, "nome": "FULANO", "cnpj": CNPJ})}],
}


def _gravar_tudo(b: historico.Banco) -> None:
    for tabela, linhas in LINHAS.items():
        for linha in linhas:
            b.inserir(tabela, dict(linha))
    b.con.commit()


def _como_gravado(con, tabela: str, linha: dict) -> dict:
    cols = list(linha)
    filtro = " AND ".join(f"{c} = ?" for c in cols)
    achado = con.execute(f"SELECT {', '.join(cols)} FROM {tabela} WHERE {filtro}", [linha[c] for c in cols])
    return dict(zip(cols, achado.fetchone() or ()))


def test_banco_inserir_guarda_o_dado_como_a_fonte_publicou(tmp_path):
    b = _banco(tmp_path)
    _gravar_tudo(b)
    for tabela, linhas in LINHAS.items():
        for linha in linhas:
            assert _como_gravado(b.con, tabela, linha) == linha, (tabela, linha)
    b.fechar()


def test_banco_abrir_nao_muda_nenhuma_linha_nem_abre_rodada_de_mascara(tmp_path):
    b = _banco(tmp_path)
    rid = rastreio.abrir_rodada(b.con, ["sancoes"])
    _gravar_tudo(b)
    b.con.execute("INSERT INTO sancoes (cnpj_cpf, cadastro, nome, inicio) VALUES (?, 'CEIS', ?, '2025-01-01')",
                  (CPF_EXEMPLO, f"DIRETO {FORMATADO_EX}"))
    rastreio.fechar_rodada(b.con, rid)
    b.con.commit()
    antes = {t: b.con.execute(f"SELECT * FROM {t} ORDER BY rowid").fetchall() for t in LINHAS}
    rodadas = b.con.execute("SELECT count(*) FROM rastreio_rodadas").fetchone()[0]
    b.fechar()
    for _ in range(2):
        b = historico.Banco.abrir(tmp_path / "historico.db")
        assert {t: b.con.execute(f"SELECT * FROM {t} ORDER BY rowid").fetchall() for t in LINHAS} == antes
        modos = {m for (m,) in b.con.execute("SELECT modo FROM rastreio_rodadas")}
        assert not modos & {rastreio.MODO_MASCARA, rastreio.MODO_RETIRADA}
        assert b.con.execute("SELECT count(*) FROM rastreio_rodadas").fetchone()[0] == rodadas
        assert rastreio.verificar(b.con)["integro"]
        b.fechar()


# --- Os coletores -------------------------------------------------------------------------------

def test_despesa_de_goiania_guarda_documento_credor_e_historico_como_o_portal_publica():
    from onisciente.coletores import goiania_transweb as G
    con = sqlite3.connect(":memory:")
    hist = f"ADIANTAMENTO, TOMADORA: FULANA - CPF:{FORMATADO_EX}, CPF {CPF_EXEMPLO}. {TEXTO_LONGO}"
    base = {"tipo": "empenho", "data": "2026-10-01", "orgao": "SAUDE", "valor": 10.0, "credor": "FULANO"}
    eventos = [dict(base, empenho="1", documento=CPF_EXEMPLO, credor=f"FULANO DE TAL {CPF_EXEMPLO}",
                    historico=hist),
               dict(base, empenho="2", documento=FORMATADO_EX),
               dict(base, empenho="3", documento="000" + CPF_EXEMPLO),      # a coluna CNPJ da exportação
               dict(base, empenho="4", documento=MASCARA_DA_FONTE),         # o que o portal publica mascarado
               dict(base, empenho="5", documento="31537116000198", credor="GMS LTDA")]
    assert G.gravar(con, eventos) == 5
    linhas = {e: (d, c, h) for e, d, c, h in con.execute(
        "select empenho, documento, credor, historico from despesa_eventos")}
    assert linhas["1"] == (CPF_EXEMPLO, f"FULANO DE TAL {CPF_EXEMPLO}", hist)
    assert linhas["2"][0] == FORMATADO_EX                    # o gravar guarda o que recebe, sem trocar nada
    assert linhas["3"][0] == "000" + CPF_EXEMPLO
    assert linhas["4"][0] == MASCARA_DA_FONTE
    assert linhas["5"][0] == "31537116000198"
    # A leitura da exportação só tira a pontuação e o "000" que a coluna CNPJ põe na frente do CPF (como antes
    # da máscara, 07e130c): os dígitos são os da fonte; o CPF mascarado pela fonte fica com os asteriscos.
    assert G.documento_do_credor("00052998224725") == CPF_EXEMPLO
    assert G.documento_do_credor(FORMATADO_EX) == CPF_EXEMPLO
    assert G.documento_do_credor(MASCARA_DA_FONTE) == MASCARA_DA_FONTE
    assert G.documento_do_credor("31.537.116/0001-98") == "31537116000198"


def test_impedimentos_fns_e_sancoes_guardam_o_cpf_como_veio(tmp_path):
    from onisciente.coletores import fns, impedimentos, sancoes
    b = _banco(tmp_path)
    impedimentos.gravar(b.con, [{"cnpj_cpf": CPF_A, "cadastro": "TCU", "nome": f"FULANO {CPF_A}",
                                 "processo": "TC 000.000/2025-0"},
                                {"cnpj_cpf": CNPJ, "cadastro": "TCU", "nome": "EMPRESA LTDA"}], "TCU")
    assert dict(b.con.execute("SELECT nome, cnpj_cpf FROM impedimentos").fetchall()) == {
        f"FULANO {CPF_A}": CPF_A, "EMPRESA LTDA": CNPJ}
    assert {(s.tipo_doc, s.doc) for s in impedimentos.ler_sancoes(b.con)} >= {("PF", CPF_A), ("PJ", CNPJ)}
    b.fechar()
    pagina = json.dumps({"resultado": {"total": 2, "totalPaginas": 1, "dados": [
        {"codigoMunicipioIBGE": "520870", "cpfCnpj": CPF_B, "cpfCnpjFormatado": "***.654.321-**",
         "razaoSocial": "BELTRANO"},
        {"codigoMunicipioIBGE": "520870", "cpfCnpj": CNPJ, "razaoSocial": "EMPRESA"}]}}).encode()
    ents, _total, _pags = fns.entidades(pagina, "520870")
    assert [e["cpf_cnpj"] for e in ents] == [CPF_B, CNPJ]
    csv_ = ("CADASTRO;CPF OU CNPJ DO SANCIONADO;NOME DO SANCIONADO;CATEGORIA DA SANÇÃO;DATA INÍCIO SANÇÃO;"
            "FUNDAMENTAÇÃO LEGAL\r\n"
            f"CEIS;{FORMATADO_B};BELTRANO;Impedimento;01/01/2025;{TEXTO_LONGO}\r\n").encode("latin-1")
    arq = io.BytesIO()
    with zipfile.ZipFile(arq, "w") as z:
        z.writestr("ceis.csv", csv_)
    lidas = sancoes.ler(arq.getvalue(), "CEIS")
    assert lidas[0]["cnpj_cpf"] == CPF_B                  # os dígitos da fonte (a pontuação sai, como sempre)
    assert lidas[0]["fundamentacao"] == TEXTO_LONGO       # sem o corte de 500 caracteres


# --- A sondagem ---------------------------------------------------------------------------------

def test_sondagem_guarda_o_corpo_e_o_zip_como_a_fonte_respondeu(tmp_path, monkeypatch):
    from onisciente import sondagem
    from onisciente.coletores.base import Leitura
    monkeypatch.setattr(sondagem, "PASTA", tmp_path)
    corpo = f"credor;documento\r\nFULANO;{CPF_EXEMPLO}\r\nBELTRANO;{FORMATADO_EX}\r\n".encode()
    sondagem._guardar("d2_transweb", "https://exemplo.invalid/a", Leitura(True, 200, corpo))
    (arq,) = tmp_path.glob("d2_transweb__*.txt")
    assert arq.read_bytes().endswith(corpo)
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w") as zz:
        zz.writestr("a.csv", corpo)
    sondagem._guardar("d1_cgu", "https://exemplo.invalid/b.zip", Leitura(True, 200, z.getvalue()))
    (b64,) = tmp_path.glob("d1_cgu__*.zip.b64")
    assert base64.b64decode(b64.read_text()) == z.getvalue()


# --- As telas -----------------------------------------------------------------------------------

def test_telas_mostram_o_cpf_como_a_fonte_publicou():
    from onisciente.telas import entradas
    from onisciente.telas.base import documento_publico, pronto_para_tela
    assert pronto_para_tela({"t": f"Credor {FORMATADO_EX} recebeu", "l": [CPF_EXEMPLO]}) == \
        {"t": f"Credor {FORMATADO_EX} recebeu", "l": [CPF_EXEMPLO]}
    assert entradas.texto(f"Pagamento a FULANO, CPF {CPF_EXEMPLO} ({FORMATADO_EX})") == \
        f"Pagamento a FULANO, CPF {CPF_EXEMPLO} ({FORMATADO_EX})"
    assert documento_publico(FORMATADO_EX) == CPF_EXEMPLO
    assert documento_publico(CNPJ) == CNPJ
    assert documento_publico(MASCARA_DA_FONTE) == MASCARA_DA_FONTE


def test_tela_da_execucao_mostra_o_credor_pessoa_fisica_e_o_documento():
    from onisciente.coletores import goiania_transweb as G
    from onisciente.telas import entradas
    con = sqlite3.connect(":memory:")
    con.executescript(historico.ESQUEMA)
    base = {"tipo": "empenho", "data": "2025-04-01", "orgao": "SAUDE", "valor": 1_000.0}
    G.gravar(con, [dict(base, empenho="2025/000800", documento=CPF_EXEMPLO, credor="FULANO DE TAL"),
                   dict(base, empenho="2025/000801", documento=MASCARA_DA_FONTE, credor="BELTRANO"),
                   dict(base, empenho="2025/000802", documento="31537116000198", credor="GMS")])
    emp = {e["numero"]: e for e in entradas.execucao(con)["empenhos"]}
    assert (emp["2025/000800"]["credor"], emp["2025/000800"]["credor_cnpj"]) == ("FULANO DE TAL", CPF_EXEMPLO)
    assert (emp["2025/000801"]["credor"], emp["2025/000801"]["credor_cnpj"]) == ("BELTRANO", MASCARA_DA_FONTE)
    assert emp["2025/000800"]["pessoa_fisica"] and emp["2025/000801"]["pessoa_fisica"]
    assert (emp["2025/000802"]["credor"], emp["2025/000802"]["credor_cnpj"]) == ("GMS", "31537116000198")


# --- O CPF inteiro casa pelo CPF inteiro -------------------------------------------------------

def test_cpf_inteiro_casa_pelo_cpf_inteiro_e_nao_pelo_miolo_de_outra_pessoa(tmp_path):
    from onisciente.coletores import goiania_transweb as G
    from onisciente.conferencias import execucao as X
    b = historico.Banco(tmp_path / "historico.db")
    con = b.con
    G.gravar(con, [{"tipo": "empenho", "empenho": "1", "data": "2025-04-01", "orgao": "SAUDE", "valor": 1.0,
                    "documento": CPF_EXEMPLO, "credor": "FULANO DE TAL"}])
    outro = CPF_EXEMPLO[:3] + "982247" + "00"                   # mesmo miolo, outro CPF (dígito qualquer)
    for pid, forn, nome in (("pf1", CPF_EXEMPLO, "FULANO DE TAL"), ("pf2", outro, "FULANO DE TAL"),
                            ("pf3", MASCARA_DA_FONTE, "FULANO DE TAL")):
        con.execute("insert into contratos_pncp (pncp_id, orgao_cnpj, orgao, fornecedor_ni, fornecedor, "
                    "valor_global, data_assinatura) values (?, '25141524000123', 'SAUDE', ?, ?, 1, '2025-01-10')",
                    (pid, forn, nome))
    con.commit()
    ctx = X.contexto_do_banco(con)
    b.fechar()
    # O CPF inteiro: o contrato do mesmo CPF e o que a fonte publicou mascarado (miolo e nome); nunca o
    # de outro CPF inteiro que só divide o miolo e o nome (o homônimo).
    assert sorted(c.id for c in X.contratos_do_credor(ctx, CPF_EXEMPLO, "FULANO DE TAL")) == ["pf1", "pf3"]
    # O credor mascarado pela fonte casa pelo miolo e o nome, como o QSA.
    assert sorted(c.id for c in X.contratos_do_credor(ctx, MASCARA_DA_FONTE, "FULANO DE TAL")) == \
        ["pf1", "pf2", "pf3"]


# --- Varreduras estáticas do caminho de gravação --------------------------------------------------

MASCARADORES = ("mascarar_linha", "mascarar_valor", "mascarar_documento", "mascarar_texto", "documento_gravavel",
                "texto_gravavel", "mascarar_cpfs_no_texto", "mascarar_cpf", "mascarar_cpfs", "migrar_cpfs",
                "sem_cpf")
# Onde as funções de reconhecimento ficam (só leitura) e onde a restauração as usa para achar o que o sistema
# mascarou e devolver o dado da fonte.
PODEM_CHAMAR = {"onisciente/mascara_banco.py", "onisciente/mascara_cpf.py", "onisciente/restauracao_fonte.py",
                "onisciente/coletores/goiania_transweb.py"}


def _modulos():
    for p in sorted((RAIZ / "onisciente").rglob("*.py")):
        yield p.relative_to(RAIZ).as_posix(), p.read_text(encoding="utf-8")


def test_nenhum_modulo_chama_a_mascara_nem_abre_rodada_de_mascara_ou_retirada():
    achados = []
    for nome, texto in _modulos():
        arvore = ast.parse(texto)
        for no in ast.walk(arvore):
            if isinstance(no, ast.Call):
                f = no.func
                alvo = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
                if alvo in MASCARADORES and nome not in PODEM_CHAMAR:
                    achados.append(f"{nome}:{no.lineno} chama {alvo}")
                if alvo == "abrir_rodada":
                    for kw in no.keywords:
                        if kw.arg == "modo" and isinstance(kw.value, ast.Attribute) and \
                                kw.value.attr in ("MODO_MASCARA", "MODO_RETIRADA"):
                            achados.append(f"{nome}:{no.lineno} abre rodada {kw.value.attr}")
                        if kw.arg == "modo" and isinstance(kw.value, ast.Constant) and \
                                kw.value.value in (rastreio.MODO_MASCARA, rastreio.MODO_RETIRADA):
                            achados.append(f"{nome}:{no.lineno} abre rodada {kw.value.value}")
    # Em goiania_transweb, as funções de reconhecimento só se chamam umas às outras, nunca no gravar.
    G = (RAIZ / "onisciente/coletores/goiania_transweb.py").read_text(encoding="utf-8")
    for funcao in ("gravar", "eventos_da_exportacao", "documento_do_credor", "substituir_empenhos", "gravar_lista"):
        corpo = _corpo(G, funcao)
        for m in MASCARADORES:
            if re.search(rf"\b{m}\(", corpo):
                achados.append(f"goiania_transweb.{funcao} chama {m}")
    assert achados == []


def _corpo(texto: str, funcao: str) -> str:
    arvore = ast.parse(texto)
    for no in arvore.body:
        if isinstance(no, ast.FunctionDef) and no.name == funcao:
            return ast.get_source_segment(texto, no) or ""
    return ""


# Os campos de texto que vêm da fonte não são cortados na gravação (o corte de mensagem de erro do próprio
# sistema, ``erro[:300]``, não é dado da fonte).
CAMPOS_DA_FONTE = ("objeto", "descricao", "detalhe", "fundamento", "fundamentacao", "sumario", "rotulo", "json",
                   "historico", "credor", "nome", "processo")


def test_nenhum_texto_da_fonte_e_cortado_na_gravacao():
    corte = re.compile(rf'"({"|".join(CAMPOS_DA_FONTE)})"\s*:\s*[^,\n]*\)\s*\[\s*:\s*\d+\s*\]'
                       rf'|"({"|".join(CAMPOS_DA_FONTE)})"\s*:\s*[^,\n]*"\s*\[\s*:\s*\d+\s*\]'
                       rf'|\[\s*["\']sumario["\']\s*\]\s*=.*\[\s*:\s*\d+\s*\]')
    achados = []
    for nome, texto in _modulos():
        if not (nome.startswith("onisciente/coletores/") or nome in ("onisciente/historico.py",)):
            continue
        for n, linha in enumerate(texto.splitlines(), 1):
            if corte.search(linha):
                achados.append(f"{nome}:{n}: {linha.strip()}")
    assert achados == []


# --- O banco real -------------------------------------------------------------------------------

@pytest.mark.xfail(strict=True, reason="o banco real ainda tem o que o sistema mascarou entre ee68c14 e a "
                   "decisão de 28/11/2026: sai depois do python -m onisciente restaurar-fonte --gravar e da "
                   "releitura da despesa; quando passar, esta marca sai (P-01)")
def test_banco_real_sem_nada_mascarado_pelo_sistema():
    from onisciente import restauracao_fonte
    if not historico.BANCO.exists():
        pytest.skip("banco real ausente")
    assert restauracao_fonte.mascarados_pelo_sistema(historico.BANCO) == {}
