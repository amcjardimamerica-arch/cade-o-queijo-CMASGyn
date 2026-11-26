"""O registro dos 183 requisitos do projeto original é honesto e tem dono."""

from onisciente import requisitos
from onisciente.__main__ import main


def test_registro_tem_os_183_e_nenhum_problema():
    itens = requisitos.carregar()
    assert len(itens) == 183
    assert requisitos.problemas(itens) == []


def test_bloco_1_conta_como_cumprido_so_com_trava():
    por = {i["id"]: i for i in requisitos.carregar()}
    for n in (36, 44, 46, 47, 77, 78):
        assert por[n]["situacao"] == "cumprido" and por[n].get("trava"), n


def test_trava_inexistente_e_problema(tmp_path):
    item = {"id": 1, "bloco": "x", "requisito": "r", "situacao": "cumprido", "evidencia": "e",
            "falta": "", "trava": "testes/nao_existe.py::test_x"}
    assert requisitos.problemas([item]) == ["#1: trava testes/nao_existe.py::test_x não existe"]
    sem = dict(item, evidencia="", trava=None, situacao="parcial")
    assert set(requisitos.problemas([sem])) == {"#1: sem evidência", "#1: parcial sem dizer o que falta"}


def test_recontagem(capsys):
    assert main(["requisitos"]) == 0
    saida = capsys.readouterr().out
    c = requisitos.contar(requisitos.carregar())
    assert c["cumpridos"] + c["parciais"] + c["ausentes"] == 183
    assert f"{c['percentual']}% do projeto original" in saida
