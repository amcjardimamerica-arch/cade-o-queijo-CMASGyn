"""SIOPE: o demonstrativo da educação (RREO Anexo 8) como o FNDE o publica.

O SICONFI não traz o Anexo 8 de Goiânia; ele nasce no SIOPE. A consulta pela página do FNDE
pede reCAPTCHA, mas o próprio FNDE guarda o PDF de cada demonstrativo transmitido num FTP
público, um arquivo por município, bimestre e ano. Este módulo lê esse PDF item a item
(``1-``, ``2.1.1-``, ``15-`` …), com os valores na ordem das colunas, sem interpretar nada:
a interpretação fica em ``onisciente.fiscal``.
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field

FTP = "ftp://ftp.fnde.gov.br/web/siope/RREO/"

ITEM = re.compile(r"^\s*(\d{1,2}(?:\.\d{1,2}){0,3})\s*(?:-\s*|\s+(?=[A-ZÀ-Ú(]))(.*)$")
VALOR = re.compile(r"(?<![\d.,])-?\d{1,3}(?:\.\d{3})*,\d{2}(?![\d,])")


def url_pdf(municipio_ibge6: str, bimestre: int, ano: int) -> str:
    return f"{FTP}RREO_Municipal_{municipio_ibge6}_{bimestre}_{ano}.pdf"


def numero(texto: str) -> float:
    return float(texto.replace(".", "").replace(",", "."))


@dataclass
class Item:
    codigo: str                 # "15", "6.4", "2.1.1"
    rotulo: str                 # o texto do item, com as linhas quebradas juntadas
    valores: list[float]        # na ordem das colunas do quadro
    ordem: int = 0


@dataclass
class Demonstrativo:
    municipio: str = ""
    exercicio: int | None = None
    bimestre: int | None = None
    emitido: str = ""
    itens: list[Item] = field(default_factory=list)

    def item(self, codigo: str) -> Item | None:
        return next((i for i in self.itens if i.codigo == codigo), None)


def texto_do_pdf(conteudo: bytes) -> str:
    """O texto das páginas, com o leiaute preservado (colunas na mesma linha)."""
    from pypdf import PdfReader
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    leitor = PdfReader(io.BytesIO(conteudo))
    return "\n".join(p.extract_text(extraction_mode="layout") for p in leitor.pages)


def ler_texto(texto: str) -> Demonstrativo:
    """Os itens do demonstrativo. Levanta ValueError se não for o Anexo 8 de um município."""
    plano = re.sub(r"[ \t]+", " ", texto)
    if "MANUTEN" not in plano.upper() or "ANEXO 8" not in plano.upper():
        raise ValueError("o PDF não traz o RREO Anexo 8 (MDE)")
    d = Demonstrativo()
    if m := re.search(r"Per[ií]odo de Refer[eê]ncia:\s*(\d)\s*º?\s*Bimestre\s*/\s*(\d{4})", plano, re.I):
        d.bimestre, d.exercicio = int(m.group(1)), int(m.group(2))
    if m := re.search(r"^\s*([^\n]+?)\s+-\s+([A-Z]{2})\s*$", plano, re.M):
        d.municipio = m.group(1).strip()
    atual: Item | None = None
    for linha in plano.splitlines():
        if linha.strip().startswith("FONTE:"):          # dali para baixo, só notas de rodapé
            break
        m = ITEM.match(linha)
        if m and not VALOR.match(linha.strip()):
            atual = Item(m.group(1), "", [], len(d.itens) + 1)
            d.itens.append(atual)
            resto = m.group(2)
        else:
            resto = linha
        if atual is None:
            continue
        rotulo = re.sub(r"\s+", " ", VALOR.sub(" ", resto)).strip()
        if rotulo:                                    # o rótulo quebra em várias linhas
            atual.rotulo = f"{atual.rotulo} {rotulo}".strip()
        atual.valores.extend(numero(v) for v in VALOR.findall(resto))
    if d.exercicio is None or not d.itens:
        raise ValueError("demonstrativo sem período de referência ou sem itens")
    return d


def ler(conteudo: bytes) -> Demonstrativo:
    if not conteudo.startswith(b"%PDF"):
        raise ValueError("o arquivo não é um PDF")
    return ler_texto(texto_do_pdf(conteudo))
