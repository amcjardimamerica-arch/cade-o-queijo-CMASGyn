"""Trava: nenhum CPF completo de pessoa física nos arquivos da sondagem (o repositório é público).

A sondagem grava as respostas das fontes em ``relatorios/onisciente/sondagem``; antes de gravar,
``onisciente.mascara_cpf`` troca todo CPF de pessoa física por ``***.NNN.NNN-**`` (os seis do meio, como o
Portal da Transparência). CNPJ fica como está. Os CPFs destes testes são fictícios.
"""

from __future__ import annotations

import base64
import io
import zipfile
from pathlib import Path

from onisciente import mascara_cpf, sondagem
from onisciente.coletores import base

PASTA = Path(__file__).resolve().parent.parent / "relatorios" / "onisciente" / "sondagem"
DADOS = Path(__file__).parent / "dados" / "federais"


# --- A função de máscara ----------------------------------------------------------------------------

def test_mascara_troca_o_cpf_de_pessoa_fisica_e_deixa_o_cnpj():
    assert mascara_cpf.mascara("123.456.789-09") == mascara_cpf.mascara("12345678909") == "***.456.789-**"
    texto = (
        'Termo assinado por FULANO FICTICIO, CPF nº 123.456.789-09, e pela empresa 12.345.678/0001-95.\n'
        '{"cpfCnpj":"98765432100","razaoSocial":"PESSOA FICTICIA"},{"cpfCnpj":"12345678000195"},'
        '{"nuCpf": 11122233396, "telefone": "62999998888", "nuDocumento":"44455566677"}\n'
        "https://exemplo.gov.br/consulta?cpf=11122233396&cnpj=12345678000195\n"
        "<pessoa><nuCPF>12312312387</nuCPF><fone>62999998888</fone></pessoa>\n"
        '"CADASTRO";"TIPO DE PESSOA";"CPF OU CNPJ DO SANCIONADO";"NOME"\n'
        '"CEIS";"F";"55566677788";"PESSOA FICTICIA"\n'
        '"CEIS";"J";"12345678000195";"EMPRESA FICTICIA"\n'
        '"CEIS";"F";"***.666.777-**";"JA MASCARADA"\n'
        'Codigo do Favorecido;Favorecido\n'
        '99988877766;OUTRA PESSOA FICTICIA\n')
    novo, n = mascara_cpf.mascarar_texto(texto)
    assert n == 8
    for cpf in ("123.456.789-09", "98765432100", "11122233396", "44455566677", "12312312387", "55566677788",
                "99988877766"):
        assert cpf not in novo
    for mantido in ("12.345.678/0001-95", "12345678000195", "62999998888", "***.666.777-**"):
        assert mantido in novo                               # CNPJ, telefone e o que já vinha mascarado
    assert '"cpfCnpj":"***.654.321-**"' in novo and "cpf=***.222.333-**&cnpj=" in novo
    assert "<nuCPF>***.123.123-**</nuCPF>" in novo and '"CEIS";"F";"***.666.777-**";"PESSOA FICTICIA"' in novo
    assert "***.888.777-**;OUTRA PESSOA FICTICIA" in novo
    assert mascara_cpf.mascarar_texto(novo) == (novo, 0)    # não mascara de novo
    assert mascara_cpf.cpfs_completos(novo) == 0 and mascara_cpf.cpfs_completos(texto) == 8


def test_mascara_o_cpf_escrito_depois_de_n_ponto_e_deixa_o_meio_de_numero_maior():
    # Trava de 28/11/2026: o histórico da despesa de Goiânia traz "INSCRITA NO CPF SOB O N.123.456.789-09";
    # o ponto depois da letra escondia o CPF da máscara. Só "dígito e ponto" antes protege (número maior).
    novo, n = mascara_cpf.mascarar_texto("PESSOA FICTICIA, INSCRITA NO CPF SOB O N.123.456.789-09, NOS TERMOS")
    assert n == 1 and "N.***.456.789-**" in novo and "123.456.789-09" not in novo
    assert mascara_cpf.mascarar_texto("CPF N.987.654.321-00 e CPF:111.222.333-96")[1] == 2
    assert mascara_cpf.mascarar_texto("conta 7.123.456.789-09")[1] == 0     # meio de um número maior


