"""Sondagem das fontes federais ainda sem coletor (SIOPE, SIOPS, Tesouro, FNS, FNDE, Transferegov).

Roda no GitHub, onde a rede é aberta. Para cada endereço candidato guarda o código de resposta,
o tipo e o começo do corpo em ``relatorios/onisciente/sondagem/``. Quando a fonte é um catálogo
CKAN ou um serviço OData, lista os recursos e lê uma amostra pequena de cada um. Só lê; não
grava nada no banco. O resultado serve para escrever os coletores sem adivinhar endereço.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from . import RAIZ
from .coletores.base import ler

PASTA = RAIZ / "relatorios" / "onisciente" / "sondagem"
LIMITE = 120_000

OLINDA = "https://www.fnde.gov.br/olinda-ide/servico/"
CANDIDATOS: dict[str, list[str]] = {
    "siope": [
        OLINDA,
        OLINDA + "DADOS_ABERTOS_SIOPE/versao/v1/odata/",
        OLINDA + "DADOS_ABERTOS_SIOPE/versao/v1/odata/$metadata",
        OLINDA + "DADOS_ABERTOS_SIOPE/versao/v1/documentacao",
    ],
    "fnde": [
        "https://www.fnde.gov.br/dadosabertos/api/3/action/package_list",
        "https://www.fnde.gov.br/dadosabertos/api/3/action/package_search?q=transferencias&rows=20",
    ],
    "siops": [
        "https://opendatasus.saude.gov.br/api/3/action/package_search?q=siops&rows=20",
        "https://opendatasus.saude.gov.br/api/3/action/package_show?id=siops",
        "http://siops.datasus.gov.br/consleirespfiscal.php",
        "http://siops.datasus.gov.br/rel_LRF.php",
        "http://siops.datasus.gov.br/indicadores.php",
    ],
    "fns": [
        "https://opendatasus.saude.gov.br/api/3/action/package_search?q=fundo%20a%20fundo&rows=20",
        "https://consultafns.saude.gov.br/",
        "https://consultafns.saude.gov.br/recursos/consulta-detalhada",
    ],
    "tesouro": [
        "https://www.tesourotransparente.gov.br/ckan/api/3/action/package_search?q="
        + quote("transferências constitucionais") + "&rows=20",
        "https://www.tesourotransparente.gov.br/ckan/api/3/action/package_show?id="
        "transferencias-constitucionais-para-municipios",
    ],
    "transferegov": [
        "https://api.transferegov.gestao.gov.br/transferenciasespeciais/",
        "https://api.transferegov.gestao.gov.br/fundoafundo/",
        "https://api.transferegov.gestao.gov.br/ted/",
    ],
}


def _slug(url: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", url.lower().split("://", 1)[-1])[:90].strip("-")


def _guardar(fonte: str, url: str, leitura) -> dict:
    PASTA.mkdir(parents=True, exist_ok=True)
    arq = PASTA / f"{fonte}__{_slug(url)}.txt"
    corpo = leitura.conteudo[:LIMITE].decode("utf-8", errors="replace") if leitura.ok else ""
    arq.write_text(f"URL: {url}\nOK: {leitura.ok}\nHTTP: {leitura.http}\nERRO: {leitura.erro}\n"
                   f"BYTES: {len(leitura.conteudo)}\n\n{corpo}", encoding="utf-8")
    return {"fonte": fonte, "url": url, "ok": leitura.ok, "http": leitura.http, "erro": leitura.erro,
            "bytes": len(leitura.conteudo), "arquivo": arq.name}


def _seguir(fonte: str, url: str, leitura) -> list[str]:
    """Endereços de segunda rodada: amostras de conjuntos OData e recursos CKAN."""
    if not leitura.ok:
        return []
    texto = leitura.texto
    novos: list[str] = []
    if url.endswith("/odata/"):
        try:
            for conj in json.loads(texto).get("value", []):
                nome = conj.get("url") or conj.get("name")
                if nome:
                    novos.append(url + nome + "?$top=3&$format=json")
        except ValueError:
            pass
    if "/api/3/action/package_" in url:
        try:
            res = json.loads(texto).get("result")
        except ValueError:
            return []
        pacotes = res.get("results", []) if isinstance(res, dict) and "results" in res else \
            [res] if isinstance(res, dict) else []
        for pac in pacotes[:12]:
            for r in (pac.get("resources") or [])[:6]:
                u = r.get("url") or ""
                if u.lower().endswith((".csv", ".json")) or "api" in u.lower():
                    novos.append(u)
    return novos[:25]


def sondar() -> list[dict]:
    resultado = []
    for fonte, urls in CANDIDATOS.items():
        fila = list(urls)
        vistos: set[str] = set()
        while fila:
            url = fila.pop(0)
            if url in vistos:
                continue
            vistos.add(url)
            leitura = ler(url, tempo=60, fonte=fonte)
            resultado.append(_guardar(fonte, url, leitura))
            if url in urls:
                fila.extend(_seguir(fonte, url, leitura))
    (PASTA / "indice.json").write_text(json.dumps(
        {"quando": datetime.now(timezone.utc).isoformat(timespec="seconds"), "leituras": resultado},
        ensure_ascii=False, indent=1), encoding="utf-8")
    return resultado


if __name__ == "__main__":
    for r in sondar():
        print(("OK " if r["ok"] else "FALHA ") + f"{r['fonte']}: {r['url']} {r['http'] or r['erro']}")
