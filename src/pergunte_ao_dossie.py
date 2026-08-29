#!/usr/bin/env python3
"""Q5 — perguntas ao dossiê, respondidas pelo modelo de julgamento (Fable).
Uso: python3 src/pergunte_ao_dossie.py "sua pergunta"
Monta o mesmo dossiê determinístico do dominical e envia UMA chamada.
Sem chave, imprime o dossiê e a pergunta pendente (nada se perde)."""
import os, sys
from datetime import date
from pathlib import Path
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))
from avaliacao_dominical import dossie, julgar, INSTRUCAO  # reuso integral

def main():
    if len(sys.argv) < 2:
        print('uso: pergunte_ao_dossie.py "pergunta"'); return 2
    pergunta = sys.argv[1]
    texto, _ = dossie(date.today())
    situacao, resp = julgar(texto + "\n\nPERGUNTA DO FISCALIZADOR (responda "
                            "apenas a ela, com selo e norma por extenso): "
                            + pergunta)
    destino = RAIZ / "relatorios" / "perguntas"
    destino.mkdir(exist_ok=True)
    arq = destino / f"{date.today().isoformat()}_{abs(hash(pergunta)) % 9999}.md"
    arq.write_text(f"# Pergunta\n{pergunta}\n\n# Resposta [{situacao}]\n"
                   + (resp or "pendente de ANTHROPIC_API_KEY — dossiê "
                      "preservado para reprocesso"), encoding="utf-8")
    print(resp if resp else f"[{situacao}] registrado em {arq.name}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
