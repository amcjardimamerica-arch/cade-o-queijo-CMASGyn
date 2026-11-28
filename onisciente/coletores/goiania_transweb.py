"""A execução da despesa de Goiânia, item a item: empenhos, liquidações, ordens de pagamento e pagamentos.

Duas portas, as duas lidas pelo que a página mostra, sem adivinhar o que ela não mostra:

* o **TransWeb** (www10.goiania.go.gov.br/transweb/), sistema ASP.NET com as consultas do manual
  ("Empenho por Órgão", "Empenho por Credor", "Ordem de Pagamento por Órgão"). Cada consulta é um
  formulário com estado escondido (``__VIEWSTATE``, ``__EVENTVALIDATION``): o coletor lê a página,
  devolve o estado como veio, preenche data e órgão, aperta o botão (ou dispara o ``__doPostBack``
  do botão), lê a tabela de resultado, segue a paginação do GridView e, quando a consulta tem
  detalhe, escolhe cada empenho para ler as liquidações e os pagamentos dele;
* a **página real** ``Portal_Despesas.aspx`` (OutSystems), lida pela sondagem: a lista do mês, uma
  linha por empenho, com os popups de liquidação e de pagamento de cada linha (``consultar_lista``);
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
import json
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
# OutSystems: OsAjax(evento, id de origem, alvo (o name, com $), evento do servidor, baldes, ...).
_OSAJAX = re.compile(r"OsAjax\(\s*[^,]*,\s*'([^']*)'\s*,\s*'([^']*)'\s*,\s*'([^']*)'\s*,\s*'([^']*)'")
_VAZIOS = ("area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr")
_OCULTO = re.compile(r"display\s*:\s*none", re.I)


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
    ajax: list[dict] = field(default_factory=list)                  # OsAjax achados (OutSystems)

    @property
    def aspnet(self) -> bool:
        return "__VIEWSTATE" in self.campos or "__OSVSTATE" in self.campos

    @property
    def outsystems(self) -> bool:
        """O TransWeb atual é OutSystems: o estado da tela vai no __OSVSTATE (o __VIEWSTATE vem vazio)."""
        return "__OSVSTATE" in self.campos

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

    def envio_ajax(self, valores: dict[str, str], alvo: str, *, evento: str = "",
                   baldes: str = "__OSVSTATE,") -> dict[str, str]:
        """O corpo do pedido que o OsAjax do OutSystems monta (lido em _osjs.js): o formulário
        serializado sem nenhum botão, ``__EVENTTARGET`` com o alvo, ``__AJAX`` com os baldes e,
        quando há evento (``Change``, ``Notify``), ``__AJAXEVENT``."""
        corpo = dict(self.campos)
        for n, _ in self.botoes:
            corpo.pop(n, None)
        corpo.update(valores)
        corpo["__EVENTTARGET"] = alvo
        corpo["__AJAX"] = baldes
        if evento:
            corpo["__AJAXEVENT"] = evento
        corpo.pop("__EVENTARGUMENT", None)
        return corpo

    def valor_de_opcao(self, nome: str, valor: str) -> str:
        """O valor que o select aceita: o próprio, ou a opção do OutSystems (``__ossli_11``) cujo
        fim é o valor pedido, ou a opção cujo texto é o valor pedido."""
        ops = self.opcoes.get(nome)
        if not ops or valor in (v for v, _ in ops):
            return valor
        alvo = str(valor).strip()
        for v, _t in ops:
            if v.startswith("__ossli_") and v[len("__ossli_"):] == alvo:
                return v
        for v, t in ops:
            if norm(t) == norm(alvo):
                return v
        return valor


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
        self._script = 0                    # dentro de <script> ou <style>: o texto não é dado
        self._ocultos: list[str] = []       # elementos com display:none abertos
        self.ajax: list[dict] = []          # os OsAjax da página, com a classe e o texto do link

    # formulário -----------------------------------------------------------------------------
    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v if v is not None else "") for k, v in attrs}
        if tag in ("script", "style"):
            self._script += 1
            return
        if tag not in _VAZIOS and _OCULTO.search(a.get("style", "")):
            self._ocultos.append(tag)
        chamada = None
        for valor in a.values():
            for origem, alvo, evento, baldes in _OSAJAX.findall(valor):
                chamada = {"id": origem, "alvo": alvo, "evento": evento, "baldes": baldes, "tag": tag,
                           "classe": a.get("class", ""), "texto": ""}
                self.ajax.append(chamada)
                if self._form is not None:
                    self._form.ajax.append(chamada)
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
            self._celula = {"texto": [], "postbacks": [], "links": [], "th": tag == "th",
                            "ocultos": len(self._ocultos)}
        elif tag == "br" and self._celula is not None:
            self._celula["texto"].append(" ")
        if tag == "a":
            self._link = [a.get("href", ""), [], chamada]
            if self._celula is not None and a.get("href") and not a["href"].lower().startswith("javascript"):
                self._celula["links"].append(a["href"])

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._script = max(0, self._script - 1)
            return
        if self._ocultos and self._ocultos[-1] == tag:
            self._ocultos.pop()
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
            del self._ocultos[c["ocultos"]:]          # o que ficou aberto dentro da célula fecha com ela
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
            href, texto, chamada = self._link
            self.links.append((href, re.sub(r"\s+", " ", "".join(texto)).strip()))
            if chamada is not None:
                chamada["texto"] = self.links[-1][1]
            self._link = None

    def handle_data(self, data):
        if self._script:
            return
        if self._opcao is not None:
            self._opcao[1] += data
        if self._textarea and self._form is not None:
            self._form.campos[self._textarea] += data
        if self._celula is not None and len(self._ocultos) <= self._celula["ocultos"]:
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
    # Só nas consultas da página real (``[[transweb.despesas]]``): o que o HTML lido comprovou,
    # como o pedido é enviado (``postback`` ou ``ajax``, como o OsAjax do OutSystems) e os popups
    # de cada linha (liquidações, pagamentos e os dados do empenho).
    confirmado: bool = False
    envio: str = "postback"
    envio_confirmado: bool = False
    popups: dict = field(default_factory=dict)
    tabela: str = ""                    # o fim do id da tabela de resultado


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
    menu_despesa: tuple[str, ...] = ()
    # As consultas da página real Portal_Despesas.aspx, lida pela sondagem (as de cima são as do
    # manual de 2010, que o portal atual não tem mais).
    despesas: tuple[Consulta, ...] = ()

    def consulta(self, cid: str) -> Consulta:
        for c in self.consultas + self.despesas:
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

    def _consulta(c: dict) -> Consulta:
        popups = {}
        for tipo, p in (c.get("popups") or {}).items():
            popups[tipo] = {"pagina": p["pagina"], "confirmado": bool(p.get("confirmado")),
                            "colunas": {k: tuple(v) for k, v in (p.get("colunas") or {}).items()},
                            "campos": {k: tuple(v) for k, v in (p.get("campos") or {}).items()}}
        envio = c.get("envio") or {}
        return Consulta(
            id=c["id"], tipo=c["tipo"], titulo=c.get("titulo", c["id"]),
            paginas=tuple(c.get("paginas", ())), granularidade=c.get("granularidade", "dia"),
            percorre_orgaos=bool(c.get("percorre_orgaos", False)), botao=tuple(c.get("botao", ("Consultar",))),
            detalhe=bool(c.get("detalhe", False)),
            campos={k: tuple(v) for k, v in (c.get("campos") or {}).items()},
            colunas={k: tuple(v) for k, v in (c.get("colunas") or {}).items()},
            confirmado=bool(c.get("confirmado")), envio=str(envio.get("modo", "postback")),
            envio_confirmado=bool(envio.get("confirmado")), popups=popups, tabela=str(c.get("tabela", "")))

    consultas = [_consulta(c) for c in tw.get("consultas", [])]
    despesas = [_consulta(c) for c in tw.get("despesas", [])]
    return Portal(
        base=tw.get("base", ""), entradas=tuple(tw.get("entradas", ())), confirmado=bool(tw.get("confirmado")),
        formato_data=tw.get("formato_data", "%d/%m/%Y"), paginas_maximas=int(tw.get("paginas_maximas", 200)),
        consultas=tuple(consultas), detalhe={k: tuple(v) for k, v in (tw.get("detalhe") or {}).items()},
        wordpress=dict(bruto.get("wordpress") or {}), dotacao=str(tw.get("dotacao", "") or DOTACAO_PADRAO),
        arquivo=str(caminho), menu_despesa=tuple(tw.get("menu_despesa", ())), despesas=tuple(despesas))


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
              "elemento": re.sub(r"\D", "", cel("elemento").split(" - ")[0]), "fonte": re.sub(r"\D", "", cel("fonte")),
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


def paginas_do_menu(html, base: str, textos: Iterable[str]) -> list[str]:
    """Os links .aspx do menu cujo texto casa com um dos textos dados, na ordem dos textos."""
    links = [(urljoin(base, unescape(h)), norm(t)) for h, t in ler_html(html).links if h and ".aspx" in h.lower()]
    out: list[str] = []
    for alvo in (norm(t) for t in textos):
        for url, texto in links:
            if alvo and alvo in texto and url not in out:
                out.append(url)
    return out


# Campos de filtro que a consulta pode deixar em branco: não decidem se a página é a certa.
OPCIONAIS = ("orgao", "documento", "favorecido", "empenho")


def abrir_consulta(ler: Ler, portal: Portal, c: Consulta) -> tuple[str, Formulario, Leitura] | str:
    """A primeira página candidata que responde com um formulário que tem os campos da consulta.

    Sem nenhuma candidata boa, procura no menu das páginas de entrada os links da despesa e tenta
    cada um deles (o TransWeb atual não tem mais os caminhos do manual de 2010)."""
    obrigatorios = [k for k in c.campos if k not in OPCIONAIS]
    erros: list[str] = []
    candidatas = [urljoin(portal.base, p) for p in c.paginas]
    tentadas: set[str] = set()
    menu_lido = not portal.menu_despesa
    while True:
        while candidatas:
            url = candidatas.pop(0)
            if url in tentadas:
                continue
            tentadas.add(url)
            pagina = url.rsplit("/", 1)[-1]
            leitura = ler(url)
            if not leitura.ok:
                erros.append(f"{pagina}: {leitura.erro or leitura.http}")
                continue
            for f in formularios(leitura.conteudo):
                if all(f.achar(c.campos[k]) for k in obrigatorios):
                    return urljoin(url, f.acao or url), f, leitura
            erros.append(f"{pagina}: formulário sem os campos {', '.join(obrigatorios)}")
        if menu_lido:
            break
        menu_lido = True
        for entrada in portal.entradas:
            u = urljoin(portal.base, entrada)
            lida = ler(u)
            if lida.ok:
                candidatas += [x for x in paginas_do_menu(lida.conteudo, u, portal.menu_despesa) if x not in tentadas]
            else:
                erros.append(f"{entrada}: {lida.erro or lida.http}")
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
        preenchidos[nome] = form.valor_de_opcao(nome, valor)
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


# --- A página real: Portal_Despesas.aspx (OutSystems), a lista por mês e os popups --------------------
#
# Lida pela sondagem de 27/11/2026: um formulário OutSystems (mês, ano, órgão, favorecido, empenho e o
# botão Buscar), a tabela com uma linha por empenho (Beneficiário, Nr. Empenho, Data, Orgão, Natureza
# Despesa, Valor Empenhado, Valor Liquidado, Valor Pago), a tabela de totais, o contador "1 to 20 of
# 822 records" e a paginação por OsAjax. Cada valor da linha é um link (GET) para um popup em
# /DespesasWebBlocks/: EmpenhoPopUp (os dados do empenho), LiquidacaoPopUp (as liquidações) e
# PagamentoPopUp (as ordens de pagamento e o valor pago); valor zero vem com link "#".

_CONTADOR = re.compile(r"(\d+)\s*(?:to|a|até)\s*(\d+)\s*(?:of|de)\s*(\d+)\s*(?:records|registros)", re.I)
_OS_JSON = "OsJSONUpdate("


def contador(html) -> tuple[int, int, int] | None:
    """O contador da lista do OutSystems: ``1 to 20 of 822 records`` vira (1, 20, 822)."""
    texto = html if isinstance(html, str) else _decodificar(html)
    texto = re.sub(r"<[^>]+>", " ", re.sub(r"<script.*?</script>", " ", texto, flags=re.S | re.I))
    m = _CONTADOR.search(texto)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def totais_da_lista(tabs: list[Tabela]) -> dict[str, float]:
    """A tabela de totais (Total Empenhado, Total Liquidado, Total Pago), em qualquer arrumação."""
    out: dict[str, float] = {}
    for t in tabs:
        textos = list(t.cabecalho) + [c.texto for ln in t.linhas for c in ln]
        for tx in textos:
            m = re.match(r"\s*Total\s+(Empenhado|Liquidado|Pago)\s*:?\s*(R\$\s*)?([\d.,()-]+)\s*$", tx, re.I)
            if m and valor_br(m.group(3)) is not None:
                out[m.group(1).lower()] = valor_br(m.group(3))
    return out


def resposta_outsystems(conteudo) -> tuple[str, dict[str, str]] | None:
    """A resposta de um pedido OsAjax: blocos ``<script>OsJSONUpdate({...})</script>`` (o formato
    que o _osjs.js processa). Devolve o HTML dos trechos trocados (cada um embrulhado com o seu id,
    numa ``<table>`` quando o trecho são linhas) e os campos escondidos novos (o ``__OSVSTATE``).
    Uma página inteira (postback comum) não é resposta OsAjax: devolve None."""
    texto = conteudo if isinstance(conteudo, str) else _decodificar(conteudo)
    if _OS_JSON not in texto:
        return None
    decod = json.JSONDecoder()
    partes: list[str] = []
    escondidos: dict[str, str] = {}
    i = texto.find(_OS_JSON)
    while i != -1:
        try:
            obj, _fim = decod.raw_decode(texto, i + len(_OS_JSON))
        except ValueError:
            i = texto.find(_OS_JSON, i + 1)
            continue
        if isinstance(obj, dict):
            escondidos.update({k: str(v) for k, v in (obj.get("hidden") or {}).items()})
            for ident, trecho in (obj.get("outers") or {}).items():
                inner = trecho.get("inner", "") if isinstance(trecho, dict) else str(trecho)
                if re.match(r"\s*<(thead|tbody|tr)\b", inner, re.I):
                    partes.append(f'<table id="{ident}">{inner}</table>')
                else:
                    partes.append(f'<div id="{ident}">{inner}</div>')
        i = texto.find(_OS_JSON, i + 1)
    return "\n".join(partes), escondidos


def proxima_pagina(ajax: list[dict], atual: int) -> dict | None:
    """O link da página seguinte: o ``next`` do navegador (o alvo dele não muda de uma página para
    outra), ou o número ``atual + 1``."""
    for a in ajax:
        if "ListNavigation_Next" in a.get("classe", ""):
            return a
    for a in ajax:
        if "ListNavigation_PageNumber" in a.get("classe", "") and a.get("texto", "").strip() == str(atual + 1):
            return a
    return None


def dados_do_empenho(html, campos: dict[str, tuple[str, ...]], *, padrao_dotacao: str = DOTACAO_PADRAO) -> dict:
    """O EmpenhoPopUp: um formulário só de leitura (rótulo e campo). Vazio, " - " e "R$ 0,00" não
    contam (a sondagem leu o popup sem o empenho, com todos os campos assim)."""
    forms = formularios(html)
    if not forms:
        return {}
    f = forms[0]
    out: dict[str, str] = {}
    for campo, cands in campos.items():
        nome = f.achar(cands)
        if not nome:
            continue
        v = re.sub(r"\s+", " ", f.campos.get(nome, "")).strip()
        if not v or v.strip(" -") == "" or (v.startswith("R$") and valor_br(v) == 0):
            continue
        if campo == "documento":
            v = documento(v)
        elif campo in ("funcao", "subfuncao", "fonte"):
            m = re.match(r"\s*(\d+)", v)
            v = m.group(1) if m else ""
        elif campo == "elemento":
            v = re.sub(r"\D", "", v.split(" - ")[0])
        elif campo == "data":
            d = data_br(v)
            v = d.isoformat() if d else ""
        if v:
            out[campo] = v
    if out.get("dotacao"):
        d = classificar_dotacao(out["dotacao"], padrao_dotacao)
        for k in ("funcao", "subfuncao"):
            out.setdefault(k, d.get(k, ""))
    return {k: v for k, v in out.items() if v}


def eventos_do_popup(html, tipo: str, colunas: dict[str, tuple[str, ...]], base: dict, *,
                     url: str = "") -> list[dict]:
    """As linhas de um popup de liquidação ou de pagamento, com o empenho, o credor e o órgão da lista.

    Liquidação: o valor é o saldo liquidado; a parte anulada vira um evento ``anulacao`` e uma
    liquidação anulada por inteiro não vira liquidação. Pagamento: o valor pago, com a data e o
    número da ordem de pagamento; uma ordem sem valor pago vira ``ordem_pagamento``."""
    achada = None
    for t in tabelas(html):
        m = mapear(t, colunas)
        if "valor" in m:
            achada = (t, m)
            break
    if achada is None:
        return []
    t, m = achada
    fixos = {k: base.get(k, "") for k in ("empenho", "orgao", "credor", "documento", "elemento", "fonte",
                                          "funcao", "subfuncao", "dotacao", "consulta")}
    out = []
    for linha in t.linhas:
        def cel(campo: str) -> str:
            i = m.get(campo)
            return linha[i].texto if i is not None and i < len(linha) else ""
        valor = valor_br(cel("valor"))
        if valor is None:
            continue
        dia = data_br(cel("data"))
        ev = {k: "" for k in CAMPOS_EVENTO}
        ev.update(fixos)
        ev.update({"tipo": tipo, "ordem": cel("ordem").strip(), "data": dia.isoformat() if dia else "",
                   "valor": round(valor, 2), "url": url})
        fonte = re.sub(r"\D", "", cel("fonte"))
        if fonte:
            ev["fonte"] = fonte
        if tipo == "liquidacao":
            anulado = valor_br(cel("anulado")) or 0.0
            if anulado > 0:
                out.append({**ev, "tipo": "anulacao", "valor": round(anulado, 2),
                            "historico": "anulação de liquidação"})
            if valor <= 0:
                continue
        elif tipo == "pagamento" and valor <= 0:
            op = valor_br(cel("valor_op")) or 0.0
            if op <= 0:
                continue
            ev.update({"tipo": "ordem_pagamento", "valor": round(op, 2)})
        out.append(ev)
    return out


def _popups_da_linha(c: Consulta, links: list[str]) -> dict[str, str]:
    """Os links da linha que são popups configurados: tipo -> URL (o "#" do valor zero fica fora)."""
    out = {}
    for href in links:
        caminho = href.split("?", 1)[0].lower()
        for tipo, p in c.popups.items():
            if caminho.endswith("/" + p["pagina"].lower()) or caminho == p["pagina"].lower():
                out.setdefault(tipo, href)
    return out


def consultar_lista(ler: Ler, portal: Portal, c: Consulta, valores: dict[str, str], *,
                    aberta: tuple[str, Formulario, Leitura] | None = None,
                    conhecidos: dict[str, dict] | None = None) -> Resultado:
    """A lista de Portal_Despesas.aspx filtrada (mês, ano e o que mais vier), página a página.

    Cada linha é um empenho. Os popups da linha (liquidações, pagamentos, dados do empenho) são
    lidos quando o banco ainda não tem o que a linha mostra (``conhecidos``: empenho -> soma
    liquidada, soma paga e documento já gravados). A soma das liquidações e dos pagamentos de
    cada popup é conferida com o total da linha; a soma da lista, com a tabela de totais."""
    if aberta is None:
        aberta = abrir_consulta(ler, portal, c)
    if isinstance(aberta, str):
        return Resultado(False, c.id, erro=aberta)
    acao, form, _primeira = aberta
    conhecidos = conhecidos or {}
    preenchidos = {}
    for campo, valor in valores.items():
        if campo.endswith("_nome"):
            continue
        nome = form.achar(c.campos.get(campo, ()))
        if nome is None:
            return Resultado(False, c.id, acao, erro=f"campo {campo} não achado no formulário")
        preenchidos[nome] = form.valor_de_opcao(nome, valor)
    botao = form.botao(c.botao)
    if botao is None:
        return Resultado(False, c.id, acao, erro="botão de consulta não achado")
    ajax = c.envio == "ajax"
    destino = acao

    def enviar(corpo):
        return ler(destino, formulario=corpo)

    corpo = form.envio_ajax(preenchidos, botao[0]) if ajax else form.envio(preenchidos, botao=botao)
    leitura = enviar(corpo)
    if not leitura.ok:
        return Resultado(False, c.id, acao, erro=leitura.erro or f"HTTP {leitura.http}")
    res = Resultado(True, c.id, acao, originais=[leitura.original] if leitura.original else [])
    estado = dict(corpo)                      # o que vai de volta no pedido seguinte
    estado.pop("__AJAXEVENT", None)
    for n, _ in form.botoes:
        estado.pop(n, None)
    ajax_da_pagina: list[dict] = list(form.ajax)
    somas = {"empenhado": 0.0, "liquidado": 0.0, "pago": 0.0}
    totais: dict[str, float] = {}
    vistos: set[str] = set()
    atual = leitura
    while True:
        res.paginas += 1
        bruto = atual.conteudo
        parcial = resposta_outsystems(bruto)
        if parcial is not None:
            html, escondidos = parcial
            estado.update(escondidos)
        else:
            html = bruto
        lido = ler_html(html)
        if lido.formularios:                       # página inteira: o estado novo vem nela
            estado = {**lido.formularios[0].campos}
            for n, _ in lido.formularios[0].botoes:
                estado.pop(n, None)
        if lido.ajax:
            ajax_da_pagina = lido.ajax
        totais = totais_da_lista(lido.tabelas) or totais
        tabs = [t for t in lido.tabelas if not c.tabela or t.id.endswith(c.tabela)] or lido.tabelas
        achada = tabela_de_resultado(tabs, c.colunas)
        if achada is None:
            texto = norm(re.sub(r"<[^>]+>", " ", html if isinstance(html, str) else _decodificar(html)))
            if res.paginas == 1 and any(s in texto for s in ("NO ITEMS TO SHOW", "NENHUM REGISTRO", "NAO HA REGISTRO",
                                                             "NAO FORAM ENCONTRADOS", "SEM REGISTROS")):
                res.vazio = True
                return res
            res.ok = False
            res.erro = (f"página {res.paginas}: " if res.paginas > 1 else "") + \
                "a resposta não traz a tabela de resultado com as colunas configuradas"
            return res
        tabela, mapa = achada
        sha = atual.original.sha256 if atual.original else ""
        novas = 0
        for linha in tabela.linhas:
            evs = eventos_da_tabela(Tabela(tabela.id, tabela.cabecalho, [linha]), mapa, c.tipo, consulta=c.id,
                                    url=acao, padrao_dotacao=portal.dotacao,
                                    fixos={"orgao": valores.get("orgao_nome", "")})
            if not evs:
                continue
            ev = evs[0]
            ev.pop("_selecao", None)
            chave = ev["empenho"] or f"{ev['credor']}|{ev['data']}|{ev['valor']}"
            if chave in vistos:
                continue
            vistos.add(chave)
            novas += 1
            ev["sha256"] = sha

            def total(campo: str) -> float:
                i = mapa.get(campo)
                return (valor_br(linha[i].texto) or 0.0) if i is not None and i < len(linha) else 0.0
            liq, pago = round(total("liquidado"), 2), round(total("pago"), 2)
            somas["empenhado"] += ev["valor"]
            somas["liquidado"] += liq
            somas["pago"] += pago
            ja = conhecidos.get(ev["empenho"], {})
            popups = _popups_da_linha(c, [h for cel in linha for h in cel.links])
            filhos: list[dict] = []
            if "documento" in ja:                  # o empenho já está no banco: os dados do popup vêm de lá
                for k in ("documento", "funcao", "subfuncao", "fonte", "dotacao", "historico"):
                    if ja.get(k) and not ev.get(k):
                        ev[k] = ja[k]
            elif "empenho" in popups:
                lida = ler(popups["empenho"])
                if lida.ok:
                    for k, v in dados_do_empenho(lida.conteudo, c.popups["empenho"]["campos"],
                                                 padrao_dotacao=portal.dotacao).items():
                        if k not in ("valor", "data") and not ev.get(k):
                            ev[k] = v
                else:
                    filhos.append(_falha(ev, popups["empenho"], lida))
            for tipo, alvo_total in (("liquidacao", liq), ("pagamento", pago)):
                if tipo not in popups or alvo_total <= 0:
                    continue
                if round(ja.get(tipo, -1.0), 2) == alvo_total:
                    continue                       # o banco já tem o que a linha mostra
                lida = ler(popups[tipo])
                if not lida.ok:
                    filhos.append(_falha(ev, popups[tipo], lida))
                    continue
                cfg = c.popups[tipo]
                evs_popup = eventos_do_popup(lida.conteudo, tipo, cfg["colunas"], ev, url=popups[tipo])
                psha = lida.original.sha256 if lida.original else ""
                for e in evs_popup:
                    e["sha256"] = psha
                soma = round(sum(e["valor"] for e in evs_popup
                                 if e["tipo"] == ("liquidacao" if tipo == "liquidacao" else "pagamento")), 2)
                if abs(soma - alvo_total) > 0.01:
                    filhos.append({**_falha(ev, popups[tipo], None),
                                   "historico": f"{tipo}: o popup soma {soma:.2f} e a lista mostra {alvo_total:.2f}"})
                filhos.extend(evs_popup)
            res.eventos.append(ev)
            res.eventos.extend(filhos)
        cont = contador(html)
        fim = cont is not None and cont[1] >= cont[2]
        prox = None if fim or novas == 0 else proxima_pagina(ajax_da_pagina, res.paginas)
        if prox is None or res.paginas >= portal.paginas_maximas:
            if cont is not None and not fim and res.paginas < portal.paginas_maximas:
                res.ok = False
                res.erro = f"a lista diz {cont[2]} registros e a página {res.paginas} não leva à seguinte"
            elif totais and fim:
                for k in ("empenhado", "liquidado", "pago"):
                    if k in totais and abs(round(somas[k], 2) - totais[k]) > 0.01:
                        res.eventos.append({**{x: "" for x in CAMPOS_EVENTO}, "tipo": "falha_detalhe",
                                            "valor": 0.0, "consulta": c.id, "url": acao,
                                            "historico": f"total {k}: a lista soma {somas[k]:.2f} e o "
                                                         f"portal mostra {totais[k]:.2f}"})
            if not res.eventos and res.paginas == 1:
                res.vazio = True
            return res
        corpo = (Formulario(acao, "post", campos=estado).envio_ajax({}, prox["alvo"], evento=prox["evento"],
                                                                    baldes=prox["baldes"] or "__OSVSTATE,")
                 if ajax else {**estado, "__EVENTTARGET": prox["alvo"], "__EVENTARGUMENT": ""})
        atual = enviar(corpo)
        if not atual.ok:
            res.ok = False
            res.erro = f"página {res.paginas + 1}: {atual.erro or atual.http}"
            return res
        if atual.original:
            res.originais.append(atual.original)


def _falha(base: dict, url: str, leitura: Leitura | None) -> dict:
    motivo = "" if leitura is None else f"detalhe não lido: {leitura.erro or leitura.http}"
    return {**{k: base.get(k, "") for k in CAMPOS_EVENTO}, "tipo": "falha_detalhe", "valor": 0.0,
            "historico": motivo, "url": url}


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


def categorias_do_portal(html) -> dict[int, str]:
    """As categorias do portal WordPress pelo filtro (``?filtro_simplificado=categoria&categoria=N``)."""
    out: dict[int, str] = {}
    for href, texto in ler_html(html).links:
        m = re.search(r"filtro_simplificado=categoria&(?:amp;|#038;)?categoria=(\d+)", unescape(href or ""))
        if m and texto:
            out.setdefault(int(m.group(1)), " ".join(texto.split()))
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


def meses_a_ler(con, consulta: str, meses: Iterable[str], *, releitura: int = 2) -> list[str]:
    """Os meses (AAAA-MM) sem leitura bem-sucedida da lista, mais os ``releitura`` meses mais recentes
    de novo: a linha de um empenho mostra o liquidado e o pago acumulados, que crescem nos meses
    seguintes ao do empenho. Do mais recente para o mais antigo."""
    criar_tabelas(con)
    ultima: dict[str, str] = {}
    for mes, situacao in con.execute("select dia, situacao from despesa_consultas where consulta = ? and dia != '' "
                                     "order by rowid", (consulta,)):
        ultima[mes] = situacao
    meses = sorted(set(meses), reverse=True)
    recentes = meses[:releitura]
    return [m for m in meses if m in recentes or ultima.get(m) not in ("lida", "vazia")]


def conhecidos_do_banco(con) -> dict[str, dict]:
    """Por empenho, o que o banco já tem: a soma das liquidações e dos pagamentos e os dados do
    empenho (documento, função, subfunção, fonte, dotação e objeto)."""
    criar_tabelas(con)
    out: dict[str, dict] = {}
    for emp, tipo, soma, doc, fun, sub, fonte, dot, hist in con.execute(
            "select empenho, tipo, round(sum(valor), 2), max(documento), max(funcao), max(subfuncao), max(fonte), "
            "max(dotacao), max(historico) from despesa_eventos "
            "where empenho != '' and tipo in ('empenho', 'liquidacao', 'pagamento') group by empenho, tipo"):
        d = out.setdefault(emp, {})
        if tipo == "empenho":
            d.update({"documento": doc or "", "funcao": fun or "", "subfuncao": sub or "", "fonte": fonte or "",
                      "dotacao": dot or "", "historico": hist or ""})
        else:
            d[tipo] = soma or 0.0
    return out


FAMILIAS = {"empenho": ("empenho",), "liquidacao": ("liquidacao", "anulacao"),
            "anulacao": ("liquidacao", "anulacao"), "pagamento": ("pagamento", "ordem_pagamento"),
            "ordem_pagamento": ("pagamento", "ordem_pagamento")}


def gravar_lista(con, eventos: list[dict], consulta: str, *, coletado_em: str | None = None) -> int:
    """Grava o que a lista leu trocando, por empenho, o que a leitura anterior tinha gravado da mesma
    família (o empenho; liquidações e anulações; pagamentos e ordens): a lista mostra valores
    acumulados, e uma liquidação anulada depois não pode ficar contada duas vezes."""
    criar_tabelas(con)
    trocar = {(e["empenho"], fam) for e in eventos if e.get("empenho") and e["tipo"] in FAMILIAS
              for fam in [FAMILIAS[e["tipo"]]]}
    for emp, fam in trocar:
        con.execute(f"DELETE FROM despesa_eventos WHERE consulta = ? AND empenho = ? AND tipo IN "
                    f"({', '.join('?' for _ in fam)})", (consulta, emp, *fam))
    return gravar(con, eventos, coletado_em=coletado_em)


def _motor_mensal(ctx, portal: Portal, c: Consulta, resumo: dict, *, limite_de_meses: int) -> None:
    """A lista de Portal_Despesas.aspx, mês a mês (mês e ano no formulário, todos os órgãos)."""
    con = ctx.banco.con

    def ler(url, formulario=None):
        return ctx.ler("execucao_goiania", c.id, url, formulario=formulario, tempo=90)

    aberta = abrir_consulta(ler, portal, c)
    if isinstance(aberta, str):
        con.execute("INSERT INTO despesa_consultas VALUES (?,?,?,?,?,?,?,?,?)",
                    (c.id, "", "", "falha", 0, 0, portal.base, aberta, datetime.now().isoformat()))
        resumo["falhas"] += 1
        return
    meses = [m for m in ctx.meses if m <= ctx.hoje.strftime("%Y-%m")]
    for mes in meses_a_ler(con, c.id, meses)[:limite_de_meses]:
        ano, mm = mes.split("-")
        valores = {"mes": mm, "ano": ano}
        res = consultar_lista(ler, portal, c, valores, aberta=aberta, conhecidos=conhecidos_do_banco(con))
        novos = gravar_lista(con, [e for e in res.eventos if e["tipo"] != "falha_detalhe"], c.id)
        notas = [e["historico"] for e in res.eventos if e["tipo"] == "falha_detalhe"]
        situacao = "falha" if not res.ok else ("vazia" if res.vazio else "lida")
        con.execute("INSERT INTO despesa_consultas VALUES (?,?,?,?,?,?,?,?,?)",
                    (c.id, mes, "", situacao, len(res.eventos), res.paginas, res.url,
                     res.erro or "; ".join(notas[:5]) + (f" (+{len(notas) - 5})" if len(notas) > 5 else ""),
                     datetime.now().isoformat()))
        resumo["eventos"] += novos
        resumo["consultas"] += 1
        resumo["falhas"] += situacao == "falha"
        resumo["vazias"] += situacao == "vazia"
        con.commit()
        if not res.ok and "campo" in res.erro:
            break


def motor(ctx, portal: Portal, *, consultas: Iterable[str] | None = None, limite_de_dias: int = 31,
          limite_de_meses: int = 3) -> dict:
    """Lê os dias que faltam (do começo do intervalo até ontem), consulta a consulta, órgão a órgão.

    ``ctx`` é o contexto do banco histórico: ``ctx.ler(motor, alvo, url, mes=, formulario=)``,
    ``ctx.banco.con``, ``ctx.meses`` e ``ctx.hoje``. Cada rodada lê no máximo ``limite_de_dias``
    dias por consulta, do mais recente para o mais antigo: o diário fica em dia primeiro, e o
    passado se completa nas rodadas seguintes.

    Sem ``consultas``, lê as da página real (``[[transweb.despesas]]``), que são por mês: cada rodada
    lê no máximo ``limite_de_meses`` meses (os que faltam e os dois mais recentes de novo)."""
    if consultas is None:
        consultas = [c.id for c in portal.despesas] or ["empenho_orgao", "ordem_pagamento_orgao"]
    con = ctx.banco.con
    criar_tabelas(con)
    inicio = date.fromisoformat(ctx.meses[0] + "-01")
    ontem = ctx.hoje - timedelta(days=1)
    resumo = {"eventos": 0, "consultas": 0, "falhas": 0, "vazias": 0}

    for cid in consultas:
        c = portal.consulta(cid)
        if c.granularidade == "mes":
            _motor_mensal(ctx, portal, c, resumo, limite_de_meses=limite_de_meses)
            continue

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
