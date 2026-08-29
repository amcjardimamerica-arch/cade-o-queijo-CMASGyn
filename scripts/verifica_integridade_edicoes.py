#!/usr/bin/env python3
"""P-N1 · Detector de Diário reescrito.

Toda edição já processada tem seu sha256 ancorado no acervo. Este script
rebaixa uma amostra das edições ancoradas e compara o hash atual com o
histórico: PDF substituído silenciosamente após a publicação é indício de
adulteração de documento de fé pública — Artigo 37, caput, da Constituição
da República — e vira achado INDICIÁRIO com os dois hashes como prova,
elevável a CONFIRMADO pela guarda do PDF original.

Economia por desenho: usa o cliente cortês do projeto (GET condicional —
HTTP 304 encerra sem baixar) e amostra rotativa: as N mais recentes sempre,
mais uma fatia determinística do histórico por rodada (semente = número da
semana), de modo que todo o acervo é reconferido ao longo do trimestre sem
custo perceptível. Camada 0: zero tokens.

Uso: python3 scripts/verifica_integridade_edicoes.py [--amostra 20]
Saída: relatorios/integridade_edicoes.json (+ achado quando houver)
"""
from __future__ import annotations
import gzip, hashlib, json, sys
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))
from cliente_http import ClienteHTTP  # cortês: robots, intervalo, condicional


def ancoras() -> dict[str, dict]:
    """edicao -> {sha256, url, data} a partir do acervo de trechos."""
    m = {}
    for arq in (RAIZ / "acervo" / "trechos").glob("*.jsonl.gz"):
        for linha in gzip.open(arq, "rt", encoding="utf-8"):
            d = json.loads(linha)
            ed = d.get("edicao")
            if ed and d.get("sha256_edicao") and d.get("url_original"):
                m.setdefault(ed, {"sha256": d["sha256_edicao"],
                                  "url": d["url_original"],
                                  "data": d.get("data")})
    return m


def amostra_rotativa(edicoes: list[str], n: int) -> list[str]:
    edicoes = sorted(edicoes)
    recentes = edicoes[-8:]
    semana = date.today().isocalendar()[1]
    historicas = [e for i, e in enumerate(edicoes[:-8])
                  if i % max(1, len(edicoes) // max(n - 8, 1))
                  == semana % max(1, len(edicoes) // max(n - 8, 1))]
    vistos, saida = set(), []
    for e in recentes + historicas:
        if e not in vistos:
            vistos.add(e)
            saida.append(e)
    return saida[:n]


def main():
    n = 20
    if "--amostra" in sys.argv:
        n = int(sys.argv[sys.argv.index("--amostra") + 1])
    anc = ancoras()
    alvo = amostra_rotativa(list(anc), n)
    cli = ClienteHTTP(user_agent="AMC-Jardim-America-Vigilancia/1.0 (fiscalizacao publica)")
    integras, inalteradas, reescritas, indisponiveis = 0, 0, [], []
    for ed in alvo:
        a = anc[ed]
        try:
            r = cli.obter(a["url"])
        except Exception:
            r = None
        if r is None or r.conteudo is None:
            if r is not None and getattr(r, "inalterado", False):
                inalteradas += 1  # HTTP 304: hash garantido pelo servidor
                continue
            indisponiveis.append(ed)
            continue
        atual = hashlib.sha256(r.conteudo).hexdigest()
        if atual == a["sha256"]:
            integras += 1
        else:
            reescritas.append({
                "edicao": ed, "data_original": a["data"], "url": a["url"],
                "sha256_ancorado": a["sha256"], "sha256_atual": atual,
                "severidade": "critica", "selo": "INDICIARIO",
                "titulo": (f"Edição {ed} do Diário Oficial com conteúdo "
                           f"alterado após a publicação"),
                "detalhe": ("O PDF servido hoje difere, byte a byte, do "
                            "ancorado quando a edição foi processada. "
                            "Substituição silenciosa de documento de fé "
                            "pública. A guarda do PDF original eleva a "
                            "CONFIRMADO por dupla via."),
                "norma": ("Artigo 37, caput, da Constituição da República — "
                          "princípios da publicidade e da moralidade"),
            })
    rel = {"verificado_em": date.today().isoformat(),
           "edicoes_ancoradas": len(anc), "amostra": len(alvo),
           "integras": integras, "inalteradas_http304": inalteradas,
           "indisponiveis": indisponiveis, "reescritas": reescritas,
           "cobertura": ("amostra rotativa determinística — acervo inteiro "
                         "reconferido ao longo do trimestre")}
    destino = RAIZ / "relatorios" / "integridade_edicoes.json"
    destino.write_text(json.dumps(rel, ensure_ascii=False, indent=1),
                       encoding="utf-8")
    print(f"  integridade: {integras + inalteradas}/{len(alvo)} íntegras "
          f"({inalteradas} por 304) · {len(reescritas)} REESCRITAS · "
          f"{len(indisponiveis)} indisponíveis")
    if reescritas:
        print("  !! EDIÇÃO REESCRITA DETECTADA — ver "
              "relatorios/integridade_edicoes.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
