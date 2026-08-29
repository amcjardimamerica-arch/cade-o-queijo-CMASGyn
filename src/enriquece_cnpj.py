#!/usr/bin/env python3
"""Enriquecimento cirúrgico de cadastro de pessoa jurídica.

Alvo: apenas os CNPJs citados na trilha do dinheiro que ainda não têm
razão social em dados/destinatarios_2026.json. Nada além disso — a busca
é pontual, com cache persistente em estado/cnpj.json, e integralmente
determinística: nenhum token de modelo é gasto aqui (camada 0 do roteador,
tarefas normalizar_cnpj e validar_digito_cnpj).

Fonte: dados abertos do CNPJ da Receita Federal do Brasil, servidos pelos
redistribuidores públicos BrasilAPI e minhareceita (a mesma dupla já usada
por src/destinatarios.py). O sítio de consulta direta da Receita exige
captcha e não é automatizável; os dados são os mesmos, da base oficial.

Regras:
  - dígito verificador inválido não vai à rede: é registrado como artefato
    de extração, para correção na origem (regra: corrigir o script que
    gera, não o resultado);
  - pessoa jurídica mantém razão social e inscrição completas;
  - respeita o limite dos serviços com pausa entre consultas.

Saída: dados/cadastro_cnpj_complementar.json
Uso:   python3 src/enriquece_cnpj.py [--limite N]
"""
from __future__ import annotations
import json, re, sys, time
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DADOS = RAIZ / "dados"
sys.path.insert(0, str(RAIZ / "src"))
from destinatarios import consultar  # reutiliza a consulta com cache
from util import ler_json


def normalizar(c: str) -> str:
    return re.sub(r"\D", "", c or "")


def digito_valido(c: str) -> bool:
    n = normalizar(c)
    if len(n) != 14 or n == n[0] * 14:
        return False
    for tam in (12, 13):
        pesos = list(range(2, 10)) * 2
        soma = sum(int(d) * p for d, p in zip(reversed(n[:tam]), pesos))
        dv = 11 - soma % 11
        if (0 if dv > 9 else dv) != int(n[tam]):
            return False
    return True


def fmt(n: str) -> str:
    return f"{n[:2]}.{n[2:5]}.{n[5:8]}/{n[8:12]}-{n[12:]}"


def faltantes() -> tuple[list[str], list[str]]:
    trilha = ler_json(DADOS / "trilha_dinheiro.json", {})
    dest = ler_json(DADOS / "destinatarios_2026.json", {})
    tem = {normalizar(d["cnpj"]) for d in dest.get("destinatarios", [])
           if d.get("razao_social") and d.get("qsa") is not None}
    compl = ler_json(DADOS / "cadastro_cnpj_complementar.json", {})
    # backfill: quem tem razão social mas ainda não tem QSA volta à fila
    tem |= {normalizar(k) for k, v in compl.get("cadastros", {}).items()
            if v.get("razao_social") and v.get("qsa") is not None}
    citados = {c for e in trilha.get("detalhe", [])
               for c in (e.get("cnpjs") or [])}
    validos, artefatos = [], []
    for c in sorted(citados):
        n = normalizar(c)
        (validos if digito_valido(n) else artefatos).append(c)
    alvo = sorted({normalizar(c) for c in validos} - tem)
    return alvo, sorted(set(artefatos))


def main():
    limite = None
    if "--limite" in sys.argv:
        limite = int(sys.argv[sys.argv.index("--limite") + 1])
    alvo, artefatos = faltantes()
    destino = DADOS / "cadastro_cnpj_complementar.json"
    atual = ler_json(destino, {"cadastros": {}, "artefatos_de_extracao": []})
    print(f"  alvo cirúrgico: {len(alvo)} CNPJs sem cadastro"
          f"{f' (limitado a {limite})' if limite else ''}"
          f" | artefatos de extração: {len(artefatos)}")
    cache_path = RAIZ / "estado" / "cnpj.json"
    cache = ler_json(cache_path, {})
    ok = falha = 0
    for n in alvo[:limite]:
        c = consultar(n, cache)
        if c and c.get("razao_social"):
            qsa = [{"nome": s.get("nome_socio") or s.get("nome"),
                    "qualificacao": s.get("qualificacao_socio")
                    or s.get("codigo_qualificacao_socio")}
                   for s in (c.get("qsa") or []) if isinstance(s, dict)]
            atual["cadastros"][fmt(n)] = {
                **c, "qsa": qsa, "fonte": ("dados abertos do CNPJ — Receita Federal, via "
                               "BrasilAPI/minhareceita"),
                "consultado_em": date.today().isoformat()}
            ok += 1
        else:
            falha += 1
        time.sleep(1.2)  # respeito ao limite dos serviços
    atual["artefatos_de_extracao"] = [
        {"texto_extraido": a,
         "motivo": "dígito verificador inválido — artefato do extrator; "
                   "corrigir em src/extracao.py, não no dado"}
        for a in artefatos]
    atual["gerado_em"] = date.today().isoformat()
    atual["nota"] = ("Complemento cirúrgico: só CNPJs citados na trilha sem "
                     "razão social no cadastro principal. Zero tokens de IA.")
    cache_path.parent.mkdir(exist_ok=True)
    cache_path.write_text(json.dumps(cache, ensure_ascii=False),
                          encoding="utf-8")
    destino.write_text(json.dumps(atual, ensure_ascii=False, indent=1),
                       encoding="utf-8")
    print(f"  consultados: {ok} com sucesso, {falha} sem resposta | "
          f"acumulado no complementar: {len(atual['cadastros'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
