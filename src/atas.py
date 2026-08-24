"""Conciliação de conselheiros: quem vota, quem assina, e se o voto é nominal.

Três verificações, todas determinísticas:

  ATA-04  Voto nominal — o Regimento Interno exige registro do voto de cada
          conselheiro. Ata que registre apenas "aprovado por unanimidade" ou
          placar agregado, sem nominar, descumpre a exigência.

  ATA-05  Conciliação votante x signatário — quem consta como presente e
          votante deve constar entre os signatários, e vice-versa. Divergência
          é vício de formalização.

  ATA-06  Composição paritária — o número de conselheiros governamentais e
          não governamentais presentes deve guardar a paridade do artigo 16 da
          Lei 8.742/1993 e do Regimento Interno.

Nomes de conselheiro são dado funcional de agente público no exercício de
função de controle social — categoria distinta do dado de usuário do SUAS,
que segue integralmente suprimido na ingestão.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

from util import agora, log

# ---------------------------------------------------------------- expressões
RE_PRESENTES = re.compile(
    r"(presen(?:tes|ça)[^\n]{0,80}?:|lista de presen[çc]a|compareceram)(.{0,4000}?)"
    r"(?=\n\s*(?:pauta|ordem do dia|expediente|delibera|abertura|encerr|assinat))",
    re.IGNORECASE | re.DOTALL)

RE_ASSINATURAS = re.compile(
    r"(assinat[ua]ra?s?|assinam|firmam|conselheir[oa]s? presentes que assinam)"
    r"(.{0,4000}?)$", re.IGNORECASE | re.DOTALL)

RE_NOME = re.compile(
    r"\b([A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-zâêôãõáéíóúç]{2,})"
    r"(?:\s+(?:d[aeo]s?|e)\s+|\s+)"
    r"([A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-zâêôãõáéíóúç]{2,}(?:\s+[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-zâêôãõáéíóúç]{2,}){0,3})\b")

RE_VOTO_AGREGADO = re.compile(
    r"(aprovad[oa]\s+por\s+unanimidade|aprovad[oa]\s+por\s+maioria|"
    r"unanimidade\s+dos\s+presentes|aprovad[oa]\s+sem\s+ressalvas?)", re.IGNORECASE)

RE_VOTO_NOMINAL = re.compile(
    r"(vot(?:o|ou|aram|os)\s+(?:favor[áa]v|contr[áa]r|nominal)|"
    r"a\s+favor:|contra:|absten[çc][ãa]o(?:\s+d[eo])?:|"
    r"votaram\s+favoravelmente)", re.IGNORECASE)

RE_SEGMENTO_GOV = re.compile(
    r"(governamental|represent(?:ante|ação)\s+d[oa]\s+(?:poder\s+público|governo|"
    r"secretaria|munic[íi]pio))", re.IGNORECASE)
RE_SEGMENTO_SOC = re.compile(
    r"(n[ãa]o[- ]governamental|sociedade civil|usu[áa]ri[oa]s|"
    r"trabalhador(?:es)?\s+d[oa]\s+[áa]rea|entidade[s]?\s+de\s+assist)", re.IGNORECASE)

RE_QUORUM = re.compile(r"(qu[óo]rum|quorum)", re.IGNORECASE)

PALAVRAS_FALSAS = {
    "conselho municipal", "assistencia social", "diario oficial", "goiania goias",
    "ordem dia", "poder publico", "sociedade civil", "presidente conselho",
    "secretaria municipal", "fundo municipal", "estado goias", "reuniao ordinaria",
    "reuniao extraordinaria", "plenaria ordinaria", "mesa diretora",
}


def _chave(nome: str) -> str:
    s = unicodedata.normalize("NFKD", nome)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"\b(d[aeo]s?|e|junior|neto|filho|sr|sra|dr|dra)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _nomes(bloco: str) -> list[str]:
    achados = []
    for m in RE_NOME.finditer(bloco):
        nome = re.sub(r"\s+", " ", m.group(0)).strip()
        if _chave(nome) in PALAVRAS_FALSAS or len(_chave(nome).split()) < 2:
            continue
        achados.append(nome)
    vistos, saida = set(), []
    for n in achados:
        k = _chave(n)
        if k not in vistos:
            vistos.add(k)
            saida.append(n)
    return saida


@dataclass
class Ata:
    documento: str
    data: str
    presentes: list[str] = field(default_factory=list)
    signatarios: list[str] = field(default_factory=list)
    voto_nominal: bool = False
    voto_agregado: bool = False
    menciona_quorum: bool = False
    governamentais: int = 0
    nao_governamentais: int = 0


def analisar(documento: str, data: str, texto: str) -> Ata:
    a = Ata(documento=documento, data=data)
    mp = RE_PRESENTES.search(texto)
    if mp:
        a.presentes = _nomes(mp.group(2))
        a.governamentais = len(RE_SEGMENTO_GOV.findall(mp.group(2)))
        a.nao_governamentais = len(RE_SEGMENTO_SOC.findall(mp.group(2)))
    ms = RE_ASSINATURAS.search(texto)
    if ms:
        a.signatarios = _nomes(ms.group(2))
    a.voto_nominal = bool(RE_VOTO_NOMINAL.search(texto))
    a.voto_agregado = bool(RE_VOTO_AGREGADO.search(texto))
    a.menciona_quorum = bool(RE_QUORUM.search(texto))
    return a


def conciliar(a: Ata) -> list[dict]:
    """Produz os achados de ATA-04, ATA-05 e ATA-06."""
    out: list[dict] = []
    base = {"documento": a.documento, "data_ref": a.data,
            "detectado_em": agora().isoformat()}

    # -------- ATA-04: voto nominal
    if a.voto_agregado and not a.voto_nominal:
        out.append({**base, "regra": "ATA-04", "severidade": "media",
            "titulo": "Deliberação sem registro de voto nominal",
            "detalhe": ("A ata registra o resultado de forma agregada, sem nominar o voto de "
                        "cada conselheiro. Havendo exigência de voto nominal no Regimento "
                        "Interno, o registro apenas agregado impede a aferição individual da "
                        "manifestação e compromete a rastreabilidade da deliberação."),
            "fundamento": "Regimento Interno do CMASGyn; Lei 9.784/1999, artigo 50"})

    # -------- ATA-05: conciliação votante x signatário
    if a.presentes and a.signatarios:
        kp = {_chave(n): n for n in a.presentes}
        ks = {_chave(n): n for n in a.signatarios}
        so_presentes = sorted(kp[k] for k in kp.keys() - ks.keys())
        so_signatarios = sorted(ks[k] for k in ks.keys() - kp.keys())
        if so_presentes or so_signatarios:
            out.append({**base, "regra": "ATA-05",
                "severidade": "alta" if so_signatarios else "media",
                "titulo": "Divergência entre presentes e signatários da ata",
                "detalhe": (
                    f"Constam como presentes e não assinam: {len(so_presentes)} "
                    f"({'; '.join(so_presentes[:6])}). "
                    f"Assinam sem constar da lista de presença: {len(so_signatarios)} "
                    f"({'; '.join(so_signatarios[:6])}). "
                    "Assinatura por quem não consta presente é vício de formalização "
                    "com potencial de nulidade da deliberação."),
                "fundamento": "Regimento Interno do CMASGyn",
                "so_presentes": so_presentes, "so_signatarios": so_signatarios})

    # -------- ATA-06: paridade
    if a.governamentais and a.nao_governamentais:
        if a.governamentais != a.nao_governamentais:
            out.append({**base, "regra": "ATA-06", "severidade": "media",
                "titulo": "Possível quebra de paridade na composição da sessão",
                "detalhe": (
                    f"Indícios de {a.governamentais} representação(ões) governamental(is) "
                    f"e {a.nao_governamentais} não governamental(is). A paridade entre "
                    "governo e sociedade civil é da essência do conselho, na forma do "
                    "artigo 16 da Lei 8.742/1993. Conferir na ata integral."),
                "fundamento": "Lei 8.742/1993, artigo 16"})

    # -------- quórum ausente
    if not a.menciona_quorum and a.presentes:
        out.append({**base, "regra": "ATA-03", "severidade": "baixa",
            "titulo": "Ata sem menção expressa a quórum",
            "detalhe": ("Não há registro expresso de verificação de quórum. A ausência "
                        "impede aferir a regularidade da instalação da sessão."),
            "fundamento": "Regimento Interno do CMASGyn"})
    return out


def processar_lote(atas: list[tuple[str, str, str]]) -> tuple[list[dict], dict]:
    """Recebe (documento, data, texto). Devolve achados e o painel de conselheiros."""
    achados: list[dict] = []
    presencas, assinaturas = Counter(), Counter()
    nomes_canonicos: dict[str, str] = {}

    for doc, data, texto in atas:
        a = analisar(doc, data, texto)
        achados.extend(conciliar(a))
        for n in a.presentes:
            k = _chave(n); presencas[k] += 1; nomes_canonicos.setdefault(k, n)
        for n in a.signatarios:
            k = _chave(n); assinaturas[k] += 1; nomes_canonicos.setdefault(k, n)

    painel = [{
        "nome": nomes_canonicos[k],
        "presencas": presencas.get(k, 0),
        "assinaturas": assinaturas.get(k, 0),
        "divergencia": presencas.get(k, 0) - assinaturas.get(k, 0),
    } for k in set(presencas) | set(assinaturas)]
    painel.sort(key=lambda x: -abs(x["divergencia"]))

    log.info("Atas processadas: %d | achados: %d | conselheiros distintos: %d",
             len(atas), len(achados), len(painel))
    return achados, {"conselheiros": painel, "atas_analisadas": len(atas)}
