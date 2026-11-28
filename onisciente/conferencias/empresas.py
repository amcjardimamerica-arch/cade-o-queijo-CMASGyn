"""As empresas contratadas pelo Município conferidas contra o cadastro da Receita Federal e os impedimentos.

Cruza cada contrato do PNCP (``contratos_pncp`` e o detalhe) com o cadastro e o quadro societário da
contratada (``cnpj_empresas``, ``cnpj_socios``, coletados por ``onisciente.coletores.cnpj``), com as
sanções (``sancoes`` e ``impedimentos``) e, quando houver, com a folha nominal (``servidores``). Confere:

* situação cadastral diferente de ATIVA na data da assinatura ou hoje;
* pouco tempo de funcionamento (abertura até a assinatura abaixo do limiar) e empresa aberta perto da
  licitação (ou depois dela);
* falta de experiência: nenhum contrato ou item ganho antes no mesmo ramo, em qualquer órgão do banco;
  CNAE principal e secundários incompatíveis com o objeto; CNAE compatível incluído há pouco; capital
  social incompatível com o valor;
* MEI, microempresa ou optante do Simples com contratos no ano acima do teto de receita;
* impedimentos: a empresa, um sócio ou administrador (ou o fornecedor pessoa física) no CEIS, no CNEP,
  no CEPIM ou na lista de inidôneos do TCU na data do contrato (ou durante a vigência);
* sócio ou administrador que é servidor ou agente público do Município (sem a folha no banco, a
  conferência registra que não pôde cruzar, e isso é alerta de transparência);
* empresas ligadas (sócio, administrador, endereço, telefone ou correio eletrônico em comum) na mesma
  compra ou no mesmo processo, ou revezando contratos do mesmo órgão e ramo (rodízio); sócio laranja
  (mesma pessoa em muitas contratadas, ou de idade atípica);
* endereço residencial ou virtual, endereço em comum entre contratadas, razão social trocada pouco
  antes, e CNPJ que não consta na base da Receita.

Todos os limiares vêm de ``config/limiares_empresas.yml``, escolhidos do lado restritivo. Cada alerta é
indício para apuração, nunca acusação, e a ficha diz isso.
"""

from __future__ import annotations

import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from datetime import date, timedelta
from html import escape
from itertools import combinations
from pathlib import Path

import yaml

from .. import partes as _partes
from .. import RAIZ
from ..coletores import cnpj as rf
from ..coletores.impedimentos import Sancao, documento, ler_sancoes, miolo_cpf
from ..nucleo.indicios import Familia, Ficha, emitir
from ..nucleo.provas import Nivel
from .compras import JANELA_DE_MESES, Achado, _mes_menos, _norm, _tabela, da_pasta, ramo as ramo_de_compras

LIMIARES = RAIZ / "config" / "limiares_empresas.yml"
AVISO = ("Isto é indício para apuração, não acusação: a conferência cruza registros públicos e o fato pode "
         "ter explicação legítima.")

TITULOS = {
    "situacao_irregular": "Contratada com situação cadastral diferente de ATIVA",
    "pouco_tempo": "Contratada com pouco tempo de funcionamento",
    "perto_da_licitacao": "Contratada aberta perto da licitação",
    "sem_experiencia": "Contratada sem experiência registrada no objeto",
    "cnae_incompativel": "Atividade (CNAE) da contratada incompatível com o objeto",
    "cnae_recente": "Atividade compatível incluída pouco antes do contrato",
    "capital_baixo": "Capital social incompatível com o valor do contrato",
    "porte_acima": "MEI, microempresa ou Simples com contratos acima do teto do ano",
    "sancionada": "Contratada impedida ou sancionada na data do contrato",
    "socio_sancionado": "Sócio ou administrador da contratada sancionado",
    "socio_servidor": "Sócio ou administrador da contratada é servidor do Município",
    "folha_ausente": "Folha nominal dos servidores não disponível para o cruzamento",
    "vinculo_mesma_compra": "Empresas ligadas na mesma compra",
    "rodizio": "Empresas ligadas revezando contratos no mesmo órgão e ramo",
    "socio_laranja": "Sócio em muitas contratadas ou com idade atípica",
    "endereco_residencial": "Contratada sediada em endereço residencial ou virtual",
    "endereco_comum": "Contratadas diferentes no mesmo endereço",
    "razao_alterada": "Razão social da contratada trocada",
    "cnpj_nao_encontrado": "CNPJ da contratada não consta na base da Receita",
}

PALAVRAS_VAZIAS = {
    "SERVICO", "SERVICOS", "CONTRATACAO", "EMPRESA", "AQUISICAO", "FORNECIMENTO", "PRESTACAO", "MUNICIPAL",
    "MUNICIPIO", "SECRETARIA", "ATENDER", "DEMANDA", "DEMANDAS", "CONFORME", "ESPECIFICACOES", "ESPECIALIZADA",
    "EVENTUAL", "FUTURA", "REGISTRO", "PRECOS", "PRECO", "GOIANIA", "ATRAVES", "DURANTE", "PERIODO", "CONTRATO",
    "OBJETO", "TERMO", "REFERENCIA", "ANEXO", "EDITAL", "UNIDADES", "UNIDADE", "DIVERSOS", "DIVERSAS", "MATERIAL",
    "MATERIAIS", "OUTROS", "OUTRAS", "VISANDO", "DESTINADOS", "DESTINADAS", "NECESSIDADES", "QUANTIDADES",
    "EXIGENCIAS", "ESTABELECIDAS", "CONDICOES", "POLITICAS", "ASSISTENCIA", "SOCIAL", "DIREITOS", "HUMANOS",
    "MULHERES", "PUBLICA", "PUBLICO", "PUBLICOS", "GERAL", "GERAIS", "COMPREENDENDO", "INCLUINDO", "SEMASDH",
}
SUFIXOS_RAZAO = {"LTDA", "ME", "EPP", "EIRELI", "SA", "S", "A", "S/A", "SLU", "SS", "MEI", "CIA", "E", "DE", "DA",
                 "DO", "DOS", "DAS", "EM", "LIMITADA"}
QUALIFICACOES_DE_GESTAO = ("ADMINISTRADOR", "DIRETOR", "PRESIDENTE", "TITULAR", "SOCIO-GERENTE", "GERENTE",
                           "PROCURADOR", "RESPONSAVEL", "EMPRESARIO")


# --- Limiares ------------------------------------------------------------------------------------

def carregar_limiares(caminho: Path = LIMIARES) -> dict:
    return yaml.safe_load(caminho.read_text(encoding="utf-8"))


def _v(cfg: dict, nome: str):
    return cfg["limiares"][nome]["valor"]


# --- Utilidades ----------------------------------------------------------------------------------

def _d(texto) -> date | None:
    t = str(texto or "")
    m = re.match(r"(\d{4})-(\d{2})(?:-(\d{2}))?", t)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3) or 1))
    except ValueError:
        return None


def _meses_entre(inicio: date, fim: date) -> int:
    meses = (fim.year - inicio.year) * 12 + fim.month - inicio.month
    return meses - (1 if fim.day < inicio.day else 0)


def _moeda(v: float) -> str:
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _data_br(iso: str | None) -> str:
    d = _d(iso)
    return d.strftime("%d/%m/%Y") if d else "sem data"


def palavras(texto, minimo: int = 5) -> set[str]:
    """Palavras significativas (radical de 6 letras), sem as palavras de edital."""
    out = set()
    for p in re.findall(r"[A-Z]+", _norm(texto)):
        if len(p) >= minimo and p not in PALAVRAS_VAZIAS:
            out.add(p[:6])
    return out


def _tokens_razao(nome) -> set[str]:
    return {t for t in re.findall(r"[A-Z0-9]+", _norm(nome)) if t not in SUFIXOS_RAZAO and not t.isdigit()}


def similaridade(a, b) -> float:
    ta, tb = _tokens_razao(a), _tokens_razao(b)
    if not ta or not tb:
        return 1.0
    return len(ta & tb) / len(ta | tb)


def ramo(objeto: str, cfg: dict) -> str | None:
    """O ramo do objeto: primeiro os ramos de ``compras.py``, depois os ramos extras da configuração."""
    r = ramo_de_compras(objeto)
    if r:
        return r
    texto = _norm(objeto)
    for nome, termos in (cfg.get("ramos_extra") or {}).items():
        if any(_norm(t) in texto for t in termos):
            return nome
    return None


def cnaes_aceitos(r: str | None, cfg: dict) -> list[str]:
    codigos = (cfg.get("cnae_por_ramo") or {}).get(r) or []
    return [str(c).zfill(2) if isinstance(c, int) else str(c) for c in codigos]


def _endereco_chave(e: dict) -> str:
    log, num, cep = e.get("logradouro") or "", e.get("numero") or "", e.get("cep") or ""
    if not log or not cep:
        return ""
    if num in ("", "S/N", "SN", "0"):
        num = "S/N " + (e.get("complemento") or "")
    return f"{log}|{num.strip()}|{cep}"


def tipo_de_endereco(e: dict, cfg: dict) -> str:
    texto = " " + _norm(f"{e.get('logradouro', '')} {e.get('complemento', '')} {e.get('endereco', '')}") + " "
    if any(_norm(p) in texto for p in cfg.get("palavras_endereco_virtual") or []):
        return "virtual"
    if any(" " + _norm(p).strip() + " " in texto for p in cfg.get("palavras_endereco_residencial") or []):
        return "residencial"
    return ""


def _gestao(qualificacao) -> bool:
    q = _norm(qualificacao)
    return any(p in q for p in QUALIFICACOES_DE_GESTAO)


