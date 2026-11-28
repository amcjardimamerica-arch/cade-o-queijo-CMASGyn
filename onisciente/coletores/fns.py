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

Sondagem de 28/11/2026 (rodada 4): ``recursos/repasse-dia/recuperar-data-ultimo-pagamento`` devolve
``{"resultado": "26/11/2026"}`` e ``recursos/repasse-dia/consultar?ano=2025&mes=1&dia=15`` devolve a
árvore do dia: bloco (``Manutenção das Ações e Serviços Públicos de Saúde``, ``OUTRAS TRANSFERÊNCIAS``),
grupo e programa, cada nível com ``vlTotal`` e os filhos em ``repasses``; a folha traz a competência,
o tipo de transferência e o nível (``ESTRATEGIA``, ``PO``). É o total nacional pago no dia, por
programa: ``arvore_repasse_dia`` o achata e confere que as folhas somam o total de cada nível. O
filtro por Município fica na consulta detalhada (``detalhadaService.js``: o recurso
``recursos/consulta-detalhada`` com ``entidades``, ``detalhe-acao``, ``detalhe-pagamento``,
``detalhe-conta``, ``detalhe-ordem-bancaria`` e os saldos; o controlador manda ``ano``, ``mes``,
``tipoConsulta``, ``blocos``, ``grupo``, ``componentes``, ``acoes``, ``estado``, ``municipio`` (IBGE de 6
dígitos), ``repasse``, ``dataInicialOb``, ``dataFinalOb``, ``page`` e ``count``). O modelo
``consulta-detalhada/entidades`` com o Município entrou em ``MODELOS``; a resposta dele ainda não foi
vista.

Sondagem da rodada 5 (28/11/2026): ``consulta-detalhada/entidades`` com ``estado=GO&municipio=520870``
respondeu 200 com ``resultado.dados`` (uf, município, ``codigoMunicipioIBGE``, ``cpfCnpj``, razão social,
esfera administrativa, ``entidadeSemRepasse``) e a paginação (``pagina`` a partir de 0, ``itensPorPagina``,
``total``, ``totalPaginas``): 191 entidades de Goiânia em 2025, todas com o IBGE 520870 (o filtro do
Município foi respeitado). É a lista de quem recebeu, sem valores: ``entidades`` a lê, e ela não serve
de repasse (``MODELOS_DE_REPASSE`` a deixa de fora). Pessoa física fica com o ``cpfCnpj`` como o FNS o
publica (inteiro; decisão do usuário de 28/11/2026). ``detalhar-pagamento-dia`` deu 500 e o ``-final`` deu 400 com os parâmetros do
controlador (o corpo do erro não foi guardado pela sondagem).

Sondagem da rodada 6 (28/11/2026): a página 2 das entidades com 100 por página fecha as 191 (``pagina`` 1,
91 linhas), e entre elas está o Fundo Municipal de Saúde de Goiânia (esfera ``MUNICIPAL``). O
``detalhar-pagamento-dia`` é um erro do servidor (``NullPointerException``), não parâmetro faltando. Os
controladores das telas de ação e de pagamento (``acaoController.js``, ``pagamentoController.js``) dão
os parâmetros do valor por entidade: ``detalhe-acao`` com ano, filtros vazios, ``estado``, ``municipio``
(IBGE da entidade) e ``cpfCnpjUg`` (o CNPJ da entidade); cada linha traz ``id``, ``descricao``,
``blocoPacto.nome``, ``grupoAcao.nome``, ``componenteBloco.nome``, ``valorTotal``, ``valorDesconto`` e
``valorLiquido``. ``detalhe-pagamento`` usa os mesmos filtros com ``acoes`` = o ``id`` da ação e traz
``valorTotal``, ``valorDescontoTotal``, ``valorLiquido``, ``numeroDocumentoSiafi`` (a ordem bancária),
``codigoBanco``, ``codigoAgencia``, ``contaCorrente``, ``nuPortaria`` e ``id.processo``. As respostas
desses dois ainda não foram vistas: ``acoes`` e ``pagamentos`` leem os campos que os controladores usam.

