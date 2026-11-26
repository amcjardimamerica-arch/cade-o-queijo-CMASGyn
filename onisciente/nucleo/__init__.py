"""Núcleo do Onisciente: provas, selos, estações, custódia, indícios e ausências."""

from .provas import Nivel, pode_afirmar_irregularidade
from .selos import Gravidade, Selo, Verificacao, Via, selar
from .custodia import Original
from .estacoes import Estacao, Evento, Percurso
from .indicios import Familia, Ficha, emitir
from .ausencias import Ausencia
from .integridade import IndiceIntegridade

__all__ = [
    "Nivel", "pode_afirmar_irregularidade",
    "Gravidade", "Selo", "Verificacao", "Via", "selar",
    "Original", "Estacao", "Evento", "Percurso",
    "Familia", "Ficha", "emitir", "Ausencia", "IndiceIntegridade",
]
