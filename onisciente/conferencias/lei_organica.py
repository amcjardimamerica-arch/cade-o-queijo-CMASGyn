"""Lei Orgânica de Goiânia: quinquênio (art. 28), servidor em empresa contratada (art. 29) e controle
interno (art. 104).

* **Art. 28 (QUINQUENIO).** O adicional por quinquênio só se confere com a folha que traz a data de
  admissão e o adicional pago. Sem ela, a conferência roda e a falta vira pedido de acesso.
* **Art. 29 (SERVIDOR-CONTRATADA).** A regra está no mapa legal com o texto e o limiar zero; o
  cruzamento do quadro de sócios das contratadas com o quadro de servidores é da conferência de
  empresas (Receita Federal), em ``onisciente/conferencias/empresas.py``.
* **Art. 104 (CONTROLE-INTERNO).** O controle interno comunica as irregularidades ao Tribunal. Cada
  indício que o próprio sistema confirma em duas vias é uma irregularidade a comunicar; sem as
  comunicações publicadas, a falta vira pedido de acesso à Controladoria.
"""

from __future__ import annotations

from ..nucleo.ausencias import Ausencia
from ..nucleo.selos import Selo
from .banco import CGM, Base, Linha, Parte, Quadro


def conferir(base: Base) -> Parte:
    parte = Parte()
    q = Quadro(6, "Lei Orgânica de Goiânia: o que se confere e com qual documento",
               "As regras da Lei Orgânica no mapa legal, com o limiar de cada uma e a peça que a confere.",
               ["Regra", "Limiar", "Documento", "Situação"])
    for rid, documento, situacao, selo in (
            ("QUINQUENIO", "folha com data de admissão e adicional pago", "folha não publicada", Selo.ROXO),
            ("SERVIDOR-CONTRATADA", "quadro de sócios (Receita Federal) contra o quadro de servidores",
             "conferido na conferência de empresas", Selo.AZUL),
            ("CONTROLE-INTERNO", "comunicações da Controladoria ao Tribunal", "comunicações não publicadas", Selo.ROXO),
            ("FOLHA-DIA-5", "matriz de saldos contábeis e folha com data de crédito",
             "conferido pela matriz; dia exato depende da folha", Selo.AZUL)):
        try:
            r = base.mapa.regra(rid)
        except KeyError:
            continue
        limiar = f"{r.valor:g} {r.unidade}" if r.valor is not None else r.unidade
        q.linhas.append(Linha(f"{r.titulo} ({r.norma})", [limiar, documento, situacao], selo))
    parte.quadros.append(q)
    parte.ausencias.append(Ausencia(
        o_que_falta="Comunicações da Controladoria ao Tribunal de Contas sobre irregularidades apuradas, com as datas",
        conferencia_impedida="conferir se cada indício confirmado foi comunicado ao Tribunal (CONTROLE-INTERNO)",
        onde_deveria_estar="Portal da Transparência de Goiânia (controle interno) e relatório anual da Controladoria",
        fundamento="Lei Orgânica, art. 104; CF, art. 74, § 1º; Decreto 265/2016",
        periodo=f"exercício {base.ate.year}", orgao=CGM, bloco="Controle interno"))
    return parte
