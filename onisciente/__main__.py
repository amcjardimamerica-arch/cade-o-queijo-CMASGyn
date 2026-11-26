"""Linha de comando do Onisciente.

    python -m onisciente verificar            # confere mapa legal, alvo e domínios
    python -m onisciente parecer              # parecer da última competência disponível
    python -m onisciente parecer --competencia 2026-10
    python -m onisciente parecer --todas      # refaz todos os pareceres do exercício
    python -m onisciente coletar leis         # confere as normas no ctresb/leis (rede)
    python -m onisciente coletar siconfi --exercicio 2025 --periodo 6   (rede)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

from . import RAIZ
from .adaptadores import cadeoqueijo
from .coletores import base as coleta
from .config import carregar_alvo
from .lai import oficios_por_orgao
from .legal.mapa import carregar
from .parecer import html as parecer_html

SAIDA_DOCS = RAIZ / "docs" / "onisciente"
SAIDA_RELATORIOS = RAIZ / "relatorios" / "onisciente"


def competencias_disponiveis(raiz: Path = RAIZ) -> list[str]:
    pasta = raiz / "relatorios" / "mensal"
    achadas = []
    for arq in pasta.glob("verificacao_*.json"):
        m = re.fullmatch(r"verificacao_(\d{4}-\d{2})\.json", arq.name)
        if m:
            achadas.append(m.group(1))
    return sorted(achadas)


def cmd_verificar(_args) -> int:
    mapa = carregar()
    alvo = carregar_alvo()
    erros = mapa.problemas()
    for d in alvo.dominios.values():
        erros += d.problemas()
        for r in d.regras:
            if r not in mapa.regras:
                erros.append(f"{d.id}: regra {r} não está no mapa legal")
    if alvo.faixa_camara not in (mapa.regra("CAMARA").get("faixas") or {}):
        erros.append(f"faixa da Câmara desconhecida: {alvo.faixa_camara}")
    print(f"Mapa legal {mapa.versao}: {len(mapa.regras)} regras, {len(mapa.normas)} normas "
          f"({len(mapa.nao_localizadas())} não localizadas, viram ofício).")
    print(f"Alvo: {alvo.nome}; domínios ativos: {', '.join(d.nome for d in alvo.ativos())}.")
    for e in erros:
        print("ERRO:", e)
    print("Tudo conferido." if not erros else f"{len(erros)} problema(s).")
    return 1 if erros else 0


def gerar_parecer(competencia: str, *, hoje: date | None = None) -> dict:
    alvo = carregar_alvo()
    panorama = cadeoqueijo.montar(competencia, alvo=alvo.nome)
    estado = coleta._carregar_estado()
    panorama.fichas += coleta.fontes_paradas(estado, hoje or date.today(),
                                             int(carregar().regra("FONTE-PARADA").valor or 3))
    SAIDA_DOCS.mkdir(parents=True, exist_ok=True)
    SAIDA_RELATORIOS.mkdir(parents=True, exist_ok=True)
    arq_html = SAIDA_DOCS / f"parecer_{competencia}.html"
    arq_html.write_text(parecer_html.gerar(panorama, hoje=hoje), encoding="utf-8")
    (SAIDA_RELATORIOS / f"panorama_{competencia}.json").write_text(
        json.dumps(panorama.como_dict(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    oficios = oficios_por_orgao(panorama.ausencias, f"Documentos não publicados: {panorama.dominio}, "
                                                    f"competência {competencia}")
    (SAIDA_RELATORIOS / f"oficios_{competencia}.txt").write_text(
        "\n\n" + ("\n\n" + "=" * 72 + "\n\n").join(o.texto(hoje=hoje) for o in oficios) + "\n",
        encoding="utf-8")
    return {"competencia": competencia, "html": str(arq_html.relative_to(RAIZ)),
            "frase": panorama.em_uma_frase()}


def atualizar_indice() -> None:
    alvo = carregar_alvo()
    pareceres = []
    for arq in SAIDA_DOCS.glob("parecer_*.html"):
        m = re.fullmatch(r"parecer_(\d{4}-\d{2})\.html", arq.name)
        if m:
            pareceres.append((m.group(1), arq.name))
    (SAIDA_DOCS / "index.html").write_text(parecer_html.indice(pareceres, alvo.nome), encoding="utf-8")


def cmd_parecer(args) -> int:
    disponiveis = competencias_disponiveis()
    if not disponiveis:
        print("Nenhuma verificação mensal do Cadê o Queijo encontrada.", file=sys.stderr)
        return 1
    if args.todas:
        alvo = [c for c in disponiveis if c.startswith(disponiveis[-1][:4])]
    else:
        alvo = [args.competencia or disponiveis[-1]]
    for c in alvo:
        r = gerar_parecer(c)
        print(f"{r['competencia']}: {r['frase']} -> {r['html']}")
    atualizar_indice()
    return 0


def cmd_coletar(args) -> int:
    if args.fonte == "leis":
        from .coletores.leis import RAW_CTRESB, conferir_ctresb
        resultado = conferir_ctresb()
        falhas = [r for r in resultado if not r["ok"]]
        revogadas = [r for r in resultado if r.get("revogada")]
        coleta.registrar("ctresb", coleta.Leitura(not falhas, RAW_CTRESB,
                                                  erro="; ".join(r["caminho"] for r in falhas)),
                        ciclo_dias=31)
        for r in resultado:
            situacao = "ok" if r["ok"] else f"FALHOU ({r.get('erro')})"
            print(f"{situacao:>8} {'REVOGADA ' if r.get('revogada') else ''}{r['caminho']}")
        print(f"{len(resultado)} normas conferidas; {len(falhas)} falha(s); {len(revogadas)} revogada(s).")
        return 1 if (falhas or revogadas) else 0
    if args.fonte == "siconfi":
        from .coletores import siconfi
        alvo = carregar_alvo()
        codigo = 0
        for d in alvo.dominios.values():
            cfg = d.extras.get("siconfi")
            if not cfg:
                continue
            leitura = siconfi.coletar(cfg["demonstrativo"], ente=alvo.siconfi_id_ente,
                                      exercicio=args.exercicio, periodo=args.periodo or cfg["periodo"],
                                      anexo=cfg["anexo"])
            print(f"{d.nome}: {'ok' if leitura.ok else 'falhou: ' + leitura.erro}")
            codigo |= 0 if leitura.ok else 1
        return codigo
    return 2


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="onisciente", description="A trilha do dinheiro público.")
    sub = p.add_subparsers(dest="comando", required=True)
    sub.add_parser("verificar", help="confere mapa legal, alvo e domínios").set_defaults(f=cmd_verificar)
    pp = sub.add_parser("parecer", help="gera o parecer mensal em HTML")
    pp.add_argument("--competencia", help="AAAA-MM (padrão: a última disponível)")
    pp.add_argument("--todas", action="store_true", help="todas as competências do exercício")
    pp.set_defaults(f=cmd_parecer)
    pc = sub.add_parser("coletar", help="coleta uma fonte (precisa de rede)")
    pc.add_argument("fonte", choices=["leis", "siconfi"])
    pc.add_argument("--exercicio", type=int, default=date.today().year - 1)
    pc.add_argument("--periodo", type=int)
    pc.set_defaults(f=cmd_coletar)
    args = p.parse_args(argv)
    return args.f(args)


if __name__ == "__main__":
    raise SystemExit(main())
