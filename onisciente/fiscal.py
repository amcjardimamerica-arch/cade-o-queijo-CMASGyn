"""O Município pelos demonstrativos fiscais já guardados no banco histórico.

Lê o RGF e o RREO que o SICONFI devolveu (tabela ``siconfi_itens`` do banco
``dados/onisciente/historico.db``) e faz três coisas, sem rede e sem pessoa no meio:

1. **Tetos da LRF e do Senado, com cálculo próprio.** Despesa com pessoal (54%),
   dívida consolidada líquida (120%) e operações de crédito (16%) são refeitas a
   partir das parcelas do próprio demonstrativo (a despesa bruta mês a mês, as
   exclusões do art. 19, a dívida e as deduções), e o percentual refeito é comparado
   com o declarado. A divergência acima da tolerância do mapa legal é indício.
2. **Duas vias.** O mesmo número publicado em dois demonstrativos homologados em
   separado (RGF e RREO) é selado: verde se dizem o mesmo dentro de 1%, azul com
   divergência, que vira ficha. A receita corrente líquida e a dívida consolidada
   líquida têm sempre as duas vias.
3. **Quanto a função gastou.** O liquidado até o bimestre por função (RREO Anexo 2),
   que é o denominador da cobertura da trilha.

Cada número sai com o demonstrativo, o período, o anexo e a linha de onde veio.
"""

from __future__ import annotations

import calendar
import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path

from . import RAIZ
from .legal.mapa import MapaLegal, carregar
from .nucleo.indicios import Familia, Ficha, emitir
from .nucleo.provas import Nivel
from .nucleo.selos import Certificacao, Selo, Via, selar
from .pisos import Medida, fichas_da_medida, medir

BANCO = RAIZ / "dados" / "onisciente" / "historico.db"


@dataclass(frozen=True)
class Periodo:
    demonstrativo: str
    exercicio: int
    periodo: int
    termina: date

    @property
    def rotulo(self) -> str:
        if self.demonstrativo == "RGF":
            return f"RGF do {self.periodo}º quadrimestre de {self.exercicio}"
        if self.demonstrativo == "RREO":
            return f"RREO do {self.periodo}º bimestre de {self.exercicio}"
        return f"{self.demonstrativo} de {self.exercicio}"


@dataclass
class ConferenciaDeVias:
    """Um número publicado em mais de um demonstrativo, selado pelas vias."""

    titulo: str
    certificacao: Certificacao
    referencia: str
    norma: str = "LC 101/2000, arts. 48, 52 e 55"
    # Duas vias de verdade são dois demonstrativos homologados em separado. A soma das
    # parcelas contra o total do mesmo anexo é conta fechada: confere, mas não é outra via.
    entre_demonstrativos: bool = True

    @property
    def selo(self) -> Selo | None:
        return self.certificacao.selo

    def como_dict(self) -> dict:
        c = self.certificacao
        return {"titulo": self.titulo, "referencia": self.referencia,
                "selo": c.selo.value if c.selo else None, "divergencia": c.divergencia,
                "entre_demonstrativos": self.entre_demonstrativos,
                "vias": [{"fonte": v.fonte, "valor": v.valor} for v in c.vias], "nota": c.nota}


@dataclass
class Fiscal:
    """O que os demonstrativos fiscais dizem do Município numa data."""

    rgf: Periodo | None = None
    rreo: Periodo | None = None
    medidas: list[Medida] = field(default_factory=list)
    conferencias: list[ConferenciaDeVias] = field(default_factory=list)
    memoria: dict[str, str] = field(default_factory=dict)   # regra -> memória de cálculo
    fontes: dict[str, str] = field(default_factory=dict)    # regra -> demonstrativos usados
    notas: list[str] = field(default_factory=list)

    def fichas(self, competencia: str, ente: str = "o Município") -> list[Ficha]:
        out: list[Ficha] = []
        for m in self.medidas:
            for f in fichas_da_medida(m, competencia=competencia, ente=ente):
                fonte = self.fontes.get(m.regra.id) or (self.rgf.rotulo if self.rgf else "")
                f.observacao = (self.memoria.get(m.regra.id) or "") + (f" Fonte: {fonte}." if fonte else "")
                out.append(f)
        for c in self.conferencias:
            if not c.certificacao.divergencia:
                continue
            vias = "; ".join(f"{v.fonte}: {_moeda(v.valor)}" for v in c.certificacao.vias)
            out.append(emitir(
                codigo=f"VIAS-{_slug(c.titulo)}-{competencia}",
                familia=Familia.PISO,
                titulo=f"{c.titulo}: os demonstrativos divergem",
                gravidade="alta",
                como_deveria="O mesmo valor publicado em dois demonstrativos do mesmo período deve ser igual.",
                norma=c.norma,
                como_esta=f"{c.referencia}. {vias}.",
                niveis=[Nivel.B, Nivel.B],
                providencia="Pedir a conciliação entre os dois demonstrativos e a retificação no SICONFI.",
                competencia=competencia,
            ))
        return out

    def certificacoes(self) -> list[Certificacao]:
        """Os valores com duas vias independentes (RGF contra RREO), para a coerência."""
        return [c.certificacao for c in self.conferencias
                if c.entre_demonstrativos and c.certificacao.selo in (Selo.VERDE, Selo.AZUL)
                and len(c.certificacao.vias) >= 2]


def _moeda(v: float | None) -> str:
    if v is None:
        return "não informado"
    s = f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-R$ " if v < 0 else "R$ ") + s


def _slug(t: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]+", "-", sem_acento.upper()).strip("-")[:30].rstrip("-")


