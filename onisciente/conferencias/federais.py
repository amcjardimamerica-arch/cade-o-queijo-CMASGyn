"""As fontes do bloco 5 conferidas no banco histórico: FNS, FNDE, Transferegov, CEIS e CNEP, Economia GO,
TCU e TCM-GO.

Cada conferência põe lado a lado vias que não dependem umas das outras e transforma a diferença em
alerta. Alerta é indício, não acusação: diz o que a regra pede, o que o dado mostra e o que pedir.

* **SUS fundo a fundo**: o que o FNS diz ter pago ao Fundo Municipal de Saúde, o que o SIAFI mostra
  (Portal da Transparência) e o que o Município declara recebido da União no RREO Anexo 12 (SIOPS,
  "Provenientes da União"), no exercício até o último bimestre homologado (LC 141/2012, arts. 13 e 17).
* **FNDE**: as liberações do FNDE (SIMAD), programa a programa, contra as mesmas ações no SIAFI.
* **Emendas especiais**: pelo menos 70% de cada plano de ação em investimento (CF, art. 166-A, § 5º),
  plano a plano e no total do ano.
* **Contratada sancionada**: cada contrato do PNCP contra as sanções do CEIS e do CNEP do mesmo CNPJ
  (raiz de 8 dígitos) vigentes em qualquer dia do contrato (Lei 14.133/2021, arts. 14 e 156).
* **Cota estadual**: o ICMS e o IPVA que o Estado diz ter entregue contra o que o Município registrou
  (matriz de saldos contábeis). Se o Estado não publica, a ausência é alerta roxo com ofício
  (CF, art. 162).
* **Decisões de controle**: os acórdãos e as decisões do TCU e do TCM-GO sobre Goiânia com sinal de
  irregularidade (débito, multa, irregularidade, determinação, rejeição).
* **Contas irregulares do TCM-GO**: cada responsável de Goiânia (Prefeitura, fundos, empresas e
  autarquias) na lista dos dados abertos de contas julgadas irregulares, e o mesmo nome entre os sócios
  das contratadas (só pelo nome: o TCM mostra os dois primeiros dígitos do CPF e a Receita os do meio,
  então pode ser homônimo).

Os limiares ficam em ``LIMIARES``, cada um com valor, justificativa e base. São restritivos de
propósito: o dono pediu que nenhuma desconformidade passe, e um alerta a mais custa uma conferência;
um a menos custa o dinheiro que não foi seguido.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from ..coletores import economia_go
from ..coletores import sancoes as sc
from ..coletores.comum_federal import digitos, norm
from ..legal.mapa import MapaLegal, carregar
from ..lai import Oficio, oficios_por_orgao
from ..nucleo.ausencias import Ausencia
from ..nucleo.indicios import Familia, Ficha, emitir
from ..nucleo.provas import Nivel
from ..nucleo.selos import Certificacao, Via, selar
from ..rio import matriz as mz

LIMIARES = {
    "tolerancia_vias": {
        "valor": 0.001, "unidade": "fração da maior via",
        "justificativa": "Vias oficiais do mesmo pagamento só se separam por arredondamento; 0,1% já "
                         "basta para absorver centavos e ainda pega qualquer parcela perdida ou desviada.",
        "base": "Premissa do Onisciente (duas vias independentes); LC 141/2012, art. 13; Lei 4.320/1964, art. 35"},
    "diferenca_minima": {
        "valor": 1.0, "unidade": "R$",
        "justificativa": "Abaixo de um real a diferença é centavo de arredondamento entre sistemas.",
        "base": "Arredondamento dos sistemas (SIAFI, FNS, SIOPS)"},
    "capital_minimo_emenda": {
        "valor": 70.0, "unidade": "% do plano de ação em investimento",
        "justificativa": "A Constituição fixa o mínimo; ele é medido em cada plano de ação, e não só no "
                         "total do ano, para não deixar um plano de custeio se esconder atrás de outro de obra.",
        "base": "CF, art. 166-A, § 5º"},
    "sancao_qualquer_dia": {
        "valor": 1, "unidade": "dia de sobreposição",
        "justificativa": "Basta um dia de sanção dentro da vigência do contrato para o alerta; a assinatura "
                         "durante a sanção agrava, mas não é condição.",
        "base": "Lei 14.133/2021, arts. 14, III, 91, § 4º, e 156; Lei 12.846/2013, art. 22"},
    "vigencia_presumida_dias": {
        "valor": 365, "unidade": "dias depois da assinatura",
        "justificativa": "Quando o PNCP não traz a vigência, o contrato é tido como vigente por um ano "
                         "desde a assinatura, a duração usual dos contratos de serviço.",
        "base": "Lei 14.133/2021, arts. 105 e 106"},
    "cota_estadual_retencao_fundeb": {
        "valor": 0.8, "unidade": "fração líquida",
        "justificativa": "O Estado pode publicar a cota já líquida dos 20% retidos ao FUNDEB; a via líquida "
                         "é dividida por 0,8 antes de comparar.",
        "base": "Lei 14.113/2020, art. 3º, § 1º"},
    "janela_meses": {
        "valor": 12, "unidade": "meses",
        "justificativa": "O parecer do mês mostra os alertas dos doze meses que terminam nele.",
        "base": "Desenho do parecer mensal (mesma janela das compras)"},
}

PROGRAMAS_FNDE = (   # trecho do nome do programa no SIMAD -> ação orçamentária no SIAFI
    (("PNAE", "ALIMENTACAO ESCOLAR"), "00PI", "Alimentação escolar (PNAE)"),
    (("PNATE", "TRANSPORTE ESCOLAR"), "0969", "Transporte escolar (PNATE)"),
    (("PDDE", "DINHEIRO DIRETO"), "0515", "Dinheiro Direto na Escola (PDDE)"),
    (("SALARIO-EDUCACAO", "SALARIO EDUCACAO", "QSE", "QUOTA"), "0369", "Salário-educação (quota municipal)"),
    (("EJA", "ALFABETIZACAO", "JOVENS E ADULTOS"), "214V", "Educação de jovens e adultos"),
)

TERMOS_DE_ALERTA = ("IRREGULAR", "MULTA", "DEBITO", "IMPUTA", "RESSARC", "DETERMIN", "REJEI", "DESFAVORAVE",
                    "SOBREPRECO", "SUPERFATUR", "DANO AO ERARIO", "INIDONE", "CAUTELAR", "SUSPENS", "GLOSA",
                    "RESSALVA", "RECOMEND")

NOMES_DAS_FONTES = {"fns": "FNS (repasses fundo a fundo)", "fnde": "FNDE (liberações do SIMAD)",
                    "transferegov": "Transferegov", "sancoes": "CEIS e CNEP", "economia_go": "Economia GO",
                    "tcu": "TCU (acórdãos)", "tcm": "TCM-GO (decisões)"}

TITULOS = {
    "fns_divergencia": "Repasses do SUS fundo a fundo divergem entre o FNS, o SIAFI e o RREO",
    "fnde_divergencia": "Liberações do FNDE divergem do SIAFI",
    "emenda_capital_plano": "Plano de ação de emenda especial abaixo de 70% em capital",
    "emenda_capital_ano": "Emendas especiais do ano abaixo de 70% em capital",
    "contratada_sancionada": "Contrato com empresa sancionada no CEIS ou no CNEP",
    "cota_estadual_divergencia": "Cota de ICMS ou IPVA do Estado diverge do registrado pelo Município",
    "decisao_controle": "Decisão de tribunal de contas com sinal de irregularidade",
    "contas_irregulares_tcm": "Responsável com contas julgadas irregulares no TCM-GO",
    "socio_com_contas_irregulares": "Sócio de contratada com o nome de um responsável com contas irregulares no TCM-GO",
}


@dataclass
class Alerta:
    tipo: str
    chave: str
    mes: str
    descricao: str
    gravidade: str = "media"
    valor: float = 0.0
    limite: float = 0.0
    orgao: str = ""
    dados: dict = field(default_factory=dict)


@dataclass
class ConferenciaFederal:
    titulo: str
    certificacao: Certificacao
    referencia: str
    detalhe: list[str] = field(default_factory=list)
    norma: str = ""

    def como_dict(self) -> dict:
        c = self.certificacao
        return {"titulo": self.titulo, "referencia": self.referencia, "norma": self.norma,
                "selo": c.selo.value if c.selo else None, "divergencia": c.divergencia,
                "vias": [{"fonte": v.fonte, "valor": v.valor} for v in c.vias], "detalhe": self.detalhe}


@dataclass
class ConferenciasFederais:
    alertas: list[Alerta] = field(default_factory=list)
    conferencias: list[ConferenciaFederal] = field(default_factory=list)
    ausencias: list[Ausencia] = field(default_factory=list)
    cobertura: dict = field(default_factory=dict)
    limiares: dict = field(default_factory=lambda: LIMIARES)

    def por_tipo(self) -> dict[str, int]:
        return {t: sum(1 for a in self.alertas if a.tipo == t) for t in TITULOS}

    def da_competencia(self, competencia: str) -> list[Alerta]:
        inicio = _mes_menos(competencia, int(LIMIARES["janela_meses"]["valor"]) - 1)
        return [a for a in self.alertas if inicio <= a.mes <= competencia]

    def fichas(self, competencia: str | None = None) -> list[Ficha]:
        lista = self.da_competencia(competencia) if competencia else self.alertas
        out = [ficha(a, competencia) for a in lista]
        for motor, problema in sorted(self.cobertura.get("problemas", {}).items()):
            out.append(emitir(
                codigo=f"SIS-FEDERAL-{motor.upper()}", familia=Familia.SIS,
                titulo=f"Fonte do bloco 5 sem leitura: {NOMES_DAS_FONTES.get(motor, motor)}",
                gravidade="alta",
                como_deveria="Cada fonte federal e estadual do bloco 5 é lida no seu ciclo e conferida com as "
                             "outras vias.",
                norma="Premissa do Onisciente: falha de coleta é falha do sistema, nunca silêncio do Município",
                como_esta=problema[:1].upper() + problema[1:] + ".",
                niveis=[Nivel.F], documento_faltante=True,
                providencia=f"Rodar de novo o motor {motor}; se repetir, rodar a sondagem das chaves d1_ e "
                            "acertar o endereço no coletor.",
                competencia=competencia, origem="sistema"))
        return out

    def oficios(self, hoje: date | None = None) -> list[Oficio]:
        return oficios_por_orgao(self.ausencias, "Valores das cotas-partes do ICMS, do IPVA e do IPI-exportação entregues ao Município")

    def como_dict(self) -> dict:
        return {"por_tipo": self.por_tipo(), "cobertura": self.cobertura, "limiares": self.limiares,
                "conferencias": [c.como_dict() for c in self.conferencias],
                "ausencias": [a.como_dict() for a in self.ausencias],
                "alertas": [{"tipo": a.tipo, "chave": a.chave, "mes": a.mes, "descricao": a.descricao,
                             "gravidade": a.gravidade, "valor": a.valor, "limite": a.limite, "orgao": a.orgao}
                            for a in self.alertas]}


# --- Utilidades -------------------------------------------------------------------------------

def _mes_menos(mes: str, n: int) -> str:
    a, m = map(int, mes.split("-"))
    t = a * 12 + (m - 1) - n
    return f"{t // 12}-{t % 12 + 1:02d}"


def _moeda(v: float | None) -> str:
    if v is None:
        return "não informado"
    s = f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-R$ " if v < 0 else "R$ ") + s


def _tabela(con: sqlite3.Connection, nome: str) -> bool:
    return con.execute("select 1 from sqlite_master where type='table' and name=?", (nome,)).fetchone() is not None


def _vazia(con: sqlite3.Connection, nome: str) -> bool:
    return not _tabela(con, nome) or con.execute(f"select 1 from {nome} limit 1").fetchone() is None


def _difere(a: float, b: float) -> bool:
    maior = max(abs(a), abs(b))
    return abs(a - b) > max(LIMIARES["diferenca_minima"]["valor"], LIMIARES["tolerancia_vias"]["valor"] * maior)


def _selar(vias: list[Via]) -> Certificacao:
    return selar(vias, tolerancia=LIMIARES["tolerancia_vias"]["valor"])


def _meses_do_ano(ano: int, ate_mes: int) -> list[str]:
    return [f"{ano}-{m:02d}" for m in range(1, ate_mes + 1)]


# --- SUS fundo a fundo: FNS x SIAFI x RREO Anexo 12 --------------------------------------------

def _cnpjs_do_fundo_de_saude(con: sqlite3.Connection) -> set[str]:
    if not _tabela(con, "transferencias_federais"):
        return set()
    return {f for (f,) in con.execute(
        "select distinct favorecido from transferencias_federais where orgao like 'Ministério da Saúde%' "
        "and tipo_favorecido like 'Administração Pública%' and tipo_favorecido not like '%Estadual%'")}


def _siops_provenientes_da_uniao(con: sqlite3.Connection, ano: int, ate: date) -> tuple[int, float] | None:
    """(bimestre, receita realizada até ele) da linha "Provenientes da União" do RREO Anexo 12."""
    if not _tabela(con, "externos_itens"):
        return None
    bims = [b for (b,) in con.execute(
        "select periodo from externos_periodos where fonte='SIOPS' and exercicio=? and situacao='homologado' "
        "order by periodo desc", (ano,)) if date(ano, 2 * b, 1) <= ate]
    for bim in bims:
        linha = con.execute(
            "select valor from externos_itens where fonte='SIOPS' and exercicio=? and periodo=? and coluna=2 "
            "and upper(rotulo) like 'PROVENIENTES DA UNI%' and upper(titulo_quadro) like 'RECEITAS ADICIONAIS%'",
            (ano, bim)).fetchone()
        if linha:
            return bim, linha[0]
    return None


def _fns_x_siafi_x_rreo(con: sqlite3.Connection, ate: date, out: ConferenciasFederais) -> None:
    anos = set()
    if _tabela(con, "repasses_fns"):
        anos |= {a for (a,) in con.execute("select distinct ano from repasses_fns where ano is not null")}
    if not anos:
        return
    fundo = _cnpjs_do_fundo_de_saude(con)
    for ano in sorted(a for a in anos if a <= ate.year):
        siops = _siops_provenientes_da_uniao(con, ano, ate)
        if siops:
            bim, rreo = siops
            meses = _meses_do_ano(ano, 2 * bim)
            ref = f"jan/{ano} ao {bim}º bimestre"
        else:
            rreo = None
            meses = _meses_do_ano(ano, ate.month if ano == ate.year else 12)
            ref = f"{meses[0]} a {meses[-1]}"
        marcas = ",".join("?" for _ in meses)
        filtro_fundo = ""
        args: list = list(meses)
        if fundo:
            filtro_fundo = f" and (cnpj = '' or cnpj is null or cnpj in ({','.join('?' for _ in fundo)}))"
            args += sorted(fundo)
        por_mes_fns = dict(con.execute(
            f"select mes, sum(valor_liquido) from repasses_fns where mes in ({marcas}){filtro_fundo} group by mes",
            args).fetchall())
        por_mes_siafi = dict(con.execute(
            f"select mes, sum(valor) from transferencias_federais where mes in ({marcas}) and orgao like "
            "'Ministério da Saúde%' and tipo_favorecido like 'Administração Pública%' and tipo_favorecido "
            "not like '%Estadual%' group by mes", meses).fetchall()) if _tabela(con, "transferencias_federais") else {}
        fns_total = round(sum(por_mes_fns.values()), 2) if por_mes_fns else None
        siafi_total = round(sum(por_mes_siafi.values()), 2) if por_mes_siafi else None
        vias = [Via("FNS, repasses ao Fundo Municipal de Saúde (Ministério da Saúde)", fns_total, Nivel.A),
                Via("Portal da Transparência, SIAFI (Ministério da Saúde ao Município)", siafi_total, Nivel.B),
                Via("RREO Anexo 12 no SIOPS, receita da saúde provenientes da União (o Município declara)",
                    rreo, Nivel.B)]
        cert = _selar(vias)
        detalhe = []
        for m in meses:
            f, s = por_mes_fns.get(m), por_mes_siafi.get(m)
            if f is not None and s is not None and _difere(f, s):
                detalhe.append(f"{m}: FNS {_moeda(f)}, SIAFI {_moeda(s)} (diferença {_moeda(f - s)}).")
            elif (f is None) != (s is None) and (f or s):
                detalhe.append(f"{m}: só {'o FNS' if f is not None else 'o SIAFI'} traz pagamento "
                               f"({_moeda(f if f is not None else s)}).")
        out.conferencias.append(ConferenciaFederal("SUS fundo a fundo", cert, ref, detalhe,
                                                   "LC 141/2012, arts. 13, 17 e 18"))
        if cert.divergencia or detalhe:
            lidas = [v for v in vias if v.valor is not None]
            maior = max(lidas, key=lambda v: v.valor)
            menor = min(lidas, key=lambda v: v.valor)
            out.alertas.append(Alerta(
                "fns_divergencia", f"FNS-{ano}", meses[-1],
                "no período " + ref + ", " + "; ".join(f"{v.fonte}: {_moeda(v.valor)}" for v in lidas)
                + f". Diferença entre a maior e a menor via: {_moeda(maior.valor - menor.valor)}"
                + (". Meses que não fecham: " + " ".join(detalhe) if detalhe else ""),
                gravidade="alta", valor=round(maior.valor - menor.valor, 2), orgao="Fundo Municipal de Saúde",
                dados={"vias": {v.fonte: v.valor for v in lidas}}))


# --- FNDE: SIMAD x SIAFI ------------------------------------------------------------------------

def _programa(nome: str) -> tuple[str, str] | None:
    n = norm(nome)
    for trechos, acao, rotulo in PROGRAMAS_FNDE:
        if any(t in n for t in trechos):
            return acao, rotulo
    return None


def _fnde_x_siafi(con: sqlite3.Connection, ate: date, out: ConferenciasFederais) -> None:
    if _vazia(con, "liberacoes_fnde"):
        return
    for (ano,) in con.execute("select distinct ano from liberacoes_fnde order by ano").fetchall():
        if ano > ate.year:
            continue
        siafi_meses = {m for (m,) in con.execute(
            "select distinct mes from transferencias_federais where substr(mes,1,4)=?", (str(ano),))} \
            if _tabela(con, "transferencias_federais") else set()
        if not siafi_meses:
            continue
        simad: dict[str, float] = {}
        rotulos: dict[str, str] = {}
        sem_mapa: dict[str, float] = {}
        for prog, mes, valor in con.execute(
                "select programa, mes, valor from liberacoes_fnde where ano=?", (ano,)):
            if mes not in siafi_meses:
                continue
            achado = _programa(prog or "")
            if achado:
                simad[achado[0]] = simad.get(achado[0], 0.0) + (valor or 0.0)
                rotulos[achado[0]] = achado[1]
            else:
                sem_mapa[prog or "sem programa"] = sem_mapa.get(prog or "sem programa", 0.0) + (valor or 0.0)
        marcas = ",".join("?" for _ in siafi_meses)
        siafi = dict(con.execute(
            f"select acao, sum(valor) from transferencias_federais where orgao = 'Fundo Nacional de "
            f"Desenvolvimento da Educação' and mes in ({marcas}) group by acao", sorted(siafi_meses)).fetchall())
        for acao in sorted(set(simad) | {a for a in siafi if a in {p[1] for p in PROGRAMAS_FNDE}}):
            s, f = simad.get(acao), siafi.get(acao)
            rotulo = rotulos.get(acao) or next(p[2] for p in PROGRAMAS_FNDE if p[1] == acao)
            cert = _selar([Via("FNDE, liberações do SIMAD", round(s, 2) if s is not None else None, Nivel.A),
                           Via("Portal da Transparência, SIAFI", round(f, 2) if f is not None else None, Nivel.B)])
            ref = f"{min(siafi_meses)} a {max(siafi_meses)}, ação {acao}"
            out.conferencias.append(ConferenciaFederal(f"FNDE: {rotulo}", cert, ref,
                                                       norma="Lei 11.947/2009; CF, art. 212, § 6º"))
            if cert.divergencia or (s is None) != (f is None):
                dif = (s or 0.0) - (f or 0.0)
                out.alertas.append(Alerta(
                    "fnde_divergencia", f"FNDE-{ano}-{acao}", max(siafi_meses),
                    f"{rotulo}, {ref}: o FNDE liberou {_moeda(s)} e o SIAFI mostra {_moeda(f)} "
                    f"(diferença {_moeda(dif)})", gravidade="alta", valor=round(abs(dif), 2),
                    orgao="Fundo Nacional de Desenvolvimento da Educação"))
        if sem_mapa:
            out.cobertura.setdefault("fnde_programas_sem_acao", {})[str(ano)] = {
                k: round(v, 2) for k, v in sorted(sem_mapa.items())}


# --- Emendas especiais: 70% em capital ---------------------------------------------------------

def _emendas(con: sqlite3.Connection, mapa: MapaLegal, ate: date, out: ConferenciasFederais) -> None:
    if _vazia(con, "transferegov_planos_especiais"):
        return
    try:
        minimo = float(mapa.regra("EMENDA-CAPITAL").valor)
        norma_regra = mapa.regra("EMENDA-CAPITAL").norma
    except KeyError:
        minimo, norma_regra = LIMIARES["capital_minimo_emenda"]["valor"], "CF, art. 166-A, § 5º"
    por_ano: dict[int, list[tuple]] = {}
    for linha in con.execute(
            "select id_plano, codigo, ano, situacao, beneficiario, parlamentar, emenda, custeio, investimento, "
            "total from transferegov_planos_especiais where total > 0 order by ano, codigo"):
        ident, codigo, ano, situacao, benef, parl, emenda, custeio, invest, total = linha
        if ano is None or ano > ate.year:
            continue
        por_ano.setdefault(ano, []).append(linha)
        pct = 100.0 * (invest or 0.0) / total
        if pct + 1e-9 < minimo:
            out.alertas.append(Alerta(
                "emenda_capital_plano", f"PLANO-{codigo or ident}", f"{ano}-12",
                f"o plano de ação {codigo or ident} de {ano} ({emenda or 'emenda sem número'}, "
                f"{parl or 'parlamentar não informado'}) destina {_moeda(invest)} a investimento e "
                f"{_moeda(custeio)} a custeio: {pct:.1f}% em capital, abaixo dos {minimo:.0f}% exigidos",
                gravidade="alta", valor=round(total * minimo / 100 - (invest or 0.0), 2), limite=minimo,
                orgao=benef or "Município", dados={"situacao": situacao, "norma": norma_regra}))
    for ano, planos in sorted(por_ano.items()):
        total = sum(p[9] for p in planos)
        invest = sum(p[8] or 0.0 for p in planos)
        pct = 100.0 * invest / total
        cert = _selar([Via("Transferegov, planos de ação das transferências especiais", round(total, 2), Nivel.C)])
        out.conferencias.append(ConferenciaFederal(
            f"Emendas especiais de {ano}: {pct:.1f}% em capital", cert,
            f"{len(planos)} planos de ação, {_moeda(invest)} em investimento de {_moeda(total)}",
            norma=norma_regra))
        if pct + 1e-9 < minimo:
            out.alertas.append(Alerta(
                "emenda_capital_ano", f"EMENDAS-{ano}", f"{ano}-12",
                f"os {len(planos)} planos de ação de {ano} somam {_moeda(total)}, dos quais {_moeda(invest)} em "
                f"investimento: {pct:.1f}% em capital, abaixo dos {minimo:.0f}% exigidos",
                gravidade="alta", valor=round(total * minimo / 100 - invest, 2), limite=minimo, orgao="Município"))


# --- Contratada sancionada -----------------------------------------------------------------------

def _data(t: str | None) -> date | None:
    try:
        return date.fromisoformat(str(t)[:10]) if t else None
    except ValueError:
        return None


def _br(t: str | None, vazio: str) -> str:
    d = _data(t)
    return d.strftime("%d/%m/%Y") if d else vazio


def _contratadas_sancionadas(con: sqlite3.Connection, ate: date, out: ConferenciasFederais) -> None:
    if _vazia(con, "sancoes") or _vazia(con, "contratos_pncp"):
        return
    por_raiz: dict[str, list[dict]] = {}
    colunas = [c[1] for c in con.execute("pragma table_info(sancoes)")]
    for linha in con.execute("select * from sancoes where length(cnpj_cpf) = 14"):
        s = dict(zip(colunas, linha))
        por_raiz.setdefault(s["cnpj_cpf"][:8], []).append(s)
    detalhe = _tabela(con, "pncp_contratos_detalhe")
    sql = ("select c.pncp_id, c.mes, c.data_assinatura, c.orgao, c.fornecedor_ni, c.fornecedor, c.objeto, "
           "c.valor_global" + (", d.vigencia_inicio, d.vigencia_fim from contratos_pncp c left join "
                               "pncp_contratos_detalhe d on d.contrato_id = c.pncp_id" if detalhe else
                               ", null, null from contratos_pncp c"))
    presumida = int(LIMIARES["vigencia_presumida_dias"]["valor"])
    conferidos = 0
    for pid, mes, assinatura, orgao, ni, nome, objeto, valor, vig_ini, vig_fim in con.execute(sql):
        ni = digitos(ni)
        if len(ni) != 14:
            continue
        conferidos += 1
        candidatas = por_raiz.get(ni[:8])
        if not candidatas:
            continue
        assinado = _data(assinatura) or _data(vig_ini)
        inicio = _data(vig_ini) or assinado
        if inicio is None:
            continue
        fim = _data(vig_fim)
        presumido = fim is None
        fim = fim or inicio + timedelta(days=presumida)
        for s in candidatas:
            s_ini = _data(s["inicio"]) or date.min
            s_fim = _data(s["fim"]) or date.max
            if s_ini > fim or s_fim < inicio:
                continue
            alcance = sc.alcanca_o_municipio(s)
            impede = sc.impede_contratar(s["tipo"])
            na_assinatura = assinado is not None and s_ini <= assinado <= s_fim
            grave = impede and alcance in ("todos", "municipio") and na_assinatura
            exato = s["cnpj_cpf"] == ni
            out.alertas.append(Alerta(
                "contratada_sancionada", f"{pid}-{s['cadastro']}-{s.get('codigo') or s['inicio']}",
                mes or (assinatura or "")[:7],
                f"o contrato {pid} ({(objeto or '')[:120]}), de {_moeda(valor)}, com {nome} (CNPJ {ni}), vigente de "
                f"{inicio:%d/%m/%Y} a {fim:%d/%m/%Y}{' (vigência presumida)' if presumido else ''}, cruza a sanção "
                f"do {s['cadastro']} \"{s['tipo']}\" aplicada por {s['orgao'] or 'órgão não informado'} "
                f"({s['esfera'] or 'esfera não informada'}/{s['uf_orgao'] or '-'}), vigente de "
                f"{_br(s['inicio'], 'data não informada')} a {_br(s['fim'], 'prazo indeterminado')}"
                + ("" if exato else f", lançada no CNPJ {s['cnpj_cpf']} da mesma empresa (mesma raiz)")
                + (". O contrato foi assinado durante a sanção" if na_assinatura else "")
                + ("" if impede else ". A categoria não impede contratar, mas mostra a empresa sancionada")
                + (". A sanção foi aplicada por outro ente; o alcance dela sobre o Município precisa ser conferido"
                   if alcance == "outro_ente" else ""),
                gravidade="alta" if grave else "media", valor=float(valor or 0.0), orgao=orgao or "",
                dados={"sancao": {k: s[k] for k in ("cadastro", "tipo", "inicio", "fim", "orgao")},
                       "exato": exato, "na_assinatura": na_assinatura, "alcance": alcance}))
    out.cobertura["contratos_conferidos_com_sancoes"] = conferidos


# --- Cota estadual: Estado x Município -----------------------------------------------------------

# As três cotas estaduais do rio do Município (rio.municipio.CORRENTES, esfera estadual).
NATUREZAS_ESTADUAIS = {"ICMS": mz.Natureza(("172150",)), "IPVA": mz.Natureza(("172151",)),
                       "IPI": mz.Natureza(("172152",))}
NOME_COTA = {"ICMS": "ICMS", "IPVA": "IPVA", "IPI": "IPI-exportação"}


def _cota_estadual(con: sqlite3.Connection, ate: date, out: ConferenciasFederais) -> None:
    entregues = sorted(mz.meses_entregues(con))
    anos = sorted({int(m[:4]) for m in entregues if int(m[:4]) <= ate.year})
    situacoes = {}
    if _tabela(con, "fontes_federais"):
        situacoes = dict(con.execute("select alvo, situacao from fontes_federais where motor='economia_go'"))
    tem_estado = not _vazia(con, "repasses_estado")
    retencao = LIMIARES["cota_estadual_retencao_fundeb"]["valor"]
    for ano in anos:
        meses = [m for m in entregues if m.startswith(str(ano)) and m <= ate.strftime("%Y-%m")]
        if not meses:
            continue
        estado_ano = {}
        if tem_estado:
            marcas = ",".join("?" for _ in meses)
            for mes, trib, v in con.execute(
                    f"select mes, tributo, valor from repasses_estado where mes in ({marcas})", meses):
                estado_ano.setdefault(trib, {})[mes] = v
        if not estado_ano:
            # Só depois que o motor tentou todos os candidatos a falta é do Estado; falha de rede, formato
            # ou motor ainda não rodado ficam na cobertura, como falha do sistema.
            if situacoes.get(str(ano)) == "nao_publicado":
                out.ausencias.append(Ausencia(
                    o_que_falta="Valores da cota-parte do ICMS, do IPVA e do IPI-exportação entregues ao Município de Goiânia, "
                                "mês a mês, com os montantes arrecadados e os critérios de rateio",
                    conferencia_impedida="as cotas estaduais declaradas pelo Estado contra o que o Município "
                                         "registrou no RREO e na matriz de saldos contábeis",
                    onde_deveria_estar="portal de transparência da Secretaria de Estado da Economia de Goiás, "
                                       "em formato aberto, até o último dia do mês seguinte ao da arrecadação",
                    fundamento=economia_go.FUNDAMENTO, periodo=str(ano), orgao=economia_go.ORGAO,
                    bloco="Fontes e cadência"))
            for trib, nat in NATUREZAS_ESTADUAIS.items():
                mun = sum(mz.receita(con, nat, meses).values())
                out.conferencias.append(ConferenciaFederal(
                    f"Cota-parte do {NOME_COTA[trib]} de {ano}", _selar([
                        Via("Estado de Goiás (Secretaria da Economia)", None),
                        Via("Matriz de saldos contábeis (o que o Município registrou)", round(mun, 2), Nivel.B)]),
                    f"{meses[0]} a {meses[-1]}; a via do Estado não foi publicada",
                    norma="CF, arts. 158, III e IV, e 162"))
            continue
        for trib, nat in NATUREZAS_ESTADUAIS.items():
            por_mes_mun = mz.receita(con, nat, meses)
            por_mes_est = estado_ano.get(trib, {})
            comuns = [m for m in meses if m in por_mes_est]
            if not comuns:
                continue
            est = sum(por_mes_est[m] for m in comuns)
            mun = sum(por_mes_mun.get(m, 0.0) for m in comuns)
            liquida = mun and abs(est - retencao * mun) < abs(est - mun)
            est_bruto = est / retencao if liquida else est
            cert = _selar([Via("Estado de Goiás (Secretaria da Economia)", round(est_bruto, 2), Nivel.A),
                           Via("Matriz de saldos contábeis (o que o Município registrou)", round(mun, 2), Nivel.B)])
            detalhe = []
            for m in comuns:
                e = por_mes_est[m] / retencao if liquida else por_mes_est[m]
                r = por_mes_mun.get(m, 0.0)
                if _difere(e, r):
                    detalhe.append(f"{m}: Estado {_moeda(e)}, Município {_moeda(r)} (diferença {_moeda(e - r)}).")
            ref = f"{comuns[0]} a {comuns[-1]}" + ("; o Estado publica o líquido da retenção do FUNDEB, "
                                                   "dividido por 0,8" if liquida else "")
            out.conferencias.append(ConferenciaFederal(f"Cota-parte do {NOME_COTA[trib]} de {ano}", cert, ref, detalhe,
                                                       "CF, arts. 158, III e IV, e 162"))
            if cert.divergencia or detalhe:
                out.alertas.append(Alerta(
                    "cota_estadual_divergencia", f"{trib}-{ano}", comuns[-1],
                    f"{NOME_COTA[trib]} de {ref}: o Estado declara {_moeda(est_bruto)} e o Município registrou {_moeda(mun)} "
                    f"(diferença {_moeda(est_bruto - mun)}). " + " ".join(detalhe),
                    gravidade="alta", valor=round(abs(est_bruto - mun), 2), orgao="Secretaria Municipal de Finanças"))


# --- Decisões do TCU e do TCM-GO ----------------------------------------------------------------

def _decisoes(con: sqlite3.Connection, ate: date, desde: str | None, out: ConferenciasFederais) -> None:
    if _vazia(con, "decisoes_controle"):
        return
    for trib, chave, numero, ano, data_dec, tipo, titulo, sumario, url, processo in con.execute(
            "select tribunal, chave, numero, ano, data, tipo, titulo, sumario, url, processo from decisoes_controle "
            "where sobre_goiania = 1 order by tribunal, ano, numero"):
        mes = (data_dec or "")[:7] or (f"{ano}-12" if ano else "")
        if not mes or mes > ate.strftime("%Y-%m") or (desde and mes < desde):
            continue
        texto = norm(f"{titulo} {sumario}")
        termos = [t for t in TERMOS_DE_ALERTA if t in texto]
        if not termos:
            continue
        familia = ("CTA" if any(t in texto for t in ("PARECER PREVIO", "CONTAS DE GOVERNO", "CONTAS ANUAIS"))
                   else "PRC" if any(t in texto for t in ("LICITA", "CONTRAT", "PREGAO", "OBRA"))
                   else "PCT")
        grave = any(t in termos for t in ("IRREGULAR", "DEBITO", "IMPUTA", "RESSARC", "DANO AO ERARIO",
                                           "SUPERFATUR", "SOBREPRECO", "REJEI", "DESFAVORAVE", "INIDONE"))
        out.alertas.append(Alerta(
            "decisao_controle", f"{trib}-{chave}", mes,
            f"{trib}, {titulo}{', processo ' + processo if processo else ''}: {(sumario or '')[:600]}",
            gravidade="alta" if grave else "media", orgao=trib,
            dados={"familia": familia, "termos": termos, "url": url}))


# --- Contas irregulares do TCM-GO ---------------------------------------------------------------

def _contas_irregulares(con: sqlite3.Connection, ate: date, out: ConferenciasFederais) -> None:
    """A lista do TCM-GO é um cadastro vigente: cada linha de Goiânia vira alerta no mês do julgamento,
    e o nome do responsável é procurado entre os sócios das contratadas."""
    if _vazia(con, "contas_irregulares_tcm"):
        return
    colunas = {c[1] for c in con.execute("PRAGMA table_info(contas_irregulares_tcm)")}
    extras = [c for c in ("cpf_parcial", "assunto", "decisao", "data_julgamento", "tipo_lista", "url_processo")
              if c in colunas]
    sel = ", ".join(["lista", "municipio", "entidade", "responsavel", "processo", "exercicio", "transito", "url"]
                    + extras)
    por_nome: dict[str, list[dict]] = {}
    for linha in con.execute(f"select {sel} from contas_irregulares_tcm order by responsavel, processo"):
        r = dict(zip(sel.split(", "), linha, strict=True))
        mes = (r.get("data_julgamento") or r.get("transito") or "")[:7]
        if not re.fullmatch(r"\d{4}-\d{2}", mes) or mes > ate.strftime("%Y-%m"):
            continue
        nome = (r.get("responsavel") or "").strip()
        debito = "DEBITO" in norm(r.get("tipo_lista") or r.get("lista") or "")
        quando = _br(r.get("data_julgamento"), "data não informada")
        out.alertas.append(Alerta(
            "contas_irregulares_tcm", f"TCMGO-{r.get('processo') or ''}-{norm(nome)[:40]}", mes,
            f"{nome or 'responsável não informado'} ({r.get('entidade') or 'órgão não informado'}) está na lista do "
            f"TCM-GO de contas julgadas irregulares: {r.get('assunto') or 'assunto não informado'}, exercício "
            f"{r.get('exercicio') or 'não informado'}, processo {r.get('processo') or 'não informado'}, "
            f"{r.get('decisao') or 'decisão não informada'} julgada em {quando}"
            + (f", trânsito em julgado em {_br(r.get('transito'), '')}" if r.get("transito") else "")
            + (f" ({r['tipo_lista']})" if r.get("tipo_lista") else ""),
            gravidade="alta" if debito else "media", orgao="TCM-GO",
            dados={"url": r.get("url_processo") or r.get("url"), "entidade": r.get("entidade"),
                   "cpf_parcial": r.get("cpf_parcial")}))
        if len(norm(nome).split()) >= 2:
            por_nome.setdefault(norm(nome), []).append({**r, "mes": mes})
    if not por_nome or _vazia(con, "cnpj_socios"):
        return
    razoes = (dict(con.execute("select cnpj, razao from cnpj_empresas")) if _tabela(con, "cnpj_empresas") else {})
    vistos: set[tuple[str, str]] = set()
    for cnpj, socio, qualificacao in con.execute("select cnpj, nome, qualificacao from cnpj_socios order by cnpj, nome"):
        chave_nome = norm(socio)
        if chave_nome not in por_nome or (cnpj, chave_nome) in vistos:
            continue
        vistos.add((cnpj, chave_nome))
        contas = por_nome[chave_nome]
        processos = ", ".join(sorted({c.get("processo") or "?" for c in contas}))
        out.alertas.append(Alerta(
            "socio_com_contas_irregulares", f"{digitos(cnpj)}-{chave_nome[:40]}", max(c["mes"] for c in contas),
            f"{socio} ({qualificacao or 'qualificação não informada'}) é sócio de {razoes.get(cnpj) or 'contratada'} "
            f"(CNPJ {cnpj}) e tem o mesmo nome de um responsável com contas julgadas irregulares no TCM-GO "
            f"(processo {processos}). Pode ser homônimo: o TCM-GO mostra só os dois primeiros dígitos do CPF e a "
            "Receita só os do meio, então os documentos não se cruzam",
            gravidade="media", orgao="TCM-GO",
            dados={"cnpj": cnpj, "processos": processos, "possivel_homonimo": True}))


# --- Cobertura ----------------------------------------------------------------------------------

def _cobertura(con: sqlite3.Connection, out: ConferenciasFederais) -> None:
    problemas: dict[str, str] = {}
    situacoes: dict[str, list[tuple]] = {}
    if _tabela(con, "fontes_federais"):
        for motor, alvo, sit, erro in con.execute("select motor, alvo, situacao, erro from fontes_federais"):
            situacoes.setdefault(motor, []).append((alvo, sit, erro))
    for motor in NOMES_DAS_FONTES:
        linhas = situacoes.get(motor)
        if not linhas:
            problemas[motor] = "a fonte nunca foi lida pela coleta histórica"
            continue
        ruins = [(a, s, e) for a, s, e in linhas if s in ("falha", "formato")
                 or (s == "nao_publicado" and motor != "economia_go")]
        if ruins:
            problemas[motor] = "; ".join(f"{a}: {s}" + (f" ({e[:160]})" if e else "") for a, s, e in ruins)
    out.cobertura["fontes"] = {m: [{"alvo": a, "situacao": s} for a, s, _ in v] for m, v in situacoes.items()}
    out.cobertura["problemas"] = problemas


# --- Entrada ------------------------------------------------------------------------------------

def conferir(banco: Path | str | sqlite3.Connection, *, ate: date | None = None, desde: str | None = None,
             mapa: MapaLegal | None = None) -> ConferenciasFederais:
    """Roda todas as conferências do bloco 5 no banco histórico, até a data ``ate``."""
    mapa = mapa or carregar()
    ate = ate or date.today()
    con = banco if isinstance(banco, sqlite3.Connection) else sqlite3.connect(f"file:{banco}?mode=ro", uri=True)
    try:
        out = ConferenciasFederais()
        _fns_x_siafi_x_rreo(con, ate, out)
        _fnde_x_siafi(con, ate, out)
        _emendas(con, mapa, ate, out)
        _contratadas_sancionadas(con, ate, out)
        _cota_estadual(con, ate, out)
        _decisoes(con, ate, desde, out)
        _contas_irregulares(con, ate, out)
        _cobertura(con, out)
        out.alertas.sort(key=lambda a: (a.mes, a.tipo, a.chave))
        return out
    finally:
        if not isinstance(banco, sqlite3.Connection):
            con.close()


# --- Fichas -------------------------------------------------------------------------------------

_BASE = {
    "fns_divergencia": dict(
        familia=Familia.RIO, norma="LC 141/2012, arts. 13, 17 e 18; Lei 4.320/1964, art. 35",
        como_deveria="O que o FNS paga ao Fundo Municipal de Saúde, o que o SIAFI mostra e o que o Município "
                     "declara recebido da União no RREO são o mesmo dinheiro e fecham entre si.",
        niveis=[Nivel.A, Nivel.B],
        providencia="Pedir ao Fundo Municipal de Saúde o extrato das contas do bloco de financiamento e a "
                    "conciliação dos repasses do FNS com a receita registrada."),
    "fnde_divergencia": dict(
        familia=Familia.RIO, norma="Lei 11.947/2009; CF, art. 212, § 6º; Lei 4.320/1964, art. 35",
        como_deveria="O que o FNDE libera a cada programa é o que o SIAFI registra como transferido.",
        niveis=[Nivel.A, Nivel.B],
        providencia="Pedir à Secretaria Municipal de Educação os extratos das contas de cada programa do FNDE "
                    "e a conciliação com as liberações."),
    "emenda_capital_plano": dict(
        familia=Familia.PISO, norma="CF, art. 166-A, § 5º",
        como_deveria="Pelo menos 70% de cada transferência especial vai para despesa de capital (investimento).",
        niveis=[Nivel.C],
        providencia="Pedir o plano de ação, as notas de empenho por natureza da despesa e a justificativa do custeio."),
    "emenda_capital_ano": dict(
        familia=Familia.PISO, norma="CF, art. 166-A, § 5º",
        como_deveria="Pelo menos 70% das transferências especiais do ano vão para despesa de capital.",
        niveis=[Nivel.C],
        providencia="Pedir a execução de cada transferência especial por natureza da despesa."),
    "contratada_sancionada": dict(
        familia=Familia.PRC, norma="Lei 14.133/2021, arts. 14, III, 91, § 4º, e 156; Lei 12.846/2013, art. 22",
        como_deveria="Antes de contratar e durante o contrato, a Administração consulta o CEIS e o CNEP; empresa "
                     "impedida, suspensa ou inidônea não contrata enquanto durar a sanção.",
        niveis=[Nivel.C, Nivel.B],
        providencia="Pedir a consulta ao CEIS e ao CNEP feita antes da assinatura e as medidas tomadas depois "
                    "da sanção (rescisão, substituição, justificativa do alcance)."),
    "cota_estadual_divergencia": dict(
        familia=Familia.RIO, norma="CF, arts. 158, III e IV, e 162; LC 63/1990",
        como_deveria="O que o Estado diz ter entregue ao Município de ICMS e IPVA é o que o Município registra.",
        niveis=[Nivel.A, Nivel.B],
        providencia="Pedir à Secretaria Municipal de Finanças a conciliação da cota-parte com os créditos "
                    "do Estado, mês a mês."),
    "contas_irregulares_tcm": dict(
        familia=Familia.PCT, norma="CF, arts. 71, II, e 75; Lei Orgânica do TCM-GO (Lei estadual 15.958/2007); "
                                   "LC 64/1990, art. 1º, I, g",
        como_deveria="Quem gere dinheiro do Município presta contas regulares; julgadas irregulares, o débito e a "
                     "multa são cobrados e a decisão é cumprida.",
        niveis=[Nivel.C, Nivel.E],
        providencia="Pedir ao órgão a prova do cumprimento do acórdão (recolhimento do débito ou da multa, "
                    "inscrição em dívida ativa, ação de cobrança) e se o responsável ainda ocupa cargo ou função."),
    "socio_com_contas_irregulares": dict(
        familia=Familia.PRC, norma="Lei 14.133/2021, arts. 9º, 14 e 156; CF, art. 37, caput",
        como_deveria="A Administração confere quem está por trás da contratada; um responsável condenado pelo "
                     "tribunal de contas não volta ao dinheiro público por uma empresa.",
        niveis=[Nivel.C],
        providencia="Confirmar a identidade (CPF completo do sócio no contrato social e do responsável no "
                    "processo do TCM-GO) antes de qualquer conclusão; sendo a mesma pessoa, pedir a análise de "
                    "vínculo feita na contratação."),
}


def ficha(a: Alerta, competencia: str | None = None) -> Ficha:
    if a.tipo == "decisao_controle":
        base = dict(familia=Familia(a.dados.get("familia", "PCT")),
                    norma="CF, arts. 71 e 75; Lei Orgânica do TCM-GO (Lei estadual 15.958/2007)",
                    como_deveria="O Município cumpre as decisões dos tribunais de contas e corrige o que eles apontam.",
                    niveis=[Nivel.C, Nivel.E],
                    providencia="Pedir ao órgão o cumprimento da decisão (recolhimento, correção, plano de ação) e "
                                "acompanhar o processo no tribunal.")
    else:
        base = _BASE[a.tipo]
    sufixo = re.sub(r"[^A-Za-z0-9/._-]+", "-", a.chave)[:80]
    codigo = {"fns_divergencia": "RIO-FNS01", "fnde_divergencia": "RIO-FNDE01", "emenda_capital_plano": "PISO-EMD01",
              "emenda_capital_ano": "PISO-EMD02", "contratada_sancionada": "PRC-SANC01",
              "cota_estadual_divergencia": "RIO-COTA01", "decisao_controle": "CTA-TC01",
              "contas_irregulares_tcm": "PCT-TC02", "socio_com_contas_irregulares": "PRC-TCM01"}[a.tipo]
    titulo = TITULOS[a.tipo] + (f": {a.orgao.title()}" if a.orgao else "")
    return emitir(codigo=f"{codigo}-{sufixo}", titulo=titulo, gravidade=a.gravidade,
                  como_esta=a.descricao[:1].upper() + a.descricao[1:] + ("" if a.descricao.endswith(".") else "."),
                  competencia=competencia, observacao="Alerta é indício, não acusação.", **base)
