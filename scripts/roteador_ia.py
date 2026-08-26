#!/usr/bin/env python3
"""Roteamento de modelo por tarefa.

Princípio: o modelo mais barato que resolve a tarefa com qualidade aceitável.
Tarefa determinística não vai para IA nenhuma — vai para código.

Escada de custo (por milhão de tokens de entrada/saída, ordem de grandeza):
  código puro   custo zero
  Haiku 4.5     ~1x
  Sonnet 4.6    ~3x
  Opus 4.6      ~15x

Regra de ouro: nunca mandar para o modelo o que pode ser decidido por regex,
comparação numérica ou consulta a tabela. A IA entra onde há juízo.
"""
import os, json, re, sys
import urllib.request

API = "https://api.anthropic.com/v1/messages"
CHAVE = os.environ.get("ANTHROPIC_API_KEY")

MODELOS = {
    "haiku":  "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-6",
    "opus":   "claude-opus-4-6",
}

# ---------------------------------------------------------------------------
# CAMADA 0 — código, sem IA. Cobre a maior parte do volume.
# ---------------------------------------------------------------------------
SEM_IA = {
    "extrair_valor_monetario", "validar_digito_cnpj", "somar_por_natureza",
    "comparar_com_teto_percentual", "detectar_lacuna_de_numeracao",
    "conferir_data_anterior_a_data", "calcular_10_por_cento_do_igd",
    "conciliar_receita_com_despesa", "detectar_fan_out", "normalizar_cnpj",
    "verificar_se_edicao_existe", "contar_dias_uteis", "aplicar_lista_negra",
    "primeiro_nome_apenas", "classificar_natureza_por_prefixo",
    "detectar_mencao_a_lei_revogada", "medir_gap_de_publicacao",
}

# ---------------------------------------------------------------------------
# CAMADA 1 — Haiku. Triagem, classificação, extração estruturada.
# Alto volume, juízo raso, resposta curta e verificável.
# ---------------------------------------------------------------------------
HAIKU = {
    "triar_relevancia_do_ato":
        "O ato é de assistência social ou é de outro domínio? Responda apenas SIM ou NAO.",
    "classificar_tipo_de_ato":
        "Classifique em: LICITACAO, CONTRATO, TERMO_FOMENTO, CONVENIO, ADITIVO, "
        "RESOLUCAO_CMAS, ATA, PORTARIA, DECRETO_CREDITO, NOMEACAO, OUTRO. Responda só o rótulo.",
    "extrair_partes_do_ato":
        "Extraia em JSON: {objeto, valor, credor, cnpj, instrumento, numero, vigencia, fundamento_legal}. "
        "Use null onde não houver. Sem comentário.",
    "identificar_dominio_estranho":
        "O texto trata de saúde, educação, meio ambiente ou cemitérios? Responda o domínio ou NENHUM.",
    "resumir_ementa":
        "Resuma o objeto em no máximo 20 palavras. Sem adjetivo.",
    "extrair_linha_de_folha":
        "Extraia {primeiro_nome, cargo, valor, vinculo}. Apenas o PRIMEIRO NOME da pessoa. JSON puro.",
}

# ---------------------------------------------------------------------------
# CAMADA 2 — Sonnet. Confronto com norma, parecer de ato individual.
# Volume médio, exige leitura de dispositivo e subsunção.
# ---------------------------------------------------------------------------
SONNET = {
    "parecer_de_ato_administrativo":
        "Analise cabimento, legitimação, procedimento e eficácia jurídica do ato, "
        "contra os dispositivos fornecidos. Selo CONFIRMADO ou INDICIÁRIO em cada afirmação.",
    "conferir_chamamento_publico":
        "O ato demonstra chamamento público, dispensa ou inexigibilidade justificada, "
        "na forma dos artigos 24, 29, 30, 31 e 32 da Lei 13.019/2014?",
    "conferir_vinculo_de_pagamento":
        "Existe contrato, termo, convênio ou ata que justifique este pagamento?",
    "avaliar_motivacao":
        "O ato está motivado com fatos e fundamentos jurídicos, artigo 50 da Lei 9.784/1999?",
    "redigir_secao_de_relatorio":
        "Redija a seção do relatório semanal. Apenas desconformidades. Cite artigo e lei por extenso.",
}

# ---------------------------------------------------------------------------
# CAMADA 3 — Opus. Auditoria financeira e parecer jurídico consolidado.
# Volume baixo, uma vez por mês, juízo profundo e integração de muitas peças.
# ---------------------------------------------------------------------------
OPUS = {
    "auditoria_financeira_mensal":
        "Audite a competência: entradas por fonte, cruzamento com LOA e LDO, saídas por destino, "
        "destinações obrigatórias, gastos do CMASGyn individualizados. Apenas desconformidades.",
    "parecer_juridico_consolidado":
        "Emita parecer jurídico fundamentado sobre a competência, no papel de auditor de tribunal "
        "de contas e promotor de justiça. Cite artigo e lei por extenso.",
    "detectar_padrao_e_reincidencia":
        "Compare com as competências anteriores. O padrão se repete? Há agravamento?",
    "avaliar_antinomia_normativa":
        "Há conflito entre normas aplicáveis? Resolva por hierarquia, especialidade e cronologia.",
}