# --- Leitura do banco ----------------------------------------------------------------------------

@dataclass
class Contrato:
    id: str
    mes: str
    data: str
    orgao_cnpj: str
    orgao: str
    ni: str
    fornecedor: str
    objeto: str
    valor: float
    compra_id: str | None = None
    processo: str | None = None
    publicacao: str | None = None
    vigencia_fim: str | None = None
    ramo: str | None = None

    @property
    def pj(self) -> bool:
        return len(self.ni) == 14

    @property
    def basico(self) -> str:
        return self.ni[:8] if self.pj else self.ni


def _doc(ni: str) -> str:
    """O documento do fornecedor como aparece no texto: o CNPJ, ou o CPF mascarado (os seis do meio)."""
    return f"***.{ni[:3]}.{ni[3:]}-**" if len(ni) == 6 and ni.isdigit() else ni


_CPF_NO_NOME = re.compile(r"\*{3}\.\d{3}\.\d{3}-\*{2}|(?<![\d.])\d{3}\.\d{3}\.\d{3}-\d{2}(?!\d)|(?<!\d)\d{11}(?!\d)")


def _mesmo_nome(a: str, b: str) -> bool:
    """Mesmo nome, com ou sem o CPF (inteiro ou mascarado) que algumas fontes juntam a ele."""
    return bool(a) and bool(b) and (a == b or _sem_cpf(a) == _sem_cpf(b) != "")


@lru_cache(maxsize=None)
def _sem_cpf(nome: str) -> str:
    """O nome sem o CPF que algumas fontes juntam a ele (inteiro ou mascarado), para comparar nomes."""
    return " ".join(_CPF_NO_NOME.sub(" ", nome or "").split())


@dataclass
class Pessoa:
    chave: str
    nome: str
    doc: str
    qualificacao: str
    faixa: str
    gestao: bool


def _contratos(con: sqlite3.Connection, cfg: dict) -> list[Contrato]:
    tem_det = _tabela(con, "pncp_contratos_detalhe")
    tem_amp = _tabela(con, "pncp_amparos")
    sql = ("SELECT c.pncp_id, c.mes, c.data_assinatura, c.orgao_cnpj, c.orgao, c.fornecedor_ni, c.fornecedor, "
           "c.objeto, COALESCE(c.valor_global, 0), "
           + ("d.compra_id, d.processo, d.vigencia_fim, " if tem_det else "NULL, NULL, NULL, ")
           + ("a.data_publicacao " if tem_det and tem_amp else "NULL ")
           + "FROM contratos_pncp c "
           + ("LEFT JOIN pncp_contratos_detalhe d ON d.contrato_id = c.pncp_id " if tem_det else "")
           + ("LEFT JOIN pncp_amparos a ON a.compra_id = d.compra_id " if tem_det and tem_amp else "")
           + "ORDER BY c.data_assinatura, c.pncp_id")
    saida = []
    for (pid, mes, data, ocnpj, orgao, ni, forn, obj, valor, compra, proc, vfim, pub) in con.execute(sql):
        ni = rf.so_cnpj(ni)
        data = data or (f"{mes}-01" if mes else "")
        saida.append(Contrato(pid, mes or (data or "")[:7], data, ocnpj or "", orgao or "", ni, forn or "",
                              obj or "", float(valor or 0), compra, proc, (pub or "")[:10] or None, vfim,
                              ramo(obj or "", cfg)))
    return saida


def _itens_ganhos(con: sqlite3.Connection) -> list[tuple[str, str, str, str]]:
    """(compra, fornecedor, data do resultado, descrição) dos itens com vencedor."""
    if not _tabela(con, "pncp_itens"):
        return []
    return [(c, rf.so_cnpj(f), d or "", desc or "") for c, f, d, desc in con.execute(
        "SELECT compra_id, fornecedor_ni, data_resultado, descricao FROM pncp_itens "
        "WHERE fornecedor_ni IS NOT NULL AND fornecedor_ni != ''")]


def _empresas(con: sqlite3.Connection) -> tuple[dict[str, dict], dict[str, list[dict]], dict[str, str], dict,
                                                    dict[str, str]]:
    empresas: dict[str, dict] = {}
    socios: dict[str, list[dict]] = defaultdict(list)
    cnaes: dict[str, str] = {}
    historico: dict = defaultdict(lambda: defaultdict(dict))
    ausentes: dict[str, str] = {}
    if _tabela(con, "cnpj_empresas"):
        cur = con.execute("SELECT * FROM cnpj_empresas")
        nomes = [c[0] for c in cur.description]
        for linha in cur:
            r = dict(zip(nomes, linha))
            empresas[r["cnpj"]] = r
    if _tabela(con, "cnpj_socios"):
        cur = con.execute("SELECT * FROM cnpj_socios")
        nomes = [c[0] for c in cur.description]
        for linha in cur:
            r = dict(zip(nomes, linha))
            socios[r["cnpj"]].append(r)
    if _tabela(con, "cnpj_codigos"):
        cnaes = {c: d for c, d in con.execute("SELECT codigo, descricao FROM cnpj_codigos WHERE tabela = 'Cnaes'")}
    if _tabela(con, "cnpj_historico"):
        for cnpj, campo, valor, primeira, ultima in con.execute("SELECT * FROM cnpj_historico"):
            historico[cnpj][campo][valor] = (primeira, ultima)
    if _tabela(con, "cnpj_ausentes"):
        ausentes = {c: m for c, m in con.execute("SELECT cnpj, motivo FROM cnpj_ausentes")}
    return empresas, socios, cnaes, historico, ausentes


def _servidores(con: sqlite3.Connection) -> list[dict] | None:
    """A folha nominal, se alguma frente a coletou: ``servidores(nome, cpf, cargo, orgao, inicio, fim)``
    (as colunas além do nome são opcionais). ``None`` quando não há folha no banco."""
    if not _tabela(con, "servidores"):
        return None
    cols = [c[1] for c in con.execute("PRAGMA table_info(servidores)")]
    if "nome" not in cols:
        return None
    sel = ", ".join(c if c in cols else f"NULL AS {c}" for c in ("nome", "cpf", "cargo", "orgao", "inicio", "fim"))
    linhas = [dict(zip(("nome", "cpf", "cargo", "orgao", "inicio", "fim"), r))
              for r in con.execute(f"SELECT {sel} FROM servidores")]
    return linhas or None


def pessoas_da_empresa(socios: list[dict]) -> list[Pessoa]:
    """Sócios e administradores, e os representantes legais, com a chave de comparação:
    ``PJ:cnpj`` para sócio pessoa jurídica, ``PF:nome|miolo do CPF`` para pessoa física."""
    out: list[Pessoa] = []
    for s in socios:
        tipo, doc = documento(s.get("cpf_cnpj"))
        nome = _norm(s.get("nome"))
        if tipo == "PJ":
            chave = f"PJ:{doc}"
        elif nome:
            chave = f"PF:{nome}|{miolo_cpf(s.get('cpf_cnpj'))}"
        else:
            continue
        out.append(Pessoa(chave, nome, s.get("cpf_cnpj") or "", s.get("qualificacao") or "",
                          str(s.get("faixa_etaria") or ""), _gestao(s.get("qualificacao"))))
        rep = _norm(s.get("representante"))
        if rep:
            out.append(Pessoa(f"PF:{rep}|{miolo_cpf(s.get('representante_cpf'))}", rep,
                              s.get("representante_cpf") or "", s.get("qualificacao_representante") or
                              "representante legal", "", True))
    return out


# --- Conferências --------------------------------------------------------------------------------

@dataclass
class ConferenciasEmpresas:
    achados: list[Achado] = field(default_factory=list)
    cobertura: dict = field(default_factory=dict)
    contratos: list[Contrato] = field(default_factory=list)
    empresas: dict[str, dict] = field(default_factory=dict)
    socios: dict[str, list[dict]] = field(default_factory=dict)
    limiares: dict = field(default_factory=dict)

    def por_tipo(self, so_da_pasta: bool = False) -> dict[str, int]:
        cont = Counter(a.tipo for a in self.achados if a.da_pasta or not so_da_pasta)
        return {t: cont.get(t, 0) for t in TITULOS}

    def por_contrato(self) -> dict[str, list[Achado]]:
        out: dict[str, list[Achado]] = defaultdict(list)
        for a in self.achados:
            for cid in a.dados.get("contratos", []):
                out[cid].append(a)
        return out

    def da_competencia(self, competencia: str, so_da_pasta: bool = True) -> list[Achado]:
        inicio = _mes_menos(competencia, JANELA_DE_MESES - 1)
        return [a for a in self.achados if (a.da_pasta or not so_da_pasta or a.tipo == "folha_ausente")
                and (inicio <= a.mes <= competencia or a.tipo == "folha_ausente")]

    def fichas(self, competencia: str | None = None) -> list[Ficha]:
        lista = (self.da_competencia(competencia) if competencia
                 else [a for a in self.achados if a.da_pasta or a.tipo == "folha_ausente"])
        out = [ficha(a, competencia) for a in lista]
        lacunas = self.cobertura.get("lacunas") or []
        if lacunas:
            out.append(emitir(
                codigo="SIS-EMPRESAS-COBERTURA", familia=Familia.SIS,
                titulo="Conferência das empresas contratadas ainda incompleta no banco", gravidade="media",
                como_deveria="Cada contratada conferida no cadastro da Receita, no quadro societário e nos "
                             "cadastros de impedidos e sancionados, na data do contrato.",
                norma="Desenho do Onisciente: falha de coleta é falha do sistema, nunca silêncio do Município",
                como_esta="; ".join(lacunas)[:1].upper() + "; ".join(lacunas)[1:] + ".",
                niveis=[Nivel.F], documento_faltante=True,
                providencia="Rodar os motores cnpj e impedimentos (e o das sanções CEIS e CNEP) na coleta "
                            "histórica.", competencia=competencia))
        faltam = self.cobertura.get("sancoes_nao_conferidas") or {}
        if faltam:
            out.append(emitir(
                codigo="SIS-EMPRESAS-SANCOES", familia=Familia.SIS,
                titulo="Sanções e impedimentos das contratadas não conferidos", gravidade="alta",
                como_deveria="Cada contratada e cada sócio conferidos no CEIS, no CNEP, no CEPIM e na lista de "
                             "inidôneos do TCU, na data do contrato.",
                norma="Lei 14.133/2021, arts. 14 e 156, III e IV; Lei 12.846/2013, arts. 22 e 23",
                como_esta="Não houve conferência de sanções em " + "; ".join(
                    f"{c}, porque {m}" for c, m in faltam.items()) + ". A falta de linhas é ausência de dado: "
                    "nenhuma contratada pode ser dada como livre de sanção por isso.",
                niveis=[Nivel.F], documento_faltante=True,
                providencia="Coletar os cadastros que faltam (motor das sanções CEIS e CNEP e motor impedimentos) "
                            "e rodar de novo a conferência.", competencia=competencia))
        return out

    def como_dict(self) -> dict:
        return {"por_tipo": self.por_tipo(), "por_tipo_da_pasta": self.por_tipo(True),
                "cobertura": self.cobertura,
                "achados": [{"tipo": a.tipo, "orgao": a.orgao, "chave": a.chave, "mes": a.mes,
                             "descricao": a.descricao, "valor": a.valor, "da_pasta": a.da_pasta,
                             "contratos": a.dados.get("contratos", [])} for a in self.achados]}


