"""Travas: nenhum CPF completo de pessoa física no banco da coleta (28/11/2026; o banco vai a um repositório
público).

``onisciente.mascara_banco`` troca o CPF por ``***.NNN.NNN-**`` (os seis do meio, como o QSA da Receita) na
gravação (``Banco.inserir``) e nas linhas antigas (na abertura do Banco, numa rodada do rastreio). CNPJ fica
inteiro. Os CPFs destes testes são fictícios (dígitos verificadores calculados aqui).
"""

from __future__ import annotations

import re
import shutil
from datetime import date
from pathlib import Path

import pytest

from onisciente import historico, mascara_banco, mascara_cpf, partes, rastreio
from onisciente.coletores import motores_federais as mf
from onisciente.conferencias import empresas

RAIZ = Path(__file__).resolve().parent.parent
BANCO_REAL = historico.BANCO


def _cpf(base9: str) -> str:
    """CPF fictício com os dígitos verificadores certos."""
    d = [int(x) for x in base9]
    for k in (9, 10):
        d.append(sum(d[i] * (k + 1 - i) for i in range(k)) * 10 % 11 % 10)
    return "".join(map(str, d))


CPF_A = _cpf("123456789")          # 12345678909
CPF_B = _cpf("987654321")
CPF_C = _cpf("111222333")
CNPJ = "12345678000195"
FORMATADO_B = f"{CPF_B[:3]}.{CPF_B[3:6]}.{CPF_B[6:9]}-{CPF_B[9:]}"
TELEFONE = "62999998888"                         # 11 dígitos, sem dígito verificador de CPF
PROCESSO = CPF_C[:9] + str((int(CPF_C[9]) + 1) % 10) + CPF_C[10]   # 11 dígitos com o dígito trocado
HASH = "ab" + CPF_A + "cd" * 26                  # um hash com 11 dígitos colados a letras


def _m(cpf: str) -> str:
    return mascara_cpf.mascara(cpf)


def test_os_dados_ficticios_sao_o_que_dizem():
    assert mascara_cpf._cpf_valido(CPF_A) and mascara_cpf._cpf_valido(CPF_B) and mascara_cpf._cpf_valido(CPF_C)
    assert mascara_cpf._cnpj_valido(CNPJ)
    assert not mascara_cpf._cpf_valido(TELEFONE) and not mascara_cpf._cpf_valido(PROCESSO)


def _banco(tmp_path: Path) -> historico.Banco:
    b = historico.Banco(tmp_path / "historico.db")
    mf.preparar(b)                                   # sancoes (na parte sancoes.db) e emendas_municipio
    return b


def _gravar_tudo(b: historico.Banco) -> None:
    """Uma linha com CPF em cada coluna que a varredura do banco real apontou, e o que deve ficar como está."""
    b.inserir("sancoes", {"cnpj_cpf": CPF_A, "cadastro": "CEIS", "nome": f"FULANO FICTICIO {CPF_A}",
                          "processo": f"processo {FORMATADO_B}", "inicio": "2025-01-01"})
    b.inserir("sancoes", {"cnpj_cpf": CNPJ, "cadastro": "CEIS", "nome": "EMPRESA FICTICIA LTDA",
                          "processo": PROCESSO, "inicio": "2025-01-01"})
    b.inserir("sancoes", {"cnpj_cpf": "000" + CPF_B, "cadastro": "CNEP", "nome": "OUTRA PESSOA",
                          "processo": f"tel {TELEFONE}", "inicio": "2025-01-01"})
    b.inserir("pncp_itens", {"compra_id": "c1", "numero_item": 1, "fornecedor_ni": FORMATADO_B,
                             "fornecedor": f"BELTRANO {FORMATADO_B}"})
    b.inserir("pncp_itens", {"compra_id": "c1", "numero_item": 2, "fornecedor_ni": CNPJ,
                             "fornecedor": "EMPRESA FICTICIA LTDA"})
    b.inserir("contratos_pncp", {"pncp_id": "k1", "fornecedor_ni": CPF_C, "fornecedor": f"CICLANO {CPF_C}",
                                 "objeto": f"Locação do imóvel de CICLANO, CPF {CPF_C}, processo {PROCESSO}"})
    b.inserir("contratos_pncp", {"pncp_id": "k2", "fornecedor_ni": CNPJ, "fornecedor": "EMPRESA FICTICIA LTDA",
                                 "objeto": f"Serviço; hash {HASH}; CNPJ {CNPJ}"})
    b.inserir("contratacoes_pncp", {"pncp_id": "p1", "objeto": f"Locação de imóvel de {FORMATADO_B} e {CPF_A}"})
    b.inserir("emendas_municipio", {"planilha": "x", "emenda": "1", "nome": f"FULANO {CPF_A}",
                                    "json": f'{{"cpf": "{CPF_A}", "nome": "FULANO", "cnpj": "{CNPJ}", '
                                            f'"telefone": "{TELEFONE}"}}'})
    b.con.commit()


