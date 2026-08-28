#!/usr/bin/env python3
"""Avaliação dominical das contas — o julgamento sai no domingo, 6h de
Goiânia (9h UTC).

Divisão rígida de trabalho, pela regra de ouro do roteador:
  - todo o levantamento é determinístico (este script monta o dossiê
    compacto por recortes, sem mandar documento inteiro a modelo algum);
  - o julgamento — e só ele — vai ao modelo avançado (Fable 5; na falta,
    Opus), porque avaliação consolidada de contas é juízo, não extração.

Regra de calendário:
  - todo domingo: avaliação do que foi lançado na semana;
  - primeiro domingo após o encerramento de um mês com verificação mensal
    concluída: avaliação consolidada daquela competência, além da semanal.

Sem ANTHROPIC_API_KEY, o script degrada limpo: publica o dossiê
determinístico com a marca AVALIACAO_PENDENTE_DE_MODELO — dado faltante
é achado, não silêncio, e a pendência P1 fica registrada no próprio
relatório.

Uso: python3 src/avaliacao_dominical.py [AAAA-MM-DD simulada]
Saída: relatorios/avaliacao_dominical/AAAA-MM-DD.md
"""
from __future__ import annotations
import json, os, sys
from datetime import date, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
REL = RAIZ / "relatorios"
SAIDA = REL / "avaliacao_dominical"
sys.path.insert(0, str(RAIZ / "src"))
from util import ler_json


def competencia_a_consolidar(hoje: date) -> str | None:
    """Primeiro domingo estritamente posterior ao fim do mês anterior."""
    primeiro_do_mes = hoje.replace(day=1)
    dias_desde_virada = (hoje - primeiro_do_mes).days
    if hoje.weekday() == 6 and dias_desde_virada < 7:
        anterior = primeiro_do_mes - timedelta(days=1)
        comp = f"{anterior:%Y-%m}"
        if (REL / "mensal" / f"verificacao_{comp}.json").exists():
            return comp
    return None


def dossie(hoje: date) -> tuple[str, dict]:
    consolidado = ler_json(REL / "achados_consolidados_2026.json", {})
    dupla = ler_json(REL / "dupla_etapa_2026.json", {})
    prec = ler_json(RAIZ / "referencias" / "transparencia"
                    / "precedentes.json", {"itens": []})
    semana_ini = (hoje - timedelta(days=7)).isoformat()
    novos_prec = [p for p in prec["itens"]
                  if p.get("capturado_em", "") >= semana_ini][:8]
    comp = competencia_a_consolidar(hoje)
    partes = [
        f"DOSSIÊ SEMANAL — domingo {hoje.isoformat()}",
        f"Consolidado do exercício: {consolidado.get('total')} achados — "
        f"{consolidado.get('por_severidade')} | selos "
        f"{consolidado.get('por_selo')} | documentos requisitados: "
        f"{consolidado.get('documentos_requisitados')}",
        f"Dupla etapa: {dupla.get('convergiram')} convergiram, "
        f"{dupla.get('divergiram')} divergiram, "
        f"{dupla.get('indisponiveis')} indisponíveis (de "
        f"{dupla.get('acionados')} acionados).",
    ]
    if comp:
        v = ler_json(REL / "mensal" / f"verificacao_{comp}.json", {})
        partes.append(
            f"CONSOLIDAÇÃO MENSAL DEVIDA — competência {comp} "
            f"({v.get('mes')}): {v.get('total_achados')} achados — "
            f"{v.get('por_severidade')} | selos {v.get('por_selo')} | "
            f"execução {v.get('execucao_do_mes')} | publicação do Diário "
            f"{v.get('publicacao_do_mes')}. Achados do mês: "
            + "; ".join(f"[{a['codigo']}|{a['selo']}] {a['titulo']}"
                        for a in v.get("achados", [])))
    if novos_prec:
        partes.append("Precedentes de outros estados capturados na semana "
                      "(direcionam pesquisa, não fundamentam parecer): "
                      + "; ".join(f"{p['titulo']} ({p['fonte']})"
                                  for p in novos_prec))
    top = [a for a in consolidado.get("achados", [])
           if a.get("severidade") == "critica"][:8]
    partes.append("Críticos vigentes: " + "; ".join(
        f"[{a['codigo']}|{a['selo']}] {a['titulo']}" for a in top))
    return "\n\n".join(partes), {"competencia_consolidada": comp,
                                 "precedentes_novos": len(novos_prec)}


