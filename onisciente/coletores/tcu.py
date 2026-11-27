"""TCU: os acórdãos do Tribunal de Contas da União que tratam do Município de Goiânia.

O TCU publica os acórdãos em dados abertos (``dados-abertos.apps.tcu.gov.br/api/acordao/
recupera-acordaos``, em páginas de ``inicio`` e ``quantidade``) e na pesquisa de jurisprudência
(``pesquisa.apps.tcu.gov.br``, com termo de busca). Os dois devolvem JSON com número, ano,
colegiado, data da sessão, relator, processo, título, sumário e o endereço do acórdão; os nomes dos
campos são achados pelo sentido. Só ficam os acórdãos que citam Goiânia (sem confundir com
Aparecida de Goiânia), porque são eles que tocam o dinheiro do Município: convênios, fundo a fundo
da saúde, FNDE.
"""

from __future__ import annotations

import re
import urllib.parse

from . import comum_federal as cf

DADOS_ABERTOS = "https://dados-abertos.apps.tcu.gov.br/api/acordao/recupera-acordaos"
PESQUISA = "https://pesquisa.apps.tcu.gov.br/rest/publico/base/acordao-completo/documentosResumidos"
QUANTIDADE = 100

GOIANIA = re.compile(r"(?<!APARECIDA DE )\bGOIANIA\b")


def url_dados_abertos(inicio: int = 0, quantidade: int = QUANTIDADE) -> str:
    return f"{DADOS_ABERTOS}?inicio={inicio}&quantidade={quantidade}"


def url_pesquisa(termo: str = "Goiânia", inicio: int = 0, quantidade: int = QUANTIDADE) -> str:
    params = {"termo": f'"{termo}"', "ordenacao": "DTRELEVANCIA desc, NUMACORDAOINT desc",
              "quantidade": quantidade, "inicio": inicio, "sinonimos": "true"}
    return PESQUISA + "?" + urllib.parse.urlencode(params)


def sobre(texto: str, municipio: str = "GOIANIA") -> bool:
    t = cf.norm(texto)
    if municipio == "GOIANIA":
        return bool(GOIANIA.search(t))
    return municipio in t


def _limpo(v) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(v or ""))).strip()


def acordao(registro: dict) -> dict | None:
    numero = cf.campo(registro, "numeroAcordao", "NUMACORDAO", "numero", "num_acordao", contem=("numacordao",))
    ano = cf.campo(registro, "anoAcordao", "ANOACORDAO", "ano", contem=("anoacordao",))
    titulo = _limpo(cf.campo(registro, "titulo", "TITULO", "tituloAcordao"))
    if numero is None and (m := re.search(r"(\d{1,5})\s*/\s*(\d{4})", titulo)):
        numero, ano = m.group(1), m.group(2)
    if numero is None:
        return None
    colegiado = _limpo(cf.campo(registro, "colegiado", "COLEGIADO"))
    chave = cf.campo(registro, "key", "KEY", "chave", "id") or f"ACORDAO-COMPLETO-{numero}-{ano}-{colegiado}"
    sumario = _limpo(cf.campo(registro, "sumario", "SUMARIO", "ementa", "assunto", "ASSUNTO"))
    entidade = _limpo(cf.campo(registro, "entidade", "ENTIDADE", "interessados", "INTERESSADOS"))
    return {
        "tribunal": "TCU",
        "chave": str(chave),
        "numero": str(numero),
        "ano": int(ano) if str(ano or "").isdigit() else None,
        "colegiado": colegiado,
        "data": cf.data(cf.campo(registro, "dataSessao", "DATASESSAO", "data", contem=("datasessao",))),
        "relator": _limpo(cf.campo(registro, "relator", "RELATOR")),
        "processo": _limpo(cf.campo(registro, "processo", "PROC", "numeroProcesso", contem=("processo",))),
        "tipo": _limpo(cf.campo(registro, "tipo", "TIPOPROCESSO", contem=("tipoprocesso",))) or "Acórdão",
        "titulo": titulo or f"Acórdão {numero}/{ano}",
        "sumario": (sumario + (" " + entidade if entidade else ""))[:4000],
        "url": str(cf.campo(registro, "urlAcordao", "urlArquivo", "urlArquivoPdf", "url", contem=("url",)) or ""),
    }


def ler(conteudo: bytes) -> list[dict]:
    """Todos os acórdãos da página (os que citam Goiânia ganham ``sobre_goiania``). Levanta
    ``ValueError`` se a resposta não é a lista de acórdãos."""
    obj = cf.json_ou_none(conteudo)
    if obj is None:
        raise ValueError("a resposta do TCU não é JSON")
    regs = cf.registros_json(obj)
    if regs is None:
        raise ValueError("o JSON do TCU não traz lista de acórdãos")
    saida = []
    for r in regs:
        a = acordao(r)
        if a:
            a["sobre_goiania"] = int(sobre(" ".join((a["titulo"], a["sumario"]))))
            saida.append(a)
    if regs and not saida:
        raise ValueError("os registros do TCU não têm número de acórdão reconhecível")
    return saida
