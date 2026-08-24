"""Conciliação financeira — o rastro do dinheiro, do repasse à aplicação.

Rastreia-se em três eixos, que é como um vereador competente lê um orçamento:

  ORIGEM    de onde veio — União, Estado ou Município. Identifica-se pela fonte
            de recursos e pelos programas nominados (IGD, Piso, emenda, FEAS).

  DESTINO   para onde foi — classificação funcional-programática, no formato
            função.subfunção.programa.ação. A função identifica a política:
            08 é assistência social, 13 é cultura, 12 educação, 10 saúde.
            É por aí que a mesma regra serve a outra área.

  APLICAÇÃO como foi gasto — natureza da despesa. O elemento 43 e o 41 são os
            que interessam ao controle social: subvenção e contribuição a
            instituição privada sem fins lucrativos. É o dinheiro que sai do
            Fundo e entra na entidade.

O módulo não presume o significado dos códigos de fonte: coleta os que
efetivamente aparecem e os confronta com `config/fontes_recursos.yml`. Código
não mapeado vira pendência explícita, nunca palpite.
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))

import extracao
from util import CONFIG, RAIZ, agora, gravar_json, ler_json, log

SAIDA = RAIZ / "dados" / "financeiro.json"
MAPA_FONTES = CONFIG / "fontes_recursos.yml"

RE_DOTACAO = re.compile(r"\b(\d{2})\.(\d{3})\.(\d{4})\.(\d{4})\b")
RE_NATUREZA = re.compile(r"\b(3[13]|4[14])\.?(\d{2})\.?(\d{2})\.?(\d{2})\b")
RE_VALOR = re.compile(r"(?:R\$\s*)?\b(\d{1,3}(?:\.\d{3})+,\d{2})\b")
RE_FONTE_EXPL = re.compile(r"fonte\s*(?:de\s*recursos?)?\s*[:\-]?\s*(\d{3,4})", re.I)
RE_CODIGO_SOLTO = re.compile(r"\.(\d{8})\.(\d{3})\s+(\d{3})\s+(\d{4})\s+(\d{4})")

# Marcadores textuais de origem. Complementam o código de fonte, que nem
# sempre aparece.
MARCADORES = {
    "uniao": [r"(?-i:\bIGD[- ]?(?:M|PBF|SUAS)\b)", r"\bFNAS\b", r"Fundo Nacional",
              r"transfer[êe]ncia fundo a fundo", r"Piso (?:B[áa]sico|Fixo|Vari[áa]vel|de Alta)",
              r"emenda parlamentar (?:federal|de bancada|individual)",
              r"Minist[ée]rio do Desenvolvimento", r"\bMDS\b", r"Bolsa Fam[íi]lia",
              r"Cadastro [ÚU]nico", r"recursos? federa"],
    "estado": [r"\bFEAS\b", r"Fundo Estadual", r"Governo do Estado", r"Estado de Goi[áa]s",
               r"cofinanciamento estadual", r"recursos? estadua", r"\bSEDS\b"],
    "municipio": [r"recursos? pr[óo]prios", r"tesouro municipal", r"recursos? ordin[áa]rios",
                  r"contrapartida municipal", r"recursos? municipa"],
}
MARCADORES_RE = {k: re.compile("|".join(f"(?:{p})" for p in v), re.IGNORECASE)
                 for k, v in MARCADORES.items()}

MAPA_FONTES_PADRAO = {
    "descricao": ("Códigos de fonte de recursos observados no Diário Oficial. "
                  "Confirme cada um contra a LOA ou o Quadro de Detalhamento de "
                  "Despesas do exercício e preencha 'ente'. Enquanto estiver como "
                  "'a confirmar', o código não é classificado."),
    "codigos": {},
}


def _carregar_mapa() -> dict:
    if MAPA_FONTES.exists():
        return yaml.safe_load(MAPA_FONTES.read_text(encoding="utf-8")) or MAPA_FONTES_PADRAO
    return dict(MAPA_FONTES_PADRAO)


def _valor(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


def _origem(janela: str, codigo_fonte: str | None, mapa: dict) -> tuple[str, str]:
    """Devolve (ente, base_da_classificacao)."""
    if codigo_fonte:
        reg = mapa.get("codigos", {}).get(str(codigo_fonte))
        if reg and reg.get("ente"):
            return reg["ente"], f"fonte {codigo_fonte}"
    marcados = [k for k, r in MARCADORES_RE.items() if r.search(janela)]
    if len(marcados) == 1:
        return marcados[0], "marcador textual"
    if len(marcados) > 1:
        return "multiplo", "marcadores concorrentes: " + ", ".join(marcados)
    return "nao_classificado", f"fonte {codigo_fonte or 'ausente'} sem mapeamento"


def conciliar(dominio: dict) -> dict:
    funcao_alvo = dominio["orcamento"]["funcao"]
    naturezas = dominio.get("naturezas_relevantes", {})
    mapa = _carregar_mapa()

    trechos = extracao.carregar(dominio["id"])
    linhas: list[dict] = []
    codigos_vistos: dict[str, int] = defaultdict(int)

    for t in trechos:
        texto = t["texto"]
        for m in RE_DOTACAO.finditer(texto):
            if m.group(1) != funcao_alvo:
                continue
            janela = texto[max(0, m.start() - 260): m.end() + 360]
            v = RE_VALOR.search(texto[m.end(): m.end() + 220])
            nat = RE_NATUREZA.search(janela)
            fonte = None
            fe = RE_FONTE_EXPL.search(janela)
            if fe:
                fonte = fe.group(1)
            else:
                cs = RE_CODIGO_SOLTO.search(janela)
                if cs:
                    fonte = cs.group(4)      # o campo de quatro dígitos após a natureza
            if fonte:
                codigos_vistos[fonte] += 1
            ente, base = _origem(janela, fonte, mapa)
            natureza = "".join(nat.groups()) if nat else None
            linhas.append({
                "data": t["data"], "edicao": t["edicao"], "trecho_id": t["id"],
                "url": t["url_original"], "pagina": t["pagina_estimada"],
                "dotacao": m.group(0),
                "funcao": m.group(1), "subfuncao": m.group(2),
                "programa": m.group(3), "acao": m.group(4),
                "subfuncao_nome": dominio["orcamento"].get("subfuncoes", {}).get(m.group(2)),
                "natureza": natureza,
                "natureza_nome": naturezas.get(natureza or "", None),
                "fonte": fonte, "ente": ente, "base_classificacao": base,
                "valor": _valor(v.group(1)) if v else None,
                "rotulo": re.sub(r"\s+", " ", texto[m.end(): m.end() + 110]).strip(" |."),
                "para_entidade": bool(natureza and natureza[:4] in ("3350", "3450")),
            })

    # ---------------------------------------------------------- consolidação
    por_ente: dict[str, dict] = defaultdict(lambda: {"linhas": 0, "valor": 0.0})
    por_acao: dict[str, dict] = defaultdict(lambda: {"linhas": 0, "valor": 0.0, "rotulo": ""})
    por_natureza: dict[str, dict] = defaultdict(lambda: {"linhas": 0, "valor": 0.0})
    por_ano: dict[str, dict] = defaultdict(lambda: {"linhas": 0, "valor": 0.0})
    para_entidades = 0.0

    for l in linhas:
        v = l["valor"] or 0.0
        por_ente[l["ente"]]["linhas"] += 1
        por_ente[l["ente"]]["valor"] += v
        k = l["dotacao"]
        por_acao[k]["linhas"] += 1
        por_acao[k]["valor"] += v
        if not por_acao[k]["rotulo"] and l["rotulo"]:
            por_acao[k]["rotulo"] = l["rotulo"][:70]
        n = l["natureza"] or "não identificada"
        por_natureza[n]["linhas"] += 1
        por_natureza[n]["valor"] += v
        a = l["data"][:4]
        por_ano[a]["linhas"] += 1
        por_ano[a]["valor"] += v
        if l["para_entidade"]:
            para_entidades += v

    # códigos de fonte ainda não mapeados viram pendência explícita
    pendentes = {c: n for c, n in sorted(codigos_vistos.items(), key=lambda x: -x[1])
                 if not mapa.get("codigos", {}).get(c, {}).get("ente")}
    if pendentes:
        mapa.setdefault("codigos", {})
        for c in pendentes:
            mapa["codigos"].setdefault(c, {"ente": None, "nome": None,
                                           "observacoes": "a confirmar na LOA/QDD"})
        MAPA_FONTES.write_text(
            yaml.safe_dump(mapa, allow_unicode=True, sort_keys=False), encoding="utf-8")

    total = sum(l["valor"] or 0 for l in linhas)
    classificado = sum(v["valor"] for k, v in por_ente.items()
                       if k not in ("nao_classificado", "multiplo"))

    dados = {
        "dominio": dominio["id"], "funcao": funcao_alvo,
        "gerado_em": agora().isoformat(),
        "linhas": len(linhas),
        "valor_total": round(total, 2),
        "valor_classificado": round(classificado, 2),
        "indice_rastreabilidade": round(100 * classificado / max(total, 1), 2),
        "para_entidades_privadas": round(para_entidades, 2),
        "por_ente": {k: {"linhas": v["linhas"], "valor": round(v["valor"], 2)}
                     for k, v in sorted(por_ente.items(), key=lambda x: -x[1]["valor"])},
        "por_ano": {k: {"linhas": v["linhas"], "valor": round(v["valor"], 2)}
                    for k, v in sorted(por_ano.items())},
        "por_acao": {k: {"linhas": v["linhas"], "valor": round(v["valor"], 2),
                         "rotulo": v["rotulo"]}
                     for k, v in sorted(por_acao.items(), key=lambda x: -x[1]["valor"])[:40]},
        "por_natureza": {k: {"linhas": v["linhas"], "valor": round(v["valor"], 2),
                             "nome": naturezas.get(k)}
                         for k, v in sorted(por_natureza.items(), key=lambda x: -x[1]["valor"])},
        "fontes_pendentes": pendentes,
        "detalhe": sorted(linhas, key=lambda x: -(x["valor"] or 0))[:400],
    }
    gravar_json(SAIDA, dados)
    log.info("Financeiro: %d linha(s) na função %s | total R$ %.2f | "
             "rastreabilidade %.2f%% | %d código(s) de fonte a confirmar",
             len(linhas), funcao_alvo, total, dados["indice_rastreabilidade"],
             len(pendentes))
    return dados


def achados(d: dict) -> list[dict]:
    out = []
    if d.get("indice_rastreabilidade", 100) < 60:
        out.append({
            "regra": "FIN-03", "severidade": "media",
            "titulo": f"Rastreabilidade da origem dos recursos em {d['indice_rastreabilidade']}%",
            "detalhe": (
                f"De R$ {d['valor_total']:,.2f} em linhas orçamentárias da função "
                f"{d['funcao']} localizadas nas publicações, apenas "
                f"R$ {d['valor_classificado']:,.2f} permitem identificar o ente de "
                "origem. Os atos publicados não indicam a fonte de recursos de forma "
                "legível, o que impede conciliar o que a União e o Estado repassaram "
                "com o que o Município executou."
            ).replace(",", "@").replace(".", ",").replace("@", "."),
            "fundamento": "Lei 4.320/1964, artigos 6º e 13; Lei Complementar 101/2000, artigo 48",
            "saida_sugerida": "minuta_lai",
            "detectado_em": agora().isoformat(),
        })
    if d.get("fontes_pendentes"):
        out.append({
            "regra": "FIN-04", "severidade": "baixa",
            "titulo": f"{len(d['fontes_pendentes'])} código(s) de fonte de recursos sem correspondência",
            "detalhe": ("Códigos observados nas publicações e ainda não mapeados: "
                        + ", ".join(list(d["fontes_pendentes"])[:20])
                        + ". Confirmar contra o Quadro de Detalhamento de Despesas do "
                          "exercício e preencher config/fontes_recursos.yml."),
            "saida_sugerida": "minuta_lai",
            "detectado_em": agora().isoformat(),
        })
    return out


if __name__ == "__main__":
    nome = sys.argv[1] if len(sys.argv) > 1 else "assistencia_social"
    dom = yaml.safe_load((RAIZ / "config" / "dominios" / f"{nome}.yml").read_text(encoding="utf-8"))
    d = conciliar(dom)
    print(json.dumps({k: d[k] for k in ("linhas", "valor_total", "indice_rastreabilidade",
                                        "para_entidades_privadas", "por_ente", "por_ano")},
                     ensure_ascii=False, indent=2))
    for a in achados(d):
        print(f"\n[{a['regra']}·{a['severidade']}] {a['titulo']}")
