"""FNS: os repasses fundo a fundo do Fundo Nacional de Saúde ao Município, pagamento a pagamento.

O FNS é a via do próprio Ministério da Saúde: diz o que pagou ao Fundo Municipal de Saúde, em que
data, por bloco e programa, com banco, agência, conta e ordem bancária. É a terceira via do SUS
fundo a fundo, ao lado do SIAFI (Portal da Transparência, tabela ``transferencias_federais``, ações
8585, 219A, 00UC...) e do que o Município declara no RREO Anexo 12 (SIOPS, "Provenientes da União")
e na matriz de saldos contábeis.

A consulta pública (``consultafns.saude.gov.br``) é um aplicativo que chama uma API JSON. O endereço
exato da API ainda não foi confirmado pela sondagem; por isso o coletor tenta, na ordem, os modelos
de ``MODELOS`` e guarda qual respondeu. Os nomes dos campos são achados pelo sentido (``data_repasse``,
``dataPagamento``, ``valor_liquido``...), nunca pela posição.
"""

from __future__ import annotations

import math

from . import comum_federal as cf

API = "https://apifns.saude.gov.br/api/"
CONSULTA = "https://consultafns.saude.gov.br/recursos/"

# Modelos de endereço por ordem de preferência. {ibge6}: código IBGE de 6 dígitos (o FNS usa 6);
# {ibge}: o de 7; {ano}; {pagina}.
MODELOS = (
    API + "v1/repasses?municipio_ibge={ibge6}&ano={ano}&pagina={pagina}&tamanho=1000",
    API + "repasses?municipio_ibge={ibge6}&ano={ano}&pagina={pagina}&tamanho=1000",
    API + "v1/pagamentos?municipio_ibge={ibge6}&ano={ano}&pagina={pagina}&tamanho=1000",
    API + "repasses-fundo-a-fundo?municipio_ibge={ibge6}&ano={ano}&page={pagina}&size=1000",
    CONSULTA + "repasse-dia/detalhar-pagamento?codigoMunicipio={ibge6}&ano={ano}&page={pagina}&count=1000",
    CONSULTA + "consolidado/municipio?codigoMunicipio={ibge6}&ano={ano}",
)


def url(modelo: str, ibge: int | str, ano: int, pagina: int = 1) -> str:
    ibge = str(ibge)
    return modelo.format(ibge6=ibge[:6], ibge=ibge, ano=ano, pagina=pagina)


def _texto(v) -> str:
    return "" if v is None else str(v).strip()


def repasse(registro: dict) -> dict | None:
    """Um pagamento do FNS reduzido aos campos do banco. None se não tiver data nem valor."""
    data = cf.data(cf.campo(registro, "data_repasse", "dataRepasse", "data_pagamento", "dataPagamento",
                            "dtPagamento", "dt_pagamento", "data_ob", "dataOb", "data",
                            contem=("datapag", "datarep", "dataob")))
    competencia = cf.mes_de(cf.campo(registro, "competencia", "mes_competencia", "nuCompetencia",
                                     "mesAnoCompetencia", contem=("competencia",)))
    liquido = cf.numero(cf.campo(registro, "valor_liquido", "valorLiquido", "vl_liquido", "vlLiquido",
                                 "valor", "vlPagamento", "valor_pago", "valorPago", "valor_total",
                                 contem=("liquido",)))
    bruto = cf.numero(cf.campo(registro, "valor_bruto", "valorBruto", "vl_bruto", "vlBruto",
                               contem=("bruto",)))
    desconto = cf.numero(cf.campo(registro, "desconto", "valor_desconto", "valorDesconto", "vl_desconto",
                                  contem=("desconto",)))
    if liquido is None and bruto is not None:
        liquido = bruto - (desconto or 0.0)
    if data is None and competencia is None or liquido is None:
        return None
    return {
        "mes": (data or "")[:7] or competencia,
        "data": data,
        "competencia": competencia,
        "bloco": _texto(cf.campo(registro, "bloco", "bloco_financiamento", "noBloco", "dsBloco",
                                 contem=("bloco",))),
        "programa": _texto(cf.campo(registro, "programa", "componente", "acao", "acao_detalhada", "noAcao",
                                    "dsAcao", "noPrograma", "dsPrograma", contem=("programa", "acao"))),
        "cnpj": cf.digitos(cf.campo(registro, "cnpj", "cnpj_favorecido", "nuCnpj", "cpfCnpj",
                                    contem=("cnpj",))),
        "favorecido": _texto(cf.campo(registro, "favorecido", "entidade", "noEntidade", "nome_favorecido",
                                      "fundo", contem=("favorecido", "entidade"))),
        "valor_bruto": bruto if bruto is not None else liquido + (desconto or 0.0),
        "desconto": desconto or 0.0,
        "valor_liquido": round(liquido, 2),
        "banco": _texto(cf.campo(registro, "banco", "codigo_banco", "nuBanco", "coBanco", contem=("banco",))),
        "agencia": _texto(cf.campo(registro, "agencia", "nuAgencia", "coAgencia", contem=("agencia",))),
        "conta": _texto(cf.campo(registro, "conta", "conta_corrente", "nuConta", "contaCorrente",
                                 contem=("conta",))),
        "ordem_bancaria": _texto(cf.campo(registro, "ordem_bancaria", "ordemBancaria", "ob", "nuOb",
                                          "nuOrdemBancaria", contem=("ordem",))),
        "situacao": _texto(cf.campo(registro, "situacao", "status", "dsSituacao", contem=("situacao",))),
    }


def ler(conteudo: bytes) -> tuple[list[dict], bool]:
    """Os repasses de uma página da API e se há página seguinte.

    Levanta ``ValueError`` se a resposta não é JSON nem CSV de repasses (formato mudado ou página
    de erro no lugar do dado). Lista vazia é resposta válida: o ano ainda sem pagamento.
    """
    if cf.parece_pagina(conteudo):
        raise ValueError("a fonte devolveu uma página HTML, não os repasses")
    obj = cf.json_ou_none(conteudo)
    if obj is not None:
        brutos = cf.registros_json(obj)
        if brutos is None:
            raise ValueError("o JSON não traz lista de repasses")
        mais = _ha_mais(obj, len(brutos))
    else:
        brutos = cf.linhas_csv(conteudo)
        if not brutos:
            raise ValueError("a resposta não é JSON nem CSV")
        mais = False
    linhas = [r for r in (repasse(b) for b in brutos) if r]
    if brutos and not linhas:
        raise ValueError("os registros não têm data e valor reconhecíveis")
    return linhas, mais


def _ha_mais(obj, recebidos: int) -> bool:
    if not isinstance(obj, dict) or recebidos == 0:
        return False
    if obj.get("last") is False or obj.get("hasNext") is True or obj.get("proximaPagina"):
        return True
    total_pag = cf.campo(obj, "totalPages", "total_paginas", "totalPaginas")
    atual = cf.campo(obj, "number", "pagina", "page", "paginaAtual")
    if total_pag is not None and atual is not None:
        base = 0 if "number" in obj else 1          # Spring conta a partir de 0
        return int(atual) - base + 1 < int(total_pag)
    total = cf.campo(obj, "totalElements", "total", "totalRegistros", "count")
    tamanho = cf.campo(obj, "size", "tamanho", "pageSize")
    if total is not None and tamanho and atual is not None:
        return int(atual) < math.ceil(int(total) / int(tamanho))
    return False
