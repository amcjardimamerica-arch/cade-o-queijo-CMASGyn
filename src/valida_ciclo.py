#!/usr/bin/env python3
"""Contrato de ciclo: após cada workflow, os artefatos obrigatórios têm de
existir, ser JSON válido e conter os campos-chave. Mata a classe de falha
'o passo rodou e o resultado evaporou' (erro histórico nº 7)."""
import json, sys
from pathlib import Path
R = Path(__file__).resolve().parent.parent
CONTRATO = {
 "relatorios/segunda_etapa.json": ["sondado_em", "fontes", "caso_de_controle"],
 "relatorios/integridade_edicoes.json": ["verificado_em", "edicoes_ancoradas"],
 "relatorios/qualidade_fontes.json": ["criterio"],
 "dados/trilha_dinheiro.json": ["eventos", "detalhe"],
 "dados/receita_mensal_2026.json": ["competencias"],
 "referencias/servidores/nomeacoes.json": ["registros", "minimizacao"],
}
falhas = []
for arq, chaves in CONTRATO.items():
    p = R / arq
    if not p.exists():
        falhas.append(f"{arq}: AUSENTE"); continue
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        falhas.append(f"{arq}: JSON inválido ({e})"); continue
    for c in chaves:
        if c not in d:
            falhas.append(f"{arq}: sem campo '{c}'")
print(("CONTRATO DE CICLO: íntegro" if not falhas else
       "CONTRATO DE CICLO VIOLADO:\n  " + "\n  ".join(falhas)))
sys.exit(1 if falhas else 0)
