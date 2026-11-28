"""Pessoal: o dinheiro que a lei manda pagar, conferido no banco (família PES).

Com a matriz de saldos contábeis, mês a mês e por natureza da despesa:

* **Salário, provento e contribuição liquidados e não pagos em dois fechamentos seguidos.** A
  liquidação e o pagamento da folha caem no mesmo mês; o que fica liquidado e não pago no fim de um
  mês e continua no fim do seguinte passou do dia 5 (folha de ativos e inativos, Lei Orgânica,
  art. 30) ou do dia 20 (regime próprio e FGTS). É indício, com o valor estimado devido.
* **Aposentadorias.** O liquidado no ano pela matriz contra o RREO Anexo 4 (duas vias), e o mês em
  que a folha de inativos cai abaixo da mediana dos meses anteriores.
* **Revisão geral anual.** As leis de revisão contra a Constituição: carreira de fora é distinção.

O que só a folha publicada responde (piso do magistério, quinquênio, jeton, dia exato do
pagamento, valor devido por servidor) roda assim mesmo: a falta vira ausência dirigida ao órgão
que tem o documento, com o ofício pronto.
"""

from __future__ import annotations

from statistics import median

from ..nucleo.ausencias import Ausencia
from ..nucleo.indicios import Familia, emitir
from ..nucleo.provas import Nivel
from ..nucleo.selos import Selo, Verificacao, Via, selar
from .banco import EDUCACAO, PREVIDENCIA, SEMAD, SOMA, Base, Linha, Parte, Quadro, moeda, pct
from .devidos import RevisaoGeral, conferir_revisao_geral

# grupo: (naturezas da despesa, regra do mapa, dia do mês seguinte, rótulo)
GRUPOS = {
    "ativos": (("319011", "319004", "319016"), "FOLHA-DIA-5", "vencimentos e salários dos ativos"),
    "inativos": (("319001", "319003"), "FOLHA-DIA-5", "aposentadorias e pensões"),
    "rpps": (("319113",), "PREVIDENCIA-DIA-20", "contribuição patronal ao regime próprio"),
    "patronal": (("319013",), "FGTS-DIA-20", "FGTS e contribuições patronais"),
}


def _filtro(naturezas: tuple[str, ...]) -> tuple[str, list[str]]:
    return "(" + " or ".join("natureza_despesa like ?" for _ in naturezas) + ")", [n + "%" for n in naturezas]


def saldos_mensais(base: Base, naturezas: tuple[str, ...], meses: list[str]) -> dict[str, tuple[float, float]]:
    """{mês: (liquidado no mês, saldo liquidado e não pago no fim do mês)} dentro de cada exercício."""
    if not meses:
        return {}
    filtro, args = _filtro(naturezas)
    marcas = ",".join("?" for _ in meses)
    mov3 = dict(base.con.execute(
        f"select mes, {SOMA} from msc_itens where conta_contabil like '6221303%' and {filtro} "
        f"and mes in ({marcas}) group by mes", [*args, *meses]))
    liq = dict(base.con.execute(
        f"select mes, {SOMA} from msc_itens where (conta_contabil like '6221303%' or conta_contabil like '6221304%' "
        f"or conta_contabil like '6221307%') and {filtro} and mes in ({marcas}) group by mes", [*args, *meses]))
    saida, saldo, ano = {}, 0.0, None
    for m in meses:
        if m[:4] != ano:
            ano, saldo = m[:4], 0.0
        saldo += mov3.get(m) or 0.0
        saida[m] = (round(liq.get(m) or 0.0, 2), round(saldo, 2))
    return saida


def persistentes(serie: dict[str, tuple[float, float]], tolerado: float) -> list[tuple[str, float]]:
    """Meses cujo saldo liquidado e não pago continua no fim do mês seguinte, no mesmo exercício.

    O valor certo de atraso é o menor dos dois saldos: até ele, o que estava liquidado no primeiro
    fechamento continuava sem pagamento no segundo.
    """
    meses = sorted(serie)
    saida = []
    for a, b in zip(meses, meses[1:]):
        if a[:4] != b[:4]:
            continue
        atraso = min(serie[a][1], serie[b][1])
        if atraso > tolerado:
            saida.append((b, round(atraso, 2)))
    return saida


