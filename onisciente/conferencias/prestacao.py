"""Prestação de contas de cada parceria (Lei 13.019/2014; regra PRESTACAO-PARCERIAS).

As parcerias vêm dos destinatários dos repasses que o Cadê o Queijo identificou no exercício
(``dados/destinatarios_AAAA.json``): as organizações sem fins lucrativos, com os termos de fomento
ou de colaboração citados. Para cada parceria se mede o que a estação Prestação pede (nível C): termo
publicado, prestação publicada, individualizada, no prazo e com o saldo devolvido.

O prazo é o do art. 69: noventa dias do fim da vigência ou o fim de cada exercício quando a
parceria passa de um ano. A parceria que segue recebendo no exercício seguinte ao do termo já
passou de um ano, e a prestação do exercício do termo venceu no fim dele.
"""

from __future__ import annotations

import json
import re

from ..nucleo.ausencias import Ausencia
from ..nucleo.selos import Selo
from .banco import Base, Linha, Parte, Quadro, moeda
from .execucao import Parceria, fichas_de_prestacao

TERMO = re.compile(r"termo\s+de\s+(fomento|colabora[çc][ãa]o)\s+(?:n[ºo.]*\s*)?(\d+)\s*/\s*(\d{4})", re.I)
ORGAO = "Secretaria Municipal de Desenvolvimento Humano e Social de Goiânia (gestora do Fundo Municipal de Assistência Social)"


def _destinatarios(base: Base) -> tuple[int | None, list[dict]]:
    for ano in (base.ate.year, base.ate.year - 1):
        caminho = base.raiz / "dados" / f"destinatarios_{ano}.json"
        if caminho.exists():
            try:
                return ano, json.loads(caminho.read_text(encoding="utf-8")).get("destinatarios", [])
            except ValueError:
                return ano, []
    return None, []


def _prestacoes_publicadas(base: Base) -> bool:
    """O índice de transparência do Cadê o Queijo diz se as prestações das parcerias estão publicadas."""
    try:
        transp = json.loads((base.raiz / "dados" / "nivel_transparencia.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return False
    bloco = (transp.get("blocos") or {}).get("Parcerias com entidades") or {}
    return not any("prestaç" in f.lower() for f in bloco.get("falta", []))


def parcerias(base: Base) -> tuple[int | None, list[Parceria], list[dict]]:
    ano, lista = _destinatarios(base)
    publicadas = _prestacoes_publicadas(base)
    saida, linhas = [], []
    for d in lista:
        if not d.get("sem_fins_lucrativos"):
            continue
        termos = sorted({(t.group(1).lower()[:5], int(t.group(2)), int(t.group(3)))
                         for i in d.get("instrumentos") or [] for t in [TERMO.search(i)] if t},
                        key=lambda x: x[2])
        nome = " ".join((d.get("razao_social") or "").split()).title()
        if termos:
            tipo, numero, ano_termo = termos[0]
            instrumento = f"{'fomento' if tipo == 'fomen' else 'colaboração'} {numero:03d}/{ano_termo}"
        else:
            ano_termo, instrumento = None, "sem termo publicado"
        vencido = bool(ano and ano_termo and ano_termo < ano)
        p = Parceria(instrumento=re.sub(r"[^A-Za-z0-9]+", "-", f"{d.get('cnpj', '')}-{instrumento}").strip("-"),
                     entidade=nome, valor=float(d.get("valor_total_no_exercicio") or 0.0),
                     prestacao_publicada=publicadas, prazo_vencido=vencido)
        saida.append(p)
        linhas.append({"entidade": nome, "instrumento": instrumento, "valor": p.valor, "vencido": vencido,
                       "competencias": d.get("competencias") or [], "termo": bool(termos)})
    return ano, saida, linhas


def conferir(base: Base) -> Parte:
    parte = Parte()
    ano, lista, linhas = parcerias(base)
    if ano is None:
        return parte
    parte.parcerias, parte.exercicio_das_parcerias = list(lista), ano
    regra = base.mapa.regra("PRESTACAO-PARCERIAS")
    q = Quadro(6, f"Prestação de contas de cada parceria ({ano})",
               "Organizações sem fins lucrativos que receberam repasses no exercício, com o termo citado. A estação "
               "Prestação (nível C) pede termo, prestação individualizada no prazo e saldo devolvido.",
               ["Entidade", "Instrumento", "Recebido no exercício", "Prestação", "Prazo"],
               regra=f"PRESTACAO-PARCERIAS: {regra.get('justificativa', '')}")
    for x in linhas:
        q.linhas.append(Linha(x["entidade"], [x["instrumento"], moeda(x["valor"]),
                                              "publicada" if lista and lista[0].prestacao_publicada else "não publicada",
                                              "vencido" if x["vencido"] else "em curso ou sem termo"],
                              Selo.ROXO if not (lista and lista[0].prestacao_publicada) else Selo.AZUL))
    if q.linhas:
        parte.quadros.append(q)
    for f in fichas_de_prestacao(lista):
        f.observacao = "indício, não acusação"
        parte.fichas.append(f)
    sem_termo = [x for x in linhas if not x["termo"]]
    if linhas:
        parte.ausencias.append(Ausencia(
            o_que_falta=(f"Termos, planos de trabalho e prestações de contas de {len(linhas)} parceria(s) com "
                         f"organizações da sociedade civil" + (f", {len(sem_termo)} delas sem termo citado" if sem_termo else "")),
            conferencia_impedida="medir a prestação de cada parceria: prazo, individualização e devolução do saldo",
            onde_deveria_estar="Portal da Transparência de Goiânia e plataforma de parcerias (Lei 13.019/2014, art. 10)",
            fundamento="Lei 13.019/2014, arts. 10, 63 e 69; Lei 9.262/2013, art. 7º, § 3º",
            periodo=f"exercício {ano}", orgao=ORGAO, bloco="Parcerias com entidades"))
    return parte
