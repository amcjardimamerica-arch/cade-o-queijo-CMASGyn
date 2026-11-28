"""Os pedidos que vieram depois do projeto original têm registro próprio, com a mesma honestidade."""

from onisciente import requisitos
from onisciente.__main__ import main


def test_ampliacao_existe_sem_problema_e_fora_dos_183():
    itens = requisitos.carregar_ampliacao()
    assert itens, "o registro da ampliação não pode sumir"
    assert min(i["id"] for i in itens) >= 184
    assert requisitos.problemas_ampliacao(itens) == []


def test_ampliacao_nao_aceita_id_do_original_nem_repetido():
    item = {"id": 184, "bloco": "x", "requisito": "r", "situacao": "parcial", "evidencia": "e", "falta": "f"}
    assert requisitos.problemas_ampliacao([item, dict(item)]) != []
    assert requisitos.problemas_ampliacao([dict(item, id=12)]) != []


def test_selo_e_empresas_contam_so_com_trava():
    for i in requisitos.carregar_ampliacao():
        if i["situacao"] == "cumprido":
            assert i.get("trava"), i["id"]


def test_recontagem_mostra_os_dois_registros(capsys):
    assert main(["requisitos"]) == 0
    saida = capsys.readouterr().out
    assert "do projeto original" in saida and "dos pedidos depois do projeto original" in saida