def conferir(banco: Path | sqlite3.Connection, *, limiares: dict | None = None,
             hoje: date | None = None) -> ConferenciasEmpresas:
    """Roda todas as conferências das empresas contratadas no banco histórico."""
    cfg = limiares or carregar_limiares()
    hoje = hoje or date.today()
    con = banco if isinstance(banco, sqlite3.Connection) else _partes.conectar_leitura(banco)
    try:
        out = ConferenciasEmpresas(limiares=cfg)
        if not _tabela(con, "contratos_pncp"):
            out.cobertura["sem_dados"] = True
            return out
        contratos = _contratos(con, cfg)
        empresas, socios, cnaes, historico, ausentes = _empresas(con)
        sancoes = ler_sancoes(con)
        servidores = _servidores(con)
        itens = _itens_ganhos(con)
        out.contratos, out.empresas, out.socios = contratos, empresas, dict(socios)
        c = _Conferidor(cfg, hoje, contratos, empresas, socios, cnaes, historico, ausentes, sancoes,
                        servidores, itens, out.achados)
        c.rodar()
        _cobertura(con, out, contratos, empresas, socios, sancoes, servidores, ausentes)
        out.achados.sort(key=lambda a: (a.mes, a.tipo, a.chave))
        return out
    finally:
        if not isinstance(banco, sqlite3.Connection):
            con.close()


