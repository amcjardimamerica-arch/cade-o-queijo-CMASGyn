"""As compras e os contratos do Município conferidos no banco histórico (famílias PRC e ENT).

Lê o que os motores do PNCP guardaram (contratações, contratos, amparo legal, itens com catálogo,
termos aditivos, preços nacionais e notas fiscais) e confere, para cada órgão do Município:

* dispensa por valor acima do limite do ano (Lei 14.133/2021, art. 75, I e II);
* dispensa ajustada ao teto (98% ou mais do limite), sinal de compra dimensionada para fugir da licitação;
* fracionamento: dispensas do mesmo ramo no mesmo órgão e exercício que, somadas, passam do limite
  (art. 75, § 1º);
* contratação emergencial com vigência acima de um ano, prorrogada ou recontratada com o mesmo
  fornecedor (art. 75, VIII);
* aditivos de acréscimo acima de 25% do valor inicial, ou 50% na reforma (art. 125);
* contratos concentrados em poucos fornecedores (CF, art. 37, impessoalidade);
* preço unitário homologado contra a mediana nacional do mesmo item no semestre (art. 23);
* notas fiscais acima do contratado, no total e no preço unitário (Lei 4.320/1964, art. 63).

As conferências valem para o Município inteiro; as fichas do parecer saem só para os órgãos da pasta.
O que o banco ainda não tem (amparo não lido, item sem código de catálogo) não some: entra na
cobertura, e a cobertura incompleta da pasta vira ficha SIS, porque é falha do sistema.
"""

from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from statistics import median
from typing import Callable, Iterable

from .. import partes as _partes
from ..legal.mapa import MapaLegal, Regra, carregar
from ..nucleo.indicios import Familia, Ficha, emitir
from ..nucleo.provas import Nivel
from .padroes import Pagamento, concentracao
from .precos import comparar, ficha_de_sobrepreco

TERMOS_DA_PASTA = ("ASSISTENCIA SOCIAL", "SEMAS", "FUNDO MUNICIPAL DE ASSISTENCIA", "DIREITOS HUMANOS",
                   "POLITICAS PARA AS MULHERES", "DESENVOLVIMENTO HUMANO E SOCIAL",
                   "DESENVOLVIMENTO  HUMANO E SOCIAL")

# Ramos de atividade (art. 75, § 1º: "objetos de mesma natureza"), do mais específico ao mais geral.
# O ramo vem do texto do objeto; quando o texto não diz, a classe do catálogo dos itens é a segunda via.
RAMOS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("material de construção", ("MATERIAL DE CONSTRUCAO", "MATERIAIS DE CONSTRUCAO", r"CIMENTO\b", "ARGAMASSA")),
    ("manutenção de veículos", ("MANUTENCAO PREVENTIVA E CORRETIVA DE VEICULO", "MANUTENCAO DE VEICULO",
                                "MANUTENCAO DA FROTA", "PECAS AUTOMOTIVAS", "PECAS E ACESSORIOS PARA VEICULO",
                                r"PNEUS?\b")),
    ("locação de veículos", ("LOCACAO DE VEICULO", "LOCACAO DE AUTOMOVE", "LOCACAO DE VAN", "LOCACAO DE ONIBUS")),
    ("combustível", ("COMBUSTIVE", "GASOLINA", "OLEO DIESEL", "ETANOL")),
    ("água mineral", ("AGUA MINERAL",)),
    ("alimentação", ("GENEROS ALIMENTICIOS", r"ALIMENTOS?\b", "ALIMENTACAO", "LANCHE", "REFEICO", "REFEICAO",
                     "MARMITEX", "COFFEE BREAK", "BUFFET", "HORTIFRUTIGRANJEIRO", "CESTA BASICA", "CESTAS BASICAS")),
    ("passagens e viagens", ("PASSAGENS", "AGENCIAMENTO DE VIAGE", "HOSPEDAGEM")),
    ("medicamentos", ("MEDICAMENTO", "FARMACO", "FARMACEUTIC")),
    ("material médico-hospitalar", ("MEDICO-HOSPITALAR", "MEDICO HOSPITALAR", "HOSPITALAR", "ODONTOLOGIC",
                                    "ORTESE", "PROTESE", "LABORATORI")),
    ("informática", ("INFORMATICA", "COMPUTADOR", "NOTEBOOK", "IMPRESSORA", "TONER", "CARTUCHO",
                     "SOFTWARE", "LICENCA DE USO", "LICENCAS DE USO", "TECNOLOGIA DA INFORMACAO")),
    ("limpeza e higiene", ("MATERIAL DE LIMPEZA", "MATERIAIS DE LIMPEZA", "HIGIENE", "DESCARTAVE")),
    ("expediente", ("MATERIAL DE EXPEDIENTE", "MATERIAIS DE EXPEDIENTE", "PAPELARIA", "MATERIAL DE ESCRITORIO")),
    ("gráfica e divulgação", ("GRAFIC", "IMPRESSAO DE", "BANNER", "PANFLETO", "ADESIVO", r"PLACAS?\b")),
    ("eventos", (r"EVENTOS?\b", "SONORIZACAO", "PALCO", "TENDA", "ILUMINACAO CENICA")),
    ("mobiliário e eletro", ("MOBILIARIO", r"MOVEIS\b", "CADEIRA", "ELETRODOMESTIC", "AR CONDICIONADO",
                             "AR-CONDICIONADO", "BEBEDOURO", "GELADEIRA", "REFRIGERADOR")),
    ("vestuário", ("UNIFORME", "VESTUARIO", "CAMISETA", "FARDAMENTO", "ENXOVAL")),
    ("capacitação", (r"CURSOS?\b", "CAPACITACAO", "TREINAMENTO", "INSCRICAO")),
    ("manutenção predial", ("MANUTENCAO PREDIAL", "INSTALACOES ELETRICAS", "INSTALACAO ELETRICA",
                            "HIDRAULIC", "SERRALHERIA", "PINTURA")),
    ("obras e engenharia", (r"(?<!MAO DE )OBRAS?\b", "REFORMA", "ENGENHARIA", "CONSTRUCAO", "PAVIMENTA", "AMPLIACAO")),
)
# Art. 75, I: obras, serviços de engenharia e manutenção de veículos automotores têm o limite maior.
RAMOS_DE_OBRA = {"obras e engenharia", "manutenção predial", "manutenção de veículos"}
REFORMA = ("REFORMA",)
AMPARO = re.compile(r"art\.?\s*(\d+)\s*,\s*([ivxl]+)\b", re.I)
JANELA_DE_MESES = 12


