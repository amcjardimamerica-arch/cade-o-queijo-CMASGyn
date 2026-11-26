"""Alvo e domínios: o núcleo não muda, muda o arquivo de configuração."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import RAIZ
from .rio.fontes import classificar

ALVO_PADRAO = RAIZ / "alvos" / "goiania.toml"


@dataclass(frozen=True)
class Dominio:
    id: str
    nome: str
    ativo: bool
    funcao: str
    dados: str
    fontes_vinculadas: tuple[str, ...] = ()
    regras: tuple[str, ...] = ()
    extras: dict = field(default_factory=dict, hash=False, compare=False)

    def problemas(self) -> list[str]:
        erros = []
        if not (len(self.funcao) == 2 and self.funcao.isdigit()):
            erros.append(f"{self.id}: função orçamentária inválida {self.funcao!r}")
        for f in self.fontes_vinculadas:
            fonte = classificar(f)
            if fonte.conhecida and fonte.destinacao and fonte.destinacao.leito \
                    and self.funcao not in fonte.destinacao.leito:
                erros.append(f"{self.id}: a fonte {f} não pode correr para a função {self.funcao}")
        return erros


@dataclass(frozen=True)
class Alvo:
    nome: str
    municipio: str
    uf: str
    ibge: int
    siconfi_id_ente: int
    faixa_camara: str
    orgao_lai: str
    abertura_sessao: tuple[int, int]
    dominios: dict[str, Dominio]

    def ativos(self) -> list[Dominio]:
        return [d for d in self.dominios.values() if d.ativo]


_CAMPOS_DOMINIO = {"id", "nome", "ativo", "funcao", "dados", "fontes_vinculadas", "regras"}


def carregar_dominio(caminho: Path) -> Dominio:
    bruto = tomllib.loads(caminho.read_text(encoding="utf-8"))
    return Dominio(
        id=bruto["id"],
        nome=bruto["nome"],
        ativo=bool(bruto.get("ativo", False)),
        funcao=str(bruto["funcao"]).zfill(2),
        dados=bruto.get("dados", ""),
        fontes_vinculadas=tuple(bruto.get("fontes_vinculadas", ())),
        regras=tuple(bruto.get("regras", ())),
        extras={k: v for k, v in bruto.items() if k not in _CAMPOS_DOMINIO},
    )


def carregar_alvo(caminho: Path | str | None = None) -> Alvo:
    caminho = Path(caminho) if caminho else ALVO_PADRAO
    bruto = tomllib.loads(caminho.read_text(encoding="utf-8"))
    dominios = {}
    for chave, rel in bruto.get("dominios", {}).items():
        dominios[chave] = carregar_dominio(RAIZ / rel)
    mes, dia = bruto.get("abertura_sessao_legislativa", [2, 1])
    return Alvo(
        nome=bruto["nome"],
        municipio=bruto.get("municipio", bruto["nome"]),
        uf=bruto.get("uf", ""),
        ibge=int(bruto["ibge"]),
        siconfi_id_ente=int(bruto.get("siconfi_id_ente", bruto["ibge"])),
        faixa_camara=bruto["faixa_camara"],
        orgao_lai=bruto.get("orgao_lai", ""),
        abertura_sessao=(int(mes), int(dia)),
        dominios=dominios,
    )
