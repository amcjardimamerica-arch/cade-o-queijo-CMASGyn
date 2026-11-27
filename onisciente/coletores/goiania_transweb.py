"""A execução da despesa de Goiânia, item a item: empenhos, liquidações, ordens de pagamento e pagamentos.

Duas portas, as duas lidas pelo que a página mostra, sem adivinhar o que ela não mostra:

* o **TransWeb** (www10.goiania.go.gov.br/transweb/), sistema ASP.NET com as consultas do manual
  ("Empenho por Órgão", "Empenho por Credor", "Ordem de Pagamento por Órgão"). Cada consulta é um
  formulário com estado escondido (``__VIEWSTATE``, ``__EVENTVALIDATION``): o coletor lê a página,
  devolve o estado como veio, preenche data e órgão, aperta o botão (ou dispara o ``__doPostBack``
  do botão), lê a tabela de resultado, segue a paginação do GridView e, quando a consulta tem
  detalhe, escolhe cada empenho para ler as liquidações e os pagamentos dele;
* o **portal novo** (www.goiania.go.gov.br/transparencia/, WordPress): a lista de arquivos de cada
  categoria; quando há planilha (CSV), ela é lida com as mesmas colunas.

Caminhos, nomes de campos e títulos de colunas ficam em ``alvos/portais/goiania.toml``: o portal
muda de rosto sem mudar este código. O que não se acha (página, campo, tabela) não vira zero:
vira falha descrita, que o motor registra e o parecer mostra em vermelho. A ausência de dado
publicado num dia lido é outra coisa, e fica registrada como tal (lacuna do Município).
"""

from __future__ import annotations

import csv
import io
import re
import tomllib
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import urljoin

from .. import RAIZ
from .base import Leitura

TIPOS = ("empenho", "liquidacao", "ordem_pagamento", "pagamento", "anulacao")

# --- Texto, números e datas no formato brasileiro ------------------------------------------------


def norm(texto) -> str:
    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t).strip().upper()


def valor_br(texto) -> float | None:
    """``1.234,56`` (ou ``R$ 1.234,56``, ``(1.234,56)`` negativo) vira 1234.56; vazio vira None."""
    t = str(texto or "").strip().replace("R$", "").replace("\xa0", "").replace(" ", "")
    if not t:
        return None
    negativo = t.startswith("(") and t.endswith(")") or t.startswith("-") or t.endswith("-")
    t = t.strip("()-")
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    elif t.count(".") > 1:
        t = t.replace(".", "")
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if negativo else v


def data_br(texto) -> date | None:
    t = str(texto or "").strip()
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", t)
    if m:
        d, mth, a = (int(x) for x in m.groups())
        try:
            return date(a, mth, d)
        except ValueError:
            return None
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        try:
            return date(*(int(x) for x in m.groups()))
        except ValueError:
            return None
    return None


def documento(texto) -> str:
    """Só os dígitos do CPF ou CNPJ (o portal pode mascarar o CPF: os asteriscos saem)."""
    return re.sub(r"\D", "", str(texto or ""))


# --- O HTML: formulários ASP.NET, tabelas e links ------------------------------------------------

_POSTBACK = re.compile(r"__doPostBack\(\s*['\"]([^'\"]*)['\"]\s*,\s*['\"]([^'\"]*)['\"]\s*\)")
_WEBFORM = re.compile(r"WebForm_PostBackOptions\(\s*['\"]([^'\"]*)['\"]\s*,\s*['\"]([^'\"]*)['\"]")


@dataclass
class Celula:
    texto: str
    postbacks: list[tuple[str, str]] = field(default_factory=list)
    links: list[str] = field(default_factory=list)


@dataclass
class Tabela:
    id: str
    cabecalho: list[str]
    linhas: list[list[Celula]]

    def coluna(self, candidatos: Iterable[str]) -> int | None:
        """O índice da primeira coluna cujo título casa com um candidato (igual, depois contém)."""
        titulos = [norm(c) for c in self.cabecalho]
        cands = [norm(c) for c in candidatos]
        for c in cands:
            if c in titulos:
                return titulos.index(c)
        for c in cands:
            for i, t in enumerate(titulos):
                if c and c in t:
                    return i
        return None


