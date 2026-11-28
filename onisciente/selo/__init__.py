"""Auditoria independente do Selo de Transparência (PNTP/Atricon) da Prefeitura de Goiânia.

Refaz, critério por critério e pela fórmula oficial, a avaliação que os Tribunais de Contas fazem no
Programa Nacional de Transparência Pública, com as provas que o Onisciente tem, e confronta o resultado
com o selo declarado. Duas leituras: a oficial e a restritiva (regras/pntp/escolhas.yml).

    from onisciente.selo import avaliar
    auditoria = avaliar()
"""

from .avaliador import Auditoria, avaliar

__all__ = ["Auditoria", "avaliar"]
