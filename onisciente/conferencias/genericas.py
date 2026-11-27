"""Ação genérica: gasto de função finalística classificado como administração geral (ACAO-GENERICA).

Para cada função finalística, a parte do liquidado no exercício que foi para a subfunção 122
(Administração Geral). Via 1: matriz de saldos contábeis (função e subfunção de cada empenho, contas
de liquidação). Via 2: RREO Anexo 2, linha "FUxx - Administração Geral". Acima do limiar do mapa
legal, a dotação deixa de dizer onde o dinheiro chega.
"""

from __future__ import annotations

from ..nucleo.ausencias import Ausencia
from ..nucleo.indicios import Familia, emitir
from ..nucleo.provas import Nivel
from ..nucleo.selos import Selo, Via, selar
from .banco import FAZENDA, SOMA, Base, Linha, Parte, Quadro, moeda, pct

REGRA = "ACAO-GENERICA"

FUNCOES = {
    "01": "Legislativa", "02": "Judiciária", "03": "Essencial à Justiça", "04": "Administração",
    "05": "Defesa Nacional", "06": "Segurança Pública", "07": "Relações Exteriores",
    "08": "Assistência Social", "09": "Previdência Social", "10": "Saúde", "11": "Trabalho",
    "12": "Educação", "13": "Cultura", "14": "Direitos da Cidadania", "15": "Urbanismo",
    "16": "Habitação", "17": "Saneamento", "18": "Gestão Ambiental", "19": "Ciência e Tecnologia",
    "20": "Agricultura", "21": "Organização Agrária", "22": "Indústria", "23": "Comércio e Serviços",
    "24": "Comunicações", "25": "Energia", "26": "Transporte", "27": "Desporto e Lazer",
    "28": "Encargos Especiais",
}

_LIQUIDADO = ("(conta_contabil like '6221303%' or conta_contabil like '6221304%' or "
              "conta_contabil like '6221307%') and substr(natureza_despesa, 3, 2) != '91'")


def por_funcao(base: Base, meses: list[str]) -> dict[str, tuple[float, float]]:
    """{função: (liquidado total, liquidado na subfunção 122)} nos meses, exceto intraorçamentária."""
    if not meses:
        return {}
    marcas = ",".join("?" for _ in meses)
    saida: dict[str, list[float]] = {}
    for funcao, sub, v in base.con.execute(
            f"select funcao, subfuncao, {SOMA} from msc_itens where {_LIQUIDADO} and mes in ({marcas}) "
            "group by 1, 2", meses):
        f = str(funcao or "").zfill(2)
        if f == "00":
            continue
        tot = saida.setdefault(f, [0.0, 0.0])
        tot[0] += v or 0.0
        if str(sub or "").zfill(3) == "122":
            tot[1] += v or 0.0
    return {f: (t, g) for f, (t, g) in saida.items()}


def no_rreo(base: Base, exercicio: int, periodo: int) -> tuple[dict[str, float], dict[str, float]]:
    """({função: liquidado total}, {função: liquidado em Administração Geral}) do RREO Anexo 2."""
    linhas = base.con.execute(
        "select conta, valor from siconfi_itens where demonstrativo = 'RREO' and exercicio = ? and periodo = ? "
        "and anexo = 'RREO-Anexo 02' and cod_conta = 'RREO2TotalDespesas' "
        "and coluna like 'DESPESAS LIQUIDADAS AT%'", (exercicio, periodo)).fetchall()
    nomes = {v: k for k, v in FUNCOES.items()}
    total, geral = {}, {}
    for conta, valor in linhas:
        conta = conta or ""
        if conta in nomes:
            total[nomes[conta]] = float(valor or 0.0)
        elif conta.startswith("FU") and conta.endswith("Administração Geral"):
            geral[conta[2:4]] = float(valor or 0.0)
    return total, geral


