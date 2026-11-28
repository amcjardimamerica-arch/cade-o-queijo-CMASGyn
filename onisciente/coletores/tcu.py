"""TCU: os acórdãos do Tribunal de Contas da União que tratam do Município de Goiânia.

O TCU publica os acórdãos em dados abertos (``dados-abertos.apps.tcu.gov.br/api/acordao/
recupera-acordaos``, em páginas de ``inicio`` e ``quantidade``) e na pesquisa de jurisprudência
(``pesquisa.apps.tcu.gov.br``, com termo de busca). Os dois devolvem JSON com número, ano,
colegiado, data da sessão, relator, processo, título, sumário e o endereço do acórdão; os nomes dos
campos são achados pelo sentido. Só ficam os acórdãos que citam Goiânia (sem confundir com
Aparecida de Goiânia), porque são eles que tocam o dinheiro do Município: convênios, fundo a fundo
da saúde, FNDE.

A sondagem de 27/11/2026 leu a pesquisa (``documentosResumidos``) de verdade: um objeto com
``quantidadeEncontrada``, ``inicio`` e ``documentos``, cada documento com ``KEY``, ``TIPO``, ``TITULO``,
``NUMACORDAO``, ``ANOACORDAO``, ``COLEGIADO``, ``DATASESSAO`` (dd/mm/aaaa), ``PROC`` (o número do processo
só com dígitos), ``RELATOR``, ``SUMARIO`` (ausente nos acórdãos de relação), ``URLARQUIVOPDF`` e os
trechos em que o termo aparece (``FRAGMENTO1``, ``FRAGMENTO2``, com ``<em>`` em volta do termo). A resposta
real está em ``testes/dados/federais/tcu_pesquisa_real.json``. Os dados abertos deram conexão
recusada na sondagem e seguem como segunda via.

Na pesquisa, o termo Goiânia casa também com Aparecida de Goiânia: por isso a menção é conferida
no título, no sumário e nos trechos. Só quando o documento não traz texto nenhum para conferir é
que vale o casamento da própria pesquisa (parâmetro restritivo: na dúvida, o acórdão fica).
"""

from __future__ import annotations

import re
import urllib.parse

from . import comum_federal as cf

DADOS_ABERTOS = "https://dados-abertos.apps.tcu.gov.br/api/acordao/recupera-acordaos"
PESQUISA = "https://pesquisa.apps.tcu.gov.br/rest/publico/base/acordao-completo/documentosResumidos"
QUANTIDADE = 100
# A pesquisa responde 100 por vez na primeira página, mas a seguinte (inicio=100) caiu sem resposta duas
# vezes na sondagem (conexão encerrada); com 50 por página, inicio=50 veio inteira (50 acórdãos, 70 KB).
QUANTIDADE_PESQUISA = 50
# Rodada 6: inicio=100 encerrou a conexão também com 50 por página, e inicio=50 veio de novo: a pesquisa
# não passa dos 100 primeiros resultados.
LIMITE_PESQUISA = 100

GOIANIA = re.compile(r"(?<!APARECIDA DE )\bGOIANIA\b")


def url_dados_abertos(inicio: int = 0, quantidade: int = QUANTIDADE) -> str:
    return f"{DADOS_ABERTOS}?inicio={inicio}&quantidade={quantidade}"


def url_pesquisa(termo: str = "Goiânia", inicio: int = 0, quantidade: int = QUANTIDADE_PESQUISA) -> str:
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


def processo_tc(valor) -> str:
    """O número do processo no formato do TCU (TC 022.670/2026-2) quando vem só com dígitos."""
    d = cf.digitos(valor)
    if 9 <= len(d) <= 11 and str(valor).strip().isdigit():
        d = d.zfill(11)
        return f"TC {d[:3]}.{d[3:6]}/{d[6:10]}-{d[10]}"
    return _limpo(valor)


def trechos(registro: dict) -> str:
    """Os trechos da pesquisa em que o termo aparece (FRAGMENTO1, FRAGMENTO2...), sem marcação."""
    partes = [_limpo(v) for k, v in sorted(registro.items()) if cf.norm(k).startswith("FRAGMENTO") and v]
    return " ".join(dict.fromkeys(p for p in partes if p))


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
    achados = trechos(registro)
    if achados:
        entidade = (entidade + " " if entidade else "") + f"Trechos: {achados}"
    return {
        "tribunal": "TCU",
        "chave": str(chave),
        "numero": str(numero),
        "ano": int(ano) if str(ano or "").isdigit() else None,
        "colegiado": colegiado,
        "data": cf.data(cf.campo(registro, "dataSessao", "DATASESSAO", "data", contem=("datasessao",))),
        "relator": _limpo(cf.campo(registro, "relator", "RELATOR")),
        "processo": processo_tc(cf.campo(registro, "processo", "PROC", "numeroProcesso", contem=("processo",))),
        "tipo": _limpo(cf.campo(registro, "tipo", "TIPOPROCESSO", contem=("tipoprocesso",))) or "Acórdão",
        "titulo": titulo or f"Acórdão {numero}/{ano}",
        "sumario": (sumario + (" " + entidade if entidade else ""))[:4000],
        "url": str(cf.campo(registro, "urlAcordao", "URLARQUIVOPDF", "urlArquivoPdf", "urlArquivo", "url",
                            contem=("url",)) or ""),
    }


def ler(conteudo: bytes, pesquisa: bool = False) -> list[dict]:
    """Todos os acórdãos da página (os que citam Goiânia ganham ``sobre_goiania``). Na ``pesquisa``,
    o documento sem título, sumário nem trecho que permita conferir fica como achado pela busca.
    Levanta ``ValueError`` se a resposta não é a lista de acórdãos."""
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
            texto = " ".join((a["titulo"], a["sumario"]))
            a["sobre_goiania"] = int(sobre(texto))
            if pesquisa and not a["sobre_goiania"] and not trechos(r) and not cf.campo(r, "sumario", "SUMARIO"):
                a["sobre_goiania"] = 1
            saida.append(a)
    if regs and not saida:
        raise ValueError("os registros do TCU não têm número de acórdão reconhecível")
    return saida
