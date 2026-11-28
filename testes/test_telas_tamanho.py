"""Travas de 28/11/2026: a página da trilha passou de 48 MB quando a despesa inteira de Goiânia entrou
(24 mil empenhos, 155 mil eventos, cada evento com a sua prova). A tela mostra no máximo 200 empenhos por
recorte, então a página leva os de maior valor de cada recorte, com as estações somadas, e a contagem."""

from __future__ import annotations

from pathlib import Path

from onisciente.telas import dados

APP = Path(__file__).resolve().parent.parent / "docs" / "onisciente" / "app"
LIMITE = 16_000_000          # nenhuma página do painel acima de 16 MB


class _Originais:
    def __init__(self):
        self.chaves = []

    def externo(self, chave, *a, **k):
        self.chaves.append(chave)
        return chave


class _Ctx:
    def __init__(self):
        self.originais = _Originais()


def test_execucao_leva_os_maiores_de_cada_recorte_com_as_estacoes_somadas_e_a_contagem():
    empenhos = []
    for i in range(300):
        empenhos.append({"numero": f"E{i}", "data": "2026-02-03", "funcao": "08" if i % 3 else "10",
                         "valor": float(i), "url": "https://exemplo.gov.br/e",
                         "eventos": [{"estacao": "empenho", "data": "2026-02-03", "valor": float(i)},
                                     {"estacao": "pagamento", "data": "2026-02-10", "valor": 1.0},
                                     {"estacao": "pagamento", "data": "2026-02-09", "valor": 2.0}]})
    ctx = _Ctx()
    lista, total = dados._execucao_entrada(ctx, {"empenhos": empenhos})
    assert total == {"2026-02": {"*": 300, "08": 200, "10": 100}}
    n = dados.EMPENHOS_POR_RECORTE
    assert len(lista) <= 3 * n and len(lista) >= n
    numeros = {e["numero"] for e in lista}
    assert "E299" in numeros and "E0" not in numeros               # os de maior valor ficam
    assert len(ctx.originais.chaves) == len(lista)                  # uma prova por empenho, não por evento
    e = next(x for x in lista if x["numero"] == "E299")
    pago = next(ev for ev in e["eventos"] if ev["estacao"] == "pagamento")
    assert pago["valor"]["v"] == 3.0 and pago["data"] == "2026-02-09" and pago["documento"] == "2 registro(s)"


def test_nenhuma_pagina_do_painel_passa_de_16_mb():
    grandes = {p.name: p.stat().st_size for p in APP.glob("*") if p.is_file() and p.stat().st_size > LIMITE}
    assert not grandes, f"página grande demais: {grandes}"
