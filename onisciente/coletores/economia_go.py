"""Economia GO: a cota-parte do ICMS e do IPVA que o Estado de Goiás entrega ao Município.

A cota do ICMS (25% do arrecadado, CF, art. 158, IV) e a do IPVA (50%, CF, art. 158, III) são
receitas do Estado repassadas ao Município, e a Constituição manda o Estado divulgar, até o último
dia do mês seguinte ao da arrecadação, os montantes arrecadados, os valores entregues e a
entregar e os critérios de rateio (CF, art. 162; LC 63/1990, art. 5º). É a via do Estado, independente
da contabilidade do Município (RREO Anexo 3 e matriz de saldos contábeis, naturezas 1.7.2.1.50 e
1.7.2.1.51).

O coletor tenta os endereços de ``CANDIDATOS`` e lê o que vier em CSV, JSON ou tabela HTML,
procurando a linha do município e as colunas (ou linhas) de ICMS e IPVA. Numa página sem o dado,
segue os links do próprio Estado que falam de repasse aos municípios, de ICMS, de IPVA ou de índice
de participação. Se nenhum candidato trouxer o dado, a ausência é descumprimento de transparência
do Estado (CF, art. 162) e vira alerta roxo com ofício à Secretaria de Estado da Economia; a
conferência segue com a via do Município, que já está no banco.

Sondagem de 27/11/2026: a API e a página do Portal da Transparência de Goiás deram 404; o endereço
antigo da Economia (``www.economia.go.gov.br/...``) cai na página inicial do novo portal
(``goias.gov.br/economia/``), cujo menu aponta "Repasses de Recursos aos Municípios" para
``goias.gov.br/economia/repasse-aos-municipios/`` (no singular; o plural deu 404). O CKAN de dados
abertos (``dadosabertos.go.gov.br``) respondeu HTTP 200 com a página "Acesso Negado" do firewall do
Estado: isso é bloqueio, não ausência do dado, e o coletor o separa (``bloqueado``). As duas
respostas reais, reduzidas, estão em ``testes/dados/federais/economia_go_*_real.html``.
"""

from __future__ import annotations

import html as html_lib
import re
import urllib.parse

from . import comum_federal as cf

ORGAO = "Secretaria de Estado da Economia de Goiás"
FUNDAMENTO = "CF, art. 162; LC 63/1990, art. 5º; LC 101/2000, art. 48; Lei 12.527/2011, art. 8º"
TRIBUTOS = ("ICMS", "IPVA", "IPI")   # IPI: a cota do IPI-exportação que o Estado repassa (LC 61/1989)

# {ano}, {ibge} e {ibge6} são preenchidos. Ordem: dados abertos antes de páginas.
CANDIDATOS = (
    "https://goias.gov.br/economia/repasse-aos-municipios/",
    "https://dadosabertos.go.gov.br/api/3/action/package_search?q=repasse%20municipios%20icms&rows=20",
    "https://dadosabertos.go.gov.br/api/3/action/package_search?q=cota%20parte%20icms&rows=20",
    "https://goias.gov.br/economia/",
)
# Os sites do Estado cujos links o coletor segue.
SITES_DO_ESTADO = ("goias.gov.br", "economia.go.gov.br", "transparencia.go.gov.br", "dadosabertos.go.gov.br")
ARQUIVOS = (".csv", ".json", ".xls", ".xlsx", ".ods", ".pdf", ".zip", ".txt")
LEGIVEIS = (".csv", ".json", ".txt")



def urls(ano: int, ibge: int | str) -> list[str]:
    ibge = str(ibge)
    return [c.format(ano=ano, ibge=ibge, ibge6=ibge[:6]) for c in CANDIDATOS]


def _tributo(texto) -> str | None:
    t = cf.norm(texto)
    for trib in TRIBUTOS:
        if re.search(rf"\b{trib}\b", t):
            return trib
    return None


def _mes(registro: dict, ano: int | None) -> str | None:
    v = cf.campo(registro, "mes_ano", "competencia", "periodo", "data", "data_repasse", "referencia",
                 contem=("competencia", "periodo", "data"))
    if v is not None and (m := cf.mes_de(v)):
        return m
    mes = cf.campo(registro, "mes", "nr_mes", "num_mes")
    a = cf.campo(registro, "ano", "exercicio") or ano
    if mes is not None and a is not None:
        nomes = ("JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ")
        n = cf.norm(mes)[:3]
        num = nomes.index(n) + 1 if n in nomes else (int(cf.digitos(mes)) if cf.digitos(mes) else None)
        if num and 1 <= num <= 12:
            return f"{int(a)}-{num:02d}"
    return None


