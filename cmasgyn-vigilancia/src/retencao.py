"""Retenção — regra R10.

Edição do Diário Oficial sem acerto no léxico é apagada após 30 dias.
Permanece somente o que referencia o CMASGyn, suas entidades inscritas ou o
Fundo Municipal de Assistência Social. O acervo do conselho nunca é expurgado:
ele é a base de comparação de hash que denuncia alteração retroativa.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from util import ACERVO, ESTADO, agora, gravar_json, ler_json, log

DIAS_RETENCAO = 30


def expurgar(dias: int = DIAS_RETENCAO, simular: bool = False) -> dict:
    registro = ler_json(ESTADO / "dom_registro.json", {})
    limite = agora().date() - timedelta(days=dias)

    apagados, mantidos, bytes_liberados = 0, 0, 0

    for chave, meta in list(registro.items()):
        if not meta.get("pdf"):
            continue
        try:
            d = date.fromisoformat(chave)
        except ValueError:
            continue
        if d >= limite:
            mantidos += 1
            continue

        if meta.get("relevante"):
            mantidos += 1
            continue

        for campo in ("pdf", "txt"):
            caminho = meta.get(campo)
            if not caminho:
                continue
            arq = ACERVO.parent / caminho
            if arq.exists():
                bytes_liberados += arq.stat().st_size
                if not simular:
                    arq.unlink()
        apagados += 1
        # Preserva-se a lápide: data, URL e hash. A prova de que nada
        # relevante havia ali permanece, ainda que o arquivo não.
        registro[chave] = {
            "data": chave, "url": meta.get("url"), "sha256": meta.get("sha256"),
            "expurgado_em": agora().isoformat(),
            "motivo": "sem referência ao CMASGyn após 30 dias",
        }

    if not simular:
        gravar_json(ESTADO / "dom_registro.json", registro)

    resumo = {
        "apagados": apagados, "mantidos": mantidos,
        "mb_liberados": round(bytes_liberados / 1_048_576, 2),
        "limite": limite.isoformat(), "simulacao": simular,
    }
    log.info("Retenção: %d expurgado(s), %d mantido(s), %.2f MB liberados",
             apagados, mantidos, resumo["mb_liberados"])
    return resumo


def marcar_relevante(data_iso: str, grupos: list[str]) -> None:
    """Chamado pela rotina diária quando a edição casa no léxico."""
    registro = ler_json(ESTADO / "dom_registro.json", {})
    if data_iso in registro:
        registro[data_iso]["relevante"] = True
        registro[data_iso]["grupos"] = grupos
        gravar_json(ESTADO / "dom_registro.json", registro)


if __name__ == "__main__":
    import sys
    expurgar(simular="--simular" in sys.argv)
    sys.exit(0)
