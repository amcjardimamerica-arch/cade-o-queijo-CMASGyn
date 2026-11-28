"""Sondagem das fontes federais ainda sem coletor (SIOPE, SIOPS, Tesouro, FNS, FNDE, Transferegov).

Roda no GitHub, onde a rede é aberta. Para cada endereço candidato guarda o código de resposta,
o tipo e o começo do corpo em ``relatorios/onisciente/sondagem/``. Quando a fonte é um catálogo
CKAN ou um serviço OData, lista os recursos e lê uma amostra pequena de cada um. Só lê; não
grava nada no banco. O resultado serve para escrever os coletores sem adivinhar endereço.
O repositório é público: todo CPF de pessoa física é mascarado (``mascara_cpf``) antes de gravar.
"""

from __future__ import annotations

import base64
import hashlib
import inspect
import json
import time
import re
import sys
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from http.cookiejar import CookieJar
from html import unescape
from urllib.parse import quote, urljoin
from urllib.request import HTTPCookieProcessor, build_opener, install_opener

from . import RAIZ, mascara_cpf
from .coletores.base import ler

PASTA = RAIZ / "relatorios" / "onisciente" / "sondagem"
LIMITE = 600_000
LIMITE_GRANDE = 6_000_000   # a MSC vem em páginas de milhares de linhas: guarda a página inteira
GRANDES = {"msc", "pncp_detalhe", "pncp_dados", "d2_transweb"}   # d2_transweb: a exportação CSV do mês (1,5 MB)
DADOS = "https://dadosabertos.compras.gov.br/"
# Cabeçalhos que a própria página manda a um serviço (pelo começo do endereço).
CABECALHOS = {"https://virtual.tcmgo.tc.br/jurisprudencia/api/": {"X-Cliente": "portal"}}