def _norm(texto) -> str:
    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t.upper()).strip()


def da_pasta(orgao: str) -> bool:
    nome = _norm(orgao)
    return any(_norm(t) in nome for t in TERMOS_DA_PASTA)


_RAMOS_RE = tuple((nome, re.compile(r"(?<![A-Z])(?:" + "|".join(termos) + ")")) for nome, termos in RAMOS)


def ramo(objeto: str) -> str | None:
    """O ramo de atividade pelo texto do objeto; cada termo casa do início de uma palavra
    (``CIMENTO`` não casa em ``forneCIMENTO``, nem ``EVENTO`` em ``EVENTUAL``)."""
    texto = _norm(objeto)
    for nome, padrao in _RAMOS_RE:
        if padrao.search(texto):
            return nome
    return None


def inciso(amparo_nome: str | None) -> tuple[int, str] | None:
    """``Lei 14.133/2021, Art. 75, II`` vira (75, 'II')."""
    m = AMPARO.search(str(amparo_nome or ""))
    return (int(m.group(1)), m.group(2).upper()) if m else None


def limite_de_dispensa(regra: Regra, ano: int, obra: bool) -> tuple[float, str]:
    """O limite do ano (decreto de atualização) e o decreto; o mais recente se o ano não estiver no mapa."""
    por_ano = regra.get("por_ano") or {}
    chaves = sorted(int(a) for a in por_ano) if por_ano else []
    if por_ano:
        escolhido = ano if ano in chaves else (max(a for a in chaves if a <= ano) if any(a <= ano for a in chaves)
                                               else min(chaves))
        linha = por_ano.get(escolhido) or por_ano.get(str(escolhido))
        return float(linha["obras" if obra else "outros"]), str(linha.get("decreto", ""))
    return float(regra.get("obras" if obra else "outros")), ""


def _mes_menos(mes: str, n: int) -> str:
    a, m = int(mes[:4]), int(mes[5:7])
    total = a * 12 + (m - 1) - n
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def _semestre(data: str) -> str:
    return f"{data[:4]}-{'1' if int(data[5:7]) <= 6 else '2'}"


def _unidade(u: str | None) -> str:
    t = _norm(u).split(" ")[0].rstrip(".") if u else ""
    sinonimos = {"UN": "UN", "UND": "UN", "UNID": "UN", "UNIDADE": "UN", "UNIDADES": "UN", "UNIT": "UN",
                 "KG": "KG", "QUILOGRAMA": "KG", "QUILO": "KG", "CX": "CX", "CAIXA": "CX", "PCT": "PCT",
                 "PACOTE": "PCT", "L": "L", "LT": "L", "LITRO": "L", "LITROS": "L", "M": "M", "METRO": "M",
                 "SERVICO": "SV", "SV": "SV", "MES": "MES", "MESES": "MES", "DIA": "DIA", "HORA": "H", "H": "H"}
    return sinonimos.get(t, t)


def _tabela(con: sqlite3.Connection, nome: str) -> bool:
    return _partes.tem_tabela(con, nome)


def _contar(con: sqlite3.Connection, sql: str, args: Iterable = ()) -> int:
    try:
        return int(con.execute(sql, list(args)).fetchone()[0] or 0)
    except sqlite3.OperationalError:
        return 0


@dataclass
class Achado:
    """Uma conferência que não fechou, com o que basta para virar ficha e linha de tabela."""

    tipo: str            # dispensa_acima, dispensa_no_teto, fracionamento, emergencial, aditivo,
                         # concentracao, preco, nota_acima, nota_preco
    orgao_cnpj: str
    orgao: str
    chave: str           # compra, contrato ou grupo
    mes: str             # AAAA-MM do fato que fechou a conferência
    descricao: str
    valor: float = 0.0
    limite: float = 0.0
    dados: dict = field(default_factory=dict)

    @property
    def da_pasta(self) -> bool:
        return da_pasta(self.orgao)


TITULOS = {
    "dispensa_acima": "Dispensa por valor acima do limite do ano",
    "dispensa_no_teto": "Dispensa ajustada ao teto do limite",
    "fracionamento": "Fracionamento de despesa (dispensas do mesmo ramo somadas)",
    "emergencial": "Contratação emergencial fora das condições do art. 75, VIII",
    "aditivo": "Aditivos acima do limite legal",
    "concentracao": "Contratos concentrados em poucos fornecedores",
    "preco": "Preço unitário acima da curva nacional",
    "nota_acima": "Notas fiscais acima do valor contratado",
    "nota_preco": "Preço da nota fiscal acima do homologado",
    "nf_ausente": "Notas fiscais dos contratos não publicadas no PNCP",
}


