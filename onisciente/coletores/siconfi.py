"""SICONFI: RREO e RGF declarados pelo próprio ente (segunda via dos pisos).

API pública do Tesouro Nacional. O coletor guarda os itens crus com a
impressão digital; a leitura de um percentual procura a linha pelo texto da
conta, porque os rótulos mudam entre exercícios. Se a linha não for achada, o
pisos fica sem segunda via e o parecer marca em vermelho.
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from urllib.parse import urlencode

from .. import RAIZ
from .base import Leitura, ler, registrar

API = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt/"
PASTA = RAIZ / "dados" / "onisciente" / "siconfi"


def url(demonstrativo: str, *, ente: int, exercicio: int, periodo: int, anexo: str) -> str:
    """Monta a consulta à API (``demonstrativo`` é ``rreo`` ou ``rgf``)."""
    demonstrativo = demonstrativo.lower()
    params = {
        "an_exercicio": exercicio,
        "nr_periodo": periodo,
        "id_ente": ente,
        "no_anexo": anexo,
    }
    if demonstrativo == "rreo":
        params["co_tipo_demonstrativo"] = "RREO"
    else:
        params.update(co_tipo_demonstrativo="RGF", in_periodicidade="Q", co_poder="E")
    return API + demonstrativo + "?" + urlencode(params)


def coletar(demonstrativo: str, *, ente: int, exercicio: int, periodo: int, anexo: str,
            ler_url=ler, pasta: Path = PASTA) -> Leitura:
    endereco = url(demonstrativo, ente=ente, exercicio=exercicio, periodo=periodo, anexo=anexo)
    leitura = ler_url(endereco, fonte="SICONFI")
    registrar(f"siconfi-{demonstrativo}", leitura)
    if leitura.ok:
        pasta.mkdir(parents=True, exist_ok=True)
        nome = f"{demonstrativo}_{exercicio}_{periodo}_{anexo.replace(' ', '_')}.json"
        dados = json.loads(leitura.texto)
        dados["_custodia"] = leitura.original.como_dict() if leitura.original else {}
        (pasta / nome).write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    return leitura


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    return " ".join(t.split())


def valor_da_conta(itens: list[dict], *palavras: str, coluna: str | None = None) -> float | None:
    """Primeiro valor cuja conta contém todas as palavras (sem acento, sem caixa)."""
    chaves = [_norm(p) for p in palavras]
    for item in itens:
        conta = _norm(str(item.get("conta", "")))
        if all(c in conta for c in chaves):
            if coluna and _norm(coluna) not in _norm(str(item.get("coluna", ""))):
                continue
            try:
                return float(item["valor"])
            except (KeyError, TypeError, ValueError):
                continue
    return None