@dataclass
class Formulario:
    acao: str
    metodo: str
    campos: dict[str, str] = field(default_factory=dict)          # o que o navegador enviaria
    tipos: dict[str, str] = field(default_factory=dict)           # nome -> hidden, text, select...
    opcoes: dict[str, list[tuple[str, str]]] = field(default_factory=dict)   # select -> (valor, texto)
    botoes: list[tuple[str, str]] = field(default_factory=list)   # submit: (name, value)
    postbacks: list[tuple[str, str]] = field(default_factory=list)  # __doPostBack achados na página

    @property
    def aspnet(self) -> bool:
        return "__VIEWSTATE" in self.campos

    def estado(self) -> dict[str, str]:
        """Os campos escondidos que o ASP.NET exige de volta, como vieram."""
        return {k: v for k, v in self.campos.items() if self.tipos.get(k) == "hidden"}

    def achar(self, candidatos: Iterable[str]) -> str | None:
        """O nome real do campo: igual ao candidato, depois terminando nele, depois contendo-o.

        O ASP.NET prefixa os nomes (``ctl00$Conteudo$txtData``): o fim do nome é o que o
        programador escreveu, e é por ele que a configuração casa."""
        nomes = [n for n in self.tipos if self.tipos[n] not in ("hidden", "submit")] + \
                [n for n, _ in self.botoes]
        baixos = {n: n.lower() for n in nomes}
        cands = [c.lower() for c in candidatos if c]
        for c in cands:
            for n, b in baixos.items():
                if b == c:
                    return n
        for c in cands:
            for n, b in baixos.items():
                if re.split(r"[$:_.]", b)[-1] == c or b.endswith("$" + c) or b.endswith(":" + c):
                    return n
        for c in cands:
            for n, b in baixos.items():
                if c in b:
                    return n
        return None

    def botao(self, candidatos: Iterable[str]) -> tuple[str, str] | None:
        """O botão de enviar, pelo nome ou pelo texto (o ``value`` que aparece na tela)."""
        cands = [norm(c) for c in candidatos]
        for c in cands:
            for nome, valor in self.botoes:
                if norm(nome).endswith(c) or norm(valor) == c:
                    return nome, valor
        for c in cands:
            for nome, valor in self.botoes:
                if c in norm(nome) or c in norm(valor):
                    return nome, valor
        return None

    def postback_de(self, candidatos: Iterable[str]) -> tuple[str, str] | None:
        """Um ``__doPostBack`` da página (botão feito com link) cujo alvo casa com o candidato."""
        cands = [c.lower() for c in candidatos if c]
        for c in cands:
            for alvo, arg in self.postbacks:
                if alvo.lower().endswith(c) or c in alvo.lower():
                    return alvo, arg
        return None

    def envio(self, valores: dict[str, str], *, botao: tuple[str, str] | None = None,
              postback: tuple[str, str] | None = None) -> dict[str, str]:
        """O corpo do POST: o estado da página, os campos preenchidos e o botão ou o postback."""
        corpo = dict(self.campos)
        for n, _ in self.botoes:          # só o botão apertado vai no corpo, como no navegador
            corpo.pop(n, None)
        corpo.update(valores)
        if postback:
            corpo["__EVENTTARGET"], corpo["__EVENTARGUMENT"] = postback
        else:
            corpo.setdefault("__EVENTTARGET", "")
            corpo.setdefault("__EVENTARGUMENT", "")
            if botao:
                corpo[botao[0]] = botao[1]
        return corpo


