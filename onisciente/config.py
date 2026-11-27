"""Alvo e domínios: o núcleo não muda, muda o arquivo de configuração.

Um alvo (``alvos/*.toml``) diz qual é o ente: nome, código do IBGE, faixa da Câmara, os órgãos
no PNCP e os domínios (``dominios/*.toml``). Um domínio é uma secretaria vista pela trilha: as
funções e subfunções orçamentárias que a recortam (o ``recorte``), as fontes vinculadas que só
podem correr para ela, os pisos que mede e o indicador de qualidade do plano municipal da pasta.
Trocar de município é trocar o arquivo do alvo: nenhuma linha de código muda.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field, replace
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
    # Funções e subfunções da secretaria: "10" é a função inteira; "15.452" só a subfunção 452
    # da função 15. Sem recorte, o domínio é a função principal inteira.
    recorte: tuple[str, ...] = ()
    orgaos: tuple[str, ...] = ()          # termos do nome dos órgãos da pasta (PNCP, portal)

    @property
    def recortes(self) -> tuple[tuple[str, str | None], ...]:
        """(função, subfunção ou None) de cada pedaço do domínio."""
        itens = self.recorte or (self.funcao,)
        out = []
        for r in itens:
            funcao, _, sub = str(r).partition(".")
            out.append((funcao.zfill(2), sub.zfill(3) if sub else None))
        return tuple(out)

    @property
    def funcoes(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(f for f, _ in self.recortes))

    def contem(self, funcao: str | None, subfuncao: str | None = None) -> bool:
        """Se uma despesa da função e subfunção dadas é do domínio."""
        f = str(funcao or "").zfill(2)
        s = str(subfuncao or "").zfill(3) if subfuncao else None
        return any(f == rf and (rs is None or rs == s) for rf, rs in self.recortes)

    @property
    def qualidade(self) -> dict:
        return dict(self.extras.get("qualidade") or {})

    def problemas(self) -> list[str]:
        erros = []
        if not (len(self.funcao) == 2 and self.funcao.isdigit()):
            erros.append(f"{self.id}: função orçamentária inválida {self.funcao!r}")
        for r in self.recorte:   # escrito como no toml: "10" (função) ou "15.452" (função.subfunção)
            if not re.fullmatch(r"\d{2}(\.\d{3})?", str(r)):
                erros.append(f"{self.id}: recorte inválido {r!r} (use \"10\" ou \"15.452\")")
        if self.funcao not in self.funcoes:
            erros.append(f"{self.id}: a função principal {self.funcao} não está no recorte")
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
    pncp_cnpjs: tuple[str, ...] = ()
    portal_despesa: str = ""              # configuração do coletor da execução item a item
    arquivo: str = ""                     # o arquivo do alvo, para o parecer dizer de onde veio

    def ativos(self) -> list[Dominio]:
        return [d for d in self.dominios.values() if d.ativo]


_CAMPOS_DOMINIO = {"id", "nome", "ativo", "funcao", "dados", "fontes_vinculadas", "regras", "recorte", "orgaos"}


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
        recorte=tuple(str(r) for r in bruto.get("recorte", ())),
        orgaos=tuple(str(o) for o in bruto.get("orgaos", ())),
        extras={k: v for k, v in bruto.items() if k not in _CAMPOS_DOMINIO},
    )


def carregar_alvo(caminho: Path | str | None = None) -> Alvo:
    caminho = Path(caminho) if caminho else ALVO_PADRAO
    bruto = tomllib.loads(caminho.read_text(encoding="utf-8"))
    dominios = {}
    nomes = bruto.get("nomes_dominios", {})   # o nome local da pasta, se o ente a chama de outro jeito
    for chave, rel in bruto.get("dominios", {}).items():
        d = carregar_dominio(RAIZ / rel)
        dominios[chave] = replace(d, nome=str(nomes[chave])) if chave in nomes else d
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
        pncp_cnpjs=tuple(str(c) for c in bruto.get("pncp_cnpjs", ())),
        portal_despesa=str(bruto.get("portal_despesa", "")),
        arquivo=str(caminho),
    )