OLINDA = "https://www.fnde.gov.br/olinda-ide/servico/"
CANDIDATOS: dict[str, list[str]] = {
    "siope": [
        OLINDA,
        OLINDA + "DADOS_ABERTOS_SIOPE/versao/v1/odata/",
        OLINDA + "DADOS_ABERTOS_SIOPE/versao/v1/odata/$metadata",
        OLINDA + "DADOS_ABERTOS_SIOPE/versao/v1/documentacao",
    ],
    "fnde": [
        "https://www.fnde.gov.br/dadosabertos/api/3/action/package_list",
        "https://www.fnde.gov.br/dadosabertos/api/3/action/package_search?q=transferencias&rows=20",
    ],
    "siops": [
        "https://opendatasus.saude.gov.br/api/3/action/package_search?q=siops&rows=20",
        "https://opendatasus.saude.gov.br/api/3/action/package_show?id=siops",
        "http://siops.datasus.gov.br/consleirespfiscal.php",
        "http://siops.datasus.gov.br/rel_LRF.php",
        "http://siops.datasus.gov.br/indicadores.php",
    ],
    "fns": [
        "https://opendatasus.saude.gov.br/api/3/action/package_search?q=fundo%20a%20fundo&rows=20",
        "https://consultafns.saude.gov.br/",
        "https://consultafns.saude.gov.br/recursos/consulta-detalhada",
    ],
    "tesouro": [
        "https://www.tesourotransparente.gov.br/ckan/api/3/action/package_search?q="
        + quote("transferências constitucionais") + "&rows=20",
        "https://www.tesourotransparente.gov.br/ckan/api/3/action/package_show?id="
        "transferencias-constitucionais-para-municipios",
    ],
    # O CKAN do Tesouro recusa a conexão da coleta: a mesma porta de novo e outras vias das transferências.
    "tesouro2": [
        "https://www.tesourotransparente.gov.br/ckan/api/3/action/package_show?id="
        "transferencias-constitucionais-para-municipios",
        "https://www.tesourotransparente.gov.br/ckan/dataset/transferencias-constitucionais-para-municipios",
        "https://demonstrativos.apps.bb.com.br/arrecadacao-federal",
        "https://portaldatransparencia.gov.br/download-de-dados/transferencias/202501",
        "https://portaldatransparencia.gov.br/transferencias/consulta?paginacaoSimples=true&tamanhoPagina=10"
        "&offset=0&direcaoOrdenacao=asc&de=01%2F01%2F2025&ate=31%2F01%2F2025&uf=GO&nomeMunicipio=GOIANIA",
    ],
    # A Matriz de Saldos Contábeis (MSC) do SICONFI: receita e despesa por fonte, natureza e função.
    "msc": [
        "https://apidatalake.tesouro.gov.br/ords/siconfi/tt/msc_orcamentaria?id_ente=5208707&an_referencia=2025"
        "&me_referencia=12&co_tipo_matriz=MSCC&classe_conta=6&id_tv=period_change",
        "https://apidatalake.tesouro.gov.br/ords/siconfi/tt/msc_orcamentaria?id_ente=5208707&an_referencia=2025"
        "&me_referencia=12&co_tipo_matriz=MSCC&classe_conta=5&id_tv=period_change",
        "https://apidatalake.tesouro.gov.br/ords/siconfi/tt/msc_orcamentaria?id_ente=5208707&an_referencia=2025"
        "&me_referencia=12&co_tipo_matriz=MSCE&classe_conta=6&id_tv=ending_balance",
        "https://apidatalake.tesouro.gov.br/ords/siconfi/tt/msc_controle?id_ente=5208707&an_referencia=2025"
        "&me_referencia=12&co_tipo_matriz=MSCC&classe_conta=8&id_tv=ending_balance",
    ],
    # As transferências do mês no Portal da Transparência (arquivo de dados abertos, sem chave).
    "transparencia": ["https://portaldatransparencia.gov.br/download-de-dados/transferencias/202501"],
    # Segunda rodada: a consulta pública do SIOPS (Anexo XVI, ASPS) e o RREO municipal do SIOPE.
    "siops2": [
        "http://siops.datasus.gov.br/consleirespfiscal.php?UF=52&Ano=2025&Periodo=1&Municipio=&MudouAno=true",
        "http://siops.datasus.gov.br/consleirespfiscal.php?UF=52&Ano=2024&Periodo=1&Municipio=&MudouAno=true",
    ],
    "siope2": [
        "https://www.fnde.gov.br/siope/relatorioRREOMunicipal2009.do?acao=atualizar&pag=result&anos=2025"
        "&periodos=6&cod_uf=52&municipios=520870",
        "https://www.fnde.gov.br/siope/relatorioRREOMunicipal2009.do?acao=atualizar&pag=result&anos=2025"
        "&periodos=-1&cod_uf=52&municipios=520870",
        "https://www.fnde.gov.br/siope/relatorioRREOMunicipal2006.do?acao=atualizar&pag=result&anos=2025"
        "&periodos=6&cod_uf=52&municipios=520870",
        "https://www.fnde.gov.br/siope/relatorioRREOMunicipal2009.do?acao=atualizar&pag=result&anos=2026"
        "&periodos=4&cod_uf=52&municipios=520870",
        "https://www.fnde.gov.br/siope/relatorioRREOMunicipal2009.do?acao=atualizar&pag=result&anos=2024"
        "&periodos=6&cod_uf=52&municipios=520870",
        "https://www.fnde.gov.br/siope/relatorioRREOMunicipal2009.do",
        "https://www.fnde.gov.br/siope/consultarRREOMunicipal.do",
    ],
    # Terceira rodada: o botão Consultar do SIOPE envia o formulário com acao=pesquisar.
    "siope3": [
        ("https://www.fnde.gov.br/siope/relatorioRREOMunicipal2006.do",
         {"acao": "pesquisar", "pag": "result", "anos": ano, "periodos": per, "cod_uf": "52",
          "municipios": "520870"})
        for ano, per in (("2025", "6"), ("2024", "6"), ("2026", "4"), ("2026", "5"))
    ],
    "siops3": [
        "http://siops.datasus.gov.br/consleirespfiscal.php?UF=52&Ano=2026&Periodo=1&Municipio=&MudouAno=true",
    ],
    # Quarta rodada: o OData do SIOPE com os parâmetros obrigatórios (ano, bimestre, UF).
    "siope4": [
        "https://www.fnde.gov.br/olinda-ide/servico/DADOS_ABERTOS_SIOPE/versao/v1/odata/"
        f"{conjunto}(Ano_Consulta=@Ano_Consulta,Num_Peri=@Num_Peri,Sig_UF=@Sig_UF)"
        f"?@Ano_Consulta={ano}&@Num_Peri={per}&@Sig_UF='GO'&$filter=COD_MUNI%20eq%20520870&$format=json&$top=2000"
        for conjunto in ("Indicadores_Siope", "Dados_Gerais_Siope", "Receita_Siope", "Despesas_Siope",
                         "Informacoes_Complementares_Siope")
        for ano, per in (("2025", "6"), ("2026", "4"))
    ] + [
        "https://www.fnde.gov.br/olinda-ide/servico/DADOS_ABERTOS_SIOPE/versao/v1/odata/"
        "Indicadores_Siope(Ano_Consulta=@Ano_Consulta,Num_Peri=@Num_Peri,Sig_UF=@Sig_UF)"
        "?@Ano_Consulta=2024&@Num_Peri=6&@Sig_UF='GO'&$format=json&$top=5",
        "https://www.fnde.gov.br/olinda-ide/servico/DADOS_ABERTOS_SIOPE/versao/v1/aplicacao",
    ],
    # Quinta rodada: o SIOPE com sessão (cookie da página do formulário) e o PDF do RREO no FTP.
    "siope5": [
        "https://www.fnde.gov.br/siope/relatorioRREOMunicipal2006.do",
        ("https://www.fnde.gov.br/siope/relatorioRREOMunicipal2006.do",
         {"acao": "pesquisar", "pag": "result", "anos": "2025", "periodos": "6", "cod_uf": "52",
          "municipios": "520870"}),
        "ftp://ftp.fnde.gov.br/web/siope/RREO/RREO_Municipal_520870_6_2025.pdf",
        "ftp://ftp.fnde.gov.br/web/siope/RREO/RREO_Municipal_520870_4_2026.pdf",
        "ftp://ftp.fnde.gov.br/web/siope/RREO/",
        "https://www.fnde.gov.br/olinda-ide/servico/DADOS_ABERTOS_SIOPE/versao/v1/odata/"
        "Indicadores_Siope(Ano_Consulta=@Ano_Consulta,Num_Peri=@Num_Peri,Sig_UF=@Sig_UF)"
        "?@Ano_Consulta=2025&@Num_Peri=6&@Sig_UF='GO'&$top=3&$format=json",
    ],
    # Sexta rodada: os PDFs do RREO Anexo 8 de Goiânia no FTP do SIOPE, guardados em bruto.
    "siope6": [f"ftp://ftp.fnde.gov.br/web/siope/RREO/RREO_Municipal_520870_{b}_{a}.pdf"
               for a, bs in ((2024, (6,)), (2025, (1, 6)), (2026, (1, 2, 3, 4, 5))) for b in bs],
    # Bloco 4: o detalhe das contratações e dos contratos do PNCP (amparo legal, itens, resultados,
    # termos aditivos) e o painel de preços do Compras.gov.br, com as especificações das APIs.
    "pncp_detalhe": [
        "https://pncp.gov.br/api/pncp/v3/api-docs",
        "https://pncp.gov.br/api/consulta/v3/api-docs",
        "https://dadosabertos.compras.gov.br/v3/api-docs",
        "https://pncp.gov.br/api/consulta/v1/orgaos/04973965000111/compras/2024/43",
        "https://pncp.gov.br/api/pncp/v1/orgaos/04973965000111/compras/2024/43",
        "https://pncp.gov.br/api/pncp/v1/orgaos/04973965000111/compras/2024/43/itens?pagina=1&tamanhoPagina=100",
        "https://pncp.gov.br/api/pncp/v1/orgaos/04973965000111/compras/2024/43/itens/1/resultados",
        "https://pncp.gov.br/api/pncp/v1/orgaos/17577524000142/compras/2024/16/itens?pagina=1&tamanhoPagina=100",
        "https://pncp.gov.br/api/pncp/v1/orgaos/04973965000111/contratos/2024/47",
        "https://pncp.gov.br/api/pncp/v1/orgaos/04973965000111/contratos/2024/47/termos",
        "https://pncp.gov.br/api/pncp/v1/orgaos/17736850000155/contratos/2024/1/termos",
        "https://pncp.gov.br/api/consulta/v1/contratos?dataInicial=20241101&dataFinal=20241130"
        "&cnpjOrgao=04973965000111&pagina=1&tamanhoPagina=10",
    ],
    # Bloco 4: as vias em lote do Compras.gov.br (amparo legal, itens com catálogo e resultado,
    # preço nacional) e, no PNCP, aditivos de contratos grandes e instrumentos de cobrança (NF-e).
    "pncp_dados": [
        DADOS + "modulo-contratacoes/1_consultarContratacoes_PNCP_14133?pagina=1&tamanhoPagina=20"
        "&dataPublicacaoPncpInicial=2025-03-01&dataPublicacaoPncpFinal=2025-03-31&codigoModalidade=8"
        "&unidadeOrgaoCodigoIbge=5208707",
        DADOS + "modulo-contratacoes/2_consultarItensContratacoes_PNCP_14133?pagina=1&tamanhoPagina=50"
        "&orgaoEntidadeCnpj=04973965000111&dataInclusaoPncpInicial=2024-11-01&dataInclusaoPncpFinal=2024-11-30",
        DADOS + "modulo-contratacoes/2_consultarItensContratacoes_PNCP_14133?pagina=1&tamanhoPagina=500"
        "&orgaoEntidadeCnpj=25141524000123&dataInclusaoPncpInicial=2025-01-01&dataInclusaoPncpFinal=2025-12-31",
        DADOS + "modulo-contratacoes/3_consultarResultadoItensContratacoes_PNCP_14133?pagina=1&tamanhoPagina=50"
        "&orgaoEntidadeCnpj=04973965000111&dataResultadoPncpInicial=2024-11-01&dataResultadoPncpFinal=2024-12-31",
        "https://pncp.gov.br/api/pncp/v1/orgaos/25141524000123/contratos/2026/76/termos",
        "https://pncp.gov.br/api/pncp/v1/orgaos/17736850000155/contratos/2024/4/termos",
        "https://pncp.gov.br/api/pncp/v1/orgaos/17736850000155/contratos/2024/3/termos",
        "https://pncp.gov.br/api/pncp/v1/orgaos/17497764000137/contratos/2026/3/termos",
        "https://pncp.gov.br/api/consulta/v1/instrumentoscobranca/inclusao?dataInicial=20250101"
        "&dataFinal=20251231&cnpjOrgao=04973965000111&pagina=1&tamanhoPagina=10",
        "https://pncp.gov.br/api/consulta/v1/instrumentoscobranca/inclusao?dataInicial=20260101"
        "&dataFinal=20260131&pagina=1&tamanhoPagina=10",
        "https://pncp.gov.br/api/consulta/v1/contratos?dataInicial=20250101&dataFinal=20251231"
        "&cnpjOrgao=25141524000123&pagina=1&tamanhoPagina=100",
    ],
    "transferegov": [
        "https://api.transferegov.gestao.gov.br/transferenciasespeciais/",
        "https://api.transferegov.gestao.gov.br/fundoafundo/",
        "https://api.transferegov.gestao.gov.br/ted/",
    ],
    # Blocos 5 a 7 (27/11): execução da despesa de Goiânia, FNS, FNDE, Transferegov e sanções.
    "goiania": [
        "https://www10.goiania.go.gov.br/transweb/",
        "https://www10.goiania.go.gov.br/transweb/Default.aspx",
        "https://www10.goiania.go.gov.br/transweb/PerguntasFrequentes.aspx",
        "https://www.goiania.go.gov.br/transparencia/",
        "https://goiania.nucleogov.com.br/cidadao/",
    ],
    # Frente D2 (execução da despesa de Goiânia): as páginas candidatas do TransWeb listadas em
    # alvos/portais/goiania.toml e o portal novo em WordPress. A sondagem de 27/11/2026 achou o menu
    # em PortaldaTransparencia.aspx?Antigo=True (Home.aspx e Default.aspx dão 404); as páginas do
    # menu ligadas à despesa vêm primeiro. O que responder com formulário dá os nomes reais dos campos.
    "d2_transweb": [
        "https://www10.goiania.go.gov.br/transweb/Portal_Despesas.aspx",
        "https://www10.goiania.go.gov.br/transweb/Orcamento.aspx",
        "https://www10.goiania.go.gov.br/transweb/ContratoseConvenios.aspx",
        "https://www10.goiania.go.gov.br/transweb/Portal_DiariasPassagens.aspx",
        "https://www10.goiania.go.gov.br/transweb/ListaOrgaos.aspx",
        "https://www10.goiania.go.gov.br/transweb/PortaldaTransparencia.aspx?Antigo=True",
        "https://www10.goiania.go.gov.br/transweb/EmpenhoOrgao.aspx",
        "https://www10.goiania.go.gov.br/transweb/ConsultaEmpenhoOrgao.aspx",
        "https://www10.goiania.go.gov.br/transweb/Empenho/EmpenhoPorOrgao.aspx",
        "https://www10.goiania.go.gov.br/transweb/EmpenhoPorOrgao.aspx",
        "https://www10.goiania.go.gov.br/transweb/Consultas/EmpenhoOrgao.aspx",
        "https://www10.goiania.go.gov.br/transweb/EmpenhoCredor.aspx",
        "https://www10.goiania.go.gov.br/transweb/ConsultaEmpenhoCredor.aspx",
        "https://www10.goiania.go.gov.br/transweb/EmpenhoPorCredor.aspx",
        "https://www10.goiania.go.gov.br/transweb/OrdemPagamentoOrgao.aspx",
        "https://www10.goiania.go.gov.br/transweb/ConsultaOrdemPagamento.aspx",
        "https://www10.goiania.go.gov.br/transweb/OrdemPagamento.aspx",
        "https://www10.goiania.go.gov.br/transweb/OrdemDePagamentoPorOrgao.aspx",
        # Terceira rodada: o EmpenhoPopUp com "&" (a segunda sondagem seguiu o link com "&amp;" e o popup
        # veio sem o empenho). Os dois primeiros empenhos da lista de novembro de 2026.
        "https://www10.goiania.go.gov.br/DespesasWebBlocks/EmpenhoPopUp.aspx?CdOrgao=1101&Empenho=20261101002310011"
        "&NmOrgao=SECRETARIA+MUNICIPAL+DE+GOVERNO",
        "https://www10.goiania.go.gov.br/DespesasWebBlocks/EmpenhoPopUp.aspx?CdOrgao=1101&Empenho=20261101002430005"
        "&NmOrgao=SECRETARIA+MUNICIPAL+DE+GOVERNO",
    ],
    # Frente D2, sexta rodada: o caminho do motor execucao_goiania, reproduzido pelo próprio código do
    # motor (goiania_transweb.exportar_mes) em três meses e em três variantes. Sem endereços na fila:
    # quem lê é _caminho_do_motor.
    "d2_transweb_motor": [],
    # Frente D2, oitava rodada: os popups de liquidação e de pagamento mostram uma página de até 50 linhas.
    # Os quatro empenhos da amostra com mais de 50 eventos na exportação (coleta 550c30b), para guardar o
    # contador ("1 to 50 of N records") e a navegação da lista, de onde sai a leitura das páginas seguintes.
    "d2_transweb_popup": [
        f"https://www10.goiania.go.gov.br/DespesasWebBlocks/{pagina}PopUp.aspx?Empenho={empenho}"
        for empenho in ("20262150000230001", "20265150000230001", "20265151000730001", "20261201000430004")
        for pagina in ("Liquidacao", "Pagamento")
    ],
    "d2_wordpress": [
        "https://www.goiania.go.gov.br/transparencia/",
        "https://www.goiania.go.gov.br/transparencia/?filtro_simplificado=categoria&categoria=49",
        "https://www.goiania.go.gov.br/wp-json/wp/v2/pages?search=despesa&per_page=20",
        "https://www.goiania.go.gov.br/wp-json/wp/v2/categories?per_page=100",
        "https://www.goiania.go.gov.br/wp-json/wp/v2/media?per_page=20&search=despesa",
        "https://www.goiania.go.gov.br/wp-json/",
    ],
    "fns2": [
        "https://consultafns.saude.gov.br/",
        "https://apifns.saude.gov.br/api/",
        "https://apifns.saude.gov.br/api/v3/api-docs",
        "https://apifns.saude.gov.br/v3/api-docs",
        "https://apifns.saude.gov.br/api/swagger-ui.html",
    ],
    "fnde2": [
        "https://www.fnde.gov.br/pls/simad/internet_fnde.liberacoes_01_pc",
        "https://www.fnde.gov.br/pls/simad/internet_fnde.liberacoes_result_pc?p_ano=2025&p_programa=&p_uf=GO"
        "&p_municipio=520870",
        "https://www.fnde.gov.br/sigefweb/index.php/liberacoes",
    ],
    "transferegov2": [
        "https://api.transferegov.gestao.gov.br/transferenciasespeciais/plano_acao_especial"
        "?cnpj_beneficiario_plano_acao=eq.01612092000123&limit=5",
        "https://api.transferegov.gestao.gov.br/transferenciasespeciais/programa_especial?limit=2",
        "https://docs.api.transferegov.gestao.gov.br/transferenciasespeciais/",
    ],
    "sancoes": [
        "https://portaldatransparencia.gov.br/download-de-dados/ceis/20261126",
        "https://portaldatransparencia.gov.br/download-de-dados/cnep/20261126",
    ],
    # Frente D1 (bloco 5), segunda rodada (27/11/2026): o que a primeira sondagem deixou em aberto.
    "d1_fns": [
        # Sexta rodada (28/11): as 191 entidades fecham em duas páginas e o Fundo Municipal de Saúde
        # (37.623.352/0001-03) está entre elas; acaoController e pagamentoController deram os parâmetros.
        # Agora as respostas: as ações do Fundo em 2025 e os pagamentos (sem ação e com a primeira).
        "https://consultafns.saude.gov.br/app/controllers/portalController.js",
        "https://consultafns.saude.gov.br/recursos/consulta-detalhada/detalhe-acao?page=1&count=100&ano=2025&mes=&"
        "tipoConsulta=&blocos=&grupo=&planoOrcamentario=&componentes=&acoes=&estado=GO&municipio=520870&repasse=&"
        "dataInicialOb=&dataFinalOb=&cpfCnpjUg=37623352000103",
        "https://consultafns.saude.gov.br/recursos/consulta-detalhada/detalhe-pagamento?page=1&count=100&ano=2025&mes=&"
        "tipoConsulta=&blocos=&componentes=&acoes=&estado=GO&municipio=520870&repasse=&dataInicialOb=&dataFinalOb=&"
        "cpfCnpjUg=37623352000103",
        "https://consultafns.saude.gov.br/app/pages/detalhada/controllers/acaoController.js",
        "https://consultafns.saude.gov.br/app/pages/consolidada/services/consolidadaService.js",
        "https://consultafns.saude.gov.br/recursos/consulta-detalhada/entidades?page=1&count=100&ano=2024&mes=&"
        "tipoConsulta=&blocos=&grupo=&componentes=&acoes=&estado=GO&municipio=520870&repasse=&dataInicialOb=&"
        "dataFinalOb=",
        # Erro do servidor (NullPointerException) nas duas rodadas: só para ver se mudou.
        "https://consultafns.saude.gov.br/recursos/repasse-dia/detalhar-pagamento-dia?ano=2025&mes=1&dia=15&"
        "codigoProgramaFundo=61861&tipoDetalhamento=PROGRAMA",
        # Sétima rodada: detalhe-pagamento com acoes vazio trouxe a página 1 de 7 (676 ordens, pagina=0 na
        # resposta). As páginas 2 e 7 mostram se page conta de 1 (sem repetir a 1) e se a última fecha o
        # total; acoes=61659 mostra se o filtro por ação (o caminho da tela, que o motor usa de reserva) vale.
        "https://consultafns.saude.gov.br/recursos/consulta-detalhada/detalhe-pagamento?page=2&count=100&ano=2025&"
        "mes=&tipoConsulta=&blocos=&componentes=&acoes=&estado=GO&municipio=520870&repasse=&dataInicialOb=&"
        "dataFinalOb=&cpfCnpjUg=37623352000103",
        "https://consultafns.saude.gov.br/recursos/consulta-detalhada/detalhe-pagamento?page=7&count=100&ano=2025&"
        "mes=&tipoConsulta=&blocos=&componentes=&acoes=&estado=GO&municipio=520870&repasse=&dataInicialOb=&"
        "dataFinalOb=&cpfCnpjUg=37623352000103",
        "https://consultafns.saude.gov.br/recursos/consulta-detalhada/detalhe-pagamento?page=1&count=100&ano=2025&"
        "mes=&tipoConsulta=&blocos=&componentes=&acoes=61659&estado=GO&municipio=520870&repasse=&dataInicialOb=&"
        "dataFinalOb=&cpfCnpjUg=37623352000103",
        # Nona rodada: na coleta d532c1d as 7 páginas vieram diferentes, mas com ordens repetidas entre elas e
        # outras faltando. count=1000 mostra se as 676 vêm numa página só (sem paginação, sem repetição).
        # Décima rodada: acoes=61659 respondeu (166 ordens, 2 páginas); a página 2 fecha a ação e mostra se a
        # paginação por ação também repete ordens. count=1000 ainda não foi lido (a sondagem de 06:50Z rodou
        # antes de ele entrar).
        ("https://consultafns.saude.gov.br/recursos/consulta-detalhada/detalhe-pagamento?page=2&count=100&ano=2025&"
         "mes=&tipoConsulta=&blocos=&componentes=&acoes=61659&estado=GO&municipio=520870&repasse=&dataInicialOb=&"
         "dataFinalOb=&cpfCnpjUg=37623352000103"),
        ("https://consultafns.saude.gov.br/recursos/consulta-detalhada/detalhe-pagamento?page=1&count=1000&ano=2025&"
         "mes=&tipoConsulta=&blocos=&componentes=&acoes=&estado=GO&municipio=520870&repasse=&dataInicialOb=&"
         "dataFinalOb=&cpfCnpjUg=37623352000103"),
    ],
    "d1_fnde": [
        # As liberações por entidade já são lidas (terceira rodada): uma de prova, para a trava do formato.
        "https://www.fnde.gov.br/pls/simad/internet_fnde.liberacoes_result_pc?p_ano=2024&p_programa=&p_uf=GO"
        "&p_municipio=520870&p_tp_entidade=&p_cgc=01612092000123",
    ],
    "d1_transferegov": [
        # A API deu 503 e o repositório 404 (quarta rodada): o motor tenta de novo no fim; aqui, de novo.
        "https://api.transferegov.gestao.gov.br/transferenciasespeciais/",
        "https://api.transferegov.gestao.gov.br/transferenciasespeciais/plano_acao_especial"
        "?cnpj_beneficiario_plano_acao=eq.01612092000123&limit=5&offset=0",
        "https://api.transferegov.gestao.gov.br/fundoafundo/",
    ],
    "d1_sancoes": [
        # A página do CEIS (28/11) anuncia só 27/11 (arquivos.push), que o motor já lê; 28 e 29/11 deram 403
        # porque ainda não saíram. De novo a página e o arquivo seguinte, para ver a defasagem de publicação.
        "https://dadosabertos-download.cgu.gov.br/PortalDaTransparencia/saida/cnep/20261127_CNEP.zip",
        "https://portaldatransparencia.gov.br/download-de-dados/ceis",
        "https://dadosabertos-download.cgu.gov.br/PortalDaTransparencia/saida/ceis/20261129_CEIS.zip",
    ],
    "d1_economia_go": [
        # As conciliações de 2025 e 2026 e a de 2024 já têm leitor (aba Agregado e abas MM-AAAA): prova do formato.
        "https://goias.gov.br/economia/repasse-aos-municipios/",
        "https://goias.gov.br/economia/wp-content/uploads/sites/45/2026/05/Conciliacao_das_Distribuicoes-2025.xlsx",
    ],
    "d1_tcu": [
        # inicio=100 encerrou a conexão com 100 e com 50 por página: a pesquisa para em 100 resultados. Uma
        # ordenação por ano e número traria os mais recentes nos 100; inicio=50 fica como prova do formato.
        "https://pesquisa.apps.tcu.gov.br/rest/publico/base/acordao-completo/documentosResumidos?termo=%22Goi%C3%A2nia%22"
        "&ordenacao=ANOACORDAO+desc%2C+NUMACORDAOINT+desc&quantidade=50&inicio=0&sinonimos=true",
        "https://pesquisa.apps.tcu.gov.br/rest/publico/base/acordao-completo/documentosResumidos?termo=%22Goi%C3%A2nia%22"
        "&ordenacao=DTRELEVANCIA+desc%2C+NUMACORDAOINT+desc&quantidade=50&inicio=50&sinonimos=true",
        "https://pesquisa.apps.tcu.gov.br/rest/publico/base/acordao-completo/documentosResumidos?termo=%22Goi%C3%A2nia%22"
        "&ordenacao=DTRELEVANCIA+desc%2C+NUMACORDAOINT+desc&quantidade=50&inicio=100&sinonimos=true",
        # Sétima rodada: inicio=100 com 50 respondeu (2/4/2024 a 26/10/2022) e a ordem por ano encerrou a
        # conexão. A ordem padrão já vem da sessão mais nova para a mais antiga. Mais fundo, para ver se o
        # corte da sexta rodada foi instabilidade: inicio=150 e inicio=1300 (são 1.374 resultados).
        "https://pesquisa.apps.tcu.gov.br/rest/publico/base/acordao-completo/documentosResumidos?termo=%22Goi%C3%A2nia%22"
        "&ordenacao=DTRELEVANCIA+desc%2C+NUMACORDAOINT+desc&quantidade=50&inicio=150&sinonimos=true",
        "https://pesquisa.apps.tcu.gov.br/rest/publico/base/acordao-completo/documentosResumidos?termo=%22Goi%C3%A2nia%22"
        "&ordenacao=DTRELEVANCIA+desc%2C+NUMACORDAOINT+desc&quantidade=50&inicio=1300&sinonimos=true",
    ],
    "d1_tcm": [
        # O pacote principal da jurisprudência só tem a base da API (/jurisprudencia/api, cabeçalho X-Cliente:
        # portal) e o /v1/health; a tela de pesquisa é carregada à parte (jurisprudencia-page-*.js).
        "https://virtual.tcmgo.tc.br/jurisprudencia/",
        "https://ws.tcm.go.gov.br/api/rest/dados/contas-irregulares",
        "https://virtual.tcmgo.tc.br/jurisprudencia/assets/jurisprudencia-page-zRQnq2W_.js",
        "https://virtual.tcmgo.tc.br/jurisprudencia/api/v1/health",
        # Sétima rodada: a tela chama {api}/v1/acordao/jurisprudencia/buscar (texto, page, page_size,
        # sort_by=data_sessao, sort_order=desc) e /filtros (os valores de municipio e entidade), com o
        # cabeçalho X-Cliente: portal (CABECALHOS, abaixo).
        "https://virtual.tcmgo.tc.br/jurisprudencia/api/v1/acordao/jurisprudencia/filtros",
        "https://virtual.tcmgo.tc.br/jurisprudencia/api/v1/acordao/jurisprudencia/buscar?texto=Goi%C3%A2nia&page=1"
        "&page_size=100&sort_by=data_sessao&sort_order=desc",
        "https://virtual.tcmgo.tc.br/jurisprudencia/api/v1/acordao/jurisprudencia/buscar?texto=Goi%C3%A2nia&page=2"
        "&page_size=100&sort_by=data_sessao&sort_order=desc",
        # Décima rodada: filtros trouxe os municípios ({"nome": "Goiânia", "valor": "GOIANIA"}) e a tela manda o
        # escolhido como municipio. Estas mostram se o filtro vale sem texto (o caminho do motor agora).
        ("https://virtual.tcmgo.tc.br/jurisprudencia/api/v1/acordao/jurisprudencia/buscar?texto=&page=1"
         "&page_size=100&sort_by=data_sessao&sort_order=desc&municipio=GOIANIA"),
        ("https://virtual.tcmgo.tc.br/jurisprudencia/api/v1/acordao/jurisprudencia/buscar?texto=&page=20"
         "&page_size=100&sort_by=data_sessao&sort_order=desc&municipio=GOIANIA"),
    ],
    # Frente E (27/11): auditoria independente do Selo de Transparência (PNTP). As páginas que cada critério
    # da matriz (regras/pntp/matriz_2026.yml) manda olhar; onisciente/selo/coleta.py segue os links internos.
    "e_home": ["https://www.goiania.go.gov.br/"],
    "e_portal": ["https://www.goiania.go.gov.br/transparencia/"]
    + [f"https://www.goiania.go.gov.br/transparencia/?filtro_simplificado=categoria&categoria={n}"
       for n in range(40, 71)]
    + ["https://www.goiania.go.gov.br/transparencia/?s=" + quote(t)
       for t in ("empenho", "diárias", "convênio", "contrato", "licitação", "obras", "renúncia", "emenda",
                 "dívida ativa", "assistência social", "conselho", "relatório de gestão fiscal",
                 "relatório resumido", "plano plurianual", "estagiários", "terceirizados", "ordem cronológica")],
    "e_transweb": [
        "https://www10.goiania.go.gov.br/transweb/",
        "https://www10.goiania.go.gov.br/transweb/Default.aspx",
        "https://www10.goiania.go.gov.br/transweb/PerguntasFrequentes.aspx",
    ],
    "e_folha": ["https://www.goiania.go.gov.br/sing_transparencia/folha-de-pagamento-dados-gerais/"],
    "e_legislacao": [
        "https://www.goiania.go.gov.br/html/gabinete_civil/sileg/dados/legis/2025/lo_20251022_000011510.html",
        "https://www.goiania.go.gov.br/html/gabinete_civil/sileg/dados/legis/2026/lo_20260109_000011589.html",
        "https://www.goiania.go.gov.br/html/gabinete_civil/sileg/dados/legis/2026/lo_20260109_000011590.html",
        "https://www.goiania.go.gov.br/html/gabinete_civil/sileg/dados/legis/2013/lo_20130522_000009262.html",
        "https://www.goiania.go.gov.br/html/gabinete_civil/sileg/dados/legis/2026/dc_20260817_000000147.html",
    ],
    "e_esic": [
        "https://esic.goiania.go.gov.br/",
        "https://www.goiania.go.gov.br/transparencia/?filtro_simplificado=categoria&categoria=50",
    ],
    "e_cmas": [
        "https://cmasgyn.com.br/Conselho/Conselheiros",
        "https://cmasgyn.com.br/Conselho/Plenarias",
        "https://cmasgyn.com.br/Conselho/Entidades",
        "https://cmasgyn.com.br/Documentos",
        "https://cmasgyn.com.br/Documentos/Legislacao",
    ],
    "e_saude": ["https://saude.goiania.go.gov.br/"],
    "e_educacao": ["https://sme.goiania.go.gov.br/"],
    "e_dados": [
        "https://dados.gov.br/dados/conjuntos-dados?organizacao=goiania",
        "https://goiania.nucleogov.com.br/api",
    ],
    # O resultado oficial (Radar, painel por entidade) e a metodologia, para confrontar e guardar.
    "e_radar": [
        "https://radardatransparencia.atricon.org.br/",
        "https://radardatransparencia.atricon.org.br/painel-6/",
        "https://pntp.atricon.org.br/dados-abertos/",
        "https://pntp.atricon.org.br/o-programa/",
    ],
    "e_metodo": [
        "https://www.mpma.mp.br/wp-content/uploads/2026/04/Cartilha-PNTP-2026-versao-08.04.2026.pdf",
        "https://sistema.pelotas.com.br/transparencia/arquivos/" + quote("Matriz de Criterios 2026 PDF.pdf"),
        "https://cdn.atricon.org.br/uploads/2026/02/Cronograma-PNTP-2026.pdf",
        "https://www.tcepi.tc.br/wp-content/uploads/2026/04/Metodologia-PNTP-2026.pdf",
    ],
    # Frente F (empresas contratadas): a base mensal do CNPJ da Receita (WebDAV do compartilhamento,
    # índice antigo, página do compartilhamento e o dicionário de dados), o espelho por CNPJ com um
    # fornecedor do banco, o CEPIM e a lista de inidôneos do TCU.
    "f_cnpj": [
        "https://arquivos.receitafederal.gov.br/public.php/webdav/Dados/Cadastros/CNPJ/",
        "https://arquivos.receitafederal.gov.br/index.php/s/gn672Ad4CF8N6TK",
        "https://arquivos.receitafederal.gov.br/dados/cnpj/dados_abertos_cnpj/",
        "https://arquivos.receitafederal.gov.br/dados/cnpj/dados_abertos_cnpj/2026-11/",
        "https://www.gov.br/receitafederal/dados/cnpj-metadados.pdf",
    ],
    "f_brasilapi": [
        "https://brasilapi.com.br/api/cnpj/v1/16826800000104",
        "https://minhareceita.org/16826800000104",
    ],
    "f_cepim": [
        "https://portaldatransparencia.gov.br/download-de-dados/cepim/20261126",
        "https://portaldatransparencia.gov.br/download-de-dados/cepim/20261125",
    ],
    "f_tcu": [
        "https://certidoes.apps.tcu.gov.br/api/publico/responsaveis-inidoneos-com-paginacao",
        "https://certidoes.apps.tcu.gov.br/api/publico/responsaveis-inidoneos-com-paginacao?pagina=0"
        "&tamanhoPagina=50",
        "https://certidoes.apps.tcu.gov.br/lista-inidoneos",
        "https://contas.tcu.gov.br/ords/condenacao/consulta/inidoneos",
    ],
}


