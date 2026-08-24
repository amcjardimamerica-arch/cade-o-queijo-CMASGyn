"""Utilitários base do sistema de vigilância."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CONFIG = RAIZ / "config"
CORPUS = RAIZ / "corpus"
ACERVO = RAIZ / "acervo"
ESTADO = RAIZ / "estado"
RELATORIOS = RAIZ / "relatorios"

for _d in (CORPUS, ACERVO, ESTADO, RELATORIOS):
    _d.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)
log = logging.getLogger("vigilancia")


def agora() -> datetime:
    return datetime.now(timezone.utc)


def hoje_iso() -> str:
    return agora().date().isoformat()


def sha256_bytes(dados: bytes) -> str:
    return hashlib.sha256(dados).hexdigest()


def sha256_arquivo(caminho: Path) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def ler_json(caminho: Path, padrao=None):
    if not caminho.exists():
        return padrao if padrao is not None else {}
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        log.warning("JSON corrompido em %s; reiniciando", caminho)
        return padrao if padrao is not None else {}


def gravar_json(caminho: Path, dados) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_suffix(caminho.suffix + ".tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(caminho)


def anexar_jsonl(caminho: Path, registro: dict) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "a", encoding="utf-8") as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")


def normalizar(texto: str) -> str:
    """Remove acentos e baixa a caixa. Só para comparação, nunca para persistir."""
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def compactar_espacos(texto: str) -> str:
    """Colapsa espaços e quebras. Reduz tokens sem perder conteúdo."""
    texto = re.sub(r"[ \t\xa0]+", " ", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


_CABECALHO = re.compile(
    r"^\s*(di[áa]rio oficial do munic[íi]pio.*|"
    r"goi[âa]nia, .{0,40}de \d{4}.*|"
    r"ano [ivxlc]+ ?[-–] ?n[º°.]? ?\d+.*|"
    r"p[áa]gina \d+( de \d+)?|\d+)\s*$",
    re.IGNORECASE,
)


def remover_cabecalho_rodape(texto: str) -> str:
    """Descarta linhas de cabeçalho e rodapé recorrentes do Diário Oficial.

    Economia direta de tokens: em uma edição de 60 páginas isso costuma
    eliminar algumas centenas de linhas sem valor informativo.
    """
    linhas = [l for l in texto.splitlines() if not _CABECALHO.match(l)]
    return compactar_espacos("\n".join(linhas))


def extrair_texto_pdf(caminho: Path, limiar_ocr: int = 200) -> tuple[str, bool]:
    """Extrai texto nativo. Só recorre a OCR se a camada de texto for pobre.

    Retorna (texto, usou_ocr). Regra R11 de economia.
    """
    import pypdf

    try:
        leitor = pypdf.PdfReader(str(caminho))
        paginas = [(p.extract_text() or "") for p in leitor.pages]
    except Exception as e:  # PDF corrompido ou cifrado
        log.warning("Falha ao ler %s: %s", caminho.name, e)
        paginas = []

    texto = "\n".join(paginas)
    n_pag = max(len(paginas), 1)
    if len(texto.strip()) >= limiar_ocr * n_pag:
        return remover_cabecalho_rodape(texto), False

    log.info("Camada de texto pobre em %s; acionando OCR", caminho.name)
    texto_ocr = _ocr(caminho)
    return remover_cabecalho_rodape(texto_ocr), True


def _ocr(caminho: Path) -> str:
    try:
        import ocrmypdf  # type: ignore

        saida = caminho.with_suffix(".ocr.pdf")
        ocrmypdf.ocr(
            str(caminho), str(saida), language="por",
            skip_text=True, optimize=1, progress_bar=False,
        )
        import pypdf

        leitor = pypdf.PdfReader(str(saida))
        texto = "\n".join((p.extract_text() or "") for p in leitor.pages)
        saida.unlink(missing_ok=True)
        return texto
    except Exception as e:
        log.error("OCR indisponível ou falhou em %s: %s", caminho.name, e)
        return ""


def carregar_yaml(nome: str) -> dict:
    import yaml

    return yaml.safe_load((CONFIG / nome).read_text(encoding="utf-8"))