def _quedas(serie: dict[str, tuple[float, float]], queda: float, janela: int) -> list[tuple[str, float, float]]:
    meses = sorted(serie)
    saida = []
    for i, m in enumerate(meses):
        anteriores = [serie[x][0] for x in meses[max(0, i - janela):i] if serie[x][0] > 0]
        if len(anteriores) < 3:
            continue
        ref = median(anteriores)
        if ref > 0 and serie[m][0] < ref * (1 - queda / 100.0):
            saida.append((m, serie[m][0], ref))
    return saida


def _aposentadorias_rreo(base: Base, exercicio: int, periodo: int) -> float | None:
    linhas = base.con.execute(
        "select valor from siconfi_itens where demonstrativo = 'RREO' and exercicio = ? and periodo = ? "
        "and anexo = 'RREO-Anexo 04' and cod_conta like 'DespesasPrevidenciariasExcetoIntraOrcamentariasAposentadorias%' "
        "and coluna like 'DESPESAS LIQUIDADAS AT%'", (exercicio, periodo)).fetchall()
    return sum(float(v or 0.0) for (v,) in linhas) if linhas else None


def conferir(base: Base) -> Parte:
    parte = Parte()
    meses = base.meses_msc()
    if base.tem("msc_itens") and meses:
        _atrasos(base, meses, parte)
        _aposentadorias(base, meses, parte)
    _revisao(base, parte)
    _ausencias(base, parte)
    return parte


def _atrasos(base: Base, meses: list[str], parte: Parte) -> None:
    q = Quadro(4, "Pessoal liquidado e não pago no fechamento de cada mês",
               "Matriz de saldos contábeis, contas 6.2.2.1.3.03 (liquidado a pagar) e .04 (pago), por natureza. "
               "Saldo que continua no fim do mês seguinte passou do dia do pagamento.",
               ["Grupo", "Último mês", "Liquidado no mês", "Saldo não pago no fim do mês", "Meses com atraso certo",
                "Valor devido estimado"],
               regra="FOLHA-DIA-5, PREVIDENCIA-DIA-20 e FGTS-DIA-20: saldo tolerado de um real em dois fechamentos.")
    devido_total = 0.0
    for chave, (naturezas, regra_id, rotulo) in GRUPOS.items():
        regra = base.mapa.regra(regra_id)
        tolerado = float(regra.get("saldo_tolerado", 1.0))
        serie = saldos_mensais(base, naturezas, meses)
        if not serie:
            continue
        ult = max(serie)
        atrasos = persistentes(serie, tolerado)
        atual = atrasos[-1][1] if atrasos and atrasos[-1][0] == ult else 0.0
        devido_total += atual
        q.linhas.append(Linha(rotulo, [ult, moeda(serie[ult][0]), moeda(serie[ult][1]), str(len(atrasos)),
                                       moeda(atual)], Selo.AZUL, base.original_msc(ult)))
        if not atrasos:
            continue
        dia = int(regra.valor or 5)
        maior = max(atrasos, key=lambda x: x[1])
        lista = "; ".join(f"{m}: {moeda(v)}" for m, v in atrasos[-6:])
        parte.fichas.append(emitir(
            codigo=f"PES-ATRASO-{chave.upper()}-{ult[:4]}",
            familia=Familia.PES,
            titulo=f"{rotulo.capitalize()} liquidados e não pagos depois do dia {dia}",
            gravidade=regra.gravidade,
            como_deveria=f"{regra.titulo}: o que se liquida num mês é pago até o dia {dia} do seguinte.",
            norma=regra.norma,
            como_esta=(f"Saldo liquidado e não pago em dois fechamentos seguidos em {len(atrasos)} mês(es); maior "
                       f"valor em {maior[0]} ({moeda(maior[1])}). Últimos: {lista}. Valor devido estimado no fim de "
                       f"{ult}: {moeda(atual)}."),
            niveis=[Nivel.B],
            providencia=("Pedir as datas de crédito da folha e dos repasses de cada competência e o demonstrativo dos "
                         "encargos de atraso (juros e atualização) pagos."),
            observacao="indício, não acusação",
        ))
    q.notas.append(f"Valor devido estimado hoje, somados os grupos: {moeda(devido_total)}. A estimativa por servidor "
                   "depende da folha publicada.")
    if q.linhas:
        parte.quadros.append(q)


