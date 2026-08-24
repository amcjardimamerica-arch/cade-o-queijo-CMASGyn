"""Critérios de qualidade derivados do repositório de leis.

O repositório normativo é atualizado uma vez por mês. Deste módulo saem os
parâmetros verificáveis que dele decorrem — prazos, percentuais, quóruns,
periodicidades — extraídos por expressão regular do próprio texto das normas,
e não digitados à mão. Assim, quando a norma muda, o critério muda com ela.

Cada critério vira uma regra de conformidade determinística, aplicada ao
acervo sem custo de token.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from util import CORPUS, RAIZ, agora, gravar_json, ler_json, log

SAIDA = RAIZ / "dados" / "criterios_qualidade.json"

# --------------------------------------------------------------- extratores
PADROES = {
    "percentual_igd_controle_social": {
        "regex": r"(?:no\s+m[íi]nimo|pelo\s+menos)\s+(\d{1,3})\s*%[^.]{0,220}"
                 r"(?:controle\s+social|conselho[s]?\s+de\s+assist)",
        "tipo": "percentual",
        "descricao": "Piso do IGD destinado ao financiamento do controle social",
    },
    "periodicidade_prestacao_contas_meses": {
        "regex": r"presta[çc][ãa]o\s+de\s+contas[^.]{0,140}?"
                 r"a\s+cada\s+(\d{1,2})\s+(?:\(\w+\)\s+)?meses",
        "tipo": "inteiro",
        "descricao": "Intervalo entre prestações de contas ao conselho",
    },
    "prazo_lai_dias": {
        "regex": r"prazo\s+n[ãa]o\s+superior\s+a\s+(\d{1,2})\s*\(\w+\)\s*dias",
        "tipo": "inteiro",
        "descricao": "Prazo de resposta ao pedido de acesso à informação",
    },
    "prazo_prorrogacao_lai_dias": {
        "regex": r"prorrogado\s+por\s+mais\s+(\d{1,2})\s*\(\w+\)\s*dias",
        "tipo": "inteiro",
        "descricao": "Prorrogação do prazo de resposta",
    },
    "prazo_recurso_lai_dias": {
        "regex": r"recurso[^.]{0,120}?prazo\s+de\s+(\d{1,2})\s*\(\w+\)\s*dias",
        "tipo": "inteiro",
        "descricao": "Prazo recursal em pedido de acesso à informação",
    },
    "periodicidade_conferencia_anos": {
        "regex": r"confer[êe]ncias?[^.]{0,160}?a\s+cada\s+(\d)\s*\(\w+\)\s*anos",
        "tipo": "inteiro",
        "descricao": "Periodicidade da conferência de assistência social",
    },
    "mandato_conselheiro_anos": {
        "regex": r"mandato[^.]{0,120}?(\d)\s*\(\w+\)\s*anos",
        "tipo": "inteiro",
        "descricao": "Duração do mandato de conselheiro",
    },
    "prazo_analise_inscricao_dias": {
        "regex": r"(?:an[áa]lise|aprecia[çc][ãa]o)[^.]{0,140}?"
                 r"(?:prazo\s+de|em\s+at[ée])\s+(\d{1,3})\s*\(?\w*\)?\s*dias",
        "tipo": "inteiro",
        "descricao": "Prazo para apreciação de pedido de inscrição de entidade",
    },
}

# Critérios que não se extraem do texto e ficam declarados, com a norma de apoio.
DECLARADOS = {
    "voto_nominal_exigido": {
        "valor": True,
        "fonte": "Regimento Interno do CMASGyn",
        "descricao": "Deliberação exige registro nominal do voto de cada conselheiro",
        "regra": "ATA-04",
    },
    "paridade_governo_sociedade": {
        "valor": True,
        "fonte": "Lei 8.742/1993, artigo 16",
        "descricao": "Composição paritária entre governo e sociedade civil",
        "regra": "ATA-06",
    },
    "publicacao_no_diario_oficial": {
        "valor": True,
        "fonte": "Constituição Federal, artigo 37, caput",
        "descricao": "Ato deliberativo deve ser publicado no Diário Oficial",
        "regra": "RES-02",
    },
    "motivacao_expressa": {
        "valor": True,
        "fonte": "Lei 9.784/1999, artigo 50",
        "descricao": "Ato que defere, indefere ou aprova contas exige motivação",
        "regra": "ENT-01",
    },
    "dotacao_especifica_controle_social": {
        "valor": True,
        "vigencia_desde": "2026-01-01",
        "fonte": "Resolução CNAS/MDS 202/2025",
        "descricao": "Dotação orçamentária própria de fortalecimento do controle social",
        "regra": "IGD-02",
    },
}


def extrair() -> dict:
    arq = CORPUS / "corpus.md"
    if not arq.exists():
        log.warning("corpus/corpus.md ausente — critérios ficam apenas nos declarados")
        texto = ""
    else:
        texto = arq.read_text(encoding="utf-8", errors="ignore")

    extraidos: dict = {}
    for chave, cfg in PADROES.items():
        achados = []
        for m in re.finditer(cfg["regex"], texto, re.IGNORECASE | re.DOTALL):
            # Localiza a norma de origem pelo cabeçalho de bloco mais próximo acima.
            antes = texto[:m.start()]
            titulo = re.findall(r"\n## \[([^\]]+)\] ([^\n]+)", antes)
            fonte = titulo[-1][1] if titulo else "não identificada"
            achados.append({"valor": int(m.group(1)), "fonte": fonte,
                            "trecho": re.sub(r"\s+", " ", m.group(0))[:200]})
        if achados:
            # Norma mais recente no corpus prevalece: fica a última ocorrência.
            extraidos[chave] = {**cfg, "ocorrencias": achados,
                                "valor_vigente": achados[-1]["valor"],
                                "conflito": len({a["valor"] for a in achados}) > 1}
            if extraidos[chave]["conflito"]:
                log.warning("Antinomia em %s: valores %s", chave,
                            sorted({a["valor"] for a in achados}))
        else:
            extraidos[chave] = {**cfg, "ocorrencias": [], "valor_vigente": None,
                                "conflito": False}

    manifesto = ler_json(CORPUS / "manifesto.json", {})
    criterios = {
        "gerado_em": agora().isoformat(),
        "corpus_sha256": manifesto.get("sha256"),
        "corpus_gerado_em": manifesto.get("gerado_em"),
        "normas_no_corpus": manifesto.get("normas", 0),
        "extraidos": extraidos,
        "declarados": DECLARADOS,
        "antinomias": [k for k, v in extraidos.items() if v.get("conflito")],
    }
    gravar_json(SAIDA, criterios)
    log.info("Critérios de qualidade: %d extraídos, %d declarados, %d antinomia(s)",
             sum(1 for v in extraidos.values() if v["valor_vigente"] is not None),
             len(DECLARADOS), len(criterios["antinomias"]))
    return criterios


def valor(chave: str, padrao=None):
    """Consulta um critério vigente. Usado pelas regras de conformidade."""
    c = ler_json(SAIDA, {})
    if chave in c.get("extraidos", {}):
        v = c["extraidos"][chave]["valor_vigente"]
        if v is not None:
            return v
    if chave in c.get("declarados", {}):
        d = c["declarados"][chave]
        if d.get("vigencia_desde") and agora().date() < date.fromisoformat(d["vigencia_desde"]):
            return padrao
        return d["valor"]
    return padrao


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--reconstruir", action="store_true")
    ap.parse_args()
    print(json.dumps(extrair(), ensure_ascii=False, indent=2)[:3000])
