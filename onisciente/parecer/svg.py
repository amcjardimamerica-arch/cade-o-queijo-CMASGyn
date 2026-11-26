"""Gráficos em SVG próprio, sem biblioteca externa: o parecer é autônomo e arquivável."""

from __future__ import annotations

from html import escape

from ..nucleo.integridade import PESOS, ROTULOS, IndiceIntegridade
from ..nucleo.selos import Selo
from ..pisos import Medida
from ..rio.afluentes import Rio
from ..rio.fontes import Esfera

TINTA = "#1F2933"
APAGADO = "#6B7280"
LINHA = "#D7DCE1"


def moeda(v: float | None) -> str:
    if v is None:
        return "—"
    s = f"{v:,.2f}"
    return "R$ " + s.replace(",", "§").replace(".", ",").replace("§", ".")


def _curto(v: float) -> str:
    if v >= 1e9:
        return f"R$ {v / 1e9:.1f} bi".replace(".", ",")
    if v >= 1e6:
        return f"R$ {v / 1e6:.1f} mi".replace(".", ",")
    if v >= 1e3:
        return f"R$ {v / 1e3:.0f} mil"
    return moeda(v)


def _linhas_do_rio(r: Rio, maximo: int | None) -> list[tuple[str, Esfera, float, str, bool]]:
    """(nome, esfera, valor, legenda, tracejado). Além de ``maximo`` linhas, as menores se juntam por esfera."""
    afl = sorted((a for a in r.afluentes if a.valor > 0), key=lambda a: -a.valor)

    def linha(a) -> tuple[str, Esfera, float, str, bool]:
        natureza = {True: "vinculada", False: "livre", None: "sem fonte declarada"}[a.vinculado]
        return (a.nome, a.esfera, a.valor, natureza + (f" · fonte {a.fonte}" if a.fonte else ""),
                a.vinculado is None)

    if maximo is None or len(afl) <= maximo:
        return [linha(a) for a in afl]
    grandes, resto = afl[:maximo - 1], afl[maximo - 1:]
    out = [linha(a) for a in grandes]
    por_esfera: dict[Esfera, list] = {}
    for a in resto:
        por_esfera.setdefault(a.esfera, []).append(a)
    for esf, lista in sorted(por_esfera.items(), key=lambda kv: -sum(a.valor for a in kv[1])):
        soma = sum(a.valor for a in lista)
        vinc = sum(a.valor for a in lista if a.vinculado)
        out.append((f"Demais afluentes ({len(lista)}), {esf.value}", esf, soma,
                    f"vinculada {_curto(vinc)} · livre ou sem fonte {_curto(soma - vinc)}", False))
    return sorted(out, key=lambda x: -x[2])


def rio(r: Rio, largura: int = 760, *, rotulo: str = "no mês", maximo: int | None = None) -> str:
    """Afluentes descendo até o leito: espessura pelo valor, cor pela esfera."""
    afl = _linhas_do_rio(r, maximo)
    total = sum(x[2] for x in afl)
    if not afl or total <= 0:
        return ('<p class="vazio">Sem afluente publicado para a competência: o rio não pode ser '
                'desenhado.</p>')
    linha_h = 34
    altura = 60 + linha_h * len(afl) + 70
    x_rotulo, x_ini, x_leito = 12, 300, largura - 150
    max_esp = 26.0
    partes = [f'<svg viewBox="0 0 {largura} {altura}" role="img" aria-label="Rio de afluentes" '
              f'xmlns="http://www.w3.org/2000/svg" class="grafico">']
    leito_y0 = 40
    leito_h = linha_h * len(afl)
    partes.append(f'<rect x="{x_leito}" y="{leito_y0 - 6}" width="22" height="{leito_h + 12}" '
                  f'rx="11" fill="#E8EEF5" stroke="{LINHA}"/>')
    acumulado = leito_y0
    maior = afl[0][2]
    for i, (nome, esfera, valor, legenda, tracejado) in enumerate(afl):
        y = leito_y0 + i * linha_h + linha_h / 2
        esp = max(2.0, max_esp * valor / maior)
        alvo_y = acumulado + (leito_h * valor / total) / 2
        acumulado += leito_h * valor / total
        traco = ' stroke-dasharray="6 4"' if tracejado else ""
        partes.append(
            f'<path d="M{x_ini},{y:.1f} C{(x_ini + x_leito) / 2:.0f},{y:.1f} '
            f'{(x_ini + x_leito) / 2:.0f},{alvo_y:.1f} {x_leito},{alvo_y:.1f}" fill="none" '
            f'stroke="{esfera.cor}" stroke-width="{esp:.1f}" stroke-linecap="round" opacity="0.85"{traco}/>')
        partes.append(f'<text x="{x_rotulo}" y="{y - 2:.1f}" class="t">{escape(nome[:40])}</text>')
        partes.append(f'<text x="{x_rotulo}" y="{y + 12:.1f}" class="ts">{_curto(valor)} · {escape(legenda)}</text>')
    vl = r.vinculada_e_livre()
    partes.append(f'<text x="{x_leito + 30}" y="{leito_y0 + 14}" class="th">{_curto(total)}</text>')
    partes.append(f'<text x="{x_leito + 30}" y="{leito_y0 + 30}" class="ts">{escape(rotulo)}</text>')
    y_leg = altura - 40
    x = x_rotulo
    for esf, nome in ((Esfera.FEDERAL, "federal"), (Esfera.ESTADUAL, "estadual"),
                      (Esfera.MUNICIPAL, "municipal"), (Esfera.MISTA, "sem esfera")):
        partes.append(f'<rect x="{x}" y="{y_leg - 9}" width="14" height="10" rx="2" fill="{esf.cor}"/>')
        partes.append(f'<text x="{x + 20}" y="{y_leg}" class="ts">{nome}</text>')
        x += 110
    partes.append(f'<text x="{x_rotulo}" y="{y_leg + 22}" class="ts">Vinculada {_curto(vl["vinculada"])}'
                  f' · livre {_curto(vl["livre"])} · sem fonte declarada {_curto(vl["sem_fonte"])}'
                  f' (tracejado)</text>')
    partes.append("</svg>")
    return "".join(partes)


