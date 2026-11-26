"""Base dos coletores.

Toda fonte é lida com impressão digital. Quando uma fonte muda de endereço ou
de formato, o coletor falha às claras: registra a falha no estado da coleta, e
o parecer marca em vermelho o trecho não alcançado. Se uma fonte ficar sem
coleta por mais dias que o mapa legal permite (3), isso aparece como falha do
próprio sistema, nunca como silêncio do município.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from .. import RAIZ, __version__
from ..nucleo.custodia import Original, impressao
from ..nucleo.indicios import Familia, Ficha, emitir

ESTADO = RAIZ / "estado" / "onisciente_coleta.json"
AGENTE = f"Onisciente/{__version__} (fiscalizacao civica; dados publicos)"


@dataclass
class Leitura:
    ok: bool
    url: str
    conteudo: bytes = b""
    erro: str = ""
    original: Original | None = None

    @property
    def texto(self) -> str:
        return self.conteudo.decode("utf-8", errors="replace")


def ler(url: str, *, tempo: int = 60, fonte: str = "") -> Leitura:
    """Lê uma URL pública. Nunca levanta exceção: devolve a falha descrita."""
    pedido = urllib.request.Request(url, headers={"User-Agent": AGENTE})
    try:
        with urllib.request.urlopen(pedido, timeout=tempo) as resposta:  # noqa: S310 (URL do mapa)
            conteudo = resposta.read()
    except urllib.error.HTTPError as e:
        return Leitura(False, url, erro=f"HTTP {e.code}")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return Leitura(False, url, erro=f"{type(e).__name__}: {getattr(e, 'reason', e)}")
    original = Original(url=url, coletado_em=date.today().isoformat(),
                        sha256=impressao(conteudo), fonte=fonte)
    return Leitura(True, url, conteudo, original=original)


def _carregar_estado(caminho: Path = ESTADO) -> dict:
    if caminho.exists():
        return json.loads(caminho.read_text(encoding="utf-8"))
    return {"fontes": {}}


def registrar(fonte: str, leitura: Leitura, *, caminho: Path = ESTADO) -> dict:
    """Guarda o resultado da coleta de uma fonte no estado do sistema."""
    estado = _carregar_estado(caminho)
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    item = estado["fontes"].setdefault(fonte, {})
    item["ultima_tentativa"] = agora
    item["url"] = leitura.url
    if leitura.ok:
        item["ultimo_sucesso"] = agora
        item["sha256"] = leitura.original.sha256 if leitura.original else None
        item.pop("erro", None)
    else:
        item["erro"] = leitura.erro
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(estado, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return estado


def fontes_paradas(estado: dict, hoje: date, limite_dias: int = 3) -> list[Ficha]:
    """Fonte sem coleta bem-sucedida há mais de ``limite_dias``: falha do sistema."""
    fichas = []
    for fonte, item in sorted(estado.get("fontes", {}).items()):
        sucesso = item.get("ultimo_sucesso")
        dias = None
        if sucesso:
            dias = (hoje - datetime.fromisoformat(sucesso).date()).days
        if sucesso is None or dias > limite_dias:
            quando = f"há {dias} dias" if dias is not None else "nunca"
            fichas.append(emitir(
                codigo=f"SIS-COLETA-{fonte.upper()}",
                familia=Familia.SIS,
                titulo=f"Coleta da fonte {fonte} parada",
                gravidade="alta",
                como_deveria=f"Toda fonte é lida pelo menos a cada {limite_dias} dias.",
                norma="Premissa do Onisciente: falha de coleta é falha do sistema",
                como_esta=f"Último sucesso {quando}. Erro registrado: {item.get('erro') or 'nenhum'}.",
                niveis=[],
                documento_faltante=True,
                providencia="Corrigir o coletor desta fonte; enquanto isso o parecer marca em "
                            "vermelho o que ela alimenta.",
                origem="sistema",
            ))
    return fichas
