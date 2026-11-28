"""Fim de mandato (LRF, arts. 21 e 42), medido no RGF do 3º quadrimestre do último ano do mandato.

* **Art. 42 (FIM-DE-MANDATO-CAIXA).** A disponibilidade de caixa líquida depois dos restos a pagar
  não processados, em cada destinação do RGF Anexo 5. Destinação negativa é obrigação contraída sem
  caixa para pagá-la.
* **Art. 21, II (FIM-DE-MANDATO-PESSOAL).** A despesa bruta com pessoal mês a mês do RGF Anexo 1:
  a média de julho a novembro (os 180 dias finais, sem o décimo terceiro de dezembro) contra a
  média de janeiro a junho.

O mandato municipal termina em 31 de dezembro dos anos múltiplos de quatro; a medida roda sobre o
último que terminou até a data, com o que estiver no banco.
"""

from __future__ import annotations

from ..nucleo.indicios import Familia, emitir
from ..nucleo.provas import Nivel
from ..nucleo.selos import Selo
from .banco import Base, Linha, Parte, Quadro, moeda, pct


def ultimo_fim_de_mandato(ate_ano: int, ate_mes: int) -> int:
    ano = ate_ano if ate_mes == 12 else ate_ano - 1
    return ano - (ano % 4)


def caixa_por_destinacao(base: Base, exercicio: int) -> dict[str, float]:
    linhas = base.con.execute(
        "select conta, valor from siconfi_itens where demonstrativo = 'RGF' and exercicio = ? and periodo = 3 "
        "and anexo = 'RGF-Anexo 05' and coluna like 'DISPONIBILIDADE DE CAIXA LÍQUIDA (APÓS%'", (exercicio,))
    return {c: float(v or 0.0) for c, v in linhas if c}


def conferir(base: Base, exercicio: int | None = None) -> Parte:
    parte = Parte()
    if not base.tem("siconfi_itens"):
        return parte
    ano = exercicio or ultimo_fim_de_mandato(base.ate.year, base.ate.month)
    rgf = next((p for p in base.lt.periodos("RGF") if p.exercicio == ano and p.periodo == 3
                and p.termina <= base.ate), None)
    q = Quadro(3, f"Fim do mandato encerrado em 31/12/{ano}",
               "RGF do 3º quadrimestre do último ano do mandato: caixa por destinação depois dos restos a pagar "
               "(art. 42) e despesa bruta com pessoal nos 180 dias finais (art. 21).",
               ["Medida", "Valor", "Limiar"])
    if rgf is None:
        parte.notas.append(f"O RGF do 3º quadrimestre de {ano} não está no banco: o fim do mandato encerrado em "
                           f"31/12/{ano} não pôde ser medido.")
        return parte
    original = base.original_do_periodo("RGF", ano, 3)

    # Art. 42: caixa por destinação.
    regra42 = base.mapa.regra("FIM-DE-MANDATO-CAIXA")
    minimo = float(regra42.valor or 0.0)
    caixa = caixa_por_destinacao(base, ano)
    negativas = {c: v for c, v in caixa.items() if not c.upper().startswith("TOTAL") and v < minimo}
    for c, v in caixa.items():
        if c.upper().startswith("TOTAL") or v < minimo:
            q.linhas.append(Linha(f"Caixa líquido após restos a pagar: {c}", [moeda(v), f"no mínimo {moeda(minimo)}"],
                                  Selo.AZUL, original))
    if negativas:
        parte.fichas.append(emitir(
            codigo=f"PISO-MANDATO-CAIXA-{ano}",
            familia=Familia.PISO,
            titulo=f"Fim do mandato de {ano}: destinações sem caixa para os restos a pagar",
            gravidade=regra42.gravidade,
            como_deveria=("Nos dois últimos quadrimestres do mandato, nenhuma obrigação sem caixa para pagá-la; "
                          "cada destinação fecha o ano com caixa líquido não negativo depois dos restos a pagar."),
            norma=regra42.norma,
            como_esta="; ".join(f"{c}: {moeda(v)}" for c, v in sorted(negativas.items(), key=lambda kv: kv[1]))
                      + f" ({rgf.rotulo}, Anexo 5).",
            niveis=[Nivel.B],
            providencia=("Pedir a relação das obrigações contraídas de maio a dezembro do último ano nessas "
                         "destinações, com as datas dos empenhos, e o parecer do controle interno sobre o art. 42."),
            observacao="indício, não acusação",
        ))

    # Art. 21, II: despesa bruta nos 180 dias finais.
    regra21 = base.mapa.regra("FIM-DE-MANDATO-PESSOAL")
    teto = float(regra21.get("aumento_maximo", 0.0))
    meses = base.lt.serie_mensal(rgf, "Anexo 01", "DespesaComPessoalBruta")
    if meses:
        jan_dez = list(reversed(meses))          # a série vem do mês de referência para trás
        antes = sum(jan_dez[0:6]) / 6
        depois = sum(jan_dez[6:11]) / 5
        aumento = 100.0 * (depois / antes - 1) if antes else None
        q.linhas.append(Linha("Despesa bruta com pessoal, média de janeiro a junho", [moeda(antes), ""],
                              Selo.AZUL, original))
        q.linhas.append(Linha("Despesa bruta com pessoal, média de julho a novembro",
                              [moeda(depois), f"aumento de até {pct(teto)}"], Selo.AZUL, original))
        if aumento is not None and aumento > teto:
            parte.fichas.append(emitir(
                codigo=f"PISO-MANDATO-PESSOAL-{ano}",
                familia=Familia.PISO,
                titulo=f"Fim do mandato de {ano}: despesa com pessoal maior nos 180 dias finais",
                gravidade=regra21.gravidade,
                como_deveria="Nenhum ato de que resulte aumento da despesa com pessoal nos 180 dias anteriores ao "
                             "fim do mandato.",
                norma=regra21.norma + ", II",
                como_esta=(f"Média mensal da despesa bruta de julho a novembro de {ano}: {moeda(depois)}, contra "
                           f"{moeda(antes)} de janeiro a junho ({pct(aumento)}; {rgf.rotulo}, Anexo 1)."),
                niveis=[Nivel.B],
                providencia=("Pedir os atos de pessoal publicados de 4 de julho a 31 de dezembro (nomeações, "
                             "reajustes, gratificações, progressões) e o impacto de cada um."),
                observacao="indício, não acusação: crescimento vegetativo também aparece aqui",
            ))
    q.regra = (f"FIM-DE-MANDATO-CAIXA: no mínimo {moeda(minimo)} em cada destinação. FIM-DE-MANDATO-PESSOAL: "
               f"aumento de até {pct(teto)}.")
    parte.quadros.append(q)
    return parte
