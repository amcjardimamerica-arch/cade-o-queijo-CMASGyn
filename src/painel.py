"""Gera docs/dados.json, que alimenta a tabela interativa publicada no Pages.

Um único arquivo, servido estaticamente. Nenhuma consulta externa, nenhum
token gasto para visualizar.
"""
from __future__ import annotations

import gzip
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import atas as mod_atas
import biblioteca as mod_bib
import financeiro as mod_fin
import trilha as mod_tri
import verificacao_dupla as mod_vd
import publicacao_diaria as mod_pd
import yaml
import cobertura as mod_cob
import padroes as mod_pad
from busca_local import conectar
from util import ESTADO, RAIZ, agora, ler_json, log

DOCS = RAIZ / "docs"
TXTGZ = RAIZ / "acervo" / "historico" / "txt_gz"

RE_ATA = re.compile(r"ATA\s+D[AO]\s+.{0,60}(REUNI[ÃA]O|PLEN[ÁA]RIA|SESS[ÃA]O)", re.I)
RE_BLOCO_CMAS = re.compile(
    r".{0,2500}(CMASGyn|CMAS/?GYN|Conselho Municipal de Assist[êe]ncia Social).{0,2500}",
    re.I | re.S)


def _texto(nome: str) -> str:
    p = TXTGZ / f"{nome[:-4]}.txt.gz"
    if not p.exists():
        return ""
    return gzip.decompress(p.read_bytes()).decode("utf-8", errors="ignore")