class Leitor:
    """Leitura somente dos itens do SICONFI guardados no banco histórico."""

    def __init__(self, caminho: Path | str = BANCO):
        self.caminho = Path(caminho)
        if not self.caminho.exists():
            raise FileNotFoundError(f"banco histórico não encontrado: {self.caminho}")
        self.con = sqlite3.connect(f"file:{self.caminho}?mode=ro", uri=True)

    def fechar(self) -> None:
        self.con.close()

    def periodos(self, demonstrativo: str) -> list[Periodo]:
        linhas = self.con.execute(
            "select exercicio, periodo, termina from siconfi_periodos where demonstrativo=? "
            "and situacao='entregue' and itens>0 order by exercicio, periodo", (demonstrativo,))
        return [Periodo(demonstrativo, e, p, date.fromisoformat(t)) for e, p, t in linhas]

    def ultimo(self, demonstrativo: str, ate: date) -> Periodo | None:
        cand = [p for p in self.periodos(demonstrativo) if p.termina <= ate]
        return cand[-1] if cand else None

    def valor(self, per: Periodo, anexo: str, cod_conta: str, coluna: str,
              conta: str | None = None) -> float | None:
        """Valor de uma linha; ``coluna`` é expressão regular sobre o rótulo da coluna."""
        sql = ("select coluna, valor from siconfi_itens where demonstrativo=? and exercicio=? and "
               "periodo=? and anexo=? and cod_conta=?")
        args: list = [per.demonstrativo, per.exercicio, per.periodo, f"{per.demonstrativo}-{anexo}",
                      cod_conta]
        if conta is not None:
            sql += " and conta=?"
            args.append(conta)
        rx = re.compile(coluna, re.I)
        achados = [v for c, v in self.con.execute(sql, args) if rx.fullmatch(c or "")]
        return achados[0] if achados else None

    def serie_mensal(self, per: Periodo, anexo: str, cod_conta: str) -> list[float] | None:
        """As doze colunas mensais (<MR-11> .. <MR>) de uma linha; None se faltar alguma."""
        linhas = dict(self.con.execute(
            "select coluna, valor from siconfi_itens where demonstrativo=? and exercicio=? and periodo=? "
            "and anexo=? and cod_conta=? and coluna like '<MR%'",
            (per.demonstrativo, per.exercicio, per.periodo, f"{per.demonstrativo}-{anexo}", cod_conta)))
        colunas = ["<MR>"] + [f"<MR-{k}>" for k in range(1, 12)]
        if not all(c in linhas for c in colunas):
            return None
        return [float(linhas[c] or 0.0) for c in colunas]


def bimestre_do_quadrimestre(q: int) -> int:
    """O RREO que fecha no mesmo dia do RGF: 1º quad -> 2º bim, 2º -> 4º, 3º -> 6º."""
    return 2 * q


def medir_municipio(ate: date, *, banco: Path | str = BANCO, mapa: MapaLegal | None = None,
                    faixa_camara: str | None = None) -> Fiscal:
    """Mede o Município pelo último RGF e RREO entregues até ``ate``."""
    mapa = mapa or carregar()
    if faixa_camara is None:
        from .config import carregar_alvo
        faixa_camara = carregar_alvo().faixa_camara
    leitor = Leitor(banco)
    try:
        fiscal = _medir(leitor, ate, mapa)
        _medir_camara(leitor, ate, mapa, fiscal, faixa_camara)
        _medir_saude(leitor, ate, mapa, fiscal)
        _medir_educacao(leitor, ate, mapa, fiscal)
        return fiscal
    finally:
        leitor.fechar()


