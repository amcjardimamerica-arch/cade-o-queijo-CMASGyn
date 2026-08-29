#!/usr/bin/env python3
"""Servidores nomeados nas publicações — pasta própria, separada.

Varre o acervo local de trechos do Diário por atos de NOMEAR, EXONERAR,
DESIGNAR e CONTRATAR, e registra: NOME COMPLETO — ato de pessoal publicado em Diário Oficial é
informação pública funcional (Artigo 37, caput e § 3º, da Constituição;
Artigo 8º da Lei 12.527/2011), e a minimização a primeiro nome fica
reservada às pessoas físicas SEM vínculo público. Registra ainda: ato, cargo quando
declarado, data, edição, página e o ponteiro verificável (URL e sha256 da
edição, onde o nome completo permanece no documento oficial).

Alvo: últimos 5 anos. Cobertura atual do acervo é declarada no próprio
arquivo — dado faltante é achado; a expansão retroativa roda no ciclo.
Camada 0: determinístico, zero tokens.

Saída: referencias/servidores/nomeacoes.json e nomeacoes_AAAA.md
"""
from __future__ import annotations
import gzip, json, re
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PASTA = RAIZ / "referencias" / "servidores"
TRECHOS = RAIZ / "acervo" / "trechos"

ATO = re.compile(r"\b(NOMEAR|EXONERAR|DESIGNAR|CONTRATAR|DISPENSAR)\b[,:\s]+"
                 r"(?:o[a]?\s+servidor[a]?\s+|o\s+|a\s+)?"
                 r"([A-ZÁÀÂÃÉÊÍÓÔÕÚÇ]{2,}(?:\s+[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ]{2,}){0,6})")
CARGO = re.compile(r"(?:cargo|fun[çc][ãa]o)\s+(?:em\s+comiss[ãa]o\s+)?(?:de\s+)"
                   r"([A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][^,;.\n]{3,60})", re.I)
PARTICULAS = {"DA", "DE", "DO", "DAS", "DOS", "E"}


def primeiro_nome(nome_maiusculo: str) -> str:
    for p in nome_maiusculo.split():
        if p not in PARTICULAS and len(p) > 1:
            return p.title()
    return nome_maiusculo.split()[0].title()


def main():
    PASTA.mkdir(parents=True, exist_ok=True)
    registros, vistos = [], set()
    anos = set()
    for arq in sorted(TRECHOS.glob("*.jsonl.gz")):
        for linha in gzip.open(arq, "rt", encoding="utf-8"):
            d = json.loads(linha)
            texto = d.get("texto") or ""
            anos.add(str(d.get("data", ""))[:4])
            for m in ATO.finditer(texto.upper()):
                ato, nome = m.group(1), m.group(2)
                if len(nome.split()) < 2:  # exige nome composto no ato
                    continue
                mc = CARGO.search(texto[m.end():m.end() + 220])
                chave = (ato, nome, d.get("edicao"))
                if chave in vistos:
                    continue
                vistos.add(chave)
                registros.append({
                    "nome_completo": nome.title(),
                    "primeiro_nome": primeiro_nome(nome),
                    "sobrenomes": [p.title() for p in nome.split()[1:]
                                   if p not in PARTICULAS],
                    "ato": ato.title(),
                    "cargo": (mc.group(1).strip().title() if mc else None),
                    "data": d.get("data"),
                    "edicao": d.get("edicao"),
                    "pagina": d.get("pagina_estimada"),
                    "url_edicao": d.get("url_original"),
                    "sha256_edicao": d.get("sha256_edicao"),
                })
    registros.sort(key=lambda r: (r["data"] or "", r["primeiro_nome"]))
    alvo = list(range(date.today().year - 4, date.today().year + 1))
    cobertos = sorted(a for a in anos if a.isdigit())
    faltam = [str(a) for a in alvo if str(a) not in cobertos]
    # situação funcional consolidada: o ato mais recente por nome define
    situacao = {}
    for r in registros:  # já ordenados por data
        situacao[r["nome_completo"]] = (
            "DESLIGADO" if r["ato"] in ("Exonerar", "Dispensar")
            else "ATIVO_OU_VINCULADO")
    for r in registros:
        r["situacao_atual"] = situacao[r["nome_completo"]]
    ativos = sorted({n for n, s in situacao.items()
                     if s == "ATIVO_OU_VINCULADO"})
    saida = {
        "gerado_em": date.today().isoformat(),
        "regra_de_analise": ("DESLIGADOS ficam fora das análises atuais da "
                             "secretaria; permanecem no histórico para "
                             "cruzamentos retroativos"),
        "quadro_atual": ativos,
        "minimizacao": ("ato de pessoal é informação pública funcional — nome "
                        "completo registrado com ponteiro sha256 à edição; "
                        "pessoas sem vínculo público seguem minimizadas ao "
                        "primeiro nome nas demais bases"),
        "alvo_anos": [str(a) for a in alvo],
        "anos_cobertos_pelo_acervo": cobertos,
        "anos_pendentes_de_varredura_retroativa": faltam,
        "total": len(registros),
        "registros": registros,
    }
    (PASTA / "nomeacoes.json").write_text(
        json.dumps(saida, ensure_ascii=False, indent=1), encoding="utf-8")
    for ano in cobertos:
        do_ano = [r for r in registros if (r["data"] or "").startswith(ano)]
        if not do_ano:
            continue
        md = [f"# Servidores nomeados/exonerados — {ano} "
              f"({len(do_ano)} atos)\n"]
        for r in do_ano:
            md.append(f"- **{r['primeiro_nome']}** — {r['ato']}"
                      + (f", {r['cargo']}" if r['cargo'] else "")
                      + f" — {r['data']}, edição {r['edicao']}")
        (PASTA / f"nomeacoes_{ano}.md").write_text("\n".join(md) + "\n",
                                                   encoding="utf-8")
    print(f"  servidores: {len(registros)} atos | anos cobertos "
          f"{cobertos} | pendentes {faltam}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
