"""Auditoria independente do selo: cada critério conferido, a nota pela fórmula oficial e o confronto.

Para cada critério que vale para a Prefeitura, o avaliador junta as provas sem rede (banco, mapa
legal, relatórios) e as páginas que a sondagem guardou, e decide os itens em duas leituras:

* oficial: a metodologia como está escrita (regras/pntp/matriz_2026.yml);
* restritiva: a leitura mais exigente onde a metodologia deixa margem (regras/pntp/escolhas.yml),
  com a dimensão suplementar O (coerência com fontes nacionais, fundos e conselhos), escolha E12.

Em cada leitura saem duas notas: a comprovada (item sem prova vale zero) e o teto (item sem prova vale
o máximo). O teto abaixo de 95 ou um essencial provadamente em falta derruba o Diamante declarado.
O resultado é indício para o parecer, não acusação.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .. import partes as _partes
from .. import RAIZ
from ..conferencias import compras
from ..legal.mapa import MapaLegal, carregar as carregar_mapa
from . import fundos as fundos_mod
from . import provas as provas_mod
from .formula import LEITURAS, Nota, calcular, itens_da_leitura
from .matriz import Criterio, Matriz, carregar
from .verificadores import Pagina, ler_sondagem, verificar

def _pct(v: float) -> str:
    return f"{v:.2f}".replace(".", ",") + "%"


BANCO = RAIZ / "dados" / "onisciente" / "historico.db"
SONDAGEM = RAIZ / "relatorios" / "onisciente" / "sondagem"

# O selo que a Prefeitura declara e de onde vem a declaração.
DECLARADO = {
    "selo": "Diamante",
    "ciclo": 2025,
    "indice": "acima de 95%",
    "fonte": "Jornal Opção, 05/12/2025: Prefeitura de Goiânia recebe selo Diamante por nota máxima em transparência",
    "url": "https://www.jornalopcao.com.br/goiania/goiania-recebe-selo-diamante-por-nota-maxima-em-transparencia-publica-772080/",
    "ciclo_2026": "O resultado do ciclo 2026 saiu em novembro de 2026 no Radar; uma manchete de 06/08/2026 (Mais Goiás) "
                  "fala em 98,08% na validação do TCM-GO, mas a página recusou a leitura e o número não foi conferido.",
}

# Dimensão suplementar da leitura restritiva (E12): o que a metodologia não mede e a lei exige.
DIMENSAO_O = {"nome": "Coerência com fontes nacionais, fundos e conselhos (Onisciente)", "peso": 4}
SUPLEMENTARES = (
    Criterio("O.1", "O", "obrigatorio", "onisciente", "Notas fiscais dos contratos do Executivo publicadas no PNCP",
             ("disponibilidade",), "Lei 14.133/2021, art. 174, § 2º, VI"),
    Criterio("O.2", "O", "essencial", "onisciente", "Receita, execução e prestação de contas do FMAS publicadas frente "
             "aos repasses do Fundo Nacional", ("disponibilidade", "atualidade"),
             "LC 101/2000, art. 48-A; Lei 12.527/2011, art. 8º, § 1º, II e III; Lei 8.742/1993, art. 30"),
    Criterio("O.3", "O", "obrigatorio", "onisciente", "Conselho Municipal de Assistência Social com resoluções, atas, "
             "composição e regimento publicados e atualizados", ("disponibilidade", "atualidade"),
             "Lei municipal 9.009/2010, arts. 3º e 10; Lei 8.742/1993, art. 30, I"),
    Criterio("O.4", "O", "essencial", "onisciente", "Relatórios fiscais coerentes com o SICONFI e entregues no prazo",
             ("disponibilidade", "atualidade"), "LC 101/2000, arts. 48, 52 e 55"),
    Criterio("O.5", "O", "obrigatorio", "onisciente", "Normas locais que regem o gasto localizadas em fonte oficial",
             ("disponibilidade",), "Lei 12.527/2011, art. 8º, caput; CF, art. 37, caput (publicidade)"),
    Criterio("O.6", "O", "obrigatorio", "onisciente", "Endereço do e-SIC alcançável", ("disponibilidade",),
             "Lei 12.527/2011, art. 10, § 2º"),
)


@dataclass
class Resultado:
    criterio: Criterio
    itens: dict[str, dict[str, bool | None]]           # leitura -> item -> valor
    provas: list[provas_mod.Prova] = field(default_factory=list)
    notas: dict[str, list[str]] = field(default_factory=dict)

    def situacao(self, leitura: str, matriz: Matriz) -> str:
        aplic = itens_da_leitura(self.criterio, matriz, leitura) if self.criterio.matriz != "onisciente" \
            else self.criterio.itens
        vals = [self.itens[leitura].get(i) for i in aplic]
        if any(v is False for v in vals):
            return "não atendido"
        if vals and all(v is True for v in vals):
            return "atendido"
        return "não verificável"

    def como_dict(self, matriz: Matriz) -> dict:
        c = self.criterio
        return {"id": c.id, "dimensao": c.dimensao, "classe": c.classe, "matriz": c.matriz, "texto": c.texto,
                "base_legal": c.base_legal, "onde": list(c.onde), "itens": self.itens,
                "situacao": {l: self.situacao(l, matriz) for l in self.itens},
                "provas": [p.como_dict() for p in self.provas], "notas": self.notas}


@dataclass
class Auditoria:
    matriz: Matriz
    hoje: date
    resultados: list[Resultado]
    notas: dict[str, Nota]                              # "oficial/comprovada", "oficial/teto", ...
    fundos: list[fundos_mod.Situacao]
    repasses: dict
    achados: list[compras.Achado]
    alertas_cruzados: dict
    paginas_lidas: int
    radar: dict

    def nota(self, leitura: str, modo: str) -> Nota:
        return self.notas[f"{leitura}/{modo}"]

    @property
    def veredito(self) -> dict:
        com, teto = self.nota("oficial", "comprovada"), self.nota("oficial", "teto")
        r_teto = self.nota("restritiva", "teto")
        if com.nivel == DECLARADO["selo"]:
            oficial = "confirmado"
            frase = "As provas lidas confirmam o Selo Diamante pela leitura oficial."
        elif teto.nivel != DECLARADO["selo"]:
            oficial = "não se sustenta"
            frase = (f"Pela leitura oficial o Selo Diamante não se sustenta: mesmo contando como atendido tudo o que "
                     f"ainda não foi provado, o índice máximo é {_pct(teto.indice)} e o nível é {teto.nivel}.")
        else:
            oficial = "não confirmado"
            frase = (f"Pela leitura oficial o Selo Diamante não está confirmado: com as provas lidas o índice é "
                     f"{_pct(com.indice)} ({com.nivel}); o máximo possível com o que falta provar é {_pct(teto.indice)}.")
        restritiva = "mantém" if r_teto.nivel == DECLARADO["selo"] else "cai"
        if restritiva == "cai":
            motivo = (f"essenciais em falta: {', '.join(r_teto.essenciais_em_falta)}" if r_teto.essenciais_em_falta
                      else f"índice máximo de {_pct(r_teto.indice)}")
            frase += (f" Pela leitura restritiva o padrão cai para {r_teto.nivel} ({motivo}), mesmo no melhor caso.")
        return {"oficial": oficial, "restritiva": restritiva, "frase": frase}

    def como_dict(self) -> dict:
        return {"ciclo": self.matriz.ciclo, "hoje": self.hoje.isoformat(), "declarado": DECLARADO,
                "veredito": self.veredito, "notas": {k: v.como_dict() for k, v in self.notas.items()},
                "radar": self.radar, "paginas_lidas": self.paginas_lidas,
                "criterios": [r.como_dict(self.matriz) for r in self.resultados],
                "fundos": [s.como_dict() for s in self.fundos], "repasses_fnas": self.repasses,
                "alertas_cruzados": self.alertas_cruzados,
                "achados": [{"tipo": a.tipo, "orgao": a.orgao, "chave": a.chave, "mes": a.mes,
                             "descricao": a.descricao, "valor": a.valor, "dados": a.dados} for a in self.achados],
                "fontes": self.matriz.fontes, "pendencias": self.matriz.pendencias}


def combinar(c: Criterio, ao_vivo: dict[str, bool | None], provas: list[provas_mod.Prova],
             leitura: str) -> dict[str, bool | None]:
    """Junta a sondagem e as provas sem rede. Na oficial a prova positiva do portal prevalece; na restritiva
    a falta provada prevalece sobre a presença (E10)."""
    itens = dict(ao_vivo)
    for p in provas:
        if not p.vale(leitura) or p.item not in itens:
            continue
        atual = itens[p.item]
        if leitura == "restritiva":
            itens[p.item] = False if (p.valor is False or atual is False) else True
        elif atual is None:
            itens[p.item] = p.valor
    if itens.get("disponibilidade") is False:
        itens = {i: False for i in itens}
    return itens


def _radar(paginas: list[Pagina]) -> dict:
    import re
    lidas = [p for p in paginas if p.fonte == "e_radar" and p.ok]
    for p in lidas:
        texto = p.visivel
        i = texto.find("goiania")
        if i >= 0:
            trecho = texto[i:i + 400]
            m = re.search(r"(\d{1,3}[.,]\d{1,2})\s*%", trecho)
            nivel = re.search(r"diamante|ouro|prata|elevado|intermediario|basico|inicial", trecho)
            return {"lido": True, "url": p.url, "indice": m.group(1).replace(",", ".") if m else None,
                    "nivel": nivel.group(0) if nivel else None, "quando": p.quando.isoformat()}
    return {"lido": False, "motivo": ("o painel 6 do Radar e os dados abertos do PNTP recusaram a leitura em "
                                      "27/11/2026; a sondagem e_radar no GitHub lê de novo" if not lidas else
                                      "as páginas do Radar lidas não trazem Goiânia no texto (painel por JavaScript)")}


def _alertas_cruzados(conf: compras.Conferencias | None) -> dict:
    """As conferências que já existem, por dimensão do PNTP que elas tocam."""
    if conf is None:
        return {}
    tipos = conf.por_tipo()
    valor = {}
    for a in conf.achados:
        valor[a.tipo] = valor.get(a.tipo, 0.0) + a.valor
    def linha(ts, dim):
        return {"dimensao": dim, "achados": sum(tipos.get(t, 0) for t in ts),
                "valor": round(sum(valor.get(t, 0.0) for t in ts), 2), "tipos": {t: tipos.get(t, 0) for t in ts}}
    return {
        "licitacoes": linha(("dispensa_acima", "dispensa_no_teto", "fracionamento", "emergencial"), "8 Licitações"),
        "contratos": linha(("aditivo", "concentracao", "nf_ausente", "nota_acima", "nota_preco"), "9 Contratos"),
        "precos": linha(("preco",), "4 Despesa (preço pago)"),
    }


def avaliar(banco: Path | sqlite3.Connection | None = BANCO, *, raiz: Path = RAIZ, sondagem: Path | None = None,
            mapa: MapaLegal | None = None, matriz: Matriz | None = None, hoje: date | None = None) -> Auditoria:
    matriz = matriz or carregar()
    mapa = mapa or carregar_mapa()
    hoje = hoje or date.today()
    con = None
    if isinstance(banco, sqlite3.Connection):
        con = banco
    elif banco is not None and Path(banco).exists():
        con = _partes.conectar_leitura(banco)
    try:
        provas = provas_mod.todas(con, mapa, raiz)
        repasses = provas_mod.repasses_fnas(con)
        conf = compras.conferir(con) if con is not None else None
    finally:
        if con is not None and not isinstance(banco, sqlite3.Connection):
            con.close()
    paginas = ler_sondagem(sondagem or (raiz / "relatorios" / "onisciente" / "sondagem"))
    situacoes = fundos_mod.avaliar(provas, repasses, paginas, raiz)
    provas += _provas_dos_fundos(situacoes)

    criterios = sorted(matriz.do_executivo(), key=lambda c: c.ordem)
    resultados = []
    for c in criterios + list(SUPLEMENTARES):
        das = [p for p in provas if p.criterio == c.id]
        itens, notas = {}, {}
        for leitura in LEITURAS:
            ao_vivo, n = (verificar(c, paginas, leitura) if c.matriz != "onisciente"
                          else ({i: None for i in c.itens}, []))
            itens[leitura] = combinar(c, ao_vivo, das, leitura)
            notas[leitura] = n
        if c.matriz == "onisciente":
            itens["oficial"] = {i: None for i in c.itens}
        resultados.append(Resultado(c, itens, das, notas))

    notas: dict[str, Nota] = {}
    dims_r = dict(matriz.dimensoes, O=DIMENSAO_O)
    for leitura in LEITURAS:
        lista = criterios if leitura == "oficial" else criterios + list(SUPLEMENTARES)
        por = {r.criterio.id: r.itens[leitura] for r in resultados}
        for otimista in (False, True):
            n = calcular(por, lista, matriz, leitura, otimista=otimista,
                         dimensoes=matriz.dimensoes if leitura == "oficial" else dims_r)
            notas[f"{leitura}/{n.modo}"] = n

    mes = f"{hoje:%Y-%m}"
    aud = Auditoria(matriz, hoje, resultados, notas, situacoes, repasses, [], _alertas_cruzados(conf),
                    len(paginas), _radar(paginas))
    aud.achados = _achados(aud, mes) + fundos_mod.achados(situacoes, repasses, mes)
    return aud


def _provas_dos_fundos(situacoes: list[fundos_mod.Situacao]) -> list[provas_mod.Prova]:
    """As obrigações do Fundo e do Conselho viram provas dos critérios O.2 e O.3."""
    out = []
    for cid, prefixo in (("O.2", "F"), ("O.3", "C")):
        do = [s for s in situacoes if s.obrigacao.id.startswith(prefixo)]
        falta = [s for s in do if s.alerta]
        if falta:
            out.append(provas_mod.Prova(cid, "disponibilidade", False, "restritiva",
                                        "sem publicação comprovada: " + "; ".join(
                                            f"{s.obrigacao.id} {s.obrigacao.texto[:1].lower() + s.obrigacao.texto[1:]} ({s.estado})" for s in falta),
                                        "onisciente/selo/fundos.py", provas_mod.Nivel.F,
                                        max((s.valor_em_jogo for s in falta), default=0.0)))
        elif do:
            out.append(provas_mod.Prova(cid, "disponibilidade", True, "restritiva", "todas as obrigações publicadas",
                                        "onisciente/selo/fundos.py", provas_mod.Nivel.C))
    return out


def _achados(aud: Auditoria, mes: str) -> list[compras.Achado]:
    """Achados da auditoria do selo, no formato das conferências (tipo, órgão, chave, mês, descrição)."""
    lista = []
    v = aud.veredito
    if v["oficial"] != "confirmado" or v["restritiva"] == "cai":
        r = aud.nota("restritiva", "teto")
        lista.append(compras.Achado(
            "selo_nao_confirmado", "", "PREFEITURA MUNICIPAL DE GOIANIA", f"selo-{aud.matriz.ciclo}", mes, v["frase"],
            0.0, 95.0, {"oficial": {k: aud.notas[k].como_dict() for k in aud.notas if k.startswith("oficial")},
                        "restritiva": r.como_dict()}))
    por_id = {r.criterio.id: r for r in aud.resultados}
    for cid in aud.nota("restritiva", "teto").essenciais_em_falta:
        r = por_id[cid]
        provas = "; ".join(p.descricao for p in r.provas if p.valor is False)[:600]
        lista.append(compras.Achado(
            "selo_essencial_em_falta", "", "PREFEITURA MUNICIPAL DE GOIANIA", f"criterio-{cid}", mes,
            f"o critério essencial {cid} ({r.criterio.texto[:1].lower() + r.criterio.texto[1:]}) não se cumpre na leitura restritiva: {provas}",
            sum(p.valor_em_jogo for p in r.provas), 0.0,
            {"criterio": cid, "base_legal": r.criterio.base_legal,
             "situacao": {l: r.situacao(l, aud.matriz) for l in r.itens}}))
    return lista
