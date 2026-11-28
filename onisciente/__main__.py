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
    python -m onisciente rastreio             # verifica a cadeia de rodadas e o hash de cada registro
    python -m onisciente rastreio --hash 3fa2c1   # um registro pelo começo do hash, com a origem
    python -m onisciente rastreio --registro coletas:120   # o hash de uma linha e a sua origem
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
    if getattr(args, "releitura_completa", False):
        # Decisão do usuário de 28/11/2026 (P-01): a despesa coletada com o CPF mascarado pelo sistema volta a ser
        # lida da fonte, todos os meses, a partir de agora (rodada após rodada, até cada mês ter leitura nova).
        from . import partes
        from .coletores import goiania_transweb
        con = partes.conectar(historico.BANCO)
        print("releitura completa da despesa desde", goiania_transweb.marcar_releitura_completa(con))
        con.close()
    banco = historico.rodar(args.desde, args.ate, motores=motores,
                            brutos=Path(args.brutos) if args.brutos else None, pausa=args.pausa,
                            somar=args.somar)
    d = diagnostico.diagnosticar(banco)
    pagina = _publicar_banco(banco, d)
    banco.fechar()
    _imprimir_diagnostico(d, [*diagnostico.gravar(d, SAIDA_RELATORIOS), *pagina])
    return 0


def cmd_restaurar_fonte(args) -> int:
    import json
    import tempfile
    from . import historico, restauracao_fonte
    caminho = Path(args.banco) if args.banco else historico.BANCO
    if not caminho.exists():
        print(f"banco não encontrado: {caminho}", file=sys.stderr)
        return 1
    cache = Path(args.cache) if args.cache else Path(tempfile.mkdtemp(prefix="restaurar_fonte_"))
    r = restauracao_fonte.rodar(caminho, args.de, cache=cache, gravar=args.gravar, sondagem=args.sondagem)
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=1, sort_keys=True, default=str))
    else:
        print("versões lidas:", ", ".join(r["versoes"]),
              f"(cadeia diferente, ignoradas: {', '.join(r['versoes_com_outra_cadeia'])})"
              if r["versoes_com_outra_cadeia"] else "")
        for t, c in r["restauradas"].items():
            print(f"  {t}: {c['total']} linha(s) restaurada(s) (prova pelo hash: {c.get('hash', 0)}; pela linha antiga: "
                  f"{c.get('linha_antiga', 0)})")
        for t, c in r["reler"].items():
            print(f"  reler da fonte, {t}: {c}")
        if r["ambiguas"] or r["sem_prova"]:
            print("  ambíguas:", r["ambiguas"], "sem prova:", r["sem_prova"])
        f = r["folhas"]
        print(f"  folhas retiradas: {f['retiradas']}; provadas pela raiz (voltam): {f['provadas_pela_raiz']}; "
              f"sem prova: {f['sem_prova']}")
        if "aplicado" in r:
            print("  aplicado:", r["aplicado"], "verificação:", r["verificacao"])
        if "sondagem" in r:
            print("  sondagem:", len(r["sondagem"]["restaurados"]), "arquivo(s) de volta; sem original:",
                  r["sondagem"]["sem_original"])
        if not args.gravar:
            print("(só os números: rode com --gravar para aplicar)")
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
    amp = requisitos.carregar_ampliacao()
    if amp:
        erros += requisitos.problemas_ampliacao(amp)
        a = requisitos.contar(amp)
        print(f"{a['percentual']}% dos pedidos depois do projeto original: {a['cumpridos']} cumpridos, "
              f"{a['parciais']} parciais, {a['ausentes']} ausentes, de {a['total']}.")
        for bloco, v in a["por_bloco"].items():
            print(f"  {bloco}: {v['percentual']}% ({v['cumpridos']}/{v['parciais']}/{v['ausentes']})")
    for e in erros:
        print("ERRO:", e, file=sys.stderr)
    return 1 if erros else 0


