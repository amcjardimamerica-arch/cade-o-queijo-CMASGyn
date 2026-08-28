"""Semáforo diário: houve ato de assistência social publicado hoje?

Três estados, e o terceiro é o que importa:

  PUBLICOU     houve edição e ela traz ato da pasta
  SEM_ATO      houve edição, mas nada da assistência social nela
  INEXISTENTE  não houve edição em dia útil, ou o índice nada devolve

INEXISTENTE em dia útil é anomalia, não normalidade. A série histórica desses
estados é a prova documental de intermitência da publicidade — e é ela que
sustenta o pedido de acesso e, se for o caso, a representação.
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import requests
import urllib3

sys.path.insert(0, str(Path(__file__).parent))

from cobertura import FERIADOS_FIXOS
from util import RAIZ, agora, gravar_json, ler_json, log

urllib3.disable_warnings()
SOLR = "https://sileg.goiania.go.gov.br/solr-4.1.0/select"
SERIE = RAIZ / "dados" / "publicacao_diaria.json"

TERMOS_PASTA = [
    "CMASGyn", "Conselho Municipal de Assistência Social",
    "Fundo Municipal de Assistência Social",
    "Secretaria Municipal de Assistência Social",
    "proteção social básica", "proteção social especial",
    "Índice de Gestão Descentralizada", "Bolsa Família", "Cadastro Único",
]


def _sessao():
    s = requests.Session(); s.verify = False
    s.headers["User-Agent"] = "AMC-Jardim-America-Vigilancia/1.0"
    return s


def _consulta(q: str, s, rows=8):
    try:
        r = s.get(SOLR, params={"q": q, "wt": "json", "rows": rows, "fl": "id"}, timeout=70)
        r.raise_for_status()
        d = r.json()["response"]
        return d["numFound"], [x["id"] for x in d["docs"]]
    except Exception as e:
        log.warning("consulta falhou: %s", e)
        return None, []


def apurar(dias: int = 45) -> dict:
    """Reapura os últimos N dias. Idempotente: pode rodar quantas vezes quiser."""
    s = _sessao()
    serie = ler_json(SERIE, {"dias": {}, "gerado_em": None})
    hoje = agora().date()

    q_pasta = " OR ".join(f'attr_content:"{t}"' for t in TERMOS_PASTA)

    for k in range(dias, -1, -1):
        d = hoje - timedelta(days=k)
        iso = d.isoformat()
        util = d.weekday() < 5 and (d.month, d.day) not in FERIADOS_FIXOS
        if not util:
            serie["dias"][iso] = {"situacao": "NAO_UTIL", "util": False}
            continue
        # Reapura sempre os 10 dias mais recentes; o resto fica congelado.
        if iso in serie["dias"] and k > 10 and serie["dias"][iso].get("situacao") != "INEXISTENTE":
            continue

        marca = f"_{d.strftime('%Y%m%d')}_"
        n_ed, ids = _consulta(f"id:*{marca}*", s)
        time.sleep(0.4)
        if n_ed is None:
            # sonda falhou (rede, proxy, limite). Falha de coleta não é fato
            # novo: nunca sobrescreve situação já apurada — apenas preenche
            # dia ainda sem registro. Preserva o achado e mantém a função
            # idempotente mesmo com a fonte inalcançável.
            if iso not in serie["dias"]:
                serie["dias"][iso] = {"situacao": "INCONCLUSIVO", "util": True}
            continue
        if not n_ed:
            serie["dias"][iso] = {"situacao": "INEXISTENTE", "util": True,
                                  "nota": "nenhuma edição indexada para o dia"}
            continue

        n_ato, docs = _consulta(f"({q_pasta}) AND id:*{marca}*", s)
        time.sleep(0.4)
        serie["dias"][iso] = {
            "situacao": "PUBLICOU" if n_ato else "SEM_ATO",
            "util": True, "edicoes": n_ed,
            "documentos": [re.sub(r"^.*/", "", x) for x in (docs or ids)][:4],
        }

    uteis = [v for v in serie["dias"].values() if v.get("util")]
    cont = {}
    for v in uteis:
        cont[v["situacao"]] = cont.get(v["situacao"], 0) + 1

    ult = sorted([k for k, v in serie["dias"].items() if v.get("situacao") == "PUBLICOU"])
    serie["gerado_em"] = agora().isoformat()
    serie["resumo"] = {
        "dias_uteis": len(uteis), "contagem": cont,
        "ultima_publicacao": ult[-1] if ult else None,
        "dias_desde_ultima": (hoje - date.fromisoformat(ult[-1])).days if ult else None,
        "inexistentes": cont.get("INEXISTENTE", 0),
    }
    gravar_json(SERIE, serie)
    log.info("Semáforo diário: %s | última publicação em %s",
             cont, serie["resumo"]["ultima_publicacao"])
    return serie


def achados(serie: dict) -> list[dict]:
    r = serie.get("resumo", {})
    out = []
    dd = r.get("dias_desde_ultima")
    if dd is not None and dd > 20:
        out.append({
            "regra": "PUB-05", "severidade": "media",
            "titulo": f"{dd} dias sem ato da assistência social no Diário Oficial",
            "detalhe": (f"A última publicação identificada da pasta é de "
                        f"{r['ultima_publicacao']}. Intervalo dessa ordem, num órgão que "
                        "delibera mensalmente e executa orçamento continuamente, sugere "
                        "que a publicação não acompanha a atividade."),
            "detectado_em": agora().isoformat(), "saida_sugerida": "minuta_lai"})
    if r.get("inexistentes", 0) >= 5:
        out.append({
            "regra": "PUB-06", "severidade": "alta",
            "titulo": f"{r['inexistentes']} dia(s) útil(eis) sem qualquer edição indexada",
            "detalhe": ("Dia útil sem edição do Diário Oficial disponível para consulta "
                        "automatizada. Ou não houve publicação, ou houve e não foi "
                        "disponibilizada em formato acessível — hipóteses que o artigo "
                        "8º, § 3º, incisos III e VI, da Lei 12.527/2011 igualmente "
                        "reprova."),
            "detectado_em": agora().isoformat(), "saida_sugerida": "minuta_lai"})
    return out


if __name__ == "__main__":
    s = apurar(int(sys.argv[1]) if len(sys.argv) > 1 else 45)
    print(json.dumps(s["resumo"], ensure_ascii=False, indent=2))
    for a in achados(s):
        print(f"[{a['regra']}·{a['severidade']}] {a['titulo']}")
