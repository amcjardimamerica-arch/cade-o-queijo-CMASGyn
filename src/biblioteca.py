"""Biblioteca dos atos do CMASGyn e apuração do que não foi divulgado.

O método parte de uma constatação simples: um ato administrativo deixa rastro
mesmo quando não é publicado. Ele é citado na ementa de outro ato, aparece na
lista de revogações de uma consolidação, é mencionado num considerando, ou
simplesmente ocupa um número na sequência.

Daí três situações possíveis para cada ato:

  PUBLICADO      o texto integral foi localizado no Diário Oficial
  APENAS_CITADO  o ato é referido por outro, mas seu texto nunca apareceu
  PRESUMIDO      ninguém o cita, mas o número existe entre dois publicados

As duas últimas categorias são o objeto da fiscalização: atos que produzem
efeito sem terem sido tornados públicos, em desacordo com o artigo 37, caput,
da Constituição Federal e com o artigo 8º da Lei 12.527/2011.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import extracao
from util import RAIZ, agora, gravar_json, log

SAIDA = RAIZ / "dados" / "biblioteca_cmasgyn.json"

# Cabeçalho de ato publicado por inteiro: número, ano e, logo adiante, a ementa.
RE_CABECALHO = re.compile(
    r"RESOLU[ÇC][ÃA]O\s*(?:CMAS\s*/?\s*GYN|CMAS)?\s*n?[.º°]?\s*0*(\d{1,4})\s*[/\-]\s*(\d{4})"
    r"[^\n]{0,40}\n?\s*(?:[-–—]\s*)?"
    r"(Disp[õo]e sobre|Aprova|Altera|Revoga|Institui|Homologa|Defere|Indefere|"
    r"Estabelece|Fixa|Torna p[úu]blic|Cria|Regulamenta|Ratifica|Referenda)"
    r"([^.;]{0,260})", re.IGNORECASE)

# Menção simples, sem o corpo do ato.
RE_MENCAO = re.compile(
    r"Resolu[çc][ãa]o\s*(?:n?[.º°]?\s*)?(?:CMAS\s*/?\s*Gyn|CMAS)?\s*n?[.º°]?\s*"
    r"0*(\d{1,4})\s*[/\-]\s*(\d{4})", re.IGNORECASE)

RE_CTX_CONSELHO = re.compile(
    r"(CMAS\s*/?\s*Gyn|Conselho Municipal de Assist[êe]ncia Social)", re.IGNORECASE)

# Sinais de que o ato foi transcrito por inteiro, e não apenas nomeado.
RE_CORPO = re.compile(
    r"(Art(?:igo)?\.?\s*1[º°o]|no uso d[ae]s?\s+(?:suas\s+)?atribui[çc][õo]es|"
    r"resolve\s*:|O\s+CONSELHO\s+MUNICIPAL|Publique[- ]se)", re.IGNORECASE)

RE_ATA_CABECALHO = re.compile(
    r"ATA\s+D[AO]\s+(\d{0,3}[ªa]?)\s*(REUNI[ÃA]O|PLEN[ÁA]RIA|ASSEMBLEIA|SESS[ÃA]O)"
    r"\s*(ORDIN[ÁA]RIA|EXTRAORDIN[ÁA]RIA)?[^\n]{0,120}", re.IGNORECASE)

CLASSES_OBJETO = {
    "inscricao_de_entidade": r"inscri[çc][ãa]o|deferimento|indeferimento|CNEAS|reordenamento",
    "plano_de_acao": r"plano de a[çc][ãa]o|plano de trabalho|plano municipal",
    "prestacao_de_contas": r"presta[çc][ãa]o de contas|comprova[çc][ãa]o de gastos|"
                           r"demonstrativo",
    "cofinanciamento": r"cofinanciamento|piso|repasse|transfer[êe]ncia fundo a fundo|"
                       r"emenda parlamentar",
    "igd": r"IGD|[ÍI]ndice de Gest[ãa]o Descentralizada",
    "composicao_do_conselho": r"conselheir|composi[çc][ãa]o|mandato|elei[çc][ãa]o|posse|"
                              r"mesa diretora|comiss[ãa]o",
    "conferencia": r"confer[êe]ncia|delegad",
    "regimento": r"regimento|regulamenta[çc][ãa]o interna",
    "orcamento": r"or[çc]ament|LOA|LDO|PPA|dota[çc][ãa]o|cr[ée]dito",
    "servico_socioassistencial": r"CRAS|CREAS|acolhimento|conviv[êe]ncia|PAIF|PAEFI|"
                                 r"prote[çc][ãa]o social",
}
CLASSES_RE = {k: re.compile(v, re.IGNORECASE) for k, v in CLASSES_OBJETO.items()}


def _classificar(texto: str) -> list[str]:
    return [k for k, r in CLASSES_RE.items() if r.search(texto)]


def construir(dominio_id: str = "assistencia_social") -> dict:
    trechos = extracao.carregar(dominio_id)
    if not trechos:
        log.warning("Nenhum trecho extraído. Rode src/extracao.py antes.")
        return {}

    atos: dict[str, dict] = {}
    atas: list[dict] = []

    for t in trechos:
        texto = t["texto"]
        proveniencia = {
            "edicao": t["edicao"], "data": t["data"], "url": t["url_original"],
            "sha256_edicao": t["sha256_edicao"], "pagina": t["pagina_estimada"],
            "trecho_id": t["id"],
        }

        # ---- atos publicados por inteiro
        for m in RE_CABECALHO.finditer(texto):
            n, ano = int(m.group(1)), int(m.group(2))
            if not (2015 <= ano <= 2030):
                continue
            chave = f"{n:03d}/{ano}"
            depois = texto[m.end():m.end() + 1200]
            integral = bool(RE_CORPO.search(depois))
            ementa = re.sub(r"\s+", " ", (m.group(3) + m.group(4))).strip()
            reg = atos.setdefault(chave, _novo(n, ano))
            if integral:
                reg["situacao"] = "PUBLICADO"
                reg["publicacoes"].append(proveniencia)
            elif reg["situacao"] == "APENAS_CITADO":
                reg["citacoes"].append(proveniencia)
            if not reg["ementa"] and len(ementa) > 12:
                reg["ementa"] = ementa[:260]
            reg["classes"] = sorted(set(reg["classes"]) | set(_classificar(ementa + depois[:400])))

        # ---- menções sem corpo
        for m in RE_MENCAO.finditer(texto):
            n, ano = int(m.group(1)), int(m.group(2))
            if not (2015 <= ano <= 2030):
                continue
            volta = texto[max(0, m.start() - 260): m.end() + 260]
            if not RE_CTX_CONSELHO.search(volta):
                continue
            chave = f"{n:03d}/{ano}"
            reg = atos.setdefault(chave, _novo(n, ano))
            if reg["situacao"] != "PUBLICADO":
                reg["citacoes"].append(proveniencia)
            if not reg["ementa"]:
                e = re.search(r"[-–—]\s*(Disp[õo]e sobre|Aprova|Altera|Revoga|Institui)"
                              r"([^.;]{0,220})", texto[m.end():m.end() + 260], re.IGNORECASE)
                if e:
                    reg["ementa"] = re.sub(r"\s+", " ", e.group(0)).strip(" -–—")[:260]

        # ---- atas
        for m in RE_ATA_CABECALHO.finditer(texto):
            if RE_CTX_CONSELHO.search(texto[max(0, m.start() - 400): m.end() + 800]):
                atas.append({**proveniencia,
                             "cabecalho": re.sub(r"\s+", " ", m.group(0))[:150]})

    # ---- atos presumidos pelas lacunas de numeração
    por_ano: dict[int, set[int]] = defaultdict(set)
    for k, v in atos.items():
        por_ano[v["ano"]].add(v["numero"])
    presumidos = 0
    for ano, nums in por_ano.items():
        if len(nums) < 3:
            continue
        for n in sorted(set(range(min(nums), max(nums) + 1)) - nums):
            atos[f"{n:03d}/{ano}"] = {**_novo(n, ano), "situacao": "PRESUMIDO"}
            presumidos += 1

    # ---- consolidação
    for v in atos.values():
        if v["publicacoes"]:
            v["situacao"] = "PUBLICADO"
        elif v["citacoes"]:
            v["situacao"] = "APENAS_CITADO"
        v["n_publicacoes"] = len(v["publicacoes"])
        v["n_citacoes"] = len(v["citacoes"])
        v["primeira_aparicao"] = min(
            [p["data"] for p in v["publicacoes"] + v["citacoes"]], default=None)

    lista = sorted(atos.values(), key=lambda x: (-x["ano"], -x["numero"]))
    sit = Counter(a["situacao"] for a in lista)
    nao_divulgados = [a for a in lista if a["situacao"] != "PUBLICADO"]

    atas_unicas = {a["cabecalho"][:70] + a["data"]: a for a in atas}
    por_ano_sit: dict[str, Counter] = defaultdict(Counter)
    for a in lista:
        por_ano_sit[str(a["ano"])][a["situacao"]] += 1

    dados = {
        "dominio": dominio_id,
        "gerado_em": agora().isoformat(),
        "total_atos": len(lista),
        "situacoes": dict(sit),
        "por_ano": {k: dict(v) for k, v in sorted(por_ano_sit.items())},
        "indice_de_publicidade": round(100 * sit.get("PUBLICADO", 0) / max(len(lista), 1), 2),
        "atos": lista,
        "nao_divulgados": nao_divulgados,
        "atas_localizadas": sorted(atas_unicas.values(), key=lambda x: x["data"], reverse=True),
        "presumidos_por_lacuna": presumidos,
        "classes_frequentes": Counter(
            c for a in lista for c in a["classes"]).most_common(),
    }
    gravar_json(SAIDA, dados)
    log.info("Biblioteca: %d atos | publicados %d, apenas citados %d, presumidos %d "
             "| índice de publicidade %.2f%% | %d ata(s)",
             len(lista), sit.get("PUBLICADO", 0), sit.get("APENAS_CITADO", 0),
             presumidos, dados["indice_de_publicidade"], len(atas_unicas))
    return dados


def _novo(n: int, ano: int) -> dict:
    return {"chave": f"{n:03d}/{ano}", "numero": n, "ano": ano,
            "situacao": "APENAS_CITADO", "ementa": None, "classes": [],
            "publicacoes": [], "citacoes": []}


def achados(dados: dict) -> list[dict]:
    """Converte a apuração em achados de conformidade."""
    out = []
    ind = dados.get("indice_de_publicidade", 100)
    if ind < 90:
        out.append({
            "regra": "PUB-01", "severidade": "alta",
            "titulo": f"Índice de publicidade dos atos do conselho em {ind}%",
            "detalhe": (
                f"De {dados['total_atos']} atos identificados no triênio, apenas "
                f"{dados['situacoes'].get('PUBLICADO', 0)} tiveram texto integral "
                f"localizado no Diário Oficial. Outros "
                f"{dados['situacoes'].get('APENAS_CITADO', 0)} são referidos por atos "
                f"posteriores sem que seu inteiro teor jamais tenha sido publicado, e "
                f"{dados.get('presumidos_por_lacuna', 0)} ocupam número na sequência sem "
                "qualquer rastro público. Ato deliberativo que produz efeito sem "
                "publicação contraria o artigo 37, caput, da Constituição Federal e o "
                "dever de transparência ativa do artigo 8º da Lei 12.527/2011."),
            "fundamento": "Constituição Federal, artigo 37, caput; Lei 12.527/2011, artigo 8º",
            "saida_sugerida": "representacao_mp",
            "detectado_em": agora().isoformat(),
        })
    for ano, v in dados.get("por_ano", {}).items():
        tot = sum(v.values())
        pub = v.get("PUBLICADO", 0)
        if tot >= 5 and pub / tot < 0.5:
            out.append({
                "regra": "PUB-02", "severidade": "media",
                "titulo": f"Exercício de {ano} com maioria de atos não publicados",
                "detalhe": (f"Em {ano}, {pub} de {tot} atos tiveram inteiro teor "
                            "localizado. Os demais existem apenas por citação ou por "
                            "lacuna de numeração."),
                "data_ref": f"{ano}-12-31",
                "fundamento": "Lei 12.527/2011, artigo 8º",
                "saida_sugerida": "minuta_lai",
                "detectado_em": agora().isoformat(),
            })
    if not dados.get("atas_localizadas"):
        out.append({
            "regra": "ATA-07", "severidade": "alta",
            "titulo": "Nenhuma ata de plenária publicada no Diário Oficial no triênio",
            "detalhe": ("Não se localizou, em três anos de edições, uma única ata de "
                        "reunião plenária do conselho. Sem ata pública não há como "
                        "aferir quórum, deliberação nem voto — o controle social fica "
                        "impossibilitado de exercer-se sobre o próprio órgão de "
                        "controle social."),
            "fundamento": "Regimento Interno do CMASGyn; Lei 12.527/2011, artigo 8º",
            "saida_sugerida": "representacao_mp",
            "detectado_em": agora().isoformat(),
        })
    return out


if __name__ == "__main__":
    d = construir(sys.argv[1] if len(sys.argv) > 1 else "assistencia_social")
    print(json.dumps({k: d[k] for k in
                      ("total_atos", "situacoes", "por_ano", "indice_de_publicidade",
                       "presumidos_por_lacuna")}, ensure_ascii=False, indent=2))
    for a in achados(d):
        print(f"\n[{a['regra']}·{a['severidade']}] {a['titulo']}")
