"""Orçamento de tokens: teto de 50% do limite e retomada automática.

Regra R9. O agente para ao consumir metade do limite da janela corrente,
enfileira o que restou e reagenda a execução para o instante da renovação.
Nada se perde: a fila é ordenada por peso do grupo, severidade e data.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from util import ESTADO, agora, anexar_jsonl, gravar_json, ler_json, log

ARQ_ORCAMENTO = ESTADO / "orcamento.json"
ARQ_FILA = ESTADO / "fila_pendente.jsonl"
ARQ_RETOMADA = ESTADO / "retomar_em.json"


class LimiteAtingido(Exception):
    """Sinaliza que o teto de 50% foi alcançado. Não é erro: é parada planejada."""


@dataclass
class Orcamento:
    limite_janela: int              # tokens da janela, vindo de config ou do cabeçalho
    fracao_maxima: float = 0.50
    rateio: dict | None = None

    def __post_init__(self) -> None:
        est = ler_json(ARQ_ORCAMENTO, {})
        janela = est.get("janela")
        if janela != self._janela_corrente():
            est = {"janela": self._janela_corrente(), "consumo": {}, "total": 0}
        self.estado = est
        self.rateio = self.rateio or {
            "triagem": 0.15, "extracao": 0.25, "validacao": 0.50, "redacao": 0.10
        }

    # ------------------------------------------------------------------ janela
    @staticmethod
    def _janela_corrente() -> str:
        """Identificador da janela de renovação. Aqui: hora cheia UTC."""
        return agora().strftime("%Y-%m-%dT%H")

    @property
    def teto(self) -> int:
        return int(self.limite_janela * self.fracao_maxima)

    def teto_do_nivel(self, nivel: str) -> int:
        return int(self.teto * self.rateio.get(nivel, 0.25))

    def consumido(self, nivel: str | None = None) -> int:
        if nivel:
            return self.estado["consumo"].get(nivel, 0)
        return self.estado.get("total", 0)

    def restante(self) -> int:
        return max(self.teto - self.consumido(), 0)

    # ------------------------------------------------------------- contabilidade
    def pode_gastar(self, nivel: str, estimativa: int) -> bool:
        if self.consumido() + estimativa > self.teto:
            return False
        if self.consumido(nivel) + estimativa > self.teto_do_nivel(nivel):
            log.info("Cota do nível %s esgotada; realocando para a próxima janela", nivel)
            return False
        return True

    def registrar(self, nivel: str, tokens: int) -> None:
        self.estado["consumo"][nivel] = self.estado["consumo"].get(nivel, 0) + tokens
        self.estado["total"] = self.estado.get("total", 0) + tokens
        gravar_json(ARQ_ORCAMENTO, self.estado)
        if self.estado["total"] >= self.teto:
            raise LimiteAtingido(
                f"Teto de {self.fracao_maxima:.0%} atingido "
                f"({self.estado['total']}/{self.limite_janela} tokens)"
            )

    # ------------------------------------------------------------------- fila
    @staticmethod
    def enfileirar(item: dict) -> None:
        anexar_jsonl(ARQ_FILA, item)

    @staticmethod
    def drenar_fila(limite: int | None = None) -> list[dict]:
        if not ARQ_FILA.exists():
            return []
        itens = [json.loads(l) for l in ARQ_FILA.read_text(encoding="utf-8").splitlines() if l.strip()]
        itens.sort(
            key=lambda i: (-i.get("peso", 0), -i.get("severidade_num", 0), i.get("data", "")),
        )
        if limite:
            restante, itens = itens[limite:], itens[:limite]
            ARQ_FILA.write_text(
                "\n".join(json.dumps(i, ensure_ascii=False) for i in restante) + ("\n" if restante else ""),
                encoding="utf-8",
            )
        else:
            ARQ_FILA.unlink()
        return itens

    # --------------------------------------------------------------- retomada
    @staticmethod
    def agendar_retomada(reset_em: datetime | None = None, margem_s: int = 120) -> None:
        """Grava o instante de retomada lido dos cabeçalhos de limite da API."""
        alvo = (reset_em or (agora() + timedelta(hours=1))) + timedelta(seconds=margem_s)
        gravar_json(ARQ_RETOMADA, {
            "retomar_em": alvo.isoformat(),
            "gravado_em": agora().isoformat(),
        })
        log.warning("Execução suspensa. Retomada agendada para %s", alvo.isoformat())

    @staticmethod
    def pronto_para_retomar() -> bool:
        est = ler_json(ARQ_RETOMADA, {})
        if not est:
            return True
        try:
            alvo = datetime.fromisoformat(est["retomar_em"])
        except (KeyError, ValueError):
            return True
        return agora() >= alvo

    @staticmethod
    def limpar_retomada() -> None:
        Path(ARQ_RETOMADA).unlink(missing_ok=True)


def reset_dos_cabecalhos(headers) -> datetime | None:
    """Extrai o instante de renovação dos cabeçalhos anthropic-ratelimit-*-reset."""
    for chave in (
        "anthropic-ratelimit-input-tokens-reset",
        "anthropic-ratelimit-output-tokens-reset",
        "anthropic-ratelimit-tokens-reset",
        "anthropic-ratelimit-requests-reset",
    ):
        valor = headers.get(chave)
        if valor:
            try:
                return datetime.fromisoformat(valor.replace("Z", "+00:00"))
            except ValueError:
                continue
    retry = headers.get("retry-after")
    if retry:
        try:
            return agora() + timedelta(seconds=int(retry))
        except ValueError:
            pass
    return None
