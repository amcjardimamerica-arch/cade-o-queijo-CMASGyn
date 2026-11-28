"""As secretarias pela trilha: a execução de cada domínio, as margens, a integridade e a qualidade do plano.

Cada domínio do alvo (``dominios/*.toml``) é recortado no orçamento por funções e subfunções. Para
cada um, no exercício e até o último bimestre entregue:

* **Autorizado, empenhado, liquidado e pago** (requisito 105). O autorizado (dotação atualizada), o
  empenhado e o liquidado têm duas vias: o RREO Anexo 2 (por função e subfunção) e a matriz de
  saldos contábeis (MSC), duas entregas homologadas em separado. Nos dados de Goiânia de 2025 e 2026
  as duas são iguais ao real. O pago só existe na matriz (o Anexo 2 não o traz): uma via, selo azul,
  até o portal da execução item a item ser a segunda.
* **As quatro margens** (requisito 22): previsto e não empenhado, empenhado e não liquidado, liquidado
  e não pago, e pago sem vínculo publicado. A quarta só se mede item a item (o pagamento cruzado com
  o contrato, a folha ou o termo); sem o portal, ela fica sem medida, com o motivo, e nunca zero.
* **A integridade da secretaria** (requisito 83), com o índice do núcleo: coerência (a fração dos
  valores da pasta em que as duas vias dizem o mesmo), tempestividade (a matriz e o RREO entregues no
  prazo, pela data da versão em vigor no SICONFI), cobertura e vínculo (a fração do pago da pasta que
  cruza as nove estações e que tem instrumento, só com o item a item), prestação (sem leitura ainda).
* **A qualidade do plano municipal da pasta** (requisito 106): o quanto o orçamento que executa o
  plano se cumpre. Aderência (1 menos a parte da dotação inicial refeita por créditos), execução
  (liquidado sobre o autorizado no fim do exercício) e o indicador de resultado do plano, lido da
  fonte nacional quando houver coleta.
* **As contas uma a uma** (requisito 132): as nove maiores saídas, com as quatro estações legais
  (empenho, liquidação, ordem de pagamento e pagamento, Lei 4.320/1964, arts. 58 a 65) e a
  cronologia. Com o portal, por credor e evento a evento; sem ele, pela natureza da despesa na
  matriz, mês a mês, e a ordem de pagamento fica marcada como não publicada na matriz.
* **O rio da secretaria** (requisito 130): o realizado (pago) da pasta aberto pelas fontes.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from .. import partes as _partes
from ..config import Dominio
from ..nucleo.integridade import IndiceIntegridade
from ..nucleo.selos import Certificacao, Selo, Via, selar
from .afluentes import Afluente, Margens, Rio
from .fontes import Esfera, classificar

TOLERANCIA = 1e-6     # RREO e matriz saem da mesma contabilidade: só o arredondamento separa
_SOMA = "sum(case when natureza_conta = 'C' then valor else -valor end)"

# Portaria MOG 42/1999: o nome da função e das subfunções como o RREO Anexo 2 as escreve.
FUNCOES = {
    "01": "Legislativa", "02": "Judiciária", "03": "Essencial à Justiça", "04": "Administração",
    "05": "Defesa Nacional", "06": "Segurança Pública", "07": "Relações Exteriores", "08": "Assistência Social",
    "09": "Previdência Social", "10": "Saúde", "11": "Trabalho", "12": "Educação", "13": "Cultura",
    "14": "Direitos da Cidadania", "15": "Urbanismo", "16": "Habitação", "17": "Saneamento",
    "18": "Gestão Ambiental", "19": "Ciência e Tecnologia", "20": "Agricultura", "21": "Organização Agrária",
    "22": "Indústria", "23": "Comércio e Serviços", "24": "Comunicações", "25": "Energia", "26": "Transporte",
    "27": "Desporto e Lazer", "28": "Encargos Especiais",
}
SUBFUNCOES = {
    "122": "Administração Geral", "301": "Atenção Básica", "302": "Assistência Hospitalar e Ambulatorial",
    "303": "Suporte Profilático e Terapêutico", "304": "Vigilância Sanitária", "305": "Vigilância Epidemiológica",
    "361": "Ensino Fundamental", "365": "Educação Infantil", "366": "Educação de Jovens e Adultos",
    "367": "Educação Especial", "244": "Assistência Comunitária", "241": "Assistência ao Idoso",
    "243": "Assistência à Criança e ao Adolescente", "451": "Infra-Estrutura Urbana", "452": "Serviços Urbanos",
    "453": "Transportes Coletivos Urbanos", "511": "Saneamento Básico Rural", "512": "Saneamento Básico Urbano",
    "782": "Transporte Rodoviário",
}
# Elementos de despesa (Portaria Interministerial 163/2001), para nomear as saídas da matriz.
ELEMENTOS = {
    "01": "Aposentadorias e reformas", "03": "Pensões", "04": "Contratação por tempo determinado",
    "05": "Outros benefícios previdenciários", "08": "Outros benefícios assistenciais",
    "11": "Vencimentos e vantagens fixas", "13": "Obrigações patronais", "14": "Diárias",
    "16": "Outras despesas variáveis de pessoal", "18": "Auxílio financeiro a estudantes",
    "21": "Juros sobre a dívida", "30": "Material de consumo", "31": "Premiações", "32": "Material de distribuição gratuita",
    "33": "Passagens e locomoção", "34": "Outras despesas de pessoal (terceirização)", "35": "Serviços de consultoria",
    "36": "Serviços de terceiros, pessoa física", "37": "Locação de mão de obra",
    "39": "Serviços de terceiros, pessoa jurídica", "40": "Serviços de tecnologia da informação",
    "41": "Contribuições", "43": "Subvenções sociais", "46": "Auxílio-alimentação", "47": "Obrigações tributárias",
    "48": "Auxílio financeiro a pessoas físicas", "49": "Auxílio-transporte", "51": "Obras e instalações",
    "52": "Equipamentos e material permanente", "61": "Aquisição de imóveis", "71": "Principal da dívida",
    "85": "Contrato de gestão", "91": "Sentenças judiciais", "92": "Despesas de exercícios anteriores",
    "93": "Indenizações e restituições", "94": "Indenizações trabalhistas",
}


def _tem(con: sqlite3.Connection, tabela: str) -> bool:
    return _partes.tem_tabela(con, tabela)


def _filtro_recorte(d: Dominio) -> tuple[str, list[str]]:
    partes, args = [], []
    for f, s in d.recortes:
        if s is None:
            partes.append("(funcao = ?)")
            args.append(f)
        else:
            partes.append("(funcao = ? and subfuncao = ?)")
            args += [f, s]
    return "(" + " or ".join(partes) + ")", args


def _meses(exercicio: int, ate_mes: int) -> list[str]:
    return [f"{exercicio}-{m:02d}" for m in range(1, ate_mes + 1)]


def _msc(con: sqlite3.Connection, d: Dominio, meses: list[str], prefixo: str, *, por: str = "") -> dict:
    """Movimento líquido da matriz nos meses, no recorte do domínio, exceto intraorçamentária."""
    if not meses or not _tem(con, "msc_itens"):
        return {}
    filtro, args = _filtro_recorte(d)
    marcas = ",".join("?" for _ in meses)
    grupo = f"{por}, " if por else ""
    sql = (f"select {grupo}{_SOMA} from msc_itens where conta_contabil like ? and {filtro} and "
           f"substr(natureza_despesa, 3, 2) != '91' and mes in ({marcas})" + (f" group by {por}" if por else ""))
    linhas = con.execute(sql, [prefixo, *args, *meses]).fetchall()
    if not por:
        return {"": linhas[0][0]} if linhas and linhas[0][0] is not None else {}
    return {tuple(r[:-1]) if len(r) > 2 else r[0]: r[-1] or 0.0 for r in linhas}


def _um(con, d, meses, prefixo) -> float | None:
    return _msc(con, d, meses, prefixo).get("")


def execucao_na_matriz(con: sqlite3.Connection, d: Dominio, meses: list[str]) -> dict[str, float | None]:
    """Autorizado (dotação atualizada: crédito disponível mais empenhado), empenhado, liquidado e pago."""
    aut = _um(con, d, meses, "6221%")
    emp = _um(con, d, meses, "62213%")
    l3, l4, l7 = (_um(con, d, meses, p) for p in ("6221303%", "6221304%", "6221307%"))
    liq = None if emp is None else (l3 or 0.0) + (l4 or 0.0) + (l7 or 0.0)
    return {"autorizado": aut, "empenhado": emp, "liquidado": liq, "pago": None if emp is None else (l4 or 0.0)}


# --- O RREO Anexo 2 -------------------------------------------------------------------------------

COLUNAS_ANEXO2 = {"inicial": "DOTAÇÃO INICIAL", "autorizado": "DOTAÇÃO ATUALIZADA (a)",
                  "empenhado": "DESPESAS EMPENHADAS ATÉ O BIMESTRE (b)",
                  "liquidado": "DESPESAS LIQUIDADAS ATÉ O BIMESTRE (d)"}


def _anexo2(con: sqlite3.Connection, exercicio: int, bimestre: int, nome: str, coluna: str) -> float | None:
    """A linha da função ou subfunção no Anexo 2; None se ausente ou se o nome se repete (ambíguo)."""
    linhas = con.execute(
        "select valor from siconfi_itens where demonstrativo = 'RREO' and exercicio = ? and periodo = ? and "
        "anexo = 'RREO-Anexo 02' and rotulo like 'Total das Despesas Exceto Intra%' and coluna = ? and conta = ?",
        (exercicio, bimestre, coluna, nome)).fetchall()
    if len(linhas) == 1:
        return linhas[0][0]
    if linhas:
        return None
    # A linha existe (tem dotação) mas a coluna veio vazia: o SICONFI omite o zero.
    base = con.execute(
        "select count(*) from siconfi_itens where demonstrativo = 'RREO' and exercicio = ? and periodo = ? and "
        "anexo = 'RREO-Anexo 02' and rotulo like 'Total das Despesas Exceto Intra%' and coluna = ? and conta = ?",
        (exercicio, bimestre, COLUNAS_ANEXO2["inicial"], nome)).fetchone()[0]
    return 0.0 if base == 1 else None


def execucao_no_rreo(con: sqlite3.Connection, d: Dominio, exercicio: int, bimestre: int) -> dict[str, float | None]:
    if not _tem(con, "siconfi_itens"):
        return {k: None for k in COLUNAS_ANEXO2}
    out: dict[str, float | None] = {}
    for chave, coluna in COLUNAS_ANEXO2.items():
        total = 0.0
        for f, s in d.recortes:
            nome = FUNCOES.get(f) if s is None else SUBFUNCOES.get(s)
            v = _anexo2(con, exercicio, bimestre, nome, coluna) if nome else None
            if v is None:
                total = None
                break
            total += v
        out[chave] = total
    return out


def bimestres_entregues(con: sqlite3.Connection, exercicio: int | None = None) -> list[tuple[int, int, date]]:
    if not _tem(con, "siconfi_periodos"):
        return []
    sql = ("select exercicio, periodo, termina from siconfi_periodos where demonstrativo = 'RREO' and "
           "situacao = 'entregue' and itens > 0")
    args: list = []
    if exercicio is not None:
        sql += " and exercicio = ?"
        args.append(exercicio)
    return [(e, p, date.fromisoformat(t)) for e, p, t in con.execute(sql + " order by exercicio, periodo", args)]


def ultimo_bimestre(con: sqlite3.Connection, ate: date) -> tuple[int, int] | None:
    cand = [(e, p) for e, p, t in bimestres_entregues(con) if t <= ate]
    return cand[-1] if cand else None


# --- A execução da secretaria ---------------------------------------------------------------------

@dataclass
class Valor:
    titulo: str
    certificacao: Certificacao

    @property
    def valor(self) -> float | None:
        c = self.certificacao
        return c.valor if c.valor is not None else next((v.valor for v in c.vias if v.valor is not None), None)

    @property
    def selo(self) -> Selo | None:
        return self.certificacao.selo

    def como_dict(self) -> dict:
        c = self.certificacao
        return {"titulo": self.titulo, "valor": self.valor, "selo": c.selo.value if c.selo else None,
                "divergencia": c.divergencia, "vias": [{"fonte": v.fonte, "valor": v.valor} for v in c.vias]}


@dataclass
class ExecucaoSecretaria:
    dominio: Dominio
    exercicio: int
    bimestre: int
    valores: dict[str, Valor] = field(default_factory=dict)   # autorizado, empenhado, liquidado, pago
    inicial: float | None = None
    pago_com_vinculo: float | None = None                    # só com o item a item
    por_fonte: list[dict] = field(default_factory=list)
    notas: list[str] = field(default_factory=list)

    @property
    def rotulo(self) -> str:
        return f"{self.dominio.nome}, RREO do {self.bimestre}º bimestre de {self.exercicio}"

    def v(self, chave: str) -> float | None:
        return self.valores[chave].valor if chave in self.valores else None

    @property
    def margens(self) -> Margens | None:
        vals = [self.v(k) for k in ("autorizado", "empenhado", "liquidado", "pago")]
        if None in vals:
            return None
        return Margens(*vals, pago_com_vinculo=self.pago_com_vinculo)  # type: ignore[arg-type]

    def certificacoes(self) -> list[Certificacao]:
        return [v.certificacao for v in self.valores.values()]

    def como_dict(self) -> dict:
        m = self.margens
        return {"dominio": self.dominio.id, "nome": self.dominio.nome, "exercicio": self.exercicio,
                "bimestre": self.bimestre, "inicial": self.inicial,
                "valores": {k: v.como_dict() for k, v in self.valores.items()},
                "margens": None if m is None else m.como_dict(), "por_fonte": self.por_fonte, "notas": self.notas}


def execucao(con: sqlite3.Connection, d: Dominio, exercicio: int, bimestre: int) -> ExecucaoSecretaria:
    """A execução da secretaria no exercício até o bimestre, com as duas vias seladas."""
    meses = _meses(exercicio, 2 * bimestre)
    entregues = {m for (m,) in con.execute("select mes from msc_meses where situacao = 'entregue'")} \
        if _tem(con, "msc_meses") else set()
    msc_cobre = all(m in entregues for m in meses)
    msc = execucao_na_matriz(con, d, meses) if msc_cobre else {k: None for k in ("autorizado", "empenhado",
                                                                                  "liquidado", "pago")}
    rreo = execucao_no_rreo(con, d, exercicio, bimestre)
    ex = ExecucaoSecretaria(d, exercicio, bimestre, inicial=rreo.get("inicial"))
    if not msc_cobre:
        ex.notas.append(f"A matriz de saldos contábeis não cobre os {len(meses)} meses do período: o pago da "
                        "secretaria fica sem medida e os demais valores ficam com uma via.")
    if None in (rreo.get("autorizado"), rreo.get("empenhado")):
        ex.notas.append("O RREO Anexo 2 não traz o recorte da secretaria com nome único (subfunção agregada em "
                        "\"demais subfunções\" ou ausente): fica a via da matriz.")
    for chave in ("autorizado", "empenhado", "liquidado"):
        ex.valores[chave] = Valor(chave, selar([Via("RREO Anexo 2", rreo.get(chave)),
                                                Via("Matriz de saldos contábeis", msc.get(chave))],
                                               tolerancia=TOLERANCIA, exigido_por_lei=True))
    ex.valores["pago"] = Valor("pago", selar([Via("Matriz de saldos contábeis", msc.get("pago"))],
                                             exigido_por_lei=True))
    if msc_cobre:
        emp = _msc(con, d, meses, "62213%", por="fonte_recursos")
        pago = _msc(con, d, meses, "6221304%", por="fonte_recursos")
        for fonte in sorted(set(emp) | set(pago), key=lambda f: -(pago.get(f) or 0.0)):
            cl = classificar(str(fonte or ""))
            ex.por_fonte.append({"fonte": str(fonte or ""), "nome": cl.destinacao.nome if cl.destinacao else "",
                                 "vinculada": cl.vinculada if cl.conhecida else None,
                                 "empenhado": round(emp.get(fonte) or 0.0, 2), "pago": round(pago.get(fonte) or 0.0, 2)})
    return ex


def execucao_por_secretaria(con: sqlite3.Connection, dominios, ate: date) -> list[ExecucaoSecretaria]:
    """Requisito 105: autorizado, empenhado, liquidado e pago de cada secretaria, no último bimestre."""
    ub = ultimo_bimestre(con, ate)
    if ub is None:
        return []
    return [execucao(con, d, ub[0], ub[1]) for d in dominios]


# --- O rio da secretaria: o realizado aberto pelas fontes -------------------------------------------

def rio_da_secretaria(ex: ExecucaoSecretaria) -> Rio:
    rio = Rio(f"{ex.exercicio}-{2 * ex.bimestre:02d}")
    for f in ex.por_fonte:
        if f["pago"] <= 0:
            continue
        cl = classificar(f["fonte"])
        esfera = cl.destinacao.esfera if cl.destinacao else Esfera.MISTA
        nome = f"{f['fonte']} · {f['nome']}" if f["nome"] else f"Fonte {f['fonte']}"
        rio.afluentes.append(Afluente(nome, esfera, f["pago"], f["fonte"], Selo.AZUL,
                                      f"pago no exercício até o {ex.bimestre}º bimestre, matriz de saldos contábeis"))
    return rio


# --- A integridade da secretaria ---------------------------------------------------------------------

def _prazo_msc(mes: str) -> date:
    a, m = int(mes[:4]), int(mes[5:7])
    a2, m2 = (a + 1, 1) if m == 12 else (a, m + 1)
    a3, m3 = (a2 + 1, 1) if m2 == 12 else (a2, m2 + 1)
    return date(a3, m3, 1).fromordinal(date(a3, m3, 1).toordinal() - 1)


def tempestividade(con: sqlite3.Connection, exercicio: int, ate: date) -> tuple[float | None, str]:
    """A fração das entregas devidas até ``ate`` (matriz mês a mês e RREO bimestre a bimestre) feitas
    no prazo, pela data da versão em vigor no SICONFI: uma retificação conta como entrega naquela data."""
    if not _tem(con, "siconfi_entregas"):
        return None, "as datas de entrega do SICONFI não estão no banco"
    devidas, no_prazo = 0, 0
    datas: dict[tuple[str, int], date] = {}
    for ent, per, quando in con.execute(
            "select entregavel, periodo, max(data_status) from siconfi_entregas where exercicio = ? group by 1, 2",
            (exercicio,)):
        try:
            datas[(ent, int(per))] = datetime.fromisoformat(str(quando).replace("Z", "+00:00")).date()
        except (TypeError, ValueError):
            continue
    for m in range(1, 13):
        prazo = _prazo_msc(f"{exercicio}-{m:02d}")
        if prazo > ate:
            continue
        devidas += 1
        d = datas.get(("MSC Agregada", m))
        no_prazo += bool(d and d <= prazo)
    if _tem(con, "siconfi_periodos"):
        for per, prazo in con.execute("select periodo, prazo from siconfi_periodos where demonstrativo = 'RREO' "
                                      "and exercicio = ?", (exercicio,)):
            p = date.fromisoformat(prazo)
            if p > ate:
                continue
            devidas += 1
            d = datas.get(("Relatório Resumido de Execução Orçamentária", int(per)))
            no_prazo += bool(d and d <= p)
    if not devidas:
        return None, "nenhuma entrega devida no período"
    return no_prazo / devidas, (f"{no_prazo} de {devidas} entregas (matriz mensal e RREO) no prazo, pela data "
                                "da versão em vigor no SICONFI")


def coerencia(con: sqlite3.Connection, d: Dominio, exercicio: int, ate_bimestre: int) -> tuple[float | None, str]:
    """A fração dos valores da secretaria (autorizado, empenhado e liquidado de cada bimestre) em que o
    RREO e a matriz dizem o mesmo."""
    verdes = total = 0
    for _e, b, _t in bimestres_entregues(con, exercicio):
        if b > ate_bimestre:
            continue
        ex = execucao(con, d, exercicio, b)
        for k in ("autorizado", "empenhado", "liquidado"):
            c = ex.valores[k].certificacao
            if len(c.vias) >= 2:
                total += 1
                verdes += c.selo is Selo.VERDE
    if not total:
        return None, "nenhum valor da secretaria com as duas vias no período"
    return verdes / total, f"{verdes} de {total} valores da pasta iguais no RREO Anexo 2 e na matriz"


def integridade_da_secretaria(con: sqlite3.Connection, d: Dominio, exercicio: int, bimestre: int, ate: date, *,
                              cobertura: float | None = None, vinculo: float | None = None,
                              minimo: float = 50.0) -> IndiceIntegridade:
    """Requisito 83: o índice do núcleo medido para uma secretaria. O que não se mede fica sem nota,
    com o motivo, e nunca conta como zero contra o Município."""
    coe, m_coe = coerencia(con, d, exercicio, bimestre)
    tem, m_tem = tempestividade(con, exercicio, ate)
    motivos = {"coerencia": m_coe, "tempestividade": m_tem}
    if cobertura is None:
        motivos["cobertura"] = ("a execução item a item do portal (empenhos, liquidações e pagamentos) ainda "
                                "não está no banco: sem ela, o pago da pasta não se segue pelas nove estações")
    else:
        motivos["cobertura"] = "fração do pago da pasta que cruza as nove estações, item a item"
    if vinculo is None:
        motivos["vinculo"] = "o pago da pasta ainda não se cruza com contratos, termos e folha (item a item)"
    else:
        motivos["vinculo"] = "fração do pago da pasta com contrato publicado no PNCP"
    motivos["prestacao"] = "a prestação de contas das parcerias da pasta ainda não é lida"
    return IndiceIntegridade(cobertura, coe, tem, vinculo, None, minimo=minimo, motivos=motivos)


# --- A qualidade do plano municipal da pasta ----------------------------------------------------------

@dataclass
class QualidadeDoPlano:
    plano: str
    norma: str
    exercicio: int
    inicial: float | None
    autorizado: float | None
    liquidado: float | None
    aderencia: float | None              # 1 - |autorizado - inicial| / inicial
    execucao: float | None               # liquidado / autorizado no fim do exercício
    indicador: str = ""
    fonte_indicador: str = ""
    valor_indicador: float | None = None
    motivo_indicador: str = ""

    @property
    def nota(self) -> float | None:
        """De 0 a 100: a média de aderência e execução (as duas medidas do orçamento do plano)."""
        partes = [p for p in (self.aderencia, self.execucao) if p is not None]
        return round(100 * sum(partes) / len(partes), 1) if partes else None

    def como_dict(self) -> dict:
        return {"plano": self.plano, "norma": self.norma, "exercicio": self.exercicio, "inicial": self.inicial,
                "autorizado": self.autorizado, "liquidado": self.liquidado, "aderencia": self.aderencia,
                "execucao": self.execucao, "nota": self.nota, "indicador": self.indicador,
                "fonte_indicador": self.fonte_indicador, "valor_indicador": self.valor_indicador,
                "motivo_indicador": self.motivo_indicador}


def qualidade_do_plano(con: sqlite3.Connection, d: Dominio, ate: date) -> QualidadeDoPlano | None:
    """Requisito 106, no último exercício fechado (6º bimestre entregue) até ``ate``."""
    fechados = [(e, p) for e, p, t in bimestres_entregues(con) if p == 6 and t <= ate]
    if not fechados:
        return None
    exercicio = fechados[-1][0]
    rreo = execucao_no_rreo(con, d, exercicio, 6)
    ini, aut, liq = rreo.get("inicial"), rreo.get("autorizado"), rreo.get("liquidado")
    if aut is None:
        msc = execucao_na_matriz(con, d, _meses(exercicio, 12))
        aut, liq = msc.get("autorizado"), msc.get("liquidado")
    q = d.qualidade
    ader = None if not ini or aut is None else max(0.0, 1 - abs(aut - ini) / ini)
    exe = None if not aut or liq is None else max(0.0, min(1.0, liq / aut))
    return QualidadeDoPlano(
        plano=q.get("plano", f"plano municipal de {d.nome}"), norma=q.get("norma_do_plano", ""), exercicio=exercicio,
        inicial=ini, autorizado=aut, liquidado=liq, aderencia=None if ader is None else round(ader, 4),
        execucao=None if exe is None else round(exe, 4), indicador=q.get("indicador", ""),
        fonte_indicador=q.get("fonte", ""),
        motivo_indicador=(f"{q.get('indicador')} depende da coleta de {q.get('fonte')}, que ainda não roda"
                          if q.get("indicador") else ""))


# --- As contas uma a uma pela matriz (as nove maiores saídas) ------------------------------------------

def contas_pela_matriz(con: sqlite3.Connection, d: Dominio, exercicio: int, ate_mes: int, *,
                       maiores: int = 9) -> list[dict]:
    """As ``maiores`` saídas da secretaria por elemento de despesa, com empenho, liquidação, ordem de
    pagamento (que a matriz não traz) e pagamento, e a cronologia mês a mês."""
    meses = _meses(exercicio, ate_mes)
    if not _tem(con, "msc_itens"):
        return []
    filtro, args = _filtro_recorte(d)
    marcas = ",".join("?" for _ in meses)
    por: dict[str, dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    for conta, nd, mes, v in con.execute(
            f"select substr(conta_contabil, 1, 7), substr(natureza_despesa, 1, 6), mes, {_SOMA} from msc_itens "
            f"where conta_contabil like '62213%' and {filtro} and substr(natureza_despesa, 3, 2) != '91' and "
            f"mes in ({marcas}) group by 1, 2, 3", [*args, *meses]):
        estacao = {"6221304": "pagamento", "6221303": "liquidacao", "6221307": "liquidacao"}.get(conta)
        linha = por[str(nd)][mes]
        linha["empenho"] += v or 0.0
        if estacao == "pagamento":
            linha["pagamento"] += v or 0.0
            linha["liquidacao"] += v or 0.0
        elif estacao == "liquidacao":
            linha["liquidacao"] += v or 0.0
    saidas = []
    for nd, porm in por.items():
        est = {k: round(sum(m.get(k, 0.0) for m in porm.values()), 2) for k in ("empenho", "liquidacao", "pagamento")}
        elemento = nd[4:6] if len(nd) >= 6 else ""
        nome = ELEMENTOS.get(elemento, f"Elemento {elemento}")
        saidas.append({
            "saida": f"{nd[0]}.{nd[1]}.{nd[2:4]}.{nd[4:6]} · {nome}", "natureza": nd,
            "estacoes": {"empenho": est["empenho"], "liquidacao": est["liquidacao"], "ordem_pagamento": None,
                         "pagamento": est["pagamento"]},
            "cronologia": [{"mes": m, **{k: round(v, 2) for k, v in porm[m].items()}} for m in sorted(porm)],
            "origem": "matriz de saldos contábeis, mês a mês (sem credor: o credor vem do portal)"})
    saidas.sort(key=lambda s: -(s["estacoes"]["pagamento"] or 0.0))
    return saidas[:maiores]


def contas_uma_a_uma(con: sqlite3.Connection, d: Dominio, exercicio: int, ate_mes: int, *, maiores: int = 9) -> dict:
    """As saídas da secretaria: item a item (portal) quando o banco tem, pela matriz sempre.

    Devolve ``{"item_a_item": [...], "matriz": [...], "falta": "..."}`` para o parecer."""
    from ..conferencias.execucao import contas_item_a_item, ler_eventos
    eventos = [e for e in ler_eventos(con) if e.data and e.data.year == exercicio and e.data.month <= ate_mes
               and e.funcao and d.contem(e.funcao, e.subfuncao or None)]
    item = contas_item_a_item(eventos, maiores=maiores) if eventos else []
    return {"item_a_item": item, "matriz": contas_pela_matriz(con, d, exercicio, ate_mes, maiores=maiores),
            "falta": "" if item else ("O credor, a ordem de pagamento e a data de cada evento dependem da execução "
                                      "item a item do portal da transparência, que ainda não está no banco.")}


def abrir(banco: Path | str | sqlite3.Connection) -> sqlite3.Connection:
    if isinstance(banco, sqlite3.Connection):
        return banco
    return _partes.conectar_leitura(banco)


# --- A trilha item a item da secretaria (cobertura e vínculo do índice) ---------------------------------

def _norm(t: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().upper().strip()


def evento_da_secretaria(e, d: Dominio) -> bool:
    """O evento é da pasta pela função e subfunção da dotação; sem elas, pelo nome do órgão."""
    if e.funcao:
        return d.contem(e.funcao, e.subfuncao or None)
    nome = _norm(e.orgao)
    return any(_norm(o) and _norm(o) in nome for o in d.orgaos)


def trilha_da_secretaria(percursos, eventos, d: Dominio, *, exercicio: int | None = None,
                         ate_mes: int = 12) -> tuple[float | None, float | None]:
    """(cobertura, vínculo) do pago da pasta: a fração que cruza as nove estações e a fração com
    instrumento publicado. None quando a pasta não tem pagamento lido item a item.

    Com ``exercicio``, conta só o pago com data no exercício até ``ate_mes``: é o período do pago da pasta
    no parecer, que multiplica a fração para dar a margem do pago sem vínculo (requisito 22). Sem ele,
    conta o pago de todos os exercícios lidos."""
    from ..nucleo.estacoes import Estacao
    chaves = {e.chave for e in eventos if evento_da_secretaria(e, d)}
    meus = [p for p in percursos if p.chave in chaves]

    def pago(p) -> float:
        if exercicio is None:
            return p.valor_pago()
        return sum(e.valor or 0.0 for e in p.eventos if e.estacao is Estacao.PAGAMENTO and e.acende and e.data
                   and e.data.year == exercicio and e.data.month <= ate_mes)
    total = sum(pago(p) for p in meus)
    if total <= 0:
        return None, None
    completo = sum(pago(p) for p in meus if p.completo)
    com_vinculo = sum(pago(p) for p in meus if Estacao.VINCULO in p.acesas())
    return completo / total, com_vinculo / total


def achado_da_secretaria(a, d: Dominio) -> bool:
    """Um achado das conferências da execução pertence à pasta pela função ou pelo órgão."""
    funcao = a.dados.get("funcao") if a.dados else None
    if a.tipo == "fim_de_ano_funcao":
        funcao = a.chave.split("|", 1)[0]
        return funcao in d.funcoes and any(s is None for f, s in d.recortes if f == funcao)
    if funcao:
        return d.contem(funcao, (a.dados or {}).get("subfuncao") or None)
    nome = _norm(a.orgao)
    return any(_norm(o) and _norm(o) in nome for o in d.orgaos)
