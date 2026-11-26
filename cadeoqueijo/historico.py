"""Constituição do acervo histórico do CMASGyn.

Política de arquivamento, ditada por uma restrição real: as 379 edições da
janela de três anos somam cerca de 4 GB em PDF, o que não cabe em repositório
do GitHub. Arquiva-se, então, o que preserva valor probatório e capacidade de
busca:

  1. SHA-256 e URL oficial de cada edição — prova de integridade e caminho para
     rebaixar o PDF original assinado a qualquer momento;
  2. o texto integral extraído, comprimido — o banco de busca local;
  3. os trechos que mencionam o CMASGyn, na íntegra — o acervo de trabalho.

O PDF assinado permanece obtenível pela URL registrada. Como o digest foi
fixado no dia da coleta, qualquer alteração posterior do arquivo oficial fica
demonstrada pela simples divergência de hash.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
import urllib3

sys.path.insert(0, str(Path(__file__).parent))
from util import ACERVO, ESTADO, agora, extrair_texto_pdf, gravar_json, ler_json, log

urllib3.disable_warnings()

BASE = "http://sileg.goiania.go.gov.br/geral/"
PDF = ACERVO / "historico" / "pdf"
TXTGZ = ACERVO / "historico" / "txt_gz"
REGISTRO = ESTADO / "historico_registro.json"

for _d in (PDF, TXTGZ):
    _d.mkdir(parents=True, exist_ok=True)


def _sessao() -> requests.Session:
    s = requests.Session()
    s.verify = False
    s.headers["User-Agent"] = "AMC-Jardim-America-Vigilancia/1.0"
    return s


def _um(item: dict, s: requests.Session, guardar_pdf: bool) -> tuple[str, dict]:
    nome = item["nome"]
    destino = PDF / nome
    try:
        r = s.get(BASE + nome, timeout=300)
        if r.status_code != 200:
            return nome, {"data": item["data"], "erro": f"HTTP {r.status_code}"}
        digest = hashlib.sha256(r.content).hexdigest()
        destino.write_bytes(r.content)
        texto, ocr = extrair_texto_pdf(destino)
        (TXTGZ / f"{nome[:-4]}.txt.gz").write_bytes(
            gzip.compress(texto.encode("utf-8"), 9))
        tam = destino.stat().st_size
        if not guardar_pdf:
            destino.unlink()
        return nome, {
            "data": item["data"], "termos": item.get("termos", []),
            "sha256": digest, "bytes": tam, "caracteres": len(texto),
            "ocr": ocr, "url": BASE + nome,
            "coletado_em": agora().isoformat(), "pdf_local": guardar_pdf,
        }
    except Exception as e:
        return nome, {"data": item["data"],
                      "erro": f"{type(e).__name__}: {str(e)[:120]}"}


def colher(itens: list[dict], trabalhadores: int = 5,
           guardar_pdf: bool = False, teto: int | None = None) -> dict:
    reg = ler_json(REGISTRO, {})
    pendentes = [i for i in itens if not reg.get(i["nome"], {}).get("sha256")]
    if teto:
        pendentes = pendentes[:teto]
    log.info("Acervo histórico: %d edição(ões) pendente(s) de %d", len(pendentes), len(itens))

    sessoes = [_sessao() for _ in range(trabalhadores)]
    feitos = 0
    with ThreadPoolExecutor(max_workers=trabalhadores) as ex:
        passo = trabalhadores * 3
        for i in range(0, len(pendentes), passo):
            lote = pendentes[i:i + passo]
            futuros = [ex.submit(_um, it, sessoes[k % trabalhadores], guardar_pdf)
                       for k, it in enumerate(lote)]
            for f in futuros:
                nome, meta = f.result()
                reg[nome] = meta
                feitos += 1
                if meta.get("erro"):
                    log.warning("%s -> %s", nome, meta["erro"])
            gravar_json(REGISTRO, reg)
            log.info("progresso %d/%d", feitos, len(pendentes))
            time.sleep(0.8)

    ok = sum(1 for m in reg.values() if m.get("sha256"))
    err = sum(1 for m in reg.values() if m.get("erro"))
    log.info("Acervo: %d íntegras, %d com erro", ok, err)
    return {"total": len(reg), "integras": ok, "erros": err}


if __name__ == "__main__":
    caminho = sys.argv[1] if len(sys.argv) > 1 else "dados/janela3anos.json"
    teto = int(sys.argv[2]) if len(sys.argv) > 2 else None
    itens = json.load(open(caminho, encoding="utf-8"))
    print(json.dumps(colher(itens, teto=teto), ensure_ascii=False, indent=2))