@dataclass
class Conferencias:
    achados: list[Achado] = field(default_factory=list)
    cobertura: dict = field(default_factory=dict)

    def por_tipo(self, so_da_pasta: bool = False) -> dict[str, int]:
        cont = Counter(a.tipo for a in self.achados if a.da_pasta or not so_da_pasta)
        return {t: cont.get(t, 0) for t in TITULOS}

    def por_orgao(self) -> list[tuple[str, int, float]]:
        """(órgão, achados, valor em jogo), do órgão com mais achados para o de menos."""
        cont: Counter = Counter()
        valor: dict[str, float] = defaultdict(float)
        for a in self.achados:
            cont[a.orgao] += 1
            valor[a.orgao] += a.valor
        return [(o, n, round(valor[o], 2)) for o, n in cont.most_common()]

    def da_competencia(self, competencia: str, so_da_pasta: bool = True) -> list[Achado]:
        inicio = _mes_menos(competencia, JANELA_DE_MESES - 1)
        # A falta de notas fiscais vale para todo o período lido, não só para o mês da última leitura.
        return [a for a in self.achados if (a.da_pasta or not so_da_pasta)
                and (inicio <= a.mes <= competencia
                     or (a.tipo == "nf_ausente" and a.dados.get("desde", a.mes) <= competencia <= a.mes))]

    def fichas(self, competencia: str | None = None) -> list[Ficha]:
        lista = self.da_competencia(competencia) if competencia else [a for a in self.achados if a.da_pasta]
        out = [f for a in lista if (f := ficha(a, competencia)) is not None]
        lacuna = self.cobertura.get("lacunas_da_pasta") or []
        if lacuna:
            out.append(emitir(
                codigo="SIS-COMPRAS-COBERTURA",
                familia=Familia.SIS,
                titulo="Conferência das compras da pasta ainda incompleta no banco",
                gravidade="media",
                como_deveria="Cada compra e cada contrato da pasta conferidos com o amparo legal, os itens, "
                             "os aditivos e as notas fiscais.",
                norma="Desenho do Onisciente: falha de coleta é falha do sistema, nunca silêncio do Município",
                como_esta="; ".join(lacuna).capitalize() + ".",
                niveis=[Nivel.F],
                documento_faltante=True,
                providencia="Rodar de novo o motor do detalhe das compras (ele continua de onde parou).",
                competencia=competencia,
            ))
        return out

    def como_dict(self) -> dict:
        return {"por_tipo": self.por_tipo(), "por_tipo_da_pasta": self.por_tipo(True),
                "por_orgao": [{"orgao": o, "achados": n, "valor": v} for o, n, v in self.por_orgao()[:15]],
                "cobertura": self.cobertura,
                "achados": [{"tipo": a.tipo, "orgao": a.orgao, "chave": a.chave, "mes": a.mes,
                             "descricao": a.descricao, "valor": a.valor, "limite": a.limite,
                             "da_pasta": a.da_pasta} for a in self.achados]}


# --- Leitura do banco -------------------------------------------------------------------------

@dataclass(frozen=True)
class _Compra:
    id: str
    mes: str
    modalidade: str
    orgao_cnpj: str
    orgao: str
    unidade: str
    objeto: str
    valor: float
    amparo: tuple[int, str] | None
    amparo_lido: bool
    classe: str | None
    homologada: bool = True


def _compras(con: sqlite3.Connection) -> list[_Compra]:
    tem_amparo = _tabela(con, "pncp_amparos")
    tem_itens = _tabela(con, "pncp_itens")
    amparos = {cid: nome for cid, nome in con.execute("select compra_id, nome from pncp_amparos")} \
        if tem_amparo else {}
    classes: dict[str, str] = {}
    if tem_itens:
        votos: dict[str, Counter] = defaultdict(Counter)
        for cid, classe, total in con.execute(
                "select compra_id, classe, coalesce(total_resultado, total_estimado, 0) from pncp_itens "
                "where classe is not null"):
            votos[cid][str(classe)] += total or 0.0
        classes = {cid: c.most_common(1)[0][0] for cid, c in votos.items() if c}
    out = []
    for pid, mes, mod, cnpj, orgao, unidade, objeto, est, hom in con.execute(
            "select pncp_id, mes, modalidade, orgao_cnpj, orgao, unidade, objeto, valor_estimado, "
            "valor_homologado from contratacoes_pncp"):
        valor = hom if hom and hom > 0 else (est or 0.0)
        out.append(_Compra(pid, mes or "", mod or "", cnpj or "", orgao or "", unidade or "", objeto or "",
                           float(valor or 0.0), inciso(amparos.get(pid)), pid in amparos, classes.get(pid),
                           bool(hom and hom > 0)))
    return out


def _por_valor(c: _Compra) -> bool | None:
    """True se é dispensa por valor (art. 75, I ou II); None se o amparo ainda não foi lido."""
    if c.amparo is not None:
        return c.amparo[0] == 75 and c.amparo[1] in ("I", "II")
    if "DISPENSA" not in _norm(c.modalidade):
        return False
    return None


def _obra(c: _Compra) -> bool:
    if c.amparo is not None and c.amparo[0] == 75 and c.amparo[1] in ("I", "II"):
        return c.amparo[1] == "I"
    return ramo(c.objeto) in RAMOS_DE_OBRA


