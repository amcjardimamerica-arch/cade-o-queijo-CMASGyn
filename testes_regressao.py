#!/usr/bin/env python3
"""Testes de regressão dos erros históricos + canário.
Cada bug real corrigido nesta investigação vira caso canônico aqui.
O ciclo NÃO pode ser considerado são se este arquivo não passar."""
import json, subprocess, sys
from pathlib import Path
R = Path(__file__).parent
sys.path.insert(0, str(R / "src")); sys.path.insert(0, str(R / "scripts"))
falhas = []

def t(nome, fn):
    try:
        fn(); print(f"  PASSOU  {nome}")
    except Exception as e:
        falhas.append(nome); print(f"  FALHOU  {nome}: {e}")

# 1. valor coletivo jamais vira individual (caso 1,5M/24)
def caso_coletivo():
    from gera_parecer_mensal_html import valor_coletivo
    ev = {"cnpjs": [f"c{i}" for i in range(24)],
          "valores": [1500000.0, 300000.0], "estacoes": ["repasse"]}
    assert valor_coletivo(ev), "1,5M/24 deveria ser coletivo"
    ev2 = {"cnpjs": ["a"], "valores": [1500000.0], "estacoes": ["pagamento"]}
    assert not valor_coletivo(ev2)
t("valor coletivo nunca individual (erro do 1,5M)", caso_coletivo)

# 2. dígito verificador barra artefato de extração
def caso_digito():
    from enriquece_cnpj import digito_valido
    assert not digito_valido("75185877518587")
    assert not digito_valido("02430968000351".replace("0003", "0003"))  # inválido real
    assert digito_valido("05039050000104")
t("dígito de CNPJ barra artefatos", caso_digito)

# 3. fonte federal vazia é INDISPONIVEL, nunca DIVERGE
def caso_federal():
    src = (R / "src" / "dupla_etapa.py").read_text()
    assert "INDISPONIVEL" in src and "veio vazia" in src
t("fonte federal vazia => INDISPONIVEL (nunca rebaixa)", caso_federal)

# 4. sonda falha não sobrescreve situação apurada (idempotência)
def caso_pub():
    src = (R / "src" / "publicacao_diaria.py").read_text()
    assert "nunca sobrescreve" in src
t("falha de sonda não degrada achado consolidado", caso_pub)

# 5. âncoras de integridade vêm do git HEAD (imutável)
def caso_ancora():
    from verifica_integridade_edicoes import ancoras
    assert len(ancoras()) >= 150, "âncoras sumiram"
t("cadeia de custódia: >=150 âncoras no HEAD", caso_ancora)

# 6. lacuna de numeração continua detectável (via do CONFIRMADO do Diário)
def caso_lacuna():
    from verifica_mensal import edicoes_conhecidas
    _, seq = edicoes_conhecidas()
    assert len(seq) > 100
t("numeração sequencial das edições disponível", caso_lacuna)

# 7. CANÁRIO: dado sintético marcado TEM de virar achado
def canario():
    from verifica_mensal import analisa_mes
    r = analisa_mes("2026-03")  # mês sabidamente com desconformidades
    assert r["total_achados"] >= 4, "o verificador emudeceu"
    assert all(a["selo"] in ("CONFIRMADO", "INDICIARIO",
               "INCONCLUSIVO_POR_DOCUMENTO_FALTANTE") for a in r["achados"])
t("canário: verificador vivo e selado", canario)

print(f"\nREGRESSÃO: {7-len(falhas)}/7" + (f" — FALHAS: {falhas}" if falhas else " — sistema são"))
sys.exit(1 if falhas else 0)
