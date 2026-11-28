"""O rio do Município inteiro, pelo RREO e pela Matriz de Saldos Contábeis guardados no banco histórico.

Cada afluente é uma espécie de receita (IPTU, ISS, FPM, cota do ICMS, FUNDEB...) somada mês a mês
no exercício, pelas doze colunas mensais do RREO Anexo 3; as receitas de capital vêm do Anexo 1.
Quando a Matriz de Saldos Contábeis (MSC) cobre os mesmos meses, cada espécie se abre pelas fontes
de recursos em que o Município a registrou: é a fonte que diz se a água é vinculada ou livre. O
FUNDEB que o Município entrega ao fundo sai do rio como sangria: o rio bruto menos a sangria é a
receita realizada.

O rio é conferido em três pontos, sem pessoa no meio:

* **Rio contra o RREO (1%)**: a soma dos afluentes, menos a sangria do FUNDEB, contra a receita
  realizada que o Anexo 1 declara; e o mesmo nos grupos (impostos e taxas, transferências).
  Mesmo relatório, quadros diferentes: confere, mas não é outra via.
* **RREO contra a matriz**: cada espécie, a receita realizada e a despesa empenhada, liquidada e
  paga contra a MSC, que o Município entrega todo mês em separado e o Tesouro homologa à parte.
* **A origem**: o que a União diz ter transferido (Portal da Transparência, SIAFI) contra o que o
  Município registrou como recebido (MSC), transferência a transferência e mês a mês. Quando falta
  dinheiro do lado do Município num mês, procura-se o mesmo valor em outra natureza ou fonte do
  mesmo mês: é o caso do recurso que entrou, mas fora da fonte que o vincula.

E dois testes do leito:

* **Realizado contra o previsto**: cada espécie contra a previsão atualizada do ano, no ritmo do ano
  anterior (o IPTU e o IPVA se concentram no começo do ano; o ritmo do ano anterior evita o falso
  alarme da régua proporcional).
* **Desvio de finalidade**: a despesa empenhada por fonte e função (MSC). Água vinculada empenhada
  numa função que não é o seu leito é indício de desvio (LRF, art. 8º, parágrafo único); dinheiro da
  alienação de bens em despesa corrente também (LRF, art. 44).

As margens do rio (previsto e não empenhado, empenhado e não liquidado, liquidado e não pago) saem
do RREO Anexo 1, colunas da despesa, conferidas com a MSC.
"""

from __future__ import annotations

import calendar
import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field
from datetime import date

from ..nucleo.indicios import Familia, Ficha, emitir
from ..nucleo.provas import Nivel
from ..nucleo.selos import Certificacao, Selo, Via, selar
from . import matriz as mz
from .afluentes import Afluente, Margens, Rio
from .fontes import Esfera, classificar, desvio_de_finalidade


@dataclass(frozen=True)
class Especie:
    cod_conta: str        # linha do RREO Anexo 3 (correntes) ou do Anexo 1 (capital)
    nome: str
    esfera: Esfera
    fonte: str | None     # fonte de destinação, quando a espécie a define sozinha (sem a MSC)
    natureza: mz.Natureza  # a mesma espécie na matriz, pela natureza da receita
    anexo: str = "Anexo 03"


_N = mz.Natureza
# As espécies que somam a receita corrente do Anexo 3 (sem sobreposição: os quatro impostos e o
# resto dos tributos, depois cada transferência). A soma fecha com a linha "RECEITAS CORRENTES (I)".
# A natureza de cada uma na MSC foi calibrada no banco real (2024 a 2026, espécie a espécie, ao centavo).
CORRENTES = (
    Especie("IPTULiquidoExcetoTransferenciasEFUNDEB", "IPTU", Esfera.MUNICIPAL, "1500", _N(("111250",))),
    Especie("ISSLiquidoExcetoTransferenciasEFUNDEB", "ISS", Esfera.MUNICIPAL, "1500", _N(("111451",))),
    Especie("ITBILiquidoExcetoTransferenciasEFUNDEB", "ITBI", Esfera.MUNICIPAL, "1500", _N(("111253",))),
    Especie("IRRFLiquidoExcetoTransferenciasEFUNDEB", "IRRF retido na fonte", Esfera.MUNICIPAL, "1500",
            _N(("11130",))),
    Especie("OutrasReceitasTributarias", "Taxas e outros tributos", Esfera.MUNICIPAL, None,
            _N(("11",), ("111250", "111451", "111253", "11130"))),
    Especie("RREO3ReceitaDeContribuicoes", "Contribuições (iluminação pública e previdência)",
            Esfera.MUNICIPAL, None, _N(("12",))),
    Especie("RREO3ReceitaPatrimonial", "Receita patrimonial", Esfera.MUNICIPAL, None, _N(("13",))),
    Especie("RREO3ReceitaDeServicos", "Receita de serviços", Esfera.MUNICIPAL, None, _N(("16",))),
    Especie("RREO3CotaParteDoFPM", "FPM", Esfera.FEDERAL, "1500", _N(("171151",))),
    Especie("RREO3CotaParteDoITR", "Cota-parte do ITR", Esfera.FEDERAL, "1500", _N(("171152",))),
    Especie("RREO3CotaParteDoICMS", "Cota-parte do ICMS", Esfera.ESTADUAL, "1500", _N(("172150",))),
    Especie("RREO3CotaParteDoIPVA", "Cota-parte do IPVA", Esfera.ESTADUAL, "1500", _N(("172151",))),
    Especie("RREO3TransferenciasDaLC611989", "IPI-exportação (LC 61/1989)", Esfera.ESTADUAL, "1500",
            _N(("172152",))),
    Especie("RREO3TransferenciasDoFUNDEB", "FUNDEB", Esfera.MISTA, "1540", _N(("1751", "17155"))),
    Especie("RREO3OutrasTransferenciasCorrentes", "Outras transferências correntes", Esfera.MISTA, None,
            _N(("17",), ("171151", "171152", "172150", "172151", "172152", "1751", "17155"))),
    Especie("RREO3OutrasReceitasCorrentes", "Outras receitas correntes", Esfera.MUNICIPAL, None,
            _N(("19", "14", "15"))),
)
TOTAL_CORRENTES = "ReceitasCorrentesLiquidasExcetoTransferenciasEFUNDEB"
SANGRIA_FUNDEB = "DeducaoDeReceitaParaFormacaoDoFUNDEB"

