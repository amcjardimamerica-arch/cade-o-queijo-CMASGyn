"""Matriz de Saldos Contábeis (MSC) do SICONFI: a receita e a despesa do mês por fonte e por função.

A MSC é a matriz que o Município envia todo mês ao Tesouro, conta a conta do plano de contas (PCASP),
com as informações complementares: fonte de recursos, função e subfunção, natureza da receita e da
despesa. É outra entrega, homologada em separado do RREO: por isso serve de segunda via das espécies
de receita, e é a única fonte pública que diz em que função cada fonte foi empenhada.

Guarda-se a classe 6 (execução do orçamento), movimento do mês (``period_change``):

* 6.2.1.2 receita realizada (crédito) e 6.2.1.3 deduções da receita (débito);
* 6.2.2.1.3 crédito empenhado: .01 a liquidar, .02 em liquidação, .03 liquidado a pagar, .04 pago;
* 6.2.2.1.1 crédito disponível; 6.3 restos a pagar.
"""

from __future__ import annotations

import json

API = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt/"
LIMITE = 5000

CAMPOS = ("conta_contabil", "poder_orgao", "ano_fonte_recursos", "fonte_recursos", "funcao", "subfuncao",
          "natureza_receita", "natureza_despesa", "ano_inscricao", "educacao_saude", "natureza_conta", "valor")


def url(ibge: str | int, mes: str, *, classe: int = 6, offset: int = 0) -> str:
    """``mes`` em AAAA-MM; a matriz de agregação (MSCC), movimento do mês."""
    return (f"{API}msc_orcamentaria?id_ente={ibge}&an_referencia={mes[:4]}&me_referencia={int(mes[5:7])}"
            f"&co_tipo_matriz=MSCC&classe_conta={classe}&id_tv=period_change"
            + (f"&offset={offset}" if offset else ""))


def pagina(conteudo: bytes) -> tuple[list[dict], bool]:
    """Os itens da página e se há mais. Levanta ``ValueError`` se a resposta não é a esperada."""
    try:
        dados = json.loads(conteudo.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise ValueError(f"não é JSON: {e}") from e
    if not isinstance(dados, dict) or "items" not in dados:
        raise ValueError("a resposta não traz 'items'")
    itens = []
    for it in dados["items"]:
        faltam = [c for c in ("conta_contabil", "natureza_conta", "valor") if c not in it]
        if faltam:
            raise ValueError(f"o item não traz {', '.join(faltam)}")
        itens.append({c: it.get(c) for c in CAMPOS})
    return itens, bool(dados.get("hasMore"))