# --- A máscara na gravação, tabela a tabela ---------------------------------------------------------

def test_mascara_na_gravacao_em_cada_tabela(tmp_path):
    b = _banco(tmp_path)
    _gravar_tudo(b)
    c = b.con
    assert c.execute("SELECT cnpj_cpf, nome, processo FROM sancoes ORDER BY rowid").fetchall() == [
        (_m(CPF_A), f"FULANO FICTICIO {_m(CPF_A)}", f"processo {_m(CPF_B)}"),
        (CNPJ, "EMPRESA FICTICIA LTDA", PROCESSO),                     # CNPJ e processo com DV errado ficam
        (_m(CPF_B), "OUTRA PESSOA", f"tel {TELEFONE}")]                # CPF com 000 na frente; telefone fica
    assert c.execute("SELECT fornecedor_ni, fornecedor FROM pncp_itens ORDER BY numero_item").fetchall() == [
        (_m(CPF_B), f"BELTRANO {_m(CPF_B)}"), (CNPJ, "EMPRESA FICTICIA LTDA")]
    assert c.execute("SELECT fornecedor_ni, fornecedor, objeto FROM contratos_pncp ORDER BY pncp_id").fetchall() == [
        (_m(CPF_C), f"CICLANO {_m(CPF_C)}", f"Locação do imóvel de CICLANO, CPF {_m(CPF_C)}, processo {PROCESSO}"),
        (CNPJ, "EMPRESA FICTICIA LTDA", f"Serviço; hash {HASH}; CNPJ {CNPJ}")]
    assert c.execute("SELECT objeto FROM contratacoes_pncp").fetchone()[0] == \
        f"Locação de imóvel de {_m(CPF_B)} e {_m(CPF_A)}"
    nome, js = c.execute("SELECT nome, json FROM emendas_municipio").fetchone()
    assert nome == f"FULANO {_m(CPF_A)}"
    assert js == f'{{"cpf": "{_m(CPF_A)}", "nome": "FULANO", "cnpj": "{CNPJ}", "telefone": "{TELEFONE}"}}'
    assert mascara_banco.varrer(c) == {}
    b.con.close()


def test_mascara_nao_se_aplica_de_novo_ao_que_ja_esta_mascarado():
    for tabela, colunas in mascara_banco.COLUNAS.items():
        for coluna in colunas:
            v = mascara_banco.mascarar_valor(tabela, coluna, f"X {_m(CPF_A)}")
            assert mascara_banco.mascarar_valor(tabela, coluna, v) == v
    assert mascara_banco.mascarar_documento(_m(CPF_A)) == _m(CPF_A)
    assert mascara_banco.mascarar_documento(int(CPF_B)) == _m(CPF_B)        # CPF guardado como número


def test_quem_grava_nas_tabelas_com_cpf_passa_pela_mascara():
    """Toda gravação nessas tabelas passa por ``Banco.inserir`` (a máscara): nenhum módulo tem um INSERT
    escrito direto nelas (``partes`` e ``agenda`` copiam de banco para banco, já mascarado)."""
    tabelas = "|".join(mascara_banco.COLUNAS)
    direto = re.compile(rf"(?i)(INSERT|REPLACE)\s+(OR\s+\w+\s+)?INTO\s+[\w.]*\b({tabelas})\b")
    achados = [f"{p.relative_to(RAIZ)}:{n}" for p in (RAIZ / "onisciente").rglob("*.py")
               for n, linha in enumerate(p.read_text(encoding="utf-8").splitlines(), 1) if direto.search(linha)]
    assert achados == []


# --- A migração das linhas antigas ----------------------------------------------------------------

