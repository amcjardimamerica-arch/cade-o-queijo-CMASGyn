"""Construção do corpus normativo — tarefa MENSAL, jamais diária.

Consolida todas as normas num único arquivo estável. É esse arquivo que a
rotina diária lê como prefixo cacheável. Se o prefixo mudar de um byte, o
cache é perdido e o custo decuplica — por isso a atualização é mensal e
deliberada, e a rotina diária nunca busca norma nova.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup

from cliente_http import ClienteHTTP
from util import (CORPUS, RELATORIOS, agora, carregar_yaml, extrair_texto_pdf,
                  compactar_espacos, gravar_json, log, sha256_bytes)


def _texto_de(conteudo: bytes, tipo: str, destino: Path) -> str:
    if "pdf" in tipo.lower() or destino.suffix.lower() == ".pdf":
        destino.write_bytes(conteudo)
        texto, _ = extrair_texto_pdf(destino)
        return texto
    sopa = BeautifulSoup(conteudo.decode("utf-8", errors="ignore"), "html.parser")
    for tag in sopa(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    return compactar_espacos(sopa.get_text("\n"))


def _recortar_artigos(texto: str, artigos: list[str]) -> str:
    """Mantém só os artigos pedidos. A Constituição inteira custaria caro em cache."""
    if not artigos:
        return texto
    blocos = []
    for art in artigos:
        padrao = re.compile(
            rf"(Art\.?\s*{re.escape(art)}\s*[ºo°]?[\s.\-–].{{0,6000}}?)(?=Art\.?\s*\d)",
            re.IGNORECASE | re.DOTALL,
        )
        m = padrao.search(texto)
        if m:
            blocos.append(compactar_espacos(m.group(1)))
        else:
            log.debug("Artigo %s não localizado no recorte", art)
    return "\n\n".join(blocos)


def construir() -> dict:
    cfg = carregar_yaml("corpus.yml")
    padrao = carregar_yaml("fontes.yml")["defaults"]
    http = ClienteHTTP(
        user_agent=padrao["user_agent"],
        intervalo=padrao["intervalo_segundos"],
        timeout=padrao["timeout"],
        tentativas=padrao["tentativas"],
    )

    brutos = CORPUS / "brutos"
    brutos.mkdir(parents=True, exist_ok=True)

    partes: list[str] = []
    indice: list[dict] = []
    pendencias: list[str] = []

    for bloco, itens in cfg["blocos"].items():
        partes.append(f"\n\n{'=' * 78}\n# BLOCO: {bloco.upper()}\n{'=' * 78}\n")
        for item in itens:
            url = item.get("url", "")
            if not url or url == "CONFIRMAR":
                # As Resoluções do CNAS são reconciliadas e arquivadas por
                # cnas_corpus.py. Para as normas centrais declaradas no YAML,
                # usa-se a cópia oficial local em vez de manter falsa pendência.
                if bloco == "cnas":
                    m = re.fullmatch(r"r(\d+)_(\d{4})", item["id"])
                    local = (RAIZ / "corpus" / "cnas_vigentes" /
                             f"resolucao_cnas_{int(m.group(1)):03d}_{m.group(2)}.txt") if m else None
                    if local and local.exists():
                        texto = local.read_text(encoding="utf-8")
                        partes.append(f"\n\n## [{item['id']}] {item['nome']}\n"
                                      f"Fonte: {local.relative_to(RAIZ)}\n\n{texto}\n")
                        indice.append({
                            "id": item["id"], "nome": item["nome"], "bloco": bloco,
                            "url": f"arquivo:{local.relative_to(RAIZ)}",
                            "sha256": sha256_bytes(local.read_bytes()),
                            "caracteres": len(texto), "critico": item.get("critico", False),
                        })
                        continue
                pendencias.append(f"- **{item['id']}** — {item['nome']} — URL a confirmar")
                continue

            r = http.obter(url, condicional=False)
            if r.status != 200 or not r.conteudo:
                pendencias.append(
                    f"- **{item['id']}** — {item['nome']} — falha HTTP {r.status} em {url}"
                )
                continue

            destino = brutos / f"{item['id']}{'.pdf' if url.lower().endswith('.pdf') else '.html'}"
            destino.write_bytes(r.conteudo)
            texto = _texto_de(r.conteudo, r.tipo, destino)
            texto = _recortar_artigos(texto, item.get("recortar_artigos", []))

            if len(texto) < 300:
                pendencias.append(
                    f"- **{item['id']}** — {item['nome']} — texto extraído insuficiente "
                    f"({len(texto)} caracteres)"
                )
                continue

            partes.append(f"\n\n## [{item['id']}] {item['nome']}\nFonte: {url}\n\n{texto}\n")
            indice.append({
                "id": item["id"],
                "nome": item["nome"],
                "bloco": bloco,
                "url": url,
                "sha256": r.sha256,
                "caracteres": len(texto),
                "critico": item.get("critico", False),
            })
            log.info("Corpus: %s (%d caracteres)", item["id"], len(texto))

    cabecalho = (
        "# CORPUS NORMATIVO — VIGILÂNCIA DO CMASGyn\n"
        f"# Consolidado em {agora().date().isoformat()}\n"
        "# Este bloco é prefixo estável de prompt. Não editar manualmente.\n"
    )
    texto_final = cabecalho + "".join(partes)
    (CORPUS / "corpus.md").write_text(texto_final, encoding="utf-8")

    manifesto = {
        "gerado_em": agora().isoformat(),
        "sha256": sha256_bytes(texto_final.encode("utf-8")),
        "caracteres": len(texto_final),
        "tokens_estimados": len(texto_final) // 3,
        "normas": len(indice),
        "indice": indice,
        "pendencias": len(pendencias),
    }
    gravar_json(CORPUS / "manifesto.json", manifesto)

    if pendencias:
        (RELATORIOS / "corpus_pendencias.md").write_text(
            "# Pendências do corpus normativo\n\n"
            f"Gerado em {agora().date().isoformat()}.\n\n"
            "As normas abaixo não foram incorporadas. O agente não adivinha endereço: "
            "informe a URL em `config/corpus.yml` ou anexe o arquivo em `corpus/brutos/`.\n\n"
            + "\n".join(pendencias) + "\n",
            encoding="utf-8",
        )
        log.warning("%d pendência(s) registrada(s) em relatorios/corpus_pendencias.md",
                    len(pendencias))

    log.info("Corpus com %d normas, ~%d tokens", len(indice), manifesto["tokens_estimados"])
    return manifesto


if __name__ == "__main__":
    m = construir()
    sys.exit(0 if m["normas"] else 1)