class _Conferidor:
    def __init__(self, cfg, hoje, contratos, empresas, socios, cnaes, historico, ausentes, sancoes, servidores,
                 itens, achados):
        self.cfg, self.hoje = cfg, hoje
        self.contratos: list[Contrato] = contratos
        self.empresas, self.socios, self.cnaes, self.historico = empresas, socios, cnaes, historico
        self.ausentes, self.sancoes, self.servidores, self.itens = ausentes, sancoes, servidores, itens
        self.achados: list[Achado] = achados
        self.pessoas = {cnpj: pessoas_da_empresa(lista) for cnpj, lista in socios.items()}
        self._indice: tuple | None = None          # das sanções, montado no primeiro uso (_candidatas)
        self._do_basico: tuple | None = None       # contratos e itens por CNPJ básico (_experiencia)

    def add(self, tipo: str, c: Contrato, chave: str, descricao: str, *, valor: float | None = None,
            limite: float = 0.0, contratos: list[str] | None = None, **dados) -> None:
        self.achados.append(Achado(tipo, c.orgao_cnpj, c.orgao, chave, c.mes, descricao,
                                   c.valor if valor is None else valor, limite,
                                   {"contratos": contratos or [c.id], "cnpj": c.ni, **dados}))

    def empresa(self, c: Contrato) -> dict | None:
        return self.empresas.get(c.ni)

    def rodar(self) -> None:
        for c in self.contratos:
            if not c.data:
                continue
            self._experiencia(c)
            self._sancoes(c)
            self._servidor(c)
            if c.pj:
                e = self.empresa(c)
                if e is None:
                    if c.ni in self.ausentes:
                        self.add("cnpj_nao_encontrado", c, f"{c.id}",
                                 f"o contrato {c.id}, de {_moeda(c.valor)}, foi assinado com o CNPJ {c.ni} "
                                 f"({c.fornecedor}), que {self.ausentes[c.ni]}", gravidade="alta")
                    continue
                self._situacao(c, e)
                self._tempo(c, e)
                self._cnae(c, e)
                self._capital(c, e)
                self._endereco(c, e)
                self._razao(c, e)
        self._porte()
        self._ligacoes()
        self._laranjas()
        if self.servidores is None and self.contratos:
            c = max(self.contratos, key=lambda x: x.mes)
            com_socios = sum(1 for x in self.contratos if x.pj and self.socios.get(x.ni))
            self.achados.append(Achado(
                "folha_ausente", "", "Município de Goiânia (todos os órgãos)", "folha", c.mes,
                f"a folha nominal dos servidores e agentes públicos do Município (nome, CPF, cargo e lotação) "
                f"não está no banco; o cruzamento de {com_socios} contratos com o quadro societário das "
                f"contratadas não pôde ser feito, e por isso nenhum sócio ou administrador servidor seria "
                f"apontado mesmo que existisse", 0.0, 0.0, {"contratos": [], "gravidade": "media"}))

    # -- cadastro --------------------------------------------------------------------------------

    def _situacao(self, c: Contrato, e: dict) -> None:
        sit = _norm(e.get("situacao"))
        if not sit or sit == "ATIVA":
            return
        desde = e.get("data_situacao")
        na_data = bool(desde) and desde <= c.data
        quando = (f"desde {_data_br(desde)}, antes da assinatura em {_data_br(c.data)}" if na_data else
                  f"desde {_data_br(desde)} (depois da assinatura em {_data_br(c.data)}); se o contrato segue "
                  "vigente, a contratada perdeu a regularidade no curso dele")
        motivo = f", motivo {e['motivo']}" if e.get("motivo") else ""
        self.add("situacao_irregular", c, c.id,
                 f"a contratada {c.fornecedor} (CNPJ {c.ni}) está com situação cadastral {sit} na Receita"
                 f"{motivo}, {quando}; contrato {c.id}, de {_moeda(c.valor)}",
                 gravidade="alta" if na_data else "media", na_data=na_data)

    def _tempo(self, c: Contrato, e: dict) -> None:
        abertura = _d(e.get("data_abertura"))
        assinatura = _d(c.data)
        if not abertura or not assinatura:
            return
        minimo = int(_v(self.cfg, "meses_minimos_de_funcionamento"))
        if abertura > assinatura:
            self.add("pouco_tempo", c, c.id,
                     f"a contratada {c.fornecedor} (CNPJ {c.ni}) foi aberta em {_data_br(e['data_abertura'])}, "
                     f"depois da assinatura do contrato {c.id} em {_data_br(c.data)}", gravidade="alta",
                     limite=minimo, meses=-1)
        else:
            meses = _meses_entre(abertura, assinatura)
            if meses < minimo:
                self.add("pouco_tempo", c, c.id,
                         f"a contratada {c.fornecedor} (CNPJ {c.ni}) foi aberta em {_data_br(e['data_abertura'])} "
                         f"e tinha {meses} meses de funcionamento ao assinar o contrato {c.id} em "
                         f"{_data_br(c.data)}, abaixo do mínimo de {minimo} meses", gravidade="alta"
                         if meses < 6 else "media", limite=minimo, meses=meses)
        publicacao = _d(c.publicacao)
        if publicacao:
            dias = (publicacao - abertura).days
            janela = int(_v(self.cfg, "dias_abertura_antes_da_licitacao"))
            if dias < janela:
                rel = (f"{-dias} dias depois da publicação da compra em {_data_br(c.publicacao)}" if dias < 0 else
                       f"{dias} dias antes da publicação da compra em {_data_br(c.publicacao)}")
                self.add("perto_da_licitacao", c, c.id,
                         f"a contratada {c.fornecedor} (CNPJ {c.ni}) foi aberta em {_data_br(e['data_abertura'])}, "
                         f"{rel} ({c.compra_id}), dentro da janela de {janela} dias", gravidade="alta",
                         limite=janela, dias=dias)

    def _cnaes_da_empresa(self, e: dict) -> list[str]:
        return [x for x in [e.get("cnae_principal"), *(e.get("cnaes_secundarios") or "").split(",")] if x]

    def _compativeis(self, c: Contrato, e: dict) -> tuple[list[str], bool]:
        """Os CNAEs da empresa compatíveis com o objeto e se a conferência foi possível."""
        codigos = self._cnaes_da_empresa(e)
        if not codigos:
            return [], False
        aceitos = cnaes_aceitos(c.ramo, self.cfg)
        compat = [x for x in codigos if any(re.sub(r"\D", "", x).startswith(a) for a in aceitos)]
        conferivel = bool(aceitos)
        if self.cnaes:
            p_obj = palavras(c.objeto)
            for x in codigos:
                desc = self.cnaes.get(x) or self.cnaes.get(re.sub(r"\D", "", x))
                if desc:
                    conferivel = conferivel or bool(p_obj)
                    if x not in compat and p_obj & palavras(desc):
                        compat.append(x)
        return compat, conferivel

    def _cnae(self, c: Contrato, e: dict) -> None:
        compat, conferivel = self._compativeis(c, e)
        codigos = self._cnaes_da_empresa(e)
        if conferivel and not compat:
            desc = ", ".join(f"{x} {self.cnaes.get(x, '')}".strip() for x in codigos[:6])
            self.add("cnae_incompativel", c, c.id,
                     f"o objeto do contrato {c.id} ({c.objeto[:160]}) é do ramo {c.ramo or 'sem ramo definido'}, "
                     f"e nenhuma das {len(codigos)} atividades da contratada {c.fornecedor} (CNPJ {c.ni}) "
                     f"corresponde a ele: {desc}", gravidade="alta", cnaes=codigos, ramo=c.ramo)
            return
        hist = self.historico.get(c.ni, {}).get("cnae") or {}
        if not compat or not hist:
            return
        primeira_obs = min(p for p, _ in hist.values())
        janela = int(_v(self.cfg, "dias_cnae_recente"))
        assinatura = _d(c.data)
        recentes = []
        for x in compat:
            p = hist.get(x, (None, None))[0]
            if p is None or p <= primeira_obs:
                return              # já estava no cadastro desde a primeira observação
            d = _d(p)
            if d and assinatura and (assinatura - d).days <= janela:
                recentes.append((x, p))
        if recentes and len(recentes) == len(compat):
            lista = ", ".join(f"{x} (vista pela primeira vez na base de {p})" for x, p in recentes)
            self.add("cnae_recente", c, c.id,
                     f"as únicas atividades da contratada {c.fornecedor} (CNPJ {c.ni}) compatíveis com o objeto "
                     f"do contrato {c.id}, assinado em {_data_br(c.data)}, entraram no cadastro há pouco: {lista}; "
                     f"o cadastro observado desde {primeira_obs} não as tinha", gravidade="media", limite=janela)

    def _capital(self, c: Contrato, e: dict) -> None:
        cap = e.get("capital_social")
        fracao = float(_v(self.cfg, "fracao_minima_capital_social"))
        if cap is None or c.valor <= 0:
            return
        if float(cap) < fracao * c.valor:
            pct = 100 * float(cap) / c.valor
            self.add("capital_baixo", c, c.id,
                     f"a contratada {c.fornecedor} (CNPJ {c.ni}) tem capital social de {_moeda(float(cap))}, "
                     f"{pct:.1f}% do contrato {c.id} ({_moeda(c.valor)}), abaixo de {fracao:.0%}",
                     gravidade="alta" if pct < 1 else "media", limite=fracao * c.valor)

    def _endereco(self, c: Contrato, e: dict) -> None:
        tipo = tipo_de_endereco(e, self.cfg)
        if tipo and c.valor >= float(_v(self.cfg, "valor_minimo_endereco_residencial")):
            self.add("endereco_residencial", c, c.id,
                     f"a sede da contratada {c.fornecedor} (CNPJ {c.ni}) tem indício de endereço {tipo} "
                     f"({e.get('endereco')}); contrato {c.id}, de {_moeda(c.valor)}", gravidade="media",
                     tipo_endereco=tipo)

    def _razao(self, c: Contrato, e: dict) -> None:
        minimo = float(_v(self.cfg, "similaridade_minima_da_razao"))
        atual = e.get("razao") or ""
        partes = []
        sim = similaridade(c.fornecedor, atual) if atual and c.fornecedor else 1.0
        if sim < minimo:
            partes.append(f"o contrato {c.id} registra a contratada como \"{c.fornecedor}\" e a Receita hoje como "
                          f"\"{atual}\" ({sim:.0%} das palavras em comum)")
        razoes = self.historico.get(c.ni, {}).get("razao") or {}
        if len(razoes) > 1:
            janela = int(_v(self.cfg, "dias_razao_recente"))
            assinatura = _d(c.data)
            for nome, (primeira, _) in sorted(razoes.items(), key=lambda kv: kv[1][0]):
                d = _d(primeira)
                if primeira == min(p for p, _ in razoes.values()) or not d or not assinatura:
                    continue
                if 0 <= (assinatura - d).days <= janela:
                    partes.append(f"a razão social passou a ser \"{nome}\" na base de {primeira}, até {janela} dias "
                                  f"antes da assinatura em {_data_br(c.data)}")
        if partes:
            self.add("razao_alterada", c, c.id, "; ".join(partes), gravidade="media")

    # -- experiência -----------------------------------------------------------------------------

    def _experiencia(self, c: Contrato) -> None:
        if not c.pj:
            return
        minimo = int(_v(self.cfg, "contratos_anteriores_minimos"))
        anteriores = 0
        p_obj = palavras(c.objeto)
        if self._do_basico is None:                # contratos e itens agrupados pelo CNPJ básico
            self._do_basico = ({}, {})
            for o in self.contratos:
                self._do_basico[0].setdefault(o.basico, []).append(o)
            for item in self.itens:
                forn = item[1]
                self._do_basico[1].setdefault(forn[:8] if len(forn) == 14 else forn, []).append(item)
        for o in self._do_basico[0].get(c.basico, ()):
            if o.id == c.id or o.basico != c.basico or not o.data or o.data >= c.data:
                continue
            if (c.ramo and o.ramo == c.ramo) or (not c.ramo and len(p_obj & palavras(o.objeto)) >= 2):
                anteriores += 1
        for compra, forn, data, desc in self._do_basico[1].get(c.basico, ()):
            if (forn[:8] if len(forn) == 14 else forn) != c.basico or not data or data[:10] >= c.data:
                continue
            if compra == c.compra_id:
                continue
            r = ramo(desc, self.cfg)
            if (c.ramo and r == c.ramo) or (not c.ramo and len(p_obj & palavras(desc)) >= 2):
                anteriores += 1
        if anteriores < minimo:
            inicio = min((o.data for o in self.contratos if o.data), default="")
            self.add("sem_experiencia", c, c.id,
                     f"a contratada {c.fornecedor} ({_doc(c.ni)}) não tem, no banco (contratos e itens do PNCP de todos "
                     f"os órgãos do Município desde {_data_br(inicio)}), nenhum contrato ou item ganho antes de "
                     f"{_data_br(c.data)} no ramo {c.ramo or 'do objeto'}; contrato {c.id}, de {_moeda(c.valor)}",
                     gravidade="media", limite=minimo, ramo=c.ramo)

    # -- impedimentos ----------------------------------------------------------------------------

    def _casa(self, s: Sancao, tipo: str, doc: str, nome: str) -> tuple[bool, bool]:
        """(casa, casou só pelo nome ou pelo CPF parcial). PJ casa pela raiz do CNPJ; PF pelo CPF inteiro,
        ou pelos seis dígitos do meio somados ao nome quando um dos lados vem mascarado."""
        if tipo == "PJ":
            if s.tipo_doc == "PJ":
                return s.doc[:8] == doc[:8], False
            return (not s.tipo_doc and _mesmo_nome(s.nome, nome)), True
        if tipo == "PF" and s.tipo_doc == "PF":
            return s.doc == doc, False
        m = doc[3:9] if tipo == "PF" else doc if tipo == "PF6" else ""
        sm = s.doc[3:9] if s.tipo_doc == "PF" else s.doc if s.tipo_doc == "PF6" else ""
        if sm and m:
            return sm == m and (not s.nome or not nome or _mesmo_nome(s.nome, nome)), True
        return (not sm and _mesmo_nome(s.nome, nome)), True

    def _candidatas(self, tipo: str, doc: str, nome: str) -> list[Sancao]:
        """As sanções que podem casar (as que ``_casa`` aceitaria estão todas aqui), na ordem da lista.
        Comparar cada contrato com a lista inteira dava 800 milhões de comparações por parecer."""
        if self._indice is None:
            raiz: dict[str, list[int]] = {}
            miolo: dict[str, list[int]] = {}
            nome_pj: dict[str, list[int]] = {}       # sem documento: casa com empresa pelo nome
            nome_sem_cpf: dict[str, list[int]] = {}  # sem CPF (nem inteiro nem mascarado): casa com pessoa pelo nome
            for i, x in enumerate(self.sancoes):
                if x.tipo_doc == "PJ":
                    raiz.setdefault(x.doc[:8], []).append(i)
                elif x.tipo_doc in ("PF", "PF6"):
                    miolo.setdefault(x.doc[3:9] if x.tipo_doc == "PF" else x.doc, []).append(i)
                if x.tipo_doc not in ("PF", "PF6") and x.nome:
                    for chave in {x.nome, _sem_cpf(x.nome)} - {""}:
                        nome_sem_cpf.setdefault(chave, []).append(i)
                        if not x.tipo_doc:
                            nome_pj.setdefault(chave, []).append(i)
            self._indice = (raiz, miolo, nome_pj, nome_sem_cpf)
        raiz, miolo, nome_pj, nome_sem_cpf = self._indice
        chaves = {nome, _sem_cpf(nome)} - {""} if nome else set()
        achadas: set[int] = set()
        if tipo == "PJ":
            achadas.update(raiz.get(doc[:8], ()))
            for k in chaves:
                achadas.update(nome_pj.get(k, ()))
        else:
            m = doc[3:9] if tipo == "PF" else doc if tipo == "PF6" else ""
            if m:
                achadas.update(miolo.get(m, ()))
            for k in chaves:
                achadas.update(nome_sem_cpf.get(k, ()))
        return [self.sancoes[i] for i in sorted(achadas)]

    def _sancoes(self, c: Contrato) -> None:
        if not self.sancoes:
            return
        if c.pj:
            alvos = [("empresa", "PJ", c.ni, _norm(c.fornecedor), None)]
            for p in self.pessoas.get(c.ni, []):
                tipo, doc = (("PJ", p.chave[3:]) if p.chave.startswith("PJ:")
                             else ("PF6", miolo_cpf(p.doc)) if miolo_cpf(p.doc) else ("", ""))
                alvos.append(("socio", tipo, doc, p.nome, p))
        else:
            # Pessoa física: o CPF inteiro casa pelo CPF inteiro; os seis do meio só quando a fonte publicou o
            # CPF mascarado (***.NNN.NNN-**), como o QSA da Receita (decisão do usuário de 28/11/2026, P-01).
            alvos = [("empresa", "PF6" if len(c.ni) == 6 else "PF", c.ni, _norm(c.fornecedor), None)]
        vigencia_fim = c.vigencia_fim or c.data
        for quem, tipo, doc, nome, pessoa in alvos:
            for s in self._candidatas(tipo, doc, nome):
                casa, parcial = self._casa(s, tipo, doc, nome)
                if not casa:
                    continue
                na_data = s.vigente_em(c.data)
                durante = not na_data and s.inicio and c.data < s.inicio <= vigencia_fim
                if not (na_data or durante):
                    continue
                periodo = (f"de {_data_br(s.inicio)} a {_data_br(s.fim) if s.fim else 'sem prazo'}" if s.inicio else
                           f"consta no cadastro na fotografia de {_data_br(s.data_base)}, sem data de início publicada")
                momento = "na data da assinatura" if na_data else "durante a vigência do contrato"
                if quem == "empresa":
                    self.add("sancionada", c, f"{c.id}-{s.cadastro}",
                             f"{'a contratada' if c.pj else 'o fornecedor pessoa física'} {c.fornecedor} ({_doc(c.ni)}) "
                             f"consta no {s.cadastro} ({s.tipo or 'sanção'}, {s.orgao or 'órgão não informado'}; "
                             f"{periodo}) {momento} do contrato {c.id}, assinado em {_data_br(c.data)}",
                             gravidade="critica" if na_data else "alta", cadastro=s.cadastro,
                             por_nome=parcial)
                else:
                    self.add("socio_sancionado", c, f"{c.id}-{s.cadastro}-{doc}",
                             f"{pessoa.nome} ({pessoa.qualificacao or 'sócio'}, {pessoa.doc or 'documento não '
                             'publicado'}) da contratada {c.fornecedor} (CNPJ {c.ni}) consta no {s.cadastro} "
                             f"({s.tipo or 'sanção'}; {periodo}) {momento} do contrato {c.id}",
                             gravidade="alta", cadastro=s.cadastro, por_nome=parcial)

    def _servidor(self, c: Contrato) -> None:
        if not self.servidores:
            return
        alvos: list[tuple[str, str, str]] = []
        if c.pj:
            for p in self.pessoas.get(c.ni, []):
                if p.chave.startswith("PF:"):
                    alvos.append((p.nome, miolo_cpf(p.doc), p.qualificacao or "sócio"))
        else:
            alvos.append((_norm(c.fornecedor), c.ni if len(c.ni) == 6 else c.ni[3:9], "fornecedor pessoa física"))
        for nome, miolo, papel in alvos:
            for s in self.servidores:
                if _norm(s.get("nome")) != nome:
                    continue
                sm = miolo_cpf(s.get("cpf"))
                if sm and miolo and sm != miolo:
                    continue
                if s.get("inicio") and str(s["inicio"])[:10] > c.data:
                    continue
                if s.get("fim") and str(s["fim"])[:10] < c.data:
                    continue
                self.add("socio_servidor", c, f"{c.id}-{nome}",
                         f"{nome} ({papel}) {'da contratada ' + c.fornecedor + ' (CNPJ ' + c.ni + ')' if c.pj else ''}"
                         f" tem o mesmo nome{' e os mesmos dígitos de CPF' if sm and miolo else ''} de servidor do "
                         f"Município ({s.get('cargo') or 'cargo não informado'}, {s.get('orgao') or 'lotação não '
                         'informada'}) na data do contrato {c.id}", gravidade="alta",
                         por_nome=not (sm and miolo))
                break

    # -- porte -----------------------------------------------------------------------------------

    def _porte(self) -> None:
        por: dict[tuple[str, str], list[Contrato]] = defaultdict(list)
        for c in self.contratos:
            if c.pj and c.data and c.ni in self.empresas:
                por[(c.basico, c.data[:4])].append(c)
        lim = {"MEI": float(_v(self.cfg, "limite_anual_mei")),
               "microempresa": float(_v(self.cfg, "limite_anual_microempresa")),
               "Simples Nacional": float(_v(self.cfg, "limite_anual_simples"))}
        for (basico, ano), lista in sorted(por.items()):
            lista.sort(key=lambda x: (x.data, x.id))
            e = self.empresas[lista[0].ni]
            for regime, teto in lim.items():
                soma, acumulado = 0.0, []
                for c in lista:
                    if not self._no_regime(e, regime, c.data):
                        continue
                    soma += c.valor
                    acumulado.append(c.id)
                    if soma > teto:
                        self.add("porte_acima", c, f"{basico}-{ano}-{regime}",
                                 f"a contratada {c.fornecedor} (CNPJ {c.ni}), {regime} na data, somou "
                                 f"{_moeda(soma)} em {len(acumulado)} contrato(s) assinados com o Município em {ano} "
                                 f"até o contrato {c.id}, acima do teto anual de {_moeda(teto)}", valor=soma,
                                 limite=teto, contratos=list(acumulado), gravidade="alta", regime=regime)
                        break

    @staticmethod
    def _no_regime(e: dict, regime: str, dia: str) -> bool:
        if regime == "microempresa":
            return "MICRO" in _norm(e.get("porte")) and e.get("mei") != "S"
        campo, ini, fim = (("mei", "data_opcao_mei", "data_exclusao_mei") if regime == "MEI"
                           else ("simples", "data_opcao_simples", "data_exclusao_simples"))
        if e.get(ini):
            return e[ini] <= dia and (not e.get(fim) or dia < e[fim])
        return e.get(campo) == "S"

    # -- ligações entre empresas -----------------------------------------------------------------

    def _sinais(self, cnpj: str) -> dict[str, set[str]]:
        e = self.empresas.get(cnpj) or {}
        s = {"pessoa": {p.chave for p in self.pessoas.get(cnpj, [])}}
        end = _endereco_chave(e)
        s["endereco"] = {end} if end else set()
        s["telefone"] = {t for t in (e.get("telefone") or "").split(",") if len(t) >= 8}
        s["email"] = {e["email"]} if e.get("email") else set()
        return s

    def _ligacao(self, a: str, b: str) -> list[str]:
        """O que liga duas contratadas de raízes diferentes: sócio ou administrador, endereço, telefone,
        correio. Matriz e filial da mesma empresa são a mesma pessoa jurídica, não empresas ligadas."""
        if a[:8] == b[:8]:
            return []
        sa, sb = self._sinais(a), self._sinais(b)
        motivos = []
        nomes = {p.chave: p.nome for p in self.pessoas.get(a, []) + self.pessoas.get(b, [])}
        for ch in sorted(sa["pessoa"] & sb["pessoa"]):
            motivos.append(f"sócio ou administrador em comum: {nomes.get(ch, ch)}")
        if sa["endereco"] & sb["endereco"]:
            e = self.empresas.get(a) or {}
            tipo = tipo_de_endereco(e, self.cfg)
            motivos.append(f"mesmo endereço{(' (' + tipo + ')') if tipo else ''}: {e.get('endereco')}")
        for t in sorted(sa["telefone"] & sb["telefone"]):
            motivos.append(f"mesmo telefone: {t}")
        for m in sorted(sa["email"] & sb["email"]):
            motivos.append(f"mesmo correio eletrônico: {m}")
        return motivos

    def _ligacoes(self) -> None:
        minimo = int(_v(self.cfg, "socios_em_comum_minimos"))
        por_id = {c.id: c for c in self.contratos}
        grupos: dict[str, set[str]] = defaultdict(set)          # compra ou processo -> CNPJs
        contratos_do_grupo: dict[str, list[str]] = defaultdict(list)
        for c in self.contratos:
            if not c.pj:
                continue
            for chave in (f"compra {c.compra_id}" if c.compra_id else None,
                          f"processo {c.orgao_cnpj} {c.processo}" if c.processo else None):
                if chave:
                    grupos[chave].add(c.ni)
                    contratos_do_grupo[chave].append(c.id)
        for compra, forn, _, _ in self.itens:
            if len(forn) == 14 and compra:
                grupos[f"compra {compra}"].add(forn)
        ja: set[tuple[str, str]] = set()
        for grupo, cnpjs in sorted(grupos.items()):
            for a, b in combinations(sorted(cnpjs), 2):
                if (a, b) in ja:
                    continue
                motivos = self._ligacao(a, b)
                if len(motivos) < minimo:
                    continue
                ja.add((a, b))
                ids = [i for i in contratos_do_grupo.get(grupo, []) if por_id[i].ni in (a, b)]
                ref = por_id[ids[0]] if ids else self._contrato_de(a) or self._contrato_de(b)
                if ref is None:
                    continue
                self.add("vinculo_mesma_compra", ref, f"{grupo}-{a}-{b}",
                         f"as empresas {self._nome(a)} ({a}) e {self._nome(b)} ({b}) participam da mesma "
                         f"{grupo.split(' ')[0]} ({grupo.split(' ', 1)[1]}) e estão ligadas: " + "; ".join(motivos),
                         valor=sum(por_id[i].valor for i in ids), contratos=ids or [ref.id], gravidade="alta",
                         motivos=motivos)
        por_orgao_ramo: dict[tuple[str, str], list[Contrato]] = defaultdict(list)
        for c in self.contratos:
            if c.pj and c.ramo:
                por_orgao_ramo[(c.orgao_cnpj, c.ramo)].append(c)
        for (orgao, r), lista in sorted(por_orgao_ramo.items()):
            cnpjs = sorted({c.ni for c in lista})
            for a, b in combinations(cnpjs, 2):
                if (a, b) in ja:
                    continue
                motivos = self._ligacao(a, b)
                if len(motivos) < minimo:
                    continue
                ja.add((a, b))
                ids = [c.id for c in lista if c.ni in (a, b)]
                ref = max((c for c in lista if c.ni in (a, b)), key=lambda x: x.data)
                self.add("rodizio", ref, f"{orgao}-{r}-{a}-{b}",
                         f"as empresas {self._nome(a)} ({a}) e {self._nome(b)} ({b}) dividem {len(ids)} contratos do "
                         f"ramo {r} no mesmo órgão ({ref.orgao}) e estão ligadas: " + "; ".join(motivos),
                         valor=sum(por_id[i].valor for i in ids), contratos=ids, gravidade="alta", motivos=motivos)
        # Endereço em comum entre quaisquer contratadas (mesmo sem disputar a mesma compra).
        por_end: dict[str, set[str]] = defaultdict(set)
        for cnpj in {c.ni for c in self.contratos if c.pj and c.ni in self.empresas}:
            end = _endereco_chave(self.empresas[cnpj])
            if end:
                por_end[end].add(cnpj)
        for end, cnpjs in sorted(por_end.items()):
            raizes = {x[:8] for x in cnpjs}
            if len(raizes) < 2:
                continue
            lista = sorted(cnpjs)
            ids = [c.id for c in self.contratos if c.ni in cnpjs]
            ref = max((c for c in self.contratos if c.ni in cnpjs), key=lambda x: x.data)
            tipo = tipo_de_endereco(self.empresas[lista[0]], self.cfg)
            self.add("endereco_comum", ref, f"end-{'-'.join(lista)}",
                     f"{len(raizes)} contratadas diferentes têm sede no mesmo endereço"
                     f"{(' com indício de endereço ' + tipo) if tipo else ''} "
                     f"({self.empresas[lista[0]].get('endereco')}): "
                     + ", ".join(f"{self._nome(x)} ({x})" for x in lista),
                     valor=sum(c.valor for c in self.contratos if c.ni in cnpjs), contratos=ids,
                     gravidade="alta" if tipo else "media")

    def _laranjas(self) -> None:
        minimo = int(_v(self.cfg, "empresas_por_socio_laranja"))
        atipicas = {str(x) for x in _v(self.cfg, "faixas_etarias_atipicas")}
        contratadas = sorted({c.ni for c in self.contratos if c.pj})
        por_pessoa: dict[str, set[str]] = defaultdict(set)
        nomes: dict[str, Pessoa] = {}
        for cnpj in contratadas:
            for p in self.pessoas.get(cnpj, []):
                por_pessoa[p.chave].add(cnpj[:8])
                nomes.setdefault(p.chave, p)
                if p.faixa in atipicas:
                    nomes[p.chave] = p
        faixas = rf.FAIXAS_ETARIAS
        for chave, raizes in sorted(por_pessoa.items()):
            p = nomes[chave]
            motivos = []
            if len(raizes) >= minimo:
                motivos.append(f"está no quadro de {len(raizes)} contratadas do Município (limiar {minimo})")
            if p.faixa in atipicas and p.chave.startswith("PF:"):
                motivos.append(f"tem idade atípica para sócio de contratada ({faixas.get(p.faixa, p.faixa)})")
            if not motivos:
                continue
            ligados = [c for c in self.contratos if c.pj and c.basico in raizes]
            ref = max(ligados, key=lambda x: x.data)
            ref_pasta = [c for c in ligados if da_pasta(c.orgao)]
            if ref_pasta:
                ref = max(ref_pasta, key=lambda x: x.data)
            empresas = sorted({f"{self._nome(c.ni)} ({c.ni})" for c in ligados})
            self.add("socio_laranja", ref, f"laranja-{chave}",
                     f"{p.nome} ({p.qualificacao or 'sócio'}, {p.doc or 'documento não publicado'}) "
                     + " e ".join(motivos) + ": " + ", ".join(empresas[:12]),
                     valor=sum(c.valor for c in ligados), contratos=[c.id for c in ligados],
                     gravidade="alta" if len(raizes) >= minimo else "media", empresas=len(raizes))

    def _nome(self, cnpj: str) -> str:
        e = self.empresas.get(cnpj)
        if e and e.get("razao"):
            return e["razao"]
        c = self._contrato_de(cnpj)
        return c.fornecedor if c else cnpj

    def _contrato_de(self, cnpj: str) -> Contrato | None:
        return next((c for c in self.contratos if c.ni == cnpj), None)


