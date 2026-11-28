"""Coletores da régua legal: ctresb/leis e Sileg.

* ctresb/leis: a Constituição, as leis federais e as de Goiás. Cada norma do
  mapa legal aponta para o arquivo dela; antes de usar uma regra o motor
  confere o campo ``revogada`` do cabeçalho.
* Sileg: as leis de Goiânia, num endereço previsível. O texto é guardado só
  como trecho, com o link e a impressão digital.
"""

from __future__ import annotations

import html
import json
import re
from datetime import date
from pathlib import Path
from urllib.parse import urlencode

import yaml

from ..legal.mapa import MapaLegal, carregar
from ..nucleo.custodia import impressao
from .base import Leitura, ler


def _impressao(leitura: Leitura) -> str | None:
    """O SHA-256 da resposta (o da custódia, quando a leitura o trouxe); None quando não houve resposta."""
    if leitura.original is not None and leitura.original.sha256:
        return leitura.original.sha256
    if leitura.ok or leitura.http is not None or leitura.conteudo:
        return impressao(leitura.conteudo or b"")
    return None

RAW_CTRESB = "https://raw.githubusercontent.com/ctresb/leis/main/"


def cabecalho(markdown: str) -> dict:
    """Lê o cabeçalho YAML de uma norma no formato do ctresb/leis."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", markdown, flags=re.S)
    if not m:
        return {}
    dados = yaml.safe_load(m.group(1)) or {}
    return dados if isinstance(dados, dict) else {}


def conferir_ctresb(mapa: MapaLegal | None = None, *, ler_url=ler) -> list[dict]:
    """Confere cada arquivo do ctresb/leis citado no mapa: existe? está revogado?"""
    mapa = mapa or carregar()
    saida = []
    vistos: set[str] = set()
    for norma in mapa.normas.values():
        for caminho in norma.ctresb:
            if caminho in vistos:
                continue
            vistos.add(caminho)
            leitura = ler_url(RAW_CTRESB + caminho, fonte="ctresb/leis")
            item = {"norma": norma.norma, "caminho": caminho, "ok": leitura.ok}
            if leitura.ok:
                cab = cabecalho(leitura.texto)
                item.update(titulo=cab.get("titulo"), revogada=bool(cab.get("revogada", False)),
                            sha256=_impressao(leitura))
            else:
                item["erro"] = leitura.erro
            saida.append(item)
    return saida


def texto_do_html(pagina: str) -> str:
    """Extrai só o texto de uma página do Sileg (sem guardar o documento)."""
    pagina = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", pagina)
    pagina = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", pagina)
    texto = html.unescape(re.sub(r"<[^>]+>", " ", pagina))
    linhas = [re.sub(r"[ \t\xa0]+", " ", l).strip() for l in texto.splitlines()]
    return "\n".join(l for l in linhas if l)


def ler_sileg(url: str, *, ler_url=ler) -> dict:
    leitura = ler_url(url, fonte="Sileg")
    if not leitura.ok:
        return {"url": url, "ok": False, "erro": leitura.erro}
    texto = texto_do_html(leitura.conteudo.decode("latin-1", errors="replace")
                          if b"charset=iso-8859-1" in leitura.conteudo[:2000].lower()
                          else leitura.texto)
    return {"url": url, "ok": True, "sha256": _impressao(leitura), "inicio": texto[:600]}


# --- Normas de Goiânia no Sileg --------------------------------------------------------
#
# O mapa legal guarda, para cada norma municipal, o endereço oficial dela no Sileg. O motor
# ``normas`` baixa cada uma (só o começo do texto, o tamanho e a impressão digital ficam no
# banco) e procura no índice do Sileg as que o mapa dá como não localizadas, pela lista de
# ``onisciente/legal/procuras.yml``. O que não for achado vira item de ofício
# (``onisciente.legal.normas.ausencias``).

SILEG_SOLR = "https://sileg.goiania.go.gov.br/solr-4.1.0/select"
SILEG_PDF = "http://sileg.goiania.go.gov.br/geral/"
HOSTS_MUNICIPAIS = ("goiania.go.gov.br",)

TABELAS = (
    """CREATE TABLE IF NOT EXISTS normas_municipais (norma_id TEXT, norma TEXT, nome TEXT, url TEXT,
        ok INTEGER, http INTEGER, bytes INTEGER, sha256 TEXT, formato TEXT, inicio TEXT,
        aviso_revogacao INTEGER, erro TEXT)""",
    """CREATE TABLE IF NOT EXISTS normas_procura (norma_id TEXT, alvo TEXT, consulta TEXT, achada INTEGER,
        id_sileg TEXT, data TEXT, url TEXT, confirmada INTEGER, erro TEXT)""",
)
# Revogada por outra norma (o texto da própria norma diz isso no começo): aviso, a conferir.
_REVOGADA = re.compile(r"\b(revogad[ao]s?)\s+(pel[ao]s?|integralmente|totalmente|expressamente)\b", re.I)
_ID_SILEG = re.compile(r"(do|lo|lc|dc|dec)_(\d{8})_(\d+)", re.I)


def e_municipal(url: str) -> bool:
    host = url.split("://", 1)[-1].split("/", 1)[0].lower()
    return any(host == h or host.endswith("." + h) for h in HOSTS_MUNICIPAIS)


def normas_municipais(mapa: MapaLegal | None = None) -> list[dict]:
    """Cada endereço oficial de norma de Goiânia citado no mapa legal (um por linha)."""
    mapa = mapa or carregar()
    saida, vistos = [], set()
    for n in mapa.normas.values():
        for nome, url in n.oficial:
            if e_municipal(url) and url not in vistos:
                vistos.add(url)
                saida.append({"norma_id": n.id, "norma": n.norma, "nome": nome, "url": url})
    return saida


def ler_norma_municipal(url: str, *, ler_url=ler) -> dict:
    """Baixa a norma do Sileg: HTML vira começo de texto; PDF fica só com o tamanho e a impressão."""
    leitura = ler_url(url, fonte="Sileg")
    item = {"url": url, "ok": int(leitura.ok), "http": leitura.http, "erro": leitura.erro or None,
            "bytes": len(leitura.conteudo or b""), "sha256": _impressao(leitura), "formato": None,
            "inicio": None, "aviso_revogacao": 0}
    if not leitura.ok:
        return item
    conteudo = leitura.conteudo or b""
    if conteudo[:5] == b"%PDF-" or url.lower().endswith(".pdf"):
        item["formato"] = "pdf"
        return item
    pagina = (conteudo.decode("latin-1", errors="replace")
              if b"iso-8859-1" in conteudo[:2000].lower() else conteudo.decode("utf-8", errors="replace"))
    texto = texto_do_html(pagina)
    if len(texto) < 80:                       # página vazia ou de erro no lugar da lei
        item.update(ok=0, erro="página sem o texto da norma")
        return item
    item.update(formato="html", inicio=texto[:600], aviso_revogacao=int(bool(_REVOGADA.search(texto[:1500]))))
    return item


def consulta_por_numero(tipo: str, numero: int, ano: int) -> str:
    """Consulta ao índice do Sileg por tipo, ano e número (``lc_2021..._000000335``).
    Decreto aparece no índice como ``dc`` ou ``dec``."""
    tipos = ("dc", "dec") if tipo in ("dc", "dec") else (tipo,)
    return " OR ".join(f"id:*{t}_{int(ano)}*_{int(numero):09d}*" for t in tipos)


def consulta_por_texto(texto: str, ano: int | None = None) -> str:
    frase = texto.replace('"', " ").strip()
    q = f'attr_content:"{frase}"'
    return f"{q} AND id:*_{int(ano)}*" if ano else q


def url_da_consulta(q: str, linhas: int = 20) -> str:
    return SILEG_SOLR + "?" + urlencode({"q": q, "rows": linhas, "fl": "id", "wt": "json",
                                         "sort": "id desc"})


def achados_do_indice(resposta: dict) -> list[dict]:
    """Os documentos que o índice devolveu, com tipo, data e número tirados do identificador."""
    saida = []
    for d in (resposta.get("response") or {}).get("docs") or []:
        ident = str(d.get("id") or "")
        m = _ID_SILEG.search(ident)
        if not m:
            continue
        s = m.group(2)
        try:
            data = date(int(s[:4]), int(s[4:6]), int(s[6:8])).isoformat()
        except ValueError:
            continue
        saida.append({"id": ident, "tipo": m.group(1).lower(), "data": data, "numero": int(m.group(3)),
                      "nome": re.sub(r"^.*/", "", ident).lstrip("./")})
    return saida


def procurar(alvo: dict, mapa: MapaLegal, *, ler_url=ler) -> dict:
    """Procura uma norma (ou um documento, como o QDD) no índice do Sileg.

    ``alvo`` traz ``tipo``, ``numero`` e ``ano`` (lei, lei complementar, decreto: o endereço
    oficial sai do padrão do Sileg e é lido para confirmar) ou ``texto`` (frase procurada no
    texto integral do Diário Oficial, com ``ano`` ou ``desde`` opcionais).
    """
    if alvo.get("texto"):
        q = consulta_por_texto(alvo["texto"], alvo.get("ano"))
        rotulo = alvo.get("rotulo") or f'"{alvo["texto"]}"' + (f" ({alvo['ano']})" if alvo.get("ano") else "")
    else:
        q = consulta_por_numero(alvo["tipo"], alvo["numero"], alvo["ano"])
        rotulo = alvo.get("rotulo") or f"{alvo['tipo']} {alvo['numero']}/{alvo['ano']}"
    item = {"alvo": rotulo, "consulta": q, "achada": 0, "id_sileg": None, "data": None, "url": None,
            "confirmada": 0, "erro": None}
    leitura = ler_url(url_da_consulta(q), fonte="Sileg")
    if not leitura.ok:
        item["erro"] = leitura.erro or "índice do Sileg não respondeu"
        return item
    try:
        resposta = json.loads(leitura.texto)
    except ValueError:
        item["erro"] = "resposta do índice não é JSON"
        return item
    achados = achados_do_indice(resposta)
    if alvo.get("desde"):
        achados = [a for a in achados if a["data"] >= f"{int(alvo['desde'])}-01-01"]
    if not alvo.get("texto"):
        achados = [a for a in achados if a["numero"] == int(alvo["numero"]) and a["tipo"] != "do"]
    if not achados:
        return item
    a = achados[0]
    item.update(achada=1, id_sileg=a["id"], data=a["data"])
    if alvo.get("texto") or a["tipo"] == "do":
        item["url"] = SILEG_PDF + a["nome"]
        item["confirmada"] = 1                 # o próprio índice é a prova: a edição tem a frase
        return item
    tipo_url = "dc" if a["tipo"] in ("dc", "dec") else a["tipo"]
    url = mapa.url_sileg(tipo_url, date.fromisoformat(a["data"]), a["numero"])
    item["url"] = url
    confirmacao = ler_norma_municipal(url, ler_url=ler_url)
    item["confirmada"] = confirmacao["ok"]
    if not confirmacao["ok"]:
        item["erro"] = f"achada no índice, mas o endereço não abriu: {confirmacao['erro']}"
    return item


PROCURAS = Path(__file__).resolve().parent.parent / "legal" / "procuras.yml"


def carregar_procuras(caminho: Path | None = None) -> list[dict]:
    """A lista do que procurar no Sileg: normas não localizadas do mapa e documentos (QDD)."""
    bruto = yaml.safe_load(Path(caminho or PROCURAS).read_text(encoding="utf-8")) or {}
    return list(bruto.get("procuras") or [])