def _medir(lt: Leitor, ate: date, mapa: MapaLegal) -> Fiscal:
    fiscal = Fiscal(rgf=lt.ultimo("RGF", ate), rreo=lt.ultimo("RREO", ate))
    rgf = fiscal.rgf
    if rgf is None:
        fiscal.notas.append("Nenhum RGF entregue até a data no banco histórico.")
        return fiscal
    q = rgf.periodo
    par = next((p for p in lt.periodos("RREO")
                if p.exercicio == rgf.exercicio and p.periodo == bimestre_do_quadrimestre(q)), None)

    # --- Despesa com pessoal (LRF, arts. 19 e 20) -------------------------------------
    bruta_meses = lt.serie_mensal(rgf, "Anexo 01", "DespesaComPessoalBruta")
    bruta_total = lt.valor(rgf, "Anexo 01", "DespesaComPessoalBruta", r"TOTAL \(ÚLTIMOS 12 MESES\).*")
    bruta_rp = lt.valor(rgf, "Anexo 01", "DespesaComPessoalBruta", r"INSCRITAS EM RESTOS A PAGAR.*")
    nao_comp = lt.valor(rgf, "Anexo 01", "DespesaComPessoalNaoComputada", r"TOTAL \(ÚLTIMOS 12 MESES\).*")
    nao_comp_rp = lt.valor(rgf, "Anexo 01", "DespesaComPessoalNaoComputada", r"INSCRITAS EM RESTOS A PAGAR.*")
    rcl_aj_pessoal = lt.valor(rgf, "Anexo 01", "ReceitaCorrenteLiquidaAjustada", "Valor")
    dtp_declarada = lt.valor(rgf, "Anexo 01", "DespesaComPessoalTotal", "Valor")
    pct_pessoal = lt.valor(rgf, "Anexo 01", "DespesaComPessoalTotal", r"% sobre a RCL Ajustada")
    if None not in (bruta_total, nao_comp):
        # Cálculo próprio: a bruta pelos doze meses publicados, quando estão todos.
        bruta = sum(bruta_meses) if bruta_meses else bruta_total
        dtp = (bruta - nao_comp) + ((bruta_rp or 0.0) - (nao_comp_rp or 0.0))
        fiscal.medidas.append(medir("PESSOAL-EXECUTIVO", dtp, rcl_aj_pessoal, declarado=pct_pessoal,
                                    mapa=mapa))
        fiscal.memoria["PESSOAL-EXECUTIVO"] = (
            f"Despesa bruta de {_moeda(bruta)} ({'soma dos doze meses publicados' if bruta_meses else 'total declarado'}), "
            f"menos {_moeda(nao_comp)} não computados (art. 19, § 1º), mais restos a pagar não processados "
            f"líquidos de {_moeda((bruta_rp or 0.0) - (nao_comp_rp or 0.0))}: {_moeda(dtp)}, sobre a RCL ajustada "
            f"de {_moeda(rcl_aj_pessoal)}.")
        if bruta_meses and bruta_total:
            fiscal.conferencias.append(ConferenciaDeVias(
                "Despesa bruta com pessoal: doze meses contra o total",
                selar([Via("RGF, soma dos doze meses", sum(bruta_meses)),
                       Via("RGF, total declarado", bruta_total)], tolerancia=0.01),
                rgf.rotulo, "LC 101/2000, art. 18, § 2º", entre_demonstrativos=False))
        if dtp_declarada:
            fiscal.conferencias.append(ConferenciaDeVias(
                "Despesa total com pessoal: parcelas contra o total",
                selar([Via("RGF, soma das parcelas", dtp), Via("RGF, total declarado", dtp_declarada)]),
                rgf.rotulo, "LC 101/2000, arts. 18 e 19", entre_demonstrativos=False))
    else:
        fiscal.medidas.append(medir("PESSOAL-EXECUTIVO", None, None, mapa=mapa))

    # --- Dívida consolidada líquida (Resolução do Senado 40/2001) ----------------------
    col_q = rf"Até o {q}º Quadrimestre"
    dcl = lt.valor(rgf, "Anexo 02", "DividaConsolidadaLiquida", col_q)
    dc = lt.valor(rgf, "Anexo 02", "DividaConsolidada", col_q)
    ded = lt.valor(rgf, "Anexo 02", "DeducoesDaDividaConsolidada", col_q)
    rcl_end = lt.valor(rgf, "Anexo 02", "ReceitaCorrenteLiquidaAjustadaParaCalculoDosLimitesDeEndividamento", col_q)
    pct_dcl = lt.valor(rgf, "Anexo 02", "PercentualDaDCLSobreARCL", col_q)
    base_dcl = (dc - ded) if (dc is not None and ded is not None) else dcl
    fiscal.medidas.append(medir("DIVIDA-CONSOLIDADA", base_dcl, rcl_end, declarado=pct_dcl, mapa=mapa))
    fiscal.memoria["DIVIDA-CONSOLIDADA"] = (
        f"Dívida consolidada líquida de {_moeda(base_dcl)}"
        + (f" (dívida de {_moeda(dc)} menos deduções de {_moeda(ded)})" if ded is not None else "")
        + f", sobre a RCL ajustada para endividamento de {_moeda(rcl_end)}.")

    # --- Operações de crédito (Resolução do Senado 43/2001) ----------------------------
    oc = lt.valor(rgf, "Anexo 04", "RGF4OperacoesDeCreditoTotal", r"Até o Quadrimestre de Referência.*")
    oc_considerado = lt.valor(rgf, "Anexo 04",
                              "TotalConsideradoParaFinsDaApuracaoDoCumprimentoDoLimiteOperacoesDeCredito",
                              "VALOR")
    pct_oc = lt.valor(rgf, "Anexo 04",
                      "TotalConsideradoParaFinsDaApuracaoDoCumprimentoDoLimiteOperacoesDeCredito",
                      r"% SOBRE A RCL AJUSTADA")
    oc_base = oc_considerado if oc_considerado is not None else oc
    fiscal.medidas.append(medir("OPERACOES-CREDITO", oc_base, rcl_end, declarado=pct_oc, mapa=mapa))
    fiscal.memoria["OPERACOES-CREDITO"] = (
        f"Operações de crédito consideradas no limite, até o quadrimestre: {_moeda(oc_base)}, sobre a RCL "
        f"ajustada para endividamento de {_moeda(rcl_end)}.")

    # --- Duas vias: RGF contra o RREO que fecha no mesmo dia ---------------------------
    if par is None:
        fiscal.notas.append(f"O RREO do {bimestre_do_quadrimestre(q)}º bimestre de {rgf.exercicio} não está "
                            "no banco: a receita corrente líquida e a dívida ficam com uma via só.")
    else:
        ref = f"{rgf.rotulo} e {par.rotulo}"
        rcl_rgf = lt.valor(rgf, "Anexo 01", "ReceitaCorrenteLiquidaLimiteLegal", "Valor")
        rcl_rreo = lt.valor(par, "Anexo 03", "RREO3ReceitaCorrenteLiquida", r"TOTAL \(ÚLTIMOS 12 MESES\)")
        fiscal.conferencias.append(ConferenciaDeVias(
            "Receita corrente líquida", selar([Via("RGF Anexo 1", rcl_rgf), Via("RREO Anexo 3", rcl_rreo)]),
            ref))
        aj_rreo = lt.valor(par, "Anexo 03", "RREO3ReceitaCorrenteLiquidaAjustadaParaCalculoDosLimitesDaDespesaComPessoal",
                           r"TOTAL \(ÚLTIMOS 12 MESES\)")
        fiscal.conferencias.append(ConferenciaDeVias(
            "Receita corrente líquida ajustada para a despesa com pessoal",
            selar([Via("RGF Anexo 1", rcl_aj_pessoal), Via("RREO Anexo 3", aj_rreo)]), ref))
        dcl_rreo = lt.valor(par, "Anexo 06", "DividaConsolidadaLiquida", r"Até o Bimestre.*")
        fiscal.conferencias.append(ConferenciaDeVias(
            "Dívida consolidada líquida", selar([Via("RGF Anexo 2", dcl), Via("RREO Anexo 6", dcl_rreo)]),
            ref, "LC 101/2000, arts. 53 e 55; Resolução do Senado 40/2001"))
    return fiscal


