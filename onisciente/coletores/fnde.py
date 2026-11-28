"""FNDE: as liberações do Fundo Nacional de Desenvolvimento da Educação às entidades do Município.

A consulta pública de liberações do FNDE (SIMAD, ``www.fnde.gov.br/pls/simad``) funciona em dois
passos, como o botão de uma página: um POST com o ano, a UF e o código IBGE de 6 dígitos devolve a
lista das entidades do município (Prefeitura, conselhos escolares, unidades executoras), cada uma
com o CNPJ; as liberações de cada entidade saem do mesmo endereço, pelo formulário oculto da página
(``formOculto``, que a função ``enviarFormulario`` preenche com o ano, o programa, a UF, o município,
o tipo de entidade e o CNPJ em ``p_cgc``). O formulário não declara método, então vai por GET.

A sondagem de 27/11/2026 confirmou o primeiro passo com a página real de Goiânia em 2025 (guardada
em ``testes/dados/federais/fnde_entidades_real.html``, reduzida): 406 entidades com CNPJ e centenas
de pessoas físicas (bolsistas) sem CNPJ, que ficam de fora porque não há liberação a pedir por CNPJ
e porque o nome de pessoa não é dado de entidade. O endereço antigo das liberações por CNPJ
(``liberacoes_01_result_pc``) deu 404. A página de liberações de uma entidade ainda não foi lida na
sondagem: o leitor dela segue o formato presumido (programa a programa, com data, ordem bancária,
banco, agência, conta e valor, e a linha "Total:").

A soma das liberações é conferida com a linha "Total:" da própria página: se não fechar, a leitura
está errada (formato mudado) e o coletor falha às claras.
"""

from __future__ import annotations

import re

from . import comum_federal as cf

BASE = "https://www.fnde.gov.br/pls/simad/"
FORMULARIO = BASE + "internet_fnde.liberacoes_01_pc"
ENTIDADES = BASE + "internet_fnde.liberacoes_result_pc"
LIBERACOES = ENTIDADES          # o formOculto da lista manda o CNPJ (p_cgc) ao mesmo endereço

# enviarFormulario('ano', 'programa', 'uf', 'municipio', 'tipo de entidade', 'cnpj'), seguido do rótulo do link.
CHAMADA = re.compile(r"enviarFormulario\(\s*'([^']*)'\s*,\s*'([^']*)'\s*,\s*'([^']*)'\s*,\s*'([^']*)'\s*,"
                     r"\s*'([^']*)'\s*,\s*'([^']*)'\s*\)\s*;?\s*\"?\s*>\s*([^<]*)<")

DATA = re.compile(r"^\d{2}/\d{2}/\d{4}$")
CNPJ = re.compile(r"\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}")


def formulario(ano: int, uf: str, ibge6: str) -> dict:
    """Os campos do botão Consultar da página de liberações."""
    return {"p_ano": str(ano), "p_programa": "", "p_uf": uf, "p_municipio": str(ibge6)[:6],
            "p_tp_entidade": ""}


def url_liberacoes(ano: int, cnpj: str, uf: str = "", ibge6: str = "", programa: str = "",
                   tp_entidade: str = "") -> str:
    """O formOculto da lista de entidades, com o CNPJ da entidade, como o navegador o envia (GET)."""
    return (f"{LIBERACOES}?p_ano={ano}&p_programa={programa}&p_uf={uf}&p_municipio={str(ibge6)[:6]}"
            f"&p_tp_entidade={tp_entidade}&p_cgc={cf.digitos(cnpj)}")


