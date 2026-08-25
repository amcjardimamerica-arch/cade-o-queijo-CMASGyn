"""Movimentação bancária da SEMASDH/FMAS com minimização de dados pessoais.

Este módulo é propositalmente mais restritivo que ``financeiro.py``. Dotação,
empenho e crédito adicional não são tratados como dinheiro que entrou ou saiu
da conta. Uma ocorrência só é classificada como movimentação quando o trecho
publicado contém, ao mesmo tempo:

* referência expressa à SEMASDH, ao FMAS ou à conta do Fundo;
* marcador de entrada ou de saída bancária; e
* valor monetário.

Para pessoa física, conserva-se somente o primeiro nome. CPF e nome completo
jamais são gravados na saída deste módulo.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import extracao
from util import RAIZ, agora, gravar_json, log

SAIDA = RAIZ / "dados" / "movimentacao_contas.json"

RE_ORGAO = re.compile(
    r"\b(?:SEMASDH|SEMAS|FMAS(?:Gyn)?|Fundo Municipal de Assist[êe]ncia Social)\b",
    re.IGNORECASE,
)
RE_CONTA = re.compile(
    r"\b(?:conta(?:\s+banc[áa]ria)?|ag[êe]ncia|extrato|saldo|cr[ée]dito|d[ée]bito|"
    r"transfer[êe]ncia|ordem banc[áa]ria|pagamento)\b",
    re.IGNORECASE,
)
RE_ENTRADA = re.compile(
    r"\b(?:cr[ée]dito em conta|valor (?:recebido|creditado)|transfer[êe]ncia recebida|"
    r"repasse (?:recebido|creditado)|dep[óo]sito|ingresso de recursos?)\b",
    re.IGNORECASE,
)
RE_SAIDA = re.compile(
    r"\b(?:d[ée]bito em conta|valor (?:pago|debitado)|pagamento efetuado|"
    r"ordem (?:de pagamento|banc[áa]ria)|transfer[êe]ncia (?:efetuada|realizada)|"
    r"sa[íi]da de recursos?)\b",
    re.IGNORECASE,
)
RE_VALOR = re.compile(r"R\$\s*(\d{1,3}(?:\.\d{3})*,\d{2})", re.IGNORECASE)
RE_FONTE = re.compile(
    r"(?:fonte(?:\s+de\s+recursos?)?|origem(?:\s+do\s+recurso)?)\s*[:\-]?\s*"
    r"([A-ZÁ-Ú0-9][A-ZÁ-Ú0-9 ._\-/]{1,90})",
    re.IGNORECASE,
)
RE_DESTINO = re.compile(
    r"(?:destino|favorecid[oa]|benefici[áa]ri[oa]|creditad[oa]\s+a|pago\s+a)\s*[:\-]?\s*"
    r"([A-ZÁ-Ú][A-Za-zÀ-ÿ' -]{1,100})",
    re.IGNORECASE,
)
RE_CNPJ = re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b")
RE_CPF_SUPRIMIDO = re.compile(r"\[CPF-SUPRIMIDO\]|\bCPF\b", re.IGNORECASE)

PALAVRAS_INVALIDAS = {
    "a", "ao", "aos", "de", "da", "das", "do", "dos", "em", "e", "para",
    "pessoa", "beneficiario", "beneficiária", "beneficiário", "favorecido",
    "favorecida", "não", "nao", "identificado", "identificada",
}


def _valor(texto: str) -> float:
    return float(texto.replace(".", "").replace(",", "."))


def _limpar_campo(texto: str | None) -> str | None:
    if not texto:
        return None
    texto = re.split(r"[.;\n|]", texto, maxsplit=1)[0]
    texto = re.sub(r"\s+", " ", texto).strip(" -:,")
    return texto[:100] or None


def primeiro_nome_pessoa_fisica(janela: str) -> str | None:
    """Retorna apenas o primeiro nome quando a pessoa física é inequívoca."""
    if not RE_CPF_SUPRIMIDO.search(janela) or RE_CNPJ.search(janela):
        return None
    m = RE_DESTINO.search(janela)
    if not m:
        return None
    candidato = _limpar_campo(m.group(1)) or ""
    for palavra in re.findall(r"[A-Za-zÀ-ÿ']+", candidato):
        if palavra.casefold() not in PALAVRAS_INVALIDAS and len(palavra) >= 2:
            return palavra[:1].upper() + palavra[1:].lower()
    return None


def _destino(janela: str) -> tuple[str | None, str]:
    primeiro = primeiro_nome_pessoa_fisica(janela)
    if primeiro:
        return primeiro, "pessoa_fisica_primeiro_nome"
    m = RE_DESTINO.search(janela)
    if m and RE_CNPJ.search(janela):
        return _limpar_campo(m.group(1)), "pessoa_juridica"
    return None, "nao_identificado"


def apurar(dominio: dict) -> dict:
    registros: list[dict] = []
    for trecho in extracao.carregar(dominio["id"]):
        texto = trecho["texto"]
        if not (RE_ORGAO.search(texto) and RE_CONTA.search(texto)):
            continue
        entradas = list(RE_ENTRADA.finditer(texto))
        saidas = list(RE_SAIDA.finditer(texto))
        for tipo, marcadores in (("entrada", entradas), ("saida", saidas)):
            for marcador in marcadores:
                ini = max(0, marcador.start() - 280)
                fim = min(len(texto), marcador.end() + 520)
                janela = texto[ini:fim]
                valor = RE_VALOR.search(janela)
                if not valor:
                    continue
                fonte = RE_FONTE.search(janela)
                destino, tipo_destino = _destino(janela) if tipo == "saida" else (None, "nao_aplicavel")
                registros.append({
                    "tipo": tipo,
                    "data": trecho["data"],
                    "edicao": trecho["edicao"],
                    "valor": _valor(valor.group(1)),
                    "fonte_recurso": _limpar_campo(fonte.group(1)) if fonte else None,
                    "destino_recurso": destino,
                    "tipo_destino": tipo_destino,
                    "url": trecho["url_original"],
                    "pagina": trecho["pagina_estimada"],
                    "trecho_id": trecho["id"],
                    "criterio": "movimentacao_bancaria_expressa",
                })

    # Deduplica a mesma ocorrência capturada por expressões equivalentes.
    unicos = {}
    for r in registros:
        chave = (r["tipo"], r["trecho_id"], r["valor"], r["destino_recurso"])
        unicos[chave] = r
    registros = sorted(unicos.values(), key=lambda x: (x["data"], x["tipo"], x["valor"]), reverse=True)
    entradas = [r for r in registros if r["tipo"] == "entrada"]
    saidas = [r for r in registros if r["tipo"] == "saida"]
    dados = {
        "gerado_em": agora().isoformat(),
        "orgao": "SEMASDH/FMAS",
        "escopo": "movimentacao_bancaria_documentalmente_demonstrada",
        "entrada_de_valores_em_conta_da_semasdh": round(sum(r["valor"] for r in entradas), 2),
        "saida_de_valores_da_conta_da_semasdh": round(sum(r["valor"] for r in saidas), 2),
        "entradas": entradas,
        "saidas": saidas,
        "quantidade_entradas": len(entradas),
        "quantidade_saidas": len(saidas),
        "fontes_nao_identificadas": sum(1 for r in entradas if not r["fonte_recurso"]),
        "destinos_nao_identificados": sum(1 for r in saidas if not r["destino_recurso"]),
        "status": "DEMONSTRADO" if registros else "NAO_DEMONSTRADO_NO_ACERVO",
        "nota_metodologica": (
            "Dotação, crédito adicional e empenho não são movimentação bancária. "
            "Os totais incluem somente trechos com marcador expresso de conta e de "
            "entrada ou saída. Pessoa física é exibida apenas pelo primeiro nome."
        ),
    }
    gravar_json(SAIDA, dados)
    log.info("Movimentação de contas: %d entrada(s), %d saída(s)", len(entradas), len(saidas))
    return dados


if __name__ == "__main__":
    import yaml

    nome = sys.argv[1] if len(sys.argv) > 1 else "assistencia_social"
    dominio = yaml.safe_load(
        (RAIZ / "config" / "dominios" / f"{nome}.yml").read_text(encoding="utf-8")
    )
    print(json.dumps(apurar(dominio), ensure_ascii=False, indent=2))
