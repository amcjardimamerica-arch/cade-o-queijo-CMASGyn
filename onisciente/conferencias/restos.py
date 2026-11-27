"""Restos a pagar que nunca viraram entrega (regra RP-NUNCA-LIQUIDADOS).

Duas medidas, as duas sobre o banco:

1. **Cancelados sem liquidar.** No exercício seguinte ao da inscrição, quanto dos restos a pagar
   não processados foi cancelado em vez de liquidado. Via 1: RREO Anexo 14 do 6º bimestre
   (inscrição e cancelamento). Via 2: a matriz de saldos contábeis, conta 6.3.1.9.9 (cancelados),
   somada no ano. As duas são entregas homologadas em separado.
2. **Parados.** O saldo da conta 6.3.1.1 (a liquidar) por ano de inscrição: o que foi inscrito há
   mais de um exercício e segue sem liquidação. A matriz registra a abertura do exercício como
   movimento de janeiro em alguns anos e não em outros; quando não registra, o saldo do ano
   anterior e a inscrição do fim dele (conta 6.3.1.7) entram como abertura.
"""

from __future__ import annotations

from ..nucleo.ausencias import Ausencia
from ..nucleo.indicios import Familia, emitir
from ..nucleo.provas import Nivel
from ..nucleo.selos import Selo, Via, selar
from .banco import FAZENDA, SOMA, Base, Linha, Parte, Quadro, moeda, pct

REGRA = "RP-NUNCA-LIQUIDADOS"
NORMA = "Lei 4.320/1964, arts. 36 e 58 a 65"


def anexo14(base: Base, exercicio: int) -> dict[str, float] | None:
    """Inscrição, cancelamento, pagamento e saldo dos restos não processados no RREO do 6º bimestre."""
    if not base.tem("siconfi_itens"):
        return None
    linhas = base.con.execute(
        "select coluna, valor from siconfi_itens where demonstrativo = 'RREO' and exercicio = ? and periodo = 6 "
        "and anexo = 'RREO-Anexo 14' and cod_conta = 'RestosAPagarNaoProcessadosDemonstrativoSimplificado'",
        (exercicio,)).fetchall()
    if not linhas:
        return None
    saida = {}
    for coluna, valor in linhas:
        c = (coluna or "").lower()
        chave = ("inscricao" if c.startswith("inscri") else "cancelamento" if c.startswith("cancel")
                 else "pagamento" if c.startswith("pagamento") else "saldo" if c.startswith("saldo") else None)
        if chave:
            saida[chave] = float(valor or 0.0)
    return saida if "inscricao" in saida else None


def cancelados_na_matriz(base: Base, exercicio: int) -> float | None:
    meses = [m for m in base.meses_msc() if m.startswith(f"{exercicio}-")]
    if len(meses) < 12:
        return None
    v = base.con.execute(
        f"select {SOMA} from msc_itens where conta_contabil like '63199%' and substr(mes, 1, 4) = ?",
        (str(exercicio),)).fetchone()[0]
    return float(v) if v is not None else None


def saldo_por_inscricao(base: Base) -> tuple[str | None, dict[int, float]]:
    """Saldo a liquidar dos restos não processados por ano de inscrição, no último mês da matriz."""
    meses = base.meses_msc()
    if not meses:
        return None, {}
    saldo: dict[int, float] = {}
    inscricao_anterior: dict[int, float] = {}
    for ano in sorted({m[:4] for m in meses}):
        do_ano = [m for m in meses if m.startswith(ano)]
        marcas = ",".join("?" for _ in do_ano)
        abertura = base.con.execute(
            "select sum(valor) from msc_itens where conta_contabil like '6311%' and natureza_conta = 'C' "
            "and mes = ?", (f"{ano}-01",)).fetchone()[0] or 0.0
        movimento = {int(a): float(v or 0.0) for a, v in base.con.execute(
            f"select ano_inscricao, {SOMA} from msc_itens where conta_contabil like '6311%' and mes in ({marcas}) "
            "and ano_inscricao is not null group by 1", do_ano)}
        if f"{ano}-01" in do_ano and abertura > 0:
            saldo = movimento                       # a matriz trouxe a abertura em janeiro
        else:
            chaves = set(saldo) | set(inscricao_anterior) | set(movimento)
            saldo = {a: saldo.get(a, 0.0) + inscricao_anterior.get(a, 0.0) + movimento.get(a, 0.0) for a in chaves}
        inscricao_anterior = {int(a): float(v or 0.0) for a, v in base.con.execute(
            f"select ano_inscricao, {SOMA} from msc_itens where conta_contabil like '6317%' and mes in ({marcas}) "
            "and ano_inscricao is not null group by 1", do_ano)}
    return meses[-1], {a: round(v, 2) for a, v in saldo.items()}