def _slug(url: str, formulario: dict | None = None) -> str:
    chave = url + json.dumps(formulario or {}, sort_keys=True)
    curto = re.sub(r"[^a-z0-9]+", "-", url.lower().split("://", 1)[-1])[:70].strip("-")
    return f"{curto}-{hashlib.sha256(chave.encode()).hexdigest()[:8]}"


def _guardar(fonte: str, url: str, leitura, formulario: dict | None = None,
             cabecalhos: dict | None = None) -> dict:
    PASTA.mkdir(parents=True, exist_ok=True)
    arq = PASTA / f"{fonte}__{_slug(url, formulario)}.txt"
    bruto = leitura.conteudo[:LIMITE_GRANDE if fonte in GRANDES else LIMITE]
    if leitura.ok and bruto.startswith((b"%PDF", b"PK\x03\x04")):   # binário: os bytes como vieram, em base64
        sufixo = ".pdf.b64" if bruto.startswith(b"%PDF") else ".zip.b64"
        dados = leitura.conteudo
        if sufixo == ".zip.b64":
            try:
                dados = mascara_cpf.mascarar_zip(dados)[0]       # o repositório é público: CPF mascarado
            except (zipfile.BadZipFile, RuntimeError, ValueError, EOFError):
                pass                                            # ZIP que não abre não tem texto legível
        arq.with_suffix(sufixo).write_text(base64.b64encode(dados).decode())
    try:
        # Frente D1: o corpo da recusa também (a mensagem do 400/500 diz o parâmetro que falta).
        # Frente D2 (rodada 10): a recusa do TransWeb (o HTTP 500 do OsAjax) também, para provar a causa.
        corpo = bruto.decode("utf-8") if leitura.ok or fonte.startswith(("d1_", "d2_transweb")) else ""
    except UnicodeDecodeError:
        corpo = bruto.decode("latin-1")
    if fonte.startswith("d2_transweb"):
        # Frente D2: o repositório é público; o CPF de pessoa física (a coluna CNPJ da exportação traz o
        # CPF com "000", as diárias trazem o do servidor) fica só com os seis dígitos do meio.
        from .coletores.goiania_transweb import mascarar_cpfs_no_texto
        corpo = mascarar_cpfs_no_texto(corpo)
    pedido = ""
    if cabecalhos:
        # O pedido inteiro fica guardado (Frente D2, rodada 10). Cookie vai só com o nome: o valor da
        # sessão não entra no repositório.
        visiveis = {k: (_sem_valor_de_cookie(v) if k.lower() == "cookie" else v) for k, v in cabecalhos.items()}
        pedido = f"CABECALHOS: {json.dumps(visiveis, ensure_ascii=False)}\n"
    texto = (f"URL: {url}\nPOST: {json.dumps(formulario or {}, ensure_ascii=False)}\n{pedido}OK: {leitura.ok}\nHTTP: {leitura.http}\nERRO: {leitura.erro}\n"
             f"BYTES: {len(leitura.conteudo)}\n\n{corpo}")
    arq.write_text(mascara_cpf.mascarar_texto(texto)[0], encoding="utf-8")   # CPF de pessoa física mascarado
    return {"fonte": fonte, "url": url, "post": formulario, "ok": leitura.ok, "http": leitura.http, "erro": leitura.erro,
            "bytes": len(leitura.conteudo), "arquivo": arq.name}