def test_migracao_mascara_as_linhas_antigas_numa_rodada_e_o_rastreio_sela_de_novo(tmp_path):
    b = _banco(tmp_path)
    # Linhas gravadas antes da máscara, numa rodada com origem (como uma coleta de verdade).
    rid = rastreio.abrir_rodada(b.con, ["sancoes"])
    b.inserir("coletas", {"motor": "sancoes", "alvo": "CEIS", "mes": "2026-11", "url": "https://x/ceis", "ok": 1,
                          "http": 200, "bytes": 10, "sha256": "f" * 64})
    b.con.execute("INSERT INTO sancoes (cnpj_cpf, cadastro, nome, inicio) VALUES (?, 'CEIS', ?, '2025-01-01')",
                  (CPF_A, f"FULANO {CPF_A}"))
    b.con.execute("INSERT INTO sancoes (cnpj_cpf, cadastro, nome, inicio) VALUES (?, 'CEIS', 'EMPRESA', "
                  "'2025-01-01')", (CNPJ,))
    b.con.execute("INSERT INTO contratos_pncp (pncp_id, fornecedor_ni, fornecedor) VALUES ('k1', ?, 'CICLANO')",
                  (CPF_C,))
    rastreio.fechar_rodada(b.con, rid)
    origem = b.con.execute("SELECT origem FROM rastreio_selos s JOIN rastreio_tabelas t ON t.id = s.tabela "
                           "WHERE t.nome = 'sancoes' AND s.origem IS NOT NULL").fetchone()[0]
    b.fechar()
    assert len(mascara_banco.varrer(partes.conectar_leitura(tmp_path / "historico.db"))) == 3

    b = historico.Banco.abrir(tmp_path / "historico.db")
    c = b.con
    assert c.execute("SELECT cnpj_cpf, nome FROM sancoes ORDER BY rowid").fetchall() == [
        (_m(CPF_A), f"FULANO {_m(CPF_A)}"), (CNPJ, "EMPRESA")]
    assert c.execute("SELECT fornecedor_ni FROM contratos_pncp").fetchone()[0] == _m(CPF_C)
    assert mascara_banco.varrer(c) == {}
    rodada = c.execute("SELECT id, modo, registros FROM rastreio_rodadas ORDER BY id DESC LIMIT 1").fetchone()
    assert rodada[1:] == (mascara_banco.MODO, 2)
    novos = c.execute("SELECT t.nome, s.origem FROM rastreio_selos s JOIN rastreio_tabelas t ON t.id = s.tabela "
                      "WHERE s.rodada = ? ORDER BY t.nome", (rodada[0],)).fetchall()
    assert novos == [("contratos_pncp", origem), ("sancoes", origem)]   # a origem do selo antigo continua
    assert c.execute("SELECT count(*) FROM rastreio_selos WHERE descartada = ?", (rodada[0],)).fetchone()[0] == 2
    v = rastreio.verificar(c)
    assert v["integro"], v
    b.fechar()
    # Já mascarado: a abertura seguinte não abre outra rodada.
    b = historico.Banco.abrir(tmp_path / "historico.db")
    assert b.con.execute("SELECT max(id) FROM rastreio_rodadas").fetchone()[0] == rodada[0]
    b.fechar()


# --- A varredura do banco inteiro ----------------------------------------------------------------

def test_varredura_acha_cpf_completo_em_qualquer_tabela_e_ignora_telefone_hash_e_cnpj(tmp_path):
    b = _banco(tmp_path)
    _gravar_tudo(b)
    b.con.execute("CREATE TABLE avulsa (documento TEXT, texto TEXT, numero INTEGER, cpf INTEGER)")
    b.con.execute("INSERT INTO avulsa VALUES (?, ?, ?, ?)", (CNPJ, f"tel {TELEFONE} hash {HASH}", int(CPF_A), None))
    b.con.commit()
    assert mascara_banco.varrer(b.con) == {}            # o número solto fora de coluna de documento não conta
    b.con.execute("INSERT INTO avulsa VALUES (?, ?, ?, ?)", ("000" + CPF_A, f"de {FORMATADO_B} e {CPF_C}", None,
                                                            int(CPF_C)))
    b.con.commit()
    assert mascara_banco.varrer(b.con) == {("avulsa", "documento"): 1, ("avulsa", "texto"): 2,
                                           ("avulsa", "cpf"): 1}
    b.con.close()