CAPITAL = (
    Especie("ReceitasDeOperacoesDeCredito", "Operações de crédito", Esfera.MUNICIPAL, None, _N(("21",)),
            "Anexo 01"),
    Especie("AlienacaoDeBens", "Alienação de bens", Esfera.MUNICIPAL, None, _N(("22",)), "Anexo 01"),
    Especie("TransferenciasDeCapitalDaUniaoEDeSuasEntidades", "Transferências de capital da União",
            Esfera.FEDERAL, None, _N(("241",)), "Anexo 01"),
    Especie("TransferenciasDeCapitalDosEstadosEDoDistritoFederalEDeSuasEntidades",
            "Transferências de capital do Estado", Esfera.ESTADUAL, None, _N(("242",)), "Anexo 01"),
)
TOTAL_CAPITAL = "ReceitasDeCapital"
OUTRAS_CAPITAL = _N(("2",), ("21", "22", "241", "242"))

COL_REALIZADO = r"Até o Bimestre \(c\)"
COL_PREVISTO = r"PREVISÃO ATUALIZADA \(a\)"
TOLERANCIA_CONTABIL = 1e-6  # RREO e matriz saem da mesma contabilidade: só o arredondamento separa
TOLERANCIA_RITMO = 0.10   # abaixo de 90% do ritmo do ano anterior: alerta de frustração da receita
MATERIALIDADE_RITMO = 0.0005  # a falta só vira alerta se passar de 0,05% da receita prevista no ano
PISO_AFLUENTE = 1_000.0   # fonte com menos que isto entra no saldo da espécie
PISO_DESVIO = 1_000.0     # empenho fora do leito abaixo disto não vira ficha (arredondamentos e estornos)


# --- As transferências da União conferidas na origem ----------------------------------------------
@dataclass(frozen=True)
class Origem:
    """Uma transferência da União: como o SIAFI a mostra e como o Município deve registrá-la."""

    nome: str
    tipo: str                         # tipo de transferência no Portal (o mês só conta se o Portal o traz)
    natureza: mz.Natureza             # onde o Município deve registrar o que recebeu
    norma: str
    acoes: tuple[str, ...] = ()       # ações orçamentárias da União (vazio: todas do órgão)
    orgao: str | None = None          # órgão concedente no Portal
    fontes: tuple[str, ...] = ()      # destinações em que deve entrar (vazio: qualquer)
    sem_acoes: tuple[str, ...] = ()   # ações do órgão que têm conferência própria
    retencao_fundeb: bool = False     # o SIAFI traz o líquido da retenção de 20% ao FUNDEB
    adicional: mz.Natureza | None = None  # parcela que o Portal às vezes soma à ação (o 1% do FPM)


_TRANSF = ("17", "24")
ORIGENS = (
    Origem("FPM", "Constitucionais e Royalties", _N(("1711511",)),
           "CF, art. 159, I, b; Lei 14.113/2020, art. 3º", acoes=("0045",), retencao_fundeb=True,
           adicional=_N(("1711512",))),
    Origem("Cota-parte do ITR", "Constitucionais e Royalties", _N(("171152",)),
           "CF, art. 158, II; Lei 14.113/2020, art. 3º", acoes=("006M",), retencao_fundeb=True),
    Origem("Royalties do petróleo e da mineração", "Constitucionais e Royalties", _N(("17125",)),
           "Lei 7.990/1989; Lei 9.478/1997, art. 49; Lei 8.001/1990, art. 2º", acoes=("0A53", "0547")),
    Origem("Complementação da União ao FUNDEB", "Constitucionais e Royalties", _N(("17155",)),
           "CF, art. 212-A, V; Lei 14.113/2020, art. 5º", acoes=("00SB",)),
    Origem("SUS fundo a fundo", "Legais, Voluntárias e Específicas", _N(_TRANSF),
           "LC 141/2012, arts. 17 e 18", orgao="Ministério da Saúde%", fontes=("600", "601", "604", "605")),
    Origem("FNDE (salário-educação, alimentação e transporte escolar)", "Legais, Voluntárias e Específicas",
           _N(_TRANSF), "CF, art. 212, § 6º; Lei 11.947/2009; Lei 10.880/2004",
           orgao="Fundo Nacional de Desenvolvimento da Educação", fontes=("550", "551", "552", "553", "569"),
           sem_acoes=("00SB", "0C33")),
    Origem("FNAS (assistência social)", "Legais, Voluntárias e Específicas", _N(_TRANSF),
           "Lei 8.742/1993, art. 30; Decreto 7.788/2012", orgao="Fundo Nacional de Assistência Social",
           fontes=("660",)),
)


class Tipo:
    MESMO_RELATORIO = "mesmo_relatorio"            # quadros do mesmo RREO: confere, não é outra via
    ENTRE_DEMONSTRATIVOS = "entre_demonstrativos"  # RREO contra MSC: duas entregas do Município
    ENTRE_FONTES = "entre_fontes"                  # União (SIAFI) contra Município (MSC)