def _sem_valor_de_cookie(valor: str) -> str:
    """``a=1; b=2`` vira ``a=<valor omitido>; b=<valor omitido>``: o nome do cookie prova que a sessão
    foi junto; o valor não se guarda."""
    nomes = [p.split("=", 1)[0].strip() for p in str(valor).split(";") if p.strip()]
    return "; ".join(f"{n}=<valor omitido>" for n in nomes)


def _aceita(funcao, nome: str) -> bool:
    """A função recebe o parâmetro ``nome`` (ou ``**kwargs``)? Os leitores e guardadores falsos das
    travas antigas não recebem os parâmetros novos."""
    try:
        parametros = inspect.signature(funcao).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(p.name == nome or p.kind is inspect.Parameter.VAR_KEYWORD for p in parametros)


def _siops_consultas(url: str, texto: str) -> list[tuple[str, dict]]:
    """Da página de escolha do SIOPS, as consultas ao Anexo XVI de Goiânia em cada período."""
    ano = re.search(r"Ano=(\d{4})", url).group(1)
    mun = re.search(r"<option[^>]*value='(\d+)'[^>]*>\s*Goi[^<]{0,4}nia\s*<", texto, re.I)
    sel = re.search(r"name='cmbPeriodo'.*?</select>", texto, re.S)
    periodos = re.findall(r"value='(\d+)'", sel.group(0)) if sel else []
    codigos = [mun.group(1)] if mun else ["520870", "5208707"]
    periodos = periodos or ["1", "12", "14", "18", "20", "2", "3", "4", "5", "6"]
    return [("http://siops.datasus.gov.br/rel_LRF.php",
             {"cmbAno": ano, "cmbUF": "52", "cmbPeriodo": p, "cmbMunicipio[]": c,
              "BtConsultar": "Consultar"}) for c in codigos for p in periodos]


