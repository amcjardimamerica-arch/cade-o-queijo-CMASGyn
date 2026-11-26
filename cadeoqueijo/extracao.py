"""Extração com proveniência — substitui o armazenamento do PDF.

Política: não se guarda o arquivo, guarda-se a informação e o caminho de volta.
De cada edição extraem-se apenas os trechos pertinentes, e cada trecho carrega
a coordenada exata da origem:

    arquivo · página · deslocamento inicial e final · SHA-256 da edição · URL oficial

Com isso, qualquer trecho pode ser reconduzido ao documento original assinado,
e a integridade da fonte é aferível pela simples comparação de digest. O que se
descarta são as centenas de páginas de licitação, folha de pagamento e
loteamento que nada dizem sobre o conselho.

A economia é de duas ordens de grandeza: uma edição de 14 MB e 800 mil
caracteres costuma render de 3 a 6 mil caracteres de trecho útil.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from util import ACERVO, RAIZ, agora, compactar_espacos, log

TXTGZ = ACERVO / "historico" / "txt_gz"
TRECHOS = ACERVO / "trechos"
TRECHOS.mkdir(parents=True, exist_ok=True)

# Classificadores de contexto. Um trecho pode ter mais de uma classe.
CLASSES = {
    "resolucao": r"RESOLU[ÇC][ÃA]O\s*(?:CMAS)?",
    "ata": r"ATA\s+D[AO]\s+(?:\d+[ªa]?\s+)?(?:REUNI[ÃA]O|PLEN[ÁA]RIA|SESS[ÃA]O)",
    "edital": r"EDITAL(?:\s+DE\s+CHAMAMENTO)?",
    "portaria": r"PORTARIA\s*n?[.º°]",
    "decreto": r"DECRETO\s*(?:MUNICIPAL\s*)?n?[.º°]",
    "lei": r"\bLEI\s*(?:COMPLEMENTAR\s*)?n?[.º°]\s*\d",
    "orcamento": r"\d{2}\.\d{3}\.\d{4}\.\d{4}|dota[çc][ãa]o or[çc]ament[áa]ria|"
                 r"cr[ée]dito (?:adicional|suplementar)",
    "empenho": r"empenho|liquida[çc][ãa]o|pagamento\s+n?[.º°]",
    "parceria": r"termo de (?:fomento|colabora[çc][ãa]o)|acordo de coopera[çc][ãa]o|"
                r"chamamento p[úu]blico",
    "inscricao": r"inscri[çc][ãa]o de entidade|deferimento|indeferimento|CNEAS",
    "prestacao_contas": r"presta[çc][ãa]o de contas|comprova[çc][ãa]o de gastos|"
                        r"demonstrativo\s+(?:sint[ée]tico|f[íi]sico)",
    "convocacao": r"convoca[çc][ãa]o|edital de convoca[çc][ãa]o|confer[êe]ncia municipal",
    "nomeacao": r"nomea[çc][ãa]o|designa[çc][ãa]o|posse\s+d[oe]s?\s+conselheir",
}
CLASSES_RE = {k: re.compile(v, re.IGNORECASE) for k, v in CLASSES.items()}

RE_NUM_ATO = re.compile(
    r"n?[.º°]?\s*(\d{1,4})\s*[/\-]\s*(\d{4})")
RE_CNPJ = re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b")
RE_VALOR = re.compile(r"R\$\s*(\d{1,3}(?:\.\d{3})*,\d{2})")
RE_PAGINA = re.compile(r"\f")


@dataclass
class Trecho:
    """Unidade de arquivamento. Substitui o PDF."""
    id: str
    edicao: str                 # nome do arquivo de origem
    data: str
    url_original: str
    sha256_edicao: str
    pagina_estimada: int
    inicio: int
    fim: int
    classes: list[str]
    ancoras: list[str]
    atos_citados: list[str] = field(default_factory=list)
    cnpjs: list[str] = field(default_factory=list)
    valores: list[float] = field(default_factory=list)
    caracteres: int = 0
    sha256_trecho: str = ""
    texto: str = ""

    def citacao(self) -> str:
        """Referência para uso em peça processual."""
        return (f"Diário Oficial do Município de Goiânia, edição de "
                f"{self.data[8:10]}/{self.data[5:7]}/{self.data[:4]}, "
                f"página aproximada {self.pagina_estimada}. "
                f"Arquivo {self.edicao}, digest SHA-256 {self.sha256_edicao[:16]}…, "
                f"disponível em {self.url_original}")


def _pagina(texto: str, pos: int) -> int:
    """Estima a página pelo número de quebras de formulário até a posição."""
    return texto.count("\f", 0, pos) + 1


def extrair_de_edicao(nome: str, meta: dict, ancoras: re.Pattern,
                      margem: int = 2200, teto: int = 9000) -> list[Trecho]:
    p = TXTGZ / f"{nome[:-4]}.txt.gz"
    if not p.exists():
        return []
    texto = gzip.decompress(p.read_bytes()).decode("utf-8", errors="ignore")

    janelas: list[list] = []
    for m in ancoras.finditer(texto):
        ini, fim = max(0, m.start() - margem), min(len(texto), m.end() + margem)
        if janelas and ini <= janelas[-1][1]:
            janelas[-1][1] = max(janelas[-1][1], fim)
            janelas[-1][2].add(m.group(0).strip())
        else:
            janelas.append([ini, fim, {m.group(0).strip()}])

    saida = []
    for k, (ini, fim, termos) in enumerate(janelas):
        if fim - ini > teto:
            fim = ini + teto
        bruto = texto[ini:fim]
        limpo = compactar_espacos(bruto)
        classes = [c for c, r in CLASSES_RE.items() if r.search(bruto)]
        atos = []
        for mm in re.finditer(r"Resolu[çc][ãa]o[^\n]{0,40}?" + RE_NUM_ATO.pattern,
                              bruto, re.IGNORECASE):
            g = RE_NUM_ATO.search(mm.group(0))
            if g:
                atos.append(f"{int(g.group(1)):03d}/{g.group(2)}")
        t = Trecho(
            id=f"{nome[:-4]}#{k:02d}",
            edicao=nome, data=meta["data"], url_original=meta["url"],
            sha256_edicao=meta["sha256"], pagina_estimada=_pagina(texto, ini),
            inicio=ini, fim=fim, classes=classes, ancoras=sorted(termos),
            atos_citados=sorted(set(atos)), cnpjs=sorted(set(RE_CNPJ.findall(bruto))),
            valores=[float(v.replace(".", "").replace(",", "."))
                     for v in RE_VALOR.findall(bruto)],
            caracteres=len(limpo),
            sha256_trecho=hashlib.sha256(limpo.encode("utf-8")).hexdigest(),
            texto=limpo,
        )
        saida.append(t)
    return saida


def extrair_acervo(registro: dict, dominio: dict) -> dict:
    padroes = dominio["termos"]["ancora"] + dominio["termos"].get("programas", [])
    ancoras = re.compile("|".join(f"(?:{p})" for p in padroes), re.IGNORECASE)

    todos: list[Trecho] = []
    total_original = 0
    for nome, meta in registro.items():
        if meta.get("erro"):
            continue
        total_original += meta.get("caracteres", 0)
        todos.extend(extrair_de_edicao(nome, meta, ancoras))

    arquivo = TRECHOS / f"{dominio['id']}.jsonl.gz"
    with gzip.open(arquivo, "wt", encoding="utf-8") as f:
        for t in todos:
            f.write(json.dumps(asdict(t), ensure_ascii=False) + "\n")

    util = sum(t.caracteres for t in todos)
    resumo = {
        "dominio": dominio["id"],
        "edicoes": sum(1 for m in registro.values() if not m.get("erro")),
        "trechos": len(todos),
        "caracteres_originais": total_original,
        "caracteres_arquivados": util,
        "reducao": round(100 * (1 - util / max(total_original, 1)), 2),
        "mb_arquivo": round(arquivo.stat().st_size / 1e6, 2),
        "gerado_em": agora().isoformat(),
    }
    log.info("Extração: %d trechos de %d edições | %s caracteres -> %s (%.2f%% menos) | %s MB",
             len(todos), resumo["edicoes"], f"{total_original:,}", f"{util:,}",
             resumo["reducao"], resumo["mb_arquivo"])
    return resumo


def carregar(dominio_id: str = "assistencia_social"):
    arquivo = TRECHOS / f"{dominio_id}.jsonl.gz"
    if not arquivo.exists():
        return []
    with gzip.open(arquivo, "rt", encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


if __name__ == "__main__":
    import yaml
    from util import ESTADO, ler_json
    dom = yaml.safe_load(
        (RAIZ / "config" / "dominios" /
         f"{sys.argv[1] if len(sys.argv) > 1 else 'assistencia_social'}.yml"
         ).read_text(encoding="utf-8"))
    reg = ler_json(ESTADO / "historico_registro.json", {})
    print(json.dumps(extrair_acervo(reg, dom), ensure_ascii=False, indent=2))
