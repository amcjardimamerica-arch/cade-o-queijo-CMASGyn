"""FNS: os repasses fundo a fundo do Fundo Nacional de Saúde ao Município, pagamento a pagamento.

O FNS é a via do próprio Ministério da Saúde: diz o que pagou ao Fundo Municipal de Saúde, em que
data, por bloco e programa, com banco, agência, conta e ordem bancária. É a terceira via do SUS
fundo a fundo, ao lado do SIAFI (Portal da Transparência, tabela ``transferencias_federais``, ações
8585, 219A, 00UC...) e do que o Município declara no RREO Anexo 12 (SIOPS, "Provenientes da União")
e na matriz de saldos contábeis.

A consulta pública (``consultafns.saude.gov.br``) é um aplicativo AngularJS (versão 1.50.9) que chama
uma API JSON em ``/recursos/``. O endereço exato ainda não foi confirmado; por isso o coletor tenta, na
ordem, os modelos de ``MODELOS`` e guarda qual respondeu. Os nomes dos campos são achados pelo
sentido (``data_repasse``, ``dataPagamento``, ``valor_liquido``...), nunca pela posição.

Sondagem de 27/11/2026:
- ``apifns.saude.gov.br`` não existe no DNS (todas as rotas). Os quatro modelos desse host continuam
  na lista só porque a trava antiga do motor os cita; falham na hora, sem custo;
- ``/recursos/repasse-dia/detalhar-pagamento`` respondeu HTTP 400 com ``codigoMunicipio`` e ``ano``: o
  serviço existe, mas pede outros parâmetros. Os novos modelos mandam o período em datas;
- ``/recursos/consolidado/municipio`` deu 404 e saiu da lista;
- ``app/app.js`` e ``app/main.js`` responderam, mas não trazem os serviços: ``app.js`` só configura
  a rota padrão ``repasse-dia``, o login (``/oauth/token``, ``/api/autenticacao/usuario``) e um cache de
  10 minutos; ``main.js`` só carrega ``controllers/portalController``, ``services/utilService`` e as
  bibliotecas. Os serviços com os endereços da API estão nesses arquivos e nas páginas de cada rota,
  que a próxima sondagem lê (chave ``d1_fns``).

Sondagem de 28/11/2026 (run 46085340244):
- os três modelos do ``consultafns`` com o período em datas deram 400 ou 404, e o ``detalhe-acao`` deu
  400 (o corpo é a página de erro padrão, sem dizer o parâmetro que falta);
- o ``repasseDiaService.js`` diz o serviço de verdade: o recurso ``recursos/repasse-dia`` com
  ``consultar`` (ano, mês e dia), ``detalhar-pagamento-dia``, ``detalhar-pagamento-dia-final``,
  ``detalhar-pagamento``, ``detalhar-pagamento-emenda``, ``recuperar-data-ultimo-pagamento`` (sem
  parâmetro) e três planilhas por POST. É um serviço nacional por dia, não por Município: o filtro do
  Município fica nas páginas ``detalhada`` e ``consolidada`` do mesmo aplicativo, cujos serviços a
  próxima sondagem lê. ``servicos_do_js`` tira os endereços de qualquer serviço desses;
- ``recursos/municipios/uf/GO`` é JSON real (``coMunicipioIbge`` de 6 dígitos): ``municipios``.
"""

from __future__ import annotations

import json
import math
import re
import urllib.parse

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
    # consultafns: modelos da segunda rodada. Deram 400 ou 404 na sondagem de 28/11 (ver o topo);
    # ficam enquanto a trava da segunda rodada os pede e falham sem custo.
    CONSULTA + "repasse-dia/detalhar-pagamento?codigoMunicipio={ibge6}&dataPagamentoInicial={inicio}"
               "&dataPagamentoFinal={fim}&page={pagina}&count=1000",
    CONSULTA + "repasse-dia/detalhar-pagamento?municipio={ibge6}&dataInicial={inicio}&dataFinal={fim}"
               "&page={pagina}&count=1000",
    CONSULTA + "repasse-dia/consolidado?codigoMunicipio={ibge6}&dataPagamentoInicial={inicio}"
               "&dataPagamentoFinal={fim}&page={pagina}&count=1000",
    CONSULTA + "consulta-detalhada/detalhe-acao?codigoMunicipio={ibge6}&ano={ano}&page={pagina}&count=1000",
)
# Lidos na sondagem e descartados (404 ou parâmetros recusados).
DESCARTADOS = (
    CONSULTA + "repasse-dia/detalhar-pagamento?codigoMunicipio={ibge6}&ano={ano}&page={pagina}&count=1000",
    CONSULTA + "consolidado/municipio?codigoMunicipio={ibge6}&ano={ano}",
)


# O serviço do "repasse dia" (repasseDiaService.js, lido em 28/11/2026).
REPASSE_DIA = CONSULTA + "repasse-dia/"
PAGINAS_DO_APP = ("detalhada", "consolidada", "entidade", "convenios", "detalhada-multisselecao", "saldo-mac")

_RECURSO = re.compile(r"this\.resource\s*=\s*'([^']+)'")
_METODO = re.compile(r"\.prototype\.(\w+)\s*=\s*function\s*\(([^)]*)\)\s*\{(.*?)\n\t\t\}", re.DOTALL)


def servicos_do_js(js: str) -> dict[str, tuple[str, str]]:
    """Os endereços que um serviço AngularJS do consultafns chama: {função: (método, caminho)}.

    O caminho é o recurso (``this.resource``) mais o sufixo; métodos comentados não contam."""
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.DOTALL)
    recurso = _RECURSO.search(js)
    if not recurso:
        return {}
    saida = {}
    for nome, _params, corpo in _METODO.findall(js):
        sufixo = re.search(r"this\.resource\s*\+\s*'([^']+)'", corpo)
        if not sufixo:
            continue
        metodo = "POST" if re.search(r"\.post\s*\(|customPOST", corpo) else "GET"
        saida[nome] = (metodo, recurso.group(1) + sufixo.group(1))
    return saida


def url_repasse_dia(servico: str, **params) -> str:
    """Um endereço do serviço do repasse dia (``consultar``, ``detalhar-pagamento-dia``...)."""
    base = REPASSE_DIA + servico.strip("/")
    limpos = {k: v for k, v in params.items() if v is not None}
    return base + ("?" + urllib.parse.urlencode(limpos) if limpos else "")


def municipios(conteudo: bytes) -> dict[str, str]:
    """``recursos/municipios/uf/XX``: {código IBGE de 6 dígitos: nome}."""
    try:
        obj = json.loads(conteudo)
    except ValueError as e:
        raise ValueError(f"municípios do FNS não são JSON: {e}") from e
    lista = obj.get("resultado") if isinstance(obj, dict) else None
    if not isinstance(lista, list):
        raise ValueError("municípios do FNS sem a lista 'resultado'")  # noqa: TRY004 (formato, como os outros leitores)
    return {str(m["coMunicipioIbge"]): m.get("noMunicipio", "") for m in lista
            if isinstance(m, dict) and m.get("coMunicipioIbge")}


def url(modelo: str, ibge: int | str, ano: int, pagina: int = 1) -> str:
    ibge = str(ibge)
    return modelo.format(ibge6=ibge[:6], ibge=ibge, ano=ano, pagina=pagina,
                         inicio=f"01/01/{ano}", fim=f"31/12/{ano}")


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