def rotear(tarefa: str) -> str | None:
    """Devolve a chave do modelo, ou None se a tarefa não deve ir para IA."""
    if tarefa in SEM_IA:  return None
    if tarefa in HAIKU:   return "haiku"
    if tarefa in SONNET:  return "sonnet"
    if tarefa in OPUS:    return "opus"
    raise KeyError(f"tarefa não roteada: {tarefa}")

# ---------------------------------------------------------------------------
# Economia estrutural
# ---------------------------------------------------------------------------
LIMITES = {
    "haiku":  {"max_tokens": 500,  "contexto_maximo": 8000},
    "sonnet": {"max_tokens": 2000, "contexto_maximo": 30000},
    "opus":   {"max_tokens": 8000, "contexto_maximo": 120000},
}

def recortar(texto: str, tarefa: str, ancoras: list[str] | None = None) -> str:
    """Nunca manda o documento inteiro. Recorta a vizinhança das âncoras.
    Um Diário Oficial tem 14 MB; o trecho relevante tem 2 KB."""
    modelo = rotear(tarefa)
    if modelo is None: return texto
    teto = LIMITES[modelo]["contexto_maximo"] * 4  # ~4 chars por token
    if not ancoras or len(texto) <= teto:
        return texto[:teto]
    pedacos, vistos = [], set()
    for a in ancoras:
        for m in re.finditer(re.escape(a), texto, re.I):
            i, j = max(0, m.start() - 600), m.start() + 1400
            if any(i < v < j for v in vistos): continue
            vistos.add(m.start()); pedacos.append(texto[i:j])
            if sum(len(p) for p in pedacos) > teto: break
        if sum(len(p) for p in pedacos) > teto: break
    return "\n[...]\n".join(pedacos)[:teto] or texto[:teto]

def chamar(tarefa: str, conteudo: str, sistema: str = "", ancoras=None) -> str | None:
    modelo = rotear(tarefa)
    if modelo is None:
        raise ValueError(f"'{tarefa}' é determinística. Resolva em código, não na IA.")
    if not CHAVE:
        print(f"[sem chave] {tarefa} iria para {modelo}", file=sys.stderr); return None
    instrucao = {**HAIKU, **SONNET, **OPUS}[tarefa]
    corpo = json.dumps({
        "model": MODELOS[modelo],
        "max_tokens": LIMITES[modelo]["max_tokens"],
        "system": sistema or instrucao,
        "messages": [{"role": "user", "content": recortar(conteudo, tarefa, ancoras)}],
    }).encode()
    req = urllib.request.Request(API, data=corpo, headers={
        "content-type": "application/json", "x-api-key": CHAVE,
        "anthropic-version": "2023-06-01"})
    with urllib.request.urlopen(req, timeout=180) as r:
        d = json.loads(r.read())
    return "".join(b.get("text", "") for b in d.get("content", []))

# ---------------------------------------------------------------------------
# Orçamento por ciclo
# ---------------------------------------------------------------------------
ORCAMENTO = {
    "semanal": {
        "haiku":  {"chamadas_esperadas": 120, "nota": "triagem e extração de cada ato da semana"},
        "sonnet": {"chamadas_esperadas": 15,  "nota": "parecer só dos atos que a triagem marcou relevantes"},
        "opus":   {"chamadas_esperadas": 0,   "nota": "não entra no ciclo semanal"},
    },
    "mensal": {
        "haiku":  {"chamadas_esperadas": 200, "nota": "extração de linhas de folha e de execução"},
        "sonnet": {"chamadas_esperadas": 30,  "nota": "conferência de vínculo por contrato"},
        "opus":   {"chamadas_esperadas": 3,   "nota": "auditoria, parecer e padrão — uma vez cada"},
    },
    "mensal_legal": {
        "haiku":  {"chamadas_esperadas": 20,  "nota": "só captura e catalogação; sem parecer"},
        "sonnet": {"chamadas_esperadas": 0},
        "opus":   {"chamadas_esperadas": 0},
    },
}

def relatorio_de_roteamento():
    return {
        "camada_0_sem_ia": sorted(SEM_IA),
        "camada_1_haiku": sorted(HAIKU),
        "camada_2_sonnet": sorted(SONNET),
        "camada_3_opus": sorted(OPUS),
        "total_tarefas": len(SEM_IA) + len(HAIKU) + len(SONNET) + len(OPUS),
        "proporcao_sem_ia": round(100 * len(SEM_IA) / (len(SEM_IA)+len(HAIKU)+len(SONNET)+len(OPUS)), 1),
        "orcamento_por_ciclo": ORCAMENTO,
        "principio": "Opus entra 3 vezes por mês. Haiku carrega o volume. "
                     "Metade das tarefas não vai para IA nenhuma.",
    }

if __name__ == "__main__":
    print(json.dumps(relatorio_de_roteamento(), ensure_ascii=False, indent=1))