def construir() -> dict:
    c = conectar()
    docs = c.execute(
        "SELECT nome, data, ano, edicao, url, sha256, bytes, caracteres, ocr, termos "
        "FROM documentos ORDER BY data DESC").fetchall()

    linhas, textos_cmas, textos_ata = [], [], []
    for nome, data, ano, edicao, url, sha, bytes_, chars, ocr, termos in docs:
        t = _texto(nome)
        blocos = RE_BLOCO_CMAS.findall(t) if t else []
        mencoes = len(re.findall(r"CMASGyn|Conselho Municipal de Assist[êe]ncia Social", t, re.I))
        eh_ata = bool(RE_ATA.search(t)) if t else False
        if t and mencoes:
            recorte = "\n\n[…]\n\n".join(
                m.group(0) for m in list(RE_BLOCO_CMAS.finditer(t))[:4])
            textos_cmas.append((nome, data, recorte))
        if eh_ata:
            textos_ata.append((nome, data, t))
        linhas.append({
            "nome": nome, "data": data, "ano": ano, "edicao": edicao, "url": url,
            "sha256": sha, "digest": sha[:12], "mb": round((bytes_ or 0) / 1e6, 1),
            "caracteres": chars, "ocr": bool(ocr),
            "termos": json.loads(termos or "[]"),
            "mencoes_cmas": mencoes, "ata": eh_ata,
        })

    achados_atas, painel_conselheiros = mod_atas.processar_lote(textos_ata)
    padrao = mod_pad.analisar_acervo(textos_cmas)

    datas = [l["data"] for l in linhas] or [agora().date().isoformat()]
    ids = {f"_{d.replace('-', '')}_" for d in datas}
    cob = mod_cob.auditar(date.fromisoformat(min(datas)),
                          date.fromisoformat(max(datas)), ids)

    achados_bd = [dict(zip(
        ["regra", "severidade", "titulo", "detalhe", "documento", "data_ref", "detectado_em"], r))
        for r in c.execute(
            "SELECT regra,severidade,titulo,detalhe,documento,data_ref,detectado_em "
            "FROM achados ORDER BY CASE severidade WHEN 'alta' THEN 0 "
            "WHEN 'media' THEN 1 ELSE 2 END, data_ref DESC").fetchall()]
    c.close()

    try:
        bib = mod_bib.construir("assistencia_social")
        dom = yaml.safe_load((RAIZ / "config" / "dominios" /
                              "assistencia_social.yml").read_text(encoding="utf-8"))
        fin = mod_fin.conciliar(dom)
        tri = mod_tri.mapear(dom)
        vd = ler_json(RAIZ / 'dados' / 'verificacao_dupla.json', {})
        pdz = ler_json(RAIZ / 'dados' / 'publicacao_diaria.json', {})
    except Exception as e:
        log.error("Biblioteca ou financeiro falharam: %s", e)
        bib, fin, tri, vd, pdz = {}, {}, {}, {}, {}

    achados = (achados_bd + achados_atas
               + (mod_bib.achados(bib) if bib else [])
               + (mod_fin.achados(fin) if fin else [])
               + (tri.get('indicios') if tri else [])
               + (mod_vd.achados(vd) if vd else [])
               + (mod_pd.achados(pdz) if pdz else []))
    ordem = {"alta": 0, "media": 1, "baixa": 2}
    achados.sort(key=lambda a: (ordem.get(a.get("severidade"), 3), a.get("data_ref") or ""))

    fita = [{"data": x, "situacao": s} for x, s in
            [(d, "coletado") for d in sorted(datas)]]
    for lac in cob["lacunas"]:
        fita.append({"data": lac["data"], "situacao": lac["situacao"]})
    fita.sort(key=lambda x: x["data"])

    dados = {
        "gerado_em": agora().isoformat(),
        "periodo": [min(datas), max(datas)],
        "edicoes": linhas,
        "achados": achados,
        "conselheiros": painel_conselheiros["conselheiros"],
        "atas_analisadas": painel_conselheiros["atas_analisadas"],
        "padrao": padrao,
        "cobertura": {k: cob[k] for k in
                      ("dias_uteis", "resumo", "indice_cobertura", "lacunas")},
        "fita": fita,
        "biblioteca": {k: bib.get(k) for k in
                       ("total_atos", "situacoes", "por_ano", "indice_de_publicidade",
                        "presumidos_por_lacuna", "classes_frequentes")} if bib else {},
        "nao_divulgados": (bib.get("nao_divulgados") or [])[:600] if bib else [],
        "atos": [{k: a[k] for k in ("chave", "numero", "ano", "situacao", "ementa",
                                    "classes", "n_publicacoes", "n_citacoes",
                                    "primeira_aparicao")}
                 for a in (bib.get("atos") or [])] if bib else [],
        "financeiro": {k: fin.get(k) for k in
                       ("linhas", "valor_total", "valor_classificado",
                        "indice_rastreabilidade", "para_entidades_privadas",
                        "por_ente", "por_ano", "por_acao", "por_natureza",
                        "fontes_pendentes")} if fin else {},
        "trilha": {k: tri.get(k) for k in
                   ("eventos", "cobertura_das_estacoes", "rupturas",
                    "integridade_da_trilha", "entidades", "entidades_identificadas",
                    "valor_associado_a_entidades", "contratos_localizados",
                    "nota_metodologica", "catalogo_de_indicios")} if tri else {},
        "verificacao": {k: vd.get(k) for k in
                        ("atos_verificados", "desfechos", "concordancia",
                         "nao_publicados_confirmados", "fila_de_conferencia_humana")} if vd else {},
        "semaforo": pdz if pdz else {},
        "resumo": {
            "edicoes": len(linhas),
            "com_mencao_cmas": sum(1 for l in linhas if l["mencoes_cmas"]),
            "atas": sum(1 for l in linhas if l["ata"]),
            "achados_altos": sum(1 for a in achados if a.get("severidade") == "alta"),
            "achados": len(achados),
            "cobertura": cob["indice_cobertura"],
            "caracteres": sum(l["caracteres"] or 0 for l in linhas),
            "atos_identificados": bib.get("total_atos", 0) if bib else 0,
            "indice_publicidade": bib.get("indice_de_publicidade", 0) if bib else 0,
            "valor_rastreado": fin.get("valor_total", 0) if fin else 0,
        },
    }

    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "dados.json").write_text(
        json.dumps(dados, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (RAIZ / "relatorios" / "correicao.md").write_text(
        mod_cob.relatorio_markdown(cob), encoding="utf-8")
    log.info("Painel: %d edições, %d achados, cobertura de %.2f%%",
             len(linhas), len(achados), cob["indice_cobertura"])
    return dados["resumo"]


if __name__ == "__main__":
    print(json.dumps(construir(), ensure_ascii=False, indent=2))