@dataclass
class Ritmo:
    """Uma espécie contra a previsão do ano, no ritmo do ano anterior."""

    especie: str
    realizado: float
    previsto: float
    esperado: float | None       # o previsto vezes a fração que o ano anterior tinha realizado
    fracao_anterior: float | None
    situacao: str                # "cumpre", "alerta", "abaixo_imaterial" ou "sem_dado"

    def como_dict(self) -> dict:
        return {"especie": self.especie, "realizado": self.realizado, "previsto": self.previsto,
                "esperado": self.esperado, "fracao_anterior": self.fracao_anterior,
                "situacao": self.situacao}


@dataclass
class Conferencia:
    titulo: str
    certificacao: Certificacao
    referencia: str
    tipo: str
    detalhe: list[str] = field(default_factory=list)
    norma: str = ""

    @property
    def selo(self) -> Selo | None:
        return self.certificacao.selo

    @property
    def entre_fontes(self) -> bool:
        return self.tipo == Tipo.ENTRE_FONTES

    def como_dict(self) -> dict:
        c = self.certificacao
        return {"titulo": self.titulo, "referencia": self.referencia, "tipo": self.tipo,
                "selo": c.selo.value if c.selo else None, "divergencia": c.divergencia,
                "vias": [{"fonte": v.fonte, "valor": v.valor} for v in c.vias], "detalhe": self.detalhe}


@dataclass
class Desvio:
    """Recurso vinculado empenhado fora da sua finalidade."""

    fonte: str                        # destinação, três dígitos
    nome_fonte: str
    funcao: str
    valor: float
    norma: str
    motivo: str                       # "leito" (fora da finalidade da lei) ou "alienacao"
    naturezas: list[tuple[str, str, float]] = field(default_factory=list)   # (subfunção, natureza, valor)

    def como_dict(self) -> dict:
        return {"fonte": self.fonte, "nome_fonte": self.nome_fonte, "funcao": self.funcao,
                "valor": self.valor, "norma": self.norma, "motivo": self.motivo,
                "naturezas": [{"subfuncao": s, "natureza": n, "valor": v} for s, n, v in self.naturezas]}


