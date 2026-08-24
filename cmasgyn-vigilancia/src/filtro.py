"""Filtro determinístico — o portão que antecede qualquer chamada ao modelo.

Regras R1, R2 e supressão LGPD na ingestão. Nenhum caractere sobe ao modelo
sem casar aqui, e o que sobe é apenas a janela em torno do acerto.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from util import CONFIG, carregar_yaml, compactar_espacos, log


@dataclass
class Acerto:
    grupo: str
    peso: int
    termo: str
    inicio: int
    fim: int


@dataclass
class Trecho:
    documento: str
    grupos: list[str]
    peso: int
    texto: str
    termos: list[str] = field(default_factory=list)


class Lexico:
    def __init__(self) -> None:
        cfg = carregar_yaml("termos.yml")
        self.janela_padrao = cfg.get("janela_padrao", 1800)
        self.janela_maxima = cfg.get("janela_maxima", 6000)
        self.exigir_ancora = cfg.get("exigir_ancora", True)
        self.ancoras: set[str] = set()
        self.grupos: dict[str, dict] = {}

        for nome, g in cfg["grupos"].items():
            padroes = g.get("padroes", [])
            if g.get("gerado") and g.get("arquivo"):
                padroes = padroes + self._carregar_gerado(g["arquivo"])
            if not padroes:
                continue
            if g.get("ancora"):
                self.ancoras.add(nome)
            self.grupos[nome] = {
                "peso": g.get("peso", 5),
                "janela": g.get("janela", self.janela_padrao),
                "regex": re.compile("|".join(f"(?:{p})" for p in padroes), re.IGNORECASE),
            }

        self.exclusoes = re.compile(
            "|".join(f"(?:{p})" for p in cfg.get("exclusoes", [])), re.IGNORECASE
        ) if cfg.get("exclusoes") else None

        self.redacoes = [
            (re.compile(r["padrao"]), r["substituto"]) for r in cfg.get("redacao_pessoal", [])
        ]

    @staticmethod
    def _carregar_gerado(rel: str) -> list[str]:
        arq = CONFIG.parent / rel
        if not arq.exists():
            log.info("Léxico gerado ainda inexistente: %s", rel)
            return []
        import yaml
        dados = yaml.safe_load(arq.read_text(encoding="utf-8")) or {}
        return dados.get("padroes", [])

    # ------------------------------------------------------------------ LGPD
    def suprimir_pessoais(self, texto: str) -> str:
        """Aplicada na ingestão, antes de persistir e antes de enviar ao modelo.

        Pessoa natural é descartada. Pessoa jurídica, inclusive o CNPJ, é
        preservada: é ela o objeto do controle social.
        """
        for regex, substituto in self.redacoes:
            texto = regex.sub(substituto, texto)
        return texto

    # ---------------------------------------------------------------- acertos
    def localizar(self, texto: str) -> list[Acerto]:
        acertos: list[Acerto] = []
        for nome, g in self.grupos.items():
            for m in g["regex"].finditer(texto):
                if self.exclusoes and self.exclusoes.search(
                    texto[max(0, m.start() - 60): m.end() + 60]
                ):
                    continue
                acertos.append(Acerto(nome, g["peso"], m.group(0), m.start(), m.end()))
        return sorted(acertos, key=lambda a: a.inicio)

    # ---------------------------------------------------------------- recorte
    def recortar(self, documento: str, texto: str) -> list[Trecho]:
        """Funde acertos próximos numa só janela e devolve os trechos."""
        acertos = self.localizar(texto)
        if not acertos:
            return []

        janelas: list[list] = []
        for a in acertos:
            j = self.grupos[a.grupo]["janela"]
            ini, fim = max(0, a.inicio - j), min(len(texto), a.fim + j)
            if janelas and ini <= janelas[-1][1]:
                bloco = janelas[-1]
                bloco[1] = max(bloco[1], fim)
                bloco[2].add(a.grupo)
                bloco[3] = max(bloco[3], a.peso)
                bloco[4].add(a.termo.strip())
            else:
                janelas.append([ini, fim, {a.grupo}, a.peso, {a.termo.strip()}])

        trechos = []
        descartados = 0
        for ini, fim, grupos, peso, termos in janelas:
            # Sem grupo âncora, o acerto é ruído contextual: descarta antes do modelo.
            if self.exigir_ancora and not (grupos & self.ancoras):
                descartados += 1
                continue
            if fim - ini > self.janela_maxima:
                fim = ini + self.janela_maxima
            trechos.append(Trecho(
                documento=documento,
                grupos=sorted(grupos),
                peso=peso,
                texto=compactar_espacos(texto[ini:fim]),
                termos=sorted(termos),
            ))
        log.info("%s: %d acerto(s) -> %d trecho(s) (%d descartado(s) por falta de âncora)",
                 documento, len(acertos), len(trechos), descartados)
        return trechos


def processar(documento: str, texto: str, lexico: Lexico) -> list[Trecho]:
    """Pipeline de ingestão: suprime pessoais, depois recorta."""
    return lexico.recortar(documento, lexico.suprimir_pessoais(texto))
