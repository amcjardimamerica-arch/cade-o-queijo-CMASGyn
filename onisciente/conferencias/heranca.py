"""As trilhas do Rato e do Mato ligadas às fichas do Onisciente.

* **Rato (vínculos).** O Cadê o Queijo cruza o quadro de sócios das beneficiárias com os servidores
  e grava os alertas em ``referencias/vinculos/alertas.json`` (homonímia, sobrenome raro
  compartilhado, mesma pessoa em várias beneficiárias). Cada alerta vira ficha da família VIN,
  sempre marcada como coincidência de nome: nome igual não prova que é a mesma pessoa. O
  cruzamento novo com a Receita Federal é da conferência de empresas; aqui só se lê o que o Rato
  já gravou.
* **Mato (casos semelhantes).** Os precedentes de outros estados em
  ``referencias/transparencia/precedentes.json`` inspiram a providência e nunca fundamentam. Cada
  ficha sem caso semelhante recebe o precedente mais próximo pelo tema, com a fonte e o aviso de
  que precisa de confirmação na fonte oficial.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

from ..nucleo.indicios import Familia, Ficha, emitir
from ..nucleo.provas import Nivel
from .banco import Base, Parte

TIPOS_RATO = {
    "A1_HOMONIMIA_SOCIO_SERVIDOR": ("Sócio ou administrador com o mesmo nome de servidor", "alta"),
    "A2_PARENTESCO_POSSIVEL": ("Sobrenome raro em comum entre sócio e servidor", "media"),
    "A3_SOCIO_MULTIEMPRESA": ("A mesma pessoa no quadro de sócios de várias beneficiárias", "media"),
}

# Tema da ficha (palavras do título, da norma e da família) -> palavras do título do precedente.
TEMAS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("DIARIA", "PASSAGE"), ("DIARIA",)),
    (("ADITIVO", "CONTRAT", "LICITA", "DISPENSA", "FRACION", "ALUGUEL", "LOCACAO", "PRC"), ("LICITA", "CONTRAT")),
    (("EMENDA",), ("EMENDA",)),
    (("CONCURSO", "FOLHA", "SERVIDOR", "PES", "APOSENTA", "PREVIDENC"), ("CONCURSO", "NOMEA", "SELETIVO")),
    (("VIN", "SOCIO", "PARENT", "NEPOT"), ("NEPOTISMO",)),
    (("OBRA", "INVESTIMENTO"), ("OBRA",)),
    (("PUBLICA", "TRANSPAR", "PORTAL", "OFICIO", "PRAZO", "CTA", "AUSENC"), ("TRANSPAR", "PORTAL")),
    (("CONSELHO", "CONTROLE SOCIAL"), ("CONSELHO",)),
)
FONTES_PREFERIDAS = ("TRIBUNAL", "TCE", "TCM", "MINIST", "MP", "JUSTI")


def _sem_acento(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t or "") if unicodedata.category(c) != "Mn").upper()


def _json(caminho: Path) -> dict:
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def fichas_do_rato(raiz: Path) -> list[Ficha]:
    dados = _json(raiz / "referencias" / "vinculos" / "alertas.json")
    saida = []
    for n, a in enumerate(dados.get("alertas") or [], 1):
        titulo, gravidade = TIPOS_RATO.get(a.get("tipo", ""), ("Possível vínculo entre beneficiária e servidor", "media"))
        quem = a.get("socio") or a.get("nome") or a.get("pessoa") or ""
        empresa = a.get("empresa") or a.get("razao_social") or ", ".join(a.get("empresas") or [])
        como_esta = (a.get("descricao") or a.get("detalhe")
                     or f"{titulo}: {quem}{' em ' + empresa if empresa else ''}").strip()
        saida.append(emitir(
            codigo=f"VIN-RATO-{n:03d}", familia=Familia.VIN, titulo=titulo, gravidade=gravidade,
            como_deveria="Servidor não contrata nem recebe por meio de empresa da qual é sócio ou administrador, "
                         "e o parentesco com quem decide a contratação é declarado e afastado.",
            norma="Lei Orgânica, art. 29; Lei 14.133/2021, art. 14, IV; Lei 8.429/1992, art. 11",
            como_esta=como_esta[:1].upper() + como_esta[1:] + ("" if como_esta.endswith(".") else "."),
            niveis=[Nivel.D], por_coincidencia_de_nome=True,
            providencia="Pedir o quadro funcional com CPF parcial e conferir no quadro de sócios da Receita; "
                        "nome igual não prova que é a mesma pessoa.",
            observacao="Indício por coincidência de nome, não acusação."))
    return saida


def precedentes(raiz: Path) -> list[dict]:
    itens = _json(raiz / "referencias" / "transparencia" / "precedentes.json").get("itens") or []
    return [i for i in itens if i.get("titulo")]


def caso_semelhante(ficha: Ficha, itens: list[dict]) -> str:
    """O precedente do Mato mais próximo pelo tema, ou vazio. Inspira, não fundamenta."""
    tema = _sem_acento(f"{ficha.titulo} {ficha.norma} {ficha.familia.value} {ficha.codigo}")
    for chaves, procura in TEMAS:
        if not any(re.search(rf"\b{c}", tema) for c in chaves):
            continue
        candidatos = [i for i in itens if any(p in _sem_acento(i["titulo"]) for p in procura)]
        if not candidatos:
            continue
        candidatos.sort(key=lambda i: (not any(p in _sem_acento(i.get("fonte", "")) for p in FONTES_PREFERIDAS),
                                       itens.index(i)))
        i = candidatos[0]
        titulo = re.sub(r"\s+-\s+[^-]+$", "", i["titulo"]).strip()
        return (f"{titulo} ({i.get('fonte') or 'fonte não identificada'}). Precedente de outro lugar: inspira a "
                "providência, não fundamenta, e precisa de confirmação na fonte oficial.")
    return ""


def conferir(base: Base) -> Parte:
    parte = Parte()
    parte.fichas += fichas_do_rato(base.raiz)
    if parte.fichas:
        parte.notas.append(f"Trilha do Rato: {len(parte.fichas)} alerta(s) de vínculo por coincidência de nome.")
    return parte