def medidor(m: Medida, largura: int = 760) -> str:
    """Um medidor por regra: a barra é o cálculo próprio, o traço é o limite."""
    h = 58
    x0, x1 = 12, largura - 12
    escala = max(m.limite * 2, (m.percentual or 0) * 1.1, 1.0)
    px = lambda v: x0 + (x1 - x0) * min(v, escala) / escala  # noqa: E731
    cor = {"cumpre": "#15803D", "acompanha": "#0E7490", "alerta": "#A16207", "prudencial": "#E07B00",
           "descumpre": "#E01B0E", "sem_dado": Selo.ROXO.cor}[m.situacao]
    partes = [f'<svg viewBox="0 0 {largura} {h}" role="img" xmlns="http://www.w3.org/2000/svg" '
              f'aria-label="{escape(m.regra.titulo)}" class="grafico">',
              f'<rect x="{x0}" y="22" width="{x1 - x0}" height="14" rx="7" fill="#EEF1F4"/>']
    if m.percentual is None:
        partes.append(f'<rect x="{x0}" y="22" width="{x1 - x0}" height="14" rx="7" fill="none" '
                      f'stroke="{cor}" stroke-dasharray="5 4"/>')
        partes.append(f'<text x="{x0}" y="54" class="ts">Sem dado publicado: a lei manda publicar e '
                      f'não está publicado.</text>')
    else:
        partes.append(f'<rect x="{x0}" y="22" width="{px(m.percentual) - x0:.1f}" height="14" rx="7" '
                      f'fill="{cor}"/>')
        partes.append(f'<text x="{x0}" y="54" class="ts">Cálculo próprio {m.percentual:.2f}%'
                      + (f" · declarado {m.declarado:.2f}%" if m.declarado is not None else "")
                      + (" · divergem" if m.divergencia else "") + "</text>")
    lx = px(m.limite)
    partes.append(f'<line x1="{lx:.1f}" y1="16" x2="{lx:.1f}" y2="42" stroke="{TINTA}" stroke-width="2"/>')
    partes.append(f'<text x="{lx:.1f}" y="12" text-anchor="middle" class="ts">limite {m.limite:g}%</text>')
    partes.append("</svg>")
    return "".join(partes)


def integridade(ind: IndiceIntegridade, largura: int = 760) -> str:
    """As cinco medidas do índice, cada uma contra o seu peso; a não medida sai em vermelho."""
    linha_h = 26
    h = 20 + linha_h * len(PESOS)
    x_barra, x_fim = 170, largura - 150
    partes = [f'<svg viewBox="0 0 {largura} {h}" role="img" xmlns="http://www.w3.org/2000/svg" '
              f'aria-label="Índice de integridade da trilha" class="grafico">']
    for i, (nome, peso) in enumerate(PESOS.items()):
        y = 10 + i * linha_h
        obtido = ind.partes[nome]
        larg = (x_fim - x_barra) * peso / 40
        partes.append(f'<text x="12" y="{y + 12}" class="t">{ROTULOS[nome]}</text>')
        if obtido is None:
            partes.append(f'<rect x="{x_barra}" y="{y + 2}" width="{larg:.1f}" height="12" rx="3" '
                          f'fill="none" stroke="{Selo.VERMELHO.cor}" stroke-dasharray="4 3"/>')
            partes.append(f'<text x="{x_barra + larg + 8:.1f}" y="{y + 12}" class="ts" '
                          f'fill="{Selo.VERMELHO.cor}">não medida ({peso} pts)</text>')
            continue
        partes.append(f'<rect x="{x_barra}" y="{y + 2}" width="{larg:.1f}" height="12" rx="3" fill="#EEF1F4"/>')
        partes.append(f'<rect x="{x_barra}" y="{y + 2}" width="{larg * obtido / peso:.1f}" height="12" '
                      f'rx="3" fill="#2563EB"/>')
        partes.append(f'<text x="{x_barra + larg + 8:.1f}" y="{y + 12}" class="ts">{obtido:g} de {peso}</text>')
    partes.append("</svg>")
    return "".join(partes)