def _preco_dos_itens(texto: str) -> list[str]:
    """Dos itens de um órgão, a pesquisa de preço nacional dos três primeiros códigos achados."""
    try:
        itens = json.loads(texto).get("resultado") or []
    except (ValueError, AttributeError):
        return []
    novos: list[str] = []
    for it in itens:
        pdm, cat = it.get("codigoPdm"), it.get("codItemCatalogo")
        if it.get("materialOuServico") == "S" and cat:
            novos.append(DADOS + f"modulo-pesquisa-preco/3_consultarServico?pagina=1&tamanhoPagina=50"
                                 f"&codigoItemCatalogo={cat}")
        elif cat:
            novos.append(DADOS + f"modulo-pesquisa-preco/1_consultarMaterial?pagina=1&tamanhoPagina=50"
                                 f"&tipo=codigoItemCatalogo&codigo={cat}")
        elif pdm:
            novos.append(DADOS + f"modulo-pesquisa-preco/1_consultarMaterial?pagina=1&tamanhoPagina=50"
                                 f"&tipo=codigoPdm&codigo={pdm}")
        if len(set(novos)) >= 3:
            break
    return list(dict.fromkeys(novos))


def _seguir(fonte: str, url: str, leitura) -> list:
    """Endereços de segunda rodada: amostras de conjuntos OData e recursos CKAN."""
    if not leitura.ok:
        return []
    texto = leitura.texto
    novos: list = []
    if fonte in ("goiania", "fns2", "fnde2") or (fonte.startswith("d2_") and fonte != "d2_transweb_popup"):
        # As páginas dos portais: os links internos (.aspx, scripts com os endereços da API).
        base = re.match(r"https?://[^/]+", url).group(0)
        for href in re.findall(r"""(?:href|src)=["']([^"'#]+\.(?:aspx|js|php)[^"']*)["']""", texto, re.I):
            if fonte == "d2_transweb":
                href = unescape(href)   # o link do EmpenhoPopUp traz "&amp;" no HTML; o pedido leva "&"
            if href.startswith("//"):
                href = "https:" + href
            elif href.startswith("/"):
                href = base + href
            elif not href.startswith("http"):
                href = url.rsplit("/", 1)[0] + "/" + href
            if href.startswith(base) and "jquery" not in href.lower():
                novos.append(href)
        return list(dict.fromkeys(novos))[:30]
    if "2_consultarItensContratacoes" in url:
        return _preco_dos_itens(texto)
    if "consleirespfiscal.php?UF=" in url:
        return _siops_consultas(url, leitura.conteudo.decode("latin-1"))
    if url.endswith("/odata/"):
        try:
            for conj in json.loads(texto).get("value", []):
                nome = conj.get("url") or conj.get("name")
                if nome:
                    novos.append(url + nome + "?$top=3&$format=json")
        except ValueError:
            pass
    if "/api/3/action/package_" in url:
        try:
            res = json.loads(texto).get("result")
        except ValueError:
            return []
        pacotes = res.get("results", []) if isinstance(res, dict) and "results" in res else \
            [res] if isinstance(res, dict) else []
        for pac in pacotes[:12]:
            for r in (pac.get("resources") or [])[:6]:
                u = r.get("url") or ""
                if u.lower().endswith((".csv", ".json")) or "api" in u.lower():
                    novos.append(u)
    return novos[:25]