def _cobertura(con, out: ConferenciasEmpresas, contratos: list[Contrato], empresas, socios, sancoes, servidores,
               ausentes) -> None:
    pj = [c for c in contratos if c.pj]
    cnpjs = {c.ni for c in pj}
    cob = out.cobertura
    cob["contratos"] = len(contratos)
    cob["contratos_pessoa_juridica"] = len(pj)
    cob["contratos_pessoa_fisica"] = len(contratos) - len(pj)
    cob["cnpjs"] = len(cnpjs)
    cob["cnpjs_com_cadastro"] = sum(1 for c in cnpjs if c in empresas)
    cob["cnpjs_com_qsa"] = sum(1 for c in cnpjs if socios.get(c))
    cob["cnpjs_nao_encontrados"] = sum(1 for c in cnpjs if c in ausentes)
    fontes = Counter(f"{e.get('fonte')} ({e.get('data_base') or 'data da base não informada pela via'})"
                     for c, e in empresas.items() if c in cnpjs)
    cob["fontes"] = dict(fontes)
    cadastros = Counter(s.cadastro for s in sancoes)
    cob["sancoes"] = dict(cadastros)
    cob["folha"] = len(servidores or [])
    lacunas = []
    sem = len(cnpjs) - cob["cnpjs_com_cadastro"] - cob["cnpjs_nao_encontrados"]
    if sem:
        lacunas.append(f"{sem} de {len(cnpjs)} CNPJs contratados sem o cadastro da Receita no banco")
    faltam = [c for c in CADASTROS_DE_SANCAO if not cadastros.get(c)]
    cob["sancoes_nao_conferidas"] = {c: _motivo_da_falta(con, c) for c in faltam}
    if faltam:
        lacunas.append("cadastros de sanções e impedimentos sem nenhuma linha no banco, portanto não conferidos "
                       "(ausência de dado, nunca atestado de empresa sem sanção): "
                       + "; ".join(f"{c} ({m})" for c, m in cob["sancoes_nao_conferidas"].items()))
    cob["lacunas"] = lacunas