@dataclass
class RioMunicipal:
    exercicio: int
    bimestre: int
    rio: Rio
    sangria_fundeb: float
    realizado_declarado: float | None          # Anexo 1, receitas (exceto intra) até o bimestre
    previsto_ano: float | None
    margens: Margens | None = None
    margens_no_ano: bool = False               # True no 6º bimestre: o previsto não empenhado é margem
    conferencias: list[Conferencia] = field(default_factory=list)
    ritmos: list[Ritmo] = field(default_factory=list)
    desvios: list[Desvio] = field(default_factory=list)
    meses_desvio: list[str] = field(default_factory=list)
    fontes_sem_catalogo: dict[str, float] = field(default_factory=dict)   # destinação -> empenhado
    meses: dict[str, dict[str, float]] = field(default_factory=dict)      # espécie -> mês -> valor
    notas: list[str] = field(default_factory=list)

    @property
    def rotulo(self) -> str:
        return f"RREO do {self.bimestre}º bimestre de {self.exercicio}"

    @property
    def liquido(self) -> float:
        return self.rio.total() - self.sangria_fundeb

    def certificacoes(self) -> list[Certificacao]:
        """Só as de duas entregas ou fontes distintas contam para a coerência."""
        return [c.certificacao for c in self.conferencias
                if c.tipo != Tipo.MESMO_RELATORIO and len(c.certificacao.vias) >= 2]

    def fichas(self, competencia: str) -> list[Ficha]:
        out: list[Ficha] = []
        for c in self.conferencias:
            if not c.certificacao.divergencia:
                continue
            vias = "; ".join(f"{v.fonte}: {_moeda(v.valor)}" for v in c.certificacao.vias)
            detalhe = (" " + " ".join(c.detalhe[:8])) if c.detalhe else ""
            if c.tipo == Tipo.ENTRE_FONTES:
                siafi, registrado = (v.valor for v in c.certificacao.vias[:2])
                faltou = (siafi or 0.0) > (registrado or 0.0)
                out.append(emitir(
                    codigo=f"RIO-ORIGEM-{_slug(c.titulo)}-{competencia}", familia=Familia.RIO,
                    titulo=(f"{c.titulo}: a União transferiu mais do que o Município registrou na fonte que "
                            "vincula o recurso" if faltou else
                            f"{c.titulo}: o Município registrou mais do que o SIAFI mostra como transferido"),
                    gravidade="alta" if faltou else "media",
                    como_deveria="A receita de transferência registrada pelo Município, na natureza e na fonte "
                                 "que a vinculam, deve ser a que o SIAFI registra como transferida no mês.",
                    norma=f"{c.norma}; LC 101/2000, arts. 8º, parágrafo único, e 48-A, II; Lei 4.320/1964, art. 35, I",
                    como_esta=f"{c.referencia}. {vias}.{detalhe}", niveis=[Nivel.A, Nivel.B],
                    providencia="Pedir a conciliação da receita de transferências com os extratos da conta "
                                "do fundo e a reclassificação da receita, se for o caso.",
                    competencia=competencia))
            elif c.tipo == Tipo.ENTRE_DEMONSTRATIVOS:
                out.append(emitir(
                    codigo=f"RIO-MSC-{_slug(c.titulo)}-{competencia}", familia=Familia.RIO,
                    titulo=f"{c.titulo}: o RREO e a matriz de saldos contábeis divergem",
                    gravidade="media",
                    como_deveria="O RREO e a matriz de saldos contábeis saem da mesma contabilidade e devem "
                                 "trazer os mesmos valores para os mesmos meses.",
                    norma="LC 101/2000, arts. 48, § 2º, e 52; Portaria STN 642/2019 (MSC)",
                    como_esta=f"{c.referencia}. {vias}.{detalhe}", niveis=[Nivel.B],
                    providencia="Pedir a conciliação entre o RREO e a matriz e a retificação no SICONFI.",
                    competencia=competencia))
            else:
                out.append(emitir(
                    codigo=f"RIO-RREO-{_slug(c.titulo)}-{competencia}", familia=Familia.RIO,
                    titulo=f"{c.titulo}: os quadros do RREO não fecham",
                    gravidade="media",
                    como_deveria="A receita somada espécie a espécie (Anexo 3 e capital do Anexo 1) deve "
                                 "ser a receita realizada que o Anexo 1 declara.",
                    norma="LC 101/2000, art. 52, I, a; Portaria STN do MDF",
                    como_esta=f"{c.referencia}. {vias}.", niveis=[Nivel.B],
                    providencia="Pedir a retificação do RREO no SICONFI.", competencia=competencia))
        for r in self.ritmos:
            if r.situacao != "alerta":
                continue
            ano_todo = self.bimestre == 6
            out.append(emitir(
                codigo=f"RIO-RECEITA-{_slug(r.especie)}-{competencia}", familia=Familia.ORC,
                titulo=(f"{r.especie}: realizada abaixo da previsão do ano" if ano_todo else
                        f"{r.especie}: arrecadação abaixo do ritmo do ano anterior"),
                gravidade="media",
                como_deveria=("A receita prevista deve se realizar; se não se realizar, o Poder limita o "
                              "empenho no bimestre seguinte." if not ano_todo else
                              "A previsão da receita deve ser realista e a frustração, compensada pela "
                              "limitação de empenho."),
                norma="LC 101/2000, arts. 9º e 12",
                como_esta=(f"{self.rotulo}: realizado {_moeda(r.realizado)} contra previsão atualizada de "
                           f"{_moeda(r.previsto)}"
                           + (f"; no ritmo do ano anterior ({r.fracao_anterior:.1%} da receita do ano até este "
                              f"bimestre) esperavam-se {_moeda(r.esperado)}"
                              if r.esperado is not None and r.fracao_anterior is not None and not ano_todo else "")
                           + "."),
                niveis=[Nivel.B],
                providencia="Verificar no RREO e no Diário Oficial se houve decreto de limitação de empenho.",
                competencia=competencia))
        periodo = _periodo(self.meses_desvio)
        for d in self.desvios:
            linhas = "; ".join(f"subfunção {s}, natureza {n}: {_moeda(v)}" for s, n, v in d.naturezas[:5])
            if d.motivo == "alienacao":
                titulo = f"Dinheiro da alienação de bens em despesa corrente ({_moeda(d.valor)})"
                como_deveria = ("A receita da alienação de bens só financia despesa de capital, salvo a "
                                "previdência dos servidores.")
                norma = d.norma
            else:
                titulo = f"{d.nome_fonte}: empenhada fora da sua finalidade, na função {d.funcao} ({_moeda(d.valor)})"
                como_deveria = ("O recurso vinculado só se aplica no objeto da vinculação, ainda que em "
                                "exercício diverso do ingresso.")
                norma = f"LC 101/2000, art. 8º, parágrafo único; {d.norma}"
            out.append(emitir(
                codigo=f"VIN-DESVIO-{d.fonte}-{d.funcao}-{competencia}", familia=Familia.VIN,
                titulo=titulo, gravidade="alta" if d.valor >= 100_000 else "media",
                como_deveria=como_deveria, norma=norma,
                como_esta=(f"Matriz de saldos contábeis, empenhos de {periodo}: destinação {d.fonte} "
                           f"({d.nome_fonte}) na função {d.funcao}, {_moeda(d.valor)}. Maiores itens: {linhas}."),
                niveis=[Nivel.B],
                providencia="Pedir as notas de empenho e o enquadramento da despesa na finalidade da fonte; "
                            "se não houver, a recomposição da conta vinculada.",
                competencia=competencia))
        return out

    def como_dict(self) -> dict:
        return {
            "rreo": self.rotulo,
            "total_bruto": self.rio.total(),
            "sangria_fundeb": self.sangria_fundeb,
            "liquido": self.liquido,
            "realizado_declarado": self.realizado_declarado,
            "previsto_ano": self.previsto_ano,
            "por_esfera": {e.value: v for e, v in self.rio.por_esfera().items()},
            "vinculada_e_livre": self.rio.vinculada_e_livre(),
            "afluentes": [{"nome": a.nome, "esfera": a.esfera.value, "valor": a.valor, "fonte": a.fonte,
                           "selo": a.selo.value if a.selo else None, "origem": a.origem}
                          for a in self.rio.afluentes],
            "margens": None if self.margens is None else {
                **self.margens.como_dict(), "previsto": self.margens.previsto,
                "empenhado": self.margens.empenhado, "liquidado": self.margens.liquidado,
                "pago": self.margens.pago, "fim_do_ano": self.margens_no_ano},
            "conferencias": [c.como_dict() for c in self.conferencias],
            "ritmos": [r.como_dict() for r in self.ritmos],
            "desvios": [d.como_dict() for d in self.desvios],
            "meses_desvio": self.meses_desvio,
            "fontes_sem_catalogo": self.fontes_sem_catalogo,
            "notas": self.notas,
        }


def _moeda(v: float | None) -> str:
    if v is None:
        return "não informado"
    s = f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-R$ " if v < 0 else "R$ ") + s


def _slug(t: str) -> str:
    sem = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]+", "-", sem.upper()).strip("-")[:30].rstrip("-")


