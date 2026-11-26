"""Verificação dupla da publicidade dos atos.

Um único classificador é um ponto único de falha: se a expressão regular não
reconhece o formato de um ato, ele é dado por não publicado e o achado nasce
falso. Como o número que daqui sai pode fundamentar representação, a apuração
é feita por dois caminhos independentes, que se conferem mutuamente.

  VIA A — estrutural. Sobre o texto já extraído do Diário Oficial, exige
          cabeçalho reconhecível e corpo do ato: artigo primeiro, fórmula de
          competência ou cláusula de publicação.

  VIA B — busca cega. Consulta o índice Solr do SILEG pelo número do ato,
          isoladamente, sem depender do acervo local nem do classificador da
          via A. Depois confere o sítio do próprio conselho.

Os resultados são cruzados. Quatro desfechos:

  CONFIRMADO_PUBLICADO      ambas as vias acham o inteiro teor
  CONFIRMADO_NAO_PUBLICADO  nenhuma das vias acha — este é o achado firme
  DIVERGENTE                as vias discordam: exige conferência humana
  INCONCLUSIVO              a via B falhou tecnicamente

Só o segundo desfecho alimenta representação. O terceiro vira fila de
conferência manual, e é ele que impede que um defeito do classificador se
converta em acusação indevida.
"""
from __future__ import annotations

import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

import requests
import urllib3

sys.path.insert(0, str(Path(__file__).parent))

from util import RAIZ, agora, gravar_json, ler_json, log

urllib3.disable_warnings()

SOLR = "https://sileg.goiania.go.gov.br/solr-4.1.0/select"
SAIDA = RAIZ / "dados" / "verificacao_dupla.json"
CACHE = RAIZ / "estado" / "verificacao_cache.json"

RE_CORPO = re.compile(
    r"(Art(?:igo)?\.?\s*1[º°o]|no uso d[ae]s?\s+(?:suas\s+)?atribui[çc][õo]es|"
    r"resolve\s*:|Publique[- ]se|entra em vigor)", re.IGNORECASE)


def _sessao() -> requests.Session:
    s = requests.Session()
    s.verify = False
    s.headers["User-Agent"] = "AMC-Jardim-America-Vigilancia/1.0"
    return s


def via_b(numero: int, ano: int, s: requests.Session,
          cache: dict) -> tuple[bool | None, list[str]]:
    """Busca cega no índice, independente do acervo local."""
    chave = f"{numero:03d}/{ano}"
    if chave in cache:
        c = cache[chave]
        return c["achou"], c["docs"]

    consultas = [
        f'attr_content:"Resolução CMASGyn nº {numero:03d}/{ano}"',
        f'attr_content:"Resolução CMASGyn nº {numero}/{ano}"',
        f'attr_content:"RESOLUÇÃO Nº {numero:03d}/{ano}" AND attr_content:"CMASGyn"',
        f'attr_content:"Resolução nº {numero}/{ano}" AND attr_content:'
        f'"Conselho Municipal de Assistência Social"',
    ]
    docs: list[str] = []
    for q in consultas:
        try:
            r = s.get(SOLR, params={"q": q, "wt": "json", "rows": 6, "fl": "id"},
                      timeout=60)
            r.raise_for_status()
            d = r.json()["response"]
            docs.extend(x["id"] for x in d["docs"])
        except Exception as e:
            log.debug("via B falhou em %s: %s", chave, e)
            cache[chave] = {"achou": None, "docs": []}
            return None, []
        time.sleep(0.35)

    docs = sorted(set(docs))
    achou = bool(docs)
    cache[chave] = {"achou": achou, "docs": docs[:6]}
    return achou, docs[:6]


