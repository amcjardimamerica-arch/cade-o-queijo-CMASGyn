"""O subcomando ``python -m onisciente telas``: gera o site das telas, sem rede."""

from __future__ import annotations

import argparse
from pathlib import Path


def cmd_telas(args: argparse.Namespace) -> int:
    from . import BANCO, DESTINO, gerar, panoramas_dos_relatorios
    banco = Path(args.banco) if args.banco else BANCO
    if not banco.exists():
        print(f"Banco histórico não encontrado em {banco}. Rode a coleta histórica antes.")
        return 1
    panoramas = panoramas_dos_relatorios()
    if args.recalcular:
        from ..__main__ import competencias_disponiveis
        from ..adaptadores import cadeoqueijo
        for c in competencias_disponiveis():
            panoramas[c] = cadeoqueijo.montar(c).como_dict()
    escritos = gerar(Path(args.destino) if args.destino else DESTINO, banco=banco, panoramas=panoramas,
                     brutos=Path(args.brutos) if args.brutos else None)
    paginas = [a for a in escritos if a.suffix == ".html"]
    print(f"{len(paginas)} telas geradas em {paginas[0].parent}; comece por {paginas[0].parent / 'index.html'}.")
    return 0


def registrar(sub) -> None:
    pt = sub.add_parser("telas", help="gera as telas do Onisciente (site estático, sem rede)")
    pt.add_argument("--banco", help="banco histórico (padrão: dados/onisciente/historico.db)")
    pt.add_argument("--destino", help="pasta do site (padrão: docs/onisciente/app)")
    pt.add_argument("--brutos", help="pasta das respostas cruas da coleta, para publicar os originais")
    pt.add_argument("--recalcular", action="store_true",
                    help="refaz os panoramas mensais em vez de ler os JSON de relatorios/onisciente")
    pt.set_defaults(f=cmd_telas)