def cmd_rastreio(args) -> int:
    """Verifica o rastreio por hash do banco (cadeia, raízes, registro a registro) ou mostra um registro."""
    from . import historico, rastreio
    caminho = Path(args.banco) if args.banco else historico.BANCO
    if not caminho.exists():
        print(f"Banco não encontrado: {caminho}", file=sys.stderr)
        return 1
    banco = historico.Banco.abrir(caminho)       # um banco anterior ao rastreio é migrado aqui
    try:
        con = banco.con
        if args.hash or args.registro:
            if args.registro:
                tabela, _, linha = args.registro.partition(":")
                achados = [rastreio.registro(con, tabela, int(linha))] if linha.isdigit() else []
                achados = [a for a in achados if a]
            else:
                achados = rastreio.localizar(con, args.hash)
            if args.json:
                print(json.dumps(achados, ensure_ascii=False, indent=1, default=str))
            for a in achados:
                _imprimir_registro(a)
            if not achados:
                print("Nenhum registro com esse hash ou nessa linha.")
            return 0 if achados else 1
        v = rastreio.verificar(con)
        if args.json:
            print(json.dumps(v, ensure_ascii=False, indent=1, default=str))
        else:
            _imprimir_verificacao(v)
        return 0 if v["integro"] else 1
    finally:
        banco.con.commit()
        banco.con.close()


def _imprimir_registro(a: dict) -> None:
    print(f"Registro {a['tabela']}" + (f", linha {a['linha']}" if a.get("linha") is not None else ", linha não está "
                                         "mais no banco"))
    print(f"  hash do registro: {a['hash']}")
    campos = a.get("campos") or {}
    if campos:
        print("  campos: " + "; ".join(f"{k}={str(v)[:60]}" for k, v in campos.items() if v not in (None, ""))[:400])
    if a["tabela"] == "coletas" and campos:
        print(f"  é a própria coleta: sha256 da resposta {campos.get('sha256') or 'SEM RESPOSTA'}; "
              f"hash da requisição {campos.get('requisicao') or 'anterior ao rastreio'}")
    selo = a.get("selo")
    if not selo:
        print("  SEM SELO: o conteúdo atual não confere com nenhum registro selado (alterado ou incluído fora de "
              "rodada).")
        return
    r = selo["rodada"]
    print(f"  selado na rodada {r.get('id')} ({r.get('modo')}, {r.get('inicio')} a {r.get('fim')}), "
          f"hash da rodada {r.get('hash')}")
    if selo.get("descartada_na_rodada"):
        print(f"  descartado na rodada {selo['descartada_na_rodada']} (refeito ou substituído)")
    for x in selo.get("substituiu_retirados") or []:
        print(f"  substituiu um selo da rodada {x['rodada']} retirado pela rodada {x['retirada_por']}: {x['motivo']}")
    o = selo["origem"]
    if o.get("resposta"):
        print(f"  origem: coleta {o.get('motor') or ''} {o.get('alvo') or ''} em {o.get('quando') or '?'}")
        print(f"    url: {o.get('url') or '?'}")
        print(f"    sha256 da resposta: {o['resposta']}")
        print(f"    hash da requisição: {o.get('requisicao') or 'anterior ao rastreio'}")
        print(f"    hash da linha da coleta: {o['coleta']}")
    if o.get("situacao"):
        print(f"  origem: {o['situacao']}")


