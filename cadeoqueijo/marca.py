#!/usr/bin/env python3
"""Marca visual do Núcleo de Fiscalização — AMC Jardim América.
Logo embutida como data-URI (PNG 300px, ~11 KB) para manter cada HTML
autossuficiente. Uso: from marca import LOGO_URI, cabecalho_html
"""
from pathlib import Path

_B64 = (Path(__file__).resolve().parent.parent / "docs" /
        "assets_logo.b64").read_text().strip()
LOGO_URI = "data:image/png;base64," + _B64


def cabecalho_html(titulo_html: str, subtitulo: str = "") -> str:
    return f"""<header class="peca" style="display:flex;gap:18px;align-items:center">
 <img src="{LOGO_URI}" alt="Núcleo de Fiscalização — AMC Jardim América"
  style="width:192px;height:auto;flex:none">
 <div>
  <div class="orgao">Núcleo de Fiscalização — A.M.C. Jardim América<br>
  Vigilância da assistência social — Município de Goiânia · trilhas
  separadas: SEMASDH (execução) · CMASGyn (controle social)</div>
  <h1>{titulo_html}</h1>
  {f'<div class="orgao">{subtitulo}</div>' if subtitulo else ''}
 </div>
</header>"""


def rodape_marca_html() -> str:
    return (f'<div style="text-align:center;margin:34px 0 6px">'
            f'<img src="{LOGO_URI}" alt="Núcleo de Fiscalização — '
            f'AMC Jardim América" style="width:192px;height:auto"></div>')
