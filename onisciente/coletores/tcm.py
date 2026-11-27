"""TCM-GO: as decisões do Tribunal de Contas dos Municípios de Goiás sobre Goiânia.

O TCM-GO julga as contas do Prefeito (parecer prévio), as contas de gestão dos ordenadores e as
denúncias e representações sobre licitações e contratos. As decisões saem como acórdãos (``AC``),
resoluções (``RC``, ``RS``) e pareceres prévios, publicadas no portal e no Diário Oficial de Contas.

Nenhuma API pública foi confirmada. O coletor lê os candidatos de ``CANDIDATOS`` (a pesquisa de
jurisprudência e a busca do portal, com o termo Goiânia) e aceita JSON ou página HTML: na página,
cada menção a um acórdão, resolução ou parecer prévio com número e ano vira uma decisão, com o
trecho em volta como sumário e o link mais próximo como endereço.
"""

from __future__ import annotations

import html as html_lib
import re
import urllib.parse

from . import comum_federal as cf
from .tcu import sobre

PORTAL = "https://www.tcmgo.tc.br/"

CANDIDATOS = (
    PORTAL + "pesquisaJurisprudencia/rest/pesquisa?termo={termo}&pagina={pagina}",
    PORTAL + "site/jurisprudencia/?pesquisa={termo}&pagina={pagina}",
    PORTAL + "site/?s={termo}&paged={pagina}",
)

DECISAO = re.compile(
    r"(?i)\b(AC(?:[OÓ]RD[AÃ]O)?(?:\s*-\s*[A-Z]{2,4})?|RESOLU[CÇ][AÃ]O(?:\s*-\s*[A-Z]{2,4})?|R[CS](?:\s*-\s*[A-Z]{2,4})?"
    r"|PARECER\s+PR[EÉ]VIO)\s*(?:N[ºo°.]*\s*)?(\d{1,6})\s*/\s*(\d{4})")
PROCESSO = re.compile(r"(?i)processo\s*(?:n[ºo°.]*\s*)?([\d.]{3,}\s*/\s*\d{2,4})")


def urls(termo: str = "Goiânia", pagina: int = 1) -> list[str]:
    return [c.format(termo=urllib.parse.quote(termo), pagina=pagina) for c in CANDIDATOS]


def _tipo(rotulo: str) -> str:
    r = cf.norm(rotulo)
    if r.startswith("PARECER"):
        return "Parecer prévio"
    if r.startswith(("RESOLUC", "RC", "RS")):
        return "Resolução"
    return "Acórdão"


def _decisao(tipo: str, numero: str, ano: str, trecho: str, url: str) -> dict:
    proc = PROCESSO.search(trecho)
    return {
        "tribunal": "TCM-GO", "chave": f"TCMGO-{cf.chave(tipo)}-{int(numero)}-{ano}",
        "numero": str(int(numero)), "ano": int(ano), "colegiado": "", "data": None, "relator": "",
        "processo": re.sub(r"\s+", "", proc.group(1)) if proc else "", "tipo": tipo,
        "titulo": f"{tipo} {int(numero)}/{ano}", "sumario": trecho[:4000], "url": url,
        "sobre_goiania": int(sobre(trecho)),
    }


def _de_json(regs: list[dict]) -> list[dict]:
    saida = []
    for r in regs:
        texto = " ".join(str(v) for v in r.values() if isinstance(v, (str, int)))
        m = DECISAO.search(texto)
        numero = cf.campo(r, "numero", "numeroDecisao", contem=("numero",))
        ano = cf.campo(r, "ano", "anoDecisao", contem=("ano",))
        if m:
            tipo, numero, ano = _tipo(m.group(1)), m.group(2), m.group(3)
        else:
            if not (str(numero or "").isdigit() and str(ano or "").isdigit()):
                continue
            tipo = _tipo(str(cf.campo(r, "tipo", "tipoDecisao") or "Acórdão"))
        trecho = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(cf.campo(
            r, "ementa", "sumario", "resumo", "assunto", "texto", contem=("ementa",)) or texto)))
        d = _decisao(tipo, str(numero), str(ano), trecho, str(cf.campo(r, "url", "link", contem=("url",)) or ""))
        d["data"] = cf.data(cf.campo(r, "data", "dataSessao", "dataPublicacao", contem=("data",)))
        d["relator"] = str(cf.campo(r, "relator", contem=("relator",)) or "")
        saida.append(d)
    return saida


def _de_html(pagina: str, base: str) -> list[dict]:
    """Cada menção a uma decisão vira um registro: o trecho vai da menção até a próxima (no máximo
    800 caracteres), e o endereço é o do link que contém a menção ou o último antes dela."""
    texto = html_lib.unescape(re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", pagina))
    # As tags viram espaços do mesmo tamanho: as posições do texto continuam as da página.
    plano = re.sub(r"<[^>]+>", lambda t: " " * len(t.group(0)), texto)
    ancoras = [(m.start(), m.group(1)) for m in re.finditer(r"""(?i)<a[^>]+href=["']([^"'#]+)["']""", texto)]
    achados = list(DECISAO.finditer(plano))
    vistos: dict[str, dict] = {}
    for n, m in enumerate(achados):
        fim = achados[n + 1].start() if n + 1 < len(achados) else len(plano)
        trecho = re.sub(r"\s+", " ", plano[m.start():min(fim, m.start() + 800)]).strip()
        antes = [h for pos, h in ancoras if pos <= m.start() and m.start() - pos < 600]
        url = antes[-1] if antes else ""
        if url and not url.startswith("http"):
            url = urllib.parse.urljoin(base, url)
        d = _decisao(_tipo(m.group(1)), m.group(2), m.group(3), trecho, url)
        vistos.setdefault(d["chave"], d)
    return list(vistos.values())


def ler(conteudo: bytes, base: str = PORTAL) -> list[dict]:
    """As decisões achadas numa resposta (JSON ou HTML). Levanta ``ValueError`` se a resposta não é
    nenhum dos dois; lista vazia é busca sem resultado."""
    obj = cf.json_ou_none(conteudo)
    if obj is not None:
        regs = cf.registros_json(obj)
        if regs is None:
            raise ValueError("o JSON do TCM-GO não traz lista de decisões")
        return _de_json(regs)
    texto = cf.decodificar(conteudo)
    if "<" not in texto[:2000]:
        raise ValueError("a resposta do TCM-GO não é JSON nem página")
    return _de_html(texto, base)
