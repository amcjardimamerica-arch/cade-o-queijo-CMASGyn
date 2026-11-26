"""Página do banco histórico no site (docs/onisciente/banco/).

A página em si é fixa (onisciente/parecer/modelo_banco.html) e lê três arquivos de dados
escritos aqui a partir do banco e do diagnóstico: ``dados.json`` (contagens, régua de meses,
achados, repasses do FNAS, SICONFI), ``contratos.json`` e ``contratacoes.json`` (PNCP, um
registro por linha). Cada rodada da coleta histórica reescreve os dados; nada aqui vai à rede.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from . import RAIZ
from .diagnostico import meses_pncp_lidos
from .historico import Banco

DESTINO = RAIZ / "docs" / "onisciente" / "banco"
MODELO = Path(__file__).parent / "parecer" / "modelo_banco.html"
LIMITE_OBJETO = 400


def _limpa(texto) -> str:
    return " ".join(str(texto or "").split())


def _linhas(con, sql: str) -> list[dict]:
    cursor = con.execute(sql)
    nomes = [c[0] for c in cursor.description]
    return [dict(zip(nomes, r)) for r in cursor]


def _por_linha(registros: list[list]) -> str:
    return "[\n" + ",\n".join(json.dumps(r, ensure_ascii=False) for r in registros) + "\n]\n"


def dados(banco: Banco, diagnostico: dict) -> tuple[dict, list[list], list[list]]:
    con = banco.con
    contratos = [[r["pncp_id"], r["mes"], r["data_assinatura"], _limpa(r["orgao"]),
                  _limpa(r["fornecedor"]), r["fornecedor_ni"], _limpa(r["objeto"])[:LIMITE_OBJETO],
                  round(r["valor_global"] or 0, 2), int(r["da_pasta"] or 0)]
                 for r in _linhas(con, "SELECT * FROM contratos_pncp "
                                       "ORDER BY valor_global DESC, pncp_id")]
    contratacoes = [[r["pncp_id"], r["mes"], _limpa(r["modalidade"]), _limpa(r["orgao"]),
                     _limpa(r["objeto"])[:LIMITE_OBJETO], round(r["valor_estimado"] or 0, 2),
                     round(r["valor_homologado"] or 0, 2), _limpa(r["situacao"])]
                    for r in _linhas(con, "SELECT * FROM contratacoes_pncp ORDER BY "
                                          "COALESCE(NULLIF(valor_homologado, 0), valor_estimado) DESC, "
                                          "pncp_id")]
    meta = {r["chave"]: r["valor"] for r in _linhas(con, "SELECT chave, valor FROM meta")}
    resumo = {
        "intervalo": diagnostico["intervalo"], "rodada": diagnostico["rodada"],
        "meses": diagnostico["meses"], "motores": diagnostico["motores"],
        "cobertura": diagnostico["cobertura"], "achados": diagnostico["achados"],
        "contagens": diagnostico.get("contagens", {}),
        "fnas_mes": _linhas(con, "SELECT competencia AS mes, ROUND(SUM(valor), 2) AS valor, "
                                 "COUNT(*) AS linhas FROM repasses_fnas GROUP BY competencia "
                                 "ORDER BY competencia"),
        "fnas_bloco": _linhas(con, "SELECT bloco, ROUND(SUM(valor), 2) AS valor, COUNT(*) AS linhas "
                                   "FROM repasses_fnas GROUP BY bloco ORDER BY 2 DESC"),
        "siconfi": _linhas(con, "SELECT demonstrativo, exercicio, periodo, rotulo, prazo, situacao, "
                                "itens, anexos FROM siconfi_periodos "
                                "ORDER BY exercicio, demonstrativo, periodo"),
        "diario": _linhas(con, "SELECT fonte, mes, edicoes, com_termos FROM diario_oficial_mes "
                               "ORDER BY fonte, mes"),
        "orgaos_contratos": _linhas(con, "SELECT orgao, COUNT(*) AS n, ROUND(SUM(valor_global), 2) "
                                         "AS valor FROM contratos_pncp GROUP BY orgao ORDER BY 3 DESC"),
        "pncp": {"orgaos_conhecidos": len(json.loads(meta.get("pncp_orgaos") or "[]")),
                 "janelas_lidas": len(json.loads(meta.get("pncp_janelas") or "[]")),
                 "procura": json.loads(meta.get("pncp_procura") or "[]"),
                 "meses_completos": sorted(meses_pncp_lidos(banco, diagnostico["meses"])[0])},
    }
    return resumo, contratos, contratacoes


def gerar(banco: Banco, diagnostico: dict, destino: Path = DESTINO) -> list[Path]:
    """Escreve a página do banco e os seus dados; devolve os arquivos escritos."""
    resumo, contratos, contratacoes = dados(banco, diagnostico)
    destino.mkdir(parents=True, exist_ok=True)
    arquivos = [destino / "index.html", destino / "dados.json",
                destino / "contratos.json", destino / "contratacoes.json"]
    shutil.copyfile(MODELO, arquivos[0])
    arquivos[1].write_text(json.dumps(resumo, ensure_ascii=False) + "\n", encoding="utf-8")
    arquivos[2].write_text(_por_linha(contratos), encoding="utf-8")
    arquivos[3].write_text(_por_linha(contratacoes), encoding="utf-8")
    return arquivos