_MESES = ("jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez")


def _mes(m: str) -> str:
    return f"{_MESES[int(m[5:7]) - 1]}/{m[:4]}"


def _periodo(meses: list[str]) -> str:
    if not meses:
        return "sem meses"
    return _mes(meses[0]) if len(meses) == 1 else f"{_mes(meses[0])} a {_mes(meses[-1])}"


def meses_do_exercicio(lt, per, cod_conta: str) -> dict[str, float] | None:
    """Os meses do exercício até o fim do bimestre, pelas colunas mensais do Anexo 3.

    O Anexo 3 traz os doze meses que terminam no bimestre (<MR> é o último); do exercício são os
    últimos ``2 × bimestre``.
    """
    serie = lt.serie_mensal(per, "Anexo 03", cod_conta)   # <MR>, <MR-1>, ... <MR-11>
    if serie is None:
        return None
    ultimo = 2 * per.periodo
    return {f"{per.exercicio}-{m:02d}": serie[ultimo - m] for m in range(1, ultimo + 1)}


def _realizado_ate(lt, exercicio: int, bimestre: int, especie: Especie) -> float | None:
    per = next((p for p in lt.periodos("RREO") if p.exercicio == exercicio and p.periodo == bimestre), None)
    if per is None:
        return None
    if especie.anexo == "Anexo 01":
        return lt.valor(per, "Anexo 01", especie.cod_conta, COL_REALIZADO)
    meses = meses_do_exercicio(lt, per, especie.cod_conta)
    return sum(meses.values()) if meses else None


def _previsto(lt, per, especie: Especie) -> float | None:
    if especie.anexo == "Anexo 01":
        return lt.valor(per, "Anexo 01", especie.cod_conta, COL_PREVISTO)
    return lt.valor(per, "Anexo 03", especie.cod_conta, rf"PREVISÃO ATUALIZADA {per.exercicio}")


def _ritmo(lt, per, especie: Especie, realizado: float) -> Ritmo:
    previsto = _previsto(lt, per, especie)
    if not previsto:
        return Ritmo(especie.nome, realizado, previsto or 0.0, None, None, "sem_dado")
    if per.periodo == 6:
        situacao = "alerta" if realizado < previsto * (1 - TOLERANCIA_RITMO) else "cumpre"
        return Ritmo(especie.nome, realizado, previsto, previsto, 1.0, situacao)
    ate_ant = _realizado_ate(lt, per.exercicio - 1, per.periodo, especie)
    ano_ant = _realizado_ate(lt, per.exercicio - 1, 6, especie)
    if not ate_ant or not ano_ant:
        return Ritmo(especie.nome, realizado, previsto, None, None, "sem_dado")
    fracao = ate_ant / ano_ant
    esperado = previsto * fracao
    situacao = "alerta" if realizado < esperado * (1 - TOLERANCIA_RITMO) else "cumpre"
    return Ritmo(especie.nome, realizado, previsto, esperado, fracao, situacao)


def _esfera(fonte: str, padrao: Esfera) -> Esfera:
    if padrao is not Esfera.MISTA:
        return padrao
    f = classificar(fonte)
    return f.destinacao.esfera if f.destinacao is not None else padrao


def _abrir_por_fonte(con: sqlite3.Connection, e: Especie, valor: float, meses: list[str],
                     selo: Selo | None, origem: str) -> list[Afluente]:
    """A espécie aberta pelas fontes em que o Município a registrou na MSC.

    Só abre quando a matriz soma a espécie inteira (até 1%): fonte de outro valor não se inventa.
    Exercício corrente e anteriores da mesma destinação ficam juntos. A esfera é a da espécie (de
    onde vem o dinheiro); só as espécies mistas tomam a esfera da destinação.
    """
    por_fonte = mz.receita_por_fonte(con, e.natureza, meses)
    if not por_fonte or abs(sum(por_fonte.values()) - valor) > max(1.0, 0.01 * abs(valor)):
        return [Afluente(e.nome, e.esfera, valor, e.fonte, selo, origem)]
    grupos: dict[str, float] = {}
    for f, v in por_fonte.items():
        chave = ("1" + f[1:4]) if len(f) >= 4 and classificar(f).conhecida else f
        grupos[chave] = grupos.get(chave, 0.0) + v
    positivos = sorted(((f, v) for f, v in grupos.items() if v >= PISO_AFLUENTE), key=lambda x: -x[1])
    if positivos and positivos[0][1] >= 0.99 * valor:
        f = positivos[0][0]
        return [Afluente(e.nome, _esfera(f, e.esfera), valor, f, selo, f"{origem}; fonte {f} na matriz")]
    out = []
    for f, v in positivos:
        fonte = classificar(f)
        nome = f"{e.nome}: {fonte.nome}" if fonte.conhecida else f"{e.nome}: fonte {f}"
        out.append(Afluente(nome, _esfera(f, e.esfera), v, f, selo, f"{origem}; fonte {f} na matriz"))
    resto = valor - sum(v for _, v in positivos)
    if abs(resto) >= 0.005:
        out.append(Afluente(f"{e.nome}: estornos e fontes menores", e.esfera, resto, None, selo,
                            f"{origem}; saldo das fontes abaixo de R$ 1.000 e das negativas"))
    return out