def _dispensas(compras: list[_Compra], regra: Regra, achados: list[Achado], cobertura: dict) -> None:
    grupos: dict[tuple, list[_Compra]] = defaultdict(list)
    sem_ramo = sem_resultado = 0
    for c in compras:
        por_valor = _por_valor(c)
        if por_valor is False or not c.mes:
            continue
        ano = int(c.mes[:4])
        obra = _obra(c)
        limite, decreto = limite_de_dispensa(regra, ano, obra)
        if por_valor is None and c.valor > limite:
            continue  # dispensa sem amparo lido acima do limite: quase sempre outro inciso (emergência etc.)
        tipo_limite = "obras e engenharia" if obra else "compras e serviços"
        if por_valor and c.valor > limite + 0.005:
            achados.append(Achado("dispensa_acima", c.orgao_cnpj, c.orgao, c.id, c.mes,
                                  f"{c.objeto[:160]}: {c.valor:,.2f} por dispensa (art. 75, {c.amparo[1]}) "
                                  f"com limite de {limite:,.2f} em {ano} ({decreto})",
                                  c.valor, limite, {"amparo": f"art. 75, {c.amparo[1]}", "decreto": decreto}))
        elif limite * 0.98 <= c.valor <= limite + 0.005:
            achados.append(Achado("dispensa_no_teto", c.orgao_cnpj, c.orgao, c.id, c.mes,
                                  f"{c.objeto[:160]}: {c.valor:,.2f}, {c.valor / limite * 100:.1f}% do limite de "
                                  f"{tipo_limite} de {ano} ({limite:,.2f})", c.valor, limite,
                                  {"amparo_lido": c.amparo_lido}))
        if not c.homologada:
            sem_resultado += 1
            continue  # compra sem resultado homologado (deserta, fracassada, em curso) não entra na soma
        natureza = ramo(c.objeto) or (f"classe {c.classe} do catálogo" if c.classe else None)
        if natureza is None:
            sem_ramo += 1
            continue
        grupos[(c.orgao_cnpj, c.orgao, ano, natureza, obra)].append(c)
    cobertura["dispensas_sem_ramo"] = sem_ramo
    cobertura["dispensas_sem_resultado"] = sem_resultado
    for (cnpj, orgao, ano, natureza, obra), lista in grupos.items():
        if len(lista) < 2:
            continue
        limite, decreto = limite_de_dispensa(regra, ano, obra)
        lista.sort(key=lambda c: (c.mes, c.id))
        soma, mes_cruzou = 0.0, None
        for i, c in enumerate(lista):
            soma += c.valor
            if i and mes_cruzou is None and soma > limite + 0.005:   # a segunda compra em diante fecha a soma
                mes_cruzou = c.mes
        if mes_cruzou is None:
            continue
        sem_amparo = sum(1 for c in lista if not c.amparo_lido)
        achados.append(Achado(
            "fracionamento", cnpj, orgao, f"{cnpj}-{ano}-{natureza}", mes_cruzou,
            f"{len(lista)} dispensas de {natureza} em {ano} somam {soma:,.2f}, acima do limite de "
            f"{limite:,.2f} ({decreto})" + (f"; {sem_amparo} ainda sem o amparo lido" if sem_amparo else ""),
            round(soma, 2), limite,
            {"compras": [c.id for c in lista], "natureza": natureza, "ano": ano, "sem_amparo": sem_amparo}))


def _contratos(con: sqlite3.Connection) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for pid, mes, assin, cnpj, orgao, forn_ni, forn, objeto, valor in con.execute(
            "select pncp_id, mes, data_assinatura, orgao_cnpj, orgao, fornecedor_ni, fornecedor, objeto, "
            "valor_global from contratos_pncp"):
        out[pid] = {"id": pid, "mes": mes or "", "assinatura": assin or "", "cnpj": cnpj or "", "orgao": orgao or "",
                    "fornecedor_ni": forn_ni or "", "fornecedor": forn or "", "objeto": objeto or "",
                    "valor": float(valor or 0.0)}
    if _tabela(con, "pncp_contratos_detalhe"):
        for cid, compra, ini, glob, acum, vi, vf in con.execute(
                "select contrato_id, compra_id, valor_inicial, valor_global, valor_acumulado, vigencia_inicio, "
                "vigencia_fim from pncp_contratos_detalhe"):
            if cid in out:
                out[cid].update({"compra_id": compra, "valor_inicial": ini, "valor_global": glob,
                                 "valor_acumulado": acum, "vigencia_inicio": vi, "vigencia_fim": vf})
    return out


def _data(texto: str | None) -> date | None:
    try:
        return date.fromisoformat(str(texto)[:10]) if texto else None
    except ValueError:
        return None


