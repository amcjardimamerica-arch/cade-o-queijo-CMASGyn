"""Orquestrador da rotina diária.

Ordem obrigatória e não negociável:
  1. coleta com GET condicional
  2. supressão de dados pessoais na ingestão
  3. filtro determinístico por expressão regular
  4. verificações determinísticas de conformidade (custo zero)
  5. triagem em lote com o modelo mais barato
  6. extração em lote com o modelo intermediário
  7. validação jurídica síncrona com o modelo avançado, sobre corpus cacheado
  8. retenção de 30 dias
  9. boletim

Ao atingir metade do limite de tokens, o que restou vai para a fila e a
execução é reagendada. Nada se perde.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import coleta_cmasgyn
import coleta_dom
import conformidade
import igd
import retencao
from cliente_http import ClienteHTTP
from filtro import Lexico, processar
from llm import chamar, chamar_em_lote
from orcamento import LimiteAtingido, Orcamento
from util import (ACERVO, ESTADO, RELATORIOS, agora, carregar_yaml,
                  gravar_json, hoje_iso, ler_json, log)

ANALISADOS = ESTADO / "analisados.json"


def _cliente_http() -> ClienteHTTP:
    d = carregar_yaml("fontes.yml")["defaults"]
    ua = d["user_agent"].replace("SEU_EMAIL", os.environ.get("CONTATO_EMAIL", "contato"))
    return ClienteHTTP(
        user_agent=ua, intervalo=d["intervalo_segundos"], timeout=d["timeout"],
        tentativas=d["tentativas"], respeitar_robots=d["respeitar_robots"],
    )


def _fontes(cadencia: str) -> list[dict]:
    cfg = carregar_yaml("fontes.yml")
    hoje = agora()
    if cadencia == "semanal" and hoje.weekday() != 0:
        return []
    if cadencia == "mensal" and hoje.day != 1:
        return []
    return [f for f in cfg["fontes"] if f.get("cadencia") == cadencia]


def executar() -> int:
    if not Orcamento.pronto_para_retomar():
        log.warning("Ainda dentro da janela de espera. Encerrando sem consumir.")
        return 0

    orc = Orcamento(
        limite_janela=int(os.environ.get("LIMITE_TOKENS_JANELA", "400000")),
        fracao_maxima=0.50,
        rateio=carregar_yaml("modelos.yml")["orcamento"]["rateio"],
    )
    http = _cliente_http()
    lexico_cfg = carregar_yaml("termos.yml")
    achados: list[dict] = []
    trechos_do_dia = []

    # ------------------------------------------------------------- 1. COLETA
    for fonte in _fontes("semanal"):
        if fonte.get("alimenta_lexico"):
            coleta_cmasgyn.atualizar_lexico_de_entidades(http, fonte)

    lexico = Lexico()   # carregado DEPOIS da atualização do léxico de entidades

    for fonte in _fontes("diaria"):
        if fonte["tipo"] == "dom":
            for meta in coleta_dom.coletar(http, dias_retroativos=3):
                texto = (ACERVO.parent / meta["txt"]).read_text(encoding="utf-8")
                t = processar(meta["data"], texto, lexico)
                if t:
                    retencao.marcar_relevante(
                        meta["data"], sorted({g for x in t for g in x.grupos})
                    )
                trechos_do_dia.extend(t)
        elif fonte["tipo"] == "html_lista":
            r = coleta_cmasgyn.coletar_lista(http, fonte)
            achados.extend(r["alterados"])
            for novo in r["novos"]:
                arq = ACERVO.parent / novo["arquivo"]
                txt = arq.with_suffix(".txt")
                if txt.exists():
                    trechos_do_dia.extend(
                        processar(novo["arquivo"], txt.read_text(encoding="utf-8"), lexico)
                    )

    # ------------------------------------- 2. DETERMINÍSTICO (custo zero)
    achados.extend(conformidade.executar_todas())
    achados.extend(igd.rastrear(trechos_do_dia))
    achados.extend(igd.auditar_opacidade())

    # ------------------------------------------------- 3. DEDUPLICAÇÃO (R3)
    analisados = ler_json(ANALISADOS, {})
    from util import sha256_bytes
    pendentes = []
    for i, t in enumerate(trechos_do_dia):
        h = sha256_bytes(t.texto.encode("utf-8"))
        if h in analisados:
            continue
        pendentes.append({"id": f"t{i}_{h[:10]}", "hash": h, "trecho": t,
                          "conteudo": t.texto, "peso": t.peso})
    log.info("%d trecho(s) novos após deduplicação (de %d)",
             len(pendentes), len(trechos_do_dia))

    pendentes.sort(key=lambda p: -p["peso"])

    try:
        # ------------------------------------------------- 4. TRIAGEM (barato)
        triagem = chamar_em_lote(
            "triagem", [{"id": p["id"], "conteudo": p["conteudo"]} for p in pendentes], orc
        )
        aprovados = [p for p in pendentes
                     if triagem.get(p["id"], {}).get("relevante") is True]
        log.info("Triagem aprovou %d de %d", len(aprovados), len(pendentes))

        # ----------------------------------------------- 5. EXTRAÇÃO (médio)
        extraidos = chamar_em_lote(
            "extracao", [{"id": p["id"], "conteudo": p["conteudo"]} for p in aprovados], orc
        )

        # ---------------------------------------------- 6. VALIDAÇÃO (caro)
        for p in aprovados:
            dados = extraidos.get(p["id"])
            if not dados:
                continue
            if not dados.get("exige_validacao_juridica", True):
                continue
            import json
            entrada = (
                "ATO MUNICIPAL A VALIDAR (dados já extraídos):\n"
                + json.dumps(dados, ensure_ascii=False, indent=1)
                + "\n\nTRECHO ORIGINAL:\n" + p["conteudo"]
            )
            resultado = chamar("validacao", entrada, orc)
            for a in resultado.get("achados", []):
                a.setdefault("documento", p["trecho"].documento)
                a.setdefault("detectado_em", agora().isoformat())
                achados.append(a)
            analisados[p["hash"]] = {"em": hoje_iso(), "doc": p["trecho"].documento}

    except LimiteAtingido as e:
        log.warning("Parada planejada: %s", e)
        for p in pendentes:
            if p["hash"] not in analisados:
                Orcamento.enfileirar({
                    "id": p["id"], "hash": p["hash"], "peso": p["peso"],
                    "documento": p["trecho"].documento, "conteudo": p["conteudo"],
                    "data": hoje_iso(),
                })
        Orcamento.agendar_retomada()
    else:
        Orcamento.limpar_retomada()

    gravar_json(ANALISADOS, analisados)

    # ------------------------------------------------------ 7. RETENÇÃO
    resumo_retencao = retencao.expurgar()

    # ------------------------------------------------------- 8. BOLETIM
    boletim = _boletim(achados, orc, resumo_retencao, len(trechos_do_dia))
    (RELATORIOS / f"boletim_{hoje_iso()}.md").write_text(boletim, encoding="utf-8")
    gravar_json(RELATORIOS / f"achados_{hoje_iso()}.json", achados)
    print(boletim)

    return 2 if any(a.get("severidade") == "alta" for a in achados) else 0


def _boletim(achados: list[dict], orc: Orcamento, retencao_: dict, n_trechos: int) -> str:
    ordem = {"alta": 0, "media": 1, "baixa": 2}
    achados = sorted(achados, key=lambda a: ordem.get(a.get("severidade", "baixa"), 3))

    linhas = [
        f"# Boletim de vigilância — {hoje_iso()}",
        "",
        f"Trechos filtrados: {n_trechos} | Achados: {len(achados)} | "
        f"Tokens: {orc.consumido()} de {orc.teto} (teto de 50%)",
        f"Retenção: {retencao_['apagados']} edição(ões) expurgada(s), "
        f"{retencao_['mb_liberados']} MB liberados.",
        "",
    ]
    if not achados:
        linhas.append("Nenhum achado no período.")
        return "\n".join(linhas)

    atual = None
    for a in achados:
        sev = a.get("severidade", "baixa")
        if sev != atual:
            atual = sev
            linhas += ["", f"## Severidade {sev}", ""]
        linhas.append(f"### [{a.get('regra','—')}] {a.get('titulo','(sem título)')}")
        linhas.append(a.get("detalhe", ""))
        if a.get("documento"):
            linhas.append(f"Documento: `{a['documento']}`")
        if a.get("fundamento"):
            linhas.append(f"Fundamento: {a['fundamento']}")
        if a.get("saida_sugerida"):
            linhas.append(f"Encaminhamento sugerido: **{a['saida_sugerida']}**")
        linhas.append("")

    linhas += [
        "---",
        "",
        "Achados gerados por rotina automatizada. Nenhuma peça deve ser protocolada "
        "sem revisão do advogado responsável, nos termos do artigo 32 da Lei 8.906/1994.",
    ]
    return "\n".join(linhas)


if __name__ == "__main__":
    sys.exit(executar())
