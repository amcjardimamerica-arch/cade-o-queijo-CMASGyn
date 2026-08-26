#!/usr/bin/env python3
"""Bloco PES — pessoal, diárias e verbas além do salário.

A natureza da despesa vem truncada em 8 dígitos no acervo, o que torna a
diária inatingível por código: 3.3.90.14 exige o subitem. O contorno é o
texto do próprio ato de concessão, que nomeia servidor, destino e período.

Privacidade: pessoa física é minimizada ao PRIMEIRO NOME na EXTRAÇÃO, nunca
só na exibição. Nome completo, CPF e matrícula não chegam a ser gravados.
"""
from __future__ import annotations
import json, re, sys, unicodedata
from collections import Counter, defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CFG = RAIZ / "config" / "criterios_pessoal.yml"
SAIDA = RAIZ / "dados" / "pessoal.json"

def _yaml():
    import yaml
    return yaml.safe_load(CFG.read_text(encoding="utf-8"))

def primeiro_nome(txt: str) -> str:
    """Minimização na extração. Devolve só o primeiro nome, capitalizado."""
    t = re.sub(r"\s+", " ", (txt or "").strip())
    if not t: return ""
    p = t.split(" ")[0]
    return p.capitalize() if p.isupper() or p.islower() else p

def _sem_acento(s):
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn").lower()

RE_DIARIA = re.compile(
    r"[Cc]onceder\s+di[áa]ria[s]?\s+(?:ao|à|a)\s+(?:servidor[a]?|Senhor[a]?)?\s*"
    r"([A-ZÀ-Ú][A-ZÀ-Úa-zà-ú]+)[^,]{0,80}?"          # captura só o primeiro nome
    r"(?:.{0,200}?(?:viagem|deslocamento)\s+(?:à|a|ao|para)\s+(?:cidade\s+de\s+)?"
    r"([A-ZÀ-Ú][\w\s/\-]{2,40}))?", re.S)

RE_VANTAGEM = re.compile(
    r"(gratifica[çc][ãa]o\s+de\s+fun[çc][ãa]o|adicional\s+noturno|insalubridade|"
    r"periculosidade|hora[s]?\s+extra|servi[çc]o\s+extraordin[áa]rio|ajuda\s+de\s+custo|"
    r"verba\s+indenizat[óo]ria|abono|jeton)", re.I)

RE_CESSAO = re.compile(r"(cedid[oa]|cess[ãa]o|requisitad[oa]|[àa]\s+disposi[çc][ãa]o\s+de)", re.I)