# Base do art. 29-A: receita tributária e as transferências dos arts. 153, § 5º, 158 e 159 da CF
# efetivamente realizadas no exercício anterior, sem a dedução do FUNDEB.
BASE_29A_RREO = {  # RREO Anexo 3, coluna dos últimos 12 meses do 6º bimestre
    "ReceitaTributariaLiquidaExcetoTransferenciasEFUNDEB": "Impostos, taxas e contribuições de melhoria",
    "RREO3CotaParteDoFPM": "Cota-parte do FPM",
    "RREO3CotaParteDoICMS": "Cota-parte do ICMS",
    "RREO3CotaParteDoIPVA": "Cota-parte do IPVA",
    "RREO3CotaParteDoITR": "Cota-parte do ITR",
    "RREO3TransferenciasDaLC611989": "IPI-exportação (LC 61/1989)",
}
BASE_29A_DCA = ("RO1.7.1.1.51.0.0", "RO1.7.2.1.50.0.0", "RO1.7.2.1.51.0.0", "RO1.7.1.1.52.0.0",
                "RO1.7.2.1.52.0.0")   # FPM, ICMS, IPVA, ITR, IPI-exportação na DCA Anexo I-C


def _dca(lt: Leitor, exercicio: int, anexo: str, cod_conta: str, coluna: str,
         conta: str | None = None) -> float | None:
    per = next((p for p in lt.periodos("DCA") if p.exercicio == exercicio), None)
    return lt.valor(per, anexo, cod_conta, coluna, conta=conta) if per else None


def _medir_camara(lt: Leitor, ate: date, mapa: MapaLegal, fiscal: Fiscal, faixa: str) -> None:
    """Art. 29-A: a despesa do Legislativo no último exercício fechado sobre a base do anterior.

    Numerador: o liquidado na função Legislativa (RREO Anexo 2 do 6º bimestre), com as
    intraorçamentárias, que são despesa da Câmara (as contribuições patronais); os inativos
    ficam na função Previdência e não entram. Segunda via: a DCA do exercício (Anexo I-E).
    Denominador: a base do exercício anterior pelo RREO Anexo 3, com segunda via na DCA (I-C).
    """
    fechados = [p for p in lt.periodos("RREO") if p.periodo == 6 and p.termina <= ate]
    if not fechados:
        fiscal.notas.append("Câmara (CF, art. 29-A): nenhum exercício fechado no banco.")
        fiscal.medidas.append(medir("CAMARA", None, None, faixa=faixa, mapa=mapa))
        return
    fim = fechados[-1]
    ant = next((p for p in fechados if p.exercicio == fim.exercicio - 1), None)
    sql = ("select rotulo, valor from siconfi_itens where demonstrativo='RREO' and exercicio=? and "
           "periodo=6 and anexo='RREO-Anexo 02' and conta='Legislativa' and "
           "coluna like 'DESPESAS LIQUIDADAS ATÉ O BIMESTRE%'")
    linhas = dict(lt.con.execute(sql, (fim.exercicio,)).fetchall())
    exceto = next((v for r, v in linhas.items() if r.startswith("Total das Despesas Exceto Intra")), None)
    intra = next((v for r, v in linhas.items() if r.startswith("Total das Despesas Intra")), 0.0)
    base = None
    if ant is not None:
        partes = {k: lt.valor(ant, "Anexo 03", k, r"TOTAL \(ÚLTIMOS 12 MESES\)") for k in BASE_29A_RREO}
        if None not in partes.values():
            base = sum(partes.values())
    despesa = (exceto + (intra or 0.0)) if exceto is not None else None
    m = medir("CAMARA", despesa, base, faixa=faixa, mapa=mapa)
    ref = f"Câmara em {fim.exercicio} sobre a base de {fim.exercicio - 1}"
    if base is None:
        fiscal.notas.append(f"Câmara (CF, art. 29-A): o RREO do 6º bimestre de {fim.exercicio - 1}, "
                            "que dá a base do limite, não está no banco.")
    # Segunda via de cada parcela, na DCA do mesmo exercício.
    vias_ok = []
    dca_desp = _dca(lt, fim.exercicio, "Anexo I-E", "TotalDespesas", "Despesas Liquidadas",
                    conta="01 - Legislativa")
    if exceto is not None:
        c = ConferenciaDeVias(f"Despesa liquidada da Câmara em {fim.exercicio}",
                              selar([Via("RREO Anexo 2", exceto), Via("DCA Anexo I-E", dca_desp)]),
                              f"{fim.rotulo} e DCA de {fim.exercicio}", "CF, art. 29-A; LC 101/2000, art. 51")
        fiscal.conferencias.append(c)
        vias_ok.append(c.selo is Selo.VERDE)
    if base is not None:
        trib = _dca(lt, ant.exercicio, "Anexo I-C", "RO1.1.0.0.00.0.0", "Receitas Brutas Realizadas")
        ded = _dca(lt, ant.exercicio, "Anexo I-C", "RO1.1.0.0.00.0.0", "Outras Deduções da Receita") or 0.0
        transf = [_dca(lt, ant.exercicio, "Anexo I-C", k, "Receitas Brutas Realizadas") for k in BASE_29A_DCA]
        base_dca = (trib - ded + sum(transf)) if trib is not None and None not in transf else None
        c = ConferenciaDeVias(f"Base do limite da Câmara ({ant.exercicio})",
                              selar([Via("RREO Anexo 3", base), Via("DCA Anexo I-C", base_dca)]),
                              f"{ant.rotulo} e DCA de {ant.exercicio}", "CF, art. 29-A; LC 101/2000, art. 51")
        fiscal.conferencias.append(c)
        vias_ok.append(c.selo is Selo.VERDE)
        fiscal.memoria["CAMARA"] = (
            f"Despesa liquidada na função Legislativa em {fim.exercicio}: {_moeda(exceto)}, mais "
            f"{_moeda(intra)} de despesas intraorçamentárias (contribuições patronais), total "
            f"{_moeda(despesa)}; sobre a receita tributária e as transferências constitucionais de "
            f"{ant.exercicio} ({', '.join(BASE_29A_RREO.values())}): {_moeda(base)}. "
            f"Limite da faixa {faixa}. Inativos ficam na função Previdência e não entram.")
    # Sem percentual declarado, o número é certificado pelas duas vias das parcelas.
    if m.situacao != "sem_dado" and len(vias_ok) == 2 and all(vias_ok):
        m = replace(m, selo=Selo.VERDE)
    fiscal.medidas.append(m)
    fiscal.fontes["CAMARA"] = f"{fim.rotulo}, RREO do 6º bimestre de {fim.exercicio - 1} e DCA"