def entidades(pagina: str) -> list[dict]:
    """As entidades do município na lista do SIMAD: CNPJ, nome e o endereço das liberações.

    Lê as chamadas ``enviarFormulario(...)`` da página real (o CNPJ vem em ``p_cgc``; as pessoas
    físicas vêm com ``p_cgc`` vazio e ficam de fora), os links com ``p_cgc=`` e, por fim, as células
    com CNPJ das tabelas. Levanta ``ValueError`` se a página não traz nenhuma entidade com CNPJ.
    """
    vistos: dict[str, dict] = {}
    for ano, programa, uf, municipio, tp, cgc, rotulo in CHAMADA.findall(pagina):
        cnpj = cf.digitos(cgc)
        if len(cnpj) != 14:
            continue
        item = vistos.setdefault(cnpj, {"cnpj": cnpj, "nome": "",
                                        "url": url_liberacoes(ano, cnpj, uf, municipio, programa, tp)})
        rotulo = re.sub(r"\s+", " ", rotulo).strip()
        if rotulo and not CNPJ.fullmatch(rotulo):
            item["nome"] = item["nome"] or rotulo
    for href, rotulo in cf.links(pagina, ENTIDADES):
        if m := re.search(r"p_cgc=(\d{14})", href):
            nome = "" if CNPJ.fullmatch(rotulo.strip()) else rotulo
            vistos.setdefault(m.group(1), {"cnpj": m.group(1), "nome": nome, "url": None})
    for tabela in cf.tabelas_html(pagina):
        for linha in tabela:
            for i, celula in enumerate(linha):
                if CNPJ.fullmatch(celula.strip()):
                    cnpj = cf.digitos(celula)
                    nome = next((c for c in linha[i + 1:] if c and not CNPJ.fullmatch(c)), "")
                    if len(cnpj) != 14:
                        continue
                    item = vistos.setdefault(cnpj, {"cnpj": cnpj, "nome": nome, "url": None})
                    item["nome"] = item["nome"] or nome
    if not vistos:
        if "NENHUM" in cf.norm(re.sub(r"<[^>]+>", " ", pagina)):
            return []
        raise ValueError("a página não traz a lista de entidades com CNPJ")
    return sorted(vistos.values(), key=lambda e: e["cnpj"])


MESES = {"JAN": 1, "FEV": 2, "MAR": 3, "ABR": 4, "MAI": 5, "JUN": 6, "JUL": 7, "AGO": 8, "SET": 9, "OUT": 10,
         "NOV": 11, "DEZ": 12}
DATA_SIMAD = re.compile(r"^(\d{2})/([A-Za-z]{3})/(\d{4})$")


def _data(texto: str) -> str | None:
    """A data do SIMAD (06/FEV/2025) ou dd/mm/aaaa, em ISO."""
    m = DATA_SIMAD.match(texto.strip())
    if m and cf.norm(m.group(2)) in MESES:
        return f"{m.group(3)}-{MESES[cf.norm(m.group(2))]:02d}-{m.group(1)}"
    return cf.data(texto) if DATA.match(texto.strip()) else None


def _coluna(cabeca: list[str], *nomes: str) -> int | None:
    normal = [cf.norm(c).rstrip(".:") for c in cabeca]
    for nome in nomes:
        if nome in normal:
            return normal.index(nome)
    return None


def _liberacoes_com_cabecalho(pagina: str) -> tuple[list[dict], float | None, int]:
    """O formato real (sondagem de 28/11/2026): cada programa é uma tabela; a primeira linha, de
    uma célula, é o nome do grupo (ALIMENTAÇÃO ESCOLAR..., QUOTA - QUOTA ESTADUAL / MUNICIPAL...);
    a segunda é o cabeçalho (Data Pgto, OB, Valor, [Parcela,] Programa, Banco, Agência, C/C); depois
    as liberações, com a data em 06/FEV/2025 e o banco pelo nome; por fim a linha "Total:".
    Devolve as liberações, a soma dos totais e quantas tabelas tinham o cabeçalho."""
    saida: list[dict] = []
    total, tabelas = None, 0
    for tabela in cf.tabelas_html(pagina):
        grupo, cabeca = "", None
        soma, total_tabela = 0.0, None
        for linha in tabela:
            textos = [c for c in linha if c]
            if not textos:
                continue
            junto = cf.norm(" ".join(textos))
            if cabeca is None:
                if _coluna(linha, "DATA PGTO", "DATA PAGAMENTO", "DATA") is not None and \
                        _coluna(linha, "VALOR") is not None:
                    cabeca = linha
                    tabelas += 1
                elif len(textos) == 1:
                    grupo = re.sub(r"(?i)^programa\s*:?\s*", "", textos[0]).strip()
                continue
            if len(textos) == 1 and not junto.startswith("TOTAL"):
                grupo = re.sub(r"(?i)^programa\s*:?\s*", "", textos[0]).strip()     # outro programa na mesma tabela
                continue
            if junto.startswith("TOTAL"):
                valores = [cf.numero(c) for c in textos[1:] if cf.numero(c) is not None]
                if valores:
                    total_tabela = (total_tabela or 0.0) + valores[-1]
                continue
            pos = {k: _coluna(cabeca, *n) for k, n in (
                ("data", ("DATA PGTO", "DATA PAGAMENTO", "DATA")), ("ob", ("OB", "ORDEM BANCARIA")),
                ("valor", ("VALOR",)), ("parcela", ("PARCELA",)), ("programa", ("PROGRAMA",)),
                ("banco", ("BANCO",)), ("agencia", ("AGENCIA",)), ("conta", ("C/C", "CONTA", "CONTA CORRENTE")))}

            def cel(chave, pos=pos, linha=linha):
                i = pos[chave]
                return linha[i].strip() if i is not None and i < len(linha) else ""

            data, valor = _data(cel("data")), cf.numero(cel("valor"))
            if data is None or valor is None:
                continue
            programa = cel("programa")
            saida.append({
                "programa": f"{programa} ({grupo})" if programa and grupo else (programa or grupo),
                "data": data, "ordem_bancaria": cel("ob"), "banco": cel("banco"), "agencia": cel("agencia"),
                "conta": cel("conta"), "valor": valor,
            })
            soma += valor
        if total_tabela is not None:
            if abs(soma - total_tabela) > 0.01 * max(len(tabela), 1) + 0.01:
                raise ValueError(f"a soma das liberações de {grupo or 'um programa'} ({soma:.2f}) não fecha "
                                 f"com o Total da página ({total_tabela:.2f})")
            total = (total or 0.0) + total_tabela
    return saida, total, tabelas


