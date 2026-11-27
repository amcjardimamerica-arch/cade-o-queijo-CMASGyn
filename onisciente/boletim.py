"""Boletim de uma coleta em andamento: o que cada fonte respondeu desde o início da rodada.

Lê o banco enquanto os motores ainda escrevem nele (só leitura) e devolve um Markdown curto,
que o fluxo do GitHub publica no ramo a cada 10 minutos. Assim os erros de uma rodada de
duas horas e meia aparecem enquanto ela corre, e não só no fim.

    python -m onisciente.boletim dados/onisciente/historico.db 2026-11-27T10:00:00+00:00
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

TABELAS = ("pncp_amparos", "pncp_contratos_detalhe", "pncp_termos", "pncp_itens",
           "pncp_cobrancas", "pncp_nf_itens", "precos_referencia")


def _fonte(url: str) -> str:
    partes = (url or "").split("://", 1)[-1].split("/")
    return "/".join(partes[:3]) if len(partes) > 2 and partes[1] == "api" else partes[0]


def _situacao(ok: int, http: int | None, erro: str | None) -> str:
    if ok:
        return "ok"
    erro = erro or ""
    if erro.startswith("não tentado"):
        return erro.split(":", 1)[-1].strip()[:70]
    if http == 404 and "nenhum" in erro.lower():
        return "sem registro (404 com \"nenhum\": lido)"
    if http:
        return f"HTTP {http}" + (f" ({erro.split(':', 1)[1].strip()[:60]})" if ":" in erro else "")
    return erro.split(":", 1)[0][:40] or "falha"


def boletim(caminho: str, desde: str) -> str:
    con = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True, timeout=30)
    linhas = con.execute("SELECT alvo, url, ok, http, erro, segundos, quando FROM coletas "
                         "WHERE quando >= ? ORDER BY rowid", (desde,)).fetchall()
    agora = datetime.now(timezone.utc).isoformat(timespec="minutes")
    saida = [f"# Coleta em andamento: boletim de {agora}", "",
             f"Desde {desde}: {len(linhas)} chamadas registradas."]
    if linhas:
        saida.append(f"Última chamada: {linhas[-1][6]} ({linhas[-1][0]}).")
    contagem: Counter = Counter()
    tempos: dict[str, list[float]] = defaultdict(list)
    for _alvo, url, ok, http, erro, segundos, _q in linhas:
        contagem[(_fonte(url), _situacao(ok, http, erro))] += 1
        if ok:
            tempos[_fonte(url)].append(segundos or 0.0)
    saida += ["", "## Por fonte", "", "| fonte | situação | chamadas |", "|---|---|---|"]
    for (fonte, situacao), n in sorted(contagem.items(), key=lambda x: (x[0][0], -x[1])):
        saida.append(f"| {fonte} | {situacao} | {n} |")
    saida += ["", "## Tempo das respostas boas (segundos)", "", "| fonte | n | mediana | p90 | máximo |",
              "|---|---|---|---|---|"]
    for fonte, lista in sorted(tempos.items()):
        lista.sort()
        saida.append(f"| {fonte} | {len(lista)} | {lista[len(lista) // 2]:.1f} | "
                     f"{lista[int(len(lista) * 0.9)]:.1f} | {lista[-1]:.1f} |")
    saida += ["", "## O que o banco tem agora", "", "| tabela | linhas |", "|---|---|"]
    for tabela in TABELAS:
        try:
            n = con.execute(f"SELECT COUNT(*) FROM {tabela}").fetchone()[0]
        except sqlite3.Error:
            n = "-"
        saida.append(f"| {tabela} | {n} |")
    guardado = con.execute("SELECT valor FROM meta WHERE chave = 'pncp_detalhe_lidos'").fetchone()
    if guardado:
        lidos = Counter(c.split()[0] + (" da compra" if c.startswith("itens da compra") else "")
                        for c in json.loads(guardado[0]))
        saida += ["", "## Lido por inteiro (acumulado)", ""]
        saida += [f"- {k}: {v}" for k, v in sorted(lidos.items())]
    con.close()
    return "\n".join(saida) + "\n"


if __name__ == "__main__":
    print(boletim(sys.argv[1], sys.argv[2]), end="")
