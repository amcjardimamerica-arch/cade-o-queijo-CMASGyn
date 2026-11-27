"""Linha de comando do Onisciente.

    python -m onisciente verificar            # confere mapa legal, alvo e domínios
    python -m onisciente parecer              # parecer da última competência disponível
    python -m onisciente parecer --competencia 2026-10
    python -m onisciente parecer --todas      # refaz todos os pareceres do exercício
    python -m onisciente coletar leis         # confere as normas no ctresb/leis (rede)
    python -m onisciente coletar siconfi --exercicio 2025 --periodo 6   (rede)
    python -m onisciente historico --desde 2024-11 --ate 2026-11   (rede; banco + diagnóstico)
    python -m onisciente diagnostico          # refaz o diagnóstico a partir do banco, sem rede
    python -m onisciente painel-banco         # refaz só a página do banco no site, sem rede
    python -m onisciente selo                 # auditoria independente do selo de transparência (PNTP)
    python -m onisciente selo --sondar        # lê antes o portal, o Radar e o sítio do Conselho (rede)
    python -m onisciente empresas             # confere as contratadas e escreve docs/onisciente/empresas.html
    python -m onisciente telas                # gera as telas (docs/onisciente/app), sem rede
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
    banco = (SAIDA_DOCS / "banco" / "index.html").exists()
    (SAIDA_DOCS / "index.html").write_text(parecer_html.indice(pareceres, alvo.nome, banco=banco),
                                           encoding="utf-8")


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


def _imprimir_diagnostico(d: dict, arquivos) -> None:
    from collections import Counter
    tipos = Counter(a["tipo"] for a in d["achados"])
    for r in d["motores"]:
        print(f"{r['nome']}: {r['ok']}/{r['chamadas']} chamadas certas")
    print(f"Achados: {tipos.get('falha', 0)} falha(s), {tipos.get('lacuna', 0)} lacuna(s), "
          f"{tipos.get('melhoria', 0)} melhoria(s).")
    for a in arquivos:
        print("->", Path(a).relative_to(RAIZ) if Path(a).is_relative_to(RAIZ) else a)


def cmd_historico(args) -> int:
    from . import diagnostico, historico
    motores = tuple(args.motores.split(",")) if args.motores else historico.MOTORES
    desconhecidos = set(motores) - set(historico.MOTORES)
    if desconhecidos:
        print(f"motor desconhecido: {', '.join(sorted(desconhecidos))}", file=sys.stderr)
        return 2
    banco = historico.rodar(args.desde, args.ate, motores=motores,
                            brutos=Path(args.brutos) if args.brutos else None, pausa=args.pausa,
                            somar=args.somar)
    d = diagnostico.diagnosticar(banco)
    pagina = _publicar_banco(banco, d)
    banco.fechar()
    _imprimir_diagnostico(d, [*diagnostico.gravar(d, SAIDA_RELATORIOS), *pagina])
    return 0


def _publicar_banco(banco, d: dict) -> list[Path]:
    """Escreve a página do banco no site e liga ela no índice dos pareceres."""
    from . import painel_banco
    arquivos = painel_banco.gerar(banco, d)
    atualizar_indice()
    return arquivos


def cmd_diagnostico(_args) -> int:
    from . import diagnostico, historico
    if not historico.BANCO.exists():
        print("Banco histórico não encontrado; rode `python -m onisciente historico`.", file=sys.stderr)
        return 1
    banco = historico.Banco.abrir(historico.BANCO)
    d = diagnostico.diagnosticar(banco)
    pagina = _publicar_banco(banco, d)
    banco.con.close()
    _imprimir_diagnostico(d, [*diagnostico.gravar(d, SAIDA_RELATORIOS), *pagina])
    return 0


def cmd_painel_banco(_args) -> int:
    """Só a página do banco no site, sem regravar o diagnóstico em relatorios/."""
    from . import diagnostico, historico
    if not historico.BANCO.exists():
        print("Banco histórico não encontrado; rode `python -m onisciente historico`.", file=sys.stderr)
        return 1
    banco = historico.Banco.abrir(historico.BANCO)
    arquivos = _publicar_banco(banco, diagnostico.diagnosticar(banco))
    banco.con.close()
    for a in arquivos:
        print("->", Path(a).relative_to(RAIZ))
    return 0


def cmd_requisitos(args) -> int:
    """Reconta os 183 requisitos do projeto original a partir do registro."""
    from . import requisitos
    itens = requisitos.carregar()
    erros = requisitos.problemas(itens)
    c = requisitos.contar(itens)
    print(f"{c['percentual']}% do projeto original: {c['cumpridos']} cumpridos, {c['parciais']} parciais, "
          f"{c['ausentes']} ausentes, de {c['total']}.")
    for bloco, v in c["por_bloco"].items():
        print(f"  {bloco}: {v['percentual']}% ({v['cumpridos']}/{v['parciais']}/{v['ausentes']})")
    for e in erros:
        print("ERRO:", e, file=sys.stderr)
    return 1 if erros else 0


def cmd_selo(args) -> int:
    """Auditoria independente do selo de transparência: critério por critério, nota e confronto."""
    from .selo import avaliar, relatorio
    if args.sondar:
        from .selo import coleta
        lidas = coleta.coletar(args.fontes.split(",") if args.fontes else None)
        print(f"sondagem do selo: {sum(1 for x in lidas if x.get('ok'))} de {len(lidas)} páginas lidas")
    hoje = date.fromisoformat(args.hoje) if args.hoje else None
    aud = avaliar(Path(args.banco) if args.banco else relatorio.RAIZ / "dados" / "onisciente" / "historico.db",
                  hoje=hoje)
    for arq in relatorio.gravar(aud):
        print("gravado:", arq.relative_to(RAIZ))
    print(aud.veredito["frase"])
    for k, n in aud.notas.items():
        print(f"  {k}: {relatorio.pct(n.indice)} ({n.nivel})")
    erros = aud.matriz.problemas()
    for e in erros:
        print("ERRO na matriz:", e, file=sys.stderr)
    return 1 if erros else 0


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
    ph = sub.add_parser("historico", help="liga os motores de busca num intervalo de meses (rede)")
    ph.add_argument("--desde", required=True, help="AAAA-MM")
    ph.add_argument("--ate", required=True, help="AAAA-MM")
    ph.add_argument("--motores", help="lista separada por vírgula (padrão: todos)")
    ph.add_argument("--brutos", help="pasta para guardar as respostas cruas")
    ph.add_argument("--pausa", type=float, default=1.0, help="segundos entre chamadas")
    ph.add_argument("--somar", action="store_true",
                    help="refaz só os motores pedidos no banco existente, mantendo os outros")
    ph.set_defaults(f=cmd_historico)
    sub.add_parser("diagnostico", help="refaz o diagnóstico a partir do banco histórico") \
        .set_defaults(f=cmd_diagnostico)
    sub.add_parser("painel-banco", help="refaz só a página do banco histórico no site") \
        .set_defaults(f=cmd_painel_banco)
    sub.add_parser("requisitos", help="reconta os 183 requisitos do projeto original") \
        .set_defaults(f=cmd_requisitos)
    ps = sub.add_parser("selo", help="auditoria independente do selo de transparência (PNTP)")
    ps.add_argument("--sondar", action="store_true", help="lê antes as páginas das fontes e_* (rede)")
    ps.add_argument("--fontes", help="fontes e_* separadas por vírgula (padrão: todas)")
    ps.add_argument("--hoje", help="AAAA-MM-DD (padrão: hoje)")
    ps.add_argument("--banco", help="banco histórico (padrão: dados/onisciente/historico.db)")
    ps.set_defaults(f=cmd_selo)
    pe = sub.add_parser("empresas", help="confere as empresas contratadas (Receita, QSA, impedimentos)")
    pe.add_argument("--banco", help="caminho do banco (padrão: dados/onisciente/historico.db)")
    pe.add_argument("--saida", help="página a escrever (padrão: docs/onisciente/empresas.html)")
    pe.set_defaults(f=lambda a: __import__("onisciente.conferencias.empresas", fromlist=["cmd"]).cmd(a))
    from .telas.cli import registrar as registrar_telas
    registrar_telas(sub)
    args = p.parse_args(argv)
    return args.f(args)


if __name__ == "__main__":
    raise SystemExit(main())
