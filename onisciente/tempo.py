"""Máquina do tempo: de 2019 até o fim do PPA.

Para trás: previsto, pago e prestado. Para a frente: o que o PPA promete e a
projeção do próprio Onisciente pela execução média dos últimos três anos. A
projeção aparece sempre como projeção, com a régua usada.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class Exercicio:
    ano: int
    previsto: float
    pago: float | None = None

    @property
    def execucao(self) -> float | None:
        if self.pago is None or not self.previsto:
            return None
        return self.pago / self.previsto


def taxa_media(historico: list[Exercicio], anos: int = 3) -> float | None:
    taxas = [e.execucao for e in sorted(historico, key=lambda e: e.ano) if e.execucao is not None]
    ultimas = taxas[-anos:]
    if len(ultimas) < anos:
        return None
    return sum(ultimas) / len(ultimas)


def projetar(historico: list[Exercicio], promessa_ppa: Mapping[int, float], anos: int = 3) -> list[dict]:
    """Projeta o pago de cada ano futuro pela execução média dos últimos ``anos``."""
    taxa = taxa_media(historico, anos)
    saida = []
    for ano in sorted(promessa_ppa):
        prometido = promessa_ppa[ano]
        linha = {"ano": ano, "prometido": prometido, "tipo": "projeção",
                 "regua": f"execução média dos últimos {anos} anos"}
        if taxa is None:
            linha.update(projetado=None, diferenca=None,
                         nota="série insuficiente para projetar")
        else:
            projetado = round(prometido * taxa, 2)
            linha.update(projetado=projetado, taxa=round(taxa, 4),
                         diferenca=round(prometido - projetado, 2))
        saida.append(linha)
    return saida


# --- Tempestividade: cada documento contra o seu prazo legal ------------------------------
#
# O prazo de cada demonstrativo vem do mapa legal quando ele tem a regra (``PRAZO-RREO``,
# ``PRAZO-RGF``, ``PRAZO-DCA``, ``PRAZO-MSC``, ``PRAZO-SIOPS``, com ``valor`` em dias depois
# do fim do período); sem a regra, vale o prazo da própria lei, citado ao lado.

from datetime import date, datetime, timedelta  # noqa: E402

PRAZOS: dict[str, dict] = {
    "RREO": {"meses": 2, "dias": 30, "norma": "Lei Complementar 101/2000, art. 52",
             "nome": "Relatório Resumido da Execução Orçamentária"},
    "RGF": {"meses": 4, "dias": 30, "norma": "Lei Complementar 101/2000, art. 55, § 2º",
            "nome": "Relatório de Gestão Fiscal"},
    "DCA": {"meses": 12, "data_fixa": (4, 30), "norma": "Lei Complementar 101/2000, art. 51, § 1º, I",
            "nome": "Declaração de Contas Anuais"},
    "MSC": {"meses": 1, "fim_do_mes_seguinte": True, "norma": "Portaria STN 642/2019, art. 5º",
            "nome": "Matriz de Saldos Contábeis"},
    "SIOPS": {"meses": 2, "dias": 30, "norma": "Lei Complementar 141/2012, art. 39, e Lei Complementar "
              "101/2000, art. 52", "nome": "Demonstrativo da saúde no SIOPS"},
}
ENTREGAVEIS = {"Relatório Resumido de Execução Orçamentária": "RREO", "Relatório de Gestão Fiscal": "RGF",
               "Balanço Anual (DCA)": "DCA", "MSC Agregada": "MSC"}
PERIODOS_NO_ANO = {"RREO": 6, "RGF": 3, "DCA": 1, "MSC": 12, "SIOPS": 6}


def _fim_do_mes(ano: int, mes: int) -> date:
    proximo = date(ano + 1, 1, 1) if mes == 12 else date(ano, mes + 1, 1)
    return proximo - timedelta(days=1)


def fim_do_periodo(documento: str, exercicio: int, periodo: int) -> date:
    meses = PRAZOS[documento]["meses"]
    return _fim_do_mes(exercicio, min(12, periodo * meses))


def prazo_legal(documento: str, exercicio: int, periodo: int, mapa=None) -> tuple[date, str]:
    """A data-limite do documento e a norma que a fixa.

    Com o mapa legal, a regra ``PRAZO-{documento}`` manda: ``valor`` é o número de dias depois do fim do
    período; sem valor, ``data_limite`` ({mes, dia}) é a data fixa seguinte ao fim do período e
    ``meses_depois`` é o último dia do mês que fica tantos meses depois do fim do período.
    """
    spec = PRAZOS[documento]
    norma = spec["norma"]
    dias = spec.get("dias")
    fim = fim_do_periodo(documento, exercicio, periodo)
    if mapa is not None:
        regra = mapa.regras.get(f"PRAZO-{documento}")
        if regra is not None and regra.valor is not None:
            dias, norma = int(regra.valor), regra.norma or norma
        elif regra is not None:
            norma = regra.norma or norma
            limite = regra.get("data_limite")
            if isinstance(limite, dict) and limite.get("mes") and limite.get("dia"):
                d = date(fim.year, int(limite["mes"]), int(limite["dia"]))
                return (d if d > fim else date(fim.year + 1, int(limite["mes"]), int(limite["dia"]))), norma
            meses = regra.get("meses_depois")
            if meses:
                m = fim.month + int(meses)
                return _fim_do_mes(fim.year + (m - 1) // 12, (m - 1) % 12 + 1), norma
    if spec.get("data_fixa") and dias == spec.get("dias"):
        mes, dia = spec["data_fixa"]
        return date(exercicio + 1, mes, dia), norma
    if spec.get("fim_do_mes_seguinte") and dias == spec.get("dias"):
        seguinte = fim + timedelta(days=1)
        return _fim_do_mes(seguinte.year, seguinte.month), norma
    return fim + timedelta(days=int(dias or 0)), norma


def _data(texto) -> date | None:
    """'2025-03-28T16:13:01Z' ou '04/10/24 10:09:05' (o SIOPS escreve assim) viram data."""
    if not texto:
        return None
    t = str(texto).strip()
    for formato, tamanho in (("%Y-%m-%d", 10), ("%d/%m/%y", 8), ("%d/%m/%Y", 10)):
        try:
            return datetime.strptime(t[:tamanho], formato).date()
        except ValueError:
            continue
    return None


def _rotulo(documento: str, exercicio: int, periodo: int) -> str:
    if documento == "DCA":
        return f"DCA {exercicio}"
    if documento == "MSC":
        return f"MSC {exercicio}-{periodo:02d}"
    nome = {"RREO": "º bimestre", "RGF": "º quadrimestre", "SIOPS": "º bimestre"}[documento]
    return f"{documento} {exercicio}, {periodo}{nome}"


def tempestividade_dos_documentos(banco, hoje: date, mapa=None) -> list[dict]:
    """Cada documento fiscal do banco histórico contra o prazo da lei.

    ``banco`` é um ``historico.Banco`` (ou qualquer objeto com ``consultar``). Situações:
    ``no prazo``, ``atrasado`` (com os dias), ``ausente`` (prazo vencido sem entrega),
    ``ainda no prazo`` e ``não medida`` (o extrato só guarda a data da retificação, que não
    é a da primeira entrega; a medida não pesa contra o Município).
    """
    entregas: dict[tuple, dict] = {}
    for entregavel, exercicio, periodo, status, quando in banco.consultar(
            "SELECT entregavel, exercicio, periodo, status, data_status FROM siconfi_entregas"):
        doc = ENTREGAVEIS.get(entregavel)
        if not doc or exercicio is None or periodo is None:
            continue
        chave = (doc, int(exercicio), int(periodo))
        item = entregas.setdefault(chave, {"datas": [], "retificado": False})
        d = _data(quando)
        if d:
            item["datas"].append(d)
        item["retificado"] |= str(status or "").upper() == "RE"
    for exercicio, periodo, homologado, situacao in banco.consultar(
            "SELECT exercicio, periodo, homologado, situacao FROM externos_periodos WHERE fonte = 'SIOPS'"):
        d = _data(homologado)
        if d:
            entregas.setdefault(("SIOPS", int(exercicio), int(periodo)),
                                {"datas": [], "retificado": False})["datas"].append(d)

    # Vários períodos do mesmo documento entregues no mesmo dia: é reenvio em lote, e o extrato
    # só guarda a data do último envio. A medida não pesa contra o Município.
    lote: dict[tuple, int] = {}
    for (doc, ano, _), item in entregas.items():
        if item["datas"]:
            chave = (doc, max(item["datas"]))
            lote[chave] = lote.get(chave, 0) + 1

    anos: dict[str, set[int]] = {}
    for doc, ano, _ in entregas:
        anos.setdefault(doc, set()).add(ano)
    saida = []
    for doc, conjunto in sorted(anos.items()):
        for ano in sorted(conjunto):
            for periodo in range(1, PERIODOS_NO_ANO[doc] + 1):
                if fim_do_periodo(doc, ano, periodo) >= hoje:
                    continue                    # o período ainda corre: não se cobra
                prazo, norma = prazo_legal(doc, ano, periodo, mapa)
                item = entregas.get((doc, ano, periodo))
                linha = {"documento": doc, "nome": PRAZOS[doc]["nome"], "exercicio": ano, "periodo": periodo,
                         "rotulo": _rotulo(doc, ano, periodo), "prazo": prazo.isoformat(), "norma": norma,
                         "entregue_em": None, "dias_de_atraso": None,
                         "ressalva": "a data é a do envio vigente no extrato; um reenvio posterior a substitui"}
                if item and item["datas"]:
                    # Quando há mais de uma entrega no período (Executivo e Câmara no RGF), vale a última.
                    entregue = max(item["datas"])
                    linha["entregue_em"] = entregue.isoformat()
                    if item["retificado"]:
                        linha["situacao"] = "não medida"
                        linha["motivo"] = ("o extrato guarda só a data da retificação; a data da primeira "
                                           "entrega não vem nele")
                    elif lote.get((doc, entregue), 0) > 1 and entregue > prazo:
                        linha["situacao"] = "não medida"
                        linha["motivo"] = (f"{lote[(doc, entregue)]} períodos com a mesma data de envio: é reenvio "
                                           "em lote, e a data da primeira entrega não vem no extrato")
                    elif entregue <= prazo:
                        linha["situacao"] = "no prazo"
                        linha["dias_de_atraso"] = 0
                    else:
                        linha["situacao"] = "atrasado"
                        linha["dias_de_atraso"] = (entregue - prazo).days
                else:
                    linha["situacao"] = "ainda no prazo" if hoje <= prazo else "ausente"
                saida.append(linha)
    return saida


def indice_de_tempestividade(itens: list[dict]) -> float | None:
    """Parte dos documentos medidos que saiu no prazo (ausente conta como fora do prazo)."""
    medidos = [i for i in itens if i["situacao"] in ("no prazo", "atrasado", "ausente")]
    if not medidos:
        return None
    return sum(1 for i in medidos if i["situacao"] == "no prazo") / len(medidos)


def dias_com_diario(banco, mes: str, fonte: str = "sileg") -> int | None:
    """Dias do mês em que o Diário Oficial saiu, contados pelo coletor no índice do SILEG.
    None quando o coletor ainda não contou o mês (tabela ausente ou mês não lido por inteiro)."""
    try:
        linhas = banco.consultar("SELECT COUNT(DISTINCT data) FROM diario_oficial_dias "
                                 "WHERE fonte = ? AND mes = ?", fonte, mes)
        lidos = banco.consultar("SELECT COUNT(*) FROM diario_oficial_mes WHERE fonte = ? AND mes = ? "
                                "AND erro IS NULL", fonte, mes)
    except Exception:  # noqa: BLE001 (banco de rodada antiga, sem a tabela)
        return None
    if not lidos or not lidos[0][0]:
        return None
    n = linhas[0][0] if linhas else 0
    return n or None


def dias_uteis(mes: str, feriados: set[str] = frozenset()) -> int:
    """Dias de segunda a sexta do mês, menos os feriados dados (``AAAA-MM-DD``)."""
    ano, m = map(int, mes.split("-"))
    d, fim, n = date(ano, m, 1), _fim_do_mes(ano, m), 0
    while d <= fim:
        if d.weekday() < 5 and d.isoformat() not in feriados:
            n += 1
        d += timedelta(days=1)
    return n


def publicacao_do_mes(banco, mes: str) -> dict:
    """Dias com Diário pelo SILEG contra os dias úteis do mês (a tempestividade da publicação)."""
    dias = dias_com_diario(banco, mes)
    uteis = dias_uteis(mes)
    return {"mes": mes, "dias_com_edicao": dias, "dias_uteis": uteis,
            "razao": round(min(dias, uteis) / uteis, 4) if dias is not None and uteis else None,
            "fonte": "índice do SILEG (onisciente/historico.py, motor sileg)"}