def montar(lt, per, *, ate: date | None = None) -> RioMunicipal | None:
    """O rio do exercício até o bimestre ``per`` (um RREO entregue); a origem e o leito, até ``ate``."""
    if per is None or per.demonstrativo != "RREO":
        return None
    con = lt.con
    entregues = mz.meses_entregues(con)
    janela = [f"{per.exercicio}-{m:02d}" for m in range(1, 2 * per.periodo + 1)]
    msc_janela = [m for m in janela if m in entregues]
    msc_cobre = len(msc_janela) == len(janela)

    rio = Rio(f"{per.exercicio}-{2 * per.periodo:02d}")
    meses: dict[str, dict[str, float]] = {}
    ritmos: list[Ritmo] = []
    notas: list[str] = []
    faltam: list[str] = []
    conf_msc: list[Conferencia] = []
    ref_msc = (f"{_periodo(msc_janela)}: RREO Anexo 3 mês a mês contra a matriz de saldos contábeis "
               "(receita realizada menos as deduções que não são do FUNDEB)")
    especies: list[tuple[Especie, float, str]] = []
    for e in CORRENTES:
        m = meses_do_exercicio(lt, per, e.cod_conta)
        if m is None:
            faltam.append(e.nome)
            continue
        meses[e.nome] = m
        especies.append((e, sum(m.values()), f"RREO Anexo 3, {per.exercicio}, meses 1 a {2 * per.periodo}"))
        ritmos.append(_ritmo(lt, per, e, sum(m.values())))
        if msc_janela:
            msc = mz.receita(con, e.natureza, msc_janela)
            detalhe = [f"{_mes(k)}: RREO {_moeda(m[k])}, matriz {_moeda(msc.get(k, 0.0))}."
                       for k in msc_janela if abs(m[k] - msc.get(k, 0.0)) >= 1.0]
            conf_msc.append(Conferencia(e.nome, selar([
                Via("RREO Anexo 3", sum(m[k] for k in msc_janela)),
                Via("Matriz de saldos contábeis", sum(msc.values()))], tolerancia=TOLERANCIA_CONTABIL),
                ref_msc, Tipo.ENTRE_DEMONSTRATIVOS, detalhe))
    capital_soma = 0.0
    for e in CAPITAL:
        valor = lt.valor(per, "Anexo 01", e.cod_conta, COL_REALIZADO) or 0.0
        capital_soma += valor
        if valor:
            especies.append((e, valor, f"RREO Anexo 1, até o {per.periodo}º bimestre"))
    capital_total = lt.valor(per, "Anexo 01", TOTAL_CAPITAL, COL_REALIZADO)
    if capital_total is not None and capital_total - capital_soma > 0.005:
        especies.append((Especie("", "Outras receitas de capital", Esfera.MUNICIPAL, None, OUTRAS_CAPITAL,
                                 "Anexo 01"), capital_total - capital_soma,
                         f"RREO Anexo 1, até o {per.periodo}º bimestre"))
    if msc_cobre and capital_total is not None:
        conf_msc.append(Conferencia("Receitas de capital", selar([
            Via("RREO Anexo 1", capital_total),
            Via("Matriz de saldos contábeis", sum(mz.receita(con, _N(("2",)), msc_janela).values()))],
            tolerancia=TOLERANCIA_CONTABIL),
            f"{_periodo(msc_janela)}: RREO Anexo 1 contra a matriz", Tipo.ENTRE_DEMONSTRATIVOS))
    if faltam:
        notas.append("O Anexo 3 não traz os doze meses de: " + ", ".join(faltam) + ".")

    # Os afluentes: cada espécie aberta pelas fontes da matriz, com o selo da sua conferência.
    selos = {c.titulo: c.selo for c in conf_msc}
    for e, valor, origem in especies:
        if not msc_cobre:
            rio.afluentes.append(Afluente(e.nome, e.esfera, valor, e.fonte, None, origem))
            continue
        selo = selos.get("Receitas de capital") if e.anexo == "Anexo 01" else selos.get(e.nome)
        rio.afluentes.extend(_abrir_por_fonte(con, e, valor, janela, selo, origem))
    if msc_janela and not msc_cobre:
        notas.append(f"A matriz de saldos contábeis cobre {len(msc_janela)} dos {len(janela)} meses do "
                     "exercício: a receita fica com a fonte padrão de cada espécie, sem abrir pelas fontes "
                     "registradas, e cada espécie se confere só nos meses que a matriz traz.")
    sangria = sum((meses_do_exercicio(lt, per, SANGRIA_FUNDEB) or {}).values())

    realizado = lt.valor(per, "Anexo 01", "ReceitasExcetoIntraOrcamentarias", COL_REALIZADO)
    previsto = lt.valor(per, "Anexo 01", "ReceitasExcetoIntraOrcamentarias", COL_PREVISTO)
    for r in ritmos:
        falta = (r.esperado or 0.0) - r.realizado
        if r.situacao == "alerta" and previsto and falta < MATERIALIDADE_RITMO * previsto:
            r.situacao = "abaixo_imaterial"
    rm = RioMunicipal(per.exercicio, per.periodo, rio, sangria, realizado, previsto, meses=meses,
                      ritmos=[r for r in ritmos if r.previsto], notas=notas)

    # --- A soma por espécie contra o RREO: a receita realizada do Anexo 1 ------------------------
    ref = f"{rm.rotulo}: Anexo 3 mês a mês contra o Anexo 1 acumulado"
    if not faltam:
        rm.conferencias.append(Conferencia(
            "Receita realizada no exercício", selar([
                Via("soma das espécies menos o FUNDEB entregue", rio.total() - sangria),
                Via("RREO Anexo 1, receitas até o bimestre", realizado)]), ref, Tipo.MESMO_RELATORIO))
        tributos = sum(sum(meses[n].values()) for n in
                       ("IPTU", "ISS", "ITBI", "IRRF retido na fonte", "Taxas e outros tributos"))
        rm.conferencias.append(Conferencia(
            "Impostos, taxas e contribuições de melhoria", selar([
                Via("soma das espécies: IPTU, ISS, ITBI, IRRF e taxas", tributos),
                Via("RREO Anexo 1, até o bimestre", lt.valor(per, "Anexo 01", "ReceitaTributaria", COL_REALIZADO))]),
            ref, Tipo.MESMO_RELATORIO))
        transf = sum(sum(meses[e.nome].values()) for e in CORRENTES
                     if e.cod_conta.startswith(("RREO3CotaParte", "RREO3Transferencias", "RREO3OutrasTransferencias")))
        rm.conferencias.append(Conferencia(
            "Transferências correntes", selar([
                Via("soma das transferências menos o FUNDEB entregue", transf - sangria),
                Via("RREO Anexo 1, até o bimestre", lt.valor(per, "Anexo 01", "TransferenciasCorrentes", COL_REALIZADO))]),
            ref, Tipo.MESMO_RELATORIO))

    # --- RREO contra a matriz -------------------------------------------------------------------
    rm.conferencias.extend(conf_msc)
    if msc_cobre:
        rm.conferencias.append(Conferencia("Receita realizada (Anexo 1 e matriz)", selar([
            Via("RREO Anexo 1", realizado), Via("Matriz de saldos contábeis", mz.receita_realizada(con, janela))],
            tolerancia=TOLERANCIA_CONTABIL),
            f"{rm.rotulo}: receitas exceto intraorçamentárias, deduções incluídas", Tipo.ENTRE_DEMONSTRATIVOS))

    # --- As margens: a despesa do Anexo 1, conferida com a matriz ------------------------------------
    dot = lt.valor(per, "Anexo 01", "DespesasExcetoIntraOrcamentarias", r"DOTAÇÃO ATUALIZADA \(e\)")
    emp = lt.valor(per, "Anexo 01", "DespesasExcetoIntraOrcamentarias", r"DESPESAS EMPENHADAS ATÉ O BIMESTRE \(f\)")
    liq = lt.valor(per, "Anexo 01", "DespesasExcetoIntraOrcamentarias", r"DESPESAS LIQUIDADAS ATÉ O BIMESTRE \(h\)")
    pag = lt.valor(per, "Anexo 01", "DespesasExcetoIntraOrcamentarias", r"DESPESAS PAGAS ATÉ O BIMESTRE \(j\)")
    if None not in (dot, emp, liq, pag):
        rm.margens = Margens(previsto=dot, empenhado=emp, liquidado=liq, pago=pag, pago_com_vinculo=pag)
        rm.margens_no_ano = per.periodo == 6
        execucao = mz.despesa(con, janela) if msc_cobre else None
        if execucao is not None:
            for titulo, rreo, msc in (("Despesa empenhada", emp, execucao.empenhado),
                                      ("Despesa liquidada", liq, execucao.liquidado),
                                      ("Despesa paga", pag, execucao.pago)):
                rm.conferencias.append(Conferencia(titulo, selar([
                    Via("RREO Anexo 1", rreo), Via("Matriz de saldos contábeis", msc)], tolerancia=TOLERANCIA_CONTABIL),
                    f"{rm.rotulo}: despesa exceto intraorçamentária", Tipo.ENTRE_DEMONSTRATIVOS))
    else:
        rm.notas.append("O RREO Anexo 1 não traz a despesa dotada, empenhada, liquidada e paga do bimestre.")

    # --- A origem e o leito, no exercício da data do parecer ---------------------------------------
    ate = ate or per.termina
    exercicio = [f"{ate.year}-{m:02d}" for m in range(1, ate.month + 1)
                 if date(ate.year, m, calendar.monthrange(ate.year, m)[1]) <= ate]
    exercicio_msc = [m for m in exercicio if m in entregues]
    rm.conferencias.extend(conferir_origem(con, exercicio_msc))
    rm.meses_desvio = exercicio_msc
    rm.desvios, rm.fontes_sem_catalogo = desvios(con, exercicio_msc)
    return rm