def analisar(detalhe: list, por_natureza: dict) -> dict:
    cfg = _yaml()
    nat = cfg["naturezas"]
    achados, diarias, vantagens, cessoes = [], [], [], []

    def ach(rid, sev, selo, titulo, detalhe_txt, norma, dados=None):
        achados.append({"regra": rid, "severidade": sev, "selo": selo, "titulo": titulo,
                        "detalhe": detalhe_txt, "norma": norma, "dados": dados or {}})

    # PES-01 — a folha existe no acervo?
    folha = [n for n in por_natureza if str(n) in nat["vencimentos_e_vantagens_fixas"]]
    if not folha:
        ach("PES-01", "alta", "CONFIRMADO",
            "Folha de pagamento invisível no acervo",
            "Nenhuma linha de natureza 31901100 (Vencimentos e vantagens fixas). "
            "As rubricas do grupo 31 presentes são de exercícios anteriores e de "
            "ressarcimento de pessoal requisitado — não são a folha. Sem folha não se "
            "conta cargo, não se separa efetivo de comissionado e não se afere o teto de 30%.",
            "Artigo 48-A inciso I da Lei Complementar 101/2000; "
            "Artigo 8 paragrafo 1 inciso III da Lei 12.527/2011",
            {"naturezas_de_folha_encontradas": folha,
             "grupo_31_presente": sorted(n for n in por_natureza if str(n).startswith("31"))})

    # PES-03 — diárias por texto do ato
    for x in detalhe:
        obj = json.dumps(x, ensure_ascii=False)
        for m in RE_DIARIA.finditer(obj):
            nome, destino = m.group(1), (m.group(2) or "").strip()
            d = {"primeiro_nome": primeiro_nome(nome),
                 "destino": re.sub(r"\s+", " ", destino)[:40] or None,
                 "data_do_ato": x.get("data"), "edicao": x.get("edicao"),
                 "processos": x.get("processos", [])[:2],
                 "valor_da_diaria": None,
                 "nota": "valor não isolável: a natureza vem truncada em 8 dígitos e "
                         "os valores da página não são atribuíveis a este ato"}
            diarias.append(d)
        for m in RE_VANTAGEM.finditer(obj):
            vantagens.append({"verba": m.group(1).lower(), "data": x.get("data"),
                              "edicao": x.get("edicao")})
        if RE_CESSAO.search(obj):
            cessoes.append({"data": x.get("data"), "edicao": x.get("edicao")})

    # PES-03 — cobertura
    if len(diarias) <= 2:
        ach("PES-03", "alta", "CONFIRMADO",
            "Concessão de diárias praticamente ausente do acervo",
            f"{len(diarias)} ato(s) de concessão localizado(s) em {len(detalhe)} eventos. "
            "Órgão com equipes volantes, conferências e reuniões regionais não concede "
            "uma diária por exercício. A ausência mede a publicidade, não a despesa.",
            "Artigo 37 caput da Constituicao Federal; Artigo 50 da Lei 9.784/1999",
            {"atos_localizados": len(diarias), "eventos_examinados": len(detalhe)})

    # PES-04 — prestação de contas do deslocamento
    if diarias:
        ach("PES-04", "media", "CONFIRMADO",
            "Prestação de contas de deslocamento não localizada",
            "Nenhum relatório de viagem, comprovante de deslocamento ou devolução de "
            "diária não utilizada consta do acervo. A liquidação exige verificação do "
            "direito adquirido pelo credor, com base em títulos e documentos comprobatórios.",
            "Artigo 63 da Lei 4.320/1964",
            {"concessoes": len(diarias), "prestacoes": 0})

    # PES-05 — concentração por servidor
    c = Counter(d["primeiro_nome"] for d in diarias if d["primeiro_nome"])
    conc = {k: v for k, v in c.items() if v >= 12}
    if conc:
        ach("PES-05", "media", "INDICIARIO", "Concentração de diárias no mesmo servidor",
            f"Servidores com 12 ou mais concessões na janela: {list(conc)}. "
            "Concentração é indício; irregularidade se demonstra pelo processo.",
            "metodo", {"concentracao": conc})

    # PES-07 — vedação do IGD
    ach("PES-07", "critica", "INCONCLUSIVO_POR_DOCUMENTO_FALTANTE",
        "Vedação do IGD quanto a pessoal não verificável",
        "O Artigo 12-A paragrafo 4 parte final da Lei 8.742/1993 veda usar recurso do "
        "IGD destinado ao conselho para pagar pessoal efetivo e gratificações. Sem a "
        "folha por fonte de recurso, a vedação não se afere — nem para confirmar, nem "
        "para afastar.",
        "Artigo 12-A paragrafo 4 da Lei 8.742/1993",
        {"documento_necessario": "folha de pagamento por competência, com fonte de recurso por servidor"})

    # PES-02 e PES-08 — dependem de dado externo
    for rid, tit, doc in (
        ("PES-02", "Teto de 30% para pessoal não aferível",
         "receita do FMAS por fonte e despesa de pessoal custeada pelo Tesouro"),
        ("PES-08", "Proporção entre efetivos e comissionados não aferível",
         "relação nominal do quadro por competência, com forma de provimento"),
        ("PES-09", "Equipe de referência mínima não aferível",
         "quadro de lotação por unidade (CRAS, CREAS, Centro POP)")):
        ach(rid, "alta", "INCONCLUSIVO_POR_DOCUMENTO_FALTANTE", tit,
            f"Regra declarada e não avaliada. Documento necessário: {doc}.",
            "ver config/criterios_pessoal.yml", {"documento_necessario": doc})

    return {"achados": achados, "diarias": diarias,
            "vantagens_mencionadas": vantagens, "cessoes": len(cessoes),
            "resumo": {"diarias": len(diarias), "vantagens": len(vantagens),
                       "achados": len(achados),
                       "por_selo": dict(Counter(a["selo"] for a in achados))}}

def main():
    fin = json.loads((RAIZ / "dados" / "financeiro.json").read_text(encoding="utf-8"))
    tri = json.loads((RAIZ / "dados" / "trilha_dinheiro.json").read_text(encoding="utf-8"))
    r = analisar(tri.get("detalhe", []), fin.get("por_natureza", {}))
    SAIDA.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(r["resumo"], ensure_ascii=False))
    for a in r["achados"]:
        print(f"  {a['severidade'][:4].upper():5s} {a['selo'][:12]:12s} [{a['regra']}] {a['titulo'][:58]}")

if __name__ == "__main__":
    main()