CADASTROS_DE_SANCAO = ("CEIS", "CNEP", "CEPIM", "TCU-INIDONEOS")
_TRECHO_DA_URL = {"CEIS": "ceis", "CNEP": "cnep", "CEPIM": "cepim", "TCU-INIDONEOS": "inidone"}


def _motivo_da_falta(con, cadastro: str) -> str:
    """Por que o cadastro não tem linhas: a última coleta que falhou para ele, se houver."""
    try:
        linha = con.execute("SELECT http, erro, quando FROM coletas WHERE ok = 0 AND lower(url) LIKE ? "
                            "ORDER BY quando DESC LIMIT 1", (f"%{_TRECHO_DA_URL[cadastro]}%",)).fetchone()
    except sqlite3.Error:
        linha = None
    if not linha:
        return "nenhuma coleta registrada no banco"
    http, erro, quando = linha
    causa = erro or (f"HTTP {http}" if http else "falha sem detalhe")
    return f"a última coleta falhou em {str(quando)[:10]}: {causa}"


# --- Fichas --------------------------------------------------------------------------------------

_BASE = {
    "situacao_irregular": (Familia.PRC, "Lei 14.133/2021, arts. 62, III e 68, I e II; art. 92, XVI",
                           "A contratada mantém, na assinatura e durante todo o contrato, a regularidade "
                           "cadastral e fiscal exigida na habilitação (CNPJ ativo).",
                           "Pedir a habilitação fiscal do processo e o comprovante de situação cadastral na data."),
    "pouco_tempo": (Familia.PRC, "Lei 14.133/2021, arts. 67, II e 69, I",
                    "A contratada comprova capacidade técnica (atestados) e econômica (balanço) compatíveis com "
                    "o objeto, o que pressupõe atividade anterior.",
                    "Pedir os atestados de capacidade técnica e o balanço apresentados na habilitação."),
    "perto_da_licitacao": (Familia.PRC, "Lei 14.133/2021, art. 5º; Código Penal, art. 337-F",
                           "A competição se dá entre empresas que já atuavam no ramo, não entre empresas criadas "
                           "para a disputa.",
                           "Pedir a lista de participantes, as propostas e a habilitação da compra."),
    "sem_experiencia": (Familia.PRC, "Lei 14.133/2021, art. 67, II e § 1º",
                        "A contratada demonstra experiência anterior em objeto de características semelhantes.",
                        "Pedir os atestados de capacidade técnica aceitos e conferir quem os emitiu."),
    "cnae_incompativel": (Familia.PRC, "Lei 14.133/2021, art. 66; Lei 10.406/2002, art. 997, II",
                          "O objeto social e as atividades registradas da contratada abrangem o objeto do contrato.",
                          "Pedir o contrato social e a habilitação jurídica apresentados na compra."),
    "cnae_recente": (Familia.PRC, "Lei 14.133/2021, art. 66",
                     "A atividade compatível com o objeto já fazia parte do cadastro da contratada antes da compra.",
                     "Pedir as alterações do contrato social e as datas de registro na Junta Comercial."),
    "capital_baixo": (Familia.PRC, "Lei 14.133/2021, art. 69, § 4º",
                      "A contratada tem lastro econômico compatível com o contrato (capital ou patrimônio de até "
                      "10% do valor, quando o edital exige).",
                      "Pedir o balanço e a qualificação econômico-financeira exigida no edital."),
    "porte_acima": (Familia.PRC, "Lei Complementar 123/2006, arts. 3º e 18-A; Lei 14.133/2021, art. 4º, § 2º",
                    "O tratamento de MEI, microempresa ou Simples só vale até o teto anual de receita; acima "
                    "dele a empresa sai do regime e perde o benefício nas licitações.",
                    "Pedir as declarações de enquadramento entregues e comunicar a Receita Federal."),
    "sancionada": (Familia.PRC, "Lei 14.133/2021, arts. 14, III e 156; Lei 12.846/2013; Lei 8.443/1992, art. 46",
                   "Empresa ou pessoa impedida, suspensa ou declarada inidônea não contrata com a Administração "
                   "enquanto a sanção vigorar.",
                   "Pedir a consulta ao CEIS, CNEP, CEPIM e à lista do TCU feita na habilitação e as providências "
                   "sobre o contrato."),
    "socio_sancionado": (Familia.PRC, "Lei 14.133/2021, art. 14, III e § 1º",
                         "O impedimento alcança quem atua em substituição ao sancionado para burlar a sanção, "
                         "inclusive por sociedade de que ele faça parte.",
                         "Pedir o quadro societário apresentado na compra e a consulta de sanções dos sócios."),
    "socio_servidor": (Familia.VIN, "Lei 14.133/2021, arts. 9º, § 1º e 14, IV; Lei Orgânica de Goiânia, art. 29",
                       "Servidor ou dirigente do órgão contratante não participa, direta ou indiretamente, da "
                       "licitação ou da execução do contrato.",
                       "Pedir a ficha funcional do servidor e o processo da compra, com a declaração de "
                       "inexistência de impedimento."),
    "folha_ausente": (Familia.VIN, "Lei 12.527/2011, art. 8º; Lei Complementar 131/2009; Lei 14.133/2021, art. 14, IV",
                      "A folha nominal (nome, CPF parcial, cargo e lotação) fica publicada para que o cruzamento "
                      "com os sócios das contratadas seja possível.",
                      "Pedir por LAI a relação nominal dos servidores e agentes públicos do Município, com cargo, "
                      "lotação e datas de entrada e saída."),
    "vinculo_mesma_compra": (Familia.PRC, "Lei 14.133/2021, arts. 5º e 14; Lei 12.846/2013, art. 5º, IV, a; "
                                          "Código Penal, art. 337-F",
                             "Empresas que disputam a mesma compra são independentes entre si; sócio, endereço ou "
                             "contato em comum desfaz a competição.",
                             "Pedir as propostas, os documentos de habilitação e os registros de envio das "
                             "empresas ligadas."),
    "rodizio": (Familia.PRC, "Lei 14.133/2021, art. 5º; Lei 12.846/2013, art. 5º, IV, a",
                "Os contratos do mesmo órgão e ramo vão a empresas independentes, sem revezamento entre empresas "
                "do mesmo grupo.",
                "Pedir as compras que deram origem aos contratos e a lista de participantes de cada uma."),
    "socio_laranja": (Familia.PRC, "Lei 12.846/2013, art. 5º, III; Lei 14.133/2021, art. 14, § 1º",
                      "O quadro societário das contratadas revela quem de fato contrata com o Município, sem "
                      "interpostas pessoas.",
                      "Pedir os contratos sociais das empresas e as declarações de beneficiário final."),
    "endereco_residencial": (Familia.PRC, "Lei 14.133/2021, art. 67, III",
                             "A contratada tem instalações compatíveis com a execução do objeto.",
                             "Pedir a vistoria da sede ou a declaração de instalações apresentada na habilitação."),
    "endereco_comum": (Familia.PRC, "Lei 14.133/2021, art. 5º; Lei 12.846/2013, art. 5º, III",
                       "Contratadas diferentes têm sedes próprias; a mesma sede para várias é sinal de grupo "
                       "econômico ou de empresas de fachada.",
                       "Pedir a vistoria das sedes e os contratos sociais das empresas no mesmo endereço."),
    "razao_alterada": (Familia.PRC, "Lei 14.133/2021, art. 14, III e § 1º",
                       "A identificação da contratada é a mesma no contrato e na Receita, e a troca de nome não "
                       "esconde o histórico (inclusive sanções) da empresa.",
                       "Pedir as alterações contratuais e conferir as sanções com a razão anterior."),
    "cnpj_nao_encontrado": (Familia.PRC, "Lei 14.133/2021, arts. 62 e 68, I",
                            "O contrato é assinado com pessoa jurídica inscrita e ativa no CNPJ.",
                            "Pedir a documentação de habilitação e conferir o CNPJ do contrato publicado no PNCP."),
}
CODIGOS = {
    "situacao_irregular": "EMP-SIT01", "pouco_tempo": "EMP-TEMPO01", "perto_da_licitacao": "EMP-TEMPO02",
    "sem_experiencia": "EMP-EXP01", "cnae_incompativel": "EMP-CNAE01", "cnae_recente": "EMP-CNAE02",
    "capital_baixo": "EMP-CAP01", "porte_acima": "EMP-PORTE01", "sancionada": "EMP-IMP01",
    "socio_sancionado": "EMP-IMP02", "socio_servidor": "EMP-SERV01", "folha_ausente": "EMP-SERV00",
    "vinculo_mesma_compra": "EMP-LIG01", "rodizio": "EMP-LIG02", "socio_laranja": "EMP-LIG03",
    "endereco_residencial": "EMP-END01", "endereco_comum": "EMP-END02", "razao_alterada": "EMP-RAZ01",
    "cnpj_nao_encontrado": "EMP-SIT00",
}


