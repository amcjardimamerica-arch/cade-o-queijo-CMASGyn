"""Peças comuns das telas: números com selo, meses, funções de governo e secretarias."""

from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from datetime import date, timedelta
from pathlib import Path

from .. import partes as _partes

MESES = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro",
         "outubro", "novembro", "dezembro")
MESES_CURTOS = ("jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez")

# Funções de governo (Portaria MOG 42/1999).
FUNCOES = {
    "01": "Legislativa", "02": "Judiciária", "03": "Essencial à Justiça", "04": "Administração",
    "05": "Defesa Nacional", "06": "Segurança Pública", "07": "Relações Exteriores",
    "08": "Assistência Social", "09": "Previdência Social", "10": "Saúde", "11": "Trabalho",
    "12": "Educação", "13": "Cultura", "14": "Direitos da Cidadania", "15": "Urbanismo",
    "16": "Habitação", "17": "Saneamento", "18": "Gestão Ambiental", "19": "Ciência e Tecnologia",
    "20": "Agricultura", "21": "Organização Agrária", "22": "Indústria", "23": "Comércio e Serviços",
    "24": "Comunicações", "25": "Energia", "26": "Transporte", "27": "Desporto e Lazer",
    "28": "Encargos Especiais", "99": "Reserva de Contingência",
}

# A função de governo em que cada órgão costuma empenhar, pelo nome do órgão. Serve para ligar o
# órgão do PNCP à execução da matriz, que só traz a função; a tela diz que é a função inteira.
_FUNCAO_DO_ORGAO = (
    ("CAMARA", "01"), ("PROCURADORIA", "03"), ("PREVIDENCIA", "09"), ("ASSISTENCIA A SAUDE DOS SERV", "10"),
    ("SAUDE", "10"), ("ENSINO", "12"), ("EDUCACAO", "12"), ("ASSISTENCIA SOCIAL", "08"),
    ("HUMANO E SOCIAL", "08"), ("DIREITOS HUMANOS", "14"), ("TRANSITO", "26"), ("MEIO AMBIENTE", "18"),
    ("ESPORTE", "27"), ("HABITACAO", "16"), ("SANEAMENTO", "17"), ("TURISMO", "23"),
    ("ECONOMIA CRIATIVA", "23"), ("INOVACAO", "19"), ("CIENCIA", "19"), ("INFRAESTRUTURA", "15"),
    ("DESENVOLVIMENTO URBANO", "15"), ("REGULACAO", "04"), ("COMUNICACAO", "04"), ("ADMINISTRACAO", "04"),
    ("FINANCAS", "04"), ("CONTROLADORIA", "04"), ("GOVERNO", "04"), ("PRIORIDADES", "04"),
)


def sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", str(texto or "")) if not unicodedata.combining(c)).upper()


def funcao_do_orgao(nome: str) -> str | None:
    n = sem_acento(nome)
    for termo, funcao in _FUNCAO_DO_ORGAO:
        if termo in n:
            return funcao
    return None


def N(valor, fonte: str, selo: str | None = None) -> dict | None:
    """Um número das telas: sempre com a chave da fonte; o selo é opcional (a fonte já tem um)."""
    if valor is None:
        return None
    d = {"v": round(float(valor), 4), "f": fonte}
    if selo:
        d["s"] = selo
    return d


def abrir(caminho: Path | str) -> sqlite3.Connection:
    """Abre o banco só para leitura (as telas nunca escrevem nele)."""
    return _partes.conectar_leitura(Path(caminho))


def tabela_existe(con: sqlite3.Connection, nome: str) -> bool:
    return _partes.tem_tabela(con, nome)


def consultar(con: sqlite3.Connection, sql: str, args=()) -> list[tuple]:
    try:
        return con.execute(sql, args).fetchall()
    except sqlite3.OperationalError:
        return []


def fim_do_mes(competencia: str) -> date:
    ano, mes = (int(x) for x in competencia.split("-"))
    return date(ano + (mes == 12), 1 if mes == 12 else mes + 1, 1) - timedelta(days=1)


def mes_menos(mes: str, n: int) -> str:
    ano, m = (int(x) for x in mes.split("-"))
    total = ano * 12 + (m - 1) - n
    return f"{total // 12}-{total % 12 + 1:02d}"


def rotulo_mes(competencia: str) -> str:
    ano, mes = competencia.split("-")
    return f"{MESES[int(mes) - 1]} de {ano}"


def chaves_de_fonte(obj) -> set[str]:
    """Todas as chaves de fonte usadas num pedaço de dados (para levar só elas à página)."""
    achadas: set[str] = set()

    def anda(o):
        if isinstance(o, dict):
            f = o.get("f")
            if isinstance(f, str) and "v" in o:
                achadas.add(f)
            for k, v in o.items():
                if k in ("fonte", "fontes_mes") and isinstance(v, str):
                    achadas.add(v)
                anda(v)
        elif isinstance(o, list):
            for v in o:
                anda(v)
    anda(obj)
    return achadas


def json_seguro(obj) -> str:
    """JSON para ir dentro de <script type="application/json"> sem fechar a tag."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def sem_travessao(texto: str) -> str:
    """As telas não usam travessão: o do texto de origem vira vírgula (a fonte original fica a um clique)."""
    return re.sub(r"\s*[—–]\s*", ", ", texto)


def limpa(texto, limite: int | None = None) -> str:
    t = sem_travessao(" ".join(str(texto or "").split()))
    if limite and len(t) > limite:
        t = t[: limite - 1].rstrip() + "…"
    return t


CNPJ = re.compile(r"(?<!\d)(\d{14})(?!\d)")

CPF_FORMATADO = re.compile(r"(?<!\d)\d{3}\.\d{3}\.\d{3}-\d{2}(?!\d)")


def documento_publico(ni) -> str:
    """O documento do fornecedor que pode ir às telas: o CNPJ; o CPF de pessoa física nunca aparece."""
    d = re.sub(r"\D", "", str(ni or ""))
    return d if len(d) == 14 else ""


def sem_cpf(obj):
    """Prepara os textos que vão às telas: tira qualquer CPF escrito por extenso (000.000.000-00) e troca o
    travessão do texto de origem por vírgula."""
    if isinstance(obj, str):
        if "—" in obj or "–" in obj:
            obj = sem_travessao(obj)
        return CPF_FORMATADO.sub("CPF omitido", obj) if "-" in obj else obj
    if isinstance(obj, list):
        return [sem_cpf(x) for x in obj]
    if isinstance(obj, dict):
        return {k: sem_cpf(v) for k, v in obj.items()}
    return obj
