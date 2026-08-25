"""Arquiva as Resoluções nacionais do CNAS formalmente vigentes.

Critério de vigência:

1. parte-se da relação oficial de atos vigentes consolidada pela Portaria MC
   nº 833/2022 (página do Sistema de Regulação do SUAS, código 6328);
2. acrescentam-se as Resoluções do CNAS posteriores à data-base da Portaria;
3. removem-se as normas expressamente revogadas por resolução posterior;
4. cada item só é marcado ``texto_integral`` quando o conteúdo oficial foi
   efetivamente baixado e arquivado.

O inventário diferencia ``vigência formal`` de ``efeito temporal exaurido``.
Uma resolução anual pode continuar formalmente não revogada, mas não servir de
fundamento para exercício posterior. Essa distinção evita apagar norma sem ato
revogador e evita tratá-la como regra material permanente.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, asdict
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).parent))

from util import RAIZ, agora, gravar_json, log

BASE = "https://aplicacoes.mds.gov.br/snas/regulacao/"
BASELINE_URL = urljoin(BASE, "visualizar.php?codigo=6328")
REGISTRO_URL = urljoin(BASE, "atos_normativos.php")
CORPUS = RAIZ / "corpus" / "cnas_vigentes"
INVENTARIO = RAIZ / "docs" / "INVENTARIO_CNAS.md"
MANIFESTO = RAIZ / "corpus" / "cnas_manifesto.json"
DATA_BASE = date(2022, 8, 1)

RE_CHAVE = re.compile(
    r"resolu[cç][aã]o(?:\s+conjunta)?(?:\s+cnas(?:\s*(?:/|e)?\s*"
    r"(?:mc|mds|cncd|cns|cnpcp|conanda))*)?\s*"
    r"(?:n[ºo°.]*)?\s*0*(\d{1,3})\s*(?:/|,\s*de.*?\b)(19\d{2}|20\d{2})",
    re.IGNORECASE,
)
RE_DATA = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")
RE_REVOGA = re.compile(
    r"revogad[ao]s?.{0,180}?resolu[cç][aã]o(?:\s+cnas(?:/\w+)?)?\s*"
    r"(?:n[ºo°.]*)?\s*0*(\d{1,3}).{0,80}?(19\d{2}|20\d{2})",
    re.IGNORECASE | re.DOTALL,
)


@dataclass
class Norma:
    numero: int
    ano: int
    titulo: str
    qualificador: str = "cnas"
    data_publicacao: str | None = None
    fonte_url: str | None = None
    origem_inclusao: str = ""
    arquivo: str | None = None
    sha256_fonte: str | None = None
    caracteres: int = 0
    texto_integral: bool = False
    vigencia_formal: str = "vigente"
    efeito_temporal: str = "a_classificar"
    revogada_por: str | None = None
    observacao: str | None = None

    @property
    def chave(self) -> str:
        sufixo = "" if self.qualificador == "cnas" else f" ({self.qualificador.replace('_', ' ')})"
        return f"{self.numero}/{self.ano}{sufixo}"


def _normalizar(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s).strip()


def _qualificador(texto: str) -> str:
    n = _normalizar(texto).casefold()
    if "resolucao conjunta" not in n:
        return "cnas"
    siglas = [s for s in ("cnas", "cncd", "cns", "cnpcp", "conanda")
              if re.search(rf"\b{s}\b", n)]
    return "conjunta_" + "_".join(siglas or ["cnas"])


def _chave(texto: str) -> tuple[int, int, str] | None:
    normal = _normalizar(texto)
    m = RE_CHAVE.search(normal)
    return (int(m.group(1)), int(m.group(2)), _qualificador(normal)) if m else None


def _data(texto: str) -> str | None:
    m = RE_DATA.search(texto)
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
    except ValueError:
        return None


def _sessao() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "AMC-CMASGyn-Vigilancia/1.0 (acervo normativo; contato no repositorio)",
        "Accept": "text/html,application/pdf;q=0.9,*/*;q=0.5",
    })
    return s


def _obter(s: requests.Session, url: str) -> tuple[bytes, str]:
    ultimo = None
    for tentativa in range(4):
        try:
            r = s.get(url, timeout=60)
            if r.status_code == 200 and r.content:
                return r.content, r.headers.get("content-type", "")
            ultimo = RuntimeError(f"HTTP {r.status_code}")
        except requests.RequestException as e:
            ultimo = e
        time.sleep(1.5 * (tentativa + 1))
    raise RuntimeError(f"falha ao obter {url}: {ultimo}")


def _linhas(html: bytes, base_url: str) -> list[dict]:
    sopa = BeautifulSoup(html, "lxml")
    saida = []
    for tr in sopa.select("tr"):
        texto = re.sub(r"\s+", " ", tr.get_text(" ", strip=True))
        if not texto:
            continue
        links = [urljoin(base_url, a.get("href")) for a in tr.select("a[href]")]
        saida.append({"texto": texto, "links": links})
    return saida


def _e_cnas(texto: str) -> bool:
    n = _normalizar(texto).casefold()
    return ("conselho nacional de assistencia social" in n or
            "resolucao do cnas" in n or "resolucao cnas" in n)


def _url_norma(links: list[str]) -> str | None:
    preferidos = [u for u in links if "in.gov.br" in u and "resolucao" in u.casefold()]
    preferidos += [u for u in links if "visualizar.php?codigo=" in u]
    preferidos += [u for u in links if u.lower().endswith(".pdf")]
    return preferidos[0] if preferidos else (links[0] if links else None)


def _texto(conteudo: bytes, tipo: str, url: str) -> str:
    if "pdf" in tipo.casefold() or conteudo[:4] == b"%PDF" or url.lower().endswith(".pdf"):
        leitor = PdfReader(io.BytesIO(conteudo))
        return "\n".join(p.extract_text() or "" for p in leitor.pages)
    sopa = BeautifulSoup(conteudo.decode("utf-8", errors="ignore"), "lxml")
    for tag in sopa(["script", "style", "nav", "header", "footer", "form"]):
        tag.decompose()
    return re.sub(r"[ \t]+", " ", sopa.get_text("\n")).strip()


def _efeito(texto: str, titulo: str) -> str:
    n = _normalizar(titulo + " " + texto[:1800]).casefold()
    temporais = ("calendario de reunio", "processo eleitoral", "exercicio de 20",
                 "trimestre", "conferencia nacional", "comissao organizadora",
                 "proposta orcamentaria")
    return "possivelmente_exaurido" if any(x in n for x in temporais) else "continuado_ou_indeterminado"


def construir() -> dict:
    CORPUS.mkdir(parents=True, exist_ok=True)
    s = _sessao()
    baseline_html, _ = _obter(s, BASELINE_URL)
    registro_html, _ = _obter(s, REGISTRO_URL)
    baseline = _linhas(baseline_html, BASELINE_URL)
    registro = _linhas(registro_html, REGISTRO_URL)

    mapa_registro: dict[tuple[int, int, str], dict] = {}
    for linha in registro:
        chave = _chave(linha["texto"])
        if chave and _e_cnas(linha["texto"]):
            atual = mapa_registro.setdefault(chave, linha)
            if not _url_norma(atual["links"]) and _url_norma(linha["links"]):
                mapa_registro[chave] = linha

    normas: dict[tuple[int, int, str], Norma] = {}
    for linha in baseline:
        chave = _chave(linha["texto"])
        if not (chave and _e_cnas(linha["texto"])):
            continue
        reg = mapa_registro.get(chave, linha)
        normas[chave] = Norma(
            numero=chave[0], ano=chave[1], qualificador=chave[2], titulo=linha["texto"][:500],
            data_publicacao=_data(linha["texto"]), fonte_url=_url_norma(reg["links"]),
            origem_inclusao="Portaria MC 833/2022 — relação oficial de vigentes",
        )

    for chave, linha in mapa_registro.items():
        data_iso = _data(linha["texto"])
        posterior = chave[1] > 2022 or (data_iso and date.fromisoformat(data_iso) > DATA_BASE)
        if posterior and chave not in normas:
            normas[chave] = Norma(
                numero=chave[0], ano=chave[1], qualificador=chave[2], titulo=linha["texto"][:500],
                data_publicacao=data_iso, fonte_url=_url_norma(linha["links"]),
                origem_inclusao="Resolução posterior à data-base da Portaria MC 833/2022",
            )

    textos: dict[tuple[int, int, str], str] = {}
    for i, (chave, norma) in enumerate(sorted(normas.items(), key=lambda x: (x[0][1], x[0][0]))):
        if not norma.fonte_url:
            norma.observacao = "URL oficial do texto integral não localizada no registro"
            continue
        try:
            conteudo, tipo = _obter(s, norma.fonte_url)
            texto = _texto(conteudo, tipo, norma.fonte_url)
            if len(texto) < 250:
                norma.observacao = f"extração insuficiente: {len(texto)} caracteres"
                continue
            sufixo = "" if norma.qualificador == "cnas" else f"_{norma.qualificador}"
            nome = f"resolucao_cnas_{norma.numero:03d}_{norma.ano}{sufixo}.txt"
            caminho = CORPUS / nome
            cabecalho = (
                f"RESOLUÇÃO CNAS {norma.chave}\n"
                f"Fonte oficial: {norma.fonte_url}\n"
                f"Capturada em: {agora().isoformat()}\n\n"
            )
            caminho.write_text(cabecalho + texto, encoding="utf-8")
            norma.arquivo = caminho.relative_to(RAIZ).as_posix()
            norma.sha256_fonte = hashlib.sha256(conteudo).hexdigest()
            norma.caracteres = len(texto)
            norma.texto_integral = True
            norma.efeito_temporal = _efeito(texto, norma.titulo)
            textos[chave] = texto
        except Exception as e:
            norma.observacao = str(e)[:300]
        if i and i % 20 == 0:
            log.info("CNAS: %d/%d normas processadas", i, len(normas))
        time.sleep(0.25)

    revogacoes: dict[tuple[int, int, str], tuple[int, int, str]] = {}
    for revogadora, texto in textos.items():
        for m in RE_REVOGA.finditer(_normalizar(texto)):
            revogada = (int(m.group(1)), int(m.group(2)), "cnas")
            if revogada in normas and revogada != revogadora:
                revogacoes[revogada] = revogadora
    for revogada, revogadora in revogacoes.items():
        normas[revogada].vigencia_formal = "revogada"
        normas[revogada].revogada_por = f"{revogadora[0]}/{revogadora[1]}"

    vigentes = [n for n in normas.values() if n.vigencia_formal == "vigente"]
    integrais = [n for n in vigentes if n.texto_integral]
    pendentes = [n for n in vigentes if not n.texto_integral]
    manifesto = {
        "gerado_em": agora().isoformat(),
        "metodo": "Portaria MC 833/2022 + atos posteriores - revogações expressas",
        "fontes": [BASELINE_URL, REGISTRO_URL],
        "candidatas": len(normas),
        "vigentes_formais": len(vigentes),
        "revogadas_detectadas": len(revogacoes),
        "vigentes_com_texto_integral": len(integrais),
        "vigentes_pendentes": len(pendentes),
        "completude_percentual": round(100 * len(integrais) / max(len(vigentes), 1), 2),
        "normas": [asdict(n) | {"chave": n.chave}
                   for n in sorted(normas.values(), key=lambda x: (x.ano, x.numero))],
    }
    gravar_json(MANIFESTO, manifesto)

    linhas = [
        "# Inventário das Resoluções nacionais vigentes do CNAS", "",
        f"Atualizado em {datetime.now().strftime('%d/%m/%Y')}.", "",
        "## Critério", "",
        "A relação parte da lista oficial de atos vigentes da Portaria MC nº 833/2022, "
        "acrescenta as Resoluções do CNAS posteriores e retira revogações expressas. "
        "Vigência formal e efeito temporal são campos distintos.", "",
        "| Situação | Quantidade |", "|---|---:|",
        f"| Vigentes formais | {len(vigentes)} |",
        f"| Com texto integral arquivado | {len(integrais)} |",
        f"| Pendentes de texto integral | {len(pendentes)} |",
        f"| Revogações expressas detectadas | {len(revogacoes)} |",
        f"| Completude | {manifesto['completude_percentual']}% |", "",
        "## Resoluções vigentes", "",
        "| Resolução | Data | Efeito temporal | Texto | Fonte oficial |", "|---|---|---|---|---|",
    ]
    for n in sorted(vigentes, key=lambda x: (x.ano, x.numero)):
        texto_status = n.arquivo or "PENDENTE"
        fonte = f"[abrir]({n.fonte_url})" if n.fonte_url else "não localizada"
        linhas.append(f"| {n.chave} | {n.data_publicacao or '—'} | {n.efeito_temporal} | "
                      f"`{texto_status}` | {fonte} |")
    if pendentes:
        linhas += ["", "## Pendências", ""]
        for n in pendentes:
            linhas.append(f"- **{n.chave}** — {n.observacao or 'texto não capturado'}")
    INVENTARIO.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    log.info("CNAS: %d vigentes; %d textos integrais; completude %.2f%%",
             len(vigentes), len(integrais), manifesto["completude_percentual"])
    return manifesto


if __name__ == "__main__":
    print(json.dumps(construir(), ensure_ascii=False, indent=2))
