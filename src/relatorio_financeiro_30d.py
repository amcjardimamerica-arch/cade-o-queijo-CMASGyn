"""Fechamento financeiro independente em janelas de 30 dias corridos."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from util import ESTADO, RAIZ, RELATORIOS, agora, gravar_json, ler_json

MOVIMENTOS = RAIZ / "dados" / "movimentacao_contas.json"
CONTROLE = ESTADO / "relatorio_financeiro_30d.json"


def filtrar_periodo(registros: list[dict], inicio: date, fim: date) -> list[dict]:
    saida = []
    for r in registros:
        try:
            d = date.fromisoformat(str(r.get("data", ""))[:10])
        except ValueError:
            continue
        if inicio <= d <= fim:
            saida.append(r)
    return saida


def vencido(fim: date, controle: dict) -> bool:
    ultima = controle.get("ultima_data_final")
    if not ultima:
        return True
    try:
        return fim >= date.fromisoformat(ultima) + timedelta(days=30)
    except ValueError:
        return True


def _cobertura(entradas: list[dict], saidas: list[dict], mov: dict) -> float:
    presentes = 0
    exigidos = 2  # saldo inicial e saldo final
    presentes += int(mov.get("saldo_inicial") is not None)
    presentes += int(mov.get("saldo_final") is not None)
    for r in entradas:
        for campo in ("data", "valor", "fonte_recurso", "url"):
            exigidos += 1
            presentes += int(r.get(campo) not in (None, ""))
    for r in saidas:
        for campo in ("data", "valor", "destino_recurso", "url"):
            exigidos += 1
            presentes += int(r.get(campo) not in (None, ""))
    return round(100 * presentes / max(exigidos, 1), 2)


def gerar(fim: date | None = None, somente_se_vencido: bool = False) -> dict | None:
    fim = fim or agora().date()
    controle = ler_json(CONTROLE, {})
    if somente_se_vencido and not vencido(fim, controle):
        return None
    inicio = fim - timedelta(days=29)
    mov = ler_json(MOVIMENTOS, {})
    entradas = filtrar_periodo(mov.get("entradas") or [], inicio, fim)
    saidas = filtrar_periodo(mov.get("saidas") or [], inicio, fim)

    faltantes: list[str] = []
    if mov.get("saldo_inicial") is None or mov.get("saldo_final") is None:
        faltantes.append("extratos com saldo inicial e saldo final de todas as contas do FMAS")
    if not entradas and not saidas:
        faltantes.append("extratos e comprovantes bancários do período")
    if any(not r.get("fonte_recurso") for r in entradas):
        faltantes.append("identificação da fonte das entradas sem classificação")
    if any(not r.get("destino_recurso") for r in saidas):
        faltantes.append("identificação do destino das saídas sem classificação")
    faltantes += [
        "cadeia documental de empenho, liquidação e pagamento por saída",
        "contratos, parcerias, notas fiscais, atestes e deliberações aplicáveis",
    ]
    faltantes = list(dict.fromkeys(faltantes))

    dados = {
        "tipo": "fiscalizacao_financeira_30_dias",
        "periodo_inicial": inicio.isoformat(),
        "periodo_final": fim.isoformat(),
        "gerado_em": agora().isoformat(),
        "orgao": "SEMASDH/FMAS",
        "entrada_de_valores_em_conta_da_semasdh_fmas": round(
            sum(float(r.get("valor") or 0) for r in entradas), 2),
        "saida_de_valores_da_conta_da_semasdh_fmas": round(
            sum(float(r.get("valor") or 0) for r in saidas), 2),
        "entradas": entradas,
        "saidas": saidas,
        "fontes_nao_identificadas": sum(not r.get("fonte_recurso") for r in entradas),
        "destinos_nao_identificados": sum(not r.get("destino_recurso") for r in saidas),
        "saldo_inicial": mov.get("saldo_inicial"),
        "saldo_final": mov.get("saldo_final"),
        "conciliacao_demonstrada": False,
        "cobertura_documental_percentual": _cobertura(entradas, saidas, mov),
        "resultado_de_conformidade": "INCONCLUSIVO_POR_DOCUMENTO_FALTANTE",
        "documentos_faltantes": faltantes,
        "privacidade": (
            "Pessoa física aparece somente pelo primeiro nome; CPF, sobrenomes, "
            "endereço e dados bancários são suprimidos."
        ),
    }
    nome = f"financeiro_30d_{fim.isoformat()}"
    gravar_json(RELATORIOS / f"{nome}.json", dados)
    (RELATORIOS / f"{nome}.md").write_text(markdown(dados), encoding="utf-8")
    gravar_json(CONTROLE, {"ultima_data_final": fim.isoformat(), "ultimo_relatorio": nome})
    return dados


def _brl(v) -> str:
    return ("R$ " + f"{float(v or 0):,.2f}").replace(",", "@").replace(".", ",").replace("@", ".")


def _campo(v) -> str:
    return str(v or "não identificado").replace("|", "/").replace("\n", " ")


def markdown(d: dict) -> str:
    l = [
        f"# Relatório financeiro de 30 dias — {d['periodo_inicial']} a {d['periodo_final']}", "",
        f"**Resultado:** {d['resultado_de_conformidade']}", "",
        f"**Cobertura documental:** {d['cobertura_documental_percentual']}%", "",
        "## Entrada de valores em conta da SEMASDH/FMAS", "",
        "| Data | Valor | Fonte do recurso | Prova |", "|---|---:|---|---|",
    ]
    for r in d["entradas"]:
        l.append(f"| {_campo(r.get('data'))} | {_brl(r.get('valor'))} | "
                 f"{_campo(r.get('fonte_recurso'))} | {_campo(r.get('url'))} |")
    if not d["entradas"]:
        l.append("| — | — | não demonstrada no acervo | — |")
    l += ["", "## Saída de valores da conta da SEMASDH/FMAS", "",
          "| Data | Valor | Destino do recurso | Prova |", "|---|---:|---|---|"]
    for r in d["saidas"]:
        l.append(f"| {_campo(r.get('data'))} | {_brl(r.get('valor'))} | "
                 f"{_campo(r.get('destino_recurso'))} | {_campo(r.get('url'))} |")
    if not d["saidas"]:
        l.append("| — | — | não demonstrada no acervo | — |")
    l += ["", "## Conciliação", "",
          f"- Saldo inicial: {_brl(d.get('saldo_inicial')) if d.get('saldo_inicial') is not None else 'não demonstrado'}",
          f"- Entradas: {_brl(d['entrada_de_valores_em_conta_da_semasdh_fmas'])}",
          f"- Saídas: {_brl(d['saida_de_valores_da_conta_da_semasdh_fmas'])}",
          f"- Saldo final: {_brl(d.get('saldo_final')) if d.get('saldo_final') is not None else 'não demonstrado'}",
          "", "## Documentos faltantes", ""]
    l += [f"- {x}" for x in d["documentos_faltantes"]]
    l += ["", f"> {d['privacidade']}", ""]
    return "\n".join(l)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--fim", help="Data final no formato AAAA-MM-DD")
    p.add_argument("--somente-se-vencido", action="store_true")
    args = p.parse_args()
    fim = date.fromisoformat(args.fim) if args.fim else None
    resultado = gerar(fim, args.somente_se_vencido)
    print(json.dumps(resultado or {"situacao": "AINDA_NAO_VENCIDO"}, ensure_ascii=False, indent=2))
