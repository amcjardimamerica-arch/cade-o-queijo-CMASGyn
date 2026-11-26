"""SIOPS: o demonstrativo da saúde (RREO Anexo 12) como o Ministério da Saúde o publica.

O SICONFI não traz o Anexo 12 de Goiânia; ele nasce no SIOPS, homologado pelo Município.
A consulta pública é um formulário: escolhe-se ano, UF, período e município, e o botão
Consultar envia tudo por POST para ``rel_LRF.php``. Este módulo lê a página de escolha
(os códigos dos bimestres e do município) e a tabela do demonstrativo, linha a linha,
sem interpretar nada: a interpretação fica em ``onisciente.fiscal``.
"""

from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass, field

ESCOLHA = "http://siops.datasus.gov.br/consleirespfiscal.php"
RELATORIO = "http://siops.datasus.gov.br/rel_LRF.php"


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode()
    return " ".join(t.upper().split())


def texto(conteudo: bytes) -> str:
    """A página declara iso-8859-15, mas nem sempre é: tenta UTF-8 antes."""
    try:
        return conteudo.decode("utf-8")
    except UnicodeDecodeError:
        return conteudo.decode("latin-1")


def url_escolha(uf: str, ano: int) -> str:
    return f"{ESCOLHA}?UF={uf}&Ano={ano}&Periodo=1&Municipio=&MudouAno=true"


def formulario(ano: int, uf: str, codigo_periodo: str, municipio: str) -> dict:
    return {"cmbAno": str(ano), "cmbUF": uf, "cmbPeriodo": codigo_periodo,
            "cmbMunicipio[]": municipio, "BtConsultar": "Consultar"}


def periodos(pagina: str) -> dict[int, str]:
    """Bimestre (1 a 6) -> código que o SIOPS usa no formulário daquele ano."""
    sel = re.search(r"(?is)name='cmbPeriodo'.*?</select>", pagina)
    if not sel:
        return {}
    achados = {}
    for codigo, rotulo in re.findall(r"(?i)value='(\d+)'[^>]*>\s*(\d)\s*º?\s*Bimestre", sel.group(0)):
        achados[int(rotulo)] = codigo
    return achados


def codigo_municipio(pagina: str, municipio: str) -> str | None:
    alvo = _norm(municipio)
    for codigo, nome in re.findall(r"(?i)<option[^>]*value='(\d{6,7})'[^>]*>\s*([^<\n]+)", pagina):
        if _norm(nome) == alvo:
            return codigo
    return None


def numero(celula: str) -> float | None:
    t = celula.strip().replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


@dataclass
class Linha:
    quadro: int          # cada cabeçalho abre um quadro novo
    titulo_quadro: str
    ordem: int
    rotulo: str
    valores: list[float | None]


@dataclass
class Demonstrativo:
    municipio: str = ""
    exercicio: int | None = None
    bimestre: int | None = None
    homologado: str = ""
    linhas: list[Linha] = field(default_factory=list)

    def procurar(self, padrao: str, quadro_padrao: str | None = None) -> Linha | None:
        """A primeira linha cujo rótulo casa com o padrão (sem acento, maiúsculas)."""
        rx = re.compile(padrao)
        qx = re.compile(quadro_padrao) if quadro_padrao else None
        for linha in self.linhas:
            if rx.search(_norm(linha.rotulo)) and (qx is None or qx.search(_norm(linha.titulo_quadro))):
                return linha
        return None


def _celulas(linha_html: str) -> list[str]:
    brutas = re.findall(r"(?is)<t[dh][^>]*>(.*?)</t[dh]>", linha_html)
    return [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", c))).strip() for c in brutas]


def ler(pagina: str) -> Demonstrativo:
    """A tabela do demonstrativo, linha a linha. Levanta ValueError se não for o demonstrativo."""
    if "ACOES E SERVICOS PUBLICOS DE SAUDE" not in _norm(re.sub(r"<[^>]+>", " ", pagina)):
        raise ValueError("a página não traz o demonstrativo da saúde (ASPS)")
    d = Demonstrativo()
    quadro, titulo, ordem = 0, "", 0
    for bruto in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", pagina):
        celulas = [c for c in _celulas(bruto)]
        if not any(celulas):
            continue
        primeira = celulas[0]
        norm = _norm(" ".join(celulas))
        if m := re.search(r"MUNICIPIO: (.+)$", _norm(primeira) + " " + " ".join(_norm(c) for c in celulas[1:])):
            d.municipio = m.group(1).strip()
        cabeca = not d.linhas                      # o título vem antes da primeira linha de valores
        if cabeca and (m := re.search(r"^EXERCICIO DE (\d{4})$", norm)):
            d.exercicio = int(m.group(1))
        if cabeca and (m := re.search(r"^(\d)O? BIMESTRE DE (\d{4})$", norm)):
            d.bimestre, d.exercicio = int(m.group(1)), int(m.group(2))
        if m := re.search(r"HOMOLOGADOS EM ([\d/]+ [\d:]+)", norm):
            d.homologado = m.group(1)
        valores = [numero(c) if c not in ("N/A", "") else None for c in celulas[1:]]
        numericas = [v for v in valores if v is not None]
        nao_numericas = [c for c in celulas[1:] if c and c != "N/A" and numero(c) is None]
        if len(celulas) > 1 and nao_numericas:          # cabeçalho de um quadro
            quadro += 1
            titulo = primeira
            continue
        if numericas or (len(celulas) > 1 and all(c == "N/A" for c in celulas[1:])):
            ordem += 1
            d.linhas.append(Linha(quadro, titulo, ordem, primeira, valores))
    if d.exercicio is None or not d.linhas:
        raise ValueError("demonstrativo sem exercício ou sem linhas")
    if d.bimestre is None:
        d.bimestre = 6          # o relatório do último bimestre não traz o número: é o anual
    return d
