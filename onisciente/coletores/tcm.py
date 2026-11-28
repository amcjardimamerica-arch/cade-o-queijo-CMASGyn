"""TCM-GO: as decisões do Tribunal de Contas dos Municípios de Goiás sobre Goiânia.

O TCM-GO julga as contas do Prefeito (parecer prévio), as contas de gestão dos ordenadores e as
denúncias e representações sobre licitações e contratos. As decisões saem como acórdãos (``AC``),
resoluções (``RC``, ``RS``) e pareceres prévios, publicadas no portal e no Diário Oficial de Contas.

Nenhuma API pública foi confirmada. O coletor lê os candidatos de ``CANDIDATOS`` e aceita JSON ou
página HTML: na página, cada menção a um acórdão, resolução ou parecer prévio com número e ano vira
uma decisão, com o trecho em volta como sumário e o link mais próximo como endereço.

A sondagem de 27/11/2026 mostrou que os endereços da primeira rodada não pesquisam: a página
``site/jurisprudencia/`` ignora o termo e é só o índice das ferramentas (a pesquisa de verdade fica
em ``virtual.tcmgo.tc.br/jurisprudencia/``, um aplicativo cujo serviço ainda não foi lido), a busca
``site/?s=`` devolve notícias e páginas do portal, e o antigo ``pesquisaJurisprudencia/rest`` só
redireciona para o portal. As três respostas reais, reduzidas, estão em ``testes/dados/federais/``
(``tcm_*_real.html``) e o leitor devolve lista vazia para elas, sem inventar decisão. Os candidatos
agora são a busca do WordPress em JSON, a lista oficial de contas com parecer prévio pela rejeição
ou julgadas irregulares e a busca do portal.

Sondagem de 28/11/2026 (run 46085340244): as duas páginas das listas não trazem as listas, só os links
para elas. A de "contas com parecer prévio pela rejeição ou julgamentos irregulares" aponta as três
relações (``contas_irregulares_tcm/tipo_id=1``, 2 e 3) e duas páginas de informação (``mp/id=44``,
contas de governo julgadas pelas câmaras, e ``mp/id=45``, contas encaminhadas ao TRE) no
``acessoainformacao.tcmgo.tc.br``, além dos "Dados Abertos" em ``ws.tcm.go.gov.br/api/rest/dados/
contas-irregulares``; a de "julgamento das contas de governo pelas câmaras" aponta o painel
``tcmgo.tc.br/contaseleicoes/``. ``links_das_listas`` tira esses endereços da página e ``LISTAS`` os
guarda; ``contas`` lê qualquer uma delas (JSON ou tabela HTML) e fica com as linhas do Município.

Sondagem da rodada 7 (28/11/2026): a tela de pesquisa da jurisprudência (``jurisprudencia-page-*.js``)
mostra a API: ``GET {JURISPRUDENCIA}buscar`` com ``texto``, ``page``, ``page_size`` (10 a 100),
``sort_by=data_sessao`` e ``sort_order=desc`` (a ordem padrão da tela) e os filtros ``municipio``,
``entidade``, ``ano_votacao``, ``conselheiro``, ``resultado`` e outros (os valores aceitos vêm de
``filtros``); o cabeçalho ``X-Cliente: portal`` vai em todo pedido. A resposta traz ``data`` (as decisões,
com ``numero_acordao``, ``ano_votacao``, ``data_sessao``, ``tipo_decisao``, ``numero_processo``,
``assunto``, ``ementa``, ``resultado``, ``conselheiro_relator``, ``orgao_julgador``,
``entidade_fiscalizada`` e ``document_id``, cujo PDF fica em ``pdf/{document_id}``) e ``pagination``
(``page``, ``total_pages``, ``has_next``). O ``/v1/health`` respondeu ``healthy``. A resposta de
``buscar`` ainda não foi vista: ``jurisprudencia`` lê os campos que a tela usa.
"""

from __future__ import annotations

import csv
import html as html_lib
import io
import re
import unicodedata
import urllib.parse

from . import comum_federal as cf
from .tcu import sobre

PORTAL = "https://www.tcmgo.tc.br/"