class _Leitor(HTMLParser):
    """Lê formulários, tabelas e links numa passada, sem depender de HTML bem formado."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.formularios: list[Formulario] = []
        self.tabelas: list[Tabela] = []
        self.links: list[tuple[str, str]] = []
        self._form: Formulario | None = None
        self._select: str | None = None
        self._opcao: list | None = None
        self._textarea: str | None = None
        self._pilha: list[dict] = []        # tabelas abertas (aninhadas)
        self._celula: dict | None = None
        self._link: list | None = None

    # formulário -----------------------------------------------------------------------------
    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v if v is not None else "") for k, v in attrs}
        for valor in a.values():
            for alvo, arg in _POSTBACK.findall(valor) + _WEBFORM.findall(valor):
                if self._form is not None and (alvo, arg) not in self._form.postbacks:
                    self._form.postbacks.append((alvo, arg))
                if self._celula is not None:
                    self._celula["postbacks"].append((alvo, arg))
        if tag == "form":
            self._form = Formulario(a.get("action", ""), a.get("method", "get").lower())
            self.formularios.append(self._form)
        elif tag == "input" and self._form is not None:
            nome = a.get("name")
            tipo = a.get("type", "text").lower()
            if not nome:
                return
            if tipo in ("submit", "image", "button"):
                if tipo != "button":
                    self._form.botoes.append((nome, a.get("value", "")))
                return
            if tipo in ("checkbox", "radio") and "checked" not in a:
                self._form.tipos.setdefault(nome, tipo)
                return
            self._form.campos[nome] = a.get("value", "")
            self._form.tipos[nome] = tipo
        elif tag == "select" and self._form is not None:
            self._select = a.get("name")
            if self._select:
                self._form.tipos[self._select] = "select"
                self._form.opcoes[self._select] = []
        elif tag == "option" and self._select and self._form is not None:
            self._opcao = [a.get("value"), "", "selected" in a]
        elif tag == "textarea" and self._form is not None:
            self._textarea = a.get("name")
            if self._textarea:
                self._form.tipos[self._textarea] = "textarea"
                self._form.campos[self._textarea] = ""
        elif tag == "table":
            self._pilha.append({"id": a.get("id", ""), "linhas": [], "linha": None, "cab": []})
        elif tag == "tr" and self._pilha:
            self._pilha[-1]["linha"] = []
        elif tag in ("td", "th") and self._pilha and self._pilha[-1]["linha"] is not None:
            self._celula = {"texto": [], "postbacks": [], "links": [], "th": tag == "th"}
        elif tag == "br" and self._celula is not None:
            self._celula["texto"].append(" ")
        if tag == "a":
            self._link = [a.get("href", ""), []]
            if self._celula is not None and a.get("href") and not a["href"].lower().startswith("javascript"):
                self._celula["links"].append(a["href"])

    def handle_endtag(self, tag):
        if tag == "form":
            self._form = None
        elif tag == "select":
            self._select = None
        elif tag == "option" and self._opcao is not None and self._form is not None and self._select:
            valor, texto, marcada = self._opcao
            texto = texto.strip()
            valor = texto if valor is None else valor
            self._form.opcoes[self._select].append((valor, texto))
            if marcada or self._select not in self._form.campos:
                self._form.campos[self._select] = valor
            self._opcao = None
        elif tag == "textarea":
            self._textarea = None
        elif tag in ("td", "th") and self._celula is not None and self._pilha:
            c = self._celula
            texto = re.sub(r"\s+", " ", "".join(c["texto"])).strip()
            linha = self._pilha[-1]["linha"]
            if linha is not None:
                linha.append((Celula(texto, c["postbacks"], c["links"]), c["th"]))
            self._celula = None
        elif tag == "tr" and self._pilha:
            t = self._pilha[-1]
            linha = t["linha"]
            t["linha"] = None
            if not linha:
                return
            if not t["cab"] and (all(th for _, th in linha) or not t["linhas"] and _parece_cabecalho(linha)):
                t["cab"] = [c.texto for c, _ in linha]
            else:
                t["linhas"].append([c for c, _ in linha])
        elif tag == "table" and self._pilha:
            t = self._pilha.pop()
            self.tabelas.append(Tabela(t["id"], t["cab"], t["linhas"]))
        elif tag == "a" and self._link is not None:
            href, texto = self._link
            self.links.append((href, re.sub(r"\s+", " ", "".join(texto)).strip()))
            self._link = None

    def handle_data(self, data):
        if self._opcao is not None:
            self._opcao[1] += data
        if self._textarea and self._form is not None:
            self._form.campos[self._textarea] += data
        if self._celula is not None:
            self._celula["texto"].append(data)
        if self._link is not None:
            self._link[1].append(data)


def _parece_cabecalho(linha) -> bool:
    """Primeira linha sem número nem data: é o cabeçalho (GridView sem <th>)."""
    textos = [c.texto for c, _ in linha]
    return bool(textos) and all(t and valor_br(t) is None and data_br(t) is None for t in textos)


def ler_html(html: str | bytes) -> _Leitor:
    if isinstance(html, bytes):
        html = _decodificar(html)
    leitor = _Leitor()
    leitor.feed(html)
    leitor.close()
    while leitor._pilha:                      # tabela não fechada no fim da página
        leitor.handle_endtag("table")
    return leitor


def _decodificar(conteudo: bytes) -> str:
    m = re.search(rb"charset=[\"']?([\w-]+)", conteudo[:2048], re.I)
    cod = m.group(1).decode() if m else "utf-8"
    try:
        return conteudo.decode(cod)
    except (LookupError, UnicodeDecodeError):
        return conteudo.decode("latin-1")


def formularios(html) -> list[Formulario]:
    return ler_html(html).formularios


def tabelas(html) -> list[Tabela]:
    return ler_html(html).tabelas


def paginas_do_grid(tabela: Tabela | None, formulario: Formulario | None = None) -> list[tuple[str, str]]:
    """Os ``__doPostBack(grid, 'Page$N')`` do pager, na ordem das páginas."""
    achados: list[tuple[str, str]] = []
    fontes = [c.postbacks for linha in (tabela.linhas if tabela else []) for c in linha]
    if formulario is not None:
        fontes.append(formulario.postbacks)
    for lista in fontes:
        for alvo, arg in lista:
            if arg.startswith("Page$") and (alvo, arg) not in achados:
                achados.append((alvo, arg))
    return achados


# --- A configuração do portal ---------------------------------------------------------------------

@dataclass(frozen=True)
class Consulta:
    id: str
    tipo: str
    titulo: str
    paginas: tuple[str, ...]
    granularidade: str                  # dia, mes ou intervalo
    percorre_orgaos: bool
    botao: tuple[str, ...]
    detalhe: bool
    campos: dict[str, tuple[str, ...]]
    colunas: dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class Portal:
    base: str
    entradas: tuple[str, ...]
    confirmado: bool
    formato_data: str
    paginas_maximas: int
    consultas: tuple[Consulta, ...]
    detalhe: dict[str, tuple[str, ...]]
    wordpress: dict
    dotacao: str = ""
    arquivo: str = ""

    def consulta(self, cid: str) -> Consulta:
        for c in self.consultas:
            if c.id == cid:
                return c
        raise KeyError(f"consulta {cid!r} não está em {self.arquivo}")


# Dotação compactada: função.subfunção.programa.ação e a natureza (c.g.mm.ee); a fonte, quatro dígitos.
DOTACAO_PADRAO = (r"(?P<funcao>\d{2})\.(?P<subfuncao>\d{3})\.(?P<programa>\d{4})\.(?P<acao>\d{4})"
                  r".*?(?P<natureza>\d\.\d\.\d{2}\.\d{2}(?:\.\d{2})?)(?:.*?(?P<fonte>\b\d{3,4}\b))?")


def carregar_portal(caminho: Path | str) -> Portal:
    caminho = Path(caminho)
    if not caminho.is_absolute():
        caminho = RAIZ / caminho
    bruto = tomllib.loads(caminho.read_text(encoding="utf-8"))
    tw = bruto.get("transweb", {})
    consultas = []
    for c in tw.get("consultas", []):
        consultas.append(Consulta(
            id=c["id"], tipo=c["tipo"], titulo=c.get("titulo", c["id"]),
            paginas=tuple(c.get("paginas", ())), granularidade=c.get("granularidade", "dia"),
            percorre_orgaos=bool(c.get("percorre_orgaos", False)), botao=tuple(c.get("botao", ("Consultar",))),
            detalhe=bool(c.get("detalhe", False)),
            campos={k: tuple(v) for k, v in (c.get("campos") or {}).items()},
            colunas={k: tuple(v) for k, v in (c.get("colunas") or {}).items()}))
    return Portal(
        base=tw.get("base", ""), entradas=tuple(tw.get("entradas", ())), confirmado=bool(tw.get("confirmado")),
        formato_data=tw.get("formato_data", "%d/%m/%Y"), paginas_maximas=int(tw.get("paginas_maximas", 200)),
        consultas=tuple(consultas), detalhe={k: tuple(v) for k, v in (tw.get("detalhe") or {}).items()},
        wordpress=dict(bruto.get("wordpress") or {}), dotacao=str(tw.get("dotacao", "") or DOTACAO_PADRAO),
        arquivo=str(caminho))


# --- Da tabela ao evento --------------------------------------------------------------------------

CAMPOS_EVENTO = ("tipo", "empenho", "ordem", "data", "orgao", "credor", "documento", "valor", "elemento",
                 "fonte", "funcao", "subfuncao", "dotacao", "historico", "consulta", "url", "sha256",
                 "coletado_em")


def mapear(tabela: Tabela, colunas: dict[str, tuple[str, ...]]) -> dict[str, int]:
    out = {}
    usados: set[int] = set()
    # "documento" e "data" antes dos genéricos, para "CPF/CNPJ" não cair em "credor".
    for campo in sorted(colunas, key=lambda c: (c not in ("documento", "data", "empenho", "ordem"), c)):
        i = tabela.coluna(colunas[campo])
        if i is not None and i not in usados:
            out[campo] = i
            usados.add(i)
    return out


def tabela_de_resultado(tabs: list[Tabela], colunas: dict[str, tuple[str, ...]]) -> tuple[Tabela, dict] | None:
    """A tabela que traz valor e (empenho, ordem ou credor) mapeados: a de mais linhas, se houver mais de uma."""
    melhores = []
    for t in tabs:
        m = mapear(t, colunas)
        if "valor" in m and ({"empenho", "ordem", "credor"} & set(m)):
            melhores.append((len(t.linhas), len(m), t, m))
    if not melhores:
        return None
    melhores.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return melhores[0][2], melhores[0][3]


def classificar_dotacao(texto: str, padrao: str = DOTACAO_PADRAO) -> dict[str, str]:
    m = re.search(padrao, str(texto or ""))
    if not m:
        return {}
    out = {k: v for k, v in m.groupdict().items() if v}
    if "natureza" in out:
        out["natureza"] = re.sub(r"\D", "", out["natureza"])
    return out


def eventos_da_tabela(tabela: Tabela, mapa: dict[str, int], tipo: str, *, consulta: str = "",
                      url: str = "", padrao_dotacao: str = DOTACAO_PADRAO,
                      fixos: dict | None = None) -> list[dict]:
    """Cada linha da tabela vira um evento; linha de total, de pager ou sem valor fica fora."""
    eventos = []
    for linha in tabela.linhas:
        def cel(campo: str) -> str:
            i = mapa.get(campo)
            return linha[i].texto if i is not None and i < len(linha) else ""
        valor = valor_br(cel("valor"))
        if valor is None:
            continue
        if any(norm(c.texto).startswith(("TOTAL", "SUBTOTAL")) for c in linha) or any(a.startswith("Page$") for c in linha for _, a in c.postbacks):
            continue
        dia = data_br(cel("data"))
        ev = {"tipo": tipo, "empenho": cel("empenho").strip(), "ordem": cel("ordem").strip(),
              "data": dia.isoformat() if dia else "", "orgao": cel("orgao").strip(),
              "credor": cel("credor").strip(), "documento": documento(cel("documento")), "valor": round(valor, 2),
              "elemento": re.sub(r"\D", "", cel("elemento")), "fonte": re.sub(r"\D", "", cel("fonte")),
              "funcao": "", "subfuncao": "", "dotacao": cel("dotacao").strip(), "historico": cel("historico").strip(),
              "consulta": consulta, "url": url}
        if ev["dotacao"]:
            d = classificar_dotacao(ev["dotacao"], padrao_dotacao)
            ev["funcao"] = d.get("funcao", "")
            ev["subfuncao"] = d.get("subfuncao", "")
            ev["elemento"] = ev["elemento"] or d.get("natureza", "")
            ev["fonte"] = ev["fonte"] or d.get("fonte", "")
        for k, v in (fixos or {}).items():
            if v and not ev.get(k):
                ev[k] = v
        ev["_selecao"] = next(((a, g) for c in linha for a, g in c.postbacks if g.startswith("Select$")), None) \
            or next((h for c in linha for h in c.links if ".aspx" in h.lower()), None)
        eventos.append(ev)
    return eventos


def eventos_do_detalhe(html, detalhe: dict[str, tuple[str, ...]], colunas: dict[str, tuple[str, ...]],
                       base: dict, *, url: str = "", padrao_dotacao: str = DOTACAO_PADRAO) -> list[dict]:
    """O detalhe de um empenho: cada tabela é de liquidações, ordens, pagamentos ou anulações,
    conforme o cabeçalho (ou o título logo antes dela); o empenho, o credor e o órgão vêm da lista."""
    out = []
    generico = {"data": colunas.get("data", ("Data",)) + ("Data",), "valor": colunas.get("valor", ("Valor",)) + ("Valor",),
                "ordem": ("Ordem", "Nº OP", "OP", "Ordem de Pagamento"), "historico": colunas.get("historico", ())}
    for t in tabelas(html):
        cab = " ".join(norm(c) for c in t.cabecalho)
        # O tipo da tabela é o de mais sinais no cabeçalho (cada sinal casa como palavra inteira).
        pontos = {nome: sum(1 for s in sinais if re.search(r"(?<![A-Z])" + re.escape(norm(s)) + r"(?![A-Z])", cab))
                  for nome, sinais in detalhe.items()}
        tipo = max(pontos, key=lambda k: pontos[k]) if pontos and max(pontos.values()) > 0 else None
        if tipo is None:
            continue
        m = mapear(t, generico)
        if "valor" not in m:
            continue
        fixos = {k: base.get(k, "") for k in ("empenho", "orgao", "credor", "documento", "elemento", "fonte",
                                              "funcao", "subfuncao", "dotacao")}
        for ev in eventos_da_tabela(t, m, tipo, consulta=base.get("consulta", ""), url=url,
                                    padrao_dotacao=padrao_dotacao, fixos=fixos):
            ev.pop("_selecao", None)
            out.append(ev)
    return out


# --- A navegação: página, formulário, envio, paginação e detalhe ----------------------------------

Ler = Callable[..., Leitura]   # ler(url, formulario=None) -> Leitura


@dataclass
class Resultado:
    ok: bool
    consulta: str
    url: str = ""
    eventos: list[dict] = field(default_factory=list)
    paginas: int = 0
    erro: str = ""
    vazio: bool = False                # a consulta respondeu, sem nenhuma linha: nada publicado
    orgaos: list[tuple[str, str]] = field(default_factory=list)
    originais: list = field(default_factory=list)


def abrir_consulta(ler: Ler, portal: Portal, c: Consulta) -> tuple[str, Formulario, Leitura] | str:
    """A primeira página candidata que responde com um formulário que tem os campos da consulta."""
    obrigatorios = [k for k in c.campos if k not in ("orgao", "documento")]
    erros = []
    for pagina in c.paginas:
        url = urljoin(portal.base, pagina)
        leitura = ler(url)
        if not leitura.ok:
            erros.append(f"{pagina}: {leitura.erro or leitura.http}")
            continue
        for f in formularios(leitura.conteudo):
            if all(f.achar(c.campos[k]) for k in obrigatorios):
                return urljoin(url, f.acao or url), f, leitura
        erros.append(f"{pagina}: formulário sem os campos {', '.join(obrigatorios)}")
    return "; ".join(erros) or "nenhuma página candidata"


def opcoes_de_orgao(f: Formulario, c: Consulta) -> list[tuple[str, str]]:
    """As opções do campo órgão; se houver "Todos", só ela (uma consulta no lugar de dezenas)."""
    nome = f.achar(c.campos.get("orgao", ()))
    if not nome:
        return []
    ops = [(v, t) for v, t in f.opcoes.get(nome, []) if v not in ("", "0", "-1")
           and not norm(t).startswith(("SELECIONE", "ESCOLHA", "--"))]
    todos = [(v, t) for v, t in ops if norm(t) in ("TODOS", "TODOS OS ORGAOS", "TODAS")]
    return todos[:1] or ops


def consultar(ler: Ler, portal: Portal, c: Consulta, valores: dict[str, str], *,
              aberta: tuple[str, Formulario, Leitura] | None = None) -> Resultado:
    """Uma consulta preenchida: ``valores`` por campo lógico (data, orgao, data_inicial...)."""
    if aberta is None:
        aberta = abrir_consulta(ler, portal, c)
    if isinstance(aberta, str):
        return Resultado(False, c.id, erro=aberta)
    acao, form, primeira = aberta
    preenchidos = {}
    for campo, valor in valores.items():
        if campo.endswith("_nome"):
            continue                       # o nome do órgão vai no evento, não no formulário
        nome = form.achar(c.campos.get(campo, ()))
        if nome is None:
            return Resultado(False, c.id, acao, erro=f"campo {campo} não achado no formulário")
        preenchidos[nome] = valor
    botao = form.botao(c.botao)
    postback = None if botao else form.postback_de(c.botao)
    if botao is None and postback is None:
        return Resultado(False, c.id, acao, erro="botão de consulta não achado")
    leitura = ler(acao, formulario=form.envio(preenchidos, botao=botao, postback=postback))
    if not leitura.ok:
        return Resultado(False, c.id, acao, erro=leitura.erro or f"HTTP {leitura.http}")
    res = Resultado(True, c.id, acao, originais=[leitura.original] if leitura.original else [])
    vistas: set[str] = set()
    atual = leitura
    while True:
        res.paginas += 1
        lido = ler_html(atual.conteudo)
        achada = tabela_de_resultado(lido.tabelas, c.colunas)
        if achada is None:
            if res.paginas == 1:
                texto = norm(re.sub(r"<[^>]+>", " ", _decodificar(atual.conteudo)))
                if any(s in texto for s in ("NENHUM REGISTRO", "NAO HA REGISTRO", "NAO FORAM ENCONTRADOS",
                                             "NENHUM DADO", "SEM REGISTROS")):
                    res.vazio = True
                    return res
                res.ok = False
                res.erro = "a resposta não traz a tabela de resultado com as colunas configuradas"
            return res
        tabela, mapa = achada
        sha = atual.original.sha256 if atual.original else ""
        fixos = {"orgao": valores.get("orgao_nome", "")}
        evs = eventos_da_tabela(tabela, mapa, c.tipo, consulta=c.id, url=acao, padrao_dotacao=portal.dotacao,
                                fixos=fixos)
        form_atual = (lido.formularios or [form])[0]
        for ev in evs:
            ev["sha256"] = sha
            selecao = ev.pop("_selecao", None)
            res.eventos.append(ev)
            if c.detalhe and selecao:
                res.eventos.extend(_detalhe(ler, portal, c, acao, form_atual, selecao, ev))
        proximas = [p for p in paginas_do_grid(tabela, form_atual) if p[1] not in vistas
                    and p[1] != f"Page${res.paginas}"]
        proximas = [p for p in proximas if _numero_da_pagina(p[1]) == res.paginas + 1] or \
            [p for p in proximas if p[1] in ("Page$Next", "Page$Proxima")]
        if not proximas or res.paginas >= portal.paginas_maximas:
            if not evs and res.paginas == 1:
                res.vazio = True
            return res
        vistas.add(proximas[0][1])
        atual = ler(acao, formulario=form_atual.envio({}, postback=proximas[0]))
        if not atual.ok:
            res.ok = False
            res.erro = f"página {res.paginas + 1}: {atual.erro or atual.http}"
            return res
        if atual.original:
            res.originais.append(atual.original)


def _numero_da_pagina(arg: str) -> int | None:
    m = re.fullmatch(r"Page\$(\d+)", arg)
    return int(m.group(1)) if m else None


def _detalhe(ler: Ler, portal: Portal, c: Consulta, acao: str, form: Formulario, selecao, base: dict) -> list[dict]:
    if isinstance(selecao, tuple):
        leitura = ler(acao, formulario=form.envio({}, postback=selecao))
        url = acao
    else:
        url = urljoin(acao, selecao)
        leitura = ler(url)
    if not leitura.ok:
        return [{**{k: base.get(k, "") for k in CAMPOS_EVENTO}, "tipo": "falha_detalhe", "valor": 0.0,
                 "historico": f"detalhe não lido: {leitura.erro or leitura.http}", "url": url}]
    evs = eventos_do_detalhe(leitura.conteudo, portal.detalhe, c.colunas, base, url=url,
                             padrao_dotacao=portal.dotacao)
    sha = leitura.original.sha256 if leitura.original else ""
    for ev in evs:
        ev["sha256"] = sha
    return evs


# --- O portal novo (WordPress): os arquivos de uma categoria --------------------------------------

def arquivos_da_categoria(html, base: str, formatos: Iterable[str] = ("csv", "xls", "xlsx", "ods", "pdf", "json")
                          ) -> list[dict]:
    exts = tuple("." + f.lower() for f in formatos)
    out, vistos = [], set()
    for href, texto in ler_html(html).links:
        if not href:
            continue
        url = urljoin(base, unescape(href))
        caminho = url.split("?")[0].lower()
        if caminho.endswith(exts) and url not in vistos:
            vistos.add(url)
            out.append({"titulo": texto or url.rsplit("/", 1)[-1], "url": url,
                        "formato": caminho.rsplit(".", 1)[-1]})
    return out


def eventos_do_csv(conteudo: bytes, colunas: dict[str, tuple[str, ...]], tipo: str, *, url: str = "",
                   padrao_dotacao: str = DOTACAO_PADRAO) -> list[dict]:
    """Uma planilha CSV da categoria Despesas, lida com as mesmas colunas da consulta."""
    texto = _decodificar(conteudo) if not conteudo.startswith(b"\xef\xbb\xbf") else conteudo.decode("utf-8-sig")
    amostra = texto[:4096]
    sep = ";" if amostra.count(";") >= amostra.count(",") else ","
    linhas = list(csv.reader(io.StringIO(texto), delimiter=sep))
    if not linhas:
        return []
    t = Tabela("csv", [c.strip() for c in linhas[0]], [[Celula(x.strip()) for x in ln] for ln in linhas[1:] if ln])
    m = mapear(t, colunas)
    if "valor" not in m:
        raise ValueError("a planilha não traz a coluna de valor configurada")
    evs = eventos_da_tabela(t, m, tipo, consulta="wordpress", url=url, padrao_dotacao=padrao_dotacao)
    for ev in evs:
        ev.pop("_selecao", None)
    return evs


# --- O banco ----------------------------------------------------------------------------------------

TABELAS_SQL = """
CREATE TABLE IF NOT EXISTS despesa_eventos (tipo TEXT, empenho TEXT, ordem TEXT, data TEXT, orgao TEXT,
    credor TEXT, documento TEXT, valor REAL, elemento TEXT, fonte TEXT, funcao TEXT, subfuncao TEXT,
    dotacao TEXT, historico TEXT, consulta TEXT, url TEXT, sha256 TEXT, coletado_em TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS despesa_eventos_chave ON despesa_eventos
    (tipo, empenho, ordem, data, documento, valor, orgao);
CREATE TABLE IF NOT EXISTS despesa_consultas (consulta TEXT, dia TEXT, orgao TEXT, situacao TEXT,
    linhas INTEGER, paginas INTEGER, url TEXT, erro TEXT, quando TEXT);
"""
# Para o motor do banco histórico (onisciente/historico.py): o que refazer ao refazer o motor.
TABELAS_DO_MOTOR = [("coletas", "motor = 'execucao_goiania'"), ("despesa_eventos", ""), ("despesa_consultas", "")]


def criar_tabelas(con) -> None:
    con.executescript(TABELAS_SQL)


def gravar(con, eventos: Iterable[dict], *, coletado_em: str | None = None) -> int:
    """Grava os eventos sem repetir (a chave é tipo, empenho, ordem, data, credor, valor e órgão)."""
    criar_tabelas(con)
    quando = coletado_em or date.today().isoformat()
    n = 0
    for ev in eventos:
        linha = {k: ev.get(k, "") for k in CAMPOS_EVENTO}
        linha["valor"] = float(ev.get("valor") or 0.0)
        linha["coletado_em"] = linha["coletado_em"] or quando
        cur = con.execute(f"INSERT OR IGNORE INTO despesa_eventos ({', '.join(CAMPOS_EVENTO)}) VALUES "
                          f"({', '.join('?' for _ in CAMPOS_EVENTO)})", [linha[k] for k in CAMPOS_EVENTO])
        n += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
    return n


# --- O motor diário ---------------------------------------------------------------------------------

def dias_a_ler(con, consulta: str, inicio: date, fim: date) -> list[date]:
    """Os dias do intervalo sem consulta bem-sucedida (lida ou vazia) registrada: o motor continua
    de onde parou e refaz só o que falhou."""
    criar_tabelas(con)
    ultima: dict[tuple[str, str], str] = {}
    for dia, orgao, situacao in con.execute(
            "select dia, orgao, situacao from despesa_consultas where consulta = ? and dia != '' "
            "order by rowid", (consulta,)):
        ultima[(dia, orgao)] = situacao          # vale a leitura mais recente de cada órgão no dia
    por_dia: dict[str, set[str]] = {}
    for (dia, _orgao), situacao in ultima.items():
        por_dia.setdefault(dia, set()).add(situacao)
    feitos = {d for d, s in por_dia.items() if "falha" not in s}
    out, d = [], inicio
    while d <= fim:
        if d.isoformat() not in feitos:
            out.append(d)
        d += timedelta(days=1)
    return out


def motor(ctx, portal: Portal, *, consultas: Iterable[str] = ("empenho_orgao", "ordem_pagamento_orgao"),
          limite_de_dias: int = 31) -> dict:
    """Lê os dias que faltam (do começo do intervalo até ontem), consulta a consulta, órgão a órgão.

    ``ctx`` é o contexto do banco histórico: ``ctx.ler(motor, alvo, url, mes=, formulario=)``,
    ``ctx.banco.con``, ``ctx.meses`` e ``ctx.hoje``. Cada rodada lê no máximo ``limite_de_dias``
    dias por consulta, do mais recente para o mais antigo: o diário fica em dia primeiro, e o
    passado se completa nas rodadas seguintes."""
    con = ctx.banco.con
    criar_tabelas(con)
    inicio = date.fromisoformat(ctx.meses[0] + "-01")
    ontem = ctx.hoje - timedelta(days=1)
    resumo = {"eventos": 0, "consultas": 0, "falhas": 0, "vazias": 0}

    for cid in consultas:
        c = portal.consulta(cid)

        def ler(url, formulario=None, _c=c):
            return ctx.ler("execucao_goiania", _c.id, url, formulario=formulario, tempo=90)

        aberta = abrir_consulta(ler, portal, c)
        if isinstance(aberta, str):
            con.execute("INSERT INTO despesa_consultas VALUES (?,?,?,?,?,?,?,?,?)",
                        (c.id, "", "", "falha", 0, 0, portal.base, aberta, datetime.now().isoformat()))
            resumo["falhas"] += 1
            continue
        orgaos = opcoes_de_orgao(aberta[1], c) if c.percorre_orgaos else [("", "")]
        for dia in sorted(dias_a_ler(con, c.id, inicio, ontem), reverse=True)[:limite_de_dias]:
            for valor_orgao, nome_orgao in orgaos or [("", "")]:
                valores = {}
                if "data" in c.campos:
                    valores["data"] = dia.strftime(portal.formato_data)
                if "data_inicial" in c.campos:
                    valores["data_inicial"] = dia.strftime(portal.formato_data)
                    valores["data_final"] = dia.strftime(portal.formato_data)
                if valor_orgao:
                    valores["orgao"] = valor_orgao
                    valores["orgao_nome"] = nome_orgao
                res = consultar(ler, portal, c, valores, aberta=aberta)
                for ev in res.eventos:
                    ev["orgao"] = ev.get("orgao") or nome_orgao
                novos = gravar(con, [e for e in res.eventos if e["tipo"] != "falha_detalhe"])
                falhas_detalhe = sum(1 for e in res.eventos if e["tipo"] == "falha_detalhe")
                situacao = "falha" if not res.ok else ("vazia" if res.vazio else "lida")
                con.execute("INSERT INTO despesa_consultas VALUES (?,?,?,?,?,?,?,?,?)",
                            (c.id, dia.isoformat(), nome_orgao, situacao, len(res.eventos), res.paginas, res.url,
                             res.erro or (f"{falhas_detalhe} detalhe(s) não lido(s)" if falhas_detalhe else ""),
                             datetime.now().isoformat()))
                resumo["eventos"] += novos
                resumo["consultas"] += 1
                resumo["falhas"] += situacao == "falha"
                resumo["vazias"] += situacao == "vazia"
                if not res.ok and "campo" in res.erro:
                    break                  # o formulário mudou: o resto do dia falharia igual
        con.commit()
    return resumo
