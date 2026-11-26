"""Transferências federais do mês, pelo arquivo de dados abertos do Portal da Transparência.

O arquivo ``download-de-dados/transferencias/AAAAMM`` (zip com um CSV separado por ';', em
latin-1) traz, linha a linha, o que a União transferiu no mês: as constitucionais (FPM, ITR,
FUNDEB, complementação da União, CIDE, royalties), as legais (SUS fundo a fundo, salário-educação,
FNAS) e as voluntárias, por ação orçamentária e favorecido. Vem do SIAFI, a mesma base das
planilhas do Tesouro, e é a via independente das receitas de transferência do RREO.
"""

from __future__ import annotations

import csv
import io
import unicodedata
import zipfile
from collections import defaultdict

BASE = "https://portaldatransparencia.gov.br/download-de-dados/transferencias/"

# Coluna do CSV -> campo guardado no banco.
CAMPOS = {
    "TIPO TRANSFERÊNCIA": "tipo",
    "TIPO FAVORECIDO": "tipo_favorecido",
    "NOME ÓRGÃO": "orgao",
    "NOME FUNÇÃO": "funcao",
    "NOME PROGRAMA": "programa",
    "AÇÃO": "acao",
    "NOME AÇÃO": "nome_acao",
    "CÓDIGO FAVORECIDO": "favorecido",
    "NOME FAVORECIDO": "nome_favorecido",
}


def url_mes(mes: str) -> str:
    """``mes`` em AAAA-MM."""
    return BASE + mes.replace("-", "")


def _norm(t: str) -> str:
    return unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().upper().strip()


def _valor(t: str) -> float:
    t = (t or "").strip()
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    return float(t) if t else 0.0


def linhas_do_municipio(conteudo: bytes, municipio: str, uf: str) -> list[dict]:
    """As linhas do município no arquivo do mês, somadas por ação e favorecido.

    Levanta ``ValueError`` se o arquivo não é o zip esperado ou se o cabeçalho mudou.
    """
    try:
        arquivo = zipfile.ZipFile(io.BytesIO(conteudo))
    except zipfile.BadZipFile as e:
        raise ValueError(f"não é zip: {e}") from e
    nomes = [n for n in arquivo.namelist() if n.lower().endswith(".csv")]
    if not nomes:
        raise ValueError("o zip não traz CSV")
    alvo_mun, alvo_uf = _norm(municipio), _norm(uf)
    somas: dict[tuple, float] = defaultdict(float)
    with arquivo.open(nomes[0]) as bruto:
        leitor = csv.reader(io.TextIOWrapper(bruto, encoding="latin-1", newline=""), delimiter=";")
        cabecalho = next(leitor, None) or []
        idx = {nome: i for i, nome in enumerate(cabecalho)}
        faltam = [c for c in ("ANO / MÊS", "UF", "NOME MUNICÍPIO", "VALOR TRANSFERIDO", *CAMPOS) if c not in idx]
        if faltam:
            raise ValueError(f"o cabeçalho mudou: faltam {', '.join(faltam)}")
        i_mun, i_uf, i_mes, i_valor = idx["NOME MUNICÍPIO"], idx["UF"], idx["ANO / MÊS"], idx["VALOR TRANSFERIDO"]
        colunas = [idx[c] for c in CAMPOS]
        for linha in leitor:
            if len(linha) <= i_valor or _norm(linha[i_uf]) != alvo_uf or _norm(linha[i_mun]) != alvo_mun:
                continue
            aaaamm = linha[i_mes].strip()
            chave = (f"{aaaamm[:4]}-{aaaamm[4:6]}", *(linha[i].strip() for i in colunas))
            somas[chave] += _valor(linha[i_valor])
    saida = []
    for chave, valor in somas.items():
        registro = {"mes": chave[0], **dict(zip(CAMPOS.values(), chave[1:])), "valor": round(valor, 2)}
        saida.append(registro)
    saida.sort(key=lambda r: (r["mes"], r["tipo"], r["nome_acao"], r["nome_favorecido"]))
    return saida
