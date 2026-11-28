"""As telas do Onisciente: um site estático, gerado do banco histórico, para o GitHub Pages.

    python -m onisciente telas            # gera docs/onisciente/app/

Treze páginas, agrupadas pelas etapas do gasto público: origem do dinheiro, orçamento, contratação, liquidação,
pagamento e prestação de contas (o estudo de UX em docs/onisciente/ux/estudo_ux.md explica o porquê). Cada
página leva embutidos os dados da sua tela, a tabela das fontes dos números que ela mostra e o índice das
fichas (para os recortes e as contagens por etapa e condição). Nada vai à rede: só o banco e os módulos do
Onisciente.
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
    comum["entradas"] = sorted(n for n in ctx.entradas if ctx.entrada(n))
    comum["coletas"] = ctx.coletas()
    origem = D.rio(ctx)
    precos = D.precos(ctx)
    ind = D.indicios(ctx)
    trilha = D.trilha(ctx)
    paginas = {
        "index": {"inicio": D.inicio(ctx, origem, precos), "estacoes": D.ESTACOES_TEXTO,
                  "estacoes_da_familia": ind["estacoes_da_familia"],
                  "estacoes_com_documento": D.estacoes_com_documento(trilha)},
        "origem": origem,
        "leis": D.leis(ctx),
        "trilha": trilha,
        "secretarias": D.secretarias_dados(ctx),
        "pisos": D.pisos(ctx),
        "pessoal": D.pessoal(ctx),
        "precos": precos,
        "empresas": D.empresas(ctx),
        "contas": D.contas(ctx),
        "indicios": {"fichas": ind["fichas"], "familias": ind["familias"], "rotulos": ind["rotulos"],
                     "estacoes_da_familia": ind["estacoes_da_familia"], "estacoes": D.ESTACOES_TEXTO},
        "transparencia": D.transparencia(ctx),
        "tempo": D.tempo(ctx),
    }
    for pid, temas in TEMAS_DA_PAGINA.items():
        if pid in paginas and pid != "indicios":
            paginas[pid]["fichas"] = [f for f in ind["fichas"] if f["tema"] in temas]
    return comum, paginas, D.indice_das_fichas(ind["fichas"])


def indice_de_hashes(paginas: list[dict], chaves: dict[str, set[str]], originais: og.Originais) -> list[dict]:
    """Os hashes das fontes de todas as páginas, para a busca por hash da tela de indícios (as fichas já vão
    com os seus hashes na própria tela). Cada fonte entra com o hash da resposta (sha256) e, quando o banco
    tem rastreio, com o hash do registro da coleta; ``p`` é a primeira tela, na ordem das etapas, que mostra
    um número dessa fonte."""
    out, vistos = [], set()
    for pg in paginas:
        for chave in sorted(chaves.get(pg["id"], ())):
            o = originais.tabela.get(chave)
            if o is None:
                continue
            for tipo, h in (("resposta", o.sha256), ("registro", o.registro)):
                if not h or (tipo, h, chave) in vistos:
                    continue
                vistos.add((tipo, h, chave))
                d = {"h": h, "t": tipo, "k": chave, "r": o.rotulo, "p": pg["id"]}
                if o.url:
                    d["u"] = o.url
                if tipo == "registro" and o.confere:
                    d["v"] = 1
                out.append(d)
    return out


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
    chaves = {p["id"]: chaves_comum | chaves_de_fonte(paginas[p["id"]]) for p in comum["paginas"]}
    if "indicios" in paginas:
        paginas["indicios"]["hashes"] = indice_de_hashes(comum["paginas"], chaves, originais)
    for p in comum["paginas"]:
        dados = sem_cpf(paginas[p["id"]])
        fontes = sem_cpf(originais.como_dict(chaves_comum | chaves_de_fonte(dados)))
        arq = destino / f"{p['id']}.html"
        arq.write_text(html(p, sem_cpf(comum), dados, fontes, indice, versao_estatico=versao), encoding="utf-8")
        escritos.append(arq)
    return escritos
