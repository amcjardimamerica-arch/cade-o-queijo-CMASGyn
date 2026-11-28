"""Trava: os fluxos que gravam o banco guardam o rastreio.db e não tentam enviar banco grande demais.

O GitHub recusa arquivo acima de 100 MiB, e um envio recusado perde a rodada inteira. Todo fluxo do
grupo onisciente-banco confere o tamanho de cada .db antes do commit: acima de 95 MB, sobe os bancos
como artefato da execução, escreve no resumo qual arquivo passou e falha sem tentar o push. E o
arquivo do rastreio por hash (dados/onisciente/rastreio.db, frente H) entra no mesmo commit do banco.
"""
import os
import re
import subprocess
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[1]
GRANDE = "steps.tamanho.outputs.grande"


def _fluxos_do_banco():
    for p in sorted((RAIZ / ".github" / "workflows").glob("*.yml")):
        dados = yaml.safe_load(p.read_text(encoding="utf-8"))
        if (dados.get("concurrency") or {}).get("group") == "onisciente-banco":
            yield p, dados


def _passos(dados):
    for job in dados["jobs"].values():
        yield job["steps"]


def test_todo_fluxo_do_banco_tem_a_guarda_de_tamanho_e_adiciona_o_rastreio():
    fluxos = list(_fluxos_do_banco())
    assert len(fluxos) >= 7
    for p, dados in fluxos:
        for passos in _passos(dados):
            ids = {s.get("id"): i for i, s in enumerate(passos)}
            assert "tamanho" in ids, p.name
            guarda = passos[ids["tamanho"]]
            assert "95000000" in guarda["run"] and "GITHUB_STEP_SUMMARY" in guarda["run"], p.name
            assert "grande=1" in guarda["run"] and "dados/onisciente/*.db" in guarda["run"], p.name
            # O passo que publica (o último que faz commit e push; o boletim da coleta em andamento, que só
            # envia relatorios/onisciente/boletim_coleta.md de outra cópia do ramo, vem antes e não conta).
            envios = [i for i, s in enumerate(passos) if "git commit" in str(s.get("run", ""))
                      and "git push" in str(s.get("run", ""))]
            assert envios, p.name
            commit = [envios[-1]]
            assert not any(re.search(r"git add[^\n]*dados/onisciente", passos[i]["run"]) for i in envios[:-1]), p.name
            for i in commit:
                assert ids["tamanho"] < i, p.name
                assert f"{GRANDE} != '1'" in passos[i].get("if", ""), p.name        # não envia se passou
                assert re.search(r"git add dados/onisciente/rastreio\.db", passos[i]["run"]), p.name
            artefato = [i for i, s in enumerate(passos) if str(s.get("uses", "")).startswith("actions/upload-artifact")
                        and f"{GRANDE} == '1'" in s.get("if", "")]
            assert artefato and ids["tamanho"] < artefato[0] < commit[0], p.name
            assert "dados/onisciente/*.db" in passos[artefato[0]]["with"]["path"], p.name
            falha = [i for i, s in enumerate(passos) if f"{GRANDE} == '1'" in s.get("if", "")
                     and "exit 1" in str(s.get("run", ""))]
            assert falha and falha[0] > ids["tamanho"], p.name


def _rodar_guarda(pasta: Path, tamanhos: dict[str, int]) -> tuple[str, str]:
    p, dados = next(_fluxos_do_banco())
    passos = next(_passos(dados))
    script = next(s for s in passos if s.get("id") == "tamanho")["run"].replace("${{ github.run_id }}", "123")
    (pasta / "dados" / "onisciente").mkdir(parents=True)
    for nome, t in tamanhos.items():
        with open(pasta / "dados" / "onisciente" / nome, "wb") as f:
            f.truncate(t)                                   # arquivo esparso: não ocupa o disco
    saida, resumo = pasta / "saida", pasta / "resumo"
    subprocess.run(["bash", "-e", "-c", script], cwd=pasta, check=True,
                   env={**os.environ, "GITHUB_OUTPUT": str(saida), "GITHUB_STEP_SUMMARY": str(resumo)})
    ler = (lambda x: x.read_text(encoding="utf-8") if x.exists() else "")
    return ler(saida), ler(resumo)


def test_a_guarda_aponta_o_banco_grande_e_deixa_passar_o_normal(tmp_path):
    saida, resumo = _rodar_guarda(tmp_path / "normal", {"historico.db": 77_406_208, "rastreio.db": 20_000_000})
    assert "grande=1" not in saida and resumo == ""
    saida, resumo = _rodar_guarda(tmp_path / "grande", {"historico.db": 96_000_000, "rastreio.db": 20_000_000})
    assert "grande=1" in saida
    assert "historico.db" in resumo and "rastreio.db" not in resumo and "onisciente-bancos-123" in resumo