def ficha(a: Achado, competencia: str | None = None) -> Ficha:
    familia, norma, como_deveria, providencia = _BASE[a.tipo]
    ausente = a.tipo == "folha_ausente"
    return emitir(
        codigo=f"{CODIGOS[a.tipo]}-{a.chave}"[:120], familia=familia,
        titulo=f"{TITULOS[a.tipo]}: {a.orgao.title()}" if a.orgao else TITULOS[a.tipo],
        gravidade=a.dados.get("gravidade", "media"), como_deveria=como_deveria, norma=norma,
        como_esta=a.descricao[:1].upper() + a.descricao[1:] + ". " + AVISO,
        niveis=[Nivel.F] if ausente else [Nivel.C], documento_faltante=ausente,
        por_coincidencia_de_nome=bool(a.dados.get("por_nome")) or a.tipo in ("socio_servidor", "socio_laranja"),
        providencia=providencia, competencia=competencia)


# --- Saídas: seção do parecer e página do site ----------------------------------------------------

def secao_parecer(conf: ConferenciasEmpresas, competencia: str) -> str:
    """O trecho do parecer: quantos alertas de cada conferência na pasta, nos 12 meses até a competência."""
    lista = conf.da_competencia(competencia)
    cont = Counter(a.tipo for a in lista)
    linhas = "".join(f"<tr><td>{escape(TITULOS[t])}</td><td class=\"num\">{cont.get(t, 0)}</td></tr>"
                     for t in TITULOS)
    cob = conf.cobertura
    s = ['<p>As empresas contratadas pelos órgãos da pasta, conferidas no cadastro da Receita Federal, no quadro '
         "societário e nos cadastros de sancionados (Lei 14.133/2021, arts. 14, 66 a 69; LC 123/2006). Cada "
         "alerta é indício para apuração, não acusação. A lista completa, contrato a contrato, está na página "
         '<a href="empresas.html">Empresas contratadas</a>.</p>',
         '<div class="tabela"><table><tr><th>Conferência</th><th>Alertas da pasta</th></tr>' + linhas
         + "</table></div>"]
    if cob.get("cnpjs") is not None:
        s.append(f'<p class="omitido">Base: {cob.get("cnpjs", 0)} CNPJs contratados, {cob.get("cnpjs_com_cadastro", 0)} '
                 f'com o cadastro da Receita e {cob.get("cnpjs_com_qsa", 0)} com o quadro societário no banco; '
                 f'{cob.get("contratos_pessoa_fisica", 0)} contratos com pessoa física.</p>')
    for lacuna in cob.get("lacunas") or []:
        s.append(f'<p class="omitido">Falta no banco: {escape(lacuna)}.</p>')
    return "".join(s)


