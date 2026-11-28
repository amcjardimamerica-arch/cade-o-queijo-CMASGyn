"""As entradas das telas, escritas a partir do que as outras frentes já deixam no repositório e no banco.

    python -m onisciente telas            # escreve as entradas e depois gera as páginas

Quatro arquivos em ``relatorios/onisciente/entradas/``, no formato da seção 11 do estudo de UX
(``docs/onisciente/ux/estudo_ux.md``), sem rede:

* ``selo_transparencia.json``: a auditoria do selo (``relatorios/onisciente/selo/auditoria.json``, gerada por
  ``python -m onisciente selo``), com as duas leituras (oficial e restritiva), cada uma comprovada e no teto, e
  as obrigações F1 a F5 do Fundo e C1 a C4 do Conselho;
* ``empresas.json``: ``onisciente.conferencias.empresas.conferir``, com a cobertura (inclusive os cadastros de
  sanção não conferidos) e os alertas por CNPJ. Nunca CPF;
* ``execucao.json``: os eventos da execução (``despesa_eventos``, motor ``execucao_goiania``), empenho a empenho;
* ``federais.json``: ``onisciente.conferencias.federais.conferir`` e os repasses (FNS, FNDE, FNAS, Transferegov).

Todo arquivo traz ``situacao``: ``dado`` quando há o que mostrar e ``coleta_nao_feita`` quando a coleta do
próprio sistema ainda não trouxe nada. A tela mostra a segunda em cinza (falha do sistema), nunca em roxo,
porque a falha do sistema não é imputada ao Município.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict
from datetime import date
from pathlib import Path

from .. import partes as _partes
from .. import RAIZ
from .base import documento_publico, sem_travessao

ENTRADAS = RAIZ / "relatorios" / "onisciente" / "entradas"
AUDITORIA_DO_SELO = RAIZ / "relatorios" / "onisciente" / "selo" / "auditoria.json"
FMAS = "01393989000103"
DADO, COLETA_NAO_FEITA = "dado", "coleta_nao_feita"

_CPF_SOLTO = re.compile(r"(?<![\dA-Za-z])\d{11}(?![\dA-Za-z])")
_CPF_FORMATADO = re.compile(r"\d{3}\.\d{3}\.\d{3}-\d{2}")
_URL = re.compile(r"https?://[^\s,;)]+")


def texto(valor, limite: int = 600) -> str:
    """Texto pronto para a tela: sem CPF (solto ou formatado), sem travessão, aparado."""
    t = _CPF_FORMATADO.sub("CPF omitido", str(valor or ""))
    t = _CPF_SOLTO.sub("CPF omitido", t)
    t = sem_travessao(re.sub(r"\s+", " ", t).strip())
    return t if len(t) <= limite else t[: limite - 1].rstrip() + "…"


def _url(texto_fonte) -> str:
    m = _URL.search(str(texto_fonte or ""))
    return m.group(0).rstrip(".") if m else ""


def _tabela(con: sqlite3.Connection, nome: str) -> bool:
    return _partes.tem_tabela(con, nome)


def _linhas(con: sqlite3.Connection, sql: str, args: tuple = ()) -> list[dict]:
    cur = con.execute(sql, args)
    nomes = [c[0] for c in cur.description]
    return [dict(zip(nomes, r)) for r in cur]


def _ultima_coleta(con: sqlite3.Connection, motores: tuple[str, ...]) -> dict | None:
    if not _tabela(con, "coletas"):
        return None
    marcas = ",".join("?" for _ in motores)
    linhas = _linhas(con, f"SELECT motor, ok, quando, erro FROM coletas WHERE motor IN ({marcas}) "
                          "ORDER BY quando DESC LIMIT 1", motores)
    return linhas[0] if linhas else None


def _leitura(con: sqlite3.Connection, motor: str, contem: str) -> tuple[str, str, str]:
    """(endereço, data, impressão digital) da última leitura bem-sucedida de um motor."""
    if not _tabela(con, "coletas"):
        return "", "", ""
    cols = {c[1] for c in con.execute("PRAGMA table_info(coletas)")}
    sha = "sha256" if "sha256" in cols else "''"
    linha = con.execute(f"SELECT url, quando, {sha} FROM coletas WHERE ok = 1 AND motor = ? AND alvo LIKE ? "
                        "ORDER BY quando DESC LIMIT 1", (motor, f"%{contem}%")).fetchone()
    return (linha[0] or "", str(linha[1] or "")[:10], linha[2] or "") if linha else ("", "", "")


# =============================================================================================
# Selo de transparência
# =============================================================================================

_AUDITADO = {"atendido": "cumpre", "não atendido": "falha", "não verificável": "sem_dado"}
_ORGAOS = {"FMAS": ("Fundo Municipal de Assistência Social", FMAS),
           "CMAS": ("Conselho Municipal de Assistência Social", "")}


def selo(auditoria: Path = AUDITORIA_DO_SELO) -> dict:
    """A auditoria do selo no formato da tela."""
    if not Path(auditoria).is_file():
        return {"situacao": COLETA_NAO_FEITA, "programa": "Programa Nacional de Transparência Pública (PNTP)",
                "motivo": "a auditoria do selo ainda não foi gerada (python -m onisciente selo)", "criterios": [],
                "por_orgao": []}
    a = json.loads(Path(auditoria).read_text(encoding="utf-8"))
    dec = a.get("declarado") or {}
    notas = a.get("notas") or {}
    leituras = []
    for chave in ("oficial/comprovada", "oficial/teto", "restritiva/comprovada", "restritiva/teto"):
        n = notas.get(chave)
        if n:
            leituras.append({"leitura": n.get("leitura"), "modo": n.get("modo"), "indice": n.get("indice"),
                             "nivel": n.get("nivel"), "selo": bool(n.get("selo")),
                             "essenciais_ok": bool(n.get("essenciais_ok")),
                             "essenciais_em_falta": list(n.get("essenciais_em_falta") or [])})
    oficial = notas.get("oficial/comprovada") or {}
    criterios = []
    for c in a.get("criterios") or []:
        sit = c.get("situacao") or {}
        provas = c.get("provas") or []
        url = next((u for u in (_url(p.get("fonte")) for p in provas) if u), "")
        nota_oficial = "; ".join((c.get("notas") or {}).get("oficial") or [])
        criterios.append({
            "id": c.get("id"), "dimensao": c.get("dimensao"), "criterio": texto(c.get("texto"), 200),
            "peso": c.get("classe"), "base_legal": texto(c.get("base_legal"), 200), "declarado": None,
            "auditado": _AUDITADO.get(sit.get("oficial"), "sem_dado"),
            "auditado_restritiva": _AUDITADO.get(sit.get("restritiva"), "sem_dado"),
            "prova_url": url, "lido_em": a.get("hoje", ""),
            "nota": texto(provas[0].get("descricao") if provas else nota_oficial, 300),
            "provas": [{"descricao": texto(p.get("descricao"), 300), "fonte": texto(p.get("fonte"), 200),
                        "url": _url(p.get("fonte")), "leituras": p.get("leituras"), "nivel": p.get("nivel")}
                       for p in provas[:6]],
        })
    por_orgao: dict[str, dict] = {}
    for f in a.get("fundos") or []:
        sigla = f.get("orgao") or ""
        nome, cnpj = _ORGAOS.get(sigla, (sigla, ""))
        o = por_orgao.setdefault(sigla, {"sigla": sigla, "orgao": nome, "cnpj": cnpj, "obrigacoes": []})
        o["obrigacoes"].append({"id": f.get("id"), "texto": texto(f.get("texto"), 300),
                                "base": texto(f.get("base"), 200), "pntp": texto(f.get("pntp"), 120),
                                "estado": f.get("estado"), "alerta": bool(f.get("alerta")),
                                "valor_em_jogo": f.get("valor_em_jogo") or 0.0,
                                "provas": [texto(p, 300) for p in (f.get("provas") or [])[:8]]})
    for o in por_orgao.values():
        total = len(o["obrigacoes"])
        cumpridas = sum(1 for x in o["obrigacoes"] if not x["alerta"])
        o["nota"] = round(100.0 * cumpridas / total, 1) if total else None
        o["nivel"] = f"{cumpridas} de {total} obrigações cumpridas"
        o["nota_texto"] = ("Nenhuma obrigação de transparência comprovada com as provas lidas." if not cumpridas
                           else f"{total - cumpridas} obrigação(ões) em falta.")
    fontes = [{"titulo": texto(x.get("titulo"), 200), "url": x.get("url", ""), "lida_em": x.get("lida_em", "")}
              for x in a.get("fontes") or []]
    return {
        "situacao": DADO,
        "programa": "Programa Nacional de Transparência Pública (PNTP)",
        "ciclo": str(a.get("ciclo") or ""),
        "hoje": a.get("hoje", ""),
        "declarado": {"nivel": dec.get("selo"), "ciclo": str(dec.get("ciclo") or ""), "nota": None,
                      "nota_texto": dec.get("indice") or "", "url": dec.get("url", ""),
                      "lido_em": "", "fonte": texto(dec.get("fonte"), 200),
                      "ciclo_seguinte": texto(dec.get("ciclo_2026"), 400)},
        "auditado": {"nivel": oficial.get("nivel"), "nota": oficial.get("indice")},
        "leituras": leituras,
        "veredito": {"oficial": (a.get("veredito") or {}).get("oficial"),
                     "restritiva": (a.get("veredito") or {}).get("restritiva"),
                     "frase": texto((a.get("veredito") or {}).get("frase"), 600)},
        "radar": {"lido": bool((a.get("radar") or {}).get("lido")), "motivo": texto((a.get("radar") or {}).get("motivo"), 300)},
        "criterios": criterios,
        "por_orgao": list(por_orgao.values()),
        "pendencias": [texto(p, 500) for p in a.get("pendencias") or []],
        "fontes": fontes,
    }


# =============================================================================================
# Empresas
# =============================================================================================

def _cnpj(valor) -> str:
    """Só CNPJ (14 posições, numérico ou alfanumérico); CPF e o resto ficam de fora."""
    v = re.sub(r"[^0-9A-Za-z]", "", str(valor or "")).upper()
    return v if len(v) == 14 else ""


def empresas(banco: Path | sqlite3.Connection, *, hoje: date | None = None) -> dict:
    from ..conferencias import empresas as E
    r = E.conferir(banco, hoje=hoje)
    cob = dict(r.cobertura)
    nomes: dict[str, str] = {}
    contratos: dict[str, int] = defaultdict(int)
    for c in r.contratos:
        doc = _cnpj(c.ni) if getattr(c, "pj", False) else ""
        if doc:
            nomes.setdefault(doc, texto(getattr(c, "fornecedor", "") or "", 160))
            contratos[doc] += 1
    alertas: dict[str, list[dict]] = defaultdict(list)
    gerais = []
    for a in r.achados:
        doc = _cnpj(a.dados.get("cnpj"))
        item = {"tipo": a.tipo, "titulo": E.TITULOS.get(a.tipo, a.tipo) if hasattr(E, "TITULOS") else a.tipo,
                "gravidade": a.dados.get("gravidade", "media"), "texto": texto(a.descricao, 500), "mes": a.mes,
                "contratos": [str(x) for x in a.dados.get("contratos", [])][:6], "orgao": a.orgao_cnpj,
                "valor": a.valor or 0.0}
        if doc:
            alertas[doc].append(item)
        else:
            gerais.append(item)
    cnpjs = set(nomes) | set(alertas) | {_cnpj(c) for c in r.empresas}
    cnpjs.discard("")
    lista = []
    for cnpj in sorted(cnpjs):
        e = r.empresas.get(cnpj) or {}
        socios = [{"nome": texto(s.get("nome"), 120), "qualificacao": texto(s.get("qualificacao"), 80),
                   "desde": s.get("data_entrada") or ""} for s in r.socios.get(cnpj, [])]
        lista.append({
            "cnpj": cnpj, "razao": texto(e.get("razao") or nomes.get(cnpj), 160),
            "abertura": e.get("data_abertura") or "", "situacao": e.get("situacao") or "",
            "capital": e.get("capital_social"), "cnae": texto(e.get("cnae_principal"), 160),
            "socios": socios, "sancoes": [], "contratos": contratos.get(cnpj, 0),
            "cadastro": bool(e), "alertas": alertas.get(cnpj, []),
            "url": "", "lido_em": e.get("consultado_em") or "", "fonte_cadastro": texto(e.get("fonte"), 120),
        })
    cob.pop("fontes", None)
    lacunas = [texto(x, 600) for x in cob.get("lacunas") or []]
    sancoes = {k: texto(v, 200) for k, v in (cob.get("sancoes_nao_conferidas") or {}).items()}
    tem = bool(lista)
    return {
        "situacao": DADO if tem else COLETA_NAO_FEITA,
        "motivo": "" if tem else "nenhum contrato do PNCP no banco para conferir",
        "cobertura": {**{k: v for k, v in cob.items() if isinstance(v, (int, float, bool))},
                      "sancoes_nao_conferidas": sancoes, "lacunas": lacunas,
                      "cadastro_coletado": cob.get("cnpjs_com_cadastro", 0) > 0},
        "por_tipo": r.por_tipo(),
        "empresas": lista,
        "alertas_gerais": gerais,
    }


# =============================================================================================
# Execução, empenho a empenho
# =============================================================================================

_ESTACAO = {"empenho": "empenho", "liquidacao": "liquidacao", "ordem_pagamento": "pagamento",
            "pagamento": "pagamento", "anulacao": "anulacao"}


def execucao(con: sqlite3.Connection) -> dict:
    coleta = _ultima_coleta(con, ("execucao_goiania",))
    if not _tabela(con, "despesa_eventos") or not con.execute("SELECT 1 FROM despesa_eventos LIMIT 1").fetchone():
        motivo = ("o motor execucao_goiania ainda não rodou na coleta histórica" if not coleta else
                  f"a última leitura do motor execucao_goiania ({coleta['quando']}) não trouxe eventos"
                  + (f": {texto(coleta.get('erro'), 200)}" if coleta.get("erro") else ""))
        return {"situacao": COLETA_NAO_FEITA, "motivo": motivo, "empenhos": []}
    por_empenho: dict[str, dict] = {}
    for ev in _linhas(con, "SELECT * FROM despesa_eventos ORDER BY data, empenho"):
        num = (ev.get("empenho") or "").strip()
        if not num:
            continue
        doc = re.sub(r"\D", "", str(ev.get("documento") or ""))
        pessoa_fisica = len(doc) == 11
        e = por_empenho.setdefault(num, {
            "numero": num, "data": ev.get("data") or "", "orgao_cnpj": "", "orgao": texto(ev.get("orgao"), 120),
            "credor": "Pessoa física" if pessoa_fisica else texto(ev.get("credor"), 160),
            "credor_cnpj": documento_publico(doc), "fonte": ev.get("fonte") or "", "funcao": ev.get("funcao") or "",
            "natureza": ev.get("elemento") or "", "valor": 0.0, "contrato": "", "eventos": [],
            "url": ev.get("url") or "", "lido_em": ev.get("coletado_em") or ""})
        estacao = _ESTACAO.get(ev.get("tipo") or "", ev.get("tipo") or "")
        valor = float(ev.get("valor") or 0)
        if estacao == "empenho":
            e["valor"] += valor
            e["data"] = min(filter(None, [e["data"], ev.get("data") or ""]), default="")
        e["eventos"].append({"estacao": estacao, "data": ev.get("data") or "", "valor": valor,
                             "documento": texto(ev.get("ordem") or ev.get("tipo"), 60), "url": ev.get("url") or "",
                             "lido_em": ev.get("coletado_em") or "", "sha256": ev.get("sha256") or ""})
    return {"situacao": DADO, "motivo": "", "empenhos": list(por_empenho.values())}


# =============================================================================================
# Transferências federais
# =============================================================================================

_MOTOR_DA_ORIGEM = {"FNS": "fns", "FNDE": "fnde", "Transferegov": "transferegov"}


def federais(con: sqlite3.Connection, *, hoje: date | None = None) -> dict:
    from ..conferencias import federais as F
    hoje = hoje or date.today()
    try:
        r = F.conferir(con, ate=hoje)
        conf = r.como_dict()
    except Exception as erro:  # noqa: BLE001
        conf = {"cobertura": {"problemas": {}}, "conferencias": [], "alertas": [], "ausencias": [],
                "erro": texto(erro, 200)}
    problemas = (conf.get("cobertura") or {}).get("problemas") or {}
    repasses: list[dict] = []
    if _tabela(con, "repasses_fns"):
        for x in _linhas(con, "SELECT mes, competencia, bloco, programa, valor_bruto, valor_liquido FROM repasses_fns"):
            repasses.append({"origem": "FNS", "mes": str(x.get("mes") or x.get("competencia") or "")[:7],
                             "programa": texto(" ".join(filter(None, [x.get("bloco"), x.get("programa")])), 200),
                             "valor": x.get("valor_liquido") if x.get("valor_liquido") is not None else x.get("valor_bruto"),
                             "fonte_destino": "1600", "url": "", "lido_em": ""})
    if _tabela(con, "liberacoes_fnde"):
        for x in _linhas(con, "SELECT mes, data, programa, valor FROM liberacoes_fnde"):
            repasses.append({"origem": "FNDE", "mes": str(x.get("mes") or x.get("data") or "")[:7],
                             "programa": texto(x.get("programa"), 200), "valor": x.get("valor"),
                             "fonte_destino": "", "url": "", "lido_em": ""})
    if _tabela(con, "repasses_fnas"):
        planilhas: dict = {}
        for x in _linhas(con, "SELECT competencia, bloco, programa, valor, planilha FROM repasses_fnas"):
            ano = x.get("planilha")
            if ano not in planilhas:
                planilhas[ano] = _leitura(con, "fnas", f"planilha {ano}")
            url, quando, sha = planilhas[ano]
            repasses.append({"origem": "FNAS", "mes": str(x.get("competencia") or "")[:7],
                             "programa": texto(x.get("programa") or x.get("bloco"), 200), "valor": x.get("valor"),
                             "fonte_destino": "1660", "url": url, "lido_em": quando, "sha256": sha,
                             "planilha": ano})
    emendas = []
    if _tabela(con, "transferegov_planos_especiais"):
        for x in _linhas(con, "SELECT codigo, ano, situacao, parlamentar, emenda, custeio, investimento, total "
                              "FROM transferegov_planos_especiais"):
            emendas.append({k: (texto(v, 160) if isinstance(v, str) else v) for k, v in x.items()})
    origens = {}
    for origem, motor in _MOTOR_DA_ORIGEM.items():
        n = sum(1 for x in repasses if x["origem"] == origem) if origem != "Transferegov" else len(emendas)
        origens[origem] = {"situacao": DADO if n else COLETA_NAO_FEITA, "linhas": n,
                           "motivo": "" if n else texto(problemas.get(motor) or "a coleta ainda não trouxe linhas", 300)}
    n_fnas = sum(1 for x in repasses if x["origem"] == "FNAS")
    origens["FNAS"] = {"situacao": DADO if n_fnas else COLETA_NAO_FEITA, "linhas": n_fnas,
                       "motivo": "" if n_fnas else "a planilha do FNAS ainda não foi lida"}
    repasses = [x for x in repasses if x["mes"] and x["valor"] is not None]
    repasses.sort(key=lambda x: (x["mes"], x["origem"], x["programa"]))
    return {
        "situacao": DADO if repasses or emendas else COLETA_NAO_FEITA,
        "motivo": "" if repasses or emendas else "nenhuma fonte federal tem linhas no banco",
        "origens": origens,
        "repasses": repasses,
        "emendas": emendas,
        "conferencias": [{"titulo": texto(c.get("titulo"), 200), "referencia": texto(c.get("referencia"), 200),
                          "norma": texto(c.get("norma"), 160), "selo": c.get("selo"), "divergencia": c.get("divergencia"),
                          "vias": [{"fonte": texto(v.get("fonte"), 160), "valor": v.get("valor")} for v in c.get("vias") or []]}
                         for c in conf.get("conferencias") or []],
        "alertas": [{k: (texto(v, 400) if isinstance(v, str) else v) for k, v in a.items()}
                    for a in conf.get("alertas") or []],
        "problemas": {k: texto(v, 300) for k, v in problemas.items()},
    }


# =============================================================================================
# Escrever
# =============================================================================================

def escrever(banco: Path, destino: Path = ENTRADAS, *, hoje: date | None = None,
             auditoria: Path = AUDITORIA_DO_SELO) -> dict[str, Path]:
    """Escreve as quatro entradas e devolve {nome: arquivo}."""
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    hoje = hoje or date.today()
    con = _partes.conectar_leitura(banco)
    try:
        conteudo = {
            "selo_transparencia": selo(auditoria),
            "empresas": empresas(con, hoje=hoje),
            "execucao": execucao(con),
            "federais": federais(con, hoje=hoje),
        }
    finally:
        con.close()
    out = {}
    for nome, dados in conteudo.items():
        dados = {"gerado_em": hoje.isoformat(), **dados}
        arq = destino / f"{nome}.json"
        arq.write_text(json.dumps(dados, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        out[nome] = arq
    return out