CANDIDATOS = (
    PORTAL + "site/wp-json/wp/v2/search?search={termo}&per_page=100&page={pagina}",
    PORTAL + "site/contas-com-parecer-previo-pela-rejeicao-ou-julgamentos-irregulares/?pagina={pagina}",
    PORTAL + "site/?s={termo}&paged={pagina}",
)
# Lidos na sondagem e descartados: não pesquisam (ver o comentário do módulo).
DESCARTADOS = (
    PORTAL + "pesquisaJurisprudencia/rest/pesquisa?termo={termo}&pagina={pagina}",
    PORTAL + "site/jurisprudencia/?pesquisa={termo}&pagina={pagina}",
)

JURISPRUDENCIA = "https://virtual.tcmgo.tc.br/jurisprudencia/api/v1/acordao/jurisprudencia/"
CABECALHOS_JURISPRUDENCIA = {"X-Cliente": "portal"}
# Na coleta de 28/11/2026 (d532c1d) a busca por "Goiânia", da sessão mais nova para a mais antiga, deu 100
# decisões por página em uns 2 s; as 5 primeiras páginas (500 decisões, 190 sobre Goiânia) só cobriram de
# 03/09 a 27/10/2026. O motor segue até a sessão mais antiga do intervalo, com este teto de páginas.
PAGINAS_JURISPRUDENCIA = 80
# Rodada 11 (28/11/2026, sondagem 9cc559c): a página 20 com municipio=GOIANIA respondeu HTTP 422 com
# {"detail": "Sem chave de API, a busca pagina ate o resultado 1000. ..."}; a página 1 declarou 5.491
# decisões com o filtro (55 páginas de 100; 92 das 100 primeiras são de Goiânia, nenhuma de Aparecida).
# Sem chave, a busca lê no máximo as 10 primeiras páginas e diz até onde chegou. Rodada 12: o motor lê antes
# /exportar (CSV, com os mesmos filtros), ano a ano (ver COLUNAS_EXPORTACAO); a busca ficou de reserva.
RESULTADOS_SEM_CHAVE = 1000
# Rodada 10 (28/11/2026, sondagem a8761d9): a resposta real de filtros traz os 246 municípios como
# {"nome": "Goiânia", "valor": "GOIANIA"}, e a tela real (jurisprudencia-page-*.js) manda o filtro escolhido
# como parâmetro municipio de buscar. A busca pelo texto "Goiânia" achava 13.493 decisões de todo o Estado
# (só 35 das 100 primeiras eram de Goiânia: entidade_fiscalizada "GOIANIA - IPSM", "GOIANIA"). O motor pede
# primeiro pelo município, sem texto; se a primeira página não for na maior parte de Goiânia (o filtro não
# valeu), volta à busca pelo texto e anota.

ACESSO = "https://acessoainformacao.tcmgo.tc.br/"
DADOS_ABERTOS = "https://ws.tcm.go.gov.br/api/rest/dados/contas-irregulares"
PAGINAS_DAS_LISTAS = (
    PORTAL + "site/contas-com-parecer-previo-pela-rejeicao-ou-julgamentos-irregulares/",
    PORTAL + "site/tcm-em-acao/julgamento-das-contas-de-governo-pelas-camaras-municipais/",
)
# As listas, na ordem de leitura: os dados abertos primeiro, depois as relações em HTML.
LISTAS = {
    "dados_abertos": DADOS_ABERTOS,
    "rejeicao_prefeitos": ACESSO + "cidadao/outras_informacoes/contas_irregulares_tcm/tipo_id=1",
    "irregulares_gestao": ACESSO + "cidadao/outras_informacoes/contas_irregulares_tcm/tipo_id=2",
    "irregulares_com_debito": ACESSO + "cidadao/outras_informacoes/contas_irregulares_tcm/tipo_id=3",
    "governo_julgadas_camaras": ACESSO + "informacao/mp/id=44",
    "encaminhadas_tre": ACESSO + "cidadao/informacao/mp/id=45",
    "painel_camaras": PORTAL + "contaseleicoes/",
}
_HOSTS_DAS_LISTAS = ("acessoainformacao.tcmgo.tc.br", "ws.tcm.go.gov.br", "www.tcmgo.tc.br")


def links_das_listas(pagina: str) -> list[str]:
    """Os endereços das listas no corpo de uma das ``PAGINAS_DAS_LISTAS`` (sem o menu e o rodapé do
    portal): os do acesso à informação, os dados abertos e o painel das câmaras."""
    inicio = pagina.find("entry-content")
    fim = pagina.find("Baixe nosso aplicativo", max(inicio, 0))
    corpo = pagina[max(inicio, 0):fim if fim > 0 else len(pagina)]
    saida = []
    for href in re.findall(r"""(?is)<a[^>]+href=["']([^"'#]+)["']""", corpo):
        url = html_lib.unescape(href.strip())
        partes = urllib.parse.urlparse(url)
        if partes.scheme not in ("http", "https") or partes.netloc.lower() not in _HOSTS_DAS_LISTAS:
            continue
        if partes.netloc.lower() == "www.tcmgo.tc.br" and not partes.path.startswith("/contaseleicoes"):
            continue
        saida.append(url)
    return list(dict.fromkeys(saida))


