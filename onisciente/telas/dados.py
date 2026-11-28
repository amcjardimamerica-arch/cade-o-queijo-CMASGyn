"""Os dados de cada tela, tirados do banco histórico e dos módulos do Onisciente.

Nada aqui vai à rede. Cada número sai como ``{"v": valor, "f": chave_da_fonte}``; a chave aponta para a
tabela de originais (``originais.py``), que diz de onde veio o número e onde está o original. Os
recortes globais (período e secretaria) são feitos assim: os dados vão por mês e por órgão, e a página
soma o que o recorte pede.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from .. import RAIZ, __version__, rastreio
from ..config import Alvo
from ..legal.mapa import MapaLegal
from ..nucleo.estacoes import Estacao, Evento, Percurso
from ..nucleo.indicios import Familia
from ..nucleo.provas import Nivel
from ..rio import matriz as mz
from ..rio import municipio
from ..rio.fontes import classificar
from . import originais as og
from .base import (CNPJ, FUNCOES, N, consultar, documento_publico, fim_do_mes, funcao_do_orgao, limpa, mes_menos,
                   rotulo_mes, sem_acento, sem_travessao, tabela_existe)

ENTRADAS = RAIZ / "relatorios" / "onisciente" / "entradas"
NOMEACOES = RAIZ / "referencias" / "servidores" / "nomeacoes.json"
JANELA = 12   # meses de compras e contratos que contam para uma competência (como no parecer)

# As etapas do gasto público, na ordem em que o dinheiro anda. Cada etapa tem um ícone próprio (desenhado
# em app.js), as estações da trilha que a comprovam e os temas de desconformidade que caem nela.
ETAPAS = (
    # id, nome, o que se confere, estações da trilha, temas
    ("origem", "Origem do dinheiro", "Receita e repasses, recurso vinculado ou livre", (1, 2), ("vinculo", "cosip", "fnas")),
    ("orcamento", "Orçamento", "Previsão, dotação, pisos e tetos", (3, 4), ("pisos", "orcamento")),
    ("contratacao", "Contratação", "Licitação, contrato, empresa e preço", (5, 6), ("empresas", "precos")),
    ("liquidacao", "Liquidação", "A entrega comprovada por nota fiscal", (7,), ("notas",)),
    ("pagamento", "Pagamento", "O dinheiro que saiu e o que deixou de sair", (8,), ("execucao", "pessoal")),
    ("prestacao", "Prestação de contas", "Contas entregues, julgadas e publicadas", (9,), ("contas", "selo", "oficios")),
)

PAGINAS = (
    # arquivo, título, grupo (a etapa ou a consulta), pergunta
    ("index", "Início", "Início", "O que está fora da regra no mês, etapa por etapa"),
    ("origem", "Origem do dinheiro", "Origem do dinheiro", "De onde veio o dinheiro, vinculado ou livre, e onde foi empenhado"),
    ("pisos", "Pisos e tetos", "Orçamento", "Os percentuais da Constituição e da LRF, pelo cálculo próprio"),
    ("tempo", "Previsto e realizado", "Orçamento", "Previsto e realizado desde 2019 e a projeção até o fim do PPA"),
    ("empresas", "Contratos e empresas", "Contratação", "Quem recebeu, quem administra e se podia contratar"),
    ("precos", "Preço e entrega", "Contratação", "Preço pago, entrega comprovada e conta prestada"),
    ("trilha", "Execução", "Liquidação e pagamento", "Em quais das nove etapas da despesa o dinheiro tem documento"),
    ("pessoal", "Pessoal", "Liquidação e pagamento", "A despesa com pessoal perto do limite e o que deixou de ser pago"),
    ("contas", "Contas", "Prestação de contas", "As contas entregues e julgadas no prazo"),
    ("transparencia", "Transparência", "Prestação de contas", "O selo auditado, o que falta publicar e os ofícios prontos"),
    ("indicios", "Desconformidades", "Consulta", "Todas as desconformidades, por etapa, condição, gravidade e secretaria"),
    ("secretarias", "Secretarias", "Consulta", "Quanto cada secretaria contratou e quanto destoa"),
    ("leis", "Normas", "Consulta", "A régua de cada conferência e onde está a norma"),
)

# Os temas de desconformidade: cada ficha cai em um tema, cada tema numa etapa e numa tela (e numa seção dela).
TEMAS = {
    "selo": ("Selo de transparência", "transparencia", "selo",
             "O selo declarado contra o refeito pelo Onisciente, e o que deixou de ser publicado"),
    "vinculo": ("Vinculado fora da finalidade", "origem", "desvios", "Recurso vinculado empenhado fora da finalidade da lei"),
    "cosip": ("COSIP", "origem", "cosip", "A contribuição da iluminação pública empenhada em outras funções"),
    "fnas": ("FNAS e o Fundo", "origem", "fnas", "O que a União mandou contra o que entrou na fonte da assistência"),
    "pisos": ("Pisos e tetos", "pisos", "medidas", "Os percentuais da Constituição e da LRF pelo cálculo próprio"),
    "precos": ("Preços", "precos", "preco", "Preço unitário acima da mediana das compras do país"),
    "empresas": ("Contratos e empresas", "empresas", "fornecedores",
                 "Dispensas no teto, fracionamento, aditivos, concentração e a Receita Federal"),
    "notas": ("Notas fiscais", "precos", "notas", "Notas fiscais dos contratos nunca publicadas no PNCP"),
    "execucao": ("Execução", "trilha", "estacoes", "Empenho, liquidação e pagamento sem documento publicado"),
    "pessoal": ("Pessoal", "pessoal", "fichas", "A despesa com pessoal e o que a lei manda pagar e não foi pago"),
    "contas": ("Contas", "contas", "fichas", "Contas e prestações não apresentadas ou não julgadas no prazo"),
    "orcamento": ("Orçamento e receita", "tempo", "fichas", "Previsão, dotação e ritmo da arrecadação"),
    "oficios": ("Normas e ofícios", "transparencia", "oficios", "Fundamento revogado, norma ausente e o ofício pronto"),
    "sistema": ("Falhas de leitura do sistema", "transparencia", "falhas",
                "O que o próprio Onisciente não conseguiu ler; nunca é imputado ao Município"),
}

ETAPA_DO_TEMA = {tema: e[0] for e in ETAPAS for tema in e[4]}

# As três condições, com o mesmo ícone em todas as telas: conforme, alerta (com gravidade) e sem dado.
# Sem dado é a falta de transparência (o documento que a lei manda publicar e não está publicado) ou a
# leitura que o próprio sistema não fez (esta em cinza, nunca imputada ao Município).
_SEM_DADO = re.compile(r"não publicad|nunca publicad|sem publicação|sem edição|não divulgad|não localizad"
                       r"|não apresentad|não conferid|ainda incompleta", re.I)


def condicao_da_ficha(codigo: str, tema: str, titulo: str) -> str:
    """``sem_dado`` para a ausência de documento e a falha de leitura; ``alerta`` para o indício."""
    c = sem_acento(codigo)
    if tema in ("selo", "notas", "sistema") or c.startswith(("PUB", "ENT-NF", "SIS", "SYS")):
        return "sem_dado"
    return "sem_dado" if _SEM_DADO.search(titulo or "") else "alerta"


_TEMA_DA_FAMILIA = {"RIO": "vinculo", "PISO": "pisos", "ORC": "orcamento", "VIN": "execucao", "PRC": "empresas",
                    "ENT": "execucao", "PCT": "contas", "PES": "pessoal", "CTA": "contas", "SIS": "sistema"}


def tema_da_ficha(codigo: str, familia: str) -> str:
    c = sem_acento(codigo)
    if "-751-" in c or "COSIP" in c:
        return "cosip"
    if "FNAS" in c or "-660-" in c or c.startswith(("IGD", "CMAS", "FMAS", "REC-", "EMD")):
        return "fnas"
    if c.startswith("ENT-NF"):
        return "notas"
    if c.startswith("PRC-SOB") and not c.startswith("PRC-SOB04"):
        return "precos"
    regras = (("PRC-", "empresas"), ("PES", "pessoal"), ("CTA", "contas"), ("ATA", "contas"), ("PUB", "selo"),
              ("LEG", "oficios"), ("SYS", "sistema"), ("SIS", "sistema"), ("EXE", "execucao"), ("DES", "execucao"),
              ("ENT", "execucao"), ("VIAS", "pisos"), ("PISO", "pisos"), ("RIO-RECEITA", "orcamento"),
              ("RIO", "vinculo"), ("VIN", "vinculo"))
    for prefixo, tema in regras:
        if c.startswith(prefixo):
            return tema
    return _TEMA_DA_FAMILIA.get(familia, "sistema")


@dataclass
class Contexto:
    con: object
    banco: Path
    alvo: Alvo
    alvo_id: str
    mapa: MapaLegal
    originais: og.Originais
    panoramas: dict[str, dict] = field(default_factory=dict)
    entradas: dict[str, dict] = field(default_factory=dict)
    hoje: date = field(default_factory=date.today)
    alvos: list[dict] = field(default_factory=list)
    _cache: dict = field(default_factory=dict)

    # --- as entradas das outras frentes -----------------------------------------------------
    _LISTA_DA_ENTRADA = {"execucao": "empenhos", "federais": "repasses", "empresas": "empresas"}

    def entrada(self, nome: str) -> dict | None:
        """A entrada só quando ela traz dado: a que diz ``coleta_nao_feita`` (ou vem com a lista vazia) vale
        como ausente, para a tela mostrar o quadro cinza e nunca cobrar do Município o que o sistema não leu."""
        e = self.entradas.get(nome)
        if not e or e.get("situacao") == "coleta_nao_feita":
            return None
        lista = self._LISTA_DA_ENTRADA.get(nome)
        if lista and not e.get(lista) and not (nome == "federais" and e.get("emendas")):
            return None
        return e

    def coletas(self) -> dict[str, dict]:
        """A situação de cada entrada lida (dado ou coleta ainda não feita), para os quadros das telas."""
        out = {}
        for nome, e in self.entradas.items():
            out[nome] = {"situacao": "dado" if self.entrada(nome) else "coleta_nao_feita",
                         "motivo": sem_travessao(str(e.get("motivo") or "")), "gerado_em": e.get("gerado_em", "")}
        return out

    # --- o que várias telas usam -----------------------------------------------------------
    def meses_msc(self) -> list[str]:
        if "msc" not in self._cache:
            self._cache["msc"] = sorted(m for (m,) in consultar(
                self.con, "SELECT mes FROM msc_meses WHERE situacao = 'entregue'"))
        return self._cache["msc"]

    def competencias(self) -> list[str]:
        return sorted(set(self.meses_msc()) | set(self.panoramas))

    def padrao(self) -> str:
        if self.panoramas:
            return max(self.panoramas)
        cs = self.competencias()
        return cs[-1] if cs else f"{self.hoje.year}-{self.hoje.month:02d}"

    def do_ano(self, c: str) -> list[str]:
        return [m for m in self.meses_msc() if m[:4] == c[:4] and m <= c]

    def orgaos(self) -> dict[str, str]:
        """CNPJ -> nome de cada órgão do Município que aparece no PNCP ou no alvo."""
        if "orgaos" not in self._cache:
            nomes: dict[str, str] = {}
            for cnpj, nome in consultar(self.con, "SELECT orgao_cnpj, orgao FROM contratos_pncp "
                                                  "UNION SELECT orgao_cnpj, orgao FROM contratacoes_pncp"):
                if cnpj and nome:
                    nomes.setdefault(cnpj, limpa(nome))
            meta = consultar(self.con, "SELECT valor FROM meta WHERE chave = 'pncp_orgaos'")
            if meta:
                try:
                    for cnpj, nome in json.loads(meta[0][0] or "{}").items():
                        nomes.setdefault(cnpj, limpa(nome))
                except (ValueError, AttributeError):
                    pass
            for cnpj in self.alvo.pncp_cnpjs:
                nomes.setdefault(cnpj, cnpj)
            self._cache["orgaos"] = nomes
        return self._cache["orgaos"]

    def compras(self):
        if "compras" not in self._cache:
            from ..conferencias import compras
            self._cache["compras"] = compras.conferir(self.con, mapa=self.mapa)
        return self._cache["compras"]

    def fiscal(self, c: str):
        chave = ("fiscal", c)
        if chave not in self._cache:
            from ..fiscal import medir_municipio
            try:
                self._cache[chave] = medir_municipio(fim_do_mes(c), banco=self.banco, mapa=self.mapa,
                                                     faixa_camara=self.alvo.faixa_camara)
            except Exception as erro:  # noqa: BLE001 - uma tela não pode derrubar as outras
                from ..fiscal import Fiscal
                f = Fiscal()
                f.notas.append(f"A medição do Município falhou nesta competência: {erro}.")
                self._cache[chave] = f
        return self._cache[chave]


def nome_orgao(nome: str) -> str:
    """O nome do órgão como se lê, sem caixa alta."""
    pequenas = {"de", "da", "do", "das", "dos", "e", "a", "o"}
    siglas = {"FMAS", "IMAS", "AMMA", "AR", "SEFIN", "FMSB", "PGM"}
    out = []
    for i, p in enumerate(limpa(nome).split(" ")):
        if p.upper() in siglas or (p.isupper() and len(p) <= 4 and "-" in nome and i > 0 and p.isalpha()
                                   and p.upper() in nome.split("-")[-1].upper()):
            out.append(p.upper())
        elif p.lower() in pequenas and i:
            out.append(p.lower())
        else:
            out.append(p.capitalize())
    return " ".join(out)


# =============================================================================================
# Comum a todas as páginas
# =============================================================================================

def secretarias(ctx: Contexto) -> list[dict]:
    from ..conferencias.compras import da_pasta
    out = []
    for cnpj, nome in sorted(ctx.orgaos().items(), key=lambda kv: nome_orgao(kv[1])):
        f = funcao_do_orgao(nome)
        out.append({"id": cnpj, "nome": nome_orgao(nome), "funcao": f, "pasta": da_pasta(nome)})
    return out


def comum(ctx: Contexto) -> dict:
    a = ctx.alvo
    return {
        "alvo": {"id": ctx.alvo_id, "nome": a.nome, "municipio": a.municipio, "uf": a.uf, "ibge": a.ibge},
        "alvos": ctx.alvos,
        "competencias": ctx.competencias(),
        "padrao": ctx.padrao(),
        "pareceres": sorted(ctx.panoramas),
        "secretarias": secretarias(ctx),
        "funcoes": FUNCOES,
        "paginas": [{"id": p, "titulo": t, "grupo": g, "pergunta": q} for p, t, g, q in PAGINAS],
        "etapas": [{"id": i, "nome": n, "confere": c, "estacoes": list(es), "temas": list(ts)}
                   for i, n, c, es, ts in ETAPAS],
        "gerado_em": ctx.hoje.isoformat(),
        "versao": __version__,
        "dominio": {d.id: {"nome": d.nome, "funcao": d.funcao} for d in ctx.alvo.ativos()},
        "rastreio": cadeia(ctx.con),
    }


def cadeia(con) -> dict:
    """O topo da cadeia do rastreio por hash, para o rodapé de todas as páginas (só leitura). Sem
    ``rastreio.db`` ao lado do banco (banco ainda não migrado), ``{"rastreado": False}``, sem erro."""
    if con is None:
        return {"rastreado": False}
    try:
        r = rastreio.resumo_da_cadeia(con)
    except Exception as e:  # noqa: BLE001 - o rodapé nunca derruba a geração das telas
        return {"rastreado": False, "erro": str(e)}
    if not r.get("rastreado"):
        return {k: v for k, v in r.items() if k in ("rastreado", "erro")}
    u = r.get("ultima") or {}
    return {"rastreado": True, "ok": bool(r.get("ok")), "rodadas": r.get("rodadas", 0),
            "problemas": len(r.get("problemas") or []),
            "ultima": {k: u.get(k) for k in ("id", "modo", "inicio", "fim", "respostas", "registros", "raiz", "hash")}}


def rastreio_da_ficha(f: dict) -> dict:
    """Os hashes de um achado, como no parecer: o do próprio achado (a ficha sem a chave ``rastreio``) e o
    do conjunto das provas em que ele se apoia (o registro de cada original, ou o sha256 da resposta;
    um só, o próprio hash; vários, a raiz de Merkle em ordem; nenhum, vazio, porque a falta é o achado)."""
    r = f.get("rastreio") if isinstance(f.get("rastreio"), dict) else {}
    provas: list[str] = []
    for h in [*(r.get("apoio") or []), *(f.get("apoio") or []),
              *((o.get("registro") or o.get("sha256")) for o in f.get("custodia") or [])]:
        if h and h not in provas:
            provas.append(h)
    apoio = r.get("hash_apoio") or (provas[0] if len(provas) == 1 else rastreio.raiz_de(provas) if provas else "")
    return {"achado": r.get("hash_achado") or rastreio.hash_achado(f), "apoio": apoio, "provas": provas}


# =============================================================================================
# Origem do dinheiro (receita por espécie e fonte, e o empenhado por função)
# =============================================================================================

def _classe(fonte: str) -> str:
    f = classificar(fonte)
    if f.vinculada is None:
        return "sem_catalogo"
    return "vinculada" if f.vinculada else "livre"


def _empenhos_mes(ctx: Contexto) -> dict[str, list[tuple[str, str, float]]]:
    """(fonte, função, empenhado) de cada mês da matriz, exceto intraorçamentário."""
    if "emp" not in ctx._cache:
        out: dict[str, list] = defaultdict(list)
        for mes, fonte, funcao, v in consultar(ctx.con, (
                "SELECT mes, fonte_recursos, funcao, SUM(CASE WHEN natureza_conta = 'C' THEN valor ELSE -valor END) "
                "FROM msc_itens WHERE conta_contabil LIKE '62213%' AND substr(natureza_despesa, 3, 2) != '91' "
                "GROUP BY 1, 2, 3")):
            if v:
                out[mes].append((str(fonte or ""), str(funcao or "").zfill(2), float(v)))
        ctx._cache["emp"] = out
    return ctx._cache["emp"]


def _fonte_ano(ctx: Contexto, c: str) -> str:
    """Fonte composta: a matriz de janeiro até a competência (soma dos meses)."""
    meses = ctx.do_ano(c)
    chave = f"msc_ano:{c}"
    if chave not in ctx.originais.tabela:
        ultimo = og.msc(ctx.originais, meses[-1]) if meses else None
        base = ctx.originais.tabela.get(ultimo) if ultimo else None
        rotulo = (f"Matriz de saldos contábeis, soma de {rotulo_mes(meses[0])} a {rotulo_mes(meses[-1])}"
                  if meses else f"Matriz de saldos contábeis de {c[:4]}")
        nota = ("Soma das matrizes de cada mês do exercício; o original aberto é o do último mês, e os "
                "demais estão na tela Origem do dinheiro, mês a mês.") if meses else ""
        if base and base.url:
            ctx.originais.externo(chave, rotulo, base.url, sha256=base.sha256, quando=base.quando, nota=nota,
                                  registro=base.registro, confere=base.confere)
        else:
            ctx.originais.sem_original(chave, rotulo, nota)
    return chave


def _fonte_transf_ano(ctx: Contexto, c: str) -> str:
    meses = ctx.do_ano(c)
    chave = f"transf_ano:{c}"
    if chave not in ctx.originais.tabela:
        ultimo = og.transferencias(ctx.originais, meses[-1]) if meses else None
        base = ctx.originais.tabela.get(ultimo) if ultimo else None
        rotulo = f"Portal da Transparência: transferências da União, {c[:4]} até {rotulo_mes(c)}"
        nota = "Soma dos arquivos mensais do Portal; o original aberto é o do último mês."
        if base and base.url:
            ctx.originais.externo(chave, rotulo, base.url, sha256=base.sha256, quando=base.quando, nota=nota,
                                  registro=base.registro, confere=base.confere)
        else:
            ctx.originais.sem_original(chave, rotulo, nota)
    return chave


def rio(ctx: Contexto) -> dict:
    meses = ctx.meses_msc()
    especies = list(municipio.CORRENTES) + list(municipio.CAPITAL)
    por_mes: dict[str, dict] = {m: {"a": defaultdict(float), "b": defaultdict(float), "fr": defaultdict(float),
                                    "fe": defaultdict(float)} for m in meses}
    for i, e in enumerate(especies):
        for (fonte, mes), v in mz.receita_por_fonte_e_mes(ctx.con, e.natureza, meses).items():
            if mes in por_mes and v:
                por_mes[mes]["a"][(i, _classe(fonte))] += v
                por_mes[mes]["fr"][fonte] += v
    for mes, linhas in _empenhos_mes(ctx).items():
        if mes not in por_mes:
            continue
        for fonte, funcao, v in linhas:
            por_mes[mes]["b"][(_classe(fonte), funcao)] += v
            por_mes[mes]["fe"][fonte] += v
    saida_meses = {}
    for m, d in por_mes.items():
        fontes = sorted(set(d["fr"]) | set(d["fe"]), key=lambda f: -(abs(d["fr"].get(f, 0)) + abs(d["fe"].get(f, 0))))
        saida_meses[m] = {
            "fonte": og.msc(ctx.originais, m),
            "a": [[i, c, round(v, 2)] for (i, c), v in d["a"].items() if abs(v) >= 0.01],
            "b": [[c, f, round(v, 2)] for (c, f), v in d["b"].items() if abs(v) >= 0.01],
            "fv": [[f, classificar(f).nome, _classe(f), round(d["fr"].get(f, 0.0), 2), round(d["fe"].get(f, 0.0), 2)]
                   for f in fontes[:60]],
        }
    por_c = {}
    for c in ctx.competencias():
        ms = ctx.do_ano(c)
        if not ms:
            continue
        por_c[c] = _rio_competencia(ctx, c, ms)
    return {
        "especies": [{"nome": e.nome, "esfera": e.esfera.value} for e in especies],
        "meses": saida_meses,
        "por_c": por_c,
        "federais": _federais(ctx),
        "federais_origens": (ctx.entradas.get("federais") or {}).get("origens"),
    }


def _federais(ctx: Contexto) -> list[dict] | None:
    """Repasses federais por programa (FNS, FNDE, FNAS, Transferegov), quando a frente entrega ``federais.json``."""
    dados = ctx.entrada("federais")
    if not dados:
        return None
    out = []
    for r in dados.get("repasses") or []:
        origem, ano = r.get("origem", ""), str(r.get("mes") or "")[:4]
        k = f"fed:{origem}:{ano}"
        if k not in ctx.originais.tabela:
            ctx.originais.externo(k, f"{origem}: repasses de {ano}", r.get("url", ""), quando=r.get("lido_em", ""),
                                  sha256=r.get("sha256", ""))
        out.append({"origem": r.get("origem"), "mes": str(r.get("mes") or "")[:7], "programa": limpa(r.get("programa"), 140),
                    "fonte": r.get("fonte_destino"), "valor": N(r.get("valor"), k),
                    "registrado": N(r.get("registrado"), k) if r.get("registrado") is not None else None})
    return out


def _rio_competencia(ctx: Contexto, c: str, ms: list[str]) -> dict:
    fa, ft = _fonte_ano(ctx, c), _fonte_transf_ano(ctx, c)
    origem = []
    try:
        conferencias = municipio.conferir_origem(ctx.con, ms)
    except Exception:  # noqa: BLE001
        conferencias = []
    for conf in conferencias:
        vias = conf.certificacao.vias
        origem.append({
            "titulo": conf.titulo, "referencia": conf.referencia,
            "selo": conf.selo.value if conf.selo else "roxo", "divergencia": conf.certificacao.divergencia,
            "vias": [{"rotulo": v.fonte, "valor": N(v.valor, ft if i == 0 else fa)} for i, v in enumerate(vias[:2])],
            "detalhe": conf.detalhe[:6], "norma": conf.norma,
        })
    try:
        desvios, sem_catalogo = municipio.desvios(ctx.con, ms)
    except Exception:  # noqa: BLE001
        desvios, sem_catalogo = [], {}
    lista_desvios = [{"fonte": d.fonte, "nome": d.nome_fonte, "funcao": d.funcao, "valor": N(d.valor, fa, "azul"),
                      "norma": d.norma, "motivo": "finalidade" if d.motivo == "leito" else d.motivo,
                      "naturezas": [[s, n, N(v, fa)] for s, n, v in d.naturezas[:8]]} for d in desvios]

    def cartao(destino: str, titulo_origem: str) -> dict:
        nucleo = classificar("1" + destino)
        leito = list(nucleo.destinacao.leito) if nucleo.destinacao else []
        receita = 0.0
        emp_funcao: dict[str, float] = defaultdict(float)
        for m in ms:
            for fonte, funcao, v in _empenhos_mes(ctx).get(m, []):
                if fonte[-3:] == destino:
                    emp_funcao[funcao] += v
        for m in ms:
            for (fonte, mes), v in _receita_fonte(ctx).get(destino, {}).items():
                if mes == m:
                    receita += v
        conf = next((o for o in origem if titulo_origem and o["titulo"].startswith(titulo_origem)), None)
        fora = [d for d in lista_desvios if d["fonte"] == destino]
        return {
            "fonte": destino, "nome": nucleo.nome, "funcoes": leito,
            "norma": nucleo.destinacao.norma if nucleo.destinacao else "",
            "receita": N(receita, fa),
            "empenhado": [[f, N(v, fa), f in leito or not leito] for f, v in
                          sorted(emp_funcao.items(), key=lambda kv: -kv[1]) if abs(v) >= 0.01],
            "origem": conf, "desvios": fora,
        }

    cosip = cartao("751", "")
    cosip["lei"] = "Lei Complementar municipal 386/2025"
    fnas = cartao("660", "FNAS")
    ano = c[:4]
    repasses = consultar(ctx.con, "SELECT SUM(valor) FROM repasses_fnas WHERE competencia LIKE ? AND competencia <= ?",
                         (f"{ano}-%", c))
    fnas["planilha"] = N(repasses[0][0], og.fnas(ctx.originais, ano)) if repasses and repasses[0][0] else None
    return {"fonte": fa, "origem": origem, "desvios": lista_desvios, "cosip": cosip, "fnas": fnas,
            "sem_catalogo": [[f, N(v, fa)] for f, v in sorted(sem_catalogo.items(), key=lambda kv: -kv[1])]}


def _receita_fonte(ctx: Contexto) -> dict[str, dict[tuple[str, str], float]]:
    """Receita realizada por destinação (três dígitos) e mês, toda a receita orçamentária."""
    if "rec_fonte" not in ctx._cache:
        out: dict[str, dict] = defaultdict(lambda: defaultdict(float))
        for fonte, mes, v in consultar(ctx.con, (
                "SELECT fonte_recursos, mes, SUM(CASE WHEN natureza_conta = 'C' THEN valor ELSE -valor END) "
                "FROM msc_itens WHERE (conta_contabil LIKE '6212%' OR conta_contabil LIKE '62139%') "
                "AND substr(natureza_receita, 1, 1) NOT IN ('7', '8') GROUP BY 1, 2")):
            f = str(fonte or "")
            if f and v:
                out[f[-3:]][(f, mes)] += -float(v) if False else float(v)
        ctx._cache["rec_fonte"] = out
    return ctx._cache["rec_fonte"]


# =============================================================================================
# Trilha
# =============================================================================================

_CONTAS_EXEC = (("emp", "62213%"), ("liq3", "6221303%"), ("liq7", "6221307%"), ("pago", "6221304%"))


def execucao_por_funcao(ctx: Contexto) -> dict[tuple[str, str], dict[str, float]]:
    """(mês, função) -> empenhado, liquidado e pago no mês, pela matriz (exceto intra)."""
    if "exec" not in ctx._cache:
        out: dict[tuple[str, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for chave, prefixo in _CONTAS_EXEC:
            for mes, funcao, v in consultar(ctx.con, (
                    "SELECT mes, funcao, SUM(CASE WHEN natureza_conta = 'C' THEN valor ELSE -valor END) FROM msc_itens "
                    "WHERE conta_contabil LIKE ? AND substr(natureza_despesa, 3, 2) != '91' GROUP BY 1, 2"), (prefixo,)):
                out[(mes, str(funcao or "").zfill(2))][chave] += float(v or 0)
        final = {}
        for k, d in out.items():
            final[k] = {"emp": d["emp"], "liq": d["liq3"] + d["liq7"] + d["pago"], "pago": d["pago"]}
        ctx._cache["exec"] = final
    return ctx._cache["exec"]


def _dotacoes(ctx: Contexto) -> dict[tuple[int, int], dict[str, dict[str, float]]]:
    """(exercício, bimestre) -> função -> dotação inicial e atualizada (RREO Anexo 2)."""
    if "dot" not in ctx._cache:
        nomes = {sem_acento(n): c for c, n in FUNCOES.items()}
        out: dict = defaultdict(lambda: defaultdict(dict))
        for ex, per, conta, coluna, v in consultar(ctx.con, (
                "SELECT exercicio, periodo, conta, coluna, valor FROM siconfi_itens WHERE demonstrativo = 'RREO' "
                "AND anexo = 'RREO-Anexo 02' AND cod_conta = 'RREO2TotalDespesas' AND (coluna LIKE 'DOTAÇÃO%' "
                "OR coluna LIKE 'DESPESAS LIQUIDADAS ATÉ%' OR coluna LIKE 'DESPESAS EMPENHADAS ATÉ%')")):
            f = nomes.get(sem_acento(conta))
            if not f:
                continue
            chave = ("inicial" if "INICIAL" in coluna else "atualizada" if "ATUALIZADA" in coluna
                     else "liquidada" if "LIQUIDADAS" in coluna else "empenhada")
            out[(int(ex), int(per))][f][chave] = float(v or 0)
        ctx._cache["dot"] = out
    return ctx._cache["dot"]


def _transf_por_funcao(ctx: Contexto) -> dict[tuple[str, str], float]:
    if "tf" not in ctx._cache:
        nomes = {sem_acento(n): c for c, n in FUNCOES.items()}
        out: dict = defaultdict(float)
        for mes, funcao, v in consultar(ctx.con, "SELECT mes, funcao, SUM(valor) FROM transferencias_federais "
                                                 "GROUP BY 1, 2"):
            f = nomes.get(sem_acento(funcao))
            out[(mes, f or "")] += float(v or 0)
        ctx._cache["tf"] = out
    return ctx._cache["tf"]


def _contratos_mes(ctx: Contexto) -> list[tuple]:
    if "contratos" not in ctx._cache:
        ctx._cache["contratos"] = consultar(ctx.con, (
            "SELECT c.pncp_id, c.mes, c.orgao_cnpj, c.orgao, c.fornecedor, c.fornecedor_ni, c.objeto, c.valor_global, "
            "d.compra_id, d.valor_inicial, d.vigencia_inicio, d.vigencia_fim, c.data_assinatura "
            "FROM contratos_pncp c LEFT JOIN pncp_contratos_detalhe d ON d.contrato_id = c.pncp_id "
            "ORDER BY c.valor_global DESC"))
    return ctx._cache["contratos"]


ESTACOES_TEXTO = [{"n": e.numero, "nome": e.nome, "prova": e.prova, "onde": e.onde_nasce,
                   "nivel": e.nivel_minimo.name} for e in Estacao]


def estacoes_com_documento(trilha_dados: dict) -> dict[str, list[int]]:
    """As estações com documento publicado em cada mês, para todas as funções (a contagem de conforme do início)."""
    out = {}
    for m, por_funcao in (trilha_dados.get("exemplos") or {}).items():
        ex = por_funcao.get("*")
        if ex:
            out[m] = [x["n"] for x in ex["linhas"] if x["acesa"]]
    return out


def trilha(ctx: Contexto) -> dict:
    exec_ = execucao_por_funcao(ctx)
    tf = _transf_por_funcao(ctx)
    dot = _dotacoes(ctx)
    emp_mes = _empenhos_mes(ctx)
    funcao_cnpj = {cnpj: funcao_do_orgao(nome) for cnpj, nome in ctx.orgaos().items()}
    contratos: dict[tuple[str, str], list[float]] = defaultdict(lambda: [0, 0.0])
    for r in _contratos_mes(ctx):
        for f in (funcao_cnpj.get(r[2]) or "", "*"):
            contratos[(r[1], f)][0] += 1
            contratos[(r[1], f)][1] += float(r[7] or 0)
    funcoes = sorted({f for (_, f) in exec_ if f in FUNCOES})
    exemplos: dict[str, dict] = {}
    for m in ctx.meses_msc():
        exemplos[m] = {}
        for f in ["*"] + funcoes:
            exemplos[m][f] = _estacoes(ctx, m, f, exec_, tf, dot, emp_mes, contratos)
    execucao = ctx.entrada("execucao")
    lista, total = _execucao_entrada(ctx, execucao) if execucao else (None, {})
    return {"estacoes": ESTACOES_TEXTO, "exemplos": exemplos, "funcoes": funcoes,
            "execucao": lista, "execucao_total": total,
            "dominio": next((d.funcao for d in ctx.alvo.ativos()), None)}


def _estacoes(ctx, m, f, exec_, tf, dot, emp_mes, contratos) -> list:
    fm = og.msc(ctx.originais, m)
    ano, mes = int(m[:4]), int(m[5:])
    if f == "*":
        e = {k: sum(v[k] for (mm, ff), v in exec_.items() if mm == m) for k in ("emp", "liq", "pago")}
        origem = sum(v for (mm, _), v in tf.items() if mm == m)
    else:
        e = exec_.get((m, f), {"emp": 0.0, "liq": 0.0, "pago": 0.0})
        origem = tf.get((m, f), 0.0)
    vinc = livre = 0.0
    for fonte, funcao, v in emp_mes.get(m, []):
        if f != "*" and funcao != f:
            continue
        c = _classe(fonte)
        if c == "vinculada":
            vinc += v
        elif c == "livre":
            livre += v
    periodos = sorted(p for (ex, p) in dot if ex == ano)
    ate = [p for p in periodos if 2 * p <= mes]
    p_ini = (ate or periodos or [None])[-1] if periodos else None
    p_atu = ate[-1] if ate else None

    def dotacao(p, chave):
        if p is None:
            return None
        d = dot[(ano, p)]
        if f == "*":
            return sum(x.get(chave, 0.0) for x in d.values()) or None
        return d.get(f, {}).get(chave)
    ini, atu = dotacao(p_ini, "inicial"), dotacao(p_atu, "atualizada")
    cont = contratos.get((m, f), [0, 0.0])
    eventos = []
    linhas = []

    def estacao(est: Estacao, nivel: Nivel | None, valor, fonte, nota, extra=None):
        acesa = nivel is not None and est.acende_com(nivel) and valor not in (None, 0, 0.0)
        if acesa:
            eventos.append(Evento(est, nivel, valor))
        linhas.append({"n": est.numero, "acesa": acesa, "valor": N(valor, fonte) if valor else None,
                       "nivel": nivel.name if nivel else "F", "nota": nota, **(extra or {})})
    ft = og.transferencias(ctx.originais, m)
    estacao(Estacao.ORIGEM, Nivel.B, origem, ft,
            "Transferências da União no mês" + ("" if f == "*" else f" para a função {FUNCOES.get(f, f)}")
            + ", pelo Portal da Transparência. Os tributos próprios aparecem na tela Origem do dinheiro.")
    estacao(Estacao.FONTE, Nivel.B, vinc + livre, fm, "Empenhado no mês, separado pela fonte de recursos.",
            {"vinculada": N(vinc, fm), "livre": N(livre, fm)})
    fr = og.siconfi(ctx.originais, "RREO", ano, p_ini) if p_ini else fm
    estacao(Estacao.PREVISAO, Nivel.D, ini, fr, "Dotação inicial da Lei Orçamentária, pelo RREO do exercício.")
    fa = og.siconfi(ctx.originais, "RREO", ano, p_atu) if p_atu else fm
    estacao(Estacao.DOTACAO, Nivel.D, atu,
            fa, "Dotação atualizada pelos créditos adicionais até o último RREO do mês."
            if atu else "O primeiro RREO do ano ainda não fechou neste mês.",
            {"variacao": N((atu or 0) - (ini or 0), fa) if atu and ini else None})
    estacao(Estacao.EMPENHO, Nivel.B, e["emp"], fm, "Empenhado no mês pela matriz de saldos contábeis "
                                                    "(soma por função; o empenho com número e credor vem da execução).")
    estacao(Estacao.VINCULO, Nivel.C, cont[1], f"pncp_mes:{m}",
            f"{cont[0]} contrato(s) assinado(s) no mês e publicados no PNCP"
            + ("" if f == "*" else " pelos órgãos desta função") + ".", {"contratos": cont[0]})
    ctx.originais.sem_original(f"pncp_mes:{m}", f"PNCP: contratos assinados em {rotulo_mes(m)}",
                               "Soma de várias leituras do PNCP; cada contrato abre a sua na tela Preço e entrega.")
    estacao(Estacao.LIQUIDACAO, Nivel.B, e["liq"], fm, "Liquidado no mês pela matriz (entrega atestada).")
    estacao(Estacao.PAGAMENTO, Nivel.B, e["pago"], fm, "Pago no mês pela matriz.")
    estacao(Estacao.PRESTACAO, None, None, "", "A prestação de contas por empenho não está publicada; "
                                               "a tela Contas mostra as entregas ao Tesouro.")
    p = Percurso(chave=f"{m}:{f}", eventos=eventos)
    return {"linhas": linhas, "faltantes": [s.numero for s in p.faltantes()], "ordem": p.ordem_violada()}


# Empenhos por recorte (mês e função, e o mês inteiro) que entram na página: os de maior valor. A tela mostra
# no máximo 200 por recorte; com a despesa inteira de Goiânia (24 mil empenhos, 155 mil eventos), a trilha
# levava todos e passou de 48 MB (28/11/2026). A contagem completa de cada recorte vai em ``execucao_total``.
EMPENHOS_POR_RECORTE = 50
EMPENHOS_POR_ORGAO = 20       # o recorte do órgão escolhido na tela (o:<CNPJ>:*), para a página não crescer
_ESTACOES_EXEC = ("empenho", "liquidacao", "pagamento")


def _execucao_entrada(ctx: Contexto, dados: dict) -> tuple[list[dict], dict]:
    """Empenho a empenho, quando a frente da execução entrega ``execucao.json``: os de maior valor de cada
    recorte, com as estações somadas (uma prova por empenho, a resposta lida do portal), e quantos há."""
    empenhos = dados.get("empenhos") or []
    total: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    grupos: dict[tuple[str, str], list[int]] = defaultdict(list)
    for i, e in enumerate(empenhos):
        mes, fun = str(e.get("data") or "")[:7], str(e.get("funcao") or "")
        orgao = str(e.get("orgao_cnpj") or "")
        # O órgão (a secretaria escolhida na tela) tem os seus próprios maiores e a sua contagem, em
        # "o:<CNPJ>:*", para a tela não dizer que os maiores do Município são todos os da pasta.
        recortes = ("*", fun) + ((f"o:{orgao}:*",) if orgao else ())
        for f in recortes:
            total[mes][f] += 1
            grupos[(mes, f)].append(i)
        if orgao:
            total[mes][f"o:{orgao}:{fun}"] += 1         # só a contagem; os maiores vêm dos recortes acima
    escolhidos: set[int] = set()
    for (_, f), idx in grupos.items():
        idx.sort(key=lambda i: -float(empenhos[i].get("valor") or 0))
        escolhidos.update(idx[:EMPENHOS_POR_ORGAO if f.startswith("o:") else EMPENHOS_POR_RECORTE])
    out = []
    for i in sorted(escolhidos, key=lambda i: (str(empenhos[i].get("data") or ""), str(empenhos[i].get("numero")))):
        e = empenhos[i]
        chave = ctx.originais.externo(f"exec:{e.get('numero', i)}", f"Execução: empenho {e.get('numero', '')}",
                                      e.get("url", ""), quando=e.get("lido_em", ""), sha256=e.get("sha256", ""))
        soma: dict[str, list] = {}
        for ev in e.get("eventos") or []:
            st = ev.get("estacao")
            if st not in _ESTACOES_EXEC:
                continue
            x = soma.setdefault(st, [0.0, 0, ev.get("data") or ""])
            x[0] += float(ev.get("valor") or 0)
            x[1] += 1
            x[2] = min(filter(None, [x[2], ev.get("data") or ""]), default="")
        eventos = [{"estacao": st, "data": soma[st][2], "valor": N(soma[st][0], chave),
                    "documento": f"{soma[st][1]} registro(s)"} for st in _ESTACOES_EXEC if st in soma]
        out.append({"numero": e.get("numero"), "data": e.get("data"), "mes": str(e.get("data") or "")[:7],
                    "orgao": e.get("orgao_cnpj"), "credor": e.get("credor"), "fonte": e.get("fonte"),
                    "funcao": e.get("funcao"), "valor": N(e.get("valor"), chave), "contrato": e.get("contrato"),
                    "eventos": eventos})
    return out, {m: dict(v) for m, v in total.items()}


# =============================================================================================
# Pisos e tetos, pessoal
# =============================================================================================

_FUNCAO_DA_REGRA = {"PISO-SAUDE": "10", "PISO-EDUCACAO": "12", "FUNDEB-PROFISSIONAIS": "12",
                    "FUNDEB-SALDO": "12", "CAMARA": "01", "IGD-CONTROLE-SOCIAL": "08"}


def _fonte_regra(ctx: Contexto, fiscal, regra_id: str) -> tuple[str, str | None]:
    """A via principal (o cálculo próprio) e a via declarada de cada regra."""
    rgf, rreo = fiscal.rgf, fiscal.rreo
    if regra_id in ("PESSOAL-EXECUTIVO", "DIVIDA-CONSOLIDADA", "OPERACOES-CREDITO") and rgf:
        k = og.siconfi(ctx.originais, "RGF", rgf.exercicio, rgf.periodo)
        return k, k
    if regra_id == "CAMARA" and rreo:
        return og.siconfi(ctx.originais, "DCA", rreo.exercicio - 1, 1), None
    if rreo:
        k = og.siconfi(ctx.originais, "RREO", rreo.exercicio, rreo.periodo)
        externo = "SIOPS" if regra_id == "PISO-SAUDE" else "SIOPE" if regra_id.startswith(("PISO-EDUC", "FUNDEB")) else None
        if externo:
            linhas = consultar(ctx.con, "SELECT exercicio, periodo FROM externos_periodos WHERE fonte = ? AND "
                                        "situacao = 'homologado' AND exercicio = ? ORDER BY periodo DESC",
                               (externo, rreo.exercicio))
            alvo = next(((e, p) for e, p in linhas if p <= rreo.periodo), None)
            if alvo:
                return k, og.externo_periodo(ctx.originais, externo, *alvo)
        return k, None
    return ctx.originais.sem_original("sem_demonstrativo", "Nenhum demonstrativo no banco"), None


def _medidas(ctx: Contexto, c: str) -> dict:
    f = ctx.fiscal(c)
    medidas = []
    for m in f.medidas:
        r = m.regra
        k, kd = _fonte_regra(ctx, f, r.id)
        selo = m.selo.value if m.selo else "azul"
        medidas.append({
            "id": r.id, "titulo": r.titulo, "norma": r.norma, "base": r.base, "tipo": r.tipo, "unidade": r.unidade,
            "limite": m.limite, "alerta": r.get("alerta"), "prudencial": r.get("prudencial"),
            "percentual": N(m.percentual, k, selo), "declarado": N(m.declarado, kd or k) if m.declarado is not None else None,
            "situacao": m.situacao, "selo": selo, "divergencia": m.divergencia,
            "memoria": f.memoria.get(r.id, ""), "vias": f.fontes.get(r.id, ""), "funcao": _FUNCAO_DA_REGRA.get(r.id),
        })
    vias = []
    for conf in f.conferencias:
        k = og.siconfi(ctx.originais, "RGF", f.rgf.exercicio, f.rgf.periodo) if f.rgf else ""
        k2 = og.siconfi(ctx.originais, "RREO", f.rreo.exercicio, f.rreo.periodo) if f.rreo else k
        vias.append({"titulo": conf.titulo, "referencia": conf.referencia,
                     "selo": conf.selo.value if conf.selo else "roxo", "divergencia": conf.certificacao.divergencia,
                     "vias": [{"rotulo": v.fonte, "valor": N(v.valor, k if i == 0 else k2)}
                              for i, v in enumerate(conf.certificacao.vias[:2])]})
    return {"rgf": f.rgf.rotulo if f.rgf else None, "rreo": f.rreo.rotulo if f.rreo else None,
            "medidas": medidas, "vias": vias, "notas": f.notas}


def pisos(ctx: Contexto) -> dict:
    por_c = {}
    for c in ctx.competencias():
        d = _medidas(ctx, c)
        p = ctx.panoramas.get(c)
        pasta = []
        for x in (p or {}).get("pisos", []):
            k = ctx.originais.sem_original(f"pasta:{x['regra']}:{c}", f"{x['titulo']} ({c})",
                                           "Demonstrativo do piso não publicado pelo Município.", selo="roxo") \
                if x.get("percentual") is None else f"panorama:{c}"
            if x.get("percentual") is not None:
                ctx.originais.sem_original(k, f"Parecer de {rotulo_mes(c)}", "Cálculo do parecer mensal.")
            pasta.append({"id": x["regra"], "titulo": x["titulo"], "limite": x["limite"], "situacao": x["situacao"],
                          "selo": x.get("selo") or "roxo", "percentual": N(x.get("percentual"), k) if x.get("percentual") is not None else None,
                          "fonte_ausente": k if x.get("percentual") is None else None,
                          "funcao": _FUNCAO_DA_REGRA.get(x["regra"])})
        d["pasta"] = pasta
        por_c[c] = d
    return {"por_c": por_c}


def pessoal(ctx: Contexto) -> dict:
    serie = []
    vistos = set()
    for c in ctx.competencias():
        f = ctx.fiscal(c)
        if not f.rgf or f.rgf.rotulo in vistos:
            continue
        vistos.add(f.rgf.rotulo)
        m = next((x for x in f.medidas if x.regra.id == "PESSOAL-EXECUTIVO"), None)
        if m is None:
            continue
        k = og.siconfi(ctx.originais, "RGF", f.rgf.exercicio, f.rgf.periodo)
        serie.append({"rotulo": f.rgf.rotulo, "termina": f.rgf.termina.isoformat(), "ate": f.rgf.termina.isoformat()[:7],
                      "percentual": N(m.percentual, k, m.selo.value if m.selo else None),
                      "declarado": N(m.declarado, k) if m.declarado is not None else None,
                      "situacao": m.situacao, "memoria": f.memoria.get("PESSOAL-EXECUTIVO", "")})
    regra = ctx.mapa.regra("PESSOAL-EXECUTIVO") if "PESSOAL-EXECUTIVO" in ctx.mapa.regras else None
    folha: dict[str, dict[str, float]] = defaultdict(dict)
    for mes, funcao, v in consultar(ctx.con, (
            "SELECT mes, funcao, SUM(CASE WHEN natureza_conta = 'C' THEN valor ELSE -valor END) FROM msc_itens "
            "WHERE (conta_contabil LIKE '6221303%' OR conta_contabil LIKE '6221304%' OR conta_contabil LIKE '6221307%') "
            "AND natureza_despesa LIKE '31%' AND substr(natureza_despesa, 3, 2) != '91' GROUP BY 1, 2")):
        folha[mes][str(funcao or "").zfill(2)] = round(float(v or 0), 2)
    mensal = {m: {"fonte": og.msc(ctx.originais, m), "por_funcao": {f: N(v, og.msc(ctx.originais, m))
                                                                     for f, v in d.items()}}
              for m, d in sorted(folha.items())}
    return {"serie": serie, "limite": regra.valor if regra else 54.0,
            "alerta": regra.get("alerta") if regra else None, "prudencial": regra.get("prudencial") if regra else None,
            "norma": regra.norma if regra else "", "mensal": mensal, "nomeacoes": _nomeacoes(ctx)}


def _nomeacoes(ctx: Contexto) -> dict | None:
    """Atos de pessoal da pasta no Diário Oficial: só contagens, por mês e por ato (sem nomes)."""
    if not NOMEACOES.exists():
        return None
    try:
        bruto = json.loads(NOMEACOES.read_text(encoding="utf-8"))
    except ValueError:
        return None
    por_mes: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    edicoes: dict[str, dict] = {}
    for r in bruto.get("registros") or []:
        mes = str(r.get("data") or "")[:7]
        if not mes:
            continue
        por_mes[mes][r.get("ato") or "Outro"] += 1
        if r.get("url_edicao"):
            edicoes.setdefault(mes, {"url": r["url_edicao"], "sha": r.get("sha256_edicao", ""), "edicao": r.get("edicao")})
    meses = {}
    for mes, atos in sorted(por_mes.items()):
        ed = edicoes.get(mes, {})
        k = ctx.originais.externo(f"do:{mes}", f"Diário Oficial de {rotulo_mes(mes)}: atos de pessoal da pasta",
                                  ed.get("url", ""), sha256=ed.get("sha", ""),
                                  nota="A edição aberta é a primeira do mês com ato; cada ato aponta a sua.")
        meses[mes] = {a: N(n, k) for a, n in atos.items()}
    return {"meses": meses, "quadro_atual": bruto.get("quadro_atual"), "regra": bruto.get("regra_de_analise", "")}


# =============================================================================================
# Preço e entrega, empresas, secretarias
# =============================================================================================

def _achados(ctx: Contexto) -> list:
    return ctx.compras().achados


def vertice_da_prestacao(execucao: dict):
    """O vértice da prestação de cada contrato no triângulo: ``conferido`` quando um empenho ligado ao
    contrato (``contrato`` em ``execucao.json``) tem liquidação; ``ausente`` quando o contrato é de um órgão
    que a execução lida identifica e foi assinado dentro dos meses que ela cobre, sem liquidação ligada;
    ``aguardando`` no resto (sem execução lida, a Câmara, o fundo da Educação, um contrato anterior à
    coleta), porque a execução não diz nada sobre ele. Até 28/11/2026 nenhum empenho trazia o contrato e,
    com o banco cheio, os 2.118 contratos saíam todos como ausentes."""
    empenhos = execucao.get("empenhos") or []
    liquidados = {e.get("contrato") for e in empenhos
                  if e.get("contrato") and any(ev.get("estacao") == "liquidacao" for ev in e.get("eventos") or [])}
    orgaos = {e.get("orgao_cnpj") for e in empenhos if e.get("orgao_cnpj")}
    inicio = min((str(e.get("data") or "") for e in empenhos if e.get("data")), default="")

    def vertice(pid: str, orgao_cnpj: str, assinatura) -> str:
        if pid in liquidados:
            return "conferido"
        if empenhos and orgao_cnpj in orgaos and str(assinatura or "")[:10] >= inicio:
            return "ausente"
        return "aguardando"
    return vertice


def precos(ctx: Contexto) -> dict:
    from ..conferencias.compras import TITULOS
    achados = _achados(ctx)
    preco_por_compra: dict[str, int] = defaultdict(int)
    for a in achados:
        if a.tipo in ("preco", "nota_preco"):
            preco_por_compra[a.chave.rsplit("-", 1)[0]] += 1
    com_catalogo = {c for (c,) in consultar(ctx.con, "SELECT DISTINCT compra_id FROM pncp_itens WHERE catalogo IS NOT NULL")}
    com_nota = {c for (c,) in consultar(ctx.con, "SELECT DISTINCT contrato_id FROM pncp_cobrancas")}
    sem_nota = {a.orgao_cnpj for a in achados if a.tipo == "nf_ausente"}
    prestacao = vertice_da_prestacao(ctx.entrada("execucao") or {})
    contratos = []
    for (pid, mes, cnpj, orgao, forn, ni, objeto, valor, compra, inicial, vi, vf, assin) in _contratos_mes(ctx):
        k = og.pncp(ctx.originais, cnpj, mes, orgao)
        preco = ("indicio" if compra and preco_por_compra.get(compra) else
                 "conferido" if compra in com_catalogo else "sem_comparacao")
        entrega = "conferido" if pid in com_nota else ("ausente" if cnpj in sem_nota else "sem_leitura")
        prest = prestacao(pid, cnpj, assin)
        contratos.append([pid, mes, cnpj, limpa(forn, 90), documento_publico(ni), limpa(objeto, 160), N(valor or 0, k), preco,
                          preco_por_compra.get(compra or "", 0), entrega, prest, compra or ""])
    lista = []
    for a in achados:
        k = og.pncp(ctx.originais, a.orgao_cnpj, a.mes, a.orgao)
        lista.append([a.tipo, a.orgao_cnpj, a.chave, a.mes, limpa(a.descricao, 260), N(a.valor, k),
                      N(a.limite, k) if a.limite else None, a.dados.get("desde", a.mes) if a.tipo == "nf_ausente" else a.mes])
    return {"titulos": TITULOS, "contratos": contratos, "achados": lista, "cobertura": ctx.compras().cobertura,
            "janela": JANELA}


def empresas(ctx: Contexto) -> dict:
    fornecedores: dict[str, dict] = {}
    for (pid, mes, cnpj, orgao, forn, ni, objeto, valor, *_resto) in _contratos_mes(ctx):
        chave = ni or limpa(forn)
        f = fornecedores.setdefault(chave, {"ni": documento_publico(ni), "nome": limpa(forn, 90), "contratos": []})
        f["contratos"].append([pid, mes, cnpj, N(valor or 0, og.pncp(ctx.originais, cnpj, mes, orgao))])
    concentracao = []
    for a in _achados(ctx):
        if a.tipo == "concentracao":
            k = og.pncp(ctx.originais, a.orgao_cnpj, a.mes, a.orgao)
            concentracao.append({"orgao": a.orgao_cnpj, "ano": a.dados.get("ano"), "mes": a.mes, "total": N(a.valor, k),
                                 "credores": a.dados.get("credores"), "levam": a.dados.get("levam_o_corte"),
                                 "corte": a.dados.get("corte_pct"), "maiores": [m for m in a.dados.get("maiores", [])[:5] if not re.fullmatch(r"\d{11}", str(m))]})
    receita = ctx.entrada("empresas")
    cobertura = None
    if receita:
        for e in receita.get("empresas") or []:
            cnpj = documento_publico(re.sub(r"[^0-9A-Za-z]", "", str(e.get("cnpj") or "")).upper())
            if not cnpj:
                continue      # só CNPJ; pessoa física nunca entra aqui
            k = ctx.originais.externo(
                f"rf:{cnpj}", f"Receita Federal: cartão do CNPJ {cnpj}", e.get("url", ""), quando=e.get("lido_em", ""),
                sha256=e.get("sha256", ""), selo="azul" if e.get("cadastro", True) else "cinza",
                nota="" if e.get("cadastro", True) else "O cadastro desta empresa ainda não foi coletado da Receita Federal.")
            alvo = fornecedores.setdefault(cnpj, {"ni": cnpj, "nome": limpa(e.get("razao")), "contratos": []})
            alvo["receita"] = {
                "fonte": k, "cadastro": e.get("cadastro", True), "abertura": e.get("abertura"), "situacao": e.get("situacao"),
                "capital": N(e.get("capital"), k) if e.get("capital") is not None else None,
                "cnae": e.get("cnae"),
                "socios": [{"nome": limpa(s.get("nome"), 120), "qualificacao": limpa(s.get("qualificacao"), 80),
                            "desde": s.get("desde")} for s in e.get("socios") or []],
                "sancoes": e.get("sancoes") or [],
                "alertas": [{"tipo": a.get("tipo"), "titulo": limpa(a.get("titulo") or a.get("tipo")),
                             "gravidade": a.get("gravidade") or "media", "texto": limpa(a.get("texto"), 500),
                             "mes": a.get("mes", "")} for a in e.get("alertas") or []]}
        cob = receita.get("cobertura")
        if cob:
            cobertura = {"cnpjs": cob.get("cnpjs"), "com_cadastro": cob.get("cnpjs_com_cadastro"),
                         "com_qsa": cob.get("cnpjs_com_qsa"), "folha": cob.get("folha"),
                         "contratos_pessoa_fisica": cob.get("contratos_pessoa_fisica"),
                         "sancoes_nao_conferidas": cob.get("sancoes_nao_conferidas") or {},
                         "lacunas": [limpa(x, 600) for x in cob.get("lacunas") or []],
                         "alertas_gerais": [{"titulo": limpa(a.get("titulo")), "texto": limpa(a.get("texto"), 600)}
                                            for a in receita.get("alertas_gerais") or []],
                         "por_tipo": receita.get("por_tipo") or {}}
    lista = sorted(fornecedores.values(), key=lambda f: -sum(c[3]["v"] for c in f["contratos"]))
    lista = [f for f in lista if f["contratos"]]
    return {"fornecedores": lista[:600], "total_fornecedores": len(lista), "concentracao": concentracao,
            "receita": bool(receita), "cobertura": cobertura}


def secretarias_dados(ctx: Contexto) -> dict:
    contratos: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(lambda: [0, 0.0]))
    chaves: dict[tuple[str, str], str] = {}
    for r in _contratos_mes(ctx):
        contratos[r[2]][r[1]][0] += 1
        contratos[r[2]][r[1]][1] += float(r[7] or 0)
        chaves[(r[2], r[1])] = og.pncp(ctx.originais, r[2], r[1], r[3])
    achados: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(lambda: [0, 0.0]))
    for a in _achados(ctx):
        achados[a.orgao_cnpj][a.mes][0] += 1
        achados[a.orgao_cnpj][a.mes][1] += float(a.valor or 0)
        chaves.setdefault((a.orgao_cnpj, a.mes), og.pncp(ctx.originais, a.orgao_cnpj, a.mes, a.orgao))
    sem_nota = {a.orgao_cnpj for a in _achados(ctx) if a.tipo == "nf_ausente"}
    orgaos = {}
    for cnpj in ctx.orgaos():
        orgaos[cnpj] = {
            "contratos": {m: [n, N(v, chaves[(cnpj, m)])] for m, (n, v) in contratos.get(cnpj, {}).items()},
            "achados": {m: [n, N(v, chaves[(cnpj, m)])] for m, (n, v) in achados.get(cnpj, {}).items()},
            "sem_nota": cnpj in sem_nota,
        }
    exec_ = execucao_por_funcao(ctx)
    por_funcao = defaultdict(dict)
    for (m, f), d in exec_.items():
        k = og.msc(ctx.originais, m)
        por_funcao[f][m] = {x: N(d[x], k) for x in ("emp", "liq", "pago")}
    selo = ctx.entrada("selo_transparencia") or {}
    transp = {}
    for o in selo.get("por_orgao") or []:
        cnpj = re.sub(r"\D", "", str(o.get("cnpj") or ""))
        k = ctx.originais.externo(f"selo_org:{cnpj}", f"Selo de transparência refeito: {o.get('orgao') or cnpj}",
                                  selo.get("declarado", {}).get("url", ""))
        if not cnpj:
            continue
        obrig = o.get("obrigacoes")
        transp[cnpj] = {"nota": N(o.get("nota"), k) if o.get("nota") is not None and not obrig else None,
                        "nivel": o.get("nivel"), "texto": limpa(o.get("nota_texto", "")),
                        "obrigacoes": [{"id": x.get("id"), "texto": limpa(x.get("texto")), "estado": x.get("estado"),
                                        "alerta": bool(x.get("alerta"))} for x in obrig or []]}
    return {"orgaos": orgaos, "execucao": por_funcao, "transparencia": transp, "janela": JANELA}


# =============================================================================================
# Indícios, transparência, contas
# =============================================================================================

def _secretarias_da_ficha(ctx: Contexto, f: dict, pasta: list[str]) -> list[str]:
    achados = [c for c in CNPJ.findall(f.get("codigo", "")) if c in ctx.orgaos()]
    if achados:
        return achados
    if f.get("origem") == "cadeoqueijo" or f.get("codigo", "").startswith(("IGD", "CMAS", "PES", "ATA", "EXE", "FMAS")):
        return pasta
    return []   # do Município inteiro


def indicios(ctx: Contexto) -> dict:
    from ..conferencias.compras import ficha as ficha_compra
    pasta = [s["id"] for s in secretarias(ctx) if s["pasta"]]
    fichas: dict[str, dict] = {}
    for c, p in sorted(ctx.panoramas.items()):
        for f in p.get("fichas", []):
            atual = fichas.get(f["codigo"])
            if atual is None:
                atual = fichas[f["codigo"]] = _ficha(f, _secretarias_da_ficha(ctx, f, pasta), [])
            atual["cs"].append(c)
    for a in _achados(ctx):
        fc = ficha_compra(a, a.mes)
        if fc is None or fc.codigo in fichas:
            continue
        d = fc.como_dict()
        d["custodia"] = d.get("custodia") or []
        x = _ficha(d, [a.orgao_cnpj], [])
        x["de"] = a.dados.get("desde", a.mes) if a.tipo == "nf_ausente" else a.mes
        x["ate"] = a.mes if a.tipo == "nf_ausente" else _mes_mais(a.mes, JANELA - 1)
        x["fonte"] = og.pncp(ctx.originais, a.orgao_cnpj, a.mes, a.orgao)
        fichas[fc.codigo] = x
    familias = {f.value: f.descricao for f in Familia}
    return {"fichas": list(fichas.values()), "familias": familias, "rotulos": {f.value: f.rotulo for f in Familia},
            "estacoes_da_familia": {f.value: [e.numero for e in f.estacoes] for f in Familia}}


def _mes_mais(mes: str, n: int) -> str:
    return mes_menos(mes, -n)


def _ficha(f: dict, secs: list[str], cs: list[str]) -> dict:
    tema = tema_da_ficha(f["codigo"], f["familia"])
    return {"codigo": f["codigo"], "familia": f["familia"], "titulo": limpa(f["titulo"]), "gravidade": f["gravidade"],
            "verificacao": f["verificacao"], "como_deveria": limpa(f.get("como_deveria")),
            "como_esta": limpa(f.get("como_esta")), "norma": limpa(f.get("norma")),
            "providencia": limpa(f.get("providencia")), "caso": limpa(f.get("caso_semelhante")),
            "observacao": limpa(f.get("observacao")),
            "custodia": [{"url": o.get("url"), "quando": o.get("coletado_em"), "sha256": o.get("sha256"),
                          "registro": o.get("registro") or "", "edicao": o.get("edicao"), "pagina": o.get("pagina")}
                         for o in f.get("custodia") or []],
            "rastreio": rastreio_da_ficha(f),
            "secretarias": secs, "cs": list(cs), "tema": tema,
            "etapa": ETAPA_DO_TEMA.get(tema, ""), "condicao": condicao_da_ficha(f["codigo"], tema, f["titulo"])}


def transparencia(ctx: Contexto) -> dict:
    from ..lai import ESCADA, oficios_por_orgao
    from ..nucleo.ausencias import Ausencia
    pasta = [s["id"] for s in secretarias(ctx) if s["pasta"]]
    ausencias: dict[str, dict] = {}
    oficios: dict[str, list] = {}
    campos = {"o_que_falta", "conferencia_impedida", "onde_deveria_estar", "fundamento", "periodo", "orgao", "bloco"}
    for c, p in sorted(ctx.panoramas.items()):
        objs = []
        for a in p.get("ausencias", []):
            chave = a["o_que_falta"] + "|" + (a.get("periodo") or "")
            if chave not in ausencias:
                ausencias[chave] = {**{k: limpa(a.get(k, "")) for k in campos}, "cs": [], "secretarias": pasta,
                                    "fonte": ctx.originais.sem_original(
                                        f"aus:{len(ausencias)}", a["o_que_falta"],
                                        f"A lei manda publicar em: {a.get('onde_deveria_estar')}. Não está publicado.",
                                        selo="roxo")}
            ausencias[chave]["cs"].append(c)
            objs.append(Ausencia(**{k: a.get(k, "") for k in campos if a.get(k) is not None}))
        if objs:
            assunto = f"Documentos não publicados: {p.get('dominio', '')}, {rotulo_mes(c)}"
            oficios[c] = [{"destinatario": o.destinatario, "itens": len(o.itens),
                           "texto": sem_travessao(o.texto(hoje=ctx.hoje))}
                          for o in oficios_por_orgao(objs, assunto)]
    municipio_aus = _ausencias_municipio(ctx)
    falhas = []
    for motor, alvo, mes, url, erro in consultar(ctx.con, "SELECT motor, alvo, mes, url, erro FROM coletas WHERE ok = 0"):
        falhas.append({"motor": motor, "alvo": limpa(alvo), "mes": mes or "", "url": url, "erro": limpa(erro, 200)})
    selo = ctx.entrada("selo_transparencia")
    selo_dados = _selo(ctx, selo) if selo else None
    return {"ausencias": list(ausencias.values()), "oficios": oficios, "municipio": municipio_aus,
            "falhas": falhas, "selo": selo_dados,
            "escada": [{"n": d.numero, "nome": d.nome, "fundamento": d.fundamento, "agir": d.prazo_para_agir,
                        "decidir": d.prazo_para_decidir, "obs": d.observacao} for d in ESCADA]}


_COR_AUDITADO = {"cumpre": "verde", "falha": "azul", "sem_dado": "cinza"}


def _selo(ctx: Contexto, selo: dict) -> dict:
    """O selo declarado e o selo refeito: as duas leituras (oficial e restritiva), cada uma comprovada e no
    teto, os critérios com a prova e as obrigações do Fundo e do Conselho."""
    dec = selo.get("declarado") or {}
    kd = ctx.originais.externo("selo:declarado", limpa(dec.get("fonte")) or
                               f"Selo declarado: {selo.get('programa', '')} {dec.get('ciclo') or selo.get('ciclo', '')}",
                               dec.get("url", ""), quando=dec.get("lido_em", ""))
    ka = ctx.originais.sem_original("selo:auditado", "Selo refeito pelo Onisciente",
                                    "Cálculo próprio a partir dos critérios abaixo, cada um com a sua prova.")
    crit = []
    for i, c in enumerate(selo.get("criterios") or []):
        k = ctx.originais.externo(f"selo:c{i}", f"Critério {c.get('id')}: {limpa(c.get('criterio'), 120)}",
                                  c.get("prova_url", ""), quando=c.get("lido_em", ""),
                                  selo=_COR_AUDITADO.get(c.get("auditado"), "cinza"),
                                  nota=limpa("; ".join(p.get("descricao", "") for p in c.get("provas") or []), 600))
        crit.append({**{x: c.get(x) for x in ("id", "peso", "declarado", "auditado", "auditado_restritiva", "dimensao")},
                     "criterio": limpa(c.get("criterio")), "nota": limpa(c.get("nota"), 300), "fonte": k})
    leituras = [{**le, "indice": N(le.get("indice"), ka)} for le in selo.get("leituras") or []]
    orgaos = []
    for o in selo.get("por_orgao") or []:
        orgaos.append({"sigla": o.get("sigla") or "", "orgao": limpa(o.get("orgao")), "cnpj": o.get("cnpj") or "",
                       "nivel": limpa(o.get("nivel")), "texto": limpa(o.get("nota_texto")),
                       "obrigacoes": [{"id": x.get("id"), "texto": limpa(x.get("texto")), "base": limpa(x.get("base")),
                                       "pntp": limpa(x.get("pntp")), "estado": x.get("estado"), "alerta": bool(x.get("alerta")),
                                       "valor": N(x.get("valor_em_jogo"), ka) if x.get("valor_em_jogo") else None,
                                       "provas": [limpa(p, 300) for p in x.get("provas") or []]}
                                      for x in o.get("obrigacoes") or []]})
    aud = selo.get("auditado") or {}
    return {"programa": selo.get("programa"), "ciclo": selo.get("ciclo"),
            "declarado": {"nivel": dec.get("nivel"), "ciclo": dec.get("ciclo") or selo.get("ciclo"),
                          "nota": N(dec.get("nota"), kd), "nota_texto": limpa(dec.get("nota_texto")), "fonte": kd,
                          "ciclo_seguinte": limpa(dec.get("ciclo_seguinte"), 400)},
            "auditado": {"nivel": aud.get("nivel"), "nota": N(aud.get("nota"), ka)},
            "leituras": leituras, "veredito": selo.get("veredito"), "radar": selo.get("radar"),
            "criterios": crit, "orgaos": orgaos, "pendencias": [limpa(p, 500) for p in selo.get("pendencias") or []]}


def _ausencias_municipio(ctx: Contexto) -> list[dict]:
    """Demonstrativos do Município que venceram e não estão no banco como entregues."""
    out = []
    for dem, ex, per, rot, prazo, sit in consultar(ctx.con, "SELECT demonstrativo, exercicio, periodo, rotulo, prazo, "
                                                            "situacao FROM siconfi_periodos"):
        if sit != "entregue" and prazo and prazo < ctx.hoje.isoformat():
            k = ctx.originais.sem_original(f"aus_sic:{rot}", rot, "Prazo vencido sem entrega no SICONFI.", selo="roxo")
            out.append({"o_que_falta": rot, "prazo": prazo, "situacao": sit, "mes": prazo[:7], "fonte": k,
                        "onde": "SICONFI (Tesouro Nacional)", "fundamento": "LC 101/2000, arts. 52, 54 e 55"})
    for mes, sit, prazo in consultar(ctx.con, "SELECT mes, situacao, prazo FROM msc_meses"):
        if sit != "entregue" and prazo and prazo < ctx.hoje.isoformat():
            k = ctx.originais.sem_original(f"aus_msc:{mes}", f"Matriz de saldos contábeis de {mes}",
                                           "Prazo vencido sem entrega no SICONFI.", selo="roxo")
            out.append({"o_que_falta": f"Matriz de saldos contábeis de {rotulo_mes(mes)}", "prazo": prazo,
                        "situacao": sit, "mes": mes, "fonte": k, "onde": "SICONFI (Tesouro Nacional)",
                        "fundamento": "Portaria STN 642/2019"})
    for fonte, ex, per, sit in consultar(ctx.con, "SELECT fonte, exercicio, periodo, situacao FROM externos_periodos"):
        termina = fim_do_mes(f"{ex}-{per * 2:02d}")
        if sit not in ("homologado", "no_prazo") and termina + timedelta(days=30) < ctx.hoje:
            k = ctx.originais.sem_original(f"aus_ext:{fonte}:{ex}-{per}", f"{fonte} do {per}º bimestre de {ex}",
                                           "Não homologado no prazo.", selo="roxo")
            out.append({"o_que_falta": f"{fonte} do {per}º bimestre de {ex}", "prazo": (termina + timedelta(days=30)).isoformat(),
                        "situacao": sit, "mes": f"{ex}-{per * 2:02d}", "fonte": k, "onde": fonte,
                        "fundamento": "LC 141/2012, art. 39 (SIOPS); Lei 14.113/2020, art. 38 (SIOPE)"})
    return out


_ENTREGAVEIS = {
    "Relatório Resumido de Execução Orçamentária": ("RREO", "bimestre"),
    "Relatório de Gestão Fiscal": ("RGF", "quadrimestre"),
    "Balanço Anual (DCA)": ("DCA", "ano"),
    "MSC Agregada": ("MSC", "mes"),
    "MSC Encerramento": ("MSC de encerramento", "ano"),
}


def _prazo_entrega(sigla: str, ex: int, per: int) -> date:
    if sigla == "RREO":
        return fim_do_mes(f"{ex}-{per * 2:02d}") + timedelta(days=30)
    if sigla == "RGF":
        return fim_do_mes(f"{ex}-{per * 4:02d}") + timedelta(days=30)
    if sigla == "DCA":
        return date(ex + 1, 4, 30)
    if sigla == "MSC":
        return fim_do_mes(mes_menos(f"{ex}-{per:02d}", -1))
    return date(ex + 1, 3, 31)


def contas(ctx: Contexto) -> dict:
    from ..contas import NORMA_CONTAS, prazo_balancete
    entregas: dict[tuple, str] = {}
    for ex, ent, per, data in consultar(ctx.con, "SELECT exercicio, entregavel, periodo, data_status FROM siconfi_entregas"):
        if ent not in _ENTREGAVEIS or not data:
            continue
        chave = (int(ex), ent, int(per or 1))
        entregas[chave] = min(entregas.get(chave, data), data)
    lista = []
    for (ex, ent, per), data in sorted(entregas.items()):
        sigla, unidade = _ENTREGAVEIS[ent]
        prazo = _prazo_entrega(sigla, ex, per)
        entregue = date.fromisoformat(data[:10])
        atraso = (entregue - prazo).days
        k = ctx.originais.de_coleta(f"extrato:{ex}", f"SICONFI: extrato de entregas de {ex}", "siconfi", f"{ex}-12",
                                    alvo=f"extrato {ex}")
        rotulo = (f"{sigla} do {per}º {unidade} de {ex}" if unidade in ("bimestre", "quadrimestre")
                  else f"{sigla} de {rotulo_mes(f'{ex}-{per:02d}')}" if unidade == "mes" else f"{sigla} de {ex}")
        lista.append({"exercicio": ex, "rotulo": rotulo, "sigla": sigla, "prazo": prazo.isoformat(),
                      "entregue": entregue.isoformat(), "atraso": N(max(atraso, 0), k), "no_prazo": atraso <= 0,
                      "mes": prazo.isoformat()[:7]})
    anuais = []
    abertura = ctx.alvo.abertura_sessao
    ultimo = ctx.hoje.year - 1
    primeiro = int(getattr(ctx.alvo, "primeiro_exercicio", 0) or _primeiro_exercicio())
    for ex in range(primeiro, ultimo + 1):
        prazo = date(ex + 1, *abertura) + timedelta(days=60)
        venceu = ctx.hoje > prazo
        dados_ano = any(e["exercicio"] == ex for e in lista)
        k = ctx.originais.sem_original(f"contas_anuais:{ex}", f"Contas anuais de {ex} no Tribunal de Contas dos Municípios",
                                       "O Tribunal de Contas dos Municípios ainda não é lido pelo sistema; "
                                       "a entrega, o parecer prévio e o julgamento não estão no banco.")
        anuais.append({"exercicio": ex, "prazo_entrega": prazo.isoformat(), "venceu": venceu,
                       "parecer_ate": (prazo + timedelta(days=60)).isoformat(),
                       "julgamento_ate": (prazo + timedelta(days=135)).isoformat(),
                       "limite_final": date(ex + 2, 12, 31).isoformat(),
                       "conferencia": "possível" if dados_ano else "impossível", "fonte": k})
    balancetes = [{"mes": m, "prazo": prazo_balancete(m).isoformat()} for m in ctx.meses_msc()]
    return {"entregas": lista, "anuais": anuais, "balancetes": balancetes, "norma": NORMA_CONTAS}


def _primeiro_exercicio() -> int:
    import tomllib
    try:
        return int(tomllib.loads((RAIZ / "alvos" / "goiania.toml").read_text(encoding="utf-8")).get("primeiro_exercicio", 2019))
    except (OSError, ValueError):
        return 2019


# =============================================================================================
# Máquina do tempo
# =============================================================================================

def tempo(ctx: Contexto, primeiro: int | None = None, ultimo_ppa: int | None = None) -> dict:
    from .. import tempo as maquina
    import tomllib
    try:
        cfg = tomllib.loads((RAIZ / "alvos" / f"{ctx.alvo_id}.toml").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cfg = {}
    primeiro = primeiro or int(cfg.get("primeiro_exercicio", 2019))
    ultimo_ppa = ultimo_ppa or int(cfg.get("ultimo_exercicio_ppa", ctx.hoje.year + 3))
    linhas = consultar(ctx.con, (
        "SELECT exercicio, periodo, cod_conta, coluna, valor FROM siconfi_itens WHERE demonstrativo = 'RREO' AND "
        "anexo = 'RREO-Anexo 01' AND cod_conta IN ('TotalReceitas', 'TotalDespesas')"))
    por: dict[tuple[int, int], dict[str, float]] = defaultdict(dict)
    for ex, per, cod, col, v in linhas:
        k = None
        if cod == "TotalReceitas" and col.startswith("PREVISÃO ATUALIZADA"):
            k = "receita_prevista"
        elif cod == "TotalReceitas" and col.startswith("Até o Bimestre"):
            k = "receita_realizada"
        elif cod == "TotalDespesas" and col.startswith("DOTAÇÃO ATUALIZADA"):
            k = "dotacao"
        elif cod == "TotalDespesas" and col.startswith("DESPESAS EMPENHADAS ATÉ"):
            k = "empenhado"
        elif cod == "TotalDespesas" and col.startswith("DESPESAS LIQUIDADAS ATÉ"):
            k = "liquidado"
        elif cod == "TotalDespesas" and col.startswith("DESPESAS PAGAS ATÉ"):
            k = "pago"
        if k:
            por[(int(ex), int(per))][k] = float(v or 0)
    dot = _dotacoes(ctx)
    anos = []
    historico, historico_f = [], defaultdict(list)
    promessa, promessa_f = {}, defaultdict(dict)
    for ano in range(primeiro, ultimo_ppa + 1):
        periodos = sorted(p for (e, p) in por if e == ano)
        if not periodos:
            anos.append({"ano": ano, "tipo": "sem_dado" if ano <= ctx.hoje.year else "futuro",
                         "fonte": ctx.originais.sem_original(f"tempo:{ano}", f"RREO de {ano}",
                                                             "O RREO deste exercício não está no banco." if ano <= ctx.hoje.year
                                                             else "O PPA com as metas deste ano não está no banco.")})
            continue
        p = periodos[-1]
        d = por[(ano, p)]
        k = og.siconfi(ctx.originais, "RREO", ano, p)
        fechado = p == 6
        funcoes = {f: {"dotacao": N(x.get("atualizada"), k), "liquidado": N(x.get("liquidada"), k)}
                   for f, x in dot.get((ano, p), {}).items()}
        anos.append({"ano": ano, "tipo": "fechado" if fechado else "parcial", "bimestre": p, "fonte": k,
                     **{c: N(d.get(c), k) for c in ("receita_prevista", "receita_realizada", "dotacao", "empenhado",
                                                     "liquidado", "pago")}, "funcoes": funcoes})
        if fechado:
            historico.append(maquina.Exercicio(ano, d.get("dotacao", 0.0), d.get("pago")))
            for f, x in dot.get((ano, p), {}).items():
                historico_f[f].append(maquina.Exercicio(ano, x.get("atualizada", 0.0), x.get("liquidada")))
        else:
            promessa[ano] = d.get("dotacao", 0.0)
            for f, x in dot.get((ano, p), {}).items():
                promessa_f[f][ano] = x.get("atualizada", 0.0)
    projecao = maquina.projetar(historico, promessa)
    proj_f = {f: maquina.projetar(historico_f.get(f, []), pr) for f, pr in promessa_f.items()}
    fp = ctx.originais.sem_original("projecao", "Projeção do Onisciente",
                                    "Projeção pela execução média dos últimos três exercícios fechados; é projeção, não dado.")

    def conv(lista):
        return [{**{k: v for k, v in x.items() if k not in ("prometido", "projetado", "diferenca")},
                 "prometido": N(x.get("prometido"), fp), "projetado": N(x.get("projetado"), fp),
                 "diferenca": N(x.get("diferenca"), fp)} for x in lista]
    fechados = [e.ano for e in historico]
    return {"anos": anos, "projecao": conv(projecao), "projecao_funcao": {f: conv(v) for f, v in proj_f.items()},
            "fechados": fechados, "regua": "execução média dos últimos 3 exercícios fechados",
            "falta": None if len(fechados) >= 3 else
            f"A média de três anos precisa de três exercícios fechados no banco; há {len(fechados)} "
            f"({', '.join(map(str, fechados)) or 'nenhum'}).", "primeiro": primeiro, "ultimo_ppa": ultimo_ppa}


# =============================================================================================
# Leis
# =============================================================================================

def leis(ctx: Contexto) -> dict:
    m = ctx.mapa
    lidas = {c: (ok, rev) for c, ok, rev in consultar(ctx.con, "SELECT caminho, ok, revogada FROM normas")}
    regras = []
    for r in m.regras.values():
        valor = r.valor
        if valor is None:
            faixas = r.get("faixas")
            if isinstance(faixas, dict) and ctx.alvo.faixa_camara in faixas:
                valor = float(faixas[ctx.alvo.faixa_camara])
        norma = next((n for n in m.normas.values() if r.id in n.conferencias), None)
        url = (norma.links(m.base_ctresb)[0][1] if norma and norma.links(m.base_ctresb) else "")
        k = ctx.originais.externo(f"regra:{r.id}", f"{r.norma}", url,
                                  nota="Texto da norma no acervo ctresb/leis ou no Sileg.")
        regras.append({"id": r.id, "titulo": r.titulo, "tipo": r.tipo, "familia": r.familia, "gravidade": r.gravidade,
                       "valor": N(valor, k) if valor is not None else None, "unidade": r.unidade, "base": r.base,
                       "norma": r.norma, "fonte_dado": list(r.fonte_dado), "funcao": _FUNCAO_DA_REGRA.get(r.id)})
    normas = []
    for n in m.normas.values():
        links = n.links(m.base_ctresb)
        lida = [lidas.get(c) for c in n.ctresb if c in lidas]
        normas.append({"id": n.id, "area": n.area, "norma": n.norma, "assunto": n.assunto, "parametro": n.parametro,
                       "conferencias": list(n.conferencias), "localizada": n.localizada, "revogada": n.revogada,
                       "links": [[nome, url] for nome, url in links],
                       "conferida": None if not lida else all(x[0] for x in lida)})
    return {"versao": m.versao, "regras": regras, "normas": normas}


# =============================================================================================
# Início
# =============================================================================================

def inicio(ctx: Contexto, rio_dados: dict, precos_dados: dict) -> dict:
    """A frase do mês, a nota de integridade e os números grandes de cada competência."""
    por_c = {}
    meses = rio_dados.get("meses", {})
    for c in ctx.competencias():
        p = ctx.panoramas.get(c) or {}
        integ = p.get("integridade") or {}
        k = ctx.originais.sem_original(f"panorama:{c}", f"Parecer de {rotulo_mes(c)}",
                                       "Cálculo do parecer mensal, a partir das fontes de cada seção.")
        ms = [m for m in meses if m[:4] == c[:4] and m <= c]
        rc = rio_dados.get("por_c", {}).get(c) or {}
        fa = rc.get("fonte") or k
        receita = sum(v for m in ms for _, _, v in meses[m]["a"])
        empenhado = sum(v for m in ms for _, _, v in meses[m]["b"])
        fora = sum(d["valor"]["v"] for d in rc.get("desvios", []))
        janela = mes_menos(c, JANELA - 1)
        contratos = [x for x in precos_dados.get("contratos", []) if janela <= x[1] <= c]
        por_c[c] = {"frase": p.get("em_uma_frase"), "contagem": p.get("contagem"),
                    "integridade": N(integ.get("nota"), k) if integ.get("nota") is not None else None,
                    "integridade_max": integ.get("nota_maxima"), "dominio": p.get("dominio"),
                    "parecer": f"../parecer_{c}.html" if p else None,
                    "receita": N(receita, fa) if ms else None, "empenhado": N(empenhado, fa) if ms else None,
                    "fora_do_leito": N(fora, fa) if ms else None,
                    "contratos": [len(contratos), N(sum(x[6]["v"] for x in contratos), f"pncp_janela:{c}")]}
        ctx.originais.sem_original(f"pncp_janela:{c}", f"PNCP: contratos assinados de {rotulo_mes(janela)} a {rotulo_mes(c)}",
                                   "Soma de várias leituras do PNCP; cada contrato abre a sua na tela Preço e entrega.")
    return {"por_c": por_c}


def indice_das_fichas(fichas: list[dict]) -> list[dict]:
    """O resumo de todas as fichas, embutido em todas as páginas para contar por tema no recorte."""
    out = []
    for f in fichas:
        d = {"k": f["codigo"], "t": f["tema"], "g": f["gravidade"], "f": f["familia"], "s": f["secretarias"],
             "e": f.get("etapa", ""), "cd": f.get("condicao", "alerta")}
        if f["cs"]:
            d["cs"] = f["cs"]
        else:
            d["de"], d["ate"] = f.get("de"), f.get("ate")
        out.append(d)
    return out


def carregar_entradas(pasta: Path = ENTRADAS) -> dict[str, dict]:
    """Os arquivos que as outras frentes entregam (selo, empresas, execução, federais)."""
    out = {}
    for nome in ("selo_transparencia", "empresas", "execucao", "federais"):
        arq = pasta / f"{nome}.json"
        if arq.is_file():
            try:
                out[nome] = json.loads(arq.read_text(encoding="utf-8"))
            except ValueError:
                continue
    return out