# --- Saúde (CF, art. 198, § 2º; LC 141/2012, art. 7º) ------------------------------------

def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode()
    return " ".join(t.upper().split())


class Externo:
    """Um demonstrativo homologado fora do SICONFI (SIOPS, SIOPE), linha a linha."""

    def __init__(self, lt: Leitor, fonte: str, exercicio: int, periodo: int, homologado: str):
        self.fonte, self.exercicio, self.periodo, self.homologado = fonte, exercicio, periodo, homologado
        self.linhas: dict[int, tuple[str, str, dict[int, float]]] = {}
        for ordem, rotulo, quadro, coluna, valor in lt.con.execute(
                "select ordem, rotulo, titulo_quadro, coluna, valor from externos_itens where fonte=? and "
                "exercicio=? and periodo=?", (fonte, exercicio, periodo)):
            self.linhas.setdefault(ordem, (rotulo, quadro, {}))[2][coluna] = valor

    @property
    def termina(self) -> date:
        mes = 2 * self.periodo
        return date(self.exercicio, mes, calendar.monthrange(self.exercicio, mes)[1])

    @property
    def rotulo(self) -> str:
        return f"{self.fonte}, {self.periodo}º bimestre de {self.exercicio}"

    def valor(self, padrao: str, coluna: int) -> float | None:
        rx = re.compile(padrao)
        for ordem in sorted(self.linhas):
            rotulo, _, valores = self.linhas[ordem]
            if rx.search(_norm(rotulo)):
                return valores.get(coluna)
        return None


def ultimo_externo(lt: Leitor, fonte: str, ate: date) -> Externo | None:
    try:
        linhas = lt.con.execute(
            "select exercicio, periodo, homologado from externos_periodos where fonte=? and "
            "situacao='homologado' order by exercicio, periodo", (fonte,)).fetchall()
    except sqlite3.OperationalError:
        return None
    cand = [Externo(lt, fonte, e, p, h) for e, p, h in linhas]
    cand = [x for x in cand if x.termina <= ate]
    return cand[-1] if cand else None


# A receita da base da saúde e da educação (LC 141/2012, art. 7º; CF, art. 212) pelo RREO Anexo 3:
# os quatro impostos municipais e as transferências constitucionais, sem a dedução do FUNDEB.
BASE_IMPOSTOS_RREO = {
    "IPTULiquidoExcetoTransferenciasEFUNDEB": "IPTU",
    "ISSLiquidoExcetoTransferenciasEFUNDEB": "ISS",
    "ITBILiquidoExcetoTransferenciasEFUNDEB": "ITBI",
    "IRRFLiquidoExcetoTransferenciasEFUNDEB": "IRRF",
    "RREO3CotaParteDoICMS": "cota-parte do ICMS",
    "RREO3CotaParteDoIPVA": "cota-parte do IPVA",
    "RREO3CotaParteDoITR": "cota-parte do ITR",
    "RREO3TransferenciasDaLC611989": "IPI-exportação",
}


def base_de_impostos(lt: Leitor, exercicio: int, bimestre: int, *,
                     extraordinarias: bool = False) -> tuple[float | None, str]:
    """Cálculo próprio da receita de impostos e transferências até o bimestre, com a memória.

    No 6º bimestre o FPM vem da DCA (a cota mensal; as cotas extraordinárias de 1% do art.
    159, I, d e e, só com ``extraordinarias`` — a educação as conta, a saúde não) com as
    compensações da LC 176/2020; nos outros, o FPM inteiro do RREO.
    """
    per = next((p for p in lt.periodos("RREO") if p.exercicio == exercicio and p.periodo == bimestre), None)
    if per is None:
        return None, f"o RREO do {bimestre}º bimestre de {exercicio} não está no banco"
    partes: dict[str, float] = {}
    for cod, nome in {**BASE_IMPOSTOS_RREO, "RREO3CotaParteDoFPM": "FPM"}.items():
        serie = lt.serie_mensal(per, "Anexo 03", cod)
        if serie is None:
            return None, f"o RREO Anexo 3 não traz os meses de {nome}"
        partes[nome] = sum(serie[: 2 * bimestre])
    nota = "FPM inteiro do RREO Anexo 3 (as cotas extraordinárias só se separam na DCA)"
    if bimestre == 6:
        mensal = _dca(lt, exercicio, "Anexo I-C", "RO1.7.1.1.51.1.0", "Receitas Brutas Realizadas")
        lc176 = _dca(lt, exercicio, "Anexo I-C", "RO1.7.1.9.58.0.0", "Receitas Brutas Realizadas")
        extra = _dca(lt, exercicio, "Anexo I-C", "RO1.7.1.1.51.2.0", "Receitas Brutas Realizadas")
        if mensal is not None:
            partes["FPM"] = mensal
            nota = "FPM só da cota mensal, pela DCA Anexo I-C, mais as compensações da LC 176/2020"
            if extraordinarias:
                partes["FPM, cotas extraordinárias (CF, art. 159, I, d e e)"] = extra or 0.0
                nota = "FPM pela DCA Anexo I-C, cota mensal e extraordinárias, mais as compensações da LC 176/2020"
            partes["compensações da LC 176/2020"] = lc176 or 0.0
    total = sum(partes.values())
    memoria = ", ".join(f"{k} {_moeda(v)}" for k, v in partes.items()) + f" ({nota})"
    return total, memoria


