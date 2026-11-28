"""Cadeia de custódia.

O sistema não guarda os documentos: de cada fonte guarda o trecho em texto que
interessa, o link exato onde o encontrou (com edição e página quando é o Diário)
e a impressão digital do que leu naquele dia. Se a fonte mudar, a impressão
prova o que estava lá; se sumir, isso também vira ausência.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from datetime import date


def impressao(conteudo: str | bytes) -> str:
    """Impressão digital (sha256) de um texto ou de bytes."""
    if isinstance(conteudo, str):
        conteudo = conteudo.encode("utf-8")
    return hashlib.sha256(conteudo).hexdigest()


@dataclass(frozen=True)
class Original:
    url: str
    coletado_em: str
    sha256: str
    trecho: str = ""
    pagina: int | None = None
    edicao: str | None = None
    fonte: str = ""
    # Rastreio por hash (onisciente.rastreio): o hash do registro em que o achado se apoia (para uma
    # coleta, o da linha em ``coletas``, que cobre a resposta e a requisição) e o hash da requisição.
    registro: str = ""
    requisicao: str = ""

    @property
    def rastreio(self) -> str:
        """O hash para conferência: o do registro quando há, senão o da resposta (sha256)."""
        return self.registro or self.sha256

    @classmethod
    def de_texto(
        cls,
        url: str,
        texto: str,
        *,
        trecho: str = "",
        coletado_em: str | None = None,
        **extra,
    ) -> "Original":
        return cls(
            url=url,
            coletado_em=coletado_em or date.today().isoformat(),
            sha256=impressao(texto),
            trecho=trecho,
            **extra,
        )

    def confere(self, conteudo: str | bytes) -> bool:
        """True se o conteúdo lido agora é o mesmo que foi guardado."""
        return impressao(conteudo) == self.sha256

    def como_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v not in (None, "")}