Sondagem da rodada 7 (28/11/2026), com o Fundo Municipal de Saúde de Goiânia em 2025: ``detalhe-acao``
traz 40 ações numa página, com ``valorDescontoTotal`` (não ``valorDesconto``) e, na primeira linha, os
totais gerais da entidade. ``detalhe-pagamento`` com ``acoes`` vazio traz todas as ordens do ano (676, em
7 páginas de 100; ``pagina`` volta contada de 0). Cada ordem diz a ação em ``id.programaFundo.id`` (o
mesmo ``id`` da ação), o mês do pagamento em ``anoPagamento`` e ``mesPagamento``, o documento em
``tipoDocumentoPagamento`` e ``numeroDocumentoSiafi`` (vazios quando o valor inteiro foi descontado, e
então a ``dataCriacaoSiafi`` é sempre 01/01) e a parcela em ``competencia`` (``01/12 em 2025``, ``NOV de
2024``, ``Única em 2024``). As ordens com ``indicadorFundoAFundo`` = ``N`` (documento ``PF``, conta
``UNICA``) não são repasse fundo a fundo à conta do Fundo. O total geral das ordens (R$ 1.036.219.851,35)
passa o das ações (R$ 1.030.381.073,26): há ordens de programa que não está na lista de ações do ano.
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
    # consultafns, consulta detalhada (detalhadaController.js): as entidades do Município no ano.
    CONSULTA + "consulta-detalhada/entidades?page={pagina}&count=100&ano={ano}&mes=&tipoConsulta=&blocos="
               "&grupo=&componentes=&acoes=&estado={uf}&municipio={ibge6}&repasse=&dataInicialOb=&dataFinalOb=",
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

_VARIAVEL = re.compile(r"(?:\bvar\s+|\bthis\.)(\w+)\s*=\s*'([^']*)'")
_METODO = re.compile(r"\b\w+\.prototype\.(\w+)\s*=\s*function\s*\(")
_TERMO = r"\s*(?:(?:this\.)?\w+|'[^']*')\s*"
_EXPR = rf"({_TERMO}(?:\+{_TERMO})*)"
_COLECAO = re.compile(rf"\.all\({_EXPR}\)\s*(?:\.withHttpConfig\([^)]*\)\s*)?"
                      rf"\.(customGET|customPOST|customPUT|post|get|remove)\(\s*(?:{_EXPR}[,)])?")


def _avaliar(expr: str, variaveis: dict[str, str]) -> tuple[str, bool]:
    """Uma concatenação de JS (``cGetUrl + '/' + this.recurso + '/x'``) com as variáveis de texto do
    arquivo; diz também se algum termo era conhecido (literal ou variável de texto)."""
    partes, conhecido = [], False
    for termo in (t.strip() for t in expr.split("+")):
        if termo.startswith("'"):
            partes.append(termo.strip("'"))
            conhecido = conhecido or bool(termo.strip("'"))
        else:
            nome = termo.removeprefix("this.")
            if nome in variaveis:
                partes.append(variaveis[nome])
                conhecido = conhecido or bool(variaveis[nome])
    return "".join(partes), conhecido


def servicos_do_js(js: str) -> dict[str, tuple[str, str]]:
    """Os endereços que um serviço AngularJS do consultafns chama: {função: (método, caminho)}.

    O caminho junta a coleção do Restangular (``all(...)``) e o recurso de ``customGET`` ou do ``post``,
    com as variáveis de texto do arquivo (``this.resource``, ``var cGetUrl``, ``this.nomeResourceDetalhada``);
    métodos comentados e chamadas cujo recurso é um parâmetro não contam."""
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.DOTALL)
    variaveis = dict(_VARIAVEL.findall(js))
    inicios = [(m.start(), m.group(1)) for m in _METODO.finditer(js)]
    saida = {}
    for n, (pos, nome) in enumerate(inicios):
        corpo = js[pos:inicios[n + 1][0] if n + 1 < len(inicios) else len(js)]
        m = _COLECAO.search(corpo)
        if not m:
            continue
        colecao, verbo, recurso = m.group(1), m.group(2), m.group(3)
        base_, base_conhecida = _avaliar(colecao, variaveis)
        if verbo.startswith("custom"):
            if recurso is None:
                continue
            fim, conhecido = _avaliar(recurso, variaveis)
            if not conhecido:
                continue                          # o recurso vem por parâmetro (cGet genérico)
            caminho = "/".join(x.strip("/") for x in (base_, fim) if x.strip("/"))
        else:
            if not base_conhecida:
                continue
            caminho = base_.strip("/")
        metodo = {"customPOST": "POST", "post": "POST", "customPUT": "PUT", "remove": "DELETE"}.get(verbo, "GET")
        saida[nome] = (metodo, caminho)
    return saida


def url_repasse_dia(servico: str, **params) -> str:
    """Um endereço do serviço do repasse dia (``consultar``, ``detalhar-pagamento-dia``...)."""
    base = REPASSE_DIA + servico.strip("/")
    limpos = {k: v for k, v in params.items() if v is not None}
    return base + ("?" + urllib.parse.urlencode(limpos) if limpos else "")