def _emergenciais(con: sqlite3.Connection, contratos: dict[str, dict], amparos: dict[str, tuple],
                  achados: list[Achado]) -> None:
    termos = defaultdict(list)
    if _tabela(con, "pncp_termos"):
        for cid, dias, qv, data in con.execute(
                "select contrato_id, prazo_aditado_dias, qualif_vigencia, data_assinatura from pncp_termos"):
            termos[cid].append((dias or 0, qv or 0, data or ""))
    emerg = [c for c in contratos.values() if amparos.get(c.get("compra_id")) == (75, "VIII")]
    vistos: dict[tuple, list[dict]] = defaultdict(list)
    for c in sorted(emerg, key=lambda c: c["assinatura"]):
        problemas = []
        ini, fim = _data(c.get("vigencia_inicio")), _data(c.get("vigencia_fim"))
        if ini and fim and (fim - ini).days > 366:
            problemas.append(f"vigência de {(fim - ini).days} dias, acima de um ano")
        prorrog = [t for t in termos.get(c["id"], []) if t[0] > 0 or t[1]]
        if prorrog:
            problemas.append(f"{len(prorrog)} termo(s) de prorrogação, vedada no emergencial")
        chave = (c["cnpj"], c["fornecedor_ni"])
        if c["fornecedor_ni"] and vistos.get(chave):
            problemas.append(f"recontratação emergencial do mesmo fornecedor (antes: {vistos[chave][-1]['id']})")
        vistos[chave].append(c)
        if problemas:
            achados.append(Achado("emergencial", c["cnpj"], c["orgao"], c["id"], (c["assinatura"] or c["mes"])[:7],
                                  f"{c['fornecedor']}, {c['objeto'][:120]}: " + "; ".join(problemas),
                                  c.get("valor_global") or c["valor"], 0.0, {"problemas": problemas}))


def _aditivos(con: sqlite3.Connection, contratos: dict[str, dict], regra: Regra, achados: list[Achado],
              cobertura: dict) -> None:
    limite = float(regra.valor or 25.0)
    limite_reforma = float(regra.get("reforma", 50.0))
    acrescimos: dict[str, list[tuple]] = defaultdict(list)
    if _tabela(con, "pncp_termos"):
        for cid, valor, acresc, reaj, data in con.execute(
                "select contrato_id, valor_acrescido, acrescimo_supressao, qualif_reajuste, data_assinatura "
                "from pncp_termos"):
            if valor and valor > 0 and not (reaj and not acresc):  # reajuste não conta no limite do art. 125
                acrescimos[cid].append((float(valor), data or ""))
    sem_termo = 0
    for cid, c in contratos.items():
        inicial = c.get("valor_inicial") or 0.0
        if inicial <= 0:
            continue
        reforma = any(t in _norm(c["objeto"]) for t in REFORMA)
        teto = limite_reforma if reforma else limite
        lista = acrescimos.get(cid, [])
        soma = sum(v for v, _ in lista)
        pct = soma / inicial * 100.0
        if pct > teto + 0.01:
            mes = max((d for _, d in lista), default=c["mes"])[:7] or c["mes"]
            achados.append(Achado("aditivo", c["cnpj"], c["orgao"], cid, mes,
                                  f"{c['fornecedor']}, {c['objeto'][:120]}: acréscimos de {soma:,.2f} sobre "
                                  f"{inicial:,.2f} iniciais ({pct:.1f}%, limite {teto:g}%"
                                  f"{' por ser reforma' if reforma else ''})", round(soma, 2), inicial * teto / 100,
                                  {"pct": round(pct, 2), "termos": len(lista), "reforma": reforma}))
            continue
        atual = max(c.get("valor_global") or 0.0, c.get("valor_acumulado") or 0.0)
        if not lista and atual > inicial * (1 + teto / 100) + 0.005:
            sem_termo += 1
            achados.append(Achado("aditivo", c["cnpj"], c["orgao"], cid, c["mes"],
                                  f"{c['fornecedor']}, {c['objeto'][:120]}: valor atual {atual:,.2f} sobre "
                                  f"{inicial:,.2f} iniciais ({(atual / inicial - 1) * 100:.1f}%) sem termo aditivo "
                                  f"publicado no PNCP", round(atual - inicial, 2), inicial * teto / 100,
                                  {"pct": round((atual / inicial - 1) * 100, 2), "termos": 0, "sem_termo": True}))
    cobertura["aditivos_sem_termo_publicado"] = sem_termo


def _concentracao(contratos: dict[str, dict], mapa: MapaLegal, regra: Regra, achados: list[Achado]) -> None:
    minimo = int(regra.get("minimo_de_credores", 10))
    grupos: dict[tuple, list[Pagamento]] = defaultdict(list)
    meses: dict[tuple, str] = {}
    nomes: dict[str, str] = {}
    for c in contratos.values():
        if not c["fornecedor_ni"] or c["valor"] <= 0 or not c["mes"]:
            continue
        chave = (c["cnpj"], c["orgao"], c["mes"][:4])
        grupos[chave].append(Pagamento(c["fornecedor_ni"], c["valor"], date(int(c["mes"][:4]), 1, 1)))
        meses[chave] = max(meses.get(chave, ""), c["mes"])
        nomes[c["fornecedor_ni"]] = c["fornecedor"]
    for (cnpj, orgao, ano), pagamentos in grupos.items():
        r = concentracao(pagamentos, mapa=mapa)
        if r["credores"] < minimo or not r["concentrado"]:
            continue
        soma: Counter = Counter()
        for p in pagamentos:
            soma[p.credor] += p.valor
        maiores = [nomes.get(ni, ni) for ni, _ in soma.most_common(r["levam_o_corte"])]
        achados.append(Achado("concentracao", cnpj, orgao, f"{cnpj}-{ano}", meses[(cnpj, orgao, ano)],
                              f"{r['levam_o_corte']} de {r['credores']} fornecedores levam {r['corte_pct']:g}% dos "
                              f"{r['total']:,.2f} contratados em {ano}: " + ", ".join(maiores),
                              r["total"], 0.0, {**r, "ano": ano, "maiores": maiores}))


