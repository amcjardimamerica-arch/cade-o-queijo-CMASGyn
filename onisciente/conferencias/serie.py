"""Máquina do tempo ligada ao banco: a série do previsto e do pago, e a projeção pela média de três anos.

Para cada exercício encerrado no banco (RREO do 6º bimestre): a dotação atualizada e a despesa paga
(RREO Anexo 1, total das despesas). A projeção do exercício corrente aplica à dotação atualizada a
execução média dos últimos três exercícios (``onisciente/tempo.py``). Com menos de três exercícios
no banco, a projeção de três anos não sai; a provisória, com os anos que há, sai marcada como tal.
A projeção é sempre projeção, com a régua usada, e nunca vira ficha.
"""

from __future__ import annotations

from .. import tempo
from ..nucleo.selos import Selo
from .banco import Base, Linha, Parte, Quadro, moeda, pct

ANOS = 3


def _total(base: Base, exercicio: int, periodo: int, coluna: str) -> float | None:
    v = base.lt.valor(type("P", (), {"demonstrativo": "RREO", "exercicio": exercicio, "periodo": periodo})(),
                      "Anexo 01", "TotalDespesas", coluna)
    return float(v) if v is not None else None


def historico(base: Base) -> list[tempo.Exercicio]:
    saida = []
    for p in base.lt.periodos("RREO"):
        if p.periodo != 6 or p.termina > base.ate:
            continue
        previsto = _total(base, p.exercicio, 6, r"DOTAÇÃO ATUALIZADA.*")
        pago = _total(base, p.exercicio, 6, r"DESPESAS PAGAS ATÉ O BIMESTRE.*")
        if previsto:
            saida.append(tempo.Exercicio(p.exercicio, previsto, pago))
    return saida


def conferir(base: Base) -> Parte:
    parte = Parte()
    if not base.tem("siconfi_itens"):
        return parte
    hist = historico(base)
    corrente = base.lt.ultimo("RREO", base.ate)
    if not hist and corrente is None:
        return parte
    q = Quadro(4, "Máquina do tempo: previsto, pago e a projeção do exercício",
               "RREO Anexo 1, total das despesas: dotação atualizada e despesa paga de cada exercício encerrado. A "
               "projeção aplica à dotação atualizada do exercício corrente a execução média dos últimos três "
               "exercícios; com menos de três no banco, sai a provisória, marcada.",
               ["Exercício", "Previsto (dotação atualizada)", "Pago", "Execução", "Tipo"])
    for e in hist:
        q.linhas.append(Linha(str(e.ano), [moeda(e.previsto), moeda(e.pago),
                                           pct(100 * e.execucao) if e.execucao is not None else "sem dado", "realizado"],
                              Selo.AZUL, base.original_do_periodo("RREO", e.ano, 6)))
    if corrente is not None and corrente.periodo < 6:
        dotacao = _total(base, corrente.exercicio, corrente.periodo, r"DOTAÇÃO ATUALIZADA.*")
        if dotacao:
            [linha] = tempo.projetar(hist, {corrente.exercicio: dotacao}, anos=ANOS)
            regua = linha["regua"]
            if linha.get("projetado") is None and hist:
                [linha] = tempo.projetar(hist, {corrente.exercicio: dotacao}, anos=len(hist))
                regua = f"provisória: {linha['regua'].replace('últimos', 'únicos')} no banco, faltam {ANOS - len(hist)}"
            q.linhas.append(Linha(str(corrente.exercicio), [
                moeda(dotacao), moeda(linha.get("projetado")) if linha.get("projetado") is not None else "sem projeção",
                pct(100 * linha["taxa"]) if linha.get("taxa") is not None else "sem dado", f"projeção ({regua})"],
                Selo.AZUL, base.original_do_periodo("RREO", corrente.exercicio, corrente.periodo)))
    if len(hist) < ANOS:
        q.notas.append(f"O banco tem {len(hist)} exercício(s) encerrado(s); a projeção pela média de {ANOS} anos "
                       f"pede os RREO do 6º bimestre de {', '.join(str(a) for a in range((hist[0].ano if hist else base.ate.year) - (ANOS - len(hist)), hist[0].ano if hist else base.ate.year))}.")
    if q.linhas:
        parte.quadros.append(q)
    return parte