def conferir(base: Base) -> Parte:
    parte = Parte()
    if not base.tem("msc_itens"):
        return parte
    regra = base.mapa.regra(REGRA)
    limite = float(regra.valor or 10.0)
    meio = set(regra.get("funcoes_meio") or ["01", "02", "03", "04", "28"])
    rreo = base.lt.ultimo("RREO", base.ate)
    if rreo is None:
        return parte
    meses = [m for m in base.meses_msc()
             if m.startswith(f"{rreo.exercicio}-") and m <= f"{rreo.termina:%Y-%m}"]
    if len(meses) < 2 * rreo.periodo:
        parte.notas.append(f"A matriz de saldos contábeis não cobre o {rreo.rotulo} inteiro: a ação genérica "
                           "fica sem a segunda via.")
    msc = por_funcao(base, meses)
    total_rreo, geral_rreo = no_rreo(base, rreo.exercicio, rreo.periodo)
    q = Quadro(4, f"Administração geral dentro das funções finalísticas ({rreo.rotulo})",
               "Liquidado no exercício até o bimestre. Via 1: matriz de saldos contábeis (função e subfunção). "
               "Via 2: RREO Anexo 2. Funções meio (legislativa, judiciária, essencial à justiça, administração "
               "e encargos especiais) ficam fora.",
               ["Função", "Liquidado na função", "Administração geral", "Parte"],
               regra=f"{REGRA}: até {limite:g}% do liquidado da função. {regra.get('justificativa', '')}")
    acima = []
    for f in sorted(set(msc) | set(geral_rreo)):
        if f in meio:
            continue
        if f in msc:
            total, geral = msc[f]
        else:
            total, geral = total_rreo.get(f), geral_rreo.get(f)
        if not total or total <= 0:
            continue
        # O RREO só abre a linha de administração geral quando há valor nela: sem a linha, a via diz zero.
        via_rreo = geral_rreo.get(f, 0.0 if f in total_rreo else None)
        cert = selar([Via("matriz de saldos contábeis", geral if f in msc else None),
                      Via("RREO Anexo 2", via_rreo)])
        parte.certificacoes.append(cert)
        share = 100.0 * (geral or 0.0) / total
        q.linhas.append(Linha(f"{f} {FUNCOES.get(f, '')}", [moeda(total), moeda(geral), pct(share)],
                              cert.selo or Selo.AZUL, base.original_do_periodo("RREO", rreo.exercicio, rreo.periodo)))
        if share > limite:
            acima.append((f, total, geral or 0.0, share, cert.selo))
    contas = _despesa_por_funcao(base, rreo, msc, total_rreo, len(meses) >= 2 * rreo.periodo)
    if contas.linhas:
        parte.quadros.append(contas)
    if q.linhas:
        parte.quadros.append(q)
    if acima:
        dois = all(s is Selo.VERDE for *_, s in acima)
        parte.fichas.append(emitir(
            codigo=f"ORC-ACAO-GENERICA-{rreo.exercicio}",
            familia=Familia.ORC,
            titulo=(f"Gasto finalístico classificado como administração geral acima de {limite:g}% em "
                    f"{len(acima)} função{'ões' if len(acima) != 1 else ''}"),
            gravidade=regra.gravidade,
            como_deveria=(f"A despesa de cada função finalística se classifica na subfunção da sua finalidade; a "
                          f"administração geral não deve passar de {limite:g}% do liquidado da função "
                          "(limiar do mapa legal)."),
            norma=regra.norma,
            como_esta="; ".join(f"{FUNCOES.get(f, f)}: {moeda(g)} de {moeda(t)} ({pct(s)})"
                                for f, t, g, s, _ in sorted(acima, key=lambda x: -x[2])) + f" ({rreo.rotulo}). "
                      + ("A matriz de saldos contábeis e o RREO dizem o mesmo." if dois else ""),
            niveis=[Nivel.B],
            providencia=("Pedir o quadro de detalhamento da despesa por ação e elemento das subfunções de "
                         "administração geral dessas funções, com as unidades que executam."),
            observacao="indício, não acusação",
        ))
        parte.ausencias.append(Ausencia(
            o_que_falta="Execução da despesa por ação, subfunção e elemento nas funções finalísticas",
            conferencia_impedida="saber o que a administração geral das funções finalísticas comprou de fato",
            onde_deveria_estar="Portal da Transparência de Goiânia, execução da despesa por ação",
            fundamento="LC 101/2000, arts. 48 e 48-A; Lei 9.262/2013, art. 7º, § 3º",
            periodo=f"exercício {rreo.exercicio}", orgao=FAZENDA, bloco="Execução da despesa"))
    return parte


TOLERANCIA_CONTAS = 1e-6   # RREO e matriz saem da mesma contabilidade: só o arredondamento separa


def _despesa_por_funcao(base: Base, rreo, msc: dict[str, tuple[float, float]], total_rreo: dict[str, float],
                        matriz_completa: bool) -> Quadro:
    """As contas da despesa, uma a uma: o liquidado de cada função nas duas vias, selado, com o original."""
    q = Quadro(4, f"A despesa por função, conta a conta ({rreo.rotulo})",
               "Liquidado no exercício até o bimestre em cada função, exceto intraorçamentário. Via 1: RREO Anexo 2. "
               "Via 2: matriz de saldos contábeis dos mesmos meses. As duas saem da mesma contabilidade e só o "
               "arredondamento as separa; qualquer diferença acima disso tira o selo verde.",
               ["Função", "RREO Anexo 2", "Matriz de saldos contábeis", "Resultado"])
    original = base.original_do_periodo("RREO", rreo.exercicio, rreo.periodo)
    for f in sorted(set(total_rreo) | set(msc)):
        via_msc = msc[f][0] if (f in msc and matriz_completa) else None
        cert = selar([Via("RREO Anexo 2", total_rreo.get(f)), Via("matriz de saldos contábeis", via_msc)],
                     tolerancia=TOLERANCIA_CONTAS)
        if cert.selo is None:
            continue
        resultado = ("iguais" if cert.selo is Selo.VERDE else "divergem" if cert.divergencia
                     else "uma via só")
        q.linhas.append(Linha(f"{f} {FUNCOES.get(f, '')}", [moeda(total_rreo.get(f)), moeda(via_msc), resultado],
                              Selo.VERMELHO if cert.divergencia else cert.selo, original))
    divergentes = [x for x in q.linhas if x.valores[-1] == "divergem"]
    if divergentes:
        q.notas.append(f"{len(divergentes)} função(ões) com as duas vias diferentes: o número de cada uma fica com a "
                       "fonte ao lado e nenhum dos dois é tido como certo.")
    return q