# Cabeçalho real dos dados abertos (sondagem de 28/11/2026): CSV com vírgula, uma linha por responsável
# e processo; o CPF vem mascarado (só os dois primeiros dígitos) e o Município traz o órgão depois de " - ".
COLUNAS_CSV = ("Município", "Nome", "CPF", "Assunto", "Mês/Ano", "Processo/Fase", "Dt. Trânsito Julgado",
               "Data Julgamento", "Acórdão/Resolução", "Url", "TipoLista")


def _sem_particulas(nome: str) -> str:
    """O nome do Município sem "de", "do", "da"... (o CSV escreve APARECIDA GOIANIA)."""
    return " ".join(p for p in cf.norm(nome).split() if p not in ("DE", "DO", "DA", "DOS", "DAS", "D"))


def _csv_contas(texto: str, municipio: str) -> list[dict]:
    """As linhas do Município no CSV dos dados abertos. O nome antes de " - " tem de ser o do Município
    inteiro (GOIANIA, não APARECIDA GOIANIA nem GOIANIRA); o resto é o órgão (sem ele, a Prefeitura)."""
    leitor = csv.DictReader(io.StringIO(texto.lstrip("\ufeff")))
    faltam = [c for c in ("Município", "Nome", "Processo/Fase") if c not in (leitor.fieldnames or [])]
    if faltam:
        raise ValueError(f"CSV das contas irregulares sem as colunas {', '.join(faltam)}")
    alvo = _sem_particulas(municipio)
    saida = []
    for r in leitor:
        lugar = (r.get("Município") or "").strip()
        nome, _, orgao = lugar.partition(" - ")
        if _sem_particulas(nome) != alvo:
            continue
        cpf = (r.get("CPF") or "").strip()
        saida.append({
            "municipio": nome.strip(), "entidade": orgao.strip() or "Prefeitura (Município)",
            "responsavel": (r.get("Nome") or "").strip(), "processo": (r.get("Processo/Fase") or "").strip(),
            "exercicio": (r.get("Mês/Ano") or "").strip(), "transito": cf.data(r.get("Dt. Trânsito Julgado")),
            "cpf_parcial": cpf or None, "assunto": (r.get("Assunto") or "").strip() or None,
            "decisao": (r.get("Acórdão/Resolução") or "").strip() or None,
            "data_julgamento": cf.data(r.get("Data Julgamento")),
            "tipo_lista": (r.get("TipoLista") or "").strip() or None,
            "url_processo": (r.get("Url") or "").strip() or None, "registro": dict(r)})
    return saida


def contas(conteudo: bytes, municipio: str = "Goiânia") -> list[dict]:
    """As linhas do Município numa lista de contas (CSV dos dados abertos, JSON ou tabela HTML). O
    Município é procurado nos campos de município, ente, órgão ou entidade, com a mesma regra que separa
    Goiânia de Aparecida de Goiânia. Levanta ``ValueError`` se a resposta não tiver lista nem tabela."""
    texto = cf.decodificar(conteudo).lstrip("\ufeff")
    primeira = texto.split("\n", 1)[0]
    if (not primeira.lstrip().startswith(("[", "{", "<")) and primeira.count(",") >= 3
            and "munic" in cf.chave(primeira)):
        return _csv_contas(texto, municipio)
    obj = cf.json_ou_none(conteudo)
    if obj is not None:
        regs = cf.registros_json(obj)
        if regs is None:
            raise ValueError("JSON das contas sem lista de registros")
    else:
        tabelas = cf.tabelas_html(cf.decodificar(conteudo))
        regs = [r for t in tabelas for r in cf.tabela_como_registros(t)]
        if not tabelas:
            raise ValueError("página das contas sem tabela")
    saida = []
    for r in regs:
        if not isinstance(r, dict):
            continue
        lugar = " ".join(str(v) for k, v in r.items()
                         if any(t in cf.chave(k) for t in ("municip", "ente", "orgao", "entidade", "unidade")))
        if not lugar or not sobre(lugar, cf.norm(municipio)):
            continue
        saida.append({
            "municipio": cf.campo(r, contem=("municip",)),
            "entidade": cf.campo(r, contem=("orgao", "entidade", "unidade", "ente")),
            "responsavel": cf.campo(r, "responsavel", "nome", "gestor", contem=("responsavel", "gestor")),
            "processo": cf.campo(r, "processo", "numero_processo", contem=("processo",)),
            "exercicio": cf.campo(r, "exercicio", "ano", contem=("exercicio",)),
            "transito": cf.campo(r, contem=("transito",)),
            "cpf_parcial": None, "assunto": cf.campo(r, "assunto", contem=("assunto",)),
            "decisao": cf.campo(r, contem=("acordao", "resolucao", "decisao")), "data_julgamento": None,
            "tipo_lista": None, "url_processo": cf.campo(r, "url", "link"),
            "registro": r,
        })
    return saida


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
        "titulo": f"{tipo} {int(numero)}/{ano}", "sumario": trecho, "url": url,
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