def _precos(con: sqlite3.Connection, mapa: MapaLegal, achados: list[Achado], cobertura: dict,
            orgaos: dict[str, tuple[str, str]]) -> None:
    if not (_tabela(con, "pncp_itens") and _tabela(con, "precos_referencia")):
        return
    # Serviço contratado por lote (uma "unidade" que é o contrato inteiro) não tem preço unitário:
    # compará-lo com a mediana do país mede o tamanho do lote, não o preço. Sai dos dois lados.
    # Acima de 20 vezes a mediana a unidade também não é a mesma (lote, caixa, kit) e não vira
    # indício de sobrepreço: fica contada na cobertura (27/11: 514 de 770 "sobrepreços" eram isso).
    fator = float(mapa.regra("PRECO-MEDIANA").get("fator_de_unidade", 20))
    refs: dict[tuple, list[tuple[float, str]]] = defaultdict(list)
    for cat, sem, preco, unid, mun, esfera, ms, qtd in con.execute(
            "select catalogo, semestre, preco, unidade, municipio, esfera, material_servico, quantidade "
            "from precos_referencia where preco > 0"):
        if _norm(mun) == "GOIANIA" and _norm(esfera).startswith("M"):
            continue  # a referência é o país, não a própria prefeitura
        if _por_lote(ms, qtd):
            continue
        refs[(int(cat), sem)].append((float(preco), _unidade(unid)))
    comparados = sem_ref = por_lote = incompativel = 0
    for cid, n, cnpj, desc, cat, unid, unit, data, forn, ms, qtd in con.execute(
            "select compra_id, numero_item, orgao_cnpj, descricao, catalogo, unidade_medida, "
            "coalesce(unitario_resultado, unitario_estimado), coalesce(data_resultado, data_inclusao), fornecedor, "
            "material_servico, coalesce(quantidade_resultado, quantidade) "
            "from pncp_itens where catalogo is not null and coalesce(unitario_resultado, unitario_estimado) > 0"):
        if not data:
            continue
        if _por_lote(ms, qtd):
            por_lote += 1
            continue
        lista = refs.get((int(cat), _semestre(data)), [])
        u = _unidade(unid)
        mesma = [p for p, ru in lista if ru == u] if u else []
        c = comparar(desc or f"item {cat}", float(unit), mesma, mapa=mapa)
        if c is None:
            sem_ref += 1
            continue
        if c.mediana and c.preco > c.mediana * fator:
            incompativel += 1
            continue
        comparados += 1
        if c.destoa:
            orgao = orgaos.get(cid, (cnpj, cnpj))
            achados.append(Achado("preco", orgao[0], orgao[1], f"{cid}-{n}", data[:7],
                                  f"{(desc or '')[:100]} ({forn or 'fornecedor não informado'}): {c.preco:,.2f} por "
                                  f"{unid or 'unidade'}, mediana nacional {c.mediana:,.2f} em {c.amostra} compras; "
                                  f"{c.motivo}", c.preco, c.mediana, {"comparacao": c, "catalogo": int(cat)}))
    cobertura["itens_comparados_com_o_pais"] = comparados
    cobertura["itens_sem_referencia_suficiente"] = sem_ref
    cobertura["servicos_contratados_por_lote"] = por_lote
    cobertura["itens_com_unidade_incompativel"] = incompativel


def _por_lote(material_servico, quantidade) -> bool:
    return (material_servico or "").upper() == "S" and quantidade is not None and float(quantidade) <= 1


def _notas(con: sqlite3.Connection, contratos: dict[str, dict], achados: list[Achado], cobertura: dict) -> None:
    if not _tabela(con, "pncp_cobrancas"):
        return
    cobrado = {cid: (v or 0.0, n, ult or "") for cid, v, n, ult in con.execute(
        "select contrato_id, sum(valor_nf), count(*), max(data_emissao) from pncp_cobrancas "
        "where coalesce(evento, '') not like '%ancel%' group by 1")}
    cobertura["contratos_com_nota_fiscal"] = len(cobrado)
    _notas_ausentes(con, contratos, cobrado, achados, cobertura)
    for cid, (valor, n, ult) in cobrado.items():
        c = contratos.get(cid)
        if not c:
            continue
        contratado = max(c.get("valor_global") or 0.0, c.get("valor_acumulado") or 0.0, c["valor"])
        if contratado > 0 and valor > contratado * 1.0001:
            achados.append(Achado("nota_acima", c["cnpj"], c["orgao"], cid, (ult or c["mes"])[:7],
                                  f"{c['fornecedor']}: {n} nota(s) fiscal(is) somam {valor:,.2f} para um contrato "
                                  f"de {contratado:,.2f}", round(valor - contratado, 2), contratado,
                                  {"notas": n, "cobrado": valor}))
    if not (_tabela(con, "pncp_nf_itens") and _tabela(con, "pncp_itens")):
        return
    for cid, desc, ncm, unit, qtd in con.execute(
            "select contrato_id, descricao, ncm, unitario, quantidade from pncp_nf_itens where ncm is not null "
            "and unitario > 0"):
        c = contratos.get(cid)
        if not c or not c.get("compra_id"):
            continue
        linha = con.execute(
            "select max(unitario_resultado) from pncp_itens where compra_id = ? and ncm = ? and "
            "(fornecedor_ni = ? or fornecedor_ni is null)", (c["compra_id"], ncm, c["fornecedor_ni"])).fetchone()
        homologado = linha[0] if linha else None
        if homologado and unit > homologado * 1.01:
            achados.append(Achado("nota_preco", c["cnpj"], c["orgao"], cid, c["mes"],
                                  f"{c['fornecedor']}, {(desc or '')[:80]}: nota a {unit:,.2f} a unidade, "
                                  f"homologado a {homologado:,.2f}", round((unit - homologado) * (qtd or 1), 2),
                                  float(homologado), {"ncm": ncm}))


