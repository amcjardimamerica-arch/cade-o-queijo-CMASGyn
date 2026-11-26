"""Coleta do acervo do CMASGyn: resoluções, plenárias, atas e entidades.

O ponto nevrálgico é o versionamento por hash. Se um arquivo já publicado
muda de conteúdo sem nova numeração nem errata, isso é achado de severidade
alta — e invisível a qualquer acompanhamento humano.
"""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from cliente_http import ClienteHTTP
from util import (ACERVO, CONFIG, ESTADO, agora, extrair_texto_pdf,
                  gravar_json, ler_json, log)

REGISTRO = ESTADO / "cmasgyn_registro.json"
BASE = "https://cmasgyn.com.br"

RE_RESOLUCAO = re.compile(r"resolucao[_-](\d{1,4})[_-](\d{4})", re.IGNORECASE)
RE_CNPJ = re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b")


def _links(html: str, pagina: str, filtro: str | None = None) -> list[str]:
    sopa = BeautifulSoup(html, "html.parser")
    saida = []
    for a in sopa.find_all("a", href=True):
        # O sítio publica caminhos no formato do Windows: \Resources\documentos\...
        href = a["href"].replace("\\", "/")
        if filtro and filtro.lower().replace("\\", "/") not in href.lower():
            continue
        if not filtro and not href.lower().endswith((".pdf", ".doc", ".docx")):
            continue
        saida.append(urljoin(pagina, href))
    return sorted(set(saida))


def coletar_lista(http: ClienteHTTP, fonte: dict) -> dict:
    """Baixa os arquivos de uma página de listagem e versiona cada um."""
    registro = ler_json(REGISTRO, {})
    achados_de_alteracao: list[dict] = []
    novos: list[dict] = []

    r = http.obter(fonte["url"], condicional=fonte.get("condicional", True))
    if r.inalterado:
        log.info("%s: página inalterada (304)", fonte["id"])
        return {"novos": [], "alterados": []}
    if r.status != 200 or not r.conteudo:
        log.warning("%s: HTTP %s", fonte["id"], r.status)
        return {"novos": [], "alterados": []}

    html = r.conteudo.decode("utf-8", errors="ignore")
    urls = _links(html, fonte["url"], fonte.get("padrao_arquivo"))
    log.info("%s: %d arquivo(s) listado(s)", fonte["id"], len(urls))

    pasta = ACERVO / "cmasgyn" / fonte["id"]
    for url in urls:
        nome = Path(url.split("?")[0]).name or "sem_nome.pdf"
        destino = pasta / nome
        anterior = registro.get(url, {})

        resp = http.baixar(url, destino)
        if resp.status == 304 or not resp.sha256:
            continue

        meta = {
            "url": url,
            "arquivo": str(destino.relative_to(ACERVO.parent)),
            "sha256": resp.sha256,
            "visto_em": agora().isoformat(),
            "fonte": fonte["id"],
        }

        if not anterior:
            m = RE_RESOLUCAO.search(nome)
            if m:
                meta["numero"], meta["exercicio"] = int(m.group(1)), int(m.group(2))
            texto, usou_ocr = extrair_texto_pdf(destino)
            destino.with_suffix(".txt").write_text(texto, encoding="utf-8")
            meta["ocr"] = usou_ocr
            meta["caracteres"] = len(texto)
            meta["versoes"] = [{"sha256": resp.sha256, "em": meta["visto_em"]}]
            novos.append(meta)
            log.info("Novo: %s", nome)

        elif anterior["sha256"] != resp.sha256:
            # ---- ALTERAÇÃO SILENCIOSA (regra RES-03) ----
            historico = anterior.get("versoes", [])
            arquivado = pasta / "versoes" / f"{anterior['sha256'][:12]}_{nome}"
            arquivado.parent.mkdir(parents=True, exist_ok=True)
            historico.append({"sha256": resp.sha256, "em": agora().isoformat()})
            meta["versoes"] = historico
            texto, _ = extrair_texto_pdf(destino)
            destino.with_suffix(".txt").write_text(texto, encoding="utf-8")
            achados_de_alteracao.append({
                "regra": "RES-03",
                "severidade": "alta",
                "arquivo": nome,
                "url": url,
                "sha_anterior": anterior["sha256"],
                "sha_atual": resp.sha256,
                "versoes": len(historico),
            })
            log.warning("ALTERAÇÃO SILENCIOSA em %s", nome)
        else:
            meta = {**anterior, "visto_em": meta["visto_em"]}

        registro[url] = meta

    gravar_json(REGISTRO, registro)
    return {"novos": novos, "alterados": achados_de_alteracao}


def atualizar_lexico_de_entidades(http: ClienteHTTP, fonte: dict) -> int:
    """Deriva termos de gatilho dos nomes e CNPJ das entidades inscritas.

    Só pessoa jurídica. Nome de conselheiro e de usuário não entra no léxico.
    """
    r = http.obter(fonte["url"], condicional=False)
    if r.status != 200 or not r.conteudo:
        log.warning("Entidades: HTTP %s", r.status)
        return 0

    sopa = BeautifulSoup(r.conteudo.decode("utf-8", errors="ignore"), "html.parser")
    texto = sopa.get_text("\n")

    cnpjs = sorted(set(RE_CNPJ.findall(texto)))
    nomes = sorted({
        l.strip() for l in texto.splitlines()
        if 8 < len(l.strip()) < 120
        and re.search(r"(associa|institut|funda|centro|lar|abrigo|casa|obra|"
                      r"soc(iedade)?|comunidad|pastoral|creche|apae|ong)",
                      l, re.IGNORECASE)
    })

    padroes = [re.escape(n) for n in nomes]
    for c in cnpjs:
        so_digitos = re.sub(r"\D", "", c)
        padroes.append(
            rf"{so_digitos[:2]}\.?{so_digitos[2:5]}\.?{so_digitos[5:8]}/?"
            rf"{so_digitos[8:12]}-?{so_digitos[12:]}"
        )

    saida = {
        "gerado_em": agora().isoformat(),
        "fonte": fonte["url"],
        "entidades": len(nomes),
        "cnpjs": len(cnpjs),
        "padroes": padroes,
    }
    import yaml
    (CONFIG / "termos_entidades.yml").write_text(
        yaml.safe_dump(saida, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    log.info("Léxico de entidades: %d nome(s), %d CNPJ", len(nomes), len(cnpjs))
    return len(padroes)
