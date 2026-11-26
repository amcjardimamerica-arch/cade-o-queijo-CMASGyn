"""Detecção de padrão nos atos do CMASGyn.

Responde a duas perguntas: os atos seguem um padrão, e quais atos fogem dele.
Tudo determinístico, sobre o texto já indexado.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

from util import agora, log

RE_RESOLUCAO = re.compile(
    r"RESOLU[ÇC][ÃA]O\s*(?:CMAS(?:Gyn)?)?\s*n?[.º°]?\s*(\d{1,4})\s*[/\-]\s*(\d{4})",
    re.IGNORECASE)
RE_EMENTA = re.compile(r"(disp[õo]e sobre|aprova|altera|revoga|institui|"
                       r"homologa|defere|indefere|estabelece|fixa|torna p[úu]blic)",
                       re.IGNORECASE)
RE_FUNDAMENTO = re.compile(
    r"(no uso d[ae]s?\s+(?:suas\s+)?atribui[çc][õo]es|considerando|"
    r"com fundamento|nos termos d[oa]|com base n[oa])", re.IGNORECASE)
RE_LEI_CITADA = re.compile(
    r"Lei\s*(?:n?[.º°]\s*)?(\d{1,2}\.?\d{3})\s*[/\-]\s*(\d{2,4})", re.IGNORECASE)
RE_RESOLUCAO_CNAS = re.compile(
    r"Resolu[çc][ãa]o\s*(?:CNAS(?:/MDS)?)?\s*n?[.º°]?\s*(\d{1,3})\s*[/\-]\s*(\d{4})",
    re.IGNORECASE)
RE_PUBLICACAO = re.compile(r"(publique[- ]se|registre[- ]se|cumpra[- ]se|"
                           r"esta resolu[çc][ãa]o entra em vigor)", re.IGNORECASE)
RE_ASSINA_PRESIDENTE = re.compile(r"presidente d[oa]\s+(?:CMAS|Conselho)", re.IGNORECASE)


ELEMENTOS = {
    "numero_e_ano": lambda t: bool(RE_RESOLUCAO.search(t)),
    "ementa": lambda t: bool(RE_EMENTA.search(t)),
    "formula_de_competencia": lambda t: bool(RE_FUNDAMENTO.search(t)),
    "base_legal_citada": lambda t: bool(RE_LEI_CITADA.search(t) or RE_RESOLUCAO_CNAS.search(t)),
    "clausula_de_vigencia": lambda t: bool(RE_PUBLICACAO.search(t)),
    "assinatura_da_presidencia": lambda t: bool(RE_ASSINA_PRESIDENTE.search(t)),
}


def perfil(texto: str) -> dict:
    return {k: f(texto) for k, f in ELEMENTOS.items()}


def analisar_acervo(docs: list[tuple[str, str, str]]) -> dict:
    """Recebe (documento, data, texto). Mede a aderência ao padrão dominante."""
    perfis, numeros, leis, resolucoes_cnas = {}, defaultdict(set), Counter(), Counter()
    for doc, data, texto in docs:
        p = perfil(texto)
        perfis[doc] = {"data": data, **p, "completude": sum(p.values()) / len(p)}
        for n, a in RE_RESOLUCAO.findall(texto):
            numeros[int(a)].add(int(n))
        for a, b in RE_LEI_CITADA.findall(texto):
            leis[f"Lei {a}/{b}"] += 1
        for a, b in RE_RESOLUCAO_CNAS.findall(texto):
            resolucoes_cnas[f"Resolução CNAS {a}/{b}"] += 1

    freq = {k: sum(1 for p in perfis.values() if p[k]) for k in ELEMENTOS}
    n = max(len(perfis), 1)
    padrao = {k: (v / n) for k, v in freq.items()}
    dominante = [k for k, v in padrao.items() if v >= 0.70]

    fora = [{"documento": d, "data": p["data"],
             "faltando": [k for k in dominante if not p[k]]}
            for d, p in perfis.items()
            if any(not p[k] for k in dominante)]
    fora.sort(key=lambda x: -len(x["faltando"]))

    lacunas = {}
    for ano, nums in numeros.items():
        if len(nums) >= 3:
            falt = sorted(set(range(min(nums), max(nums) + 1)) - nums)
            if falt:
                lacunas[ano] = falt

    log.info("Padrão: %d elemento(s) dominante(s); %d ato(s) fora do padrão",
             len(dominante), len(fora))
    return {
        "documentos": len(perfis),
        "aderencia_por_elemento": {k: round(v, 3) for k, v in padrao.items()},
        "elementos_dominantes": dominante,
        "fora_do_padrao": fora[:100],
        "numeracao_por_ano": {str(a): sorted(v) for a, v in numeros.items()},
        "lacunas_de_numeracao": {str(a): v for a, v in lacunas.items()},
        "leis_mais_citadas": leis.most_common(25),
        "resolucoes_cnas_citadas": resolucoes_cnas.most_common(25),
        "gerado_em": agora().isoformat(),
    }