def _aposentadorias(base: Base, meses: list[str], parte: Parte) -> None:
    regra = base.mapa.regra("APOSENTADORIAS")
    tol = float(regra.valor or 1.0) / 100.0
    serie = saldos_mensais(base, ("319001",), meses)
    rreo = base.lt.ultimo("RREO", base.ate)
    q = Quadro(4, "Aposentadorias: o liquidado nas duas vias e mês a mês",
               "Via 1: RREO Anexo 4 (aposentadorias dos planos previdenciário e financeiro). Via 2: matriz de "
               "saldos contábeis, natureza 3.1.90.01, somada no exercício até o bimestre.",
               ["Período", "RREO Anexo 4", "Matriz", "Resultado"],
               regra=f"APOSENTADORIAS: vias em {regra.valor:g}%; queda mensal acima de "
                     f"{regra.get('queda_mensal_maxima', 5.0):g}% da mediana dos meses anteriores.")
    if rreo is not None:
        via1 = _aposentadorias_rreo(base, rreo.exercicio, rreo.periodo)
        doano = [m for m in serie if m.startswith(f"{rreo.exercicio}-") and m <= f"{rreo.termina:%Y-%m}"]
        via2 = round(sum(serie[m][0] for m in doano), 2) if len(doano) == 2 * rreo.periodo else None
        cert = selar([Via("RREO Anexo 4", via1), Via("matriz de saldos contábeis", via2)], tolerancia=tol)
        if cert.selo is not None:
            parte.certificacoes.append(cert)
            q.linhas.append(Linha(rreo.rotulo, [moeda(via1), moeda(via2) if via2 is not None else "matriz incompleta",
                                                "divergem" if cert.divergencia else "iguais"], cert.selo,
                                  base.original_do_periodo("RREO", rreo.exercicio, rreo.periodo)))
            if cert.divergencia:
                parte.fichas.append(emitir(
                    codigo=f"PES-APOSENTADORIAS-VIAS-{rreo.exercicio}-{rreo.periodo}",
                    familia=Familia.PES,
                    titulo="Aposentadorias: o RREO e a matriz de saldos contábeis divergem",
                    gravidade=regra.gravidade,
                    como_deveria=f"O mesmo valor nas duas entregas, dentro de {regra.valor:g}%.",
                    norma=regra.norma,
                    como_esta=f"{rreo.rotulo}: RREO {moeda(via1)}; matriz {moeda(via2)}.",
                    niveis=[Nivel.B],
                    providencia="Pedir a conciliação entre o RREO e a matriz e a folha de inativos do período.",
                ))
    quedas = _quedas(serie, float(regra.get("queda_mensal_maxima", 5.0)), int(regra.get("meses_de_referencia", 6)))
    for m, v, ref in quedas[-6:]:
        q.linhas.append(Linha(f"{m}: queda", [moeda(ref) + " (mediana)", moeda(v), pct(100 * (v / ref - 1))],
                              Selo.AZUL, base.original_msc(m)))
    if quedas:
        ult = quedas[-1]
        parte.fichas.append(emitir(
            codigo=f"PES-APOSENTADORIAS-QUEDA-{ult[0][:4]}",
            familia=Familia.PES,
            titulo="Folha de aposentadorias abaixo da mediana dos meses anteriores",
            gravidade=regra.gravidade,
            como_deveria=(f"Provento é pago todo mês; a folha de inativos não cai mais de "
                          f"{regra.get('queda_mensal_maxima', 5.0):g}% abaixo da mediana dos meses anteriores "
                          "(limiar do mapa legal)."),
            norma=regra.norma,
            como_esta="; ".join(f"{m}: {moeda(v)} contra mediana de {moeda(r)}" for m, v, r in quedas[-6:]) + ".",
            niveis=[Nivel.B],
            providencia="Pedir a folha de inativos dos meses apontados e a relação de benefícios suspensos ou adiados.",
            observacao="indício, não acusação",
        ))
    if q.linhas:
        parte.quadros.append(q)