# --- O banco real ---------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def varredura_real(tmp_path_factory):
    """O banco real copiado e aberto pelo Banco (a abertura faz a migração da máscara), varrido inteiro."""
    if not BANCO_REAL.exists():
        pytest.skip("banco real ausente")
    destino = tmp_path_factory.mktemp("real")
    for arquivo in (BANCO_REAL, *partes.arquivos(BANCO_REAL), rastreio.caminho_do_rastreio(BANCO_REAL)):
        if arquivo.is_file() and not arquivo.name.endswith(("-journal", ".tmp")):
            alvo = destino / arquivo.relative_to(BANCO_REAL.parent)
            alvo.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(arquivo, alvo)
    b = historico.Banco.abrir(destino / BANCO_REAL.name)
    try:
        return mascara_banco.varrer(b.con)
    finally:
        b.con.close()


def test_banco_real_so_tem_cpf_completo_na_despesa_que_a_d2_mascara(varredura_real):
    """O que falta no banco real, depois da migração: só ``despesa_eventos``, que o coletor da despesa de
    Goiânia (Frente D2) mascara e migra. Qualquer outra tabela com CPF completo falha aqui."""
    fora = {k: n for k, n in varredura_real.items() if k[0] != "despesa_eventos"}
    assert fora == {}, f"CPF completo fora da despesa: {fora}"


# 28/11/2026, Frente D2 rodada 8: a despesa ficou limpa (documento, credor e histórico mascarados no
# coletor e migrados no Banco.abrir); o xfail estrito deu XPASS e a marca saiu, como a própria trava pedia.
def test_banco_real_sem_nenhum_cpf_completo(varredura_real):
    assert varredura_real == {}


# --- Os cruzamentos com o documento mascarado ------------------------------------------------------

def test_fornecedor_pessoa_fisica_mascarado_casa_com_a_sancao_pelos_seis_do_meio(tmp_path):
    """Pessoa física casa pelos seis do meio e pelo nome (como o QSA); pessoa jurídica, pelo CNPJ inteiro."""
    b = _banco(tmp_path)
    b.inserir("contratos_pncp", {"pncp_id": "k1", "mes": "2025-05", "data_assinatura": "2025-05-10",
                                 "orgao_cnpj": "01393989000103", "orgao": "FMAS", "fornecedor_ni": CPF_A,
                                 "fornecedor": "FULANO FICTICIO", "objeto": "Locação de imóvel",
                                 "valor_global": 1000.0, "da_pasta": 1})
    b.inserir("contratos_pncp", {"pncp_id": "k2", "mes": "2025-05", "data_assinatura": "2025-05-10",
                                 "orgao_cnpj": "01393989000103", "orgao": "FMAS", "fornecedor_ni": CPF_B,
                                 "fornecedor": "OUTRO NOME", "objeto": "Locação de imóvel",
                                 "valor_global": 1000.0, "da_pasta": 1})
    b.inserir("contratos_pncp", {"pncp_id": "k3", "mes": "2025-05", "data_assinatura": "2025-05-10",
                                 "orgao_cnpj": "01393989000103", "orgao": "FMAS", "fornecedor_ni": CNPJ,
                                 "fornecedor": "EMPRESA FICTICIA LTDA", "objeto": "Material",
                                 "valor_global": 1000.0, "da_pasta": 1})
    for doc, nome in ((CPF_A, f"FULANO FICTICIO {CPF_A}"), (CPF_B, "NOME DIFERENTE"), (CNPJ, "EMPRESA")):
        b.inserir("sancoes", {"cnpj_cpf": doc, "cadastro": "CEIS", "inicio": "2025-01-01", "fim": "2026-12-31",
                              "orgao": "Prefeitura X", "tipo": "Impedimento", "nome": nome})
    b.con.commit()
    assert b.con.execute("SELECT fornecedor_ni FROM contratos_pncp WHERE pncp_id = 'k1'").fetchone()[0] == _m(CPF_A)
    conf = empresas.conferir(b.con, hoje=date(2026, 11, 28))
    sanc = {a.chave.split("-")[0]: a for a in conf.achados if a.tipo == "sancionada"}
    assert set(sanc) == {"k1", "k3"}                 # k2: mesmos seis do meio? não; e o nome também difere
    assert _m(CPF_A) in sanc["k1"].descricao and CPF_A not in sanc["k1"].descricao
    assert sanc["k1"].dados.get("por_nome") is True and sanc["k3"].dados.get("por_nome") is False
    b.con.close()