def _liquidado_com_intra(lt: Leitor, exercicio: int, bimestre: int, funcao: str) -> float | None:
    """RREO Anexo 2: liquidado até o bimestre na função, com as intraorçamentárias."""
    linhas = dict(lt.con.execute(
        "select rotulo, valor from siconfi_itens where demonstrativo='RREO' and exercicio=? and periodo=? "
        "and anexo='RREO-Anexo 02' and conta=? and coluna like 'DESPESAS LIQUIDADAS ATÉ O BIMESTRE%'",
        (exercicio, bimestre, funcao)).fetchall())
    exceto = next((v for r, v in linhas.items() if r.startswith("Total das Despesas Exceto Intra")), None)
    intra = next((v for r, v in linhas.items() if r.startswith("Total das Despesas Intra")), 0.0)
    return exceto + (intra or 0.0) if exceto is not None else None


def _rreo14(lt: Leitor, exercicio: int, bimestre: int, conta_inicio: str) -> float | None:
    """RREO Anexo 14 (demonstrativo simplificado, no SICONFI): o % aplicado declarado."""
    linha = lt.con.execute(
        "select valor from siconfi_itens where demonstrativo='RREO' and exercicio=? and periodo=? and "
        "anexo='RREO-Anexo 14' and conta like ? and coluna='% Aplicado Até o Bimestre'",
        (exercicio, bimestre, conta_inicio + "%")).fetchone()
    return linha[0] if linha else None


def _medir_saude(lt: Leitor, ate: date, mapa: MapaLegal, fiscal: Fiscal) -> None:
    """Piso da saúde pelo demonstrativo homologado no SIOPS, com cálculo próprio da base.

    Aplicado: o valor aplicado em ASPS (linha XVI) — a despesa empenhada no 6º bimestre e a
    liquidada nos outros (nota 1 do próprio demonstrativo). Base: refeita pelo RREO Anexo 3 e
    pela DCA, e conferida com a linha III do SIOPS. A despesa total com saúde do SIOPS é
    conferida com a função Saúde do RREO Anexo 2 (com as intraorçamentárias).
    Antes do 6º bimestre o piso é acompanhamento: abaixo de 15% é alerta, não descumprimento.
    """
    d = ultimo_externo(lt, "SIOPS", ate)
    if d is None:
        fiscal.notas.append("Saúde (LC 141/2012): nenhum demonstrativo do SIOPS homologado no banco até a data.")
        fiscal.medidas.append(medir("PISO-SAUDE", None, None, mapa=mapa))
        return
    final = d.periodo == 6
    col = 0 if final else 1                     # empenhada (d) no fim do ano; liquidada (e) antes
    aplicado = d.valor(r"^\(=\) VALOR APLICADO EM ASPS", col)
    declarado = d.valor(r"^PERCENTUAL DA RECEITA DE IMPOSTOS", col)
    base_siops = d.valor(r"^TOTAL DAS RECEITAS RESULTANTES DE IMPOSTOS", 2)
    base, memoria_base = base_de_impostos(lt, d.exercicio, d.periodo)
    if base is not None:
        m = medir("PISO-SAUDE", aplicado, base, declarado=declarado, mapa=mapa)
    else:   # sem a base própria, o número é só o declarado: uma via, selo azul
        m = medir("PISO-SAUDE", aplicado, base_siops, mapa=mapa)
        fiscal.notas.append(f"Saúde: {memoria_base}; o piso fica com a base declarada no SIOPS, sem cálculo próprio.")
    if not final and m.situacao == "descumpre":
        m = replace(m, situacao="alerta")
    fiscal.medidas.append(m)
    ref = d.rotulo + (f", homologado em {d.homologado}" if d.homologado else "")
    rreo = next((p for p in lt.periodos("RREO") if p.exercicio == d.exercicio and p.periodo == d.periodo), None)
    fiscal.conferencias.append(ConferenciaDeVias(
        f"Receita da base da saúde ({d.periodo}º bimestre de {d.exercicio})",
        selar([Via("SIOPS, linha III", base_siops), Via("RREO Anexo 3 e DCA, cálculo próprio", base)]),
        f"{ref}; {rreo.rotulo if rreo else 'RREO ausente'}", "LC 141/2012, arts. 7º e 32"))
    total_siops = d.valor(r"^TOTAL DAS DESPESAS COM SAUDE \(XLVIII\)", 4)
    saude_rreo = _liquidado_com_intra(lt, d.exercicio, d.periodo, "Saúde")
    fiscal.conferencias.append(ConferenciaDeVias(
        f"Despesa liquidada com saúde ({d.periodo}º bimestre de {d.exercicio})",
        selar([Via("SIOPS, linha XLVIII", total_siops), Via("RREO Anexo 2, função Saúde", saude_rreo)]),
        f"{ref}; {rreo.rotulo if rreo else 'RREO ausente'}", "LC 141/2012, arts. 32 e 34"))
    fiscal.memoria["PISO-SAUDE"] = (
        f"Aplicado em ações e serviços públicos de saúde ({'empenhado, fim do exercício' if final else 'liquidado até o bimestre'}): "
        f"{_moeda(aplicado)}, sobre a receita de impostos e transferências refeita pelo RREO"
        f"{' e pela DCA' if final else ''}: {_moeda(base)} ({memoria_base}). O SIOPS declara a base de "
        f"{_moeda(base_siops)} e {declarado if declarado is not None else '?'}%."
        + ("" if final else " Antes do 6º bimestre é acompanhamento: o mínimo de 15% vale para o ano."))
    fiscal.fontes["PISO-SAUDE"] = f"{ref}; RREO Anexos 2 e 3" + (" e DCA Anexo I-C" if final else "")



# --- Educação e FUNDEB (CF, arts. 212 e 212-A; Lei 14.113/2020) -------------------------

