"""Panorama de uma competência: tudo o que o parecer mensal mostra."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .nucleo.ausencias import Ausencia
from .nucleo.custodia import Original
from .nucleo.indicios import Ficha, ordenar
from .nucleo.integridade import IndiceIntegridade
from .nucleo.selos import Gravidade
from .pisos import Medida
from .rio.afluentes import Margens, Rio

if TYPE_CHECKING:
    from .fiscal import Fiscal


@dataclass
class Panorama:
    competencia: str
    alvo: str
    dominio: str
    rio: Rio
    fichas: list[Ficha] = field(default_factory=list)
    ausencias: list[Ausencia] = field(default_factory=list)
    medidas: list[Medida] = field(default_factory=list)
    integridade: IndiceIntegridade | None = None
    margens: Margens | None = None
    custodia: list[Original] = field(default_factory=list)
    leitura_falhou: list[str] = field(default_factory=list)  # trechos em vermelho
    notas: list[str] = field(default_factory=list)
    fiscal: "Fiscal | None" = None   # o Município pelo RGF e pelo RREO do banco histórico

    def fichas_ordenadas(self) -> list[Ficha]:
        return ordenar(self.fichas)

    def contagem(self) -> dict[str, int]:
        cont = {g.value: 0 for g in Gravidade}
        for f in self.fichas:
            cont[f.gravidade.value] += 1
        return cont

    def em_uma_frase(self) -> str:
        c = self.contagem()
        total = sum(c.values())
        partes = [f"{c['critica']} crítico{'s' if c['critica'] != 1 else ''}",
                  f"{c['alta']} de gravidade alta",
                  f"{c['media']} de gravidade média"]
        frase = f"{total} indício{'s' if total != 1 else ''}: " + ", ".join(partes) + "."
        if self.integridade is not None:
            frase += " " + self.integridade.frase()
        n = len(self.ausencias)
        if n == 1:
            frase += " 1 documento que a lei manda publicar não está publicado."
        elif n > 1:
            frase += f" {n} documentos que a lei manda publicar não estão publicados."
        return frase

    def como_dict(self) -> dict:
        return {
            "competencia": self.competencia,
            "alvo": self.alvo,
            "dominio": self.dominio,
            "em_uma_frase": self.em_uma_frase(),
            "contagem": self.contagem(),
            "integridade": self.integridade.como_dict() if self.integridade else None,
            "rio": {
                "total": self.rio.total(),
                "por_esfera": {e.value: v for e, v in self.rio.por_esfera().items()},
                "vinculada_e_livre": self.rio.vinculada_e_livre(),
                "afluentes": [{"nome": a.nome, "esfera": a.esfera.value, "valor": a.valor,
                               "fonte": a.fonte, "selo": a.selo.value if a.selo else None,
                               "origem": a.origem} for a in self.rio.afluentes],
            },
            "margens": self.margens.como_dict() if self.margens else None,
            "pisos": [{"regra": m.regra.id, "titulo": m.regra.titulo, "percentual": m.percentual,
                       "limite": m.limite, "situacao": m.situacao, "declarado": m.declarado,
                       "divergencia": m.divergencia, "selo": m.selo.value if m.selo else None}
                      for m in self.medidas],
            "municipio": None if self.fiscal is None else {
                "rgf": self.fiscal.rgf.rotulo if self.fiscal.rgf else None,
                "rreo": self.fiscal.rreo.rotulo if self.fiscal.rreo else None,
                "tetos": [{"regra": m.regra.id, "titulo": m.regra.titulo, "percentual": m.percentual,
                           "limite": m.limite, "situacao": m.situacao, "declarado": m.declarado,
                           "divergencia": m.divergencia, "selo": m.selo.value if m.selo else None,
                           "memoria": self.fiscal.memoria.get(m.regra.id)}
                          for m in self.fiscal.medidas],
                "duas_vias": [c.como_dict() for c in self.fiscal.conferencias],
                "rio": self.fiscal.rio.como_dict() if self.fiscal.rio is not None else None,
                "notas": self.fiscal.notas,
            },
            "fichas": [f.como_dict() for f in self.fichas_ordenadas()],
            "ausencias": [a.como_dict() for a in self.ausencias],
            "custodia": [o.como_dict() for o in self.custodia],
            "leitura_falhou": self.leitura_falhou,
            "notas": self.notas,
        }
