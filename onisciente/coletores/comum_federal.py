"""Leitura tolerante das fontes federais e estaduais ainda sem formato confirmado.

As fontes do bloco 5 (FNS, FNDE, Transferegov, Economia GO, TCU e TCM-GO) entregam JSON, CSV ou
tabela HTML, e os nomes dos campos variam de uma versão da API para outra. Estes auxiliares acham
os registros e os campos pelo sentido do nome (sem acento, sem caixa, sem separador), nunca pela
posição, e falham às claras quando nada reconhecível aparece: quem chama decide se é formato
mudado (falha do sistema) ou fonte vazia.
"""

from __future__ import annotations

import csv
import html
import io
import json
import re
import unicodedata
from datetime import date

CHAVES_DE_LISTA = ("content", "conteudo", "dados", "data", "resultado", "resultados", "results", "items",
                   "itens", "registros", "value", "documentos", "lista", "rows", "linhas", "repasses",
                   "pagamentos", "acordaos", "decisoes")


def norm(texto) -> str:
    """Sem acento, maiúsculas, espaços simples."""
    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t.upper()).strip()


def chave(nome) -> str:
    """O nome de um campo reduzido a letras e números minúsculos (``valor_liquido`` = ``valorLiquido``)."""
    return re.sub(r"[^a-z0-9]", "", norm(nome).lower())


def digitos(texto) -> str:
    return re.sub(r"\D", "", str(texto or ""))


def numero(valor) -> float | None:
    """``1.234,56``, ``1234.56``, ``R$ 1.234,56`` ou número: o valor em float; vazio é None."""
    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    t = str(valor).strip().replace("R$", "").replace("\xa0", "").replace(" ", "")
    if not t or t in ("-", "--"):
        return None
    negativo = t.startswith("(") and t.endswith(")")
    t = t.strip("()")
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    elif t.count(".") > 1:
        t = t.replace(".", "")
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if negativo else v


_DATAS = (
    (re.compile(r"^(\d{4})-(\d{2})-(\d{2})"), (1, 2, 3)),
    (re.compile(r"^(\d{2})/(\d{2})/(\d{4})"), (3, 2, 1)),
    (re.compile(r"^(\d{4})(\d{2})(\d{2})$"), (1, 2, 3)),
    (re.compile(r"^(\d{2})-(\d{2})-(\d{4})"), (3, 2, 1)),
)


def data(valor) -> str | None:
    """A data em ISO (AAAA-MM-DD) a partir das formas usuais; milissegundos de época também."""
    if valor is None or valor == "":
        return None
    if isinstance(valor, (int, float)) and valor > 10**11:          # epoch em milissegundos
        from datetime import datetime, timezone
        return datetime.fromtimestamp(valor / 1000, tz=timezone.utc).date().isoformat()
    t = str(valor).strip()
    for rx, (a, m, d) in _DATAS:
        if g := rx.match(t):
            try:
                return date(int(g.group(a)), int(g.group(m)), int(g.group(d))).isoformat()
            except ValueError:
                return None
    return None


def mes_de(valor) -> str | None:
    """AAAA-MM de uma data ou de uma competência (``01/2025``, ``2025-01``, ``202501``)."""
    if d := data(valor):
        return d[:7]
    t = str(valor or "").strip()
    if m := re.match(r"^(\d{1,2})/(\d{4})$", t):
        return f"{m.group(2)}-{int(m.group(1)):02d}"
    if m := re.match(r"^(\d{4})-?(\d{2})$", t):
        if 1 <= int(m.group(2)) <= 12:
            return f"{m.group(1)}-{m.group(2)}"
    return None


def campo(registro: dict, *nomes: str, contem: tuple[str, ...] = ()):
    """O valor do primeiro campo cujo nome reduzido é um dos ``nomes``; depois, o primeiro cujo
    nome reduzido contém um dos trechos de ``contem``. None se nenhum casar."""
    reduzidos = {chave(k): v for k, v in registro.items()}
    for n in nomes:
        v = reduzidos.get(chave(n))
        if v not in (None, ""):
            return v
    for trecho in contem:
        t = chave(trecho)
        for k, v in reduzidos.items():
            if t in k and v not in (None, ""):
                return v
    return None