def _imprimir_verificacao(v: dict) -> None:
    c = v["cadeia"]
    u = c.get("ultima") or {}
    print(f"Rastreio por hash: {c['rodadas']} rodada(s) na cadeia ({c['herdadas']} herdada(s) de bancos anteriores).")
    if u:
        print(f"  última rodada {u['id']} ({u.get('modo')}, {u.get('inicio')} a {u.get('fim')}): "
              f"{u.get('respostas')} respostas e {u.get('registros')} registros novos")
        print(f"  hash da rodada (topo da cadeia): {u.get('hash')}")
        print(f"  raiz de Merkle da rodada:        {u.get('raiz')}")
    print("  cadeia: " + ("confere" if c["ok"] else "NÃO CONFERE"))
    ret = c.get("retiradas") or {}
    if ret.get("total"):
        print(f"  folhas retiradas por privacidade: {ret['total']} (o hash saiu, ficou a marca; a raiz da tabela "
              "que perdeu folhas vale pelo hash da rodada)")
        for rid, d in (ret.get("por_rodada_que_retirou") or {}).items():
            tabelas = ", ".join(f"{t} {n}" for t, n in (d.get("por_tabela") or {}).items())
            print(f"    retiradas pela rodada {rid}: {d.get('total')} ({tabelas})")
            for motivo, n in (d.get("motivos") or {}).items():
                print(f"      {n}: {motivo}")
        perdas = "; ".join(f"rodada {r}: " + ", ".join(f"{t} {n}" for t, n in tabs.items())
                           for r, tabs in (ret.get("por_rodada_do_selo") or {}).items())
        print(f"    rodadas que perderam folhas: {perdas}")
    for p in c["problemas"]:
        print(f"    rodada {p['rodada']}: {p['motivo']}" + (f" (tabelas: {', '.join(p['tabelas'])})"
                                                          if p.get("tabelas") else ""))
    r = v.get("registros") or {}
    if r:
        print(f"  registros: {r['conferidos']} linhas conferidas em {r['tabelas']} tabelas; "
              f"{len(r['sem_selo'])} sem selo, {len(r['sumidos'])} selos sem a linha, {r['pendentes']} pendentes")
        for x in r["alteradas"][:20]:
            print(f"    ALTERADA: {x['tabela']} linha {x['linha']} (hash atual {x['hash'][:16]}; selo anterior "
                  f"{', '.join(h[:16] for h in x['selos_sem_linha'])})")
        alteradas = {(x["tabela"], x["linha"]) for x in r["alteradas"]}
        for x in [x for x in r["sem_selo"] if (x["tabela"], x["linha"]) not in alteradas][:20]:
            print(f"    sem selo: {x['tabela']} linha {x['linha']} {x['campos']}")
        for x in r["sumidos"][:20]:
            print(f"    selo sem linha: {x['tabela']} {x['hash'][:16]} (rodada {x['rodada']})")
    resp = v["respostas"]
    print(f"  respostas sem impressão: {len(resp['novas'])}"
          + (f" (e {resp['anteriores']} anteriores ao rastreio, sem bytes guardados para refazer)"
             if resp["anteriores"] else ""))
    for x in resp["novas"][:20]:
        print(f"    {x['motor']} {x['alvo']} {x['url']}")
    print("Íntegro." if v["integro"] else "ALTERAÇÃO OU FALHA DE RASTREIO ENCONTRADA.")


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
    ph.add_argument("--releitura-completa", action="store_true",
                    help="relê da fonte todos os meses da despesa de Goiânia (execucao_goiania), os que faltam "
                         "primeiro, até cada mês ter uma leitura inteira nova (decisão de 28/11/2026, P-01)")
    ph.set_defaults(f=cmd_historico)
    pf = sub.add_parser("restaurar-fonte", help="devolve o dado da fonte que o sistema mascarou (decisão P-01), "
                                                "com prova pelo rastreio antigo")
    pf.add_argument("--de", default="07e130c", help="a última versão do banco antes da máscara (padrão: 07e130c); "
                                                    "entram ela e as seguintes que mudaram dados/onisciente")
    pf.add_argument("--banco", help="caminho do banco (padrão: dados/onisciente/historico.db)")
    pf.add_argument("--cache", help="pasta para as versões extraídas do git (padrão: uma pasta temporária)")
    pf.add_argument("--gravar", action="store_true", help="aplica no banco (sem isso, só mostra os números)")
    pf.add_argument("--sondagem", action="store_true",
                    help="também os arquivos de relatorios/onisciente/sondagem que o sistema mascarou")
    pf.add_argument("--json", action="store_true", help="saída em JSON")
    pf.set_defaults(f=cmd_restaurar_fonte)
    psite = sub.add_parser("site", help="monta o site do Pages com o painel na página inicial")
    psite.add_argument("--saida", default="_site", help="pasta do site montado (padrão: _site)")
    psite.set_defaults(f=lambda a: __import__("onisciente.site", fromlist=["main"]).main(["--saida", a.saida]))
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
    pr = sub.add_parser("rastreio", help="verifica o rastreio por hash (cadeia de rodadas e cada registro)")
    pr.add_argument("--banco", help="caminho do banco (padrão: dados/onisciente/historico.db)")
    pr.add_argument("--hash", help="mostra o registro cujo hash começa assim, com a origem")
    pr.add_argument("--registro", help="TABELA:LINHA (rowid): o hash dessa linha e a origem")
    pr.add_argument("--json", action="store_true", help="saída em JSON")
    pr.set_defaults(f=cmd_rastreio)
    from .telas.cli import registrar as registrar_telas
    registrar_telas(sub)
    args = p.parse_args(argv)
    return args.f(args)


if __name__ == "__main__":
    raise SystemExit(main())
