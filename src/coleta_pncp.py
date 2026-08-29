#!/usr/bin/env python3
"""Trilha do Queijo · contratações — PNCP (Portal Nacional de Contratações
Públicas, Lei 14.133/2021, Artigo 174) e, por descoberta, compras.gov.

Busca contratos do Município de Goiânia no período, filtra os da pasta da
assistência (unidade/órgão contendo os termos configurados) e grava com
âncora (id PNCP + hash do registro). Q2: dispensa/inexigibilidade sem o
documento correspondente vira observação de EXCLUDENTE LEGAL AUSENTE.
Camada 0. Falha de fonte degrada limpo e fica registrada.
"""
from __future__ import annotations
import hashlib, json, sys
from datetime import date
from pathlib import Path
import requests

RAIZ = Path(__file__).resolve().parent.parent
requests.packages.urllib3.disable_warnings()
S = requests.Session(); S.verify = False
S.headers.update({"User-Agent": "AMC-Jardim-America-Vigilancia/1.0",
                  "Accept": "application/json"})
BASE = "https://pncp.gov.br/api/consulta/v1/contratos"
TERMOS_PASTA = ("ASSISTENCIA SOCIAL", "SEMAS", "FUNDO MUNICIPAL DE ASSISTENCIA",
                "DIREITOS HUMANOS", "POLITICAS PARA AS MULHERES")


def pagina(dt1, dt2, pg, cnpj=None):
    par = {"dataInicial": dt1, "dataFinal": dt2, "pagina": pg,
           "tamanhoPagina": 50}
    if cnpj:
        par["cnpjOrgao"] = cnpj
    r = S.get(BASE, params=par, timeout=45)
    r.raise_for_status()
    return r.json()


def main():
    ano = date.today().year
    dt1, dt2 = f"{ano}0101", f"{ano}1231"
    # CNPJs do próprio Município já capturados pela triagem de cabeçalhos
    dest = json.loads((RAIZ / "dados" / "destinatarios_2026.json")
                      .read_text(encoding="utf-8"))
    cnpjs_ente = sorted({d["cnpj"] for d in dest["destinatarios"]
                         if "MUNICIPIO DE GOIANIA" in
                         (d.get("razao_social") or "").upper()
                         or "PREFEITURA" in (d.get("razao_social") or "").upper()})
    contratos, erro = [], None
    try:
        alvos = cnpjs_ente or [None]
        for cnpj in alvos:
            pg = 1
            while pg <= 20:
                d = pagina(dt1, dt2, pg, cnpj and cnpj.replace(".", "")
                           .replace("/", "").replace("-", ""))
                itens = d.get("data") or d.get("itens") or []
                if not itens:
                    break
                for it in itens:
                    orgao = json.dumps(it, ensure_ascii=False).upper()
                    if cnpj is None and "GOIANIA" not in orgao:
                        continue
                    da_pasta = any(t in orgao for t in TERMOS_PASTA)
                    reg = {
                        "pncp_id": it.get("numeroControlePNCP")
                        or it.get("numeroControlePncp"),
                        "objeto": (it.get("objetoContrato")
                                   or it.get("objeto") or "")[:400],
                        "fornecedor": it.get("nomeRazaoSocialFornecedor")
                        or (it.get("fornecedor") or {}).get("nome"),
                        "cnpj_fornecedor": it.get("niFornecedor")
                        or (it.get("fornecedor") or {}).get("ni"),
                        "valor": it.get("valorGlobal")
                        or it.get("valorInicial"),
                        "vigencia_inicio": it.get("dataVigenciaInicio"),
                        "modalidade": it.get("modalidadeNome")
                        or it.get("modalidade"),
                        "da_pasta_assistencia": da_pasta,
                        "orgao": (it.get("orgaoEntidade") or {}).get(
                            "razaoSocial") or it.get("nomeOrgao"),
                        "unidade": (it.get("unidadeOrgao") or {}).get(
                            "nomeUnidade"),
                    }
                    reg["sha256_registro"] = hashlib.sha256(
                        json.dumps(reg, sort_keys=True,
                                   ensure_ascii=False).encode()).hexdigest()
                    mod = (reg["modalidade"] or "").upper()
                    if "DISPENSA" in mod or "INEXIGIBILIDADE" in mod:
                        reg["observacao_q2"] = (
                            "EXCLUDENTE LEGAL A COMPROVAR: contratação "
                            "direta exige o ato de ratificação e o "
                            "instrumento do Artigo 72 (dispensa) ou do "
                            "Artigo 74 (inexigibilidade) da Lei "
                            "14.133/2021 — ausência do documento é "
                            "observação de excludente legal ausente")
                    contratos.append(reg)
                if d.get("totalPaginas") and pg >= d["totalPaginas"]:
                    break
                pg += 1
    except Exception as e:
        erro = f"{type(e).__name__}: {str(e)[:140]}"
    saida = {"coletado_em": date.today().isoformat(),
             "fonte": BASE, "cnpjs_do_ente_usados": cnpjs_ente,
             "total": len(contratos),
             "da_pasta": sum(1 for c in contratos
                             if c["da_pasta_assistencia"]),
             "erro_de_coleta": erro, "contratos": contratos}
    (RAIZ / "dados" / "pncp_contratos.json").write_text(
        json.dumps(saida, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  PNCP: {len(contratos)} contratos do ente "
          f"({saida['da_pasta']} da pasta) | erro: {erro or 'nenhum'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
