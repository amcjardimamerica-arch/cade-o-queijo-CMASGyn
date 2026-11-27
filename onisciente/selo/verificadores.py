"""Verificadores ao vivo: leem as páginas que a sondagem guardou e dizem item por item.

A sondagem (``python -m onisciente.sondagem e_home e_portal ...``) roda no GitHub, onde a rede é
aberta, e guarda cada resposta em ``relatorios/onisciente/sondagem/<fonte>__<slug>.txt``, com o
cabeçalho (URL, OK, HTTP) e o corpo. Aqui nada vai à rede: cada critério procura os seus termos nas
páginas das fontes que a matriz manda olhar e decide disponibilidade, atualidade, série histórica,
gravação e filtro, pela leitura oficial e pela restritiva (regras/pntp/escolhas.yml, E04 a E09).

Sem página guardada para a fonte, o item fica ``None`` (não verificável), nunca atendido.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from .matriz import Criterio

MESES = {"janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6, "julho": 7,
         "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12}
ARQUIVO = re.compile(r"""(?:href|src)=["'][^"']+\.(pdf|xlsx?|csv|ods|json|xml|txt|zip)(?:\?[^"']*)?["']""")
ABERTOS = {"csv", "ods", "json", "xml", "txt"}
QUALQUER = ABERTOS | {"pdf", "xls", "xlsx", "zip"}
DATA_BR = re.compile(r"\b(\d{1,2})/(\d{1,2})/(20\d{2})\b")
DATA_ISO = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
MES_ANO = re.compile(r"\b(" + "|".join(MESES) + r")\s*(?:de|/)\s*(20\d{2})\b")
ANO = re.compile(r"(?<![\d/.,-])(20\d{2})(?![\d])")
CAMPO = re.compile(r"<select\b|<input\b(?![^>]*type=[\"']?(?:hidden|submit|button|image)\b)")
VALOR_BR = re.compile(r"\d{1,3}(?:\.\d{3})*,\d{2}\b")


def normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return t.lower()


def texto_visivel(html: str) -> str:
    sem = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", html or "")
    sem = re.sub(r"(?s)<[^>]+>", " ", sem)
    return re.sub(r"\s+", " ", sem).strip()


@dataclass
class Pagina:
    fonte: str
    url: str
    ok: bool
    http: int | None
    html: str
    quando: date
    arquivo: str = ""

    @property
    def norm(self) -> str:
        return normalizar(self.html)

    @property
    def visivel(self) -> str:
        return normalizar(texto_visivel(self.html))


def _quando_dos_indices(pasta: Path) -> dict[str, date]:
    quando: dict[str, date] = {}
    for idx in pasta.glob("indice*.json"):
        try:
            d = json.loads(idx.read_text(encoding="utf-8"))
            q = datetime.fromisoformat(d["quando"]).date()
        except (ValueError, KeyError, TypeError):
            continue
        for leitura in d.get("leituras") or []:
            if leitura.get("arquivo"):
                quando[leitura["arquivo"]] = q
    return quando


def ler_sondagem(pasta: Path, prefixo: str = "e_") -> list[Pagina]:
    """As respostas guardadas pela sondagem para as fontes do selo (chaves com o prefixo ``e_``)."""
    if not pasta.exists():
        return []
    quando = _quando_dos_indices(pasta)
    paginas = []
    for arq in sorted(pasta.glob(f"{prefixo}*__*.txt")):
        bruto = arq.read_text(encoding="utf-8", errors="replace")
        cab, _, corpo = bruto.partition("\n\n")
        campos = dict(linha.split(": ", 1) for linha in cab.splitlines() if ": " in linha)
        http = campos.get("HTTP", "")
        q = quando.get(arq.name) or datetime.fromtimestamp(arq.stat().st_mtime).date()
        paginas.append(Pagina(fonte=arq.name.split("__", 1)[0], url=campos.get("URL", ""),
                              ok=campos.get("OK") == "True", http=int(http) if http.isdigit() else None,
                              html=corpo, quando=q, arquivo=arq.name))
    return paginas


def localiza(c: Criterio, pagina: Pagina) -> bool:
    texto = pagina.norm
    return bool(c.termos) and all(any(t in texto for t in grupo) for grupo in c.termos)


def casca_javascript(p: Pagina) -> bool:
    """Página que só mostra o conteúdo depois de rodar scripts: quase nenhum texto visível."""
    return "<script" in p.norm and len(p.visivel) < 400


def tem_dado(p: Pagina) -> bool:
    """E08: a página traz o dado (tabela, arquivo ou valores), não só o nome dele num menu."""
    n = p.norm
    return n.count("<tr") >= 5 or bool(ARQUIVO.search(n)) or len(VALOR_BR.findall(p.visivel)) >= 5


