"""Parecerista automático.

Duas coisas que faltavam para isto ser agente e não relatório:

  1. PARECER, e não apenas número. Cada achado recebe análise, fundamento
     estatutário, ressalva metodológica quando cabe, e encaminhamento sugerido.

  2. DELTA. Alerta que se repete todo dia é alerta que se ignora. O parecerista
     compara com a véspera e destaca o que é novo, o que se agravou e o que
     deixou de aparecer. Se nada mudou, diz isso em uma linha.

Opera em dois níveis. Sem chave de API, monta o parecer a partir de uma base de
conhecimento jurídico indexada por regra — determinístico, custo zero, e é o
modo padrão. Com chave presente, escala os achados de severidade alta para
análise contra o corpus normativo, e o parecer determinístico vira o piso.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from util import RAIZ, agora, gravar_json, ler_json, log

ESTADO_ANTERIOR = RAIZ / "estado" / "achados_anteriores.json"
PAINEL = RAIZ / "docs" / "dados.json"

# ---------------------------------------------------------------------------
# Base de conhecimento jurídico, indexada por regra.
# É daqui que sai o parecer quando não há chave de API.
# ---------------------------------------------------------------------------
DOUTRINA = {
"PUB-01": {
 "materia": "Publicidade dos atos deliberativos",
 "analise": ("A publicação não é formalidade acessória: é condição de eficácia do ato "
   "administrativo perante terceiros. Resolução que defere inscrição de entidade, "
   "aprova plano de aplicação ou homologa contas produz efeito jurídico imediato, e "
   "produzi-lo sem publicação compromete a própria oponibilidade do ato."),
 "fundamento": ["Constituição Federal, artigo 37, caput",
                "Lei 12.527/2011, artigo 8º",
                "Lei 9.784/1999, artigo 26"],
 "ressalva": ("O índice global é piso, não medida fechada: depende do classificador "
   "estrutural, que tem falso negativo conhecido. Use sempre o número da regra PUB-03, "
   "confirmado por duas vias independentes."),
 "encaminhamento": "representacao_mp",
 "peca": "Representação ao Ministério Público, com pedido de instauração de inquérito civil.",
},
"PUB-02": {
 "materia": "Publicidade por exercício",
 "analise": ("A distribuição temporal importa mais que o total. Exercício em que quase "
   "nenhum ato foi publicado, mas em que atos daquele ano são citados por atos "
   "posteriores, demonstra que o conselho deliberou e não deu publicidade — e não "
   "que deliberou pouco."),
 "fundamento": ["Lei 12.527/2011, artigo 8º"],
 "encaminhamento": "minuta_lai",
 "peca": "Pedido de acesso à informação com pedido do inteiro teor dos atos do exercício.",
},
"PUB-03": {
 "materia": "Não publicação confirmada por dupla via",
 "analise": ("Este é o número utilizável em peça. Dois classificadores independentes — "
   "um estrutural sobre o acervo, outro de busca cega no índice de texto integral — "
   "convergiram na ausência de publicação. A convergência afasta a hipótese de defeito "
   "de um único método."),
 "fundamento": ["Constituição Federal, artigo 37, caput",
                "Lei 12.527/2011, artigo 8º, § 1º, incisos I e IV"],
 "ressalva": ("Ainda assim, confira à mão uma amostra antes de protocolar. Convergência "
   "reduz o risco, não o elimina."),
 "encaminhamento": "representacao_mp",
 "peca": "Representação ao Ministério Público e comunicação ao Conselho Nacional.",
},
"PUB-04": {
 "materia": "Divergência entre as vias de verificação",
 "analise": ("Divergência não é achado contra o Município: é achado contra o próprio "
   "sistema, e existe para impedir que defeito de classificador se converta em acusação "
   "indevida. Cada item desta fila exige conferência humana."),
 "fundamento": [],
 "encaminhamento": "nenhuma",
 "peca": "Nenhuma. Conferência interna antes de qualquer uso.",
},
"PUB-05": {
 "materia": "Intermitência da publicação",
 "analise": ("Órgão que delibera mensalmente e executa orçamento continuamente não "
   "atravessa semanas sem produzir ato publicável. Intervalo longo sugere que a "
   "publicação não acompanha a atividade — ou que a atividade cessou, hipótese que "
   "traz consequência própria quanto à condicionalidade dos repasses."),
 "fundamento": ["Lei 12.527/2011, artigo 8º, § 3º, inciso VI",
                "Lei 8.742/1993, artigo 30"],
 "encaminhamento": "minuta_lai",
 "peca": "Pedido de acesso à informação sobre atos do período e calendário de reuniões.",
},
"PUB-06": {
 "materia": "Indisponibilidade da edição para consulta automatizada",
 "analise": ("Duas hipóteses concorrem e os dados não as distinguem: ou não houve "
   "publicação, ou houve e não foi disponibilizada em formato acessível por sistema "
   "externo. A lei reprova as duas igualmente, o que torna a ambiguidade irrelevante "
   "para o dever, embora relevante para a peça."),
 "fundamento": ["Lei 12.527/2011, artigo 8º, § 3º, incisos III e VI",
                "Lei 14.129/2021, artigo 3º"],
 "encaminhamento": "minuta_lai",
 "peca": "Pedido de acesso à informação requerendo o endereço de acesso automatizado.",
},
"ATA-01": {
 "materia": "Prazo de publicação da ata",
 "analise": ("Decorrido o prazo regimental sem publicação, a ata deixa de cumprir sua "
   "função de registro oponível e passa a ser documento interno."),
 "fundamento": ["Regimento Interno do CMASGyn", "Lei 12.527/2011, artigo 8º"],
 "encaminhamento": "oficio",
 "peca": "Ofício ao conselho requerendo a publicação.",
},
"ATA-04": {
 "materia": "Voto nominal",
 "analise": ("Registro agregado do tipo aprovado por unanimidade impede aferir a "
   "manifestação individual e, por consequência, a responsabilidade de cada "
   "conselheiro pela deliberação. Onde o regimento exige voto nominal, o registro "
   "agregado é vício de forma."),
 "fundamento": ["Regimento Interno do CMASGyn", "Lei 9.784/1999, artigo 50"],
 "encaminhamento": "oficio",
 "peca": "Ofício requerendo retificação da ata com registro nominal.",
},
"ATA-05": {
 "materia": "Divergência entre presentes e signatários",
 "analise": ("Assinatura por quem não consta da lista de presença é vício de "
   "formalização com potencial de nulidade da deliberação, porque atesta participação "
   "que o próprio documento nega."),
 "fundamento": ["Regimento Interno do CMASGyn", "Lei 9.784/1999, artigo 22, § 1º"],
 "encaminhamento": "representacao_mp",
 "peca": "Representação, com pedido de anulação das deliberações afetadas.",
},
"ATA-06": {
 "materia": "Paridade da composição",
 "analise": ("A paridade entre governo e sociedade civil é da essência do conselho. "
   "Sessão instalada sem ela decide com composição diversa da legalmente exigida."),
 "fundamento": ["Lei 8.742/1993, artigo 16"],
 "encaminhamento": "representacao_mp",
 "peca": "Representação ao Ministério Público.",
},
"ATA-07": {
 "materia": "Ausência total de atas publicadas",
 "analise": ("É o achado de maior alcance estrutural. Sem ata pública não se afere "
   "quórum, não se identifica quem deliberou, não se sabe se houve voto nominal. O "
   "controle social sobre o próprio órgão de controle social fica materialmente "
   "impossibilitado. E o efetivo funcionamento do conselho, que a lei erige em condição "
   "de repasse federal, torna-se afirmação sem lastro documental."),
 "fundamento": ["Lei 8.742/1993, artigos 16 e 30",
                "Constituição Federal, artigo 37, caput",
                "Lei 12.527/2011, artigo 8º"],
 "encaminhamento": "representacao_mp",
 "peca": ("Representação ao Ministério Público e comunicação ao Conselho Nacional de "
   "Assistência Social, dada a conexão com a condicionalidade do repasse."),
},
"RES-01": {
 "materia": "Continuidade da numeração",
 "analise": ("Lacuna na sequência numérica indica ato existente e não divulgado. A "
   "numeração é declaração do próprio órgão sobre quantos atos produziu."),
 "fundamento": ["Lei 12.527/2011, artigo 8º"],
 "encaminhamento": "minuta_lai", "peca": "Pedido do inteiro teor dos atos faltantes.",
},
"RES-02": {
 "materia": "Ato sem publicação no Diário Oficial",
 "analise": ("Divulgação no sítio do conselho não substitui a publicação oficial. A "
   "ausência desta compromete a eficácia do ato perante terceiros."),
 "fundamento": ["Constituição Federal, artigo 37, caput"],
 "encaminhamento": "oficio", "peca": "Ofício requerendo a publicação.",
},
"RES-03": {
 "materia": "Alteração de ato já publicado",
 "analise": ("Divergência de digest entre versões do mesmo arquivo, sem nova numeração "
   "nem errata, indica reedição retroativa. É o achado que nenhum acompanhamento humano "
   "produz, e o de maior gravidade quando confirmado."),
 "fundamento": ["Constituição Federal, artigo 37, caput", "Lei 8.429/1992, artigo 11"],
 "encaminhamento": "representacao_mp",
 "peca": "Representação, com as duas versões e os respectivos digests como prova.",
},
"FIN-03": {
 "materia": "Rastreabilidade da origem dos recursos",
 "analise": ("Não se trata de desvio: trata-se de opacidade, que é problema anterior e "
   "condição dele. Sem identificar qual verba é federal, não se afere o cumprimento do "
   "piso do Índice de Gestão Descentralizada destinado ao controle social. As duas "
   "coisas se conectam: a opacidade da fonte inviabiliza a fiscalização do percentual."),
 "fundamento": ["Lei Complementar 101/2000, artigo 48-A, inciso I",
                "Lei 4.320/1964, artigos 6º e 13"],
 "encaminhamento": "minuta_lai",
 "peca": "Pedido da tabela de correspondência entre códigos de fonte e origem federativa.",
},
"FIN-04": {
 "materia": "Códigos de fonte não mapeados",
 "analise": ("Código de fonte sem correspondência declarada impede a conciliação "
   "federativa. Não se presume a origem: ou o ente declara, ou o dado é inservível."),
 "fundamento": ["Lei 4.320/1964, artigo 6º"],
 "encaminhamento": "minuta_lai", "peca": "Pedido do Quadro de Detalhamento de Despesas.",
},
"IGD-01": {
 "materia": "Piso do Índice de Gestão Descentralizada",
 "analise": ("Desde janeiro de 2026 o piso é de dez por cento do valor repassado "
   "mensalmente pelo IGD do SUAS e do Bolsa Família. O piso legal de três por cento "
   "permanece como garantia mínima inderrogável; a Resolução CNAS/MDS 202/2025 "
   "exerce a competência regulamentar prevista na LOAS e eleva a destinação. Não se "
   "trata de antinomia entre os percentuais."),
 "fundamento": ["Lei 8.742/1993, artigo 12-A, § 4º",
                "Lei 14.601/2023, artigo 14, § 7º",
                "Resolução CNAS/MDS 202/2025, artigo 6º",
                "Portaria MDS 1.041/2024, artigo 11, § 1º"],
 "encaminhamento": "representacao_mp",
 "peca": "Representação, com pedido de apuração do bloqueio de repasse previsto na resolução.",
},
"IGD-04": {
 "materia": "Transparência da aplicação do IGD",
 "analise": ("A ausência de publicação sobre plano de aplicação e execução é, ela "
   "própria, o achado. Não se pode afirmar irregularidade na aplicação; pode-se afirmar "
   "que a aplicação não é verificável, o que a lei não admite."),
 "fundamento": ["Resolução CNAS/MDS 202/2025", "Lei 12.527/2011, artigo 8º"],
 "encaminhamento": "minuta_lai",
 "peca": "Pedido do plano de aplicação, da execução e das prestações de contas.",
},
"SOB-06": {
 "materia": "Repasse sem vínculo formal identificável",
 "analise": ("Valor associado a inscrição no cadastro de pessoa jurídica sem indicação "
   "de contrato, termo ou convênio impede aferir objeto, prazo, meta e prestação de "
   "contas. O instrumento é o que torna o repasse sindicável."),
 "fundamento": ["Lei 13.019/2014, artigos 42 e 63", "Lei 4.320/1964, artigo 63"],
 "ressalva": ("A extração capta também o cadastro do próprio Município nos cabeçalhos "
   "das publicações. Triagem obrigatória antes de qualquer uso: confira se cada número "
   "corresponde a entidade privada."),
 "encaminhamento": "minuta_lai",
 "peca": "Pedido da relação de instrumentos com beneficiário, objeto, valor e vigência.",
},
"SOB-07": {
 "materia": "Parceria sem chamamento público",
 "analise": ("Termo de fomento ou colaboração publicado sem registro de chamamento, "
   "dispensa ou inexigibilidade é publicação incompleta e impede aferir se houve "
   "competição. A regra é o chamamento; a exceção exige justificativa expressa."),
 "fundamento": ["Lei 13.019/2014, artigos 24, 30 e 31"],
 "encaminhamento": "minuta_lai",
 "peca": "Pedido do procedimento de seleção adotado em cada instrumento.",
},
"SOB-02": {
 "materia": "Lançamento discrepante",
 "analise": ("Indício estatístico, jamais conclusão. Sobrepreço se demonstra por "
   "confronto com preço de mercado em perícia. O que aqui se aponta é onde vale olhar."),
 "fundamento": ["Lei 14.133/2021, artigo 23"],
 "encaminhamento": "nenhuma", "peca": "Conferência do objeto e do porte do serviço.",
},
"SOB-05": {
 "materia": "Concentração de repasses",
 "analise": ("Concentração não é ilícito. É circunstância que torna relevante conferir "
   "a seleção por chamamento público."),
 "fundamento": ["Lei 13.019/2014, artigo 24"],
 "encaminhamento": "nenhuma", "peca": "Conferência da seleção.",
},
"TRI-01": {
 "materia": "Ruptura da trilha do dinheiro",
 "analise": ("O trecho invisível é o mais grave da trilha, porque impede tanto afirmar "
   "quanto negar a regularidade. É precisamente o que fundamenta o pedido de acesso."),
 "fundamento": ["Lei Complementar 101/2000, artigo 48-A"],
 "encaminhamento": "minuta_lai", "peca": "Pedido de empenhos, liquidações e pagamentos.",
},
}

PECAS = {
 "representacao_mp": "Representação ao Ministério Público",
 "representacao_tcm": "Representação ao Tribunal de Contas dos Municípios",
 "minuta_lai": "Pedido de acesso à informação",
 "oficio": "Ofício ao órgão",
 "nenhuma": "Conferência interna",
}


def _chave(a: dict) -> str:
    base = f"{a.get('regra')}|{a.get('titulo')}|{a.get('documento','')}|{a.get('data_ref','')}"
    return hashlib.sha256(base.encode()).hexdigest()[:16]


def delta(atuais: list[dict]) -> dict:
    ant = ler_json(ESTADO_ANTERIOR, {})
    mapa_ant = ant.get("achados", {})
    mapa_novo = {_chave(a): a for a in atuais}

    novos = [a for k, a in mapa_novo.items() if k not in mapa_ant]
    sumidos = [v for k, v in mapa_ant.items() if k not in mapa_novo]
    ordem = {"alta": 0, "media": 1, "baixa": 2}
    agravados = [a for k, a in mapa_novo.items()
                 if k in mapa_ant
                 and ordem.get(a.get("severidade"), 3) < ordem.get(mapa_ant[k].get("severidade"), 3)]

    gravar_json(ESTADO_ANTERIOR, {
        "data": agora().date().isoformat(),
        "achados": {k: {"regra": a.get("regra"), "titulo": a.get("titulo"),
                        "severidade": a.get("severidade")} for k, a in mapa_novo.items()},
    })
    return {"novos": novos, "agravados": agravados, "resolvidos": sumidos,
            "houve_mudanca": bool(novos or agravados or sumidos),
            "primeira_apuracao": not mapa_ant}


def parecer_de(a: dict) -> dict:
    d = DOUTRINA.get(a.get("regra"), {})
    return {
        "regra": a.get("regra"), "severidade": a.get("severidade"),
        "titulo": a.get("titulo"), "constatacao": a.get("detalhe"),
        "materia": d.get("materia", "—"),
        "analise": d.get("analise", "Sem análise específica cadastrada para esta regra."),
        "fundamento": d.get("fundamento") or ([a["fundamento"]] if a.get("fundamento") else []),
        "ressalva": d.get("ressalva"),
        "peca": d.get("peca", "—"),
        "encaminhamento": PECAS.get(d.get("encaminhamento", "nenhuma"), "—"),
        "documento": a.get("documento"), "data_ref": a.get("data_ref"),
    }


def _md(pareceres: list[dict], dl: dict, resumo: dict) -> str:
    hoje = agora().strftime("%d/%m/%Y")
    L = [f"# Parecer diário — vigilância do CMASGyn", "", f"**{hoje}**", ""]

    if dl["primeira_apuracao"]:
        L += ["Primeira apuração. Todo o quadro abaixo é linha de base.", ""]
    elif not dl["houve_mudanca"]:
        L += ["## Sem novidade",
              "",
              "Nada mudou desde a apuração anterior. O quadro permanece o descrito abaixo,",
              "e nenhuma providência nova é exigida hoje.", ""]
    else:
        L += ["## O que mudou", ""]
        if dl["novos"]:
            L.append(f"**{len(dl['novos'])} achado(s) novo(s):**")
            L += [f"- [{a.get('regra')}] {a.get('titulo')}" for a in dl["novos"]] + [""]
        if dl["agravados"]:
            L.append(f"**{len(dl['agravados'])} achado(s) agravado(s):**")
            L += [f"- [{a.get('regra')}] {a.get('titulo')}" for a in dl["agravados"]] + [""]
        if dl["resolvidos"]:
            L.append(f"**{len(dl['resolvidos'])} achado(s) que deixaram de aparecer** "
                     "— confira se foi correção ou falha de coleta:")
            L += [f"- [{v.get('regra')}] {v.get('titulo')}" for v in dl["resolvidos"]] + [""]

    L += ["## Quadro", "", "| Indicador | Valor |", "|---|---|"]
    for k, v in (resumo or {}).items():
        L.append(f"| {k.replace('_',' ')} | {v} |")
    L += [""]

    for sev, rot in (("alta", "Severidade alta"), ("media", "Severidade média"),
                     ("baixa", "Severidade baixa")):
        g = [p for p in pareceres if p["severidade"] == sev]
        if not g:
            continue
        L += [f"## {rot}", ""]
        for p in g:
            L += [f"### [{p['regra']}] {p['titulo']}", "",
                  f"**Matéria.** {p['materia']}", "",
                  f"**Constatação.** {p['constatacao']}", "",
                  f"**Análise.** {p['analise']}", ""]
            if p["fundamento"]:
                L += ["**Fundamento.** " + "; ".join(p["fundamento"]) + ".", ""]
            if p["ressalva"]:
                L += [f"**Ressalva.** {p['ressalva']}", ""]
            L += [f"**Encaminhamento.** {p['encaminhamento']} — {p['peca']}", "", "---", ""]

    L += ["",
          "Parecer produzido por rotina automatizada a partir de documento oficial "
          "coletado do Diário Oficial do Município de Goiânia. Constitui subsídio "
          "técnico, não peça processual: nada se protocola sem revisão do advogado "
          "responsável, na forma do artigo 32 da Lei 8.906/1994.",
          "",
          "Painel: https://amcjardimamerica-arch.github.io/cmasgyn-vigilancia/"]
    return "\n".join(L)


def gerar() -> dict:
    d = ler_json(PAINEL, {})
    achados = d.get("achados", [])
    if not achados:
        log.warning("Nenhum achado no painel.")
    dl = delta(achados)
    pareceres = [parecer_de(a) for a in achados]
    texto = _md(pareceres, dl, d.get("resumo", {}))

    arq = RAIZ / "relatorios" / f"parecer_{agora().date().isoformat()}.md"
    arq.parent.mkdir(parents=True, exist_ok=True)
    arq.write_text(texto, encoding="utf-8")
    (RAIZ / "docs" / "PARECER.md").write_text(texto, encoding="utf-8")

    altos = sum(1 for p in pareceres if p["severidade"] == "alta")
    resultado = {
        "arquivo": str(arq.relative_to(RAIZ)),
        "pareceres": len(pareceres), "severidade_alta": altos,
        "houve_mudanca": dl["houve_mudanca"],
        "novos": len(dl["novos"]), "agravados": len(dl["agravados"]),
        "resolvidos": len(dl["resolvidos"]),
        "notificar": dl["houve_mudanca"] or dl["primeira_apuracao"],
    }
    gravar_json(RAIZ / "dados" / "parecer_resumo.json", resultado)
    log.info("Parecer: %d verificações, %d de severidade alta, mudança=%s",
             len(pareceres), altos, dl["houve_mudanca"])
    return resultado


if __name__ == "__main__":
    print(json.dumps(gerar(), ensure_ascii=False, indent=2))