def test_mascara_o_cpf_com_000_na_coluna_cnpj_da_despesa_de_goiania():
    # A exportação do TransWeb põe o CPF do favorecido pessoa física na coluna CNPJ, com 000 na frente.
    texto = ("Empenho;VlPago;CNPJ;NmOrgao;NmFavorecido\n"
             "20251101001910001;24746,00;07968867000184;SECRETARIA;EMPRESA FICTICIA\n"
             "20251101001930002;2883,36;00000000000191;SECRETARIA;BANCO FICTICIO\n"
             "20251101001930003;1500,00;00012345678909;SECRETARIA;PESSOA FICTICIA\n"
             "20251101001930004;1500,00;98765432100;SECRETARIA;OUTRA PESSOA FICTICIA\n")
    novo, n = mascara_cpf.mascarar_texto(texto)
    assert n == 2
    assert ";***.456.789-**;SECRETARIA;PESSOA FICTICIA" in novo and ";***.654.321-**;" in novo
    assert ";07968867000184;" in novo and ";00000000000191;" in novo    # CNPJ válidos, mesmo com 000
    assert "12345678909" not in novo and mascara_cpf.cpfs_completos(novo) == 0


def test_mascara_dentro_do_zip_e_zip_limpo_volta_igual():
    bruto = io.BytesIO()
    with zipfile.ZipFile(bruto, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("20261127_CEIS.csv", '"TIPO DE PESSOA";"CPF OU CNPJ DO SANCIONADO"\n"F";"55566677788"\n'
                   .encode("latin-1"))
        z.writestr("leia.txt", "sem documento")
    novo, n = mascara_cpf.mascarar_zip(bruto.getvalue())
    assert n == 1 and mascara_cpf.zip_tem_cpf(novo) == 0
    with zipfile.ZipFile(io.BytesIO(novo)) as z:
        assert z.read("20261127_CEIS.csv").decode("latin-1").endswith('"F";"***.666.777-**"\n')
        assert z.read("leia.txt") == b"sem documento"
    assert mascara_cpf.mascarar_zip(novo) == (novo, 0)


def test_sondagem_grava_o_corpo_e_o_zip_ja_mascarados(tmp_path, monkeypatch):
    monkeypatch.setattr(sondagem, "PASTA", tmp_path)
    url = "https://consultafns.saude.gov.br/recursos/consulta-detalhada/entidades?page=1"
    corpo = b'{"resultado":{"dados":[{"cpfCnpj":"98765432100","razaoSocial":"PESSOA FICTICIA"}]}}'
    info = sondagem._guardar("d1_fns", url, base.Leitura(True, url, corpo, http=200))
    gravado = (tmp_path / info["arquivo"]).read_text(encoding="utf-8")
    assert "98765432100" not in gravado and "***.654.321-**" in gravado
    zbytes = io.BytesIO()
    with zipfile.ZipFile(zbytes, "w") as z:
        z.writestr("a.csv", '"CPF";"NOME"\n"55566677788";"PESSOA FICTICIA"\n')
    url = "https://exemplo.gov.br/ceis.zip"
    info = sondagem._guardar("d1_sancoes", url, base.Leitura(True, url, zbytes.getvalue(), http=200))
    b64 = (tmp_path / info["arquivo"]).with_suffix(".zip.b64").read_text()
    assert mascara_cpf.zip_tem_cpf(base64.b64decode(b64)) == 0


# --- A trava da pasta -------------------------------------------------------------------------------

def _texto_do_pdf(dados: bytes) -> str:
    from pypdf import PdfReader
    return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(dados)).pages)


def test_nenhum_cpf_completo_nos_arquivos_da_sondagem():
    achados = []
    for arq in sorted(PASTA.iterdir()):
        if arq.name.endswith(".zip.b64"):
            n = mascara_cpf.zip_tem_cpf(base64.b64decode(arq.read_text()))
        elif arq.name.endswith(".pdf.b64"):
            n = mascara_cpf.cpfs_completos(_texto_do_pdf(base64.b64decode(arq.read_text())))
        elif arq.is_file():
            n = mascara_cpf.cpfs_completos(arq.read_text(encoding="utf-8", errors="replace"))
        else:
            continue
        if n:
            achados.append(f"{arq.name}: {n}")
    assert not achados, "CPF completo de pessoa física na sondagem (rode a máscara): " + "; ".join(achados)


# --- TCU: o corte em 100 ----------------------------------------------------------------------------
# 28/11/2026 (rodada 10): a trava test_tcu_sem_o_corte_le_alem_de_100_quando_a_constante_for_desligada saiu
# daqui junto com a da sexta rodada, na mesma troca autorizada pelo coordenador. Ela exigia o corte ainda
# ligado (LIMITE_PESQUISA == 100) e, desligado, a leitura até ``paginas``. A sondagem a8761d9 provou que a
# pesquisa passa de 100 (inicio=150 e inicio=1300, quantidadeEncontrada 1374); o corte foi desligado e o
# motor vai até o total declarado. A trava nova:
# testes/test_coletores_federais_decima.py::test_tcu_pesquisa_le_ate_o_total_e_diz_o_que_faltou.