def _medir_educacao(lt: Leitor, ate: date, mapa: MapaLegal, fiscal: Fiscal) -> None:
    """MDE, 70% do FUNDEB e saldo do FUNDEB pelo RREO Anexo 8 transmitido ao SIOPE.

    MDE: o total para fins de limite (linha 28) sobre a receita de impostos e transferências
    refeita pelo RREO Anexo 3 e pela DCA; o percentual declarado é a linha 29. FUNDEB 70%: a
    despesa com profissionais (linha 12) sobre as receitas do FUNDEB sem a complementação VAAR
    (linha 6 menos 6.4; Lei 14.113/2020, art. 26). Saldo: o recebido e não aplicado (linha 6
    menos a 11) sobre o recebido, só no 6º bimestre (art. 25, § 3º). Empenhado no 6º bimestre,
    liquidado antes (nota 5 do demonstrativo); antes do fim do ano o mínimo é acompanhamento.
    Segundas vias: a base (linha 3), a dedução para o FUNDEB (linha 4) e as transferências
    recebidas do FUNDEB, pelo RREO Anexo 3; a despesa com educação (linha 33) pelo RREO Anexo 2;
    os dois percentuais pelo RREO Anexo 14 (SICONFI).
    """
    d = ultimo_externo(lt, "SIOPE", ate)
    if d is None:
        fiscal.notas.append("Educação (CF, art. 212): nenhum RREO Anexo 8 do SIOPE no banco até a data.")
        for regra in ("PISO-EDUCACAO", "FUNDEB-PROFISSIONAIS", "FUNDEB-SALDO"):
            fiscal.medidas.append(medir(regra, None, None, mapa=mapa))
        return
    final = d.periodo == 6
    col = 0 if final else 1
    v = d.valor
    ref = d.rotulo
    rreo = next((p for p in lt.periodos("RREO") if p.exercicio == d.exercicio and p.periodo == d.periodo), None)
    ref_rreo = rreo.rotulo if rreo else "RREO ausente"

    # MDE
    aplicado = v(r"^28-", 0)
    exigido, _, declarado = (v(r"^29-", k) for k in (0, 1, 2))
    base_siope = v(r"^3-", 1)
    base, memoria_base = base_de_impostos(lt, d.exercicio, d.periodo, extraordinarias=True)
    if base is not None:
        m = medir("PISO-EDUCACAO", aplicado, base, declarado=declarado, mapa=mapa)
    else:
        m = medir("PISO-EDUCACAO", aplicado, base_siope, mapa=mapa)
        fiscal.notas.append(f"Educação: {memoria_base}; o piso fica com a base declarada no SIOPE, sem cálculo próprio.")
    if not final and m.situacao == "descumpre":
        m = replace(m, situacao="alerta")
    fiscal.medidas.append(m)
    partes = [v(r"^22-", 0), v(r"^23-", 0), v(r"^24-", 0), v(r"^25-", 0), v(r"^26-", 0), v(r"^27-", 0)]
    refeito = (partes[0] + partes[1] - sum(partes[2:])) if None not in partes else None
    fiscal.conferencias.append(ConferenciaDeVias(
        f"Total para fins de limite em MDE ({d.periodo}º bimestre de {d.exercicio})",
        selar([Via("SIOPE, linha 28", aplicado), Via("SIOPE, linhas 22 + 23 - 24 a 27", refeito)]),
        ref, "CF, art. 212; LDB, art. 72", entre_demonstrativos=False))
    deducao = None
    if rreo is not None and (serie := lt.serie_mensal(rreo, "Anexo 03", "DeducaoDeReceitaParaFormacaoDoFUNDEB")):
        deducao = sum(serie[: 2 * d.periodo])
    recebido_fundeb = None
    if rreo is not None and (serie := lt.serie_mensal(rreo, "Anexo 03", "RREO3TransferenciasDoFUNDEB")):
        recebido_fundeb = sum(serie[: 2 * d.periodo])
    principais = [v(rf"^{k}-", 1) for k in ("6.1.1", "6.2.1", "6.3.1", "6.4.1")]
    principal = sum(principais) if None not in principais else None
    rreo_mde = _rreo14(lt, d.exercicio, d.periodo, "Mínimo Anual de <18% / 25%>")
    for titulo, vias, norma in (
            (f"Receita da base da educação ({d.periodo}º bimestre de {d.exercicio})",
             [Via("SIOPE, linha 3", base_siope), Via("RREO Anexo 3 e DCA, cálculo próprio", base)],
             "CF, art. 212"),
            (f"Receita destinada ao FUNDEB ({d.periodo}º bimestre de {d.exercicio})",
             [Via("SIOPE, linha 4", v(r"^4-", 1)), Via("RREO Anexo 3, dedução para o FUNDEB", deducao)],
             "CF, art. 212-A, II"),
            (f"Transferências recebidas do FUNDEB ({d.periodo}º bimestre de {d.exercicio})",
             [Via("SIOPE, linhas 6.1.1 a 6.4.1", principal), Via("RREO Anexo 3, transferências do FUNDEB",
                                                                    recebido_fundeb)],
             "Lei 14.113/2020, art. 3º"),
            (f"Despesa liquidada com educação ({d.periodo}º bimestre de {d.exercicio})",
             [Via("SIOPE, linha 33", v(r"^33-", 2)),
              Via("RREO Anexo 2, função Educação", _liquidado_com_intra(lt, d.exercicio, d.periodo, "Educação"))],
             "LDB, art. 72"),
            (f"Percentual aplicado em MDE ({d.periodo}º bimestre de {d.exercicio})",
             [Via("SIOPE, linha 29", declarado), Via("RREO Anexo 14 (SICONFI)", rreo_mde)], "LRF, art. 52")):
        fiscal.conferencias.append(ConferenciaDeVias(titulo, selar(vias), f"{ref}; {ref_rreo}", norma))
    fiscal.memoria["PISO-EDUCACAO"] = (
        f"Total para fins de limite (linha 28, {'empenhado' if final else 'liquidado'}): {_moeda(aplicado)} = "
        f"MDE com impostos {_moeda(partes[0])} + destinado ao FUNDEB {_moeda(partes[1])} - deduções "
        f"{_moeda(sum(x or 0 for x in partes[2:]))}; sobre a receita de impostos e transferências refeita pelo RREO"
        f"{' e pela DCA' if final else ''}: {_moeda(base)} ({memoria_base}). O SIOPE declara a base de "
        f"{_moeda(base_siope)}, o exigido de {_moeda(exigido)} e {declarado if declarado is not None else '?'}%."
        + ("" if final else " Antes do 6º bimestre é acompanhamento: o mínimo de 25% vale para o ano."))
    fiscal.fontes["PISO-EDUCACAO"] = f"{ref} (RREO Anexo 8); {ref_rreo}, Anexos 2, 3 e 14" + (" e DCA" if final else "")

    # FUNDEB, 70% na remuneração dos profissionais
    receitas = v(r"^6-", 1)
    vaar = v(r"^6\.4-", 1)
    base70 = receitas - vaar if None not in (receitas, vaar) else None
    profissionais = v(r"^12-", col)
    declarado70 = v(r"^15-", 3)
    m70 = medir("FUNDEB-PROFISSIONAIS", profissionais, base70, declarado=declarado70, mapa=mapa)
    if not final and m70.situacao == "descumpre":
        m70 = replace(m70, situacao="alerta")
    fiscal.medidas.append(m70)
    fiscal.conferencias.append(ConferenciaDeVias(
        f"Percentual do FUNDEB nos profissionais ({d.periodo}º bimestre de {d.exercicio})",
        selar([Via("SIOPE, linha 15", declarado70),
               Via("RREO Anexo 14 (SICONFI)", _rreo14(lt, d.exercicio, d.periodo, "Mínimo Anual de 70% do FUNDEB"))]),
        f"{ref}; {ref_rreo}", "LRF, art. 52"))
    fiscal.memoria["FUNDEB-PROFISSIONAIS"] = (
        f"Despesa do FUNDEB com profissionais da educação básica (linha 12, {'empenhada' if final else 'liquidada'}): "
        f"{_moeda(profissionais)}, sobre as receitas do FUNDEB recebidas sem a complementação VAAR "
        f"({_moeda(receitas)} - {_moeda(vaar)} = {_moeda(base70)}). O SIOPE declara "
        f"{declarado70 if declarado70 is not None else '?'}% (linha 15)."
        + ("" if final else " Antes do 6º bimestre é acompanhamento: o mínimo de 70% vale para o ano."))
    fiscal.fontes["FUNDEB-PROFISSIONAIS"] = f"{ref} (RREO Anexo 8, linhas 6, 12 e 15); {ref_rreo}, Anexo 14"

    # FUNDEB, saldo para o exercício seguinte: só no fechamento do ano
    fim = d if final else None
    if fim is None:
        anos = [e for e in _externos_fechados(lt, "SIOPE", ate)]
        fim = anos[-1] if anos else None
    if fim is None:
        fiscal.medidas.append(medir("FUNDEB-SALDO", None, None, mapa=mapa))
        fiscal.notas.append("FUNDEB (art. 25, § 3º): nenhum exercício fechado no SIOPE até a data.")
        return
    recebido = fim.valor(r"^6-", 1)
    gasto = fim.valor(r"^11-", 0)
    nao_aplicado = recebido - gasto if None not in (recebido, gasto) else None
    declarado10 = fim.valor(r"^18-", 4)
    fiscal.medidas.append(medir("FUNDEB-SALDO", nao_aplicado, recebido, declarado=declarado10, mapa=mapa))
    fiscal.conferencias.append(ConferenciaDeVias(
        f"Receita do FUNDEB não aplicada em {fim.exercicio}",
        selar([Via("SIOPE, linha 18", fim.valor(r"^18-", 1)), Via("SIOPE, linhas 6 - 11", nao_aplicado)]),
        fim.rotulo, "Lei 14.113/2020, art. 25, § 3º", entre_demonstrativos=False))
    fiscal.memoria["FUNDEB-SALDO"] = (
        f"Recebido do FUNDEB em {fim.exercicio} (linha 6): {_moeda(recebido)}; empenhado com esse dinheiro "
        f"(linha 11): {_moeda(gasto)}; não aplicado: {_moeda(nao_aplicado)}. O SIOPE declara "
        f"{declarado10 if declarado10 is not None else '?'}% (linha 18); o máximo é 10%, a usar até abril.")
    fiscal.fontes["FUNDEB-SALDO"] = f"{fim.rotulo} (RREO Anexo 8, linhas 6, 11 e 18)"