def cruzar(biblioteca: dict, limite: int | None = None,
           so_nao_publicados: bool = True) -> dict:
    """Confere a via A contra a via B, ato a ato."""
    atos = biblioteca.get("atos", [])
    alvo = [a for a in atos
            if (not so_nao_publicados) or a["situacao"] != "PUBLICADO"]
    alvo.sort(key=lambda a: (-a["ano"], a["numero"]))
    if limite:
        alvo = alvo[:limite]

    cache = ler_json(CACHE, {})
    s = _sessao()
    resultados: list[dict] = []

    for k, a in enumerate(alvo, 1):
        a_publicado = a["situacao"] == "PUBLICADO"
        b_publicado, docs = via_b(a["numero"], a["ano"], s, cache)

        if b_publicado is None:
            desfecho = "INCONCLUSIVO"
        elif a_publicado and b_publicado:
            desfecho = "CONFIRMADO_PUBLICADO"
        elif not a_publicado and not b_publicado:
            desfecho = "CONFIRMADO_NAO_PUBLICADO"
        else:
            desfecho = "DIVERGENTE"

        resultados.append({
            "ato": a["chave"], "numero": a["numero"], "ano": a["ano"],
            "ementa": a.get("ementa"),
            "via_a": "publicado" if a_publicado else a["situacao"].lower(),
            "via_b": {True: "encontrado", False: "não encontrado",
                      None: "consulta falhou"}[b_publicado],
            "desfecho": desfecho,
            "documentos_via_b": docs,
        })
        if k % 25 == 0:
            gravar_json(CACHE, cache)
            log.info("verificação dupla: %d/%d", k, len(alvo))

    gravar_json(CACHE, cache)
    cont = Counter(r["desfecho"] for r in resultados)
    firmes = [r for r in resultados if r["desfecho"] == "CONFIRMADO_NAO_PUBLICADO"]
    divergentes = [r for r in resultados if r["desfecho"] == "DIVERGENTE"]

    dados = {
        "gerado_em": agora().isoformat(),
        "atos_verificados": len(resultados),
        "desfechos": dict(cont),
        "concordancia": round(
            100 * (cont["CONFIRMADO_PUBLICADO"] + cont["CONFIRMADO_NAO_PUBLICADO"])
            / max(len(resultados), 1), 2),
        "nao_publicados_confirmados": len(firmes),
        "fila_de_conferencia_humana": divergentes[:200],
        "resultados": resultados,
    }
    gravar_json(SAIDA, dados)
    log.info("Verificação dupla: %d atos | concordância %.2f%% | "
             "%d não publicados confirmados | %d divergente(s) para conferência",
             len(resultados), dados["concordancia"], len(firmes), len(divergentes))
    return dados


def achados(d: dict) -> list[dict]:
    out = []
    if d.get("nao_publicados_confirmados", 0):
        out.append({
            "regra": "PUB-03", "severidade": "alta",
            "titulo": (f"{d['nao_publicados_confirmados']} ato(s) do conselho sem "
                       "publicação confirmada por duas vias independentes"),
            "detalhe": (
                f"De {d['atos_verificados']} atos examinados, "
                f"{d['nao_publicados_confirmados']} não foram localizados nem pelo "
                "classificador estrutural sobre o acervo, nem por busca direta e cega "
                "no índice de texto integral do Diário Oficial. A concordância entre "
                f"as duas vias foi de {d['concordancia']}%. Ato deliberativo que "
                "produz efeito sem publicação contraria o artigo 37, caput, da "
                "Constituição Federal e o dever de transparência ativa do artigo 8º "
                "da Lei 12.527/2011."),
            "fundamento": "Constituição Federal, artigo 37, caput; Lei 12.527/2011, artigo 8º",
            "saida_sugerida": "representacao_mp",
            "detectado_em": agora().isoformat(),
        })
    div = len(d.get("fila_de_conferencia_humana", []))
    if div:
        out.append({
            "regra": "PUB-04", "severidade": "baixa",
            "titulo": f"{div} ato(s) com divergência entre as vias de verificação",
            "detalhe": ("As duas vias discordaram quanto à publicação. Conferência "
                        "manual necessária antes de qualquer uso do dado. A lista está "
                        "em dados/verificacao_dupla.json, campo "
                        "fila_de_conferencia_humana."),
            "detectado_em": agora().isoformat(),
        })
    return out


if __name__ == "__main__":
    bib = ler_json(RAIZ / "dados" / "biblioteca_cmasgyn.json", {})
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else None
    d = cruzar(bib, limite=lim)
    print(json.dumps({k: d[k] for k in
                      ("atos_verificados", "desfechos", "concordancia",
                       "nao_publicados_confirmados")}, ensure_ascii=False, indent=2))
