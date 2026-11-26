"""Mapa legal: as regras que o motor segue.

Cada conferência aponta para uma norma e para um parâmetro testável (um
percentual, um prazo, um valor ou uma obrigação de publicar). Uma regra sem
número não vira indício: vira pergunta no ofício. O mapa fica em
``regras/mapa_legal.yml``, versionado.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path

import yaml

from .. import RAIZ

CAMINHO_PADRAO = RAIZ / "regras" / "mapa_legal.yml"
TIPOS_DE_REGRA = {"minimo", "maximo", "tolerancia", "prazo", "ordem"}
FAMILIAS_VALIDAS = {"RIO", "PISO", "ORC", "VIN", "PRC", "ENT", "PCT", "PES", "CTA", "SIS"}


@dataclass(frozen=True)
class Norma:
    id: str
    area: str
    norma: str
    assunto: str
    parametro: str
    conferencias: tuple[str, ...] = ()
    localizada: bool = True
    revogada: bool = False
    ctresb: tuple[str, ...] = ()
    oficial: tuple[tuple[str, str], ...] = ()

    def links(self, base_ctresb: str) -> list[tuple[str, str]]:
        return [("ctresb/leis", base_ctresb + c) for c in self.ctresb] + list(self.oficial)


@dataclass(frozen=True)
class Regra:
    id: str
    titulo: str
    tipo: str
    norma: str
    familia: str
    gravidade: str
    unidade: str = ""
    base: str = ""
    valor: float | None = None
    fonte_dado: tuple[str, ...] = ()
    extras: dict = field(default_factory=dict, hash=False, compare=False)

    def get(self, chave: str, padrao=None):
        return self.extras.get(chave, padrao)


@dataclass
class MapaLegal:
    versao: str
    base_ctresb: str
    padrao_sileg: str
    regras: dict[str, Regra]
    normas: dict[str, Norma]

    def regra(self, regra_id: str) -> Regra:
        try:
            return self.regras[regra_id]
        except KeyError as erro:
            raise KeyError(f"regra {regra_id!r} não está no mapa legal") from erro

    def normas_da_conferencia(self, codigo: str) -> list[Norma]:
        return [n for n in self.normas.values() if codigo in n.conferencias]

    def vigentes(self) -> list[Norma]:
        """Normas usáveis: o motor confere o campo revogada antes de usar a regra."""
        return [n for n in self.normas.values() if not n.revogada]

    def nao_localizadas(self) -> list[Norma]:
        return [n for n in self.normas.values() if not n.localizada]

    def problemas(self) -> list[str]:
        """Conferência do próprio mapa: toda regra com norma, número e família."""
        erros = []
        for r in self.regras.values():
            if r.tipo not in TIPOS_DE_REGRA:
                erros.append(f"{r.id}: tipo desconhecido {r.tipo!r}")
            if not r.norma:
                erros.append(f"{r.id}: regra sem norma")
            if r.familia not in FAMILIAS_VALIDAS:
                erros.append(f"{r.id}: família desconhecida {r.familia!r}")
            if r.tipo in {"minimo", "maximo", "tolerancia", "prazo"}:
                tem_numero = r.valor is not None or any(
                    isinstance(v, (int, float)) or isinstance(v, dict) for v in r.extras.values()
                )
                if not tem_numero:
                    erros.append(f"{r.id}: regra sem parâmetro testável")
            if r.gravidade not in {"critica", "alta", "media"}:
                erros.append(f"{r.id}: gravidade inválida {r.gravidade!r}")
        for n in self.normas.values():
            for c in n.ctresb:
                if not re.fullmatch(r"[a-z0-9_./-]+\.md", c, flags=re.I):
                    erros.append(f"{n.id}: caminho do ctresb inválido {c!r}")
            for _, url in n.oficial:
                if not url.startswith("https://"):
                    erros.append(f"{n.id}: link oficial sem https {url!r}")
        return erros

    def url_sileg(self, tipo: str, data: date, numero: int) -> str:
        """Endereço previsível de uma norma de Goiânia no Sileg.

        ``tipo`` é ``lo`` (lei ordinária), ``lc`` (lei complementar) ou ``dc`` (decreto).
        """
        if tipo not in {"lo", "lc", "dc"}:
            raise ValueError(f"tipo de norma do Sileg desconhecido: {tipo!r}")
        return self.padrao_sileg.format(ano=data.year, tipo=tipo, data=data.strftime("%Y%m%d"),
                                        numero=int(numero))


_CAMPOS_REGRA = {"id", "titulo", "tipo", "norma", "familia", "gravidade", "unidade", "base",
                 "valor", "fonte_dado"}


def _regra(bruto: dict) -> Regra:
    extras = {k: v for k, v in bruto.items() if k not in _CAMPOS_REGRA}
    valor = bruto.get("valor")
    return Regra(
        id=bruto["id"],
        titulo=bruto.get("titulo", ""),
        tipo=bruto.get("tipo", ""),
        norma=bruto.get("norma", ""),
        familia=bruto.get("familia", ""),
        gravidade=bruto.get("gravidade", ""),
        unidade=bruto.get("unidade", ""),
        base=bruto.get("base", ""),
        valor=float(valor) if valor is not None else None,
        fonte_dado=tuple(bruto.get("fonte_dado") or ()),
        extras=extras,
    )


def _norma(bruto: dict) -> Norma:
    return Norma(
        id=bruto["id"],
        area=bruto.get("area", ""),
        norma=bruto.get("norma", ""),
        assunto=bruto.get("assunto", ""),
        parametro=bruto.get("parametro", ""),
        conferencias=tuple(bruto.get("conferencias") or ()),
        localizada=bool(bruto.get("localizada", True)),
        revogada=bool(bruto.get("revogada", False)),
        ctresb=tuple(bruto.get("ctresb") or ()),
        oficial=tuple((o["nome"], o["url"]) for o in bruto.get("oficial") or ()),
    )


def carregar(caminho: Path | str | None = None) -> MapaLegal:
    caminho = Path(caminho) if caminho else CAMINHO_PADRAO
    return _carregar(str(caminho))


@lru_cache(maxsize=4)
def _carregar(caminho: str) -> MapaLegal:
    bruto = yaml.safe_load(Path(caminho).read_text(encoding="utf-8"))
    regras = [_regra(r) for r in bruto.get("regras", [])]
    normas = [_norma(n) for n in bruto.get("normas", [])]
    ids_r = [r.id for r in regras]
    ids_n = [n.id for n in normas]
    if len(set(ids_r)) != len(ids_r) or len(set(ids_n)) != len(ids_n):
        raise ValueError("mapa legal com identificador repetido")
    return MapaLegal(
        versao=str(bruto.get("versao", "")),
        base_ctresb=bruto["fonte_de_leis"]["base_url"],
        padrao_sileg=bruto["sileg"]["padrao"],
        regras={r.id: r for r in regras},
        normas={n.id: n for n in normas},
    )
