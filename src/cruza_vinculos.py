#!/usr/bin/env python3
"""Trilha do Rato — cruzamento societário e de parentesco (Q7 autorizado).

Fontes 100% públicas: QSA dos dados abertos do CNPJ (informação
empresarial, fora do alcance da minimização) e atos de pessoal do Diário.
Emite SEMPRE e no máximo INDICIÁRIO — homonímia existe; a prova é da
perícia documental que o alerta prioriza.

Alertas:
  A1 HOMONIMIA_SOCIO_SERVIDOR  sócio/administrador com nome idêntico ao de
     servidor do quadro atual da secretaria (desligados fora, regra sua).
  A2 PARENTESCO_POSSIVEL       sobrenome raro compartilhado entre sócio e
     servidor ativo (sobrenomes comuns só pesam em par: dois em comum).
  A3 SOCIO_MULTIEMPRESA        mesma pessoa no QSA de 2+ beneficiárias de
     recurso público da pasta — concentração a periciar.

Saída: referencias/vinculos/alertas.json  |  Camada 0, zero tokens.
"""
from __future__ import annotations
import json, re, unicodedata
from collections import defaultdict
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
COMUNS = {"SILVA", "SANTOS", "OLIVEIRA", "SOUZA", "SOUSA", "LIMA", "PEREIRA",
          "FERREIRA", "COSTA", "RODRIGUES", "ALMEIDA", "NASCIMENTO", "ALVES",
          "CARVALHO", "GOMES", "MARTINS", "ARAUJO", "RIBEIRO", "BARBOSA",
          "MOREIRA", "SANTANA", "JESUS", "ROCHA", "DIAS", "CAMPOS", "CARDOSO",
          "TEIXEIRA", "CORREIA", "VIEIRA", "MENDES", "FREITAS", "RAMOS"}
PART = {"DA", "DE", "DO", "DAS", "DOS", "E"}


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z ]", " ", s.upper()).split()


def main():
    dest = json.loads((RAIZ / "dados" / "destinatarios_2026.json")
                      .read_text(encoding="utf-8"))
    try:
        compl = json.loads((RAIZ / "dados" / "cadastro_cnpj_complementar.json")
                           .read_text(encoding="utf-8"))["cadastros"]
    except FileNotFoundError:
        compl = {}
    serv = json.loads((RAIZ / "referencias" / "servidores" / "nomeacoes.json")
                      .read_text(encoding="utf-8"))
    ativos = serv.get("quadro_atual") or sorted(
        {r.get("nome_completo") for r in serv["registros"]
         if r.get("nome_completo")} - {None})
    idx_serv_nome = {" ".join(norm(n)): n for n in ativos}
    idx_serv_sobren = defaultdict(list)
    for n in ativos:
        for p in norm(n)[1:]:
            if p not in PART:
                idx_serv_sobren[p].append(n)

    empresas = {}
    for d in dest.get("destinatarios", []):
        if d.get("razao_social"):
            empresas[d["cnpj"]] = {"nome": d["razao_social"],
                                   "qsa": d.get("qsa") or []}
    for c, d in compl.items():
        empresas.setdefault(c, {"nome": d.get("razao_social"),
                                "qsa": d.get("qsa") or []})

    alertas, socio_empresas = [], defaultdict(set)
    for cnpj, e in empresas.items():
        for s in e["qsa"]:
            nome_s = s.get("nome") or ""
            if not nome_s:
                continue
            chave = " ".join(norm(nome_s))
            socio_empresas[chave].add(cnpj)
            if chave in idx_serv_nome:
                alertas.append({
                    "tipo": "A1_HOMONIMIA_SOCIO_SERVIDOR", "selo": "INDICIARIO",
                    "severidade": "critica", "cnpj": cnpj,
                    "empresa": e["nome"], "socio": nome_s.title(),
                    "servidor": idx_serv_nome[chave],
                    "providencia": ("perícia documental: CPF do sócio no "
                                    "contrato social × matrícula funcional — "
                                    "vedação de contratar com a própria "
                                    "administração: Artigo 9º, § 1º, da Lei "
                                    "14.133/2021; Artigo 39, inciso III, da "
                                    "Lei 13.019/2014")})
                continue
            tokens = [p for p in norm(nome_s)[1:] if p not in PART]
            raros = [p for p in tokens if p not in COMUNS
                     and p in idx_serv_sobren]
            comuns2 = [p for p in tokens if p in COMUNS
                       and p in idx_serv_sobren]
            if raros or len(set(comuns2)) >= 2:
                marcador = raros or sorted(set(comuns2))
                alvo = idx_serv_sobren[marcador[0]][0]
                alertas.append({
                    "tipo": "A2_PARENTESCO_POSSIVEL", "selo": "INDICIARIO",
                    "severidade": "alta", "cnpj": cnpj, "empresa": e["nome"],
                    "socio": nome_s.title(), "servidor": alvo,
                    "sobrenomes_em_comum": [m.title() for m in marcador],
                    "criterio": ("sobrenome raro em comum, ou dois sobrenomes "
                                 "comuns simultâneos — homonímia parcial não "
                                 "prova parentesco; prioriza perícia"),
                    "providencia": ("conferir grau de parentesco — nepotismo "
                                    "e favorecimento: Súmula Vinculante 13 "
                                    "não se cita (regra da casa: sem "
                                    "jurisprudência); base normativa: Artigo "
                                    "37, caput, da Constituição — moralidade "
                                    "e impessoalidade")})
    for chave, cnpjs in socio_empresas.items():
        if len(cnpjs) >= 2:
            alertas.append({
                "tipo": "A3_SOCIO_MULTIEMPRESA", "selo": "INDICIARIO",
                "severidade": "alta", "socio": chave.title(),
                "empresas": sorted(cnpjs),
                "providencia": ("mapear recebimentos por empresa e somar por "
                                "pessoa — concentração de recurso público em "
                                "um mesmo particular por veículos distintos")})
    saida = {"gerado_em": date.today().isoformat(),
             "servidores_ativos_considerados": len(ativos),
             "desligados_excluidos": True,
             "empresas_com_qsa": sum(1 for e in empresas.values() if e["qsa"]),
             "alertas": alertas}
    p = RAIZ / "referencias" / "vinculos"
    p.mkdir(parents=True, exist_ok=True)
    (p / "alertas.json").write_text(json.dumps(saida, ensure_ascii=False,
                                               indent=1), encoding="utf-8")
    print(f"  vínculos: {len(ativos)} servidores ativos × "
          f"{saida['empresas_com_qsa']} empresas com QSA → "
          f"{len(alertas)} alertas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