def _conversa_despesas(fonte: str, url: str, leitura, *, ler_=None, guardar=None,
                       valores: dict | None = None) -> list[dict]:
    """d2_transweb, segunda rodada: a partir da Portal_Despesas.aspx lida, na mesma sessão de cookies,
    (a) o Buscar por OsAjax com mês 10 e ano 2026; (b) o next da página 2 com o __OSVSTATE da
    resposta (a); (c) a exportação CSV (selExportar e o botão OK, postback comum); (d) o mesmo Buscar
    por postback comum, para saber qual dos dois envios o servidor aceita. Os pedidos são montados
    pelo coletor (goiania_transweb) com a configuração de alvos/portais/goiania.toml."""
    from .coletores import goiania_transweb as G
    ler_ = ler_ or ler
    guardar = guardar or _guardar
    portal = G.carregar_portal(RAIZ / "alvos" / "portais" / "goiania.toml")
    c = portal.consulta("despesas_favorecido")
    forms = [f for f in G.formularios(leitura.conteudo) if f.achar(c.campos["mes"])]
    if not forms:
        return []
    form = forms[0]
    acao = urljoin(url, form.acao or url)
    valores = valores or {"mes": "10", "ano": "2026"}
    out: list[dict] = []

    def enviar(passo: str, corpo, *, ajax: bool):
        if isinstance(corpo, str):          # o pedido não pôde ser montado: fica registrado
            out.append({"fonte": fonte, "url": acao, "post": None, "ok": False, "http": None,
                        "erro": f"{passo}: {corpo}", "bytes": 0, "arquivo": "", "passo": passo})
            return None
        destino = f"{acao}?_ts={int(time.time() * 1000)}" if ajax else acao   # como o _osjs.js
        inicio = time.monotonic()
        cab = G.cabecalhos_osajax(url) if ajax else {}       # rodada 11: os cabeçalhos do OsAjax, como no popup
        extra = {"cabecalhos": cab} if cab and _aceita(ler_, "cabecalhos") else {}
        lida = ler_(destino, tempo=90, fonte=fonte, formulario=corpo, **extra)
        if cab and _aceita(guardar, "cabecalhos"):
            registro = guardar(fonte, destino, lida, corpo, cabecalhos=cab)
        else:
            registro = guardar(fonte, destino, lida, corpo)
        registro["segundos"] = round(time.monotonic() - inicio, 1)
        registro["passo"] = passo
        out.append(registro)
        return lida

    corpo = G.corpo_buscar(form, c, valores, ajax=True)
    lida = enviar("a_buscar_osajax", corpo, ajax=True)
    estado, ajax_da_pagina = dict(form.campos), list(form.ajax)
    if lida is not None and lida.ok:
        estado, ajax_da_pagina, _html, _lido = G.depois_da_resposta(G.estado_do_envio(corpo, form),
                                                                    ajax_da_pagina, lida.conteudo)
        prox = G.proxima_pagina(ajax_da_pagina, 1)
        if prox is None:
            enviar("b_pagina_2_osajax", "o link da página seguinte não foi achado", ajax=True)
        else:
            lida2 = enviar("b_pagina_2_osajax", G.corpo_proxima(acao, estado, prox, ajax=True, tipos=form.tipos), ajax=True)
            if lida2 is not None and lida2.ok:
                estado, ajax_da_pagina, _html, _lido = G.depois_da_resposta(estado, ajax_da_pagina, lida2.conteudo)
    enviar("c_exportar_csv", G.corpo_exportar(form, c, valores, "CSV", estado=estado), ajax=False)
    enviar("d_buscar_postback", G.corpo_buscar(form, c, valores, ajax=False), ajax=False)
    return out