def datas(p: Pagina) -> list[date]:
    achadas = []
    texto = p.visivel
    for d, m, a in DATA_BR.findall(texto):
        try:
            achadas.append(date(int(a), int(m), int(d)))
        except ValueError:
            pass
    for a, m, d in DATA_ISO.findall(texto):
        try:
            achadas.append(date(int(a), int(m), int(d)))
        except ValueError:
            pass
    for mes, a in MES_ANO.findall(texto):
        achadas.append(date(int(a), MESES[mes], 1))
    return [x for x in achadas if x <= p.quando]


def atualidade(c: Criterio, paginas: list[Pagina], leitura: str) -> bool:
    """E05: o dado mais novo da página dentro do prazo do critério."""
    limite = c.atualidade_dias or 30
    if leitura == "restritiva" and int(c.dimensao) in (3, 4):
        limite = 7
    for p in paginas:
        ds = datas(p)
        if ds and (p.quando - max(ds)).days <= limite:
            return True
    return False


def serie(paginas: list[Pagina], leitura: str, anos: int = 3) -> bool:
    """E06: os três anos anteriores na página; na restritiva também o ano corrente."""
    for p in paginas:
        presentes = {int(a) for a in ANO.findall(p.visivel)}
        y = p.quando.year
        exigidos = {y - k for k in range(1, anos + 1)} | ({y} if leitura == "restritiva" else set())
        if exigidos <= presentes:
            return True
    return False


def gravacao(paginas: list[Pagina], leitura: str) -> bool:
    """E04: arquivo para baixar; na restritiva só formato aberto."""
    aceitos = ABERTOS if leitura == "restritiva" else QUALQUER
    for p in paginas:
        if any(ext in aceitos for ext in ARQUIVO.findall(p.norm)):
            return True
        if leitura == "oficial" and re.search(r"exportar|baixar (em )?(csv|planilha|excel)", p.visivel):
            return True
    return False


def filtro(paginas: list[Pagina], leitura: str) -> bool:
    """E07: campos de filtro na consulta (um na oficial, dois na restritiva)."""
    minimo = 2 if leitura == "restritiva" else 1
    return any(len(CAMPO.findall(p.norm)) >= minimo for p in paginas)


def verificar(c: Criterio, paginas: list[Pagina], leitura: str) -> tuple[dict[str, bool | None], list[str]]:
    """Itens do critério pelas páginas guardadas, e as notas que explicam cada decisão."""
    itens: dict[str, bool | None] = {i: None for i in c.itens}
    notas: list[str] = []
    if not c.automatico:
        return itens, ["critério sem verificação automática possível; vira pergunta no ofício"]
    das_fontes = [p for p in paginas if p.fonte in c.onde]
    if not das_fontes:
        return itens, [f"fontes {', '.join(c.onde)} ainda não sondadas"]
    lidas = [p for p in das_fontes if p.ok]
    if not lidas:
        return itens, ["as páginas das fontes não responderam na sondagem (leitura falhou)"]
    achadas = [p for p in lidas if localiza(c, p)]
    cascas = [p for p in lidas if casca_javascript(p)]
    if not achadas:
        if cascas:
            notas.append(f"{len(cascas)} página(s) só mostram o conteúdo com JavaScript")
            if leitura == "restritiva" and "gravacao" in itens:
                itens["gravacao"] = False
            if leitura == "restritiva" and c.id == "15.4":
                itens = {i: False for i in itens}
            return itens, notas
        notas.append(f"termos do critério não localizados em {len(lidas)} página(s) lida(s)")
        return {i: False for i in itens}, notas
    notas.append("localizado em " + ", ".join(p.url for p in achadas[:3]))
    com_dado = [p for p in achadas if tem_dado(p)]
    exige_dado = any(i in itens for i in ("atualidade", "serie_historica", "gravacao", "filtro"))
    if leitura == "restritiva" and exige_dado and not com_dado:
        notas.append("a página traz o nome do dado, mas não o dado (link presente e vazio)")
        return {i: False for i in itens}, notas
    base = com_dado if (leitura == "restritiva" and exige_dado) else achadas
    itens["disponibilidade"] = True
    if "atualidade" in itens:
        itens["atualidade"] = atualidade(c, base, leitura)
    if "serie_historica" in itens:
        itens["serie_historica"] = serie(base, leitura)
    if "gravacao" in itens:
        itens["gravacao"] = gravacao(base, leitura)
    if "filtro" in itens:
        itens["filtro"] = filtro(base, leitura)
    return itens, notas