def url_jurisprudencia(texto: str = "Goiânia", pagina: int = 1, por_pagina: int = 100,
                       municipio: str | None = None, ano: int | None = None) -> str:
    """A pesquisa da jurisprudência do TCM-GO, da sessão mais nova para a mais antiga; com ``municipio``
    (o ``valor`` da lista de ``filtros``, como GOIANIA), só as decisões daquele município; com ``ano``, só
    as votadas naquele ano (``ano_votacao``, como a tela manda)."""
    params = {"texto": texto, "page": pagina, "page_size": por_pagina, "sort_by": "data_sessao",
              "sort_order": "desc"}
    if municipio:
        params["municipio"] = municipio
    if ano:
        params["ano_votacao"] = ano
    return JURISPRUDENCIA + "buscar?" + urllib.parse.urlencode(params)


# Rodada 14 (28/11/2026, sondagem de 09:11Z, run 46129272224): a busca com municipio=GOIANIA e ano_votacao
# declarou 747 decisões em 2024 (8 páginas) e 851 em 2026 (9 páginas), como as 918 de 2025: cada ano cabe
# no limite de 1000 da busca sem chave. As 99 decisões de Goiânia da página 1 de 2024 e as 92 da de 2026
# estão todas entre as 732 e 804 que a coleta 6c474b1 guardou pela exportação, e as outras (consórcios, o
# próprio TCM, o MP) ficaram de fora. Quando a exportação de um ano não vem, a busca daquele ano o cobre
# inteiro, sem cair na busca geral, que para no resultado 1000 e, depois das 851 de 2026, não chega a 2024.


# Rodada 12 (28/11/2026, sondagem 079a72d): exportar com municipio=GOIANIA e ano_votacao=2025 (formato=csv, sem
# page, page_size e busca_id, como a tela) respondeu 200 com 1.876.331 bytes: um CSV separado por ";" com 918
# linhas, exatamente o total_items que buscar declarou para o mesmo filtro (918, 10 páginas), todas de 2025, de
# 14/01 a 17/12/2025, sem repetir documento, e as 100 primeiras na mesma ordem da página 1 de buscar. Sem o
# limite de 1000 da busca sem chave. A tela avisa só acima de 10.000 resultados (o cabeçalho
# x-exportacao-truncada, que a leitura não vê); um ano de Goiânia fica longe disso.
COLUNAS_EXPORTACAO = {
    "ID do documento (chave)": "document_id", "Número do acórdão": "numero_acordao",
    "Número do processo": "numero_processo", "Ano": "ano_votacao", "Data da sessão": "data_sessao",
    "Órgão julgador": "orgao_julgador", "Assunto": "assunto", "Macroassunto": "macro_assunto",
    "Relator": "conselheiro_relator", "Entidade fiscalizada": "entidade_fiscalizada",
    "Resultado (IA)": "resultado", "Ementa (IA)": "ementa",
}
_COLUNAS_EXIGIDAS = ("ID do documento (chave)", "Número do acórdão", "Ano", "Entidade fiscalizada")


def url_exportacao(ano: int, municipio: str = "GOIANIA") -> str:
    """A exportação em CSV da jurisprudência de um ano da votação, só do município (o ``valor`` de
    ``filtros``), da sessão mais nova para a mais antiga."""
    params = {"texto": "", "sort_by": "data_sessao", "sort_order": "desc", "municipio": municipio,
              "ano_votacao": ano, "formato": "csv"}
    return JURISPRUDENCIA + "exportar?" + urllib.parse.urlencode(params)


