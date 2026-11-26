"""Sondagem das fontes federais ainda sem coletor (SIOPE, SIOPS, Tesouro, FNS, FNDE, Transferegov).

Roda no GitHub, onde a rede é aberta. Para cada endereço candidato guarda o código de resposta,
o tipo e o começo do corpo em ``relatorios/onisciente/sondagem/``. Quando a fonte é um catálogo
CKAN ou um serviço OData, lista os recursos e lê uma amostra pequena de cada um. Só lê; não
grava nada no banco. O resultado serve para escrever os coletores sem adivinhar endereço.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from http.cookiejar import CookieJar
from urllib.parse import quote
from urllib.request import HTTPCookieProcessor, build_opener, install_opener

from . import RAIZ
from .coletores.base import ler

PASTA = RAIZ / "relatorios" / "onisciente" / "sondagem"
LIMITE = 600_000

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
    "transferegov": [
        "https://api.transferegov.gestao.gov.br/transferenciasespeciais/",
        "https://api.transferegov.gestao.gov.br/fundoafundo/",
        "https://api.transferegov.gestao.gov.br/ted/",
    ],
}


def _slug(url: str, formulario: dict | None = None) -> str:
    chave = url + json.dumps(formulario or {}, sort_keys=True)
    curto = re.sub(r"[^a-z0-9]+", "-", url.lower().split("://", 1)[-1])[:70].strip("-")
    return f"{curto}-{hashlib.sha256(chave.encode()).hexdigest()[:8]}"


def _guardar(fonte: str, url: str, leitura, formulario: dict | None = None) -> dict:
    PASTA.mkdir(parents=True, exist_ok=True)
    arq = PASTA / f"{fonte}__{_slug(url, formulario)}.txt"
    bruto = leitura.conteudo[:LIMITE]
    if leitura.ok and bruto.startswith(b"%PDF"):      # binário: os bytes como vieram, em base64
        arq.with_suffix(".pdf.b64").write_text(base64.b64encode(leitura.conteudo).decode())
    try:
        corpo = bruto.decode("utf-8") if leitura.ok else ""
    except UnicodeDecodeError:
        corpo = bruto.decode("latin-1")
    arq.write_text(f"URL: {url}\nPOST: {json.dumps(formulario or {}, ensure_ascii=False)}\nOK: {leitura.ok}\nHTTP: {leitura.http}\nERRO: {leitura.erro}\n"
                   f"BYTES: {len(leitura.conteudo)}\n\n{corpo}", encoding="utf-8")
    return {"fonte": fonte, "url": url, "post": formulario, "ok": leitura.ok, "http": leitura.http, "erro": leitura.erro,
            "bytes": len(leitura.conteudo), "arquivo": arq.name}


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


def _seguir(fonte: str, url: str, leitura) -> list:
    """Endereços de segunda rodada: amostras de conjuntos OData e recursos CKAN."""
    if not leitura.ok:
        return []
    texto = leitura.texto
    novos: list = []
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


def sondar(fontes: list[str] | None = None) -> list[dict]:
    resultado = []
    install_opener(build_opener(HTTPCookieProcessor(CookieJar())))   # sessão, como num navegador
    for fonte, urls in CANDIDATOS.items():
        if fontes and fonte not in fontes:
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
            leitura = ler(url, tempo=60, fonte=fonte, formulario=formulario)
            resultado.append(_guardar(fonte, url, leitura, formulario))
            if item in urls:
                fila.extend(_seguir(fonte, url, leitura))
    nome = "indice.json" if not fontes else f"indice_{'_'.join(fontes)}.json"
    (PASTA / nome).write_text(json.dumps(
        {"quando": datetime.now(timezone.utc).isoformat(timespec="seconds"), "leituras": resultado},
        ensure_ascii=False, indent=1), encoding="utf-8")
    return resultado


if __name__ == "__main__":
    for r in sondar([f for f in sys.argv[1:] if f] or None):
        print(("OK " if r["ok"] else "FALHA ") + f"{r['fonte']}: {r['url']} {r['http'] or r['erro']}")