def _externos_fechados(lt: Leitor, fonte: str, ate: date) -> list[Externo]:
    try:
        linhas = lt.con.execute(
            "select exercicio, periodo, homologado from externos_periodos where fonte=? and periodo=6 and "
            "situacao='homologado' order by exercicio", (fonte,)).fetchall()
    except sqlite3.OperationalError:
        return []
    return [x for x in (Externo(lt, fonte, e, p, h) for e, p, h in linhas) if x.termina <= ate]


def liquidado_na_funcao(funcao_nome: str, ate: date, *, banco: Path | str = BANCO
                        ) -> tuple[float | None, Periodo | None]:
    """Despesa liquidada até o bimestre na função (RREO Anexo 2), do último RREO até ``ate``."""
    lt = Leitor(banco)
    try:
        per = lt.ultimo("RREO", ate)
        if per is None:
            return None, None
        linhas = [v for (v,) in lt.con.execute(
            "select valor from siconfi_itens where demonstrativo='RREO' and exercicio=? and periodo=? and "
            "anexo='RREO-Anexo 02' and conta=? and coluna like 'DESPESAS LIQUIDADAS ATÉ O BIMESTRE%' "
            "and rotulo like 'Total das Despesas Exceto Intra%'",
            (per.exercicio, per.periodo, funcao_nome))]
        # Só as despesas exceto intraorçamentárias: a intraorçamentária é dinheiro que circula
        # dentro do próprio Município e contaria duas vezes.
        return (linhas[0] if len(linhas) == 1 else None), per
    finally:
        lt.fechar()