def data_ultimo_pagamento(conteudo: bytes) -> str:
    """``recuperar-data-ultimo-pagamento``: a data do último pagamento, em ISO. Levanta ``ValueError``."""
    obj = cf.json_ou_none(conteudo)
    data = cf.data(obj.get("resultado")) if isinstance(obj, dict) else None
    if not data:
        raise ValueError("a data do último pagamento do FNS não veio no formato esperado")
    return data


def arvore_repasse_dia(conteudo: bytes, data: str) -> list[dict]:
    """A árvore do ``repasse-dia/consultar`` achatada: uma linha por nó, com o nível (0 = bloco), o
    caminho dos nomes e, na folha, a competência e o tipo. Confere que os filhos somam o pai.
    Lista vazia é dia sem pagamento. Levanta ``ValueError`` se o formato mudar ou a soma não fechar."""
    obj = cf.json_ou_none(conteudo)
    if not isinstance(obj, dict) or not isinstance(obj.get("resultado"), list):
        raise ValueError("o repasse do dia do FNS não traz a lista 'resultado'")  # noqa: TRY004
    saida: list[dict] = []

    def descer(no: dict, nivel: int, caminho: list[str]) -> float:
        if not isinstance(no, dict) or "vlTotal" not in no:
            raise ValueError("nó do repasse do dia sem vlTotal")
        total = float(no.get("vlTotal") or 0)
        filhos = no.get("repasses") or []
        nome = _texto(no.get("nome"))
        saida.append({
            "data": data, "nivel": nivel, "caminho": " > ".join(caminho + [nome]), "codigo": _texto(no.get("codigo")),
            "nome": nome, "valor_total": round(total, 2), "valor_desconto": no.get("vlDesconto"),
            "valor_liquido": no.get("vlLiquido"), "competencia": no.get("dsCompetencia"),
            "tipo_competencia": no.get("noTipoCompetencia"), "tipo_transferencia": no.get("noTipoTransferencia"),
            "nivel_programa": no.get("dsNivel"), "processos": no.get("qtdProcesso"), "folha": int(not filhos)})
        if filhos:
            soma = sum(descer(f, nivel + 1, caminho + [nome]) for f in filhos)
            if abs(soma - total) > 0.01:
                raise ValueError(f"os repasses de {nome} não fecham: {soma:.2f} contra {total:.2f}")
        return total

    for raiz in obj["resultado"]:
        descer(raiz, 0, [])
    return saida


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


# Código IBGE da UF (os dois primeiros dígitos do Município) para a sigla.
UF_DO_IBGE = {"11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO", "21": "MA",
              "22": "PI", "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL", "28": "SE", "29": "BA",
              "31": "MG", "32": "ES", "33": "RJ", "35": "SP", "41": "PR", "42": "SC", "43": "RS", "50": "MS",
              "51": "MT", "52": "GO", "53": "DF"}


ENTIDADES = next(m for m in MODELOS if "consulta-detalhada/entidades" in m)
# Os modelos que devolvem pagamentos (a lista de entidades não tem valor).
MODELOS_DE_REPASSE = tuple(m for m in MODELOS if m != ENTIDADES)


def entidades(conteudo: bytes, ibge6: str) -> tuple[list[dict], int, int]:
    """Uma página de ``consulta-detalhada/entidades``: (entidades, total, total de páginas). Levanta
    ``ValueError`` se o formato mudar ou se vier entidade de outro Município (filtro ignorado)."""
    obj = cf.json_ou_none(conteudo)
    res = obj.get("resultado") if isinstance(obj, dict) else None
    if not isinstance(res, dict) or not isinstance(res.get("dados"), list):
        raise ValueError("a lista de entidades do FNS não traz resultado.dados")  # noqa: TRY004
    saida = []
    for d in res["dados"]:
        ibge = str(d.get("codigoMunicipioIBGE") or "")
        if ibge[:6] != str(ibge6)[:6]:
            raise ValueError(f"entidade de outro Município ({ibge}): o filtro do Município não foi aplicado")
        doc = cf.digitos(d.get("cpfCnpj"))
        pessoa_fisica = len(doc) == 11
        saida.append({
            # O ``cpfCnpj`` como o FNS publica (o CPF de pessoa física vem inteiro nele; só o
            # ``cpfCnpjFormatado`` vem mascarado). Antes o coletor guardava o formatado mascarado da pessoa
            # física; a decisão do usuário de 28/11/2026 (config/decisoes_usuario.yml, P-01) manda guardar o
            # dado como a fonte publica.
            "cpf_cnpj": str(d.get("cpfCnpj") if d.get("cpfCnpj") is not None else ""),
            "pessoa_fisica": int(pessoa_fisica), "nome": _texto(d.get("razaoSocial")),
            "esfera": _texto(d.get("esferaAdministrativa")), "municipio_ibge": ibge,
            "sem_repasse": int(bool(d.get("entidadeSemRepasse")))})
    return saida, int(res.get("total") or len(saida)), int(res.get("totalPaginas") or 1)


