"""O reconhecimento do CPF mascarado (onisciente.mascara_banco), depois da revogação da máscara no banco.

Revogação: a decisão do usuário de 28/11/2026, 11:18Z (config/decisoes_usuario.yml, P-01) manda guardar o dado como a fonte
publica ("Os dados devem ser públicos e não mascarar"). ``Banco.inserir`` e ``Banco.abrir`` não mascaram mais, e
``mascara_banco`` ficou só com as funções de leitura, que a restauração (``onisciente.restauracao_fonte``) usa para
reconhecer o que o sistema mascarou. As travas que exigiam o CPF mascarado na gravação, na migração, no coletor de
impedimentos e no banco real saíram daqui pela mesma decisão e foram invertidas em testes/test_dado_da_fonte.py:

* test_mascara_na_gravacao_em_cada_tabela -> test_banco_inserir_guarda_o_dado_como_a_fonte_publicou;
* test_quem_grava_nas_tabelas_com_cpf_passa_pela_mascara ->
  test_nenhum_modulo_chama_a_mascara_nem_abre_rodada_de_mascara_ou_retirada;
* test_impedimentos_gravados_pelo_coletor_saem_mascarados -> test_impedimentos_fns_e_sancoes_guardam_o_cpf_como_veio;
* test_migracao_mascara_as_linhas_antigas_numa_rodada_e_o_rastreio_sela_de_novo ->
  test_banco_abrir_nao_muda_nenhuma_linha_nem_abre_rodada_de_mascara;
* test_banco_real_so_tem_cpf_completo_na_despesa_que_a_d2_mascara e test_banco_real_sem_nenhum_cpf_completo ->
  test_banco_real_sem_nada_mascarado_pelo_sistema.

Os CPFs destes testes são fictícios (dígitos verificadores calculados aqui).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from onisciente import historico, mascara_banco, mascara_cpf
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


# --- A máscara como função de reconhecimento (não grava nada) ---------------------------------------

def test_mascara_nao_se_aplica_de_novo_ao_que_ja_esta_mascarado():
    for tabela, colunas in mascara_banco.COLUNAS.items():
        for coluna in colunas:
            v = mascara_banco.mascarar_valor(tabela, coluna, f"X {_m(CPF_A)}")
            assert mascara_banco.mascarar_valor(tabela, coluna, v) == v
    assert mascara_banco.mascarar_documento(_m(CPF_A)) == _m(CPF_A)
    assert mascara_banco.mascarar_documento(int(CPF_B)) == _m(CPF_B)        # CPF guardado como número


# --- A varredura do banco inteiro ----------------------------------------------------------------

def test_varredura_acha_cpf_completo_em_qualquer_tabela_e_ignora_telefone_hash_e_cnpj(tmp_path):
    # A varredura é leitura (conta o CPF inteiro, que pela decisão P-01 fica no banco); aqui só a tabela avulsa,
    # porque as outras guardam o CPF inteiro como a fonte publicou.
    b = _banco(tmp_path)
    _gravar_tudo(b)
    assert mascara_banco.varrer(b.con)[("sancoes", "cnpj_cpf")] == 2        # o CPF inteiro e o com 000 na frente
    b.con.execute("CREATE TABLE avulsa (documento TEXT, texto TEXT, numero INTEGER, cpf INTEGER)")
    b.con.execute("INSERT INTO avulsa VALUES (?, ?, ?, ?)", (CNPJ, f"tel {TELEFONE} hash {HASH}", int(CPF_A), None))
    b.con.commit()
    assert {k: n for k, n in mascara_banco.varrer(b.con).items() if k[0] == "avulsa"} == {}   # o número solto fora de coluna de documento não conta
    b.con.execute("INSERT INTO avulsa VALUES (?, ?, ?, ?)", ("000" + CPF_A, f"de {FORMATADO_B} e {CPF_C}", None,
                                                            int(CPF_C)))
    b.con.commit()
    assert {k: n for k, n in mascara_banco.varrer(b.con).items() if k[0] == "avulsa"} == {("avulsa", "documento"): 1, ("avulsa", "texto"): 2,
                                           ("avulsa", "cpf"): 1}
    b.con.close()


# --- Os cruzamentos com o documento mascarado ------------------------------------------------------

def test_fornecedor_com_cpf_mascarado_pela_fonte_casa_com_a_sancao_pelos_seis_do_meio(tmp_path):
    """O contrato cujo CPF a fonte publicou mascarado casa com a sanção pelos seis do meio e pelo nome (como o
    QSA); pessoa jurídica, pelo CNPJ inteiro. Antes (ee68c14) o próprio Banco.inserir mascarava o CPF inteiro
    do contrato; pela decisão do usuário de 28/11/2026, 11:18Z (config/decisoes_usuario.yml, P-01) ele fica inteiro, e
    aqui o mascarado é o que a fonte já publica assim."""
    b = _banco(tmp_path)
    for pid, ni, nome in (("k1", _m(CPF_A), "FULANO FICTICIO"), ("k2", _m(CPF_B), "OUTRO NOME"),
                          ("k3", CNPJ, "EMPRESA FICTICIA LTDA")):
        b.inserir("contratos_pncp", {"pncp_id": pid, "mes": "2025-05", "data_assinatura": "2025-05-10",
                                     "orgao_cnpj": "01393989000103", "orgao": "FMAS", "fornecedor_ni": ni,
                                     "fornecedor": nome, "objeto": "Locação de imóvel", "valor_global": 1000.0,
                                     "da_pasta": 1})
    for doc, nome in ((CPF_A, f"FULANO FICTICIO {CPF_A}"), (CPF_B, "NOME DIFERENTE"), (CNPJ, "EMPRESA")):
        b.inserir("sancoes", {"cnpj_cpf": doc, "cadastro": "CEIS", "inicio": "2025-01-01", "fim": "2026-12-31",
                              "orgao": "Prefeitura X", "tipo": "Impedimento", "nome": nome})
    b.con.commit()
    assert b.con.execute("SELECT cnpj_cpf FROM sancoes WHERE nome = 'NOME DIFERENTE'").fetchone()[0] == CPF_B
    conf = empresas.conferir(b.con, hoje=date(2026, 11, 28))
    sanc = {a.chave.split("-")[0]: a for a in conf.achados if a.tipo == "sancionada"}
    assert set(sanc) == {"k1", "k3"}                 # k2: os seis do meio casam, mas o nome difere
    assert _m(CPF_A) in sanc["k1"].descricao
    assert sanc["k1"].dados.get("por_nome") is True and sanc["k3"].dados.get("por_nome") is False
    b.con.close()
