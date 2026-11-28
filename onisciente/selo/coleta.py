"""Coleta ao vivo para a auditoria do selo (roda no GitHub, onde a rede é aberta).

Lê as páginas das chaves ``e_*`` da sondagem e segue um nível de links internos cujo texto ou
endereço traga os termos de algum critério que olha aquela fonte. Guarda cada resposta no mesmo
formato da sondagem (``relatorios/onisciente/sondagem/<fonte>__<slug>.txt``) e grava o índice
``indice_e_selo.json`` com a data, que os verificadores usam para medir a atualidade.

    python -m onisciente selo --sondar        (rede)
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

from .. import sondagem
from ..coletores.base import ler
from .matriz import Matriz, carregar
from .verificadores import normalizar

LIMITE_POR_FONTE = 80
LINK = re.compile(r"""<a\b[^>]*href=["']([^"'#]+)["'][^>]*>(.*?)</a>""", re.I | re.S)


def termos_da_fonte(matriz: Matriz, fonte: str) -> set[str]:
    return {t for c in matriz.do_executivo() if fonte in c.onde for g in c.termos for t in g if len(t) >= 4}


def links_interessantes(url: str, html: str, termos: set[str]) -> list[str]:
    """Links do mesmo sítio cujo texto ou endereço traz algum termo dos critérios da fonte."""
    base = urlparse(url).netloc
    achados = []
    for href, texto in LINK.findall(html or ""):
        alvo = urljoin(url, href.strip())
        if urlparse(alvo).netloc != base or not alvo.startswith("http"):
            continue
        rotulo = normalizar(re.sub(r"<[^>]+>", " ", texto) + " " + alvo)
        if any(t in rotulo for t in termos):
            achados.append(alvo)
    return list(dict.fromkeys(achados))


def coletar(fontes: list[str] | None = None, matriz: Matriz | None = None, pausa: float = 0.5) -> list[dict]:
    matriz = matriz or carregar()
    resultado = []
    for fonte, urls in sondagem.CANDIDATOS.items():
        if not fonte.startswith("e_") or (fontes and fonte not in fontes):
            continue
        termos = termos_da_fonte(matriz, fonte)
        fila, vistos, lidos = list(urls), set(), 0
        while fila and lidos < LIMITE_POR_FONTE:
            url = fila.pop(0)
            if url in vistos:
                continue
            vistos.add(url)
            inicio = time.monotonic()
            leitura = ler(url, tempo=60, fonte=fonte)
            registro = sondagem._guardar(fonte, url, leitura)
            registro["segundos"] = round(time.monotonic() - inicio, 1)
            resultado.append(registro)
            lidos += 1
            if url in urls and leitura.ok and termos:
                fila.extend(u for u in links_interessantes(url, leitura.texto, termos) if u not in vistos)
            time.sleep(pausa)
    sondagem.PASTA.mkdir(parents=True, exist_ok=True)
    (sondagem.PASTA / "indice_e_selo.json").write_text(json.dumps(
        {"quando": datetime.now(timezone.utc).isoformat(timespec="seconds"), "leituras": resultado},
        ensure_ascii=False, indent=1), encoding="utf-8")
    return resultado