DETALHE = CONSULTA + "consulta-detalhada/"
# Os parâmetros que cada tela manda, na ordem dos controladores (os vazios também vão).
_PARAMETROS_DETALHE = {
    "detalhe-acao": ("ano", "mes", "tipoConsulta", "blocos", "grupo", "planoOrcamentario", "componentes",
                     "acoes", "estado", "municipio", "repasse", "dataInicialOb", "dataFinalOb", "cpfCnpjUg"),
    "detalhe-pagamento": ("ano", "mes", "tipoConsulta", "blocos", "componentes", "acoes", "estado", "municipio",
                          "repasse", "dataInicialOb", "dataFinalOb", "cpfCnpjUg"),
}


# Rodada 11 (28/11/2026): a sondagem de 07:40Z (commit 9cc559c) pediu as ordens do Fundo em 2025 com
# count=1000 e veio uma página só, de 691.235 bytes (cerca de 676 ordens de 1 KB). O recorte guardado (600 KB,
# 587 ordens inteiras) não tem nenhuma ordem repetida, começa pelas 100 da página 1 na mesma ordem e contém
# todas as 100 da página 2. Com 100 por página, a mesma listagem repetia ordens entre páginas e perdia outras.
# Rodada 12 (sondagem 079a72d, a página guardada inteira): total 676, totalPaginas 1, as 676 ordens sem repetir,
# somando o valorTotalGeral; sem a ordem rejeitada, as 40 ações de 2025 fecham uma a uma com detalhe-acao.
POR_PAGINA_PAGAMENTOS = 1000


def url_detalhe(servico: str, ibge: int | str, ano: int, cnpj: str, pagina: int = 1, acao: str = "",
                por_pagina: int = 100) -> str:
    """Um endereço de ``detalhe-acao`` ou ``detalhe-pagamento`` para uma entidade do Município."""
    ibge = str(ibge)
    valores = {"ano": ano, "acoes": acao, "estado": UF_DO_IBGE.get(ibge[:2], ""), "municipio": ibge[:6],
               "cpfCnpjUg": cf.digitos(cnpj)}
    params = [("page", pagina), ("count", por_pagina)] + [(k, valores.get(k, ""))
                                                         for k in _PARAMETROS_DETALHE[servico]]
    return DETALHE + servico + "?" + urllib.parse.urlencode(params)


def _resultado(conteudo: bytes, o_que: str) -> tuple[list[dict], int]:
    if cf.parece_pagina(conteudo):
        raise ValueError(f"{o_que} do FNS veio como página HTML")
    obj = cf.json_ou_none(conteudo)
    res = obj.get("resultado") if isinstance(obj, dict) else None
    if not isinstance(res, dict) or not isinstance(res.get("dados"), list):
        raise ValueError(f"{o_que} do FNS não traz resultado.dados")  # noqa: TRY004
    return [d for d in res["dados"] if isinstance(d, dict)], int(res.get("total") or len(res["dados"]))


def _nome(v) -> str:
    return _texto(v.get("nome") if isinstance(v, dict) else v)


def acoes(conteudo: bytes) -> tuple[list[dict], int]:
    """Uma página de ``detalhe-acao``: as ações de uma entidade no ano, com o valor (total). Linha sem
    repasse no ano (valor zero) fica, com valor 0. Levanta ``ValueError`` se o formato mudar."""
    dados, total = _resultado(conteudo, "o detalhe por ação")
    saida = []
    for d in dados:
        if "valorTotal" not in d or d.get("id") is None:
            raise ValueError("ação do FNS sem id ou sem valorTotal")
        saida.append({
            "id": _texto(d.get("id")), "bloco": _nome(d.get("blocoPacto")), "grupo": _nome(d.get("grupoAcao")),
            "componente": _nome(d.get("componenteBloco")), "descricao": _texto(d.get("descricao")),
            "valor_total": round(cf.numero(d.get("valorTotal")) or 0.0, 2),
            "valor_desconto": round(cf.numero(d.get("valorDescontoTotal", d.get("valorDesconto"))) or 0.0, 2),
            "valor_liquido": round(cf.numero(d.get("valorLiquido")) or 0.0, 2)})
    return saida, total