MESES_DO_MOTOR = ("2024-11", "2025-06", "2026-10")


def _caminho_do_motor(fonte: str, *, ler_=None, guardar=None, meses=MESES_DO_MOTOR,
                      abridor=None) -> list[dict]:
    """d2_transweb_motor: o motor execucao_goiania gravou zero eventos (rodada 46093388087: o POST da
    exportação voltou com 19.654 bytes, não com a planilha). Repete o caminho do motor com o código
    dele (exportar_mes: GET da página e postback da exportação) e guarda o corpo de cada resposta:

    * ``sem_cookies``: como o motor rodou (o leitor comum não guarda cookies), no mês 2026-10;
    * ``com_cookies``: como o motor corrigido (sessão de cookies, sessao_de_cookies), nos três meses;
    * ``buscar_antes``: com cookies, o Buscar por OsAjax antes da exportação, como a sondagem que
      recebeu a planilha, no mês 2026-10.

    Cada registro diz se a resposta é a planilha (o leitor do motor) e, se não for, o motivo legível."""
    from .coletores import goiania_transweb as G
    ler_ = ler_ or ler
    guardar = guardar or _guardar
    abridor = abridor or (lambda cookies: install_opener(
        build_opener(HTTPCookieProcessor(CookieJar())) if cookies else build_opener()))
    portal = G.carregar_portal(RAIZ / "alvos" / "portais" / "goiania.toml")
    c = portal.consulta("despesas_favorecido")
    out: list[dict] = []
    variantes = [("sem_cookies", False, "2026-10", False)] + \
        [("com_cookies", True, m, False) for m in meses] + [("buscar_antes", True, "2026-10", True)]
    for nome, cookies, mes, buscar in variantes:
        abridor(cookies)                     # sessão nova (ou nenhuma) para cada variante
        etiqueta = f"{nome}-{mes}"

        def ler_motor(url, formulario=None, _et=etiqueta, _buscar=buscar, _mes=mes):
            if _buscar and formulario and formulario.get("__EVENTTARGET") == "":
                # Antes da exportação, o Buscar por OsAjax com a página recém-lida (o passo a).
                pagina = ultimas.get("pagina")
                if pagina is not None:
                    f = [x for x in G.formularios(pagina.conteudo) if x.achar(c.campos["mes"])]
                    if f:
                        ano, mm = _mes.split("-")
                        corpo = G.corpo_buscar(f[0], c, {"mes": mm, "ano": ano}, ajax=True)
                        if isinstance(corpo, dict):
                            destino = f"{url}?_ts={int(time.time() * 1000)}"
                            lida = ler_(destino, tempo=90, fonte=fonte, formulario=corpo)
                            reg = guardar(fonte, f"{destino}#{_et}-buscar", lida, corpo)
                            reg.update({"variante": _et, "passo": "buscar_osajax"})
                            out.append(reg)
            inicio = time.monotonic()
            lida = ler_(url, tempo=120, fonte=fonte, formulario=formulario)
            reg = guardar(fonte, f"{url}#{_et}-{'exportar' if formulario else 'get'}", lida, formulario)
            reg.update({"variante": _et, "passo": "exportar" if formulario else "get",
                        "segundos": round(time.monotonic() - inicio, 1)})
            if formulario is None:
                ultimas["pagina"] = lida
            else:
                try:
                    exp = G.eventos_da_exportacao(lida.conteudo, c.exportar.get("colunas") or {})
                    reg.update({"planilha": True, "linhas": exp.linhas, "empenhos": exp.empenhos,
                                "por_mes": exp.por_mes})
                except ValueError as e:
                    reg.update({"planilha": False, "motivo": str(e)})
            out.append(reg)
            return lida

        ultimas: dict = {}
        G.exportar_mes(ler_motor, portal, c, mes)
    abridor(True)
    return out


