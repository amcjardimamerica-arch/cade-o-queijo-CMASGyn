"""Coleta do Diário Oficial pelo índice Solr do SILEG.

Descoberta relevante: o sistema de consulta da Casa Civil expõe um índice Solr
de leitura pública em `https://sileg.goiania.go.gov.br/solr-4.1.0/select`, com
o texto integral das edições. Isso inverte a economia do projeto.

Antes: baixar 14 MB por dia e varrer com expressão regular.
Agora: perguntar ao índice quais edições contêm os termos de interesse e baixar
apenas essas. Na maioria dos dias, nenhuma.

O acesso é anônimo, não autenticado e sobre dado público, no exercício da
faculdade do artigo 8º, § 3º, incisos II e III, da Lei 12.527/2011.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

import requests
import urllib3

from cliente_http import ClienteHTTP
from util import (ACERVO, ESTADO, agora, extrair_texto_pdf, gravar_json,
                  ler_json, log)

urllib3.disable_warnings()

SOLR = "https://sileg.goiania.go.gov.br/solr-4.1.0/select"
BASE_PDF = "http://sileg.goiania.go.gov.br/geral/"
REGISTRO = ESTADO / "dom_registro.json"
RE_ID = re.compile(r"(do|lo|lc|dec)_(\d{8})_(\d+)", re.IGNORECASE)


def _nome(identificador: str) -> str:
    return re.sub(r"^.*/", "", identificador).lstrip("./")


def _data_do_id(identificador: str) -> date | None:
    m = RE_ID.search(identificador)
    if not m:
        return None
    s = m.group(2)
    try:
        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except ValueError:
        return None


def consultar(termos: list[str], desde: date, ate: date, limite: int = 300) -> list[str]:
    """Identificadores das edições que contêm qualquer dos termos, no período."""
    clausula = " OR ".join(f'attr_content:"{t}"' for t in termos)
    s = requests.Session()
    s.headers["User-Agent"] = "AMC-Jardim-America-Vigilancia/1.0"
    s.verify = False
    try:
        r = s.get(SOLR, params={"q": clausula, "wt": "json", "rows": limite,
                                "fl": "id", "sort": "id desc"}, timeout=90)
        r.raise_for_status()
        dados = r.json()
    except Exception as e:
        log.error("Consulta ao índice falhou: %s", e)
        return []

    total = dados["response"]["numFound"]
    ids = [d["id"] for d in dados["response"]["docs"]]
    no_periodo = [i for i in ids
                  if (d := _data_do_id(i)) and desde <= d <= ate]
    log.info("Índice: %d documento(s) com os termos no acervo histórico; "
             "%d no período de %s a %s", total, len(no_periodo),
             desde.isoformat(), ate.isoformat())
    return no_periodo


def coletar(http: ClienteHTTP, dias_retroativos: int = 3,
            termos: list[str] | None = None) -> list[dict]:
    termos = termos or [
        "CMASGyn", "CMAS", "Conselho Municipal de Assistência Social",
        "Fundo Municipal de Assistência Social",
        "Índice de Gestão Descentralizada", "IGD",
    ]
    hoje = agora().date()
    desde = hoje - timedelta(days=dias_retroativos)

    registro = ler_json(REGISTRO, {})
    coletados: list[dict] = []

    for identificador in consultar(termos, desde, hoje):
        nome = _nome(identificador)
        d = _data_do_id(identificador)
        chave = f"{d.isoformat()}_{nome}"
        if registro.get(chave, {}).get("sha256"):
            continue

        destino = ACERVO / "dom" / f"{d.year:04d}" / nome
        r = http.baixar(BASE_PDF + nome, destino)
        if r.status != 200 or not destino.exists():
            log.warning("Falha ao baixar %s (HTTP %s)", nome, r.status)
            continue

        texto, usou_ocr = extrair_texto_pdf(destino)
        txt = destino.with_suffix(".txt")
        txt.write_text(texto, encoding="utf-8")

        meta = {"data": d.isoformat(), "arquivo": nome, "url": BASE_PDF + nome,
                "pdf": str(destino.relative_to(ACERVO.parent)),
                "txt": str(txt.relative_to(ACERVO.parent)),
                "sha256": r.sha256, "bytes": destino.stat().st_size,
                "ocr": usou_ocr, "caracteres": len(texto),
                "coletado_em": agora().isoformat(), "relevante": True}
        registro[chave] = meta
        coletados.append(meta)
        log.info("Edição %s: %.1f MB, %d caracteres%s", d.isoformat(),
                 meta["bytes"] / 1e6, len(texto), " (via OCR)" if usou_ocr else "")

    gravar_json(REGISTRO, registro)
    if not coletados:
        log.info("Nenhuma edição com os termos no período. Custo do dia: zero.")
    return coletados
