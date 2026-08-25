"""Gera docs/CONSULTA.md — o arquivo que se lê numa conversa com o Claude.

Os arquivos de dados somam centenas de milhares de bytes, grandes demais para
caber confortavelmente numa conversa. Este roteiro destila tudo num único
documento compacto, com os números, os achados e os ponteiros para o detalhe.
É ele que se busca quando se quer analisar o acervo fora do painel.
"""
from __future__ import annotations
import json, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from util import RAIZ, agora, ler_json

BRUTO = "https://raw.githubusercontent.com/amcjardimamerica-arch/cmasgyn-vigilancia/main"

def brl(v):
    return ("R$ " + f"{v or 0:,.2f}").replace(",", "@").replace(".", ",").replace("@", ".")

def gerar() -> str:
    D = RAIZ / "dados"
    d = ler_json(RAIZ / "docs" / "dados.json", {})
    b, f = d.get("biblioteca", {}), d.get("financeiro", {})
    m = d.get("movimentacao_contas", {})
    t, v = d.get("trilha", {}), d.get("verificacao", {})
    s = (d.get("semaforo") or {}).get("resumo", {})
    r = d.get("resumo", {})
    ach = d.get("achados", [])

    L = [f"# Consulta — vigilância do CMASGyn",
         "", f"Gerado em {agora().strftime('%d/%m/%Y às %H:%M')} UTC. Documento destilado para",
         "leitura em conversa. Os dados completos estão nos arquivos indicados ao final.",
         "", "## Números",
         "", "| Indicador | Valor |", "|---|---|",
         f"| Edições do Diário Oficial no acervo | {r.get('edicoes',0)} |",
         f"| Caracteres indexados | {r.get('caracteres',0):,} |".replace(",", "."),
         f"| Atos do conselho identificados | {b.get('total_atos',0)} |",
         f"| Atos com inteiro teor publicado | {(b.get('situacoes') or {}).get('PUBLICADO',0)} |",
         f"| Atos apenas citados | {(b.get('situacoes') or {}).get('APENAS_CITADO',0)} |",
         f"| Atos presumidos por lacuna | {(b.get('situacoes') or {}).get('PRESUMIDO',0)} |",
         f"| Atas de plenária publicadas | {r.get('atas',0)} |",
         f"| Valor rastreado na função 08 | {brl(f.get('valor_total'))} |",
         f"| Destinado a entidade privada | {brl(f.get('para_entidades_privadas'))} |",
         f"| Rastreabilidade da origem | {f.get('indice_rastreabilidade',0)}% |",
         f"| Entidades identificadas | {t.get('entidades_identificadas',0)} |",
         f"| Vínculos formais localizados | {len(t.get('contratos_localizados') or [])} |",
         "", "## Verificação dupla", "",
         f"- Atos examinados por duas vias independentes: **{v.get('atos_verificados',0)}**",
         f"- Não publicados confirmados pelas duas vias: **{v.get('nao_publicados_confirmados',0)}**",
         f"- Divergentes, pendentes de conferência humana: **{len(v.get('fila_de_conferencia_humana') or [])}**",
         f"- Concordância entre as vias: **{v.get('concordancia',0)}%**", "",
         "> Use o número confirmado pelas duas vias em qualquer peça. O índice de",
         "> publicidade global é piso, não medida fechada.",
         "", "## Movimentação da conta da SEMASDH/FMAS", "",
         f"**Situação:** {m.get('status') or 'NÃO APURADA'}", "",
         m.get('nota_metodologica') or (
             "Dotação orçamentária não comprova entrada ou saída bancária. "
             "Sem extrato ou pagamento identificável, a movimentação fica como não demonstrada."
         ), "",
         "### Entrada de valores em conta da SEMASDH", "",
         "| Data | Valor | Indicação da fonte do recurso | Prova |", "|---|---:|---|---|",]

    if m.get("entradas"):
        for x in m["entradas"]:
            L.append(f"| {x.get('data','—')} | {brl(x.get('valor'))} | "
                     f"{x.get('fonte_recurso') or 'não identificada'} | "
                     f"[edição/página]({x.get('url')}) |")
    else:
        L.append("| — | — | não demonstrada no acervo | — |")

    L += ["", "### Saída de valores da conta da SEMASDH", "",
          "| Data | Valor | Indicação do destino do recurso | Tipo | Prova |",
          "|---|---:|---|---|---|"]
    if m.get("saidas"):
        for x in m["saidas"]:
            L.append(f"| {x.get('data','—')} | {brl(x.get('valor'))} | "
                     f"{x.get('destino_recurso') or 'não identificado'} | "
                     f"{x.get('tipo_destino','—')} | [edição/página]({x.get('url')}) |")
    else:
        L.append("| — | — | não demonstrada no acervo | — | — |")

    L += ["", "> Quando o beneficiário da saída é pessoa física, o relatório conserva",
          "> somente o primeiro nome. CPF e demais nomes não são publicados.",
         "", "## Semáforo diário", "",
         f"- Última publicação da pasta: **{s.get('ultima_publicacao') or '—'}**",
         f"- Dias desde então: **{s.get('dias_desde_ultima')}**",
         f"- Dias úteis sem edição disponível: **{s.get('inexistentes',0)}** de {s.get('dias_uteis',0)}",
         "", "## Achados", ""]

    for sev in ("alta", "media", "baixa"):
        grupo = [a for a in ach if a.get("severidade") == sev]
        if not grupo:
            continue
        L += [f"### Severidade {sev}", ""]
        for a in grupo:
            L += [f"**[{a.get('regra','—')}] {a.get('titulo')}**", "",
                  (a.get("detalhe") or "").strip(), ""]
            if a.get("fundamento"):
                L += [f"*Fundamento:* {a['fundamento']}", ""]

    L += ["## Trilha do dinheiro — estações", "", "| Estação | Publicações |", "|---|---|"]
    rot = {"repasse": "1 Repasse da União e do Estado", "orcamento": "2 Dotação",
           "credito": "3 Créditos e remanejamentos", "deliberacao": "4 Deliberação do conselho",
           "vinculo": "5 Contrato ou termo", "empenho": "6 Empenho e pagamento",
           "entidade": "7 Chegada à entidade"}
    for k, n in (t.get("cobertura_das_estacoes") or {}).items():
        L.append(f"| {rot.get(k,k)} | {n} |")

    L += ["", "### Maiores valores associados a inscrição no cadastro de pessoa jurídica", "",
          "| CNPJ | Lançamentos | Valor associado | Vínculo |", "|---|---|---|---|"]
    for e in (t.get("entidades") or [])[:12]:
        L.append(f"| {e['cnpj']} | {e['lancamentos']} | {brl(e['valor'])} | "
                 f"{(e['contratos'][0] if e['contratos'] else 'ausente')} |")
    L += ["", f"> {t.get('nota_metodologica','')}",
          "> Confira sempre se o número inscrito corresponde a entidade privada: a",
          "> extração capta também o cadastro do próprio Município nos cabeçalhos.", ""]

    L += ["## Arquivos completos", "",
          "| Conteúdo | Endereço |", "|---|---|",
          f"| Painel | https://amcjardimamerica-arch.github.io/cmasgyn-vigilancia/ |",
          f"| Todos os dados | {BRUTO}/docs/dados.json |",
          f"| Biblioteca de atos | {BRUTO}/dados/biblioteca_cmasgyn.json |",
          f"| Verificação dupla | {BRUTO}/dados/verificacao_dupla.json |",
          f"| Conciliação financeira | {BRUTO}/dados/financeiro.json |",
          f"| Movimentação da conta SEMASDH/FMAS | {BRUTO}/dados/movimentacao_contas.json |",
          f"| Trilha do dinheiro | {BRUTO}/dados/trilha_dinheiro.json |",
          f"| Semáforo diário | {BRUTO}/dados/publicacao_diaria.json |",
          f"| Registro das edições | {BRUTO}/estado/historico_registro.json |",
          f"| Trechos com proveniência | {BRUTO}/acervo/trechos/assistencia_social.jsonl.gz |", ""]
    return "\n".join(L)


if __name__ == "__main__":
    txt = gerar()
    (RAIZ / "docs" / "CONSULTA.md").write_text(txt, encoding="utf-8")
    print(f"docs/CONSULTA.md: {len(txt)} caracteres")