# --- A segunda via da origem --------------------------------------------------------------------
def _portal(con: sqlite3.Connection, o: Origem, meses: list[str]
            ) -> tuple[dict[str, float], dict[str, list[tuple[str, str, float]]], set[str]]:
    """O que o SIAFI mostra: valor por mês, as linhas de cada mês e os meses em que o Portal traz o tipo."""
    marcas = ",".join("?" for _ in meses)
    com_tipo = {m for (m,) in con.execute(
        f"select distinct mes from transferencias_federais where tipo = ? and mes in ({marcas})", [o.tipo, *meses])}
    sql = (f"select mes, acao, nome_acao, sum(valor) from transferencias_federais where tipo = ? and mes in ({marcas}) "
           "and tipo_favorecido in ('Administração Pública', 'Administração Pública Municipal')")
    args: list = [o.tipo, *meses]
    if o.acoes:
        sql += f" and acao in ({','.join('?' for _ in o.acoes)})"
        args += list(o.acoes)
    if o.orgao:
        sql += " and orgao like ?"
        args.append(o.orgao)
    if o.sem_acoes:
        sql += f" and acao not in ({','.join('?' for _ in o.sem_acoes)})"
        args += list(o.sem_acoes)
    sql += " group by mes, acao, nome_acao"
    valores: dict[str, float] = {}
    linhas: dict[str, list[tuple[str, str, float]]] = {}
    for m, acao, nome, v in con.execute(sql, args):
        valores[m] = valores.get(m, 0.0) + (v or 0.0)
        linhas.setdefault(m, []).append((acao, nome or "", v or 0.0))
    return valores, linhas, com_tipo