INSTRUCAO = """Você é assessor jurídico de fiscalização da assistência \
social de Goiânia, com rigor de auditor de tribunal de contas e de promotor. \
Avalie o dossiê e produza a AVALIAÇÃO DOMINICAL em markdown, com:
1. Juízo consolidado da semana (e do mês, se houver consolidação devida) — \
o que piorou, o que estagnou, o que os selos permitem afirmar em peça.
2. Três providências prioritárias para a semana, cada uma com a norma por \
extenso que a sustenta.
3. Se houver precedentes listados, diga qual merece estudo para replicação \
em Goiânia e por quê — sem tratá-lo como fundamento de parecer.
Regras invioláveis: só desconformidade; selo antes de qualquer afirmação; \
em peça, use apenas o confirmado por dupla via; norma por extenso; sem \
jurisprudência e sem doutrina; indício de sobrepreço é indício; nada é \
peça processual sem revisão de advogado, Artigo 32 da Lei 8.906/1994; \
trilhas SEMASDH e CMASGyn sempre separadas."""


def julgar(texto: str) -> tuple[str, str]:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return ("AVALIACAO_PENDENTE_DE_MODELO", "")
    from roteador_ia import MODELOS, PARAMETROS  # type: ignore
    import urllib.request
    modelos = [MODELOS.get("fable", "claude-fable-5"),
               MODELOS.get("opus")]
    for m in [x for x in modelos if x]:
        try:
            corpo = json.dumps({
                "model": m, "max_tokens": 3000,
                "system": INSTRUCAO,
                "messages": [{"role": "user", "content": texto}],
            }).encode()
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages", data=corpo,
                headers={"content-type": "application/json",
                         "x-api-key": os.environ["ANTHROPIC_API_KEY"],
                         "anthropic-version": "2023-06-01"})
            with urllib.request.urlopen(req, timeout=180) as r:
                d = json.loads(r.read())
            return ("OK", "".join(b.get("text", "")
                                  for b in d.get("content", [])) or "")
        except Exception as e:
            print(f"  [aviso] modelo {m} indisponível: {e}", file=sys.stderr)
    return ("AVALIACAO_PENDENTE_DE_MODELO", "")


def main():
    hoje = (date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1
            else date.today())
    texto, meta = dossie(hoje)
    situacao, avaliacao = julgar(texto)
    SAIDA.mkdir(parents=True, exist_ok=True)
    destino = SAIDA / f"{hoje.isoformat()}.md"
    cab = (f"# Avaliação dominical — {hoje.isoformat()}\n\n"
           f"Competência consolidada neste domingo: "
           f"{meta['competencia_consolidada'] or 'nenhuma (domingo comum)'} · "
           f"precedentes novos na semana: {meta['precedentes_novos']}\n\n")
    if situacao == "OK":
        corpo = avaliacao + ("\n\n---\n*Julgamento por modelo avançado; "
                             "levantamento 100% determinístico. Nada aqui é "
                             "peça processual sem revisão de advogado — "
                             "Artigo 32 da Lei 8.906/1994.*\n")
    else:
        corpo = ("**AVALIACAO_PENDENTE_DE_MODELO** — `ANTHROPIC_API_KEY` "
                 "ausente ou modelos indisponíveis (pendência P1). O dossiê "
                 "determinístico segue abaixo; o julgamento será emitido no "
                 "primeiro domingo após o suprimento da chave.\n\n```\n"
                 + texto + "\n```\n")
    destino.write_text(cab + corpo, encoding="utf-8")
    print(f"  avaliação dominical: {destino.relative_to(RAIZ)} [{situacao}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