def exportacao(conteudo: bytes) -> list[dict]:
    """As decisões do CSV de ``exportar``, como ``jurisprudencia`` as devolve (o CSV não traz o tipo da
    decisão: vale Acórdão, como na busca sem ``tipo_decisao``). Levanta ``ValueError`` se as colunas
    mudarem ou a resposta não for o CSV."""
    texto = conteudo.decode("utf-8-sig", errors="replace")
    linhas = csv.reader(io.StringIO(texto), delimiter=";")
    cabecalho = [c.strip() for c in next(linhas, [])]
    if any(c not in cabecalho for c in _COLUNAS_EXIGIDAS):
        raise ValueError("a exportação da jurisprudência do TCM-GO não traz as colunas do CSV")
    indices = {COLUNAS_EXPORTACAO[c]: i for i, c in enumerate(cabecalho) if c in COLUNAS_EXPORTACAO}
    saida = []
    for linha in linhas:
        if not any(x.strip() for x in linha):
            continue
        r = {k: (linha[i] if i < len(linha) else "") for k, i in indices.items()}
        if (d := _da_busca(r)) is not None:
            saida.append(d)
    return saida


def recusa_da_jurisprudencia(conteudo: bytes) -> str:
    """O motivo (``detail``) de uma recusa da busca, em uma linha; vazio se a resposta não o traz."""
    obj = cf.json_ou_none(conteudo)
    detalhe = obj.get("detail") if isinstance(obj, dict) else None
    return re.sub(r"\s+", " ", str(detalhe)).strip()[:200] if isinstance(detalhe, str) else ""


def valor_do_municipio(nome: str) -> str:
    """O ``valor`` do município na lista de ``filtros``: maiúsculas sem acento (Goiânia vira GOIANIA)."""
    sem_acento = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", sem_acento).strip().upper()


def _da_busca(r: dict) -> dict | None:
    """Uma decisão de ``buscar`` (ou uma linha de ``exportar`` com os mesmos nomes); None sem número ou ano."""
    bruto = str(r.get("numero_acordao") or "")
    numero = re.match(r"\s*(\d[\d.]*)", bruto)
    ano = str(r.get("ano_votacao") or "")
    if not ano.isdigit() and (m := re.search(r"/\s*(\d{4})", bruto)):
        ano = m.group(1)
    if not numero or not ano.isdigit():
        return None
    trecho = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(
        r.get("ementa") or r.get("assunto") or r.get("macro_assunto") or ""))).strip()
    doc = str(r.get("document_id") or "")
    d = _decisao(_tipo(str(r.get("tipo_decisao") or "Acórdão")), numero.group(1).replace(".", ""), ano,
                 trecho, JURISPRUDENCIA + "pdf/" + urllib.parse.quote(doc) if doc else "")
    d["data"] = cf.data(r.get("data_sessao"))
    d["relator"] = str(r.get("conselheiro_relator") or "")
    d["colegiado"] = str(r.get("orgao_julgador") or "")
    d["processo"] = str(r.get("numero_processo") or "") or d["processo"]
    onde = " ".join(str(r.get(k) or "") for k in ("entidade_fiscalizada", "entidade", "municipio"))
    d["sobre_goiania"] = int(sobre(onde) if onde.strip() else sobre(trecho))
    if r.get("resultado"):
        d["sumario"] = f"{d['sumario']} Resultado: {r['resultado']}.".strip()
    return d


def jurisprudencia(conteudo: bytes) -> tuple[list[dict], bool]:
    """As decisões de uma página de ``buscar`` e se há página seguinte. Decisão sem número ou ano fica
    de fora. Levanta ``ValueError`` se a resposta não traz ``data`` (formato mudado ou página de erro)."""
    obj = cf.json_ou_none(conteudo)
    if not isinstance(obj, dict) or not isinstance(obj.get("data"), list):
        raise ValueError("a pesquisa da jurisprudência do TCM-GO não traz data")  # noqa: TRY004
    saida = [d for r in obj["data"] if isinstance(r, dict) and (d := _da_busca(r)) is not None]
    paginacao = obj.get("pagination") if isinstance(obj.get("pagination"), dict) else {}
    if "has_next" in paginacao:
        mais = bool(paginacao["has_next"])
    else:
        mais = int(paginacao.get("page") or 0) < int(paginacao.get("total_pages") or 0)
    return saida, mais