# Rodada 11: o teto era 3 e o empenho de 1.695 e 1.718 linhas parou na página 3; 40 páginas (2.000
# linhas) leem os popups da amostra inteiros, como o motor (até 60).
PAGINAS_DO_POPUP_NA_SONDAGEM = 40
PAGINAS_GUARDADAS_DO_POPUP = 3      # o corpo das três primeiras (e de toda página recusada) fica guardado


def _popups_paginados(fonte: str, urls: list[str], *, ler_=None, guardar=None,
                      paginas_maximas: int = PAGINAS_DO_POPUP_NA_SONDAGEM) -> list[dict]:
    """d2_transweb_popup: cada popup de liquidação e de pagamento lido como o motor lê
    (goiania_transweb.ler_popup: a primeira página por GET e as seguintes pelo next do navegador da
    lista, por OsAjax), até ``paginas_maximas`` páginas; o corpo de cada página fica guardado e um
    registro ``resumo`` diz quantas páginas, linhas e o total do contador."""
    from .coletores import goiania_transweb as G
    ler_ = ler_ or ler
    guardar = guardar or _guardar
    portal = G.carregar_portal(RAIZ / "alvos" / "portais" / "goiania.toml")
    c = portal.consulta("despesas_favorecido")
    out: list[dict] = []
    for url in urls:
        tipo = "liquidacao" if "LiquidacaoPopUp" in url else "pagamento"
        empenho = url.rsplit("Empenho=", 1)[-1]
        paginas = [0]

        jarra: list = []

        def ler_pop(destino, formulario=None, cabecalhos=None, _url=url):
            paginas[0] += 1
            inicio = time.monotonic()
            # Rodada 10: o pedido inteiro como saiu (cabeçalhos do OsAjax e os nomes dos cookies da
            # sessão que o GET da página 1 criou), para a próxima sondagem provar o que faltava.
            enviados = dict(cabecalhos or {})
            cookies = sorted({ck.name for ck in (jarra[0] if jarra else [])})
            if cookies:
                enviados["Cookie"] = "; ".join(f"{n}=x" for n in cookies)
            extra = {"cabecalhos": cabecalhos} if cabecalhos and _aceita(ler_, "cabecalhos") else {}
            lida = ler_(destino, tempo=90, fonte=fonte, formulario=formulario, **extra)
            nome = destino if paginas[0] == 1 else f"{_url}#pagina-{paginas[0]}"
            if paginas[0] > PAGINAS_GUARDADAS_DO_POPUP and lida.ok:
                # Da quarta página em diante, só o registro (o repositório não guarda 35 páginas por popup).
                reg = {"fonte": fonte, "url": nome, "post": None, "ok": lida.ok, "http": lida.http,
                       "erro": lida.erro, "bytes": len(lida.conteudo), "arquivo": ""}
            elif enviados and _aceita(guardar, "cabecalhos"):
                reg = guardar(fonte, nome, lida, formulario, cabecalhos=enviados)
            else:
                reg = guardar(fonte, nome, lida, formulario)
            reg.update({"passo": f"pagina_{paginas[0]}", "segundos": round(time.monotonic() - inicio, 1),
                        "destino": destino, "cookies": cookies,
                        "cabecalhos": sorted(k for k in (cabecalhos or {}))})
            out.append(reg)
            return lida

        # Como o motor (sessao_de_cookies): uma sessão de cookies própria, criada pelo GET da página 1, e
        # os nomes dos cookies que foram junto ficam no registro de cada página.
        with G.sessao_de_cookies() as jar:
            jarra.append(jar)
            pop = G.ler_popup(ler_pop, url, tipo, c.popups[tipo]["colunas"], {"empenho": empenho},
                              paginas_maximas=paginas_maximas)
        out.append({"fonte": fonte, "url": url, "ok": bool(pop.paginas), "http": None, "passo": "resumo",
                    "tipo": tipo,
                    "paginas": pop.paginas, "total": pop.total, "completo": pop.completo,
                    "linhas": len([e for e in pop.eventos if e["tipo"] == tipo]),
                    "soma": round(sum(e["valor"] for e in pop.eventos if e["tipo"] == tipo), 2), "erro": pop.erro,
                    # Rodada 12: as contas por tipo e as linhas que não são do tipo (anulação de liquidação,
                    # ordem sem pagamento), para explicar a diferença entre o contador e a exportação.
                    "tipos": dict(sorted(Counter(e["tipo"] for e in pop.eventos).items())),
                    "outras_linhas": [{k: e[k] for k in ("tipo", "ordem", "data", "valor")}
                                      for e in pop.eventos if e["tipo"] != tipo][:100]})
    return out


def fontes_da_linha(argumentos: list[str]) -> list[str]:
    """As fontes pedidas na linha de comando, separadas por espaço ou por vírgula: o fluxo da sondagem
    passa o campo ``fontes`` como uma palavra só (``d2_transweb_popup,d1_fns``), e a sondagem do commit
    1e36935 não leu nada por isso."""
    return [f for a in argumentos for f in re.split(r"[\s,]+", a) if f]


def fontes_pedidas(argumentos: list[str]) -> list[str] | None:
    """As fontes de ``fontes_da_linha`` sem repetição, ou None (todas) se nada foi pedido. A fonte que
    não existe fica no índice da sondagem (``fontes_desconhecidas``), em vez de sair um índice vazio calado."""
    return list(dict.fromkeys(fontes_da_linha(argumentos))) or None


def sondar(fontes: list[str] | None = None) -> list[dict]:
    resultado = []
    desconhecidas = [f for f in fontes or () if f not in CANDIDATOS]
    for nome in desconhecidas:
        print(f"FALHA fonte desconhecida na sondagem: {nome}", file=sys.stderr)
    install_opener(build_opener(HTTPCookieProcessor(CookieJar())))   # sessão, como num navegador
    for fonte, urls in CANDIDATOS.items():
        if fontes and fonte not in fontes:
            continue
        if fonte == "d2_transweb_motor":
            resultado.extend(_caminho_do_motor(fonte))
            continue
        if fonte == "d2_transweb_popup":
            resultado.extend(_popups_paginados(fonte, urls))
            continue
        fila: list = list(urls)
        vistos: set[str] = set()
        while fila:
            item = fila.pop(0)
            url, formulario = item if isinstance(item, tuple) else (item, None)
            chave = url + json.dumps(formulario or {}, sort_keys=True)
            if chave in vistos:
                continue
            vistos.add(chave)
            inicio = time.monotonic()
            cabecalhos = next((v for k, v in CABECALHOS.items() if url.startswith(k)), None)
            leitura = ler(url, tempo=90, fonte=fonte, formulario=formulario, cabecalhos=cabecalhos)
            registro = _guardar(fonte, url, leitura, formulario)
            registro["segundos"] = round(time.monotonic() - inicio, 1)
            resultado.append(registro)
            if item in urls:
                fila.extend(_seguir(fonte, url, leitura))
            if fonte == "d2_transweb" and formulario is None and leitura.ok and \
                    url.split("?", 1)[0].endswith("/Portal_Despesas.aspx"):
                resultado.extend(_conversa_despesas(fonte, url, leitura))
    nome = "indice.json" if not fontes else f"indice_{'_'.join(fontes)}.json"
    (PASTA / nome).write_text(mascara_cpf.mascarar_texto(json.dumps(
        {"quando": datetime.now(timezone.utc).isoformat(timespec="seconds"), "leituras": resultado,
         **({"fontes_desconhecidas": desconhecidas} if desconhecidas else {})},
        ensure_ascii=False, indent=1))[0], encoding="utf-8")
    return resultado


if __name__ == "__main__":
    for r in sondar(fontes_pedidas(sys.argv[1:])):
        print(("OK " if r["ok"] else "FALHA ") + f"{r['fonte']}: {r['url']} {r['http'] or r['erro']}")