def repasses(registros: list[dict], municipio: str, ano: int | None = None) -> list[dict]:
    """Os repasses de ICMS e IPVA ao município, em forma larga (colunas ICMS e IPVA) ou longa
    (uma coluna diz o tributo e outra o valor). Valores do mesmo mês e tributo se somam."""
    alvo = cf.norm(municipio)
    somas: dict[tuple[str, str], float] = {}
    for r in registros:
        nome_mun = cf.campo(r, "municipio", "nome_municipio", "municipio_nome", "ente", contem=("municipio",))
        if nome_mun is None or cf.norm(nome_mun) != alvo:
            continue
        mes = _mes(r, ano)
        if mes is None:
            continue
        tributo_da_linha = _tributo(cf.campo(r, "tributo", "receita", "imposto", "tipo", contem=("tributo",)))
        if tributo_da_linha:
            v = cf.numero(cf.campo(r, "valor", "valor_repassado", "valor_liquido", "total", contem=("valor",)))
            if v is not None:
                somas[(mes, tributo_da_linha)] = somas.get((mes, tributo_da_linha), 0.0) + v
            continue
        for k, v in r.items():
            trib = _tributo(k)
            valor = cf.numero(v)
            if trib and valor is not None and "INDICE" not in cf.norm(k):
                somas[(mes, trib)] = somas.get((mes, trib), 0.0) + valor
    return [{"mes": m, "tributo": t, "valor": round(v, 2)} for (m, t), v in sorted(somas.items())]


def ler(conteudo: bytes, municipio: str, ano: int | None = None) -> list[dict]:
    """Os repasses do município numa resposta de qualquer candidato (JSON, CSV ou tabela HTML).
    Lista vazia quando a resposta não traz o município ou os tributos."""
    obj = cf.json_ou_none(conteudo)
    if obj is not None:
        regs = cf.registros_json(obj) or []
        return repasses(regs, municipio, ano)
    linhas = cf.linhas_csv(conteudo)
    if linhas:
        return repasses(linhas, municipio, ano)
    texto = cf.decodificar(conteudo)
    saida: list[dict] = []
    for tabela in cf.tabelas_html(texto):
        saida.extend(repasses(cf.tabela_como_registros(tabela), municipio, ano))
    return saida


def bloqueado(conteudo: bytes) -> bool:
    """A página de bloqueio do firewall do Estado ("Acesso Negado"), que vem com HTTP 200."""
    t = cf.norm(re.sub(r"<[^>]+>", " ", cf.decodificar(conteudo[:20000])))
    return "ACESSO NEGADO" in t and ("BLOQUEAD" in t or "POLITICA DE SEGURANCA" in t)


def links_de_repasse(pagina: str, base: str) -> list[str]:
    """Os links da página, nos sites do Estado, que levam à cota dos municípios: o texto ou o
    endereço fala de repasse aos municípios, de ICMS ou IPVA, de cota-parte ou de índice de
    participação. Arquivos de dados vêm primeiro."""
    achados: list[str] = []
    for href, rotulo in cf.links(pagina, ""):
        alvo = urllib.parse.urljoin(base, html_lib.unescape(href.strip()))
        if not alvo.startswith("http"):
            continue
        host = urllib.parse.urlparse(alvo).netloc.lower()
        if not any(host == s or host.endswith("." + s) for s in SITES_DO_ESTADO):
            continue
        texto = cf.norm(f"{rotulo} {urllib.parse.unquote(alvo)}").replace("-", " ").replace("_", " ")
        repasse = "REPASSE" in texto and "MUNIC" in texto
        tributo = re.search(r"\b(ICMS|IPVA)\b", texto) and re.search(r"MUNIC|REPASSE|COTA|INDICE|PARTICIPA", texto)
        if repasse or tributo or ("INDICE" in texto and "PARTICIPA" in texto):
            achados.append(alvo.split("#")[0])
    arquivos = [u for u in achados if urllib.parse.urlparse(u).path.lower().endswith(ARQUIVOS)]
    return list(dict.fromkeys(arquivos + [u for u in achados if u not in arquivos]))


def legivel(url: str) -> bool:
    """Se o coletor lê o arquivo (CSV, JSON, texto) ou só registra que existe (PDF, planilha, zip)."""
    caminho = urllib.parse.urlparse(url).path.lower()
    return not caminho.endswith(ARQUIVOS) or caminho.endswith(LEGIVEIS)