def _revisao(base: Base, parte: Parte) -> None:
    regra = base.mapa.regra("REVISAO-GERAL-ANUAL")
    revisoes = regra.get("revisoes") or {}
    q = Quadro(4, "Revisão geral anual: índice e carreiras alcançadas",
               "As leis de revisão do Executivo. A inflação do período entra quando o IPCA estiver no banco.",
               ["Ano", "Lei", "Índice", "Carreiras de fora"],
               regra=f"REVISAO-GERAL-ANUAL: {regra.get('justificativa', '')}")
    for ano in sorted(revisoes):
        if int(ano) > base.ate.year:
            continue
        r = revisoes[ano]
        excl = tuple(r.get("excluidas") or ())
        q.linhas.append(Linha(str(ano), [r.get("lei", ""), pct(float(r["indice"]), 2), ", ".join(excl) or "nenhuma"],
                              Selo.AZUL))
        # Sem o IPCA no banco, a inflação não entra: só a distinção entre carreiras é conferida.
        ficha = conferir_revisao_geral(RevisaoGeral(int(ano), float(r["indice"]), float(r["indice"]),
                                                    r.get("lei", ""), excl))
        if ficha is not None:
            # Uma via só (o texto da lei): a exclusão pode ter motivo próprio (piso da carreira, lei
            # específica), então a ficha fica indiciária até a justificativa ser lida.
            ficha.verificacao = Verificacao.INDICIARIO
            ficha.observacao = ("indício, não acusação; a comparação com o IPCA depende da série de inflação, "
                                "que não está no banco")
            parte.fichas.append(ficha)
    if q.linhas:
        parte.quadros.append(q)
        parte.ausencias.append(Ausencia(
            o_que_falta="Tabelas de vencimento de cada carreira antes e depois de cada revisão geral",
            conferencia_impedida="saber se a revisão chegou a todas as carreiras e qual a perda de quem ficou de fora",
            onde_deveria_estar="Portal da Transparência de Goiânia, pessoal (estrutura remuneratória)",
            fundamento="CF, art. 37, X; Lei 9.262/2013, art. 7º, § 3º; Lei 12.527/2011, art. 8º",
            periodo=f"{min(revisoes)} a {base.ate.year}", orgao=SEMAD, bloco="Pessoal e diárias"))


# Documento que só a folha responde: (o que falta, conferência impedida, órgão, regra)
FOLHA = (
    ("Folha do magistério com o vencimento inicial de cada nível e a jornada",
     "conferir o vencimento inicial do magistério contra o piso nacional (PISO-MAGISTERIO)", EDUCACAO,
     "Lei 11.738/2008, arts. 2º e 5º"),
    ("Folha com o adicional por tempo de serviço (quinquênio) e a data de admissão de cada cargo",
     "conferir se cada quinquênio completado foi pago no mês devido (QUINQUENIO)", SEMAD,
     "Lei Orgânica, art. 28, VI e § 2º"),
    ("Folha de jetons da JARI e do CADEP com as atas das sessões do mês",
     "conferir o valor por sessão e o número de sessões pagas (JETON)", SEMAD, "LC 335/2021, art. 29"),
    ("Data de crédito da folha de ativos e inativos de cada competência",
     "conferir o dia exato do pagamento contra o dia 5 (FOLHA-DIA-5)", SEMAD, "Lei Orgânica, art. 30"),
    ("Comprovantes de repasse das contribuições ao regime próprio com a data de cada um",
     "conferir o dia exato do repasse contra o dia 20 (PREVIDENCIA-DIA-20)", PREVIDENCIA, "LC 312/2018 e LC 336/2021"),
    ("Guias de recolhimento do FGTS dos empregados celetistas com a data de pagamento",
     "conferir o dia exato do depósito contra o dia 20 (FGTS-DIA-20)", SEMAD, "Lei 8.036/1990, art. 15"),
    ("Folha de pagamento por competência, com cargo e valor (sem CPF nem matrícula)",
     "estimar o valor devido a cada carreira pela folha (VALOR-DEVIDO)", SEMAD, "Lei Orgânica, art. 30"),
)


def _ausencias(base: Base, parte: Parte) -> None:
    for falta, impedida, orgao, norma in FOLHA:
        parte.ausencias.append(Ausencia(
            o_que_falta=falta, conferencia_impedida=impedida,
            onde_deveria_estar="Portal da Transparência de Goiânia, pessoal (folha de pagamento)",
            fundamento=f"{norma}; Lei 12.527/2011, art. 8º; Lei 9.262/2013, art. 7º, § 3º; Lei 8.902/2010",
            periodo=f"exercício {base.ate.year}", orgao=orgao, bloco="Pessoal e diárias"))
