"""CEIS e CNEP: as empresas e pessoas sancionadas, pelo arquivo de dados abertos do Portal da Transparência.

``download-de-dados/ceis/AAAAMMDD`` e ``download-de-dados/cnep/AAAAMMDD`` devolvem um zip com um
CSV separado por ';' (latin-1): uma linha por sanção, com o CPF ou CNPJ do sancionado, a
categoria (inidoneidade, impedimento, suspensão, multa...), o início e o fim da sanção, o órgão
sancionador, a esfera e a UF dele e a abrangência definida em decisão judicial. O arquivo sai todo
dia; o do dia ainda pode não existir, e o coletor recua alguns dias até achar o mais recente.

O cabeçalho é lido pelo sentido das colunas (sem acento, sem caixa), não pela posição.

Sondagem de 27/11/2026: os endereços com a data (``download-de-dados/ceis/20261126`` e
``/20261125``, ``cnep/20261126``) deram HTTP 403 com 111 bytes, enquanto o arquivo de
transferências do mesmo portal (``download-de-dados/transferencias/202501``) baixou normalmente. A
API do Portal pede chave, que não temos. Por isso o coletor agora: (1) lê a página de download do
cadastro (``download-de-dados/ceis``), que diz quais datas estão publicadas; (2) para cada data, tenta
o endereço do portal e o do repositório de arquivos da CGU, para onde o portal encaminha o download
(``dadosabertos-download.cgu.gov.br/PortalDaTransparencia/saida/ceis/AAAAMMDD_CEIS.zip``). Sem
arquivo em nenhuma via, a situação fica ``nao_publicado`` e a conferência das contratadas aparece
como não feita (ficha do sistema), nunca como "nenhuma sanção".
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from datetime import date, datetime, timedelta

from . import comum_federal as cf

BASE = "https://portaldatransparencia.gov.br/download-de-dados/"
CGU = "https://dadosabertos-download.cgu.gov.br/PortalDaTransparencia/saida/"
CADASTROS = ("CEIS", "CNEP")
RECUO_DIAS = 7

# Coluna do CSV (normalizada) -> campo; o primeiro nome achado vale.
COLUNAS = {
    "cnpj_cpf": ("CPF OU CNPJ DO SANCIONADO", "CNPJ OU CPF DO SANCIONADO", "CPF/CNPJ DO SANCIONADO"),
    "nome": ("NOME DO SANCIONADO", "RAZAO SOCIAL - CADASTRO RECEITA", "NOME INFORMADO PELO ORGAO SANCIONADOR"),
    "tipo_pessoa": ("TIPO DE PESSOA",),
    "tipo": ("CATEGORIA DA SANCAO", "TIPO DE SANCAO", "TIPO SANCAO"),
    "inicio": ("DATA INICIO SANCAO", "DATA DE INICIO DA SANCAO", "DATA INICIO DA SANCAO"),
    "fim": ("DATA FINAL SANCAO", "DATA FIM SANCAO", "DATA DE FIM DA SANCAO", "DATA FINAL DA SANCAO"),
    "orgao": ("ORGAO SANCIONADOR", "NOME DO ORGAO SANCIONADOR"),
    "uf_orgao": ("UF ORGAO SANCIONADOR", "UF DO ORGAO SANCIONADOR"),
    "esfera": ("ESFERA ORGAO SANCIONADOR", "ESFERA DO ORGAO SANCIONADOR"),
    "abrangencia": ("ABRAGENCIA DEFINIDA EM DECISAO JUDICIAL", "ABRANGENCIA DEFINIDA EM DECISAO JUDICIAL",
                    "ABRANGENCIA DA SANCAO"),
    "processo": ("NUMERO DO PROCESSO",),
    "fundamentacao": ("FUNDAMENTACAO LEGAL",),
    "publicacao": ("DATA PUBLICACAO", "DATA DE PUBLICACAO"),
    "multa": ("VALOR DA MULTA",),
    "codigo": ("CODIGO DA SANCAO",),
}
OBRIGATORIAS = ("cnpj_cpf", "tipo", "inicio")


def url(cadastro: str, dia: date) -> str:
    return f"{BASE}{cadastro.lower()}/{dia:%Y%m%d}"


def dias_para_tentar(hoje: date, recuo: int = RECUO_DIAS) -> list[date]:
    return [hoje - timedelta(days=n) for n in range(recuo + 1)]


def url_cgu(cadastro: str, dia: date) -> str:
    """O arquivo no repositório da CGU, para onde o download do portal encaminha."""
    return f"{CGU}{cadastro.lower()}/{dia:%Y%m%d}_{cadastro.upper()}.zip"


def urls(cadastro: str, dia: date) -> list[str]:
    return [url(cadastro, dia), url_cgu(cadastro, dia)]


def url_indice(cadastro: str) -> str:
    """A página de download do cadastro, que lista a data do arquivo publicado."""
    return f"{BASE}{cadastro.lower()}"


def datas_publicadas(pagina: str, cadastro: str) -> list[date]:
    """As datas de arquivo que a página de download anuncia, da mais recente para a mais antiga:
    links ``.../ceis/AAAAMMDD``, nomes ``AAAAMMDD_CEIS`` e objetos ``{"ano": "2026", "mes": "11",
    "dia": "26"}`` do script da página."""
    achadas: set[date] = set()
    cad = cadastro.lower()
    padroes = (rf"(?i)/{cad}/(\d{{8}})\b", rf"(?i)\b(\d{{8}})_{cad}\b")
    for padrao in padroes:
        for m in re.finditer(padrao, pagina):
            try:
                achadas.add(datetime.strptime(m.group(1), "%Y%m%d").date())
            except ValueError:
                pass
    for m in re.finditer(r'(?is)["\']?ano["\']?\s*:\s*["\']?(\d{4})["\']?\s*,\s*["\']?mes["\']?\s*:\s*'
                         r'["\']?(\d{1,2})["\']?\s*,\s*["\']?dia["\']?\s*:\s*["\']?(\d{1,2})', pagina):
        try:
            achadas.add(date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        except ValueError:
            pass
    return sorted(achadas, reverse=True)


def ler(conteudo: bytes, cadastro: str) -> list[dict]:
    """As sanções do arquivo, uma por linha, com as datas em ISO e o CPF/CNPJ só com dígitos
    (o CPF vem mascarado pelo Portal e fica como veio, sem os asteriscos).

    Levanta ``ValueError`` se não é o zip esperado ou se faltam as colunas essenciais.
    """
    try:
        arquivo = zipfile.ZipFile(io.BytesIO(conteudo))
    except zipfile.BadZipFile as e:
        raise ValueError(f"não é zip: {e}") from e
    nomes = [n for n in arquivo.namelist() if n.lower().endswith(".csv")]
    if not nomes:
        raise ValueError("o zip não traz CSV")
    with arquivo.open(nomes[0]) as bruto:
        texto = io.TextIOWrapper(bruto, encoding="latin-1", newline="")
        leitor = csv.reader(texto, delimiter=";")
        cabecalho = [cf.norm(c) for c in next(leitor, [])]
        idx = {}
        for campo, nomes_possiveis in COLUNAS.items():
            for n in nomes_possiveis:
                if n in cabecalho:
                    idx[campo] = cabecalho.index(n)
                    break
        faltam = [c for c in OBRIGATORIAS if c not in idx]
        if faltam:
            raise ValueError(f"o cabeçalho mudou: faltam {', '.join(faltam)}")
        saida = []
        for linha in leitor:
            if not linha or len(linha) <= max(idx.values()):
                continue
            reg = {c: linha[i].strip() for c, i in idx.items()}
            ni = cf.digitos(reg["cnpj_cpf"])
            if not ni:
                continue
            saida.append({
                "cnpj_cpf": ni,
                "cadastro": cadastro.upper(),
                "inicio": cf.data(reg.get("inicio")),
                "fim": cf.data(reg.get("fim")),
                "orgao": reg.get("orgao", ""),
                "tipo": reg.get("tipo", ""),
                "nome": reg.get("nome", ""),
                "tipo_pessoa": reg.get("tipo_pessoa", "") or ("J" if len(ni) == 14 else "F"),
                "uf_orgao": reg.get("uf_orgao", ""),
                "esfera": reg.get("esfera", ""),
                "abrangencia": reg.get("abrangencia", ""),
                "processo": reg.get("processo", ""),
                "fundamentacao": reg.get("fundamentacao", "")[:500],
                "publicacao": cf.data(reg.get("publicacao")),
                "multa": cf.numero(reg.get("multa")),
                "codigo": reg.get("codigo", ""),
            })
    return saida


# --- Alcance da sanção (para a conferência; restritivo: na dúvida, alerta) ----------------------

def impede_contratar(tipo: str) -> bool:
    """Categorias que tiram a empresa de licitações e contratos. Multa, advertência e publicação
    extraordinária não impedem; tudo o mais (inidoneidade, impedimento, suspensão, proibição,
    acordo de leniência não cumprido...) conta, porque na dúvida é alerta."""
    t = cf.norm(tipo)
    if any(x in t for x in ("INIDONE", "IMPEDIMENTO", "IMPEDID", "SUSPENS", "PROIBI")):
        return True
    if any(x in t for x in ("MULTA", "ADVERTENCIA", "PUBLICACAO EXTRAORDINARIA", "ACORDO DE LENIENCIA")):
        return False
    return True


def alcanca_o_municipio(s: dict, municipio: str = "GOIANIA", uf: str = "GO") -> str:
    """'todos' (inidoneidade ou abrangência nacional), 'municipio' (aplicada pelo próprio Município),
    ou 'outro_ente' (impedimento ou suspensão aplicado por outro ente: alcance a conferir)."""
    t = cf.norm(s.get("tipo"))
    abr = cf.norm(s.get("abrangencia"))
    if "INIDONE" in t or any(x in abr for x in ("TODAS AS ESFERAS", "NACIONAL", "TODO O TERRITORIO")):
        return "todos"
    orgao = cf.norm(s.get("orgao"))
    if municipio in orgao and cf.norm(s.get("uf_orgao")) in ("", uf):
        return "municipio"
    return "outro_ente"