CSS_EXTRA = """
details.contrato{background:var(--cartao);border:1px solid var(--linha);border-radius:10px;padding:8px 14px;margin:8px 0}
details.contrato summary{cursor:pointer}
details.contrato.alerta{border-left:6px solid var(--alta)}
.pequeno{font-size:13px;color:var(--apagado)}
dl.campos{display:grid;grid-template-columns:170px 1fr;gap:2px 12px;margin:8px 0}
dl.campos dt{color:var(--apagado);font-size:14px}dl.campos dd{margin:0}
.num{text-align:right;white-space:nowrap}
"""


def _campos(pares: list[tuple[str, str]]) -> str:
    return '<dl class="campos">' + "".join(f"<dt>{escape(k)}</dt><dd>{escape(str(v))}</dd>" for k, v in pares
                                           if v not in (None, "")) + "</dl>"


def pagina(conf: ConferenciasEmpresas, *, hoje: date | None = None) -> str:
    """A página das empresas contratadas: cada contrato, a empresa, o QSA e os alertas."""
    from ..parecer.html import CSS
    hoje = hoje or date.today()
    por_contrato = conf.por_contrato()
    cob = conf.cobertura
    tot, pasta = conf.por_tipo(), conf.por_tipo(True)
    s = [f"<h1>Empresas contratadas pelo Município</h1>",
         f'<p class="sub">Onisciente · cruzamento dos contratos do PNCP com a Receita Federal e os cadastros de '
         f"sancionados · gerado em {hoje:%d/%m/%Y}</p>",
         f'<p class="frase">{escape(AVISO)}</p>',
         "<h2>Resumo</h2>",
         '<div class="tabela"><table><tr><th>Conferência</th><th>Município</th><th>Pasta</th></tr>'
         + "".join(f"<tr><td>{escape(TITULOS[t])}</td><td class=\"num\">{tot[t]}</td><td class=\"num\">{pasta[t]}</td></tr>"
                   for t in TITULOS) + "</table></div>",
         f"<p>Base: {cob.get('contratos', 0)} contratos ({cob.get('contratos_pessoa_juridica', 0)} com pessoa jurídica, "
         f"{cob.get('contratos_pessoa_fisica', 0)} com pessoa física); {cob.get('cnpjs', 0)} CNPJs, "
         f"{cob.get('cnpjs_com_cadastro', 0)} com cadastro da Receita, {cob.get('cnpjs_com_qsa', 0)} com quadro "
         f"societário e {cob.get('cnpjs_nao_encontrados', 0)} que não constam na base; folha nominal no banco: "
         f"{cob.get('folha', 0)} registros.</p>"]
    if cob.get("fontes"):
        s.append("<p>Fontes do cadastro (selo de fonte): " + "; ".join(
            f"{escape(k)}: {v} CNPJs" for k, v in sorted(cob["fontes"].items())) + ".</p>")
    if cob.get("sancoes"):
        s.append("<p>Sanções e impedimentos no banco: " + "; ".join(
            f"{escape(k)}: {v}" for k, v in sorted(cob["sancoes"].items())) + ".</p>")
    for lacuna in cob.get("lacunas") or []:
        s.append(f'<p class="omitido"><span class="selo s-vermelho"></span>Falta no banco: {escape(lacuna)}.</p>')
    s.append("<h2>Limiares usados</h2><p>Escolhidos do lado restritivo, para pegar qualquer desconformidade; "
             "vêm de config/limiares_empresas.yml.</p>")
    s.append('<div class="tabela"><table><tr><th>Limiar</th><th>Valor</th><th>Justificativa e base</th></tr>' + "".join(
        f"<tr><td>{escape(n.replace('_', ' '))}</td><td class=\"num\">{escape(str(v['valor']))}</td>"
        f"<td>{escape(v['justificativa'])} <span class=\"pequeno\">Base: {escape(v['base'])}</span></td></tr>"
        for n, v in (conf.limiares.get("limiares") or {}).items()) + "</table></div>")
    gerais = [a for a in conf.achados if not a.dados.get("contratos")]
    if gerais:
        s.append("<h2>Alertas gerais</h2>")
        s.extend(f"<p><strong>{escape(TITULOS[a.tipo])}.</strong> {escape(a.descricao[:1].upper() + a.descricao[1:])}."
                 f"</p>" for a in gerais)
    s.append("<h2>Contrato a contrato</h2><p>Os contratos com alerta vêm primeiro, do maior valor para o menor.</p>")
    ordem = sorted(conf.contratos, key=lambda c: (0 if por_contrato.get(c.id) else 1, -c.valor, c.id))
    for c in ordem:
        alertas = por_contrato.get(c.id, [])
        e = conf.empresas.get(c.ni)
        resumo = (f"{escape(c.id)} · {escape(c.fornecedor)} · {_moeda(c.valor)} · "
                  + (f"<strong>{len(alertas)} alerta(s)</strong>" if alertas else "sem alerta"))
        corpo = [_campos([("Órgão", c.orgao), ("Assinatura", _data_br(c.data)), ("Objeto", c.objeto[:400]),
                          ("Ramo", c.ramo or ""), ("Compra", c.compra_id or ""), ("Processo", c.processo or ""),
                          ("Fornecedor", f"{c.fornecedor} ({c.ni})")])]
        if not c.pj:
            corpo.append('<p class="pequeno">Pessoa física: o cadastro de CNPJ não se aplica; conferidas as sanções '
                         "e a folha.</p>")
        elif e is None:
            corpo.append('<p class="pequeno"><span class="selo s-vermelho"></span>Cadastro da Receita ainda não '
                         "coletado para este CNPJ.</p>")
        else:
            corpo.append(_campos([
                ("Razão social", e.get("razao")), ("Situação", f"{e.get('situacao')} desde {_data_br(e.get('data_situacao'))}"),
                ("Abertura", _data_br(e.get("data_abertura"))), ("Natureza", e.get("natureza")),
                ("Porte", e.get("porte")), ("Capital social", _moeda(float(e["capital_social"]))
                                             if e.get("capital_social") is not None else ""),
                ("CNAE principal", e.get("cnae_principal")), ("CNAEs secundários", e.get("cnaes_secundarios")),
                ("Simples / MEI", f"Simples {e.get('simples') or '-'}, MEI {e.get('mei') or '-'}"),
                ("Endereço", e.get("endereco")), ("Telefone", e.get("telefone")), ("Correio", e.get("email")),
                ("Selo de fonte", f"{e.get('fonte')}; base {e.get('data_base') or 'não informada pela via'}; "
                                  f"consultado em {_data_br(e.get('consultado_em'))}")]))
            qsa = conf.socios.get(c.ni) or []
            if qsa:
                corpo.append('<div class="tabela"><table><tr><th>Sócio ou administrador</th><th>Documento</th>'
                             "<th>Qualificação</th><th>Entrada</th><th>Faixa etária</th></tr>" + "".join(
                                 f"<tr><td>{escape(q.get('nome') or '')}</td><td>{escape(q.get('cpf_cnpj') or '')}</td>"
                                 f"<td>{escape(q.get('qualificacao') or '')}</td><td>{_data_br(q.get('data_entrada'))}</td>"
                                 f"<td>{escape(rf.FAIXAS_ETARIAS.get(str(q.get('faixa_etaria') or ''), ''))}</td></tr>"
                                 for q in qsa) + "</table></div>")
            else:
                corpo.append('<p class="pequeno">Quadro societário vazio na Receita (empresário individual ou MEI) '
                             "ou não coletado.</p>")
        if conf.cobertura.get("sancoes_nao_conferidas"):
            corpo.append('<p class="pequeno"><span class="selo s-vermelho"></span>Sanções e impedimentos não '
                         "conferidos em " + escape(", ".join(conf.cobertura["sancoes_nao_conferidas"]))
                         + ": ausência de dado no banco, não atestado de empresa sem sanção.</p>")
        if alertas:
            corpo.append("<ul>" + "".join(
                f"<li><strong>{escape(TITULOS[a.tipo])}</strong> ({escape(a.dados.get('gravidade', 'media'))}): "
                f"{escape(a.descricao)}.</li>" for a in alertas) + "</ul>")
        s.append(f'<details class="contrato{" alerta" if alertas else ""}"><summary>{resumo}</summary>'
                 + "".join(corpo) + "</details>")
    return ("<!doctype html><html lang=\"pt-BR\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>Empresas contratadas</title><style>{CSS}{CSS_EXTRA}</style></head><body><main>"
            + "".join(s) + "</main></body></html>\n")


def gravar_pagina(conf: ConferenciasEmpresas, destino: Path, *, hoje: date | None = None) -> Path:
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(pagina(conf, hoje=hoje), encoding="utf-8")
    return destino


def cmd(args) -> int:
    """``python -m onisciente empresas``: confere o banco e escreve a página das empresas, sem rede."""
    banco = Path(args.banco) if getattr(args, "banco", None) else RAIZ / "dados" / "onisciente" / "historico.db"
    if not banco.exists():
        print("Banco histórico não encontrado; rode `python -m onisciente historico`.")
        return 1
    conf = conferir(banco)
    destino = Path(args.saida) if getattr(args, "saida", None) else RAIZ / "docs" / "onisciente" / "empresas.html"
    gravar_pagina(conf, destino)
    cont = {t: n for t, n in conf.por_tipo().items() if n}
    print(f"{len(conf.contratos)} contratos, {conf.cobertura.get('cnpjs', 0)} CNPJs "
          f"({conf.cobertura.get('cnpjs_com_cadastro', 0)} com cadastro); alertas: "
          + (", ".join(f"{TITULOS[t]}: {n}" for t, n in cont.items()) or "nenhum"))
    for lacuna in conf.cobertura.get("lacunas") or []:
        print("FALTA:", lacuna)
    print("->", destino)
    return 0
