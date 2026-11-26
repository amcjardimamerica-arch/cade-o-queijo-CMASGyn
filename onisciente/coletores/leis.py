"""Coletores da régua legal: ctresb/leis e Sileg.

* ctresb/leis: a Constituição, as leis federais e as de Goiás. Cada norma do
  mapa legal aponta para o arquivo dela; antes de usar uma regra o motor
  confere o campo ``revogada`` do cabeçalho.
* Sileg: as leis de Goiânia, num endereço previsível. O texto é guardado só
  como trecho, com o link e a impressão digital.
"""

from __future__ import annotations

import html
import re

import yaml

from ..legal.mapa import MapaLegal, carregar
from .base import ler

RAW_CTRESB = "https://raw.githubusercontent.com/ctresb/leis/main/"


def cabecalho(markdown: str) -> dict:
    """Lê o cabeçalho YAML de uma norma no formato do ctresb/leis."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", markdown, flags=re.S)
    if not m:
        return {}
    dados = yaml.safe_load(m.group(1)) or {}
    return dados if isinstance(dados, dict) else {}


def conferir_ctresb(mapa: MapaLegal | None = None, *, ler_url=ler) -> list[dict]:
    """Confere cada arquivo do ctresb/leis citado no mapa: existe? está revogado?"""
    mapa = mapa or carregar()
    saida = []
    vistos: set[str] = set()
    for norma in mapa.normas.values():
        for caminho in norma.ctresb:
            if caminho in vistos:
                continue
            vistos.add(caminho)
            leitura = ler_url(RAW_CTRESB + caminho, fonte="ctresb/leis")
            item = {"norma": norma.norma, "caminho": caminho, "ok": leitura.ok}
            if leitura.ok:
                cab = cabecalho(leitura.texto)
                item.update(titulo=cab.get("titulo"), revogada=bool(cab.get("revogada", False)),
                            sha256=leitura.original.sha256 if leitura.original else None)
            else:
                item["erro"] = leitura.erro
            saida.append(item)
    return saida


def texto_do_html(pagina: str) -> str:
    """Extrai só o texto de uma página do Sileg (sem guardar o documento)."""
    pagina = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", pagina)
    pagina = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", pagina)
    texto = html.unescape(re.sub(r"<[^>]+>", " ", pagina))
    linhas = [re.sub(r"[ \t\xa0]+", " ", l).strip() for l in texto.splitlines()]
    return "\n".join(l for l in linhas if l)


def ler_sileg(url: str, *, ler_url=ler) -> dict:
    leitura = ler_url(url, fonte="Sileg")
    if not leitura.ok:
        return {"url": url, "ok": False, "erro": leitura.erro}
    texto = texto_do_html(leitura.conteudo.decode("latin-1", errors="replace")
                          if b"charset=iso-8859-1" in leitura.conteudo[:2000].lower()
                          else leitura.texto)
    return {"url": url, "ok": True, "sha256": leitura.original.sha256 if leitura.original else None,
            "inicio": texto[:600]}
