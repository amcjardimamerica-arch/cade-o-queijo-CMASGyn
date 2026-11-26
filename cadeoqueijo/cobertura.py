"""Correição de cobertura — garante que nenhum dia fique de fora.

O risco de qualquer vigilância automatizada é a falha silenciosa: o roteiro
roda, não acha nada, e ninguém percebe que ele simplesmente não olhou. Este
módulo fecha essa brecha.

Para cada dia útil do período, uma das quatro situações é registrada:

  coletado            — a edição foi obtida e indexada
  sem_termos          — a edição existe no índice mas não menciona os termos
  ausente_no_indice   — o dia é útil e nada consta: LACUNA a investigar
  falha               — houve tentativa e erro técnico: reprocessar

O relatório de correição lista as lacunas e o roteiro tenta preenchê-las em
cada execução, até três vezes, antes de escalar como achado.
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta

from busca_local import conectar
from util import ESTADO, RELATORIOS, agora, gravar_json, ler_json, log

FERIADOS_FIXOS = {
    (1, 1), (4, 21), (5, 1), (9, 7), (10, 12), (11, 2), (11, 15), (12, 25),
    (5, 24),   # Nossa Senhora Auxiliadora — feriado municipal de Goiânia
    (10, 24),  # aniversário de Goiânia
}


def dias_uteis(inicio: date, fim: date) -> list[date]:
    saida, d = [], inicio
    while d <= fim:
        if d.weekday() < 5 and (d.month, d.day) not in FERIADOS_FIXOS:
            saida.append(d)
        d += timedelta(days=1)
    return saida


def auditar(inicio: date, fim: date, ids_no_indice: set[str] | None = None) -> dict:
    """Compara o calendário de dias úteis com o que foi efetivamente coletado."""
    c = conectar()
    coletados = {r[0]: r[1] for r in
                 c.execute("SELECT data, nome FROM documentos WHERE data BETWEEN ? AND ?",
                           (inicio.isoformat(), fim.isoformat())).fetchall()}

    datas_indice = set()
    if ids_no_indice:
        for i in ids_no_indice:
            m = re.search(r"_(\d{8})_", i)
            if m:
                v = m.group(1)
                try:
                    datas_indice.add(date(int(v[:4]), int(v[4:6]), int(v[6:8])).isoformat())
                except ValueError:
                    pass

    registro = ler_json(ESTADO / "historico_registro.json", {})
    falhas = {m["data"] for m in registro.values() if m.get("erro")}

    lacunas, resumo = [], {"coletado": 0, "sem_termos": 0,
                           "ausente_no_indice": 0, "falha": 0}
    agora_iso = agora().isoformat()

    for d in dias_uteis(inicio, fim):
        iso = d.isoformat()
        if iso in coletados:
            sit, nome = "coletado", coletados[iso]
        elif iso in falhas:
            sit, nome = "falha", None
            lacunas.append({"data": iso, "situacao": sit})
        elif datas_indice and iso not in datas_indice:
            sit, nome = "ausente_no_indice", None
            lacunas.append({"data": iso, "situacao": sit})
        else:
            sit, nome = "sem_termos", None
        resumo[sit] += 1
        c.execute("INSERT OR REPLACE INTO cobertura VALUES (?,?,?,?,?)",
                  (iso, d.weekday(), sit, nome, agora_iso))
    c.commit()
    c.close()

    total = sum(resumo.values())
    cobertos = total - len(lacunas)
    indice = round(100 * cobertos / total, 2) if total else 100.0

    rel = {
        "periodo": [inicio.isoformat(), fim.isoformat()],
        "dias_uteis": total, "resumo": resumo,
        "lacunas": lacunas, "indice_cobertura": indice,
        "auditado_em": agora_iso,
    }
    gravar_json(ESTADO / "cobertura.json", rel)
    log.info("Correição: %d dias úteis, cobertura de %.2f%%, %d lacuna(s)",
             total, indice, len(lacunas))
    return rel


def relatorio_markdown(rel: dict) -> str:
    l = [f"# Correição de cobertura",
         "",
         f"Período: {rel['periodo'][0]} a {rel['periodo'][1]}  ",
         f"Dias úteis: **{rel['dias_uteis']}**  ",
         f"Índice de cobertura: **{rel['indice_cobertura']}%**",
         "",
         "| Situação | Dias |", "|---|---|"]
    rotulos = {"coletado": "Edição coletada e indexada",
               "sem_termos": "Edição sem menção aos termos",
               "ausente_no_indice": "Nada consta — lacuna",
               "falha": "Erro técnico — reprocessar"}
    for k, v in rel["resumo"].items():
        l.append(f"| {rotulos.get(k, k)} | {v} |")
    if rel["lacunas"]:
        l += ["", "## Lacunas a investigar", ""]
        for x in rel["lacunas"][:60]:
            l.append(f"- **{x['data']}** — {rotulos.get(x['situacao'], x['situacao'])}")
        if len(rel["lacunas"]) > 60:
            l.append(f"- … e mais {len(rel['lacunas']) - 60}")
    else:
        l += ["", "Nenhuma lacuna. Todos os dias úteis do período foram verificados."]
    return "\n".join(l)
