"""Transferegov: as transferências especiais (emendas Pix), o fundo a fundo e os TED do Município.

A API do Transferegov (``api.transferegov.gestao.gov.br``) é um PostgREST por módulo:
``transferenciasespeciais/``, ``fundoafundo/`` e ``ted/``. A raiz de cada módulo devolve a descrição
OpenAPI com as tabelas e as colunas; cada tabela se lê com filtros na URL
(``?cnpj_beneficiario_plano_acao=eq.<cnpj>``), em páginas de ``limit`` e ``offset``.

Das transferências especiais interessa o plano de ação (``plano_acao_especial``): o beneficiário, a
emenda e o parlamentar, e os valores de custeio e de investimento. É com eles que se mede a regra
de que pelo menos 70% de cada transferência especial vai para despesa de capital (CF, art. 166-A,
§ 5º). Dos outros módulos, as tabelas que têm uma coluna de CNPJ são lidas pelo CNPJ dos entes do
Município e guardadas em forma genérica (chave, ano, valor, situação e o registro inteiro).
"""

from __future__ import annotations

import json
import urllib.parse

from . import comum_federal as cf

BASE = "https://api.transferegov.gestao.gov.br/"
MODULOS = ("transferenciasespeciais", "fundoafundo", "ted")
ESPECIAIS = "transferenciasespeciais"
PLANOS = "plano_acao_especial"
COLUNA_CNPJ_PLANO = "cnpj_beneficiario_plano_acao"
PAGINA = 1000

# Quando a raiz não responde, as tabelas e colunas de CNPJ mais prováveis de cada módulo.
PADRAO = {
    "transferenciasespeciais": {PLANOS: COLUNA_CNPJ_PLANO},
    "fundoafundo": {"plano_acao": "cnpj_beneficiario", "repasse": "cnpj_beneficiario"},
    "ted": {"plano_acao": "cnpj_beneficiario", "termo_execucao": "cnpj_beneficiario"},
}


def url_raiz(modulo: str) -> str:
    return f"{BASE}{modulo}/"


def url_tabela(modulo: str, tabela: str, filtros: dict[str, str] | None = None, *,
               limite: int = PAGINA, offset: int = 0, ordem: str | None = None) -> str:
    """Endereço PostgREST de uma tabela; ``filtros`` já com o operador (``{"ano": "eq.2025"}``)."""
    params = dict(filtros or {})
    params["limit"] = str(limite)
    params["offset"] = str(offset)
    if ordem:
        params["order"] = ordem
    return f"{BASE}{modulo}/{tabela}?" + urllib.parse.urlencode(params, safe=".,()")


def tabelas_com_cnpj(conteudo: bytes) -> dict[str, str]:
    """Da descrição OpenAPI (Swagger 2 do PostgREST ou OpenAPI 3) da raiz de um módulo: cada tabela
    que tem coluna de CNPJ e a coluna (a do beneficiário, se houver mais de uma)."""
    obj = cf.json_ou_none(conteudo)
    if not isinstance(obj, dict):
        raise ValueError("a raiz do módulo não devolveu a descrição OpenAPI")
    definicoes = obj.get("definitions") or (obj.get("components") or {}).get("schemas") or {}
    if not definicoes:
        raise ValueError("a descrição OpenAPI não traz as tabelas")
    saida = {}
    for tabela, desc in definicoes.items():
        colunas = list((desc or {}).get("properties", {}))
        cnpjs = [c for c in colunas if "cnpj" in c.lower()]
        if not cnpjs:
            continue
        preferida = next((c for c in cnpjs if "benefici" in c.lower() or "recebedor" in c.lower()
                          or "favorecido" in c.lower()), cnpjs[0])
        saida[tabela] = preferida
    return saida


def pagina(conteudo: bytes) -> list[dict]:
    """Os registros de uma página PostgREST (sempre uma lista JSON). Levanta ``ValueError`` se não for."""
    obj = cf.json_ou_none(conteudo)
    if not isinstance(obj, list) or not all(isinstance(x, dict) for x in obj):
        raise ValueError("a resposta não é a lista de registros do PostgREST")
    return obj


def plano(registro: dict) -> dict | None:
    """Um plano de ação de transferência especial reduzido ao que a regra dos 70% precisa."""
    ident = cf.campo(registro, "id_plano_acao", "id", contem=("idplano",))
    if ident is None:
        return None
    custeio = cf.numero(cf.campo(registro, "valor_custeio_plano_acao", "valor_custeio",
                                 contem=("custeio",))) or 0.0
    investimento = cf.numero(cf.campo(registro, "valor_investimento_plano_acao", "valor_investimento",
                                      "valor_capital", contem=("investimento", "capital"))) or 0.0
    emenda = " ".join(str(x) for x in (
        cf.campo(registro, "numero_emenda_parlamentar_plano_acao", contem=("numeroemenda",)),
        cf.campo(registro, "ano_emenda_parlamentar_plano_acao", contem=("anoemenda",))) if x)
    ano = cf.campo(registro, "ano_plano_acao", "ano", contem=("anoplano",))
    return {
        "id_plano": str(ident),
        "codigo": str(cf.campo(registro, "codigo_plano_acao", "codigo", contem=("codigoplano",)) or ""),
        "ano": int(ano) if str(ano or "").isdigit() else None,
        "situacao": str(cf.campo(registro, "situacao_plano_acao", "situacao", contem=("situacao",)) or ""),
        "cnpj": cf.digitos(cf.campo(registro, COLUNA_CNPJ_PLANO, "cnpj_beneficiario", contem=("cnpj",))),
        "beneficiario": str(cf.campo(registro, "nome_beneficiario_plano_acao", "nome_beneficiario",
                                     contem=("nomebenefici",)) or ""),
        "parlamentar": str(cf.campo(registro, "nome_parlamentar_emenda_plano_acao", "nome_parlamentar",
                                    contem=("parlamentar",)) or ""),
        "emenda": emenda,
        "custeio": round(custeio, 2),
        "investimento": round(investimento, 2),
        "total": round(custeio + investimento, 2),
    }


def generico(modulo: str, tabela: str, registro: dict) -> dict:
    """Um registro de qualquer tabela, com a chave, o ano, o CNPJ, o valor e o registro inteiro."""
    ident = cf.campo(registro, "id", contem=("id",))
    ano = cf.campo(registro, "ano", contem=("ano",))
    valor = cf.numero(cf.campo(registro, "valor_total", "valor", contem=("valortotal", "valor")))
    return {
        "modulo": modulo, "tabela": tabela,
        "chave": str(ident) if ident is not None else json.dumps(registro, sort_keys=True)[:200],
        "ano": int(ano) if str(ano or "").isdigit() else None,
        "cnpj": cf.digitos(cf.campo(registro, contem=("cnpj",))),
        "valor": valor,
        "situacao": str(cf.campo(registro, "situacao", contem=("situacao",)) or ""),
        "descricao": str(cf.campo(registro, "objeto", "descricao", "nome", contem=("objeto", "descricao"))
                         or ""),
        "json": json.dumps(registro, ensure_ascii=False, sort_keys=True),
    }
