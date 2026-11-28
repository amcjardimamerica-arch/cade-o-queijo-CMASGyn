"""Contrato, entrega e prestação de contas (famílias PRC, ENT e PCT).

Para o mesmo empenho juntam-se quanto se pagou, o que se recebeu e o que se
prestou em contas: três pontas de um triângulo que precisa fechar.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable

from .. import partes as _partes
from ..legal.mapa import MapaLegal, carregar
from ..nucleo.indicios import Familia, Ficha, emitir
from ..nucleo.provas import Nivel


# --- Aditivo acima do limite (Lei 14.133/2021, art. 125) --------------------

def excesso_de_aditivos(valor_original: float, aditivos: Iterable[float], *,
                        mapa: MapaLegal | None = None) -> float | None:
    """Percentual de acréscimo acima do limite legal, ou ``None`` se cabe no limite."""
    limite = (mapa or carregar()).regra("ADITIVO-LIMITE").valor or 25.0
    if valor_original <= 0:
        return None
    acrescimo = sum(a for a in aditivos if a > 0) / valor_original * 100.0
    return round(acrescimo, 2) if acrescimo > limite else None


def ficha_de_aditivo(contrato: str, valor_original: float, acrescimo_pct: float) -> Ficha:
    return emitir(
        codigo=f"PRC-SOB04-{contrato}",
        familia=Familia.PRC,
        titulo=f"Aditivos do contrato {contrato} passam do limite legal",
        gravidade="alta",
        como_deveria="Os acréscimos não podem passar de 25% do valor inicial atualizado.",
        norma="Lei 14.133/2021, art. 125",
        como_esta=f"Valor original {valor_original:,.2f}; acréscimos somam {acrescimo_pct:.2f}%.",
        niveis=[Nivel.C, Nivel.B],
        providencia="Pedir os termos aditivos e as justificativas técnicas.",
    )


# --- Fracionamento (Lei 14.133/2021, art. 75, § 1º) --------------------------

@dataclass(frozen=True)
class Compra:
    objeto: str
    valor: float
    data: date
    obra_ou_engenharia: bool = False
    por_dispensa: bool = True


def fracionamentos(compras: Iterable[Compra], *, mapa: MapaLegal | None = None) -> list[dict]:
    """Soma, por objeto e exercício, as dispensas que juntas passam do limite."""
    regra = (mapa or carregar()).regra("DISPENSA-LIMITE")
    grupos: dict[tuple, list[Compra]] = defaultdict(list)
    for c in compras:
        if c.por_dispensa:
            grupos[(c.objeto.strip().lower(), c.data.year, c.obra_ou_engenharia)].append(c)
    achados = []
    for (objeto, ano, obra), itens in grupos.items():
        limite = float(regra.get("obras" if obra else "outros"))
        soma = sum(c.valor for c in itens)
        if len(itens) > 1 and soma > limite:
            achados.append({"objeto": objeto, "ano": ano, "soma": round(soma, 2),
                            "limite": limite, "compras": len(itens),
                            "limite_vigencia": regra.get("vigencia")})
    return achados


# --- Entrega: liquidado contra contratado, medições ----------------------------

def liquidado_acima_do_contratado(contratado: float, liquidacoes: Iterable[float],
                                  tolerancia: float = 0.005) -> float | None:
    excesso = sum(liquidacoes) - contratado
    return round(excesso, 2) if excesso > tolerancia else None


def medicoes_repetidas(medicoes: Iterable[float], vezes: int = 3, tolerancia: float = 0.0) -> bool:
    """Medições idênticas mês a mês (``vezes`` seguidas) são sinal de medição não medida.

    ``tolerancia`` é a diferença relativa que ainda conta como igual (0: ao centavo)."""
    seq = [round(float(v), 2) for v in medicoes]
    corrida = 1
    for a, b in zip(seq, seq[1:]):
        iguais = a > 0 and (a == b or (tolerancia > 0 and abs(a - b) <= tolerancia * max(a, b)))
        corrida = corrida + 1 if iguais else 1
        if corrida >= vezes:
            return True
    return False


def ficha_de_ordem(chave: str, problemas: list[str], competencia: str | None = None) -> Ficha:
    return emitir(
        codigo=f"ENT-ORDEM-{chave}",
        familia=Familia.ENT,
        titulo="Despesa fora da ordem legal",
        gravidade="alta",
        como_deveria="Empenho, liquidação e pagamento, nesta ordem; o pagamento só depois da "
                     "liquidação que comprova a entrega.",
        norma="Lei 4.320/1964, arts. 60, 62 e 63",
        como_esta="; ".join(problemas).capitalize() + ".",
        niveis=[Nivel.B, Nivel.A] if "antes" in " ".join(problemas) else [Nivel.B],
        documento_faltante="sem liquidação publicada" in " ".join(problemas),
        providencia="Pedir as notas de liquidação, as medições e os atestos do empenho.",
        competencia=competencia,
    )


# --- Prestação de contas das parcerias (Lei 13.019/2014) -----------------------

@dataclass(frozen=True)
class Parceria:
    instrumento: str
    entidade: str
    valor: float
    prestacao_publicada: bool = False
    prestacao_individualizada: bool = True
    saldo_nao_devolvido: float = 0.0
    prazo_vencido: bool = False


def fichas_de_prestacao(parcerias: Iterable[Parceria], competencia: str | None = None) -> list[Ficha]:
    fichas = []
    for p in parcerias:
        problemas = []
        if p.prazo_vencido and not p.prestacao_publicada:
            problemas.append("prestação de contas vencida e não publicada")
        if p.prestacao_publicada and not p.prestacao_individualizada:
            problemas.append("prestação coletiva ou genérica, sem individualizar a parceria")
        if p.saldo_nao_devolvido > 0:
            problemas.append(f"saldo de {p.saldo_nao_devolvido:,.2f} sem devolução")
        if not problemas:
            continue
        fichas.append(emitir(
            codigo=f"PCT-{p.instrumento}",
            familia=Familia.PCT,
            titulo=f"Prestação de contas de {p.entidade} com problema",
            gravidade="alta",
            como_deveria="Cada parceria presta contas no prazo, de forma individualizada, e devolve "
                         "o saldo.",
            norma="Lei 13.019/2014, arts. 52, 63 e 69",
            como_esta="; ".join(problemas).capitalize() + ".",
            niveis=[Nivel.C],
            documento_faltante=not p.prestacao_publicada,
            providencia="Pedir a prestação de contas e o parecer técnico da parceria.",
            competencia=competencia,
        ))
    return fichas


# =====================================================================================================
# A execução item a item conferida no banco (requisitos 30, 31, 32, 55, 56, 57, 63, 64 e 66)
# =====================================================================================================
#
# O coletor da execução (coletores/goiania_transweb.py) grava cada empenho, liquidação, ordem de
# pagamento e pagamento na tabela ``despesa_eventos``. Aqui cada empenho vira um percurso pelas nove
# estações, com o documento que acende cada uma:
#
# ========== ======================================================================== =====
# Estação    O que a acende                                                            Nível
# ========== ======================================================================== =====
# Origem     a fonte do empenho tem receita realizada no exercício (matriz de saldos)   B
# Fonte      a fonte do empenho existe no catálogo de destinações                       B
# Previsão   a função do empenho tem dotação no exercício (matriz de saldos)            D
# Dotação    a função tem dotação naquela fonte (matriz de saldos)                      D
# Empenho    a nota de empenho no portal                                                B
# Vínculo    contrato do credor publicado no PNCP                                       C
# Liquidação a liquidação no portal                                                     B
# Pagamento  o pagamento no portal (a ordem de pagamento, quando é o único ato)         B
# Prestação  o RREO do bimestre do pagamento entregue no SICONFI                        C
# ========== ======================================================================== =====
#
# A integridade da trilha é a fração do pago cujo percurso acende as nove. Os limiares de cada
# conferência ficam em ``config/limiares_execucao.yml`` (o mais exigente que os dados sustentam).
# Toda conferência que não fecha é indício, nunca acusação: a ficha diz o que pedir.

import sqlite3 as _sqlite3
from pathlib import Path as _Path

import yaml as _yaml

from .. import RAIZ as _RAIZ
from ..nucleo.estacoes import Estacao, Evento, Percurso, integridade_da_trilha
from ..rio.fontes import classificar as _classificar

LIMIARES = _RAIZ / "config" / "limiares_execucao.yml"


def carregar_limiares(caminho: _Path | str | None = None) -> dict[str, dict]:
    """{grupo: {nome: valor}} do arquivo versionado; cada valor tem justificativa e base lá."""
    bruto = _yaml.safe_load(_Path(caminho or LIMIARES).read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    for grupo, itens in bruto.items():
        if isinstance(itens, dict):
            out[grupo] = {nome: (v["valor"] if isinstance(v, dict) and "valor" in v else v)
                          for nome, v in itens.items()}
    return out


def limiares_sem_justificativa(caminho: _Path | str | None = None) -> list[str]:
    """Os limiares sem valor, justificativa ou base: o arquivo é a memória de cada número."""
    bruto = _yaml.safe_load(_Path(caminho or LIMIARES).read_text(encoding="utf-8"))
    faltam = []
    for grupo, itens in bruto.items():
        if not isinstance(itens, dict):
            continue
        for nome, v in itens.items():
            if not (isinstance(v, dict) and "valor" in v and str(v.get("justificativa", "")).strip()
                    and str(v.get("base", "")).strip()):
                faltam.append(f"{grupo}.{nome}")
    return faltam


@dataclass(frozen=True)
class EventoDespesa:
    tipo: str                 # empenho, liquidacao, ordem_pagamento, pagamento, anulacao
    empenho: str
    data: date | None
    orgao: str
    credor: str
    documento: str
    valor: float
    elemento: str = ""
    fonte: str = ""
    funcao: str = ""
    subfuncao: str = ""
    url: str = ""
    sha256: str = ""

    @property
    def chave(self) -> str:
        return f"{self.orgao}|{self.empenho}"


def _tem_tabela(con: _sqlite3.Connection, nome: str) -> bool:
    return _partes.tem_tabela(con, nome)


def ler_eventos(con: _sqlite3.Connection) -> list[EventoDespesa]:
    if not _tem_tabela(con, "despesa_eventos"):
        return []
    out = []
    for (tipo, emp, dia, orgao, credor, doc, valor, elem, fonte, funcao, sub, url, sha) in con.execute(
            "select tipo, empenho, data, orgao, credor, documento, valor, elemento, fonte, funcao, subfuncao, "
            "url, sha256 from despesa_eventos where tipo != 'falha_detalhe'"):
        try:
            d = date.fromisoformat(dia) if dia else None
        except ValueError:
            d = None
        out.append(EventoDespesa(tipo, emp or "", d, orgao or "", credor or "", doc or "", float(valor or 0.0),
                                 elem or "", fonte or "", (funcao or "").zfill(2) if funcao else "",
                                 (sub or "").zfill(3) if sub else "", url or "", sha or ""))
    return out


def _destinacao(fonte: str) -> str:
    """Os três dígitos da destinação (``1500`` e ``500`` são a mesma água)."""
    f = re.sub(r"\D", "", fonte or "")
    return f[-3:] if len(f) >= 3 else f


@dataclass
class Contrato:
    id: str
    orgao_cnpj: str
    orgao: str
    fornecedor: str
    valor: float              # o maior entre global, acumulado com aditivos e inicial
    assinatura: date | None


@dataclass
class ContextoTrilha:
    """O que os outros motores já guardaram e acende estações do percurso de um empenho."""

    receitas: set = field(default_factory=set)        # (ano, destinação) com receita realizada
    dotacoes: set = field(default_factory=set)        # (ano, função) com dotação
    dotacoes_fonte: set = field(default_factory=set)  # (ano, função, destinação) com dotação
    contratos: dict = field(default_factory=dict)     # documento do fornecedor -> [Contrato]
    # Pessoa física: os seis dígitos do meio do CPF e o nome -> [Contrato]. O CPF é gravado mascarado
    # (***.NNN.NNN-**), então o cruzamento com o PNCP casa como o QSA da Receita: miolo e nome.
    contratos_pf: dict = field(default_factory=dict)
    rreo: set = field(default_factory=set)            # (ano, bimestre) entregues
    # Nome do órgão normalizado -> CNPJs dele no PNCP: o portal publica o órgão só pelo nome.
    orgaos_pncp: dict = field(default_factory=dict)
    _cnpj_de: dict = field(default_factory=dict, repr=False)   # nome do órgão do portal -> CNPJ (memória)

    def cnpj(self, orgao: str) -> str:
        if orgao not in self._cnpj_de:
            self._cnpj_de[orgao] = cnpj_do_orgao(orgao, self.orgaos_pncp) if self.orgaos_pncp else ""
        return self._cnpj_de[orgao]


def chave_orgao(nome) -> str:
    """O nome do órgão sem acento, espaço e pontuação: o portal quebra nomes longos com espaço no meio
    ("SERVIDO RES") e o PNCP acrescenta a sigla no fim ("... DE GOIANIA - IMAS")."""
    t = unicodedata.normalize("NFKD", str(nome or "")).encode("ascii", "ignore").decode().upper()
    return re.sub(r"[^A-Z0-9]", "", t)


def cnpj_do_orgao(nome: str, orgaos: dict) -> str:
    """O CNPJ do órgão do portal pelo nome no PNCP: igual, ou um começo do outro; vazio quando não há
    um só CNPJ (no banco de 28/11/2026, a Educação do portal paga pelo fundo, que tem outro nome no PNCP)."""
    k = chave_orgao(nome)
    if not k:
        return ""
    achados = set(orgaos.get(k, set()))
    if not achados:
        for kk, cnpjs in orgaos.items():
            if kk and (kk.startswith(k) or k.startswith(kk)):
                achados |= set(cnpjs)
    return next(iter(achados)) if len(achados) == 1 else ""


def orgaos_do_pncp(con: _sqlite3.Connection) -> dict[str, set[str]]:
    """Nome normalizado -> CNPJs dos órgãos do Município no PNCP (contratos e contratações)."""
    out: dict[str, set[str]] = defaultdict(set)
    for tabela in ("contratos_pncp", "contratacoes_pncp"):
        if _tem_tabela(con, tabela):
            for cnpj, nome in con.execute(f"select distinct orgao_cnpj, orgao from {tabela}"):
                if cnpj and nome:
                    out[chave_orgao(nome)].add(str(cnpj))
    return dict(out)


def _nome(texto: str) -> str:
    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t).strip().upper()


def chave_pf(documento: str, nome: str) -> tuple[str, str] | None:
    """Pessoa física: (os seis dígitos do meio do CPF, o nome). Vale para o CPF inteiro (11 dígitos) e
    para o mascarado (***.NNN.NNN-**); CNPJ e documento sem os seis dígitos não têm chave."""
    bruto = str(documento or "")
    d = re.sub(r"\D", "", bruto)
    if "*" in bruto and len(d) == 6:
        miolo = d
    elif len(d) == 11 and "*" not in bruto:
        miolo = d[3:9]
    else:
        return None
    n = _nome(nome)
    return (miolo, n) if n else None


def contratos_do_credor(ctx: ContextoTrilha, documento: str, credor: str = "") -> list:
    """Os contratos do PNCP do credor: pelo CNPJ (ou CPF inteiro) ou, para a pessoa física com o CPF
    mascarado, pelos seis dígitos do meio e o nome, como o QSA."""
    doc = re.sub(r"\D", "", documento or "")
    if "*" not in str(documento or "") and len(doc) >= 11 and ctx.contratos.get(doc):
        return ctx.contratos[doc]
    pf = chave_pf(documento, credor)
    return ctx.contratos_pf.get(pf, []) if pf else []


def contratos_do_orgao(ctx: ContextoTrilha, documento: str, credor: str, orgao: str) -> list:
    """Os contratos do credor publicados pelo órgão do empenho, quando o nome do órgão do portal casa com
    um CNPJ do PNCP; sem esse casamento (a Educação do portal, que paga pelo fundo), os do credor em
    qualquer órgão. Até 28/11/2026 valia sempre qualquer órgão: um empenho da Finanças acendia o vínculo
    com um contrato da Saúde do mesmo credor."""
    contratos = contratos_do_credor(ctx, documento, credor)
    cnpj = ctx.cnpj(orgao) if contratos else ""
    return [c for c in contratos if getattr(c, "orgao_cnpj", "") == cnpj] if cnpj else contratos


def cruzavel(documento: str, credor: str = "") -> bool:
    """O documento se cruza com o PNCP: CNPJ, CPF inteiro, ou CPF mascarado com nome."""
    doc = re.sub(r"\D", "", documento or "")
    return ("*" not in str(documento or "") and len(doc) >= 11) or chave_pf(documento, credor) is not None


def chave_do_credor(documento: str, credor: str = "") -> str:
    """O credor para agrupar: o documento; o CPF mascarado com o nome, porque os seis do meio não
    bastam para separar duas pessoas."""
    return f"{documento}|{_nome(credor)}" if "*" in str(documento or "") else documento


def contexto_do_banco(con: _sqlite3.Connection) -> ContextoTrilha:
    ctx = ContextoTrilha()
    soma = "sum(case when natureza_conta = 'C' then valor else -valor end)"
    if _tem_tabela(con, "msc_itens"):
        for mes, fonte, v in con.execute(
                f"select substr(mes, 1, 4), fonte_recursos, {soma} from msc_itens where conta_contabil like '6212%' "
                "group by 1, 2"):
            if (v or 0) > 0:
                ctx.receitas.add((int(mes), _destinacao(str(fonte))))
        for mes, funcao, fonte, v in con.execute(
                f"select substr(mes, 1, 4), funcao, fonte_recursos, {soma} from msc_itens where conta_contabil like "
                "'6221%' group by 1, 2, 3"):
            if (v or 0) > 0 and funcao:
                ctx.dotacoes.add((int(mes), str(funcao).zfill(2)))
                ctx.dotacoes_fonte.add((int(mes), str(funcao).zfill(2), _destinacao(str(fonte))))
    if _tem_tabela(con, "contratos_pncp"):
        detalhe = {}
        if _tem_tabela(con, "pncp_contratos_detalhe"):
            detalhe = {cid: (vi, vg, va) for cid, vi, vg, va in con.execute(
                "select contrato_id, valor_inicial, valor_global, valor_acumulado from pncp_contratos_detalhe")}
        for cid, cnpj, orgao, forn, valor, assinatura, nome in con.execute(
                "select pncp_id, orgao_cnpj, orgao, fornecedor_ni, valor_global, data_assinatura, fornecedor "
                "from contratos_pncp"):
            vi, vg, va = detalhe.get(cid, (None, None, None))
            contratado = max(float(x or 0.0) for x in (valor, vi, vg, va))
            try:
                d = date.fromisoformat(str(assinatura)[:10]) if assinatura else None
            except ValueError:
                d = None
            doc = re.sub(r"\D", "", forn or "")
            if doc:
                contrato = Contrato(cid, cnpj or "", orgao or "", doc, contratado, d)
                ctx.contratos.setdefault(doc, []).append(contrato)
                pf = chave_pf(forn, nome)
                if pf:
                    ctx.contratos_pf.setdefault(pf, []).append(contrato)
    ctx.orgaos_pncp = orgaos_do_pncp(con)
    if _tem_tabela(con, "siconfi_periodos"):
        for ex, per in con.execute("select exercicio, periodo from siconfi_periodos where demonstrativo = 'RREO' "
                                   "and situacao = 'entregue'"):
            ctx.rreo.add((int(ex), int(per)))
    return ctx


def _sem_contrato_por_natureza(elemento: str, excluidos: Iterable[str]) -> bool:
    """O elemento é de despesa cujo direito não nasce de contrato (pessoal, dívida, benefícios...)."""
    e = re.sub(r"\D", "", elemento or "")
    for x in excluidos:
        if e.startswith(re.sub(r"\D", "", str(x))):
            return True
    return False


def percursos(eventos: Iterable[EventoDespesa], ctx: ContextoTrilha) -> list[Percurso]:
    """Um percurso por empenho, com as estações que os documentos acendem."""
    grupos: dict[str, list[EventoDespesa]] = defaultdict(list)
    for e in eventos:
        if e.empenho:
            grupos[e.chave].append(e)
    out = []
    for chave, evs in sorted(grupos.items()):
        p = Percurso(chave)
        base = next((e for e in evs if e.tipo == "empenho"), evs[0])
        datas = [e.data for e in evs if e.data]
        ano = (base.data or (min(datas) if datas else date.today())).year
        fonte = next((e.fonte for e in evs if e.fonte), "")
        funcao = next((e.funcao for e in evs if e.funcao), "")
        dest = _destinacao(fonte)
        if fonte and (ano, dest) in ctx.receitas:
            p.eventos.append(Evento(Estacao.ORIGEM, Nivel.B, fonte_recurso=fonte))
        if fonte and _classificar(fonte if len(fonte) == 4 else "1" + dest).conhecida:
            p.eventos.append(Evento(Estacao.FONTE, Nivel.B, fonte_recurso=fonte))
        if funcao and (ano, funcao) in ctx.dotacoes:
            p.eventos.append(Evento(Estacao.PREVISAO, Nivel.D, funcao=funcao))
        if funcao and dest and (ano, funcao, dest) in ctx.dotacoes_fonte:
            p.eventos.append(Evento(Estacao.DOTACAO, Nivel.D, funcao=funcao, fonte_recurso=fonte))
        doc = base.documento
        if doc and contratos_do_orgao(ctx, doc, base.credor, base.orgao):
            p.eventos.append(Evento(Estacao.VINCULO, Nivel.C, credor=doc))
        tem_pagamento = any(e.tipo == "pagamento" for e in evs)
        for e in evs:
            estacao = {"empenho": Estacao.EMPENHO, "liquidacao": Estacao.LIQUIDACAO,
                       "pagamento": Estacao.PAGAMENTO}.get(e.tipo)
            if e.tipo == "ordem_pagamento" and not tem_pagamento:
                estacao = Estacao.PAGAMENTO   # a ordem publicada é o único ato de pagamento lido
            if estacao is not None and e.valor > 0:
                p.eventos.append(Evento(estacao, Nivel.B, e.valor, e.data, e.documento, e.fonte, e.funcao))
        pagos = [e.data for e in p.eventos if e.estacao is Estacao.PAGAMENTO and e.data]
        if pagos:
            ultimo = max(pagos)
            if (ultimo.year, (ultimo.month - 1) // 2 + 1) in ctx.rreo:
                p.eventos.append(Evento(Estacao.PRESTACAO, Nivel.C, data=ultimo))
        out.append(p)
    return out


TITULOS_EXECUCAO = {
    "ordem": "Despesa fora da ordem legal (pagamento antes ou sem liquidação)",
    "liquidado_acima": "Liquidado acima do contratado",
    "medicoes": "Medições repetidas",
    "concentracao_pago": "Pagamentos concentrados em poucos credores",
    "credor_unico": "Um credor com grande fatia do pago do órgão",
    "sem_contrato": "Credor recorrente sem contrato publicado",
    "fim_de_ano": "Empenhos concentrados no fim do ano",
    "fim_de_ano_funcao": "Empenho de dezembro acima do ritmo do ano na função",
}


@dataclass
class AchadoExecucao:
    tipo: str
    orgao: str
    chave: str
    mes: str
    descricao: str
    valor: float = 0.0
    limite: float = 0.0
    dados: dict = field(default_factory=dict)


@dataclass
class ConferenciasExecucao:
    achados: list[AchadoExecucao] = field(default_factory=list)
    cobertura: dict = field(default_factory=dict)
    percursos: list[Percurso] = field(default_factory=list)
    limiares: dict = field(default_factory=dict)

    @property
    def integridade(self) -> float | None:
        """Fração do pago que cruza as nove estações; None sem pagamento lido (não é zero do Município)."""
        if not any(p.valor_pago() > 0 for p in self.percursos):
            return None
        return integridade_da_trilha(self.percursos)

    def por_tipo(self) -> dict[str, int]:
        cont = defaultdict(int)
        for a in self.achados:
            cont[a.tipo] += 1
        return {t: cont.get(t, 0) for t in TITULOS_EXECUCAO}

    def da_competencia(self, competencia: str) -> list[AchadoExecucao]:
        ano = competencia[:4]
        return [a for a in self.achados if a.mes[:4] == ano and a.mes <= competencia]

    def fichas(self, competencia: str | None = None) -> list[Ficha]:
        lista = self.da_competencia(competencia) if competencia else self.achados
        return [ficha_execucao(a, competencia) for a in lista]

    def como_dict(self) -> dict:
        integ = self.integridade
        return {"por_tipo": self.por_tipo(), "cobertura": self.cobertura,
                "integridade_da_trilha": None if integ is None else round(integ, 4),
                "percursos": len(self.percursos),
                "completos": sum(1 for p in self.percursos if p.completo),
                "achados": [{"tipo": a.tipo, "orgao": a.orgao, "chave": a.chave, "mes": a.mes,
                             "descricao": a.descricao, "valor": a.valor, "limite": a.limite}
                            for a in self.achados]}


def _moeda(v: float) -> str:
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def conferir_execucao(banco: _Path | _sqlite3.Connection, *, mapa: MapaLegal | None = None,
                      limiares: dict | None = None) -> ConferenciasExecucao:
    """Roda as conferências da execução no banco: percursos, ordem, entrega, padrões de gasto."""
    lim = limiares or carregar_limiares()
    con = banco if isinstance(banco, _sqlite3.Connection) else _partes.conectar_leitura(banco)
    try:
        out = ConferenciasExecucao(limiares=lim)
        eventos = ler_eventos(con)
        ctx = contexto_do_banco(con)
        out.cobertura["eventos"] = len(eventos)
        out.cobertura["por_tipo"] = {t: sum(1 for e in eventos if e.tipo == t)
                                     for t in ("empenho", "liquidacao", "ordem_pagamento", "pagamento", "anulacao")}
        out.cobertura["contratos_no_banco"] = sum(len(v) for v in ctx.contratos.values())
        _fim_de_ano_na_matriz(con, out, lim["fim_de_ano"])
        meses_lidos = meses_lidos_do_portal(con)
        if not eventos:
            out.cobertura["sem_item_a_item"] = True
            return out
        out.percursos = percursos(eventos, ctx)
        _ordem(out)
        _liquidado_x_contratado(eventos, ctx, out, lim["liquidado_acima_do_contratado"])
        _medicoes(eventos, out, lim["medicoes_repetidas"])
        pagos = _pagamentos(eventos)
        _concentracao_do_pago(pagos, out, lim["concentracao"])
        _sem_contrato(pagos, ctx, out, lim["recorrente_sem_contrato"])
        _fim_de_ano_nos_empenhos(eventos, out, lim["fim_de_ano"], meses_lidos)
        out.achados.sort(key=lambda a: (a.mes, a.tipo, a.chave))
        return out
    finally:
        if not isinstance(banco, _sqlite3.Connection):
            con.close()


def meses_lidos_do_portal(con: _sqlite3.Connection) -> set[str] | None:
    """Os meses (AAAA-MM) que a coleta do portal leu inteiros (``despesa_consultas``, situação lida), ou
    None quando o banco não registra as consultas (um banco montado só com eventos)."""
    if not _tem_tabela(con, "despesa_consultas"):
        return None
    meses = {str(m)[:7] for (m,) in con.execute("select dia from despesa_consultas where situacao = 'lida'")
             if m and re.fullmatch(r"\d{4}-\d{2}", str(m)[:7])}
    return meses or None


def _mes(d: date | None) -> str:
    return f"{d.year:04d}-{d.month:02d}" if d else ""


def _ordem(out: ConferenciasExecucao) -> None:
    for p in out.percursos:
        problemas = p.ordem_violada()
        if problemas:
            datas = [e.data for e in p.eventos if e.estacao is Estacao.PAGAMENTO and e.data]
            orgao, _, emp = p.chave.partition("|")
            out.achados.append(AchadoExecucao(
                "ordem", orgao, p.chave, _mes(max(datas) if datas else None),
                f"empenho {emp}: " + "; ".join(problemas), p.valor_pago(), 0.0, {"problemas": problemas}))


def _pagamentos(eventos: list[EventoDespesa]) -> list[EventoDespesa]:
    """Os pagamentos; a ordem de pagamento conta como pagamento no empenho que não tem pagamento lido."""
    com_pagamento = {e.chave for e in eventos if e.tipo == "pagamento"}
    return [e for e in eventos if e.valor > 0 and (e.tipo == "pagamento" or
                                                   (e.tipo == "ordem_pagamento" and e.chave not in com_pagamento))]


def _liquidado_x_contratado(eventos, ctx: ContextoTrilha, out: ConferenciasExecucao, lim: dict) -> None:
    """Liquidado do credor no órgão contra os contratos do credor publicados pelo mesmo órgão no PNCP.

    O órgão do portal vem só pelo nome e casa com o CNPJ do PNCP pelo nome (``cnpj_do_orgao``). Até
    28/11/2026 a soma juntava as liquidações do credor em todos os órgãos e os contratos dele em qualquer
    órgão: no banco real, a energia paga pela Prefeitura inteira (1.142 liquidações da Equatorial) era
    comparada com o contrato de energia da Câmara Municipal (R$ 950 mil), outro Poder. A liquidação de um
    órgão sem CNPJ casado no PNCP fica fora e é contada na cobertura; a liquidação anterior ao primeiro
    contrato publicado do credor no órgão também fica fora, porque não pode ser dele."""
    liq: dict[tuple[str, str], list[EventoDespesa]] = defaultdict(list)
    sem_orgao = 0
    for e in eventos:
        if e.tipo != "liquidacao":
            continue
        contratos = contratos_do_credor(ctx, e.documento, e.credor)
        if not contratos:
            continue
        cnpj = ctx.cnpj(e.orgao)
        if not cnpj:
            sem_orgao += 1
            continue
        assinaturas = [c.assinatura for c in contratos if c.orgao_cnpj == cnpj]
        primeira = min((d for d in assinaturas if d), default=None)
        if assinaturas and not (primeira and e.data and e.data < primeira):
            liq[(chave_do_credor(e.documento, e.credor), cnpj)].append(e)
    out.cobertura["liquidacoes_de_orgao_sem_cnpj_no_pncp"] = sem_orgao
    achados = []
    for (doc, cnpj), lista in liq.items():
        contratos = [c for c in contratos_do_credor(ctx, lista[0].documento, lista[0].credor) if c.orgao_cnpj == cnpj]
        contratado = sum(c.valor for c in contratos)
        excesso = liquidado_acima_do_contratado(contratado, [e.valor for e in lista],
                                                tolerancia=float(lim["tolerancia_absoluta"]))
        if excesso is None:
            continue
        ultima = max((e.data for e in lista if e.data), default=None)
        achados.append(AchadoExecucao(
            "liquidado_acima", lista[0].orgao, doc, _mes(ultima),
            f"{lista[0].credor or doc}: {len(lista)} liquidação(ões) em {lista[0].orgao or 'órgão não informado'} "
            f"somam {_moeda(sum(e.valor for e in lista))} para {len(contratos)} contrato(s) do mesmo órgão "
            f"publicado(s) no PNCP que somam {_moeda(contratado)}, aditivos incluídos", excesso, contratado,
            {"contratos": [c.id for c in contratos], "orgao_cnpj": cnpj}))
    contagem: dict[str, int] = defaultdict(int)
    for a in achados:
        contagem[a.chave] += 1
    for a in achados:
        if contagem[a.chave] > 1:            # o mesmo credor acima do contratado em dois órgãos
            a.chave = f"{a.chave}|{a.dados['orgao_cnpj']}"
    out.achados.extend(achados)


def _medicoes(eventos, out: ConferenciasExecucao, lim: dict) -> None:
    por_empenho: dict[str, list[EventoDespesa]] = defaultdict(list)
    for e in eventos:
        if e.tipo == "liquidacao" and e.data:
            por_empenho[e.chave].append(e)
    for chave, lista in por_empenho.items():
        lista.sort(key=lambda e: e.data)
        if medicoes_repetidas([e.valor for e in lista], int(lim["vezes"]), float(lim["tolerancia_relativa"])):
            orgao, _, emp = chave.partition("|")
            out.achados.append(AchadoExecucao(
                "medicoes", orgao, chave, _mes(lista[-1].data),
                f"empenho {emp} ({lista[0].credor or lista[0].documento}): {len(lista)} liquidações, "
                f"{int(lim['vezes'])} ou mais seguidas com o mesmo valor ({_moeda(lista[-1].valor)})",
                sum(e.valor for e in lista), 0.0, {"valores": [e.valor for e in lista]}))


def _concentracao_do_pago(pagos: list[EventoDespesa], out: ConferenciasExecucao, lim: dict) -> None:
    grupos: dict[tuple[str, int], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    nomes: dict[str, str] = {}
    fora = lim.get("elementos_fora") or []
    for e in pagos:
        if e.data and not _sem_contrato_por_natureza(e.elemento, fora):
            grupos[(e.orgao, e.data.year)][e.documento or e.credor] += e.valor
            nomes[e.documento or e.credor] = e.credor or e.documento
    corte = float(lim["corte_pct"]) / 100.0
    for (orgao, ano), por_credor in grupos.items():
        total = sum(por_credor.values())
        if total <= float(lim["pago_minimo"]) or total <= 0:
            continue
        ordenados = sorted(por_credor.items(), key=lambda kv: -kv[1])
        acumulado, n = 0.0, 0
        for _, v in ordenados:
            acumulado += v
            n += 1
            if acumulado / total >= corte:
                break
        if len(ordenados) >= int(lim["minimo_de_credores"]) and n <= int(lim["credores"]) and len(ordenados) > n:
            out.achados.append(AchadoExecucao(
                "concentracao_pago", orgao, f"{orgao}|{ano}", f"{ano}-12",
                f"{orgao or 'órgão não informado'}, {ano}: {n} de {len(ordenados)} credores levam "
                f"{acumulado / total * 100:.1f}% do pago ({_moeda(total)})", acumulado, total,
                {"credores": [nomes[c] for c, _ in ordenados[:n]]}))
        lider, v = ordenados[0]
        if len(ordenados) > 1 and v / total * 100 >= float(lim["credor_unico_pct"]):
            out.achados.append(AchadoExecucao(
                "credor_unico", orgao, f"{orgao}|{ano}|{lider}", f"{ano}-12",
                f"{orgao or 'órgão não informado'}, {ano}: {nomes[lider]} recebeu {v / total * 100:.1f}% do pago "
                f"({_moeda(v)} de {_moeda(total)})", v, total))


def _sem_contrato(pagos: list[EventoDespesa], ctx: ContextoTrilha, out: ConferenciasExecucao, lim: dict) -> None:
    meses: dict[tuple[str, str], set] = defaultdict(set)
    valor: dict[tuple[str, str], float] = defaultdict(float)
    nomes = {}
    for e in pagos:
        doc = e.documento
        if not e.data or not cruzavel(doc, e.credor) or contratos_do_orgao(ctx, doc, e.credor, e.orgao):
            continue          # documento sem os dígitos para cruzar: vira cobertura, não indício
        if _sem_contrato_por_natureza(e.elemento, lim["elementos_sem_contrato"]):
            continue
        doc = chave_do_credor(doc, e.credor)
        meses[(e.orgao, doc)].add(_mes(e.data))
        valor[(e.orgao, doc)] += e.valor
        nomes[doc] = e.credor or doc
    for (orgao, doc), ms in meses.items():
        if len(ms) >= int(lim["minimo_de_meses"]) and valor[(orgao, doc)] > float(lim["valor_minimo"]):
            out.achados.append(AchadoExecucao(
                "sem_contrato", orgao, f"{orgao}|{doc}", max(ms),
                f"{nomes[doc]} ({doc.split('|')[0]}) recebeu {_moeda(valor[(orgao, doc)])} em {len(ms)} meses "
                f"distintos "
                f"({min(ms)} a {max(ms)}) sem contrato do órgão publicado no PNCP", valor[(orgao, doc)], 0.0,
                {"meses": sorted(ms)}))
    out.cobertura["pagamentos_com_documento_mascarado"] = sum(1 for e in pagos
                                                              if e.documento and not cruzavel(e.documento, e.credor))


def _fim_de_ano_nos_empenhos(eventos, out: ConferenciasExecucao, lim: dict,
                             meses_lidos: set[str] | None = None) -> None:
    """Empenhos dos últimos dias de dezembro contra o empenhado do órgão no ano.

    Só entram os exercícios que a coleta leu nos doze meses (``despesa_consultas``): num ano lido pela
    metade (a coleta de 28/11/2026 começa em novembro de 2024), dezembro seria quase todo o empenhado e o
    alerta mediria a coleta, não o Município. Sem o registro das consultas, conta todo exercício."""
    dias = int(lim["dias"])
    corte = float(lim["multiplo_da_parcela_uniforme"]) * dias / 365.0
    grupos: dict[tuple[str, int], list[EventoDespesa]] = defaultdict(list)
    for e in eventos:
        if e.tipo == "empenho" and e.data:
            grupos[(e.orgao, e.data.year)].append(e)
    anos = sorted({ano for _, ano in grupos})
    if meses_lidos is not None:
        inteiros = [a for a in anos if all(f"{a:04d}-{m:02d}" in meses_lidos for m in range(1, 13))]
        out.cobertura["fim_de_ano_exercicios_medidos"] = inteiros
        out.cobertura["fim_de_ano_exercicios_incompletos"] = [a for a in anos if a not in inteiros]
        grupos = {k: v for k, v in grupos.items() if k[1] in inteiros}
    for (orgao, ano), lista in grupos.items():
        total = sum(e.valor for e in lista)
        if total <= float(lim["empenhado_minimo"]) or total <= 0:
            continue
        fim = sum(e.valor for e in lista if e.data.month == 12 and e.data.day > 31 - dias)
        if fim / total > corte:
            out.achados.append(AchadoExecucao(
                "fim_de_ano", orgao, f"{orgao}|{ano}", f"{ano}-12",
                f"{orgao or 'órgão não informado'}, {ano}: {fim / total * 100:.1f}% do empenhado do ano nos "
                f"últimos {dias} dias de dezembro ({_moeda(fim)} de {_moeda(total)}); o ritmo uniforme seria "
                f"{dias / 365 * 100:.1f}%", fim, total))


def _fim_de_ano_na_matriz(con: _sqlite3.Connection, out: ConferenciasExecucao, lim: dict) -> None:
    """Na matriz de saldos (mensal): dezembro de cada função contra a média do mês no exercício.

    Só exercícios com os doze meses entregues; o empenhado é o movimento líquido do mês (o
    cancelamento de empenho em dezembro sai negativo e não é concentração)."""
    if not _tem_tabela(con, "msc_itens"):
        return
    soma = "sum(case when natureza_conta = 'C' then valor else -valor end)"
    meses = {}
    for ano, n in con.execute("select substr(mes, 1, 4), count(distinct mes) from msc_itens group by 1"):
        meses[int(ano)] = n
    corte = float(lim["multiplo_mensal"]) / 12.0
    medidos = 0
    for ano in sorted(a for a, n in meses.items() if n == 12):
        por_funcao: dict[str, dict[int, float]] = defaultdict(dict)
        for funcao, mes, v in con.execute(
                f"select funcao, substr(mes, 6, 2), {soma} from msc_itens where conta_contabil like '62213%' "
                "and substr(natureza_despesa, 3, 2) != '91' and mes like ? group by 1, 2", (f"{ano}-%",)):
            por_funcao[str(funcao or "").zfill(2)][int(mes)] = v or 0.0
        for funcao, m in por_funcao.items():
            total = sum(m.values())
            if total <= float(lim["empenhado_minimo"]) or total <= 0:
                continue
            medidos += 1
            dez = m.get(12, 0.0)
            if dez / total > corte:
                out.achados.append(AchadoExecucao(
                    "fim_de_ano_funcao", f"função {funcao}", f"{funcao}|{ano}", f"{ano}-12",
                    f"função {funcao}, {ano}: dezembro teve {dez / total * 100:.1f}% do empenhado do ano "
                    f"({_moeda(dez)} de {_moeda(total)}); a média do mês é {100 / 12:.1f}%", dez, total))
    out.cobertura["funcoes_ano_medidas_no_fim_de_ano"] = medidos


_BASE_FICHA = {
    "liquidado_acima": dict(familia=Familia.ENT, gravidade="alta",
                            norma="Lei 4.320/1964, arts. 62 e 63; Lei 14.133/2021, art. 125",
                            como_deveria="O que se liquida para o credor cabe no contratado com os aditivos publicados.",
                            niveis=[Nivel.B, Nivel.C],
                            providencia="Pedir as notas de liquidação, os atestos e os aditivos que cobrem a diferença."),
    "medicoes": dict(familia=Familia.ENT, gravidade="media", norma="Lei 4.320/1964, art. 63; Lei 14.133/2021, art. 140",
                     como_deveria="Cada liquidação comprova a entrega medida no período; medições iguais em sequência "
                                  "pedem a memória da medição (se o contrato é de valor mensal fixo, a cláusula fecha o "
                                  "alerta).",
                     niveis=[Nivel.B], providencia="Pedir os boletins de medição e os atestos de cada liquidação."),
    "concentracao_pago": dict(familia=Familia.PRC, gravidade="media", norma="CF, art. 37, caput (impessoalidade)",
                              como_deveria="O pago do órgão se distribui pela competição, sem que poucos credores "
                                           "levem quase tudo.",
                              niveis=[Nivel.B], providencia="Pedir as licitações e os contratos dos maiores credores."),
    "credor_unico": dict(familia=Familia.PRC, gravidade="media",
                         norma="CF, art. 37, caput; Lei 14.133/2021, art. 40, V, b",
                         como_deveria="Nenhum credor concentra a despesa do órgão sem licitação que o justifique.",
                         niveis=[Nivel.B], providencia="Pedir o contrato, a licitação e as medições do credor."),
    "sem_contrato": dict(familia=Familia.VIN, gravidade="alta",
                         norma="Lei 14.133/2021, arts. 72, 89 e 95; Lei 4.320/1964, art. 63, § 2º, I",
                         como_deveria="Despesa continuada tem contrato, ata ou termo publicado no PNCP.",
                         niveis=[Nivel.B, Nivel.F],
                         providencia="Pedir o instrumento que dá direito ao credor e a publicação no PNCP."),
    "fim_de_ano": dict(familia=Familia.ORC, gravidade="media", norma="Lei 4.320/1964, art. 35, II; LC 101/2000, art. 42",
                       como_deveria="O empenho acompanha a necessidade do ano, não a pressa de não perder a dotação.",
                       niveis=[Nivel.B], providencia="Pedir os processos dos empenhos de dezembro e a entrega de cada um."),
    "fim_de_ano_funcao": dict(familia=Familia.ORC, gravidade="media",
                              norma="Lei 4.320/1964, art. 35, II; LC 101/2000, art. 42",
                              como_deveria="O empenho acompanha a necessidade do ano, não a pressa de não perder a "
                                           "dotação.",
                              niveis=[Nivel.B],
                              providencia="Pedir a relação dos empenhos de dezembro da função e a entrega de cada um."),
}
_CODIGOS = {"liquidado_acima": "ENT-LIQ01", "medicoes": "ENT-MED01", "concentracao_pago": "PRC-CONC02",
            "credor_unico": "PRC-CONC03", "sem_contrato": "VIN-SEMCT01", "fim_de_ano": "ORC-FIMANO01",
            "fim_de_ano_funcao": "ORC-FIMANO02"}


def _slug(t: str) -> str:
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "-", t).strip("-").upper()[:60]


def ficha_execucao(a: AchadoExecucao, competencia: str | None = None) -> Ficha:
    """A ficha do achado: indício, nunca acusação (a verificação sai dos níveis de prova)."""
    if a.tipo == "ordem":
        return ficha_de_ordem(_slug(a.chave), a.dados.get("problemas") or [a.descricao], competencia)
    base = _BASE_FICHA[a.tipo]
    return emitir(codigo=f"{_CODIGOS[a.tipo]}-{_slug(a.chave)}", titulo=f"{TITULOS_EXECUCAO[a.tipo]}: "
                  f"{a.orgao.title() if a.orgao else 'órgão não informado'}",
                  como_esta="Indício, não acusação. " + a.descricao[:1].upper() + a.descricao[1:] + ".",
                  competencia=competencia, **base)


# --- As contas uma a uma, item a item (requisito 132) ---------------------------------------------

ESTACOES_LEGAIS = ("empenho", "liquidacao", "ordem_pagamento", "pagamento")   # Lei 4.320/1964, arts. 58 a 65


def contas_item_a_item(eventos: Iterable[EventoDespesa], filtro=None, *, maiores: int = 9) -> list[dict]:
    """As ``maiores`` saídas (por credor, pelo pago) com as quatro estações legais e a cronologia."""
    por_credor: dict[str, list[EventoDespesa]] = defaultdict(list)
    for e in eventos:
        if filtro is None or filtro(e):
            # CPF mascarado: os seis do meio não bastam para separar duas pessoas; o nome entra na chave.
            por_credor[chave_do_credor(e.documento, e.credor) or e.credor].append(e)
    linhas = []
    for chave, evs in por_credor.items():
        estacoes = {t: round(sum(e.valor for e in evs if e.tipo == t), 2) for t in ESTACOES_LEGAIS}
        if not any(e.tipo == "ordem_pagamento" for e in evs):
            # A exportação do portal publica cada pagamento com o número da ordem, mas não o ato da ordem
            # em separado: a estação fica sem valor (não lida), nunca zero (28/11/2026, banco real).
            estacoes["ordem_pagamento"] = None
        cronologia = [{"data": e.data.isoformat() if e.data else "", "estacao": e.tipo, "valor": e.valor,
                       "empenho": e.empenho, "url": e.url} for e in sorted(evs, key=lambda e: (e.data or date.min))]
        linhas.append({"saida": evs[0].credor or chave, "documento": evs[0].documento,
                       "orgao": evs[0].orgao, "estacoes": estacoes, "cronologia": cronologia,
                       "origem": "portal da transparência, item a item"})
    # A maior saída é a que mais saiu do caixa: pago (ou a ordem, quando o pagamento não é publicado),
    # depois o liquidado, depois o empenhado.
    linhas.sort(key=lambda r: (-(r["estacoes"]["pagamento"] or r["estacoes"]["ordem_pagamento"] or 0.0),
                               -r["estacoes"]["liquidacao"], -r["estacoes"]["empenho"]))
    return linhas[:maiores]