def _registrado(con: sqlite3.Connection, o: Origem, meses: list[str]) -> dict[str, float]:
    if not o.fontes:
        return mz.receita(con, o.natureza, meses)
    out: dict[str, float] = {}
    for (f, m), v in mz.receita_por_fonte_e_mes(con, o.natureza, meses).items():
        if len(f) >= 4 and f[1:4] in o.fontes:
            out[m] = out.get(m, 0.0) + v
    return out


def conferir_origem(con: sqlite3.Connection, meses: list[str]) -> list[Conferencia]:
    """Cada transferência da União: o SIAFI contra a MSC, somados nos meses que os dois trazem."""
    if not meses:
        return []
    try:
        con.execute("select 1 from transferencias_federais limit 1")
    except sqlite3.OperationalError:
        return []
    out: list[Conferencia] = []
    for o in ORIGENS:
        siafi, linhas, com_tipo = _portal(con, o, meses)
        comuns = [m for m in meses if m in com_tipo]
        if not comuns:
            continue
        registrado = _registrado(con, o, comuns)
        adicional = mz.receita(con, o.adicional, comuns) if o.adicional else {}
        via_siafi, via_mun, detalhe = 0.0, 0.0, []
        for m in comuns:
            s = siafi.get(m, 0.0)
            bruto = s / 0.8 if o.retencao_fundeb else s
            r = registrado.get(m, 0.0)
            extra = adicional.get(m, 0.0)
            # O 1% adicional do FPM não sofre a retenção; o Portal ora o soma à ação, ora não.
            if extra and abs(s - (0.8 * r + extra)) < abs(s - 0.8 * r):
                bruto = (s - extra) / 0.8 + extra
                r += extra
                detalhe.append(f"Em {_mes(m)} o SIAFI soma à ação o 1% adicional do FPM ({_moeda(extra)}), "
                               "que entra inteiro.")
            via_siafi += bruto
            via_mun += r
            dif = bruto - r
            if abs(dif) > max(1_000.0, 0.01 * max(abs(bruto), abs(r))):
                detalhe.append(f"{_mes(m)}: SIAFI {_moeda(bruto)}, Município {_moeda(r)} (diferença {_moeda(dif)}).")
                if dif > 0:
                    detalhe.extend(_onde_foi_parar(con, o, m, linhas.get(m, [])))
        retencao = "; o SIAFI traz o líquido da retenção de 20% ao FUNDEB, somada de volta" if o.retencao_fundeb else ""
        out.append(Conferencia(
            o.nome, selar([Via("Portal da Transparência, SIAFI (o que a União transferiu)", via_siafi),
                           Via("Matriz de saldos contábeis (o que o Município registrou)", via_mun)]),
            f"{_periodo(comuns)}, {len(comuns)} meses{retencao}", Tipo.ENTRE_FONTES,
            detalhe=detalhe, norma=o.norma))
    return out


def _onde_foi_parar(con: sqlite3.Connection, o: Origem, mes: str,
                    linhas: list[tuple[str, str, float]]) -> list[str]:
    """Cada transferência do mês procurada pelo valor exato nas naturezas e fontes de transferência do
    mesmo mês que não são o registro esperado."""
    achados: list[str] = []
    candidatos = mz.receitas_do_mes(con, mes, _TRANSF)
    for acao, nome, v in linhas:
        if v <= 0:
            continue
        for natureza, fonte, valor in candidatos:
            esperado = any(natureza.startswith(p) for p in o.natureza.entram) and \
                (not o.fontes or (len(fonte) >= 4 and fonte[1:4] in o.fontes))
            if esperado or abs(valor - v) > 0.5:
                continue
            achados.append(f"Os {_moeda(v)} da ação {acao} ({nome.capitalize()[:70]}) de {_mes(mes)} aparecem no "
                           f"mesmo mês na natureza {natureza}, fonte {fonte} ({classificar(fonte).nome}): o "
                           "recurso entrou, mas fora da fonte que o vincula.")
            break
    return achados


# --- Recurso vinculado empenhado fora da sua finalidade ------------------------------------------
def desvios(con: sqlite3.Connection, meses: list[str]) -> tuple[list[Desvio], dict[str, float]]:
    """Os empenhos do exercício por fonte e função: o que sai da finalidade e as fontes sem catálogo."""
    grupos: dict[tuple[str, str, str], Desvio] = {}
    sem_catalogo: dict[str, float] = {}
    for e in mz.empenhos_por_fonte(con, meses):
        fonte = classificar(e.fonte)
        if not fonte.conhecida:
            chave_f = e.fonte[1:4] if len(e.fonte) >= 4 else e.fonte
            sem_catalogo[chave_f] = sem_catalogo.get(chave_f, 0.0) + e.valor
            continue
        assert fonte.destinacao is not None
        nucleo = fonte.destinacao.codigo
        if nucleo == "755" and e.natureza.startswith("3") and e.funcao != "09":
            d = grupos.setdefault((nucleo, e.funcao, "alienacao"), Desvio(
                nucleo, fonte.nome, e.funcao, 0.0, "LC 101/2000, art. 44", "alienacao"))
        elif desvio_de_finalidade(e.fonte, e.funcao):
            d = grupos.setdefault((nucleo, e.funcao, "leito"), Desvio(
                nucleo, fonte.nome, e.funcao, 0.0, fonte.destinacao.norma or "fonte vinculada", "leito"))
        else:
            continue
        d.valor += e.valor
        d.naturezas.append((e.subfuncao, e.natureza, e.valor))
    out = [d for d in grupos.values() if d.valor >= PISO_DESVIO]
    for d in out:
        d.naturezas.sort(key=lambda x: -x[2])
    out.sort(key=lambda d: -d.valor)
    return out, {f: v for f, v in sorted(sem_catalogo.items()) if abs(v) >= 0.005}
