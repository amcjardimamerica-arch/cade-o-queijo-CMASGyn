"""Drena a fila de trechos que ficaram para trás quando o teto foi atingido.

Consome no máximo 50% do limite da nova janela, mesma regra da rotina diária.
A ordem é peso do grupo, depois severidade, depois data.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from llm import chamar, chamar_em_lote
from orcamento import LimiteAtingido, Orcamento
from util import ESTADO, RELATORIOS, agora, carregar_yaml, gravar_json, hoje_iso, ler_json, log

ANALISADOS = ESTADO / "analisados.json"


def executar() -> int:
    if not Orcamento.pronto_para_retomar():
        log.info("Janela ainda não renovou. Nada a fazer.")
        return 0

    orc = Orcamento(
        limite_janela=int(os.environ.get("LIMITE_TOKENS_JANELA", "400000")),
        fracao_maxima=0.50,
        rateio=carregar_yaml("modelos.yml")["orcamento"]["rateio"],
    )

    itens = Orcamento.drenar_fila(limite=200)
    if not itens:
        log.info("Fila vazia.")
        return 0
    log.info("Retomando %d item(ns) da fila", len(itens))

    analisados = ler_json(ANALISADOS, {})
    achados: list[dict] = []

    try:
        triagem = chamar_em_lote(
            "triagem", [{"id": i["id"], "conteudo": i["conteudo"]} for i in itens], orc
        )
        aprovados = [i for i in itens if triagem.get(i["id"], {}).get("relevante") is True]
        extraidos = chamar_em_lote(
            "extracao", [{"id": i["id"], "conteudo": i["conteudo"]} for i in aprovados], orc
        )
        for i in aprovados:
            dados = extraidos.get(i["id"])
            if not dados or not dados.get("exige_validacao_juridica", True):
                continue
            entrada = ("ATO MUNICIPAL A VALIDAR (dados já extraídos):\n"
                       + json.dumps(dados, ensure_ascii=False, indent=1)
                       + "\n\nTRECHO ORIGINAL:\n" + i["conteudo"])
            r = chamar("validacao", entrada, orc)
            for a in r.get("achados", []):
                a.setdefault("documento", i.get("documento"))
                achados.append(a)
            analisados[i["hash"]] = {"em": hoje_iso(), "doc": i.get("documento")}
    except LimiteAtingido as e:
        log.warning("Teto atingido de novo: %s. Reenfileirando o restante.", e)
        for i in itens:
            if i["hash"] not in analisados:
                Orcamento.enfileirar(i)
        Orcamento.agendar_retomada()
    else:
        Orcamento.limpar_retomada()

    gravar_json(ANALISADOS, analisados)
    if achados:
        arq = RELATORIOS / f"achados_retomada_{agora().strftime('%Y-%m-%dT%H')}.json"
        gravar_json(arq, achados)
        log.info("%d achado(s) gravados em %s", len(achados), arq.name)
    return 2 if any(a.get("severidade") == "alta" for a in achados) else 0


if __name__ == "__main__":
    sys.exit(executar())
