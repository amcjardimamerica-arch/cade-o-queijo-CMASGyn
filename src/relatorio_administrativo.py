"""Relatório administrativo diário, inclusive quando nada é localizado.

Converte o semáforo histórico para estados que distinguem ausência confirmada,
indisponibilidade da fonte e falha inconclusiva. Essa distinção impede que uma
falha técnica seja apresentada como falta de publicação do Município.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from util import RAIZ, RELATORIOS, agora, gravar_json, hoje_iso, ler_json

SERIE = RAIZ / "dados" / "publicacao_diaria.json"

MAPA_ESTADOS = {
    "PUBLICOU": "PUBLICACAO_LOCALIZADA_COM_ATO",
    "SEM_ATO": "PUBLICACAO_LOCALIZADA_SEM_ATO_RELEVANTE",
    "INEXISTENTE": "SEM_EDICAO_CONFIRMADA",
    "FONTE_INDISPONIVEL": "FONTE_INDISPONIVEL",
    "INCONCLUSIVO": "BUSCA_INCONCLUSIVA",
    "NAO_UTIL": "DIA_NAO_UTIL",
}


def normalizar_estado(estado: str | None) -> str:
    return MAPA_ESTADOS.get(estado or "", "BUSCA_INCONCLUSIVA")


def _resultado_publicacao(estado: str) -> tuple[str, str]:
    if estado in ("PUBLICACAO_LOCALIZADA_COM_ATO",
                  "PUBLICACAO_LOCALIZADA_SEM_ATO_RELEVANTE"):
        return "SIM", "SIM" if estado.endswith("COM_ATO") else "NAO"
    if estado == "SEM_EDICAO_CONFIRMADA":
        return "NAO", "NAO"
    if estado == "DIA_NAO_UTIL":
        return "NAO_APLICAVEL", "NAO_APLICAVEL"
    return "INCONCLUSIVO", "INCONCLUSIVO"


def gerar(data_ref: str | None = None) -> dict:
    data_ref = data_ref or hoje_iso()
    serie = ler_json(SERIE, {"dias": {}})
    registro = (serie.get("dias") or {}).get(data_ref, {})
    estado = normalizar_estado(registro.get("situacao"))
    publicacao, ato = _resultado_publicacao(estado)

    faltantes: list[str] = []
    if estado in ("FONTE_INDISPONIVEL", "BUSCA_INCONCLUSIVA"):
        faltantes.append("consulta íntegra e bem-sucedida à fonte oficial")
    if estado == "SEM_EDICAO_CONFIRMADA":
        faltantes.append("certidão ou confirmação oficial de inexistência de edição")
    if estado == "PUBLICACAO_LOCALIZADA_COM_ATO":
        faltantes.append(
            "validação individual da íntegra do ato com competência, motivação e norma vigente"
        )

    documentos = registro.get("documentos") or []
    resultado = (
        "NAO_APLICAVEL" if ato in ("NAO", "NAO_APLICAVEL")
        else "INCONCLUSIVO_POR_DOCUMENTO_FALTANTE"
    )
    dados = {
        "tipo": "fiscalizacao_administrativa_diaria",
        "data_da_apuracao": data_ref,
        "gerado_em": agora().isoformat(),
        "estado_da_coleta": estado,
        "publicacao_no_diario_oficial": publicacao,
        "ato_relevante_encontrado": ato,
        "edicoes_localizadas": registro.get("edicoes", 0),
        "documentos": documentos,
        "resultado_de_conformidade": resultado,
        "documentos_faltantes": faltantes,
        "nota": registro.get("nota"),
        "regra_de_prova": (
            "Falha da fonte não é ausência de publicação. Ato localizado só recebe "
            "conclusão de conformidade após confronto individual com o corpus vigente."
        ),
    }
    gravar_json(RELATORIOS / f"administrativo_diario_{data_ref}.json", dados)
    (RELATORIOS / f"administrativo_diario_{data_ref}.md").write_text(
        markdown(dados), encoding="utf-8"
    )
    return dados


def markdown(d: dict) -> str:
    docs = d.get("documentos") or []
    faltantes = d.get("documentos_faltantes") or []
    linhas = [
        f"# Relatório administrativo diário — {d['data_da_apuracao']}", "",
        "| Verificação | Resultado |", "|---|---|",
        f"| Estado da coleta | {d['estado_da_coleta']} |",
        f"| Houve publicação no Diário Oficial? | {d['publicacao_no_diario_oficial']} |",
        f"| Houve ato relevante? | {d['ato_relevante_encontrado']} |",
        f"| Resultado de conformidade | {d['resultado_de_conformidade']} |", "",
        "## Evidências", "",
    ]
    linhas += [f"- `{x}`" for x in docs] or ["- Nenhum documento registrado."]
    linhas += ["", "## Documentos ou verificações faltantes", ""]
    linhas += [f"- {x}" for x in faltantes] or ["- Nenhuma pendência registrada."]
    linhas += ["", f"> {d['regra_de_prova']}", ""]
    return "\n".join(linhas)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--data")
    args = p.parse_args()
    print(json.dumps(gerar(args.data), ensure_ascii=False, indent=2))