def liberacoes(pagina: str) -> tuple[list[dict], float | None]:
    """As liberações de uma entidade e o total que a página declara.

    Primeiro o formato real, com cabeçalho em cada tabela (``_liberacoes_com_cabecalho``); sem
    cabeçalho, o formato presumido da primeira rodada, abaixo.

    Cada linha com uma data e um valor é uma liberação; a linha de uma célula só (ou que começa por
    "Programa") abre o programa das linhas seguintes. Levanta ``ValueError`` se a soma não fecha com
    a linha "Total:" (diferença acima de um centavo por linha).
    """
    reais, total_real, com_cabecalho = _liberacoes_com_cabecalho(pagina)
    if com_cabecalho:
        return reais, total_real
    saida: list[dict] = []
    total = None
    programa = ""
    for tabela in cf.tabelas_html(pagina):
        for linha in tabela:
            textos = [c for c in linha if c]
            if not textos:
                continue
            junto = cf.norm(" ".join(textos))
            if junto.startswith("TOTAL"):
                valores = [cf.numero(c) for c in textos[1:] if cf.numero(c) is not None]
                if valores:
                    total = (total or 0.0) + valores[-1]
                continue
            datas = [c for c in textos if DATA.match(c)]
            dinheiro = [c for c in textos if re.fullmatch(r"-?[\d.]+,\d{2}", c)]
            if datas and dinheiro:
                outros = [c for c in textos if c not in datas and c not in dinheiro]
                ob = next((c for c in outros if re.fullmatch(r"\d{4}OB\d+|\d{6,}", c)), "")
                resto = [c for c in outros if c != ob]
                saida.append({
                    "programa": programa,
                    "data": cf.data(datas[0]),
                    "ordem_bancaria": ob,
                    "banco": resto[0] if len(resto) > 0 and resto[0].isdigit() else "",
                    "agencia": resto[1] if len(resto) > 1 else "",
                    "conta": resto[2] if len(resto) > 2 else "",
                    "valor": cf.numero(dinheiro[-1]),
                })
            elif len(textos) == 1 or junto.startswith("PROGRAMA"):
                rotulo = re.sub(r"(?i)^programa\s*:?\s*", "", textos[-1] if len(textos) > 1 else textos[0])
                if not CNPJ.search(rotulo) and not cf.norm(rotulo).startswith(("DATA", "ENTIDADE")):
                    programa = rotulo.strip()
    if total is not None and saida:
        soma = sum(l["valor"] for l in saida)
        if abs(soma - total) > 0.01 * len(saida) + 0.01:
            raise ValueError(f"a soma das liberações ({soma:.2f}) não fecha com o Total da página ({total:.2f})")
    if not saida and total is None and "NENHUM" not in cf.norm(re.sub(r"<[^>]+>", " ", pagina)):
        raise ValueError("a página não traz liberações nem a linha Total")
    return saida, total
