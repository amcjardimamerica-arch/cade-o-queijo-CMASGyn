"""O parecer de cada secretaria, gerado só pela configuração (requisitos 130, 132, 138 e 166).

Para cada domínio ativo do alvo (``alvos/<alvo>.toml`` e ``dominios/*.toml``) e o banco histórico,
monta o panorama da pasta e o entrega ao gerador de parecer de sempre (``parecer.html.gerar``):

* o rio da pasta é o **realizado**: o pago no exercício aberto pelas fontes (matriz de saldos);
* as margens são as da pasta (a quarta, pago sem vínculo, só com o item a item);
* a integridade é a da pasta (coerência e tempestividade medidas; cobertura e vínculo com o portal);
* os pisos são as regras do domínio (``regras`` no toml), medidos com a faixa da Câmara do alvo;
* o Município inteiro vem junto (``fiscal``), para o rio da pasta se ler dentro do rio do Município;
* as fichas são as da pasta: os pisos dela, as vias que divergem e os achados da execução.

O gerador de parecer é da Frente C e ainda não tem a seção da execução por secretaria nem as contas
uma a uma. Até ter, este módulo insere o bloco (``secao_execucao``) no lugar do aviso "As saídas, as
quatro estações legais e a cronologia evento a evento aparecem quando a execução da despesa é
publicada." da seção 4, e troca o cabeçalho "Previsto no mês" por "Pago no exercício", que é o que a
coluna mostra no parecer da pasta. A chamada a pôr no ``parecer/html.py`` está descrita no
relatório da Frente D2.

Nenhuma linha aqui sabe o nome de um Município: outro alvo é outro toml e outro banco.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from html import escape
from pathlib import Path

from ..config import Alvo, Dominio, carregar_alvo
from ..nucleo.indicios import Familia, Ficha, emitir
from ..nucleo.provas import Nivel
from ..nucleo.selos import Selo
from . import secretarias as S

AVISO_DA_SECAO_4 = ("As saídas, as quatro estações legais e a cronologia evento a evento aparecem quando a "
                    "execução da despesa é publicada.")
ESTACOES = (("empenho", "Empenho"), ("liquidacao", "Liquidação"), ("ordem_pagamento", "Ordem de pagamento"),
            ("pagamento", "Pagamento"))


def _moeda(v: float | None) -> str:
    if v is None:
        return "sem valor"
    return "R$ " + f"{v:,.2f}".replace(",", "§").replace(".", ",").replace("§", ".")


def _pct(v: float | None) -> str:
    return "sem medida" if v is None else f"{100 * v:.1f}%".replace(".", ",")


def _selo(s: Selo | None) -> str:
    if s is None:
        return ""
    return f'<span class="selo s-{s.value}" title="{escape(s.significado)}"></span>'


@dataclass
class ParecerDominio:
    alvo: Alvo
    dominio: Dominio
    competencia: str
    panorama: object                                   # panorama.Panorama
    execucao: S.ExecucaoSecretaria
    contas: dict = field(default_factory=dict)
    qualidade: S.QualidadeDoPlano | None = None

    def html(self, *, hoje: date | None = None) -> str:
        from ..parecer import html as parecer_html
        bruto = parecer_html.gerar(self.panorama, hoje=hoje)
        if getattr(self.panorama, "execucao", None) is not None:
            return bruto                   # o gerador do parecer já põe a seção da execução (Frente C)
        return inserir_execucao(bruto, secao_execucao(self.execucao, self.contas, self.qualidade))

    def como_dict(self) -> dict:
        return {"alvo": self.alvo.nome, "dominio": self.dominio.id, "competencia": self.competencia,
                "execucao": self.execucao.como_dict(), "contas": self.contas,
                "qualidade": None if self.qualidade is None else self.qualidade.como_dict(),
                "panorama": self.panorama.como_dict()}


# --- O bloco da execução da pasta e das contas uma a uma -------------------------------------------

def secao_execucao(ex: S.ExecucaoSecretaria, contas: dict, q: S.QualidadeDoPlano | None) -> str:
    s = [f"<h3>A execução da pasta: {escape(ex.rotulo)}</h3>"]
    linhas = []
    for chave, rotulo in (("autorizado", "Autorizado (dotação atualizada)"), ("empenhado", "Empenhado"),
                          ("liquidado", "Liquidado"), ("pago", "Pago")):
        v = ex.valores[chave]
        vias = v.certificacao.vias
        celulas = "".join(f'<td class="num">{escape(x.fonte)}<br>{_moeda(x.valor)}</td>' for x in vias[:2])
        celulas += '<td class="num">sem segunda via</td>' * (2 - len(vias[:2]))
        resultado = ("divergem" if v.certificacao.divergencia else
                     "iguais" if len(vias) >= 2 else "uma via")
        linhas.append(f"<tr><td>{_selo(v.selo)}{rotulo}</td>{celulas}<td>{resultado}</td></tr>")
    s.append('<div class="tabela"><table><tr><th>Valor</th><th>Via 1</th><th>Via 2</th><th>Resultado</th></tr>'
             + "".join(linhas) + "</table></div>")
    if ex.inicial is not None:
        s.append(f'<p class="sub">Dotação inicial da pasta: {_moeda(ex.inicial)}.</p>')
    for n in ex.notas:
        s.append(f'<p class="omitido">{escape(n)}</p>')
    if ex.por_fonte:
        s.append('<div class="tabela"><table><tr><th>Fonte</th><th>Vinculada</th><th>Empenhado</th>'
                 "<th>Pago</th></tr>" + "".join(
                     f"<tr><td>{escape(f['fonte'])} {escape(f['nome'])}</td>"
                     f"<td>{'sim' if f['vinculada'] else 'não' if f['vinculada'] is False else 'fora do catálogo'}</td>"
                     f'<td class="num">{_moeda(f["empenhado"])}</td><td class="num">{_moeda(f["pago"])}</td></tr>'
                     for f in ex.por_fonte[:12]) + "</table></div>")

    s.append("<h3>As nove maiores saídas, com as quatro estações legais</h3>")
    item = contas.get("item_a_item") or []
    saidas = item or contas.get("matriz") or []
    if not saidas:
        s.append('<p class="omitido">Nenhuma saída da pasta lida no período.</p>')
    else:
        origem = "credor a credor, pelo portal da transparência" if item else \
            "por natureza da despesa, pela matriz de saldos contábeis"
        s.append(f'<p class="sub">Lei 4.320/1964, arts. 58 a 65. Saídas {origem}.</p>')
        cab = "".join(f"<th>{r}</th>" for _, r in ESTACOES)
        corpo = "".join(
            f"<tr><td>{escape(str(x['saida']))}</td>" + "".join(
                f'<td class="num">{_moeda(x["estacoes"].get(k))}</td>' for k, _ in ESTACOES) + "</tr>"
            for x in saidas)
        s.append(f'<div class="tabela"><table><tr><th>Saída</th>{cab}</tr>{corpo}</table></div>')
        if not item:
            s.append('<p class="omitido">A ordem de pagamento não é publicada na matriz de saldos contábeis: '
                     "a coluna fica sem valor até a execução item a item ser lida.</p>")
        elif any(x["estacoes"].get("ordem_pagamento") is None for x in item):
            s.append('<p class="omitido">A exportação do portal publica cada pagamento com o número da ordem, '
                     "mas não o ato da ordem de pagamento em separado: a coluna fica sem valor, não zero.</p>")
        s.append("<h3>A cronologia</h3>")
        for x in saidas:
            if item:
                passos = "".join(f"<li>{escape(c['data'])}: {escape(c['estacao'])}, {_moeda(c['valor'])}"
                                 f" (empenho {escape(c['empenho'])})</li>" for c in x["cronologia"])
            else:
                passos = "".join(f"<li>{escape(c['mes'])}: empenhado {_moeda(c.get('empenho'))}, liquidado "
                                 f"{_moeda(c.get('liquidacao'))}, pago {_moeda(c.get('pagamento'))}</li>"
                                 for c in x["cronologia"])
            s.append(f"<details><summary>{escape(str(x['saida']))}</summary><ul>{passos}</ul></details>")
    if contas.get("falta"):
        s.append(f'<p class="omitido">{escape(contas["falta"])}</p>')

    if q is not None:
        s.append(f"<h3>A qualidade do plano: {escape(q.plano)}</h3>")
        s.append(f'<p class="sub">{escape(q.norma)} · exercício {q.exercicio}</p>')
        s.append('<div class="tabela"><table><tr><th>Medida</th><th>Valor</th></tr>'
                 f"<tr><td>Aderência (a dotação inicial que não foi refeita por créditos)</td>"
                 f'<td class="num">{_pct(q.aderencia)}</td></tr>'
                 f"<tr><td>Execução (liquidado sobre o autorizado no fim do exercício)</td>"
                 f'<td class="num">{_pct(q.execucao)}</td></tr>'
                 f'<tr><td>Nota do plano (de 0 a 100)</td><td class="num">{"sem medida" if q.nota is None else q.nota}'
                 "</td></tr></table></div>")
        if q.motivo_indicador:
            s.append(f'<p class="omitido">{escape(q.motivo_indicador[:1].upper() + q.motivo_indicador[1:])}.</p>')
    return "\n".join(s)


def inserir_execucao(bruto: str, bloco: str) -> str:
    """Põe o bloco no lugar do aviso da seção 4 (ou antes da seção 5, se o aviso mudar)."""
    bruto = bruto.replace("<th>Previsto no mês</th>", "<th>Pago no exercício</th>")
    aviso = f'<p class="omitido">{AVISO_DA_SECAO_4}</p>'
    if aviso in bruto:
        return bruto.replace(aviso, bloco, 1)
    marca = "<h2>5."
    if marca in bruto:
        return bruto.replace(marca, bloco + "\n" + marca, 1)
    return bruto + bloco


# --- O panorama da pasta --------------------------------------------------------------------------

def _fichas_de_vias(ex: S.ExecucaoSecretaria, competencia: str) -> list[Ficha]:
    out = []
    for chave, v in ex.valores.items():
        c = v.certificacao
        if not c.divergencia:
            continue
        vias = "; ".join(f"{x.fonte}: {_moeda(x.valor)}" for x in c.vias)
        out.append(emitir(
            codigo=f"VIAS-{ex.dominio.id.upper()}-{chave.upper()}-{competencia}", familia=Familia.PISO,
            titulo=f"{ex.dominio.nome}: o {chave} diverge entre o RREO e a matriz",
            gravidade="alta",
            como_deveria="O RREO Anexo 2 e a matriz de saldos contábeis saem da mesma contabilidade e dizem o "
                         "mesmo valor da função e da subfunção.",
            norma="LC 101/2000, arts. 52 e 53; Portaria STN 642/2019 (MSC)",
            como_esta=f"Indício, não acusação. {ex.rotulo}. {vias}.", niveis=[Nivel.B, Nivel.B],
            providencia="Pedir a conciliação entre o RREO e a matriz e a retificação no SICONFI.",
            competencia=competencia))
    return out


def montar(alvo: Alvo, dominio: Dominio, banco: Path | str, ate: date, *, mapa=None,
           conferencias=None, fiscal=None) -> ParecerDominio | None:
    """O parecer da pasta no último bimestre entregue até ``ate``; None sem RREO entregue."""
    from ..fiscal import medir_municipio
    from ..panorama import Panorama
    from ..pisos import fichas_da_medida
    from ..conferencias.execucao import conferir_execucao, ficha_execucao, ler_eventos

    con = S.abrir(banco)
    try:
        ub = S.ultimo_bimestre(con, ate)
        if ub is None:
            return None
        exercicio, bimestre = ub
        competencia = f"{exercicio}-{2 * bimestre:02d}"
        ex = S.execucao(con, dominio, exercicio, bimestre)
        conf = conferencias if conferencias is not None else conferir_execucao(con)
        eventos = ler_eventos(con)
        cobertura, vinculo = S.trilha_da_secretaria(conf.percursos, eventos, dominio, exercicio=exercicio,
                                                     ate_mes=2 * bimestre)
        integ = S.integridade_da_secretaria(con, dominio, exercicio, bimestre, ate,
                                            cobertura=cobertura, vinculo=vinculo)
        contas = S.contas_uma_a_uma(con, dominio, exercicio, 2 * bimestre)
        qualidade = S.qualidade_do_plano(con, dominio, ate)
        ex.pago_com_vinculo = None if vinculo is None or ex.v("pago") is None else vinculo * ex.v("pago")
    finally:
        con.close()

    if fiscal is None:
        fiscal = medir_municipio(ate, banco=banco, mapa=mapa, faixa_camara=alvo.faixa_camara)
    medidas = [m for m in fiscal.medidas if m.regra.id in dominio.regras]
    fichas: list[Ficha] = []
    for m in medidas:
        fichas += fichas_da_medida(m, competencia=competencia, ente=f"{alvo.nome}, {dominio.nome}")
    fichas += _fichas_de_vias(ex, competencia)
    fichas += [ficha_execucao(a, competencia) for a in conf.da_competencia(competencia)
               if S.achado_da_secretaria(a, dominio)]
    notas = [f"Secretaria recortada no orçamento por {', '.join(_recorte_legivel(dominio))}."]
    if ex.margens is not None and ex.margens.pago_com_vinculo is None:
        notas.append("A margem do pago sem vínculo publicado fica sem medida até o pago da pasta se cruzar, item "
                     "a item, com contratos, termos e folha.")
    pan = Panorama(competencia=competencia, alvo=alvo.nome, dominio=dominio.nome, rio=S.rio_da_secretaria(ex),
                   fichas=fichas, medidas=medidas, integridade=integ, margens=ex.margens, notas=notas,
                   fiscal=fiscal, execucao=ex, contas=contas, qualidade=qualidade, banco=banco)
    return ParecerDominio(alvo, dominio, competencia, pan, ex, contas, qualidade)


def _recorte_legivel(d: Dominio) -> list[str]:
    out = []
    for f, s in d.recortes:
        nome = S.FUNCOES.get(f, f"função {f}")
        out.append(f"função {f} ({nome})" if s is None else
                   f"subfunção {f}.{s} ({S.SUBFUNCOES.get(s, 'sem nome no catálogo')})")
    return out


def gerar_todos(alvo: Alvo | Path | str | None = None, *, banco: Path | str | None = None,
                ate: date | None = None, saida: Path | str | None = None, mapa=None,
                hoje: date | None = None) -> list[dict]:
    """Requisito 138: um parecer por secretaria ativa do alvo. Grava ``parecer_<dominio>_<competência>.html``
    e o JSON do panorama em ``saida`` (se dada) e devolve o resumo de cada um."""
    from ..conferencias.execucao import conferir_execucao
    from ..fiscal import BANCO, medir_municipio
    alvo = alvo if isinstance(alvo, Alvo) else carregar_alvo(alvo) if alvo else carregar_alvo()
    banco = banco or BANCO
    ate = ate or date.today()
    fiscal = medir_municipio(ate, banco=banco, mapa=mapa, faixa_camara=alvo.faixa_camara)
    conf = conferir_execucao(banco)
    resumo = []
    for d in alvo.ativos():
        p = montar(alvo, d, banco, ate, mapa=mapa, conferencias=conf, fiscal=fiscal)
        if p is None:
            resumo.append({"dominio": d.id, "situacao": "sem RREO entregue"})
            continue
        html = p.html(hoje=hoje)
        item = {"dominio": d.id, "competencia": p.competencia, "frase": p.panorama.em_uma_frase(),
                "situacao": "gerado"}
        if saida is not None:
            pasta = Path(saida)
            pasta.mkdir(parents=True, exist_ok=True)
            arq = pasta / f"parecer_{d.id}_{p.competencia}.html"
            arq.write_text(html, encoding="utf-8")
            (pasta / f"panorama_{d.id}_{p.competencia}.json").write_text(
                json.dumps(p.como_dict(), ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
            item["html"] = str(arq)
        else:
            item["html_texto"] = html
        resumo.append(item)
    return resumo