_MESES = {m: n for n, m in enumerate(("JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT",
                                        "NOV", "DEZ"), start=1)}


def competencia(texto) -> str | None:
    """AAAA-MM da competência de uma ordem (``NOV de 2024``, ``12 em 2024``). None para a parcela
    (``01/12 em 2025``) e a parcela única, que não dizem o mês."""
    t = _texto(texto).upper()
    if m := re.match(r"^([A-Z]{3}) DE (\d{4})$", t):
        return f"{m.group(2)}-{_MESES[m.group(1)]:02d}" if m.group(1) in _MESES else None
    if m := re.match(r"^(\d{1,2}) EM (\d{4})$", t):
        return f"{m.group(2)}-{int(m.group(1)):02d}" if 1 <= int(m.group(1)) <= 12 else None
    return cf.mes_de(t)


def pagamentos(conteudo: bytes) -> tuple[list[dict], int]:
    """Uma página de ``detalhe-pagamento``: cada ordem nas colunas de ``repasses_fns`` e mais cinco
    chaves que o motor tira antes de gravar: ``programa_id`` (o ``id`` da ação), ``programa`` e ``bloco``
    da própria ordem, ``fundo_a_fundo`` e ``rejeicao`` (o ``motivoRejeicao``, ou None). O mês é o do
    pagamento; a data, a do documento no SIAFI (sem documento, não há data). Levanta ``ValueError`` se o
    formato mudar.

    A ordem com ``motivoRejeicao`` não foi paga: na sondagem 9cc559c, a 2025OB016558 da ação 61659 (R$
    5.838.778,09, "10 CANCELAMENTO PARCIAL DA 2025OB016558 ...") é exatamente o que as ordens da ação
    passavam do total que ``detalhe-acao`` declara (669.552.284,15 contra 663.713.506,06)."""
    dados, total = _resultado(conteudo, "o detalhe por pagamento")
    saida = []
    for d in dados:
        bruto = cf.numero(d.get("valorTotal"))
        if bruto is None:
            raise ValueError("pagamento do FNS sem valorTotal")
        desconto = cf.numero(d.get("valorDescontoTotal")) or 0.0
        liquido = cf.numero(d.get("valorLiquido"))
        chave = d.get("id") if isinstance(d.get("id"), dict) else {}
        programa = chave.get("programaFundo") if isinstance(chave.get("programaFundo"), dict) else {}
        numero, tipo = _texto(d.get("numeroDocumentoSiafi")), _texto(d.get("tipoDocumentoPagamento"))
        ano_pg, mes_pg = _texto(d.get("anoPagamento")), _texto(d.get("mesPagamento"))
        data = cf.data(cf.campo(d, "dataPagamento", "dataOb", "dataOrdemBancaria", "dtPagamento", "data",
                                contem=("datapag", "dataob", "dataordem", "dtpag", "dataemiss")))
        if data is None and numero:
            data = cf.data(d.get("dataCriacaoSiafi"))
        mes = f"{ano_pg}-{int(mes_pg):02d}" if ano_pg.isdigit() and mes_pg.isdigit() else (data or "")[:7] or None
        bruta = _texto(d.get("competencia"))
        comp = competencia(bruta)
        saida.append({
            "mes": mes, "data": data, "competencia": comp,
            "valor_bruto": round(bruto, 2), "desconto": round(desconto, 2),
            "valor_liquido": round(liquido if liquido is not None else bruto - desconto, 2),
            "banco": _texto(d.get("codigoBanco")), "agencia": _texto(d.get("codigoAgencia")),
            "conta": _texto(d.get("contaCorrente")),
            "ordem_bancaria": f"{ano_pg}{tipo}{numero}" if numero and tipo and ano_pg else numero,
            "situacao": " ".join(x for x in (f"processo {chave['processo']}" if chave.get("processo") else "",
                                             f"portaria {d['nuPortaria']}" if d.get("nuPortaria") else "",
                                             f"parcela {bruta}" if bruta and comp is None else "") if x),
            "programa_id": _texto(programa.get("id")), "programa": _texto(programa.get("descricao")),
            "bloco": _texto(d.get("nomeBloco")), "fundo_a_fundo": chave.get("indicadorFundoAFundo") != "N",
            "rejeicao": re.sub(r"\s+", " ", _texto(d.get("motivoRejeicao"))) or None})
    return saida, total


def url(modelo: str, ibge: int | str, ano: int, pagina: int = 1) -> str:
    ibge = str(ibge)
    return modelo.format(ibge6=ibge[:6], ibge=ibge, ano=ano, pagina=pagina, uf=UF_DO_IBGE.get(ibge[:2], ""),
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