def registros_json(obj, _profundidade: int = 0) -> list[dict] | None:
    """A lista de registros de uma resposta JSON: a própria lista, ou a primeira lista de objetos
    sob uma chave usual (``content``, ``dados``, ``value``...). None se não houver lista."""
    if _profundidade > 4:
        return None
    if isinstance(obj, list):
        if all(isinstance(x, dict) for x in obj):
            return obj
        return None
    if isinstance(obj, dict):
        for k in CHAVES_DE_LISTA:
            for chave_real, v in obj.items():
                if chave(chave_real) == k:
                    achado = registros_json(v, _profundidade + 1)
                    if achado is not None:
                        return achado
        for v in obj.values():
            if isinstance(v, (list, dict)):
                achado = registros_json(v, _profundidade + 1)
                if achado:
                    return achado
    return None


def json_ou_none(conteudo: bytes):
    try:
        return json.loads(conteudo.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        return None


def decodificar(conteudo: bytes) -> str:
    try:
        return conteudo.decode("utf-8-sig")
    except UnicodeDecodeError:
        return conteudo.decode("latin-1")


def linhas_csv(conteudo: bytes | str) -> list[dict]:
    """As linhas de um CSV (``;`` ou ``,``), com o cabeçalho como chave. Vazio se não for CSV."""
    texto = conteudo if isinstance(conteudo, str) else decodificar(conteudo)
    primeira = texto.lstrip().split("\n", 1)[0]
    if not primeira or primeira.lstrip().startswith(("<", "{", "[")):
        return []
    separador = ";" if primeira.count(";") >= primeira.count(",") else ","
    if primeira.count(separador) == 0:
        return []
    leitor = csv.DictReader(io.StringIO(texto.lstrip()), delimiter=separador)
    return [dict(l) for l in leitor if any((v or "").strip() for v in l.values() if isinstance(v, str))]


def _celula(bruta: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"(?is)<[^>]+>", " ", bruta))).strip()


def tabelas_html(texto: str) -> list[list[list[str]]]:
    """Cada tabela da página como lista de linhas, cada linha como lista de células em texto."""
    saida = []
    for tabela in re.findall(r"(?is)<table[^>]*>(.*?)</table>", texto):
        linhas = []
        for tr in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", tabela):
            celulas = [_celula(c) for c in re.findall(r"(?is)<t[dh][^>]*>(.*?)</t[dh]>", tr)]
            if any(celulas):
                linhas.append(celulas)
        if linhas:
            saida.append(linhas)
    return saida


def tabela_como_registros(linhas: list[list[str]]) -> list[dict]:
    """Uma tabela HTML com cabeçalho na primeira linha que tem só texto: as linhas seguintes como dicts."""
    for i, linha in enumerate(linhas):
        if linha and all(c and numero(c) is None for c in linha) and len(linha) >= 2:
            cabeca = linha
            return [dict(zip(cabeca, l)) for l in linhas[i + 1:] if len(l) == len(cabeca)]
    return []


def links(texto: str, base: str = "") -> list[tuple[str, str]]:
    """(endereço, texto do link) de cada âncora; endereços relativos completados pela ``base``."""
    saida = []
    for href, rotulo in re.findall(r"""(?is)<a[^>]+href=["']([^"'#]+)["'][^>]*>(.*?)</a>""", texto):
        href = html.unescape(href.strip())
        if base and not re.match(r"^[a-z]+://", href):
            raiz = re.match(r"^[a-z]+://[^/]+", base)
            if href.startswith("/") and raiz:
                href = raiz.group(0) + href
            else:
                href = base.rsplit("/", 1)[0] + "/" + href
        saida.append((href, _celula(rotulo)))
    return saida


def parece_pagina(conteudo: bytes) -> bool:
    """Página HTML (de erro, de login, de bloqueio) no lugar de um dado."""
    return conteudo[:200].lstrip().lower().startswith((b"<!doctype", b"<html", b"<?xml", b"<head"))