def _notas_ausentes(con: sqlite3.Connection, contratos: dict[str, dict], cobrado: dict, achados: list[Achado],
                    cobertura: dict) -> None:
    """A fonte certifica por si: o órgão cujos meses o motor leu no PNCP sem achar nenhuma nota fiscal
    de nenhum dos seus contratos não publicou o que a lei manda publicar (Lei 14.133/2021, art. 174,
    § 2º, VI). Mês não lido não conta: falta de leitura é lacuna do sistema, não do Município."""
    if not _tabela(con, "meta"):
        return
    linha = con.execute("select valor from meta where chave = 'pncp_detalhe_lidos'").fetchone()
    if not linha:
        return
    try:
        lidos = json.loads(linha[0])
    except (TypeError, ValueError):
        return
    meses: dict[str, list[str]] = defaultdict(list)
    for chave in lidos:
        partes = chave.split()
        if len(partes) == 3 and partes[0] == "cobrancas":
            meses[partes[1]].append(partes[2])
    por_orgao: dict[str, list[dict]] = defaultdict(list)
    for c in contratos.values():
        por_orgao[c["cnpj"]].append(c)
    sem = 0
    for cnpj, lista in por_orgao.items():
        lidos_do_orgao = sorted(meses.get(cnpj, []))
        if not lidos_do_orgao or any(c["id"] in cobrado for c in lista):
            continue
        no_periodo = [c for c in lista if c["mes"] and lidos_do_orgao[0] <= c["mes"] <= lidos_do_orgao[-1]]
        if not no_periodo:
            continue
        sem += 1
        total = sum(c["valor"] for c in no_periodo)
        achados.append(Achado("nf_ausente", cnpj, no_periodo[0]["orgao"], f"{cnpj}-notas", lidos_do_orgao[-1],
                              f"o PNCP foi lido em {len(lidos_do_orgao)} meses ({lidos_do_orgao[0]} a "
                              f"{lidos_do_orgao[-1]}) e não traz nenhuma nota fiscal "
                              + ("do contrato assinado no período, de " if len(no_periodo) == 1 else
                                 f"dos {len(no_periodo)} contratos assinados no período, que somam ")
                              + f"{total:,.2f}",
                              total, 0.0, {"meses": len(lidos_do_orgao), "contratos": len(no_periodo),
                                                "desde": lidos_do_orgao[0]}))
    cobertura["orgaos_sem_nota_fiscal_publicada"] = sem


def conferir(banco: Path | sqlite3.Connection, *, mapa: MapaLegal | None = None) -> Conferencias:
    """Roda todas as conferências de compras no banco histórico."""
    mapa = mapa or carregar()
    con = banco if isinstance(banco, sqlite3.Connection) else _partes.conectar_leitura(banco)
    try:
        out = Conferencias()
        if not _tabela(con, "contratacoes_pncp"):
            out.cobertura["sem_dados"] = True
            return out
        compras = _compras(con)
        amparos = {c.id: c.amparo for c in compras if c.amparo}
        orgaos = {c.id: (c.orgao_cnpj, c.orgao) for c in compras}
        _dispensas(compras, mapa.regra("DISPENSA-LIMITE"), out.achados, out.cobertura)
        contratos = _contratos(con) if _tabela(con, "contratos_pncp") else {}
        _emergenciais(con, contratos, amparos, out.achados)
        _aditivos(con, contratos, mapa.regra("ADITIVO-LIMITE"), out.achados, out.cobertura)
        _concentracao(contratos, mapa, mapa.regra("CONCENTRACAO"), out.achados)
        _precos(con, mapa, out.achados, out.cobertura, orgaos)
        _notas(con, contratos, out.achados, out.cobertura)
        _cobertura(con, compras, contratos, out.cobertura)
        out.achados.sort(key=lambda a: (a.mes, a.tipo, a.chave))
        return out
    finally:
        if not isinstance(banco, sqlite3.Connection):
            con.close()


def _cobertura(con: sqlite3.Connection, compras: list[_Compra], contratos: dict[str, dict], cob: dict) -> None:
    dispensas = [c for c in compras if any(t in _norm(c.modalidade) for t in ("DISPENSA", "INEXIGIBILIDADE"))]
    da = [c for c in dispensas if da_pasta(c.orgao)]
    cob["compras"] = len(compras)
    cob["dispensas_e_inexigibilidades"] = len(dispensas)
    cob["amparo_lido"] = sum(1 for c in dispensas if c.amparo_lido)
    cob["contratos"] = len(contratos)
    cob["contratos_com_detalhe"] = sum(1 for c in contratos.values() if c.get("valor_inicial") is not None)
    cob["itens"] = _contar(con, "select count(*) from pncp_itens")
    cob["itens_com_catalogo"] = _contar(con, "select count(*) from pncp_itens where catalogo is not null")
    cob["termos"] = _contar(con, "select count(*) from pncp_termos")
    cob["precos_nacionais"] = _contar(con, "select count(*) from precos_referencia")
    cob["notas_fiscais"] = _contar(con, "select count(*) from pncp_cobrancas")
    lacunas = []
    sem = [c for c in da if not c.amparo_lido]
    if sem:
        lacunas.append(f"{len(sem)} de {len(da)} dispensas e inexigibilidades da pasta sem o amparo legal lido")
    contratos_da = [c for c in contratos.values() if da_pasta(c["orgao"])]
    sem_det = [c for c in contratos_da if c.get("valor_inicial") is None]
    if sem_det:
        lacunas.append(f"{len(sem_det)} de {len(contratos_da)} contratos da pasta sem o detalhe "
                       "(valor inicial, vigência e aditivos)")
    cob["lacunas_da_pasta"] = lacunas


