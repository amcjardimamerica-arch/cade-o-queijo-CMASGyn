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
"""

from __future__ import annotations

import html as html_lib
import re
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


def contas(conteudo: bytes, municipio: str = "Goiânia") -> list[dict]:
    """As linhas do Município numa lista de contas (JSON ou tabela HTML). O Município é procurado nos
    campos de município, ente, órgão ou entidade, com a mesma regra que separa Goiânia de Aparecida de
    Goiânia. Levanta ``ValueError`` se a resposta não tiver lista nem tabela."""
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