def conferir(base: Base) -> Parte:
    parte = Parte()
    regra = base.mapa.regra(REGRA)
    limite = float(regra.valor or 10.0)
    idade = int(regra.get("idade_maxima_exercicios", 1))
    tolerado = float(regra.get("saldo_tolerado", 1.0))

    # 1. Cancelados sem liquidar, por exercício fechado.
    quadro = Quadro(4, "Restos a pagar não processados: inscritos, cancelados sem liquidar e pagos",
                    "No exercício seguinte ao da inscrição. Via 1: RREO Anexo 14 do 6º bimestre. Via 2: matriz "
                    "de saldos contábeis, conta dos cancelados somada no ano.",
                    ["Exercício", "Inscritos", "Cancelados (RREO)", "Cancelados (matriz)", "Cancelado", "Pago"],
                    regra=f"{REGRA}: até {limite:g}% cancelado; {regra.get('justificativa', '')}")
    exercicios = sorted({e for (e,) in base.con.execute(
        "select exercicio from siconfi_periodos where demonstrativo = 'RREO' and periodo = 6 and situacao = 'entregue' "
        "and termina <= ?", (base.ate.isoformat(),))}) if base.tem("siconfi_periodos") else []
    for ex in exercicios:
        a14 = anexo14(base, ex)
        if not a14 or not a14.get("inscricao"):
            continue
        msc = cancelados_na_matriz(base, ex)
        cert = selar([Via("RREO Anexo 14", a14.get("cancelamento")), Via("matriz de saldos contábeis", msc)])
        parte.certificacoes.append(cert)
        share = 100.0 * (a14.get("cancelamento") or 0.0) / a14["inscricao"]
        pago = 100.0 * (a14.get("pagamento") or 0.0) / a14["inscricao"]
        quadro.linhas.append(Linha(str(ex), [moeda(a14["inscricao"]), moeda(a14.get("cancelamento")),
                                             moeda(msc) if msc is not None else "sem matriz do ano inteiro",
                                             pct(share), pct(pago)],
                                   cert.selo, base.original_do_periodo("RREO", ex, 6)))
        if share > limite:
            parte.fichas.append(emitir(
                codigo=f"ENT-RPNP-CANCELADOS-{ex}",
                familia=Familia.ENT,
                titulo=f"Restos a pagar de {ex - 1} cancelados sem liquidar em {ex}: {pct(share)} do inscrito",
                gravidade=regra.gravidade,
                como_deveria=(f"O empenho inscrito em restos a pagar presume obrigação a cumprir; o cancelado "
                              f"sem liquidar não deve passar de {limite:g}% do inscrito (limiar do mapa legal)."),
                norma=NORMA,
                como_esta=(f"Inscritos {moeda(a14['inscricao'])}; cancelados sem liquidar "
                           f"{moeda(a14.get('cancelamento'))} ({pct(share)}); pagos {moeda(a14.get('pagamento'))}. "
                           + ("A matriz de saldos contábeis confirma o cancelamento."
                              if cert.selo is Selo.VERDE else "Só o RREO informa o cancelamento.")),
                niveis=[Nivel.B],
                providencia=("Pedir a relação dos empenhos cancelados, com credor, objeto e motivo, e as notas "
                             "de empenho de origem; empenho sem obrigação é indício de reserva para fechar o ano."),
                observacao="indício, não acusação",
            ))
    if quadro.linhas:
        parte.quadros.append(quadro)

    # 2. Parados há mais de um exercício.
    mes, saldo = saldo_por_inscricao(base)
    if mes:
        atual = int(mes[:4])
        antigos = {a: v for a, v in saldo.items() if a <= atual - 1 - idade and v > tolerado}
        q2 = Quadro(4, f"Restos a pagar não processados ainda a liquidar em {mes}, por ano de inscrição",
                    "Matriz de saldos contábeis, conta 6.3.1.1, saldo acumulado por ano de inscrição.",
                    ["Ano de inscrição", "Saldo a liquidar", "Situação"],
                    regra=f"{REGRA}: no máximo {idade} exercício sem liquidar; saldo tolerado {moeda(tolerado)}.")
        for a in sorted(saldo):
            v = saldo[a]
            if abs(v) <= tolerado:
                continue
            q2.linhas.append(Linha(str(a), [moeda(v), "parado há mais de um exercício" if a in antigos
                                            else "dentro do prazo"], Selo.AZUL, base.original_msc(mes)))
        if q2.linhas:
            parte.quadros.append(q2)
        if antigos:
            total = sum(antigos.values())
            anos = ", ".join(f"{a} ({moeda(v)})" for a, v in sorted(antigos.items()))
            parte.fichas.append(emitir(
                codigo=f"ENT-RPNP-PARADOS-{mes[:4]}",
                familia=Familia.ENT,
                titulo=f"Restos a pagar sem liquidação há mais de um exercício: {moeda(total)}",
                gravidade=regra.gravidade,
                como_deveria=(f"Resto a pagar não processado é liquidado ou cancelado no exercício seguinte; "
                              f"o mapa legal tolera no máximo {idade} exercício."),
                norma=NORMA,
                como_esta=f"Em {mes}, ainda a liquidar, por ano de inscrição: {anos}.",
                niveis=[Nivel.B],
                providencia=("Pedir a relação dos empenhos com credor e objeto e a justificativa para mantê-los "
                             "inscritos sem entrega."),
                observacao="indício, não acusação",
            ))
            parte.ausencias.append(Ausencia(
                o_que_falta="Relação dos restos a pagar não processados por empenho, credor, objeto e ano de inscrição",
                conferencia_impedida="saber a quem e por que se mantêm restos a pagar sem liquidação há mais de um exercício",
                onde_deveria_estar="Portal da Transparência de Goiânia, execução da despesa (restos a pagar)",
                fundamento="Lei 4.320/1964, art. 36; LC 101/2000, arts. 48 e 48-A; Lei 9.262/2013, art. 7º, § 3º",
                periodo=f"até {mes}", orgao=FAZENDA, bloco="Restos a pagar"))
    return parte