# --- Fichas -----------------------------------------------------------------------------------

def ficha(a: Achado, competencia: str | None = None) -> Ficha | None:
    if a.tipo == "preco":
        return ficha_de_sobrepreco(a.dados["comparacao"], contrato=a.chave, competencia=competencia)
    base = {
        "dispensa_acima": dict(
            familia=Familia.PRC, gravidade="alta", norma="Lei 14.133/2021, art. 75, I e II; " + a.dados.get("decreto", ""),
            como_deveria="A dispensa por valor só cabe até o limite do ano, atualizado por decreto.",
            niveis=[Nivel.C], providencia="Pedir o processo da dispensa, a justificativa do valor e a pesquisa "
                                          "de preços."),
        "dispensa_no_teto": dict(
            familia=Familia.PRC, gravidade="media", norma="Lei 14.133/2021, art. 75, I e II, e § 1º",
            como_deveria="A compra é dimensionada pela necessidade, não pelo limite que dispensa a licitação; "
                         "valor colado no teto pede a memória do quantitativo.",
            niveis=[Nivel.C], providencia="Pedir a memória de cálculo do quantitativo e as demais dispensas do "
                                          "mesmo ramo no exercício."),
        "fracionamento": dict(
            familia=Familia.PRC, gravidade="alta", norma="Lei 14.133/2021, art. 75, § 1º",
            como_deveria="As dispensas de objetos da mesma natureza, no mesmo órgão e exercício, somam-se para o "
                         "limite; passando dele, a regra é licitar.",
            niveis=[Nivel.C], providencia="Pedir o planejamento anual de compras (PCA) e os processos das "
                                          "dispensas somadas."),
        "emergencial": dict(
            familia=Familia.PRC, gravidade="alta", norma="Lei 14.133/2021, art. 75, VIII",
            como_deveria="A contratação emergencial dura no máximo um ano, sem prorrogação e sem recontratar a "
                         "mesma empresa.",
            niveis=[Nivel.C], providencia="Pedir o processo emergencial, a caracterização da emergência e o "
                                          "andamento da licitação definitiva."),
        "aditivo": dict(
            familia=Familia.PRC, gravidade="alta", norma="Lei 14.133/2021, art. 125",
            como_deveria="Os acréscimos não passam de 25% do valor inicial atualizado (50% na reforma), e cada "
                         "alteração é publicada como termo aditivo.",
            niveis=[Nivel.C], documento_faltante=bool(a.dados.get("sem_termo")),
            providencia="Pedir os termos aditivos, as justificativas técnicas e as planilhas de acréscimo."),
        "concentracao": dict(
            familia=Familia.PRC, gravidade="media", norma="CF, art. 37, caput (impessoalidade)",
            como_deveria="Os contratos do órgão se distribuem entre fornecedores pela competição, sem que poucos "
                         "levem quase tudo.",
            niveis=[Nivel.C], providencia="Pedir as licitações dos maiores contratos e a lista de participantes."),
        "nota_acima": dict(
            familia=Familia.ENT, gravidade="alta", norma="Lei 4.320/1964, arts. 62 e 63; Lei 14.133/2021, art. 125",
            como_deveria="O que o fornecedor fatura cabe no valor contratado com os aditivos publicados.",
            niveis=[Nivel.B, Nivel.C], providencia="Pedir as liquidações e os atestos das notas e os aditivos "
                                                   "que as cobrem."),
        "nf_ausente": dict(
            familia=Familia.ENT, gravidade="media", norma="Lei 14.133/2021, art. 174, § 2º, VI; Lei 12.527/2011, art. 8º",
            como_deveria="As notas fiscais eletrônicas de cada contrato ficam no PNCP, onde qualquer um confere o "
                         "que foi cobrado contra o que foi contratado.",
            niveis=[Nivel.F], documento_faltante=True,
            providencia="Pedir por LAI as notas fiscais e as liquidações dos contratos do período e cobrar a "
                        "publicação no PNCP."),
        "nota_preco": dict(
            familia=Familia.ENT, gravidade="alta", norma="Lei 4.320/1964, art. 63; Lei 14.133/2021, art. 92, V",
            como_deveria="A nota fiscal cobra o preço homologado no contrato.",
            niveis=[Nivel.B, Nivel.C], providencia="Pedir a liquidação da nota e o termo que alterou o preço, "
                                                   "se houver."),
    }.get(a.tipo)
    if base is None:
        return None
    codigo = {"dispensa_acima": "PRC-DISP01", "dispensa_no_teto": "PRC-DISP02", "fracionamento": "PRC-FRAC01",
              "emergencial": "PRC-EMERG01", "aditivo": "PRC-SOB04", "concentracao": "PRC-CONC01",
              "nota_acima": "ENT-NF01", "nota_preco": "ENT-NF02", "nf_ausente": "ENT-NF00"}[a.tipo]
    return emitir(codigo=f"{codigo}-{a.chave}", titulo=f"{TITULOS[a.tipo]}: {a.orgao.title()}",
                  como_esta=a.descricao[:1].upper() + a.descricao[1:] + ".", competencia=competencia, **base)
