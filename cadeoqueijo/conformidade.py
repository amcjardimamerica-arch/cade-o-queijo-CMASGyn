"""Verificações determinísticas de conformidade.

Rodam em Python puro, sem custo de token. Só o que passa por aqui com suspeita
é promovido ao modelo. Esta é a metade barata do sistema — e a que produz os
achados mais objetivos.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime, timedelta

from util import ESTADO, agora, carregar_yaml, ler_json, log

REG_CMASGYN = ESTADO / "cmasgyn_registro.json"
REG_DOM = ESTADO / "dom_registro.json"


def _achado(regra: str, severidade: str, titulo: str, detalhe: str, **extra) -> dict:
    return {
        "regra": regra, "severidade": severidade, "titulo": titulo,
        "detalhe": detalhe, "detectado_em": agora().isoformat(), **extra,
    }


# --------------------------------------------------------------------- RES-01
def continuidade_de_numeracao() -> list[dict]:
    """Lacuna na sequência numérica das resoluções por exercício."""
    registro = ler_json(REG_CMASGYN, {})
    por_ano: dict[int, set[int]] = defaultdict(set)
    for meta in registro.values():
        if "numero" in meta and "exercicio" in meta:
            por_ano[meta["exercicio"]].add(meta["numero"])

    achados = []
    for ano, numeros in sorted(por_ano.items()):
        if len(numeros) < 3:
            continue
        faltantes = sorted(set(range(min(numeros), max(numeros) + 1)) - numeros)
        if faltantes:
            achados.append(_achado(
                "RES-01", "media",
                f"Lacuna na numeração das resoluções de {ano}",
                f"Ausentes do acervo público: {', '.join(map(str, faltantes))}. "
                f"Faixa observada: {min(numeros)} a {max(numeros)}.",
                exercicio=ano, faltantes=faltantes,
                saida_sugerida="minuta_lai",
            ))
    return achados


# --------------------------------------------------------------------- RES-02
def publicacao_no_diario() -> list[dict]:
    """Resolução no sítio do conselho sem correspondente no Diário Oficial."""
    registro = ler_json(REG_CMASGYN, {})
    dom = ler_json(REG_DOM, {})

    corpus_dom = ""
    for meta in dom.values():
        caminho = meta.get("txt")
        if caminho:
            from util import ACERVO
            arq = ACERVO.parent / caminho
            if arq.exists():
                corpus_dom += arq.read_text(encoding="utf-8", errors="ignore")

    if not corpus_dom:
        return []

    achados = []
    for meta in registro.values():
        if "numero" not in meta:
            continue
        n, ano = meta["numero"], meta["exercicio"]
        padrao = re.compile(
            rf"resolu[çc][ãa]o[^\n]{{0,40}}0?0?{n}\D{{0,6}}{ano}", re.IGNORECASE
        )
        if not padrao.search(corpus_dom):
            achados.append(_achado(
                "RES-02", "media",
                f"Resolução {n:03d}/{ano} sem publicação localizada no Diário Oficial",
                "O ato consta do sítio do conselho mas não foi localizado nas edições "
                "do Diário Oficial arquivadas. A ausência de publicação compromete a "
                "eficácia do ato perante terceiros, à luz do artigo 37, caput, da "
                "Constituição Federal.",
                arquivo=meta.get("arquivo"), url=meta.get("url"),
            ))
    return achados


# --------------------------------------------------------------------- ATA-01
def publicidade_das_atas(prazo_dias: int = 30) -> list[dict]:
    """Reunião realizada sem ata publicada dentro do prazo regimental."""
    registro = ler_json(REG_CMASGYN, {})
    atas, reunioes = [], []
    for meta in registro.values():
        nome = (meta.get("arquivo") or "").lower()
        if "ata" in nome:
            atas.append(meta)
        if "pauta" in nome or "convoca" in nome or "plenaria" in nome:
            reunioes.append(meta)

    datas_ata = set()
    for a in atas:
        for m in re.finditer(r"(\d{2})[_\-.](\d{2})[_\-.](\d{4})", a.get("arquivo", "")):
            datas_ata.add(f"{m.group(3)}-{m.group(2)}-{m.group(1)}")

    achados = []
    limite = agora().date() - timedelta(days=prazo_dias)
    for r in reunioes:
        for m in re.finditer(r"(\d{2})[_\-.](\d{2})[_\-.](\d{4})", r.get("arquivo", "")):
            iso = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
            try:
                d = date.fromisoformat(iso)
            except ValueError:
                continue
            if d < limite and iso not in datas_ata:
                achados.append(_achado(
                    "ATA-01", "media",
                    f"Ata da reunião de {d.strftime('%d/%m/%Y')} não publicada",
                    f"Decorridos mais de {prazo_dias} dias da sessão sem que a ata "
                    "correspondente tenha sido localizada no acervo público, em "
                    "desacordo com o Regimento Interno do CMASGyn e com o dever de "
                    "transparência ativa do artigo 8º da Lei 12.527/2011.",
                    data_reuniao=iso, saida_sugerida="minuta_lai",
                ))
    return achados


# --------------------------------------------------------------------- ATA-02
def acessibilidade_dos_arquivos() -> list[dict]:
    """Arquivo publicado sem camada de texto: transparência apenas formal."""
    registro = ler_json(REG_CMASGYN, {})
    achados = []
    for meta in registro.values():
        if meta.get("ocr") and meta.get("caracteres", 0) > 0:
            achados.append(_achado(
                "ATA-02", "baixa",
                f"Documento publicado como imagem: {meta.get('arquivo')}",
                "O arquivo não possui camada de texto e exigiu reconhecimento óptico. "
                "Publicação em formato não legível por máquina contraria o artigo 8º, "
                "§ 3º, incisos II e III, da Lei 12.527/2011.",
                arquivo=meta.get("arquivo"),
            ))
    return achados


# --------------------------------------------------------------------- FIN-02
def conferencia_no_bienio() -> list[dict]:
    """Decurso do biênio sem convocação da conferência municipal."""
    registro = ler_json(REG_CMASGYN, {})
    anos = set()
    for meta in registro.values():
        nome = (meta.get("arquivo") or "").lower()
        if "conferencia" in nome or "conferência" in nome:
            for m in re.finditer(r"(20\d{2})", nome):
                anos.add(int(m.group(1)))
    if not anos:
        return [_achado(
            "FIN-02", "media",
            "Nenhum ato de convocação de conferência municipal no acervo",
            "Não foi localizado, no acervo público do conselho, ato de convocação da "
            "Conferência Municipal de Assistência Social. Verificar cumprimento da "
            "periodicidade prevista na Lei 8.742/1993 e na Lei 7.532/1995.",
            saida_sugerida="minuta_lai",
        )]
    ultima = max(anos)
    if agora().year - ultima > 2:
        return [_achado(
            "FIN-02", "media",
            f"Última conferência localizada em {ultima}",
            f"Decorridos {agora().year - ultima} anos sem novo ato de convocação.",
            ultimo_ano=ultima,
        )]
    return []


def executar_todas() -> list[dict]:
    cfg = carregar_yaml("regras.yml")
    prazo = next(
        (r.get("parametros", {}).get("prazo_dias", 30)
         for r in cfg["regras"] if r["id"] == "ATA-01"), 30
    )
    achados: list[dict] = []
    for fn, args in (
        (continuidade_de_numeracao, ()),
        (publicacao_no_diario, ()),
        (publicidade_das_atas, (prazo,)),
        (acessibilidade_dos_arquivos, ()),
        (conferencia_no_bienio, ()),
    ):
        try:
            achados.extend(fn(*args))
        except Exception as e:
            log.error("Falha na regra %s: %s", fn.__name__, e)
    log.info("Verificações determinísticas: %d achado(s)", len(achados))
    return achados
