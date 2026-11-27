"""As telas do Onisciente: um site estático, gerado do banco histórico, para o GitHub Pages.

    python -m onisciente telas            # gera docs/onisciente/app/

Treze páginas, na ordem do rio (o estudo de UX em docs/onisciente/ux/estudo_ux.md explica o porquê). Cada
página leva embutidos os dados da sua tela, a tabela das fontes dos números que ela mostra e o índice das
fichas (para os recortes e os contadores da régua). Nada vai à rede: só o banco e os módulos do Onisciente.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import date
from pathlib import Path

from .. import RAIZ
from ..config import carregar_alvo
from ..legal.mapa import carregar as carregar_mapa
from . import dados as D
from . import originais as og
from .base import abrir, chaves_de_fonte, sem_cpf
from .pagina import html

ESTATICO = Path(__file__).parent / "estatico"
DESTINO = RAIZ / "docs" / "onisciente" / "app"
BANCO = RAIZ / "dados" / "onisciente" / "historico.db"

# Em que tela fica cada tema (as fichas do tema vão embutidas nela).
TEMAS_DA_PAGINA: dict[str, tuple[str, ...]] = {}
for _tema, (_t, _pagina, _a, _d) in D.TEMAS.items():
    TEMAS_DA_PAGINA.setdefault(_pagina, ())
    TEMAS_DA_PAGINA[_pagina] += (_tema,)


def panoramas_dos_relatorios(pasta: Path = RAIZ / "relatorios" / "onisciente") -> dict[str, dict]:
    """Os panoramas já calculados pelo parecer mensal (um JSON por competência)."""
    out = {}
    for arq in sorted(pasta.glob("panorama_*.json")):
        try:
            out[arq.stem.split("_", 1)[1]] = json.loads(arq.read_text(encoding="utf-8"))
        except (ValueError, IndexError):
            continue
    return out


def _versao(*arquivos: Path) -> str:
    h = hashlib.sha256()
    for a in arquivos:
        h.update(a.read_bytes())
    return h.hexdigest()[:10]


def montar(ctx: D.Contexto) -> tuple[dict, dict[str, dict], list[dict]]:
    """Os dados de todas as páginas: (comum, dados por página, índice das fichas)."""
    comum = D.comum(ctx)
    comum["temas"] = {k: {"titulo": t, "pagina": p, "ancora": a, "descricao": d} for k, (t, p, a, d) in D.TEMAS.items()}
    comum["entradas"] = sorted(ctx.entradas)
    rio = D.rio(ctx)
    precos = D.precos(ctx)
    ind = D.indicios(ctx)
    paginas = {
        "index": {"inicio": D.inicio(ctx, rio, precos), "estacoes": D.ESTACOES_TEXTO,
                  "estacoes_da_familia": ind["estacoes_da_familia"]},
        "rio": rio,
        "leis": D.leis(ctx),
        "trilha": D.trilha(ctx),
        "secretarias": D.secretarias_dados(ctx),
        "pisos": D.pisos(ctx),
        "pessoal": D.pessoal(ctx),
        "precos": precos,
        "empresas": D.empresas(ctx),
        "contas": D.contas(ctx),
        "indicios": {"fichas": ind["fichas"], "familias": ind["familias"],
                     "estacoes_da_familia": ind["estacoes_da_familia"], "estacoes": D.ESTACOES_TEXTO},
        "transparencia": D.transparencia(ctx),
        "tempo": D.tempo(ctx),
    }
    for pid, temas in TEMAS_DA_PAGINA.items():
        if pid in paginas and pid != "indicios":
            paginas[pid]["fichas"] = [f for f in ind["fichas"] if f["tema"] in temas]
    return comum, paginas, D.indice_das_fichas(ind["fichas"])


def gerar(destino: Path = DESTINO, *, banco: Path = BANCO, alvo: str = "goiania",
          panoramas: dict[str, dict] | None = None, brutos: Path | None = None, hoje: date | None = None,
          entradas: dict[str, dict] | None = None) -> list[Path]:
    """Gera o site inteiro em ``destino`` e devolve os arquivos escritos."""
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    con = abrir(banco)
    try:
        originais = og.Originais(con=con, brutos=Path(brutos) if brutos else None, destino=destino / "originais")
        a = carregar_alvo(RAIZ / "alvos" / f"{alvo}.toml")
        ctx = D.Contexto(con=con, banco=Path(banco), alvo=a, alvo_id=alvo, mapa=carregar_mapa(),
                         originais=originais,
                         panoramas=panoramas if panoramas is not None else panoramas_dos_relatorios(),
                         entradas=entradas if entradas is not None else D.carregar_entradas(),
                         hoje=hoje or date.today(),
                         alvos=[{"id": alvo, "nome": a.nome, "url": "index.html"}])
        comum, paginas, indice = montar(ctx)
    finally:
        con.close()
    escritos = []
    for nome in ("app.css", "app.js", "escudo.webp"):
        shutil.copyfile(ESTATICO / nome, destino / nome)
        escritos.append(destino / nome)
    versao = _versao(ESTATICO / "app.css", ESTATICO / "app.js")
    chaves_comum = chaves_de_fonte(comum)
    for p in comum["paginas"]:
        dados = sem_cpf(paginas[p["id"]])
        fontes = sem_cpf(originais.como_dict(chaves_comum | chaves_de_fonte(dados)))
        arq = destino / f"{p['id']}.html"
        arq.write_text(html(p, sem_cpf(comum), dados, fontes, indice, versao_estatico=versao), encoding="utf-8")
        escritos.append(arq)
    return escritos
