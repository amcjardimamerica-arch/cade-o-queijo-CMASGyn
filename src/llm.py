"""Camada de acesso ao modelo.

Roteia cada tarefa ao modelo mais barato que dá conta dela, marca o corpus
normativo como prefixo cacheável de uma hora e usa a Batch API onde não há
urgência. Regras R4, R5, R6 e R8 de economia.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import anthropic

from orcamento import LimiteAtingido, Orcamento, reset_dos_cabecalhos
from util import CORPUS, RAIZ, carregar_yaml, ler_json, log

_cfg = carregar_yaml("modelos.yml")
NIVEIS = _cfg["niveis"]

_cliente = None


def cliente() -> anthropic.Anthropic:
    global _cliente
    if _cliente is None:
        chave = os.environ.get("ANTHROPIC_API_KEY")
        if not chave:
            raise RuntimeError("ANTHROPIC_API_KEY ausente no ambiente")
        _cliente = anthropic.Anthropic(api_key=chave)
    return _cliente


def carregar_corpus() -> str:
    """Corpus consolidado. Prefixo byte-idêntico entre chamadas — requisito do cache."""
    arq = CORPUS / "corpus.md"
    if not arq.exists():
        raise RuntimeError(
            "corpus/corpus.md ausente. Execute src/corpus_build.py antes da rotina diária."
        )
    return arq.read_text(encoding="utf-8")


def _prompt(nome: str) -> str:
    return (RAIZ / "prompts" / f"{nome}.md").read_text(encoding="utf-8")


def _so_json(texto: str) -> dict:
    """Aceita resposta com ou sem cerca de código; falha explicitamente."""
    limpo = re.sub(r"^```(?:json)?|```$", "", texto.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(limpo)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", limpo, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise


def _sistema(nivel: str, cfg: dict) -> list[dict]:
    """Monta o bloco de sistema. O que é estável vem primeiro e leva cache_control."""
    blocos: list[dict] = []
    if cfg.get("corpus_no_prompt"):
        blocos.append({
            "type": "text",
            "text": carregar_corpus(),
            "cache_control": {"type": "ephemeral", "ttl": cfg.get("cache_ttl", "1h")},
        })
    blocos.append({"type": "text", "text": _prompt(nivel)})
    return blocos


def chamar(nivel: str, conteudo: str, orcamento: Orcamento) -> dict:
    """Chamada síncrona. Usada em validação e redação."""
    cfg = NIVEIS[nivel]
    estimativa = len(conteudo) // 3 + cfg["max_tokens"]
    if not orcamento.pode_gastar(nivel, estimativa):
        raise LimiteAtingido(f"Sem cota para o nível {nivel}")

    try:
        r = cliente().messages.create(
            model=cfg["modelo"],
            max_tokens=cfg["max_tokens"],
            temperature=cfg.get("temperatura", 0),
            system=_sistema(nivel, cfg),
            messages=[{"role": "user", "content": conteudo}],
        )
    except anthropic.RateLimitError as e:
        Orcamento.agendar_retomada(reset_dos_cabecalhos(getattr(e, "response", None).headers
                                                        if getattr(e, "response", None) else {}))
        raise LimiteAtingido("Limite da API atingido") from e

    u = r.usage
    gastos = (u.input_tokens + u.output_tokens
              + getattr(u, "cache_creation_input_tokens", 0)
              + int(getattr(u, "cache_read_input_tokens", 0) * 0.1))
    log.info("[%s] entrada=%s cache_lido=%s saída=%s",
             nivel, u.input_tokens,
             getattr(u, "cache_read_input_tokens", 0), u.output_tokens)
    orcamento.registrar(nivel, gastos)

    texto = "".join(b.text for b in r.content if b.type == "text")
    return _so_json(texto) if cfg.get("saida", "").startswith("json") else {"texto": texto}


def chamar_em_lote(nivel: str, itens: list[dict], orcamento: Orcamento) -> dict[str, dict]:
    """Batch API: metade do preço. Usada em triagem e extração.

    `itens` são dicionários com `id` e `conteudo`.
    """
    if not itens:
        return {}
    cfg = NIVEIS[nivel]
    requisicoes = [{
        "custom_id": it["id"],
        "params": {
            "model": cfg["modelo"],
            "max_tokens": cfg["max_tokens"],
            "temperature": cfg.get("temperatura", 0),
            "system": _sistema(nivel, cfg),
            "messages": [{"role": "user", "content": it["conteudo"]}],
        },
    } for it in itens]

    lote = cliente().messages.batches.create(requests=requisicoes)
    log.info("[%s] lote %s criado com %d itens", nivel, lote.id, len(itens))

    while True:
        lote = cliente().messages.batches.retrieve(lote.id)
        if lote.processing_status == "ended":
            break
        time.sleep(20)

    saidas: dict[str, dict] = {}
    total = 0
    for res in cliente().messages.batches.results(lote.id):
        if res.result.type != "succeeded":
            log.warning("Item %s falhou no lote: %s", res.custom_id, res.result.type)
            continue
        msg = res.result.message
        total += msg.usage.input_tokens + msg.usage.output_tokens
        texto = "".join(b.text for b in msg.content if b.type == "text")
        try:
            saidas[res.custom_id] = _so_json(texto)
        except json.JSONDecodeError:
            log.warning("Resposta não-JSON em %s", res.custom_id)

    orcamento.registrar(nivel, total // 2)  # desconto de 50% da Batch API
    return saidas
