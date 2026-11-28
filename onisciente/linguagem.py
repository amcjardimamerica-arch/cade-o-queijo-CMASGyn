"""Linguagem direta: o que aparece para quem lê não usa metáfora.

Decisão do usuário de 28/11/2026: a imagem do rio era só um exemplo de fluxo para o desenho e não a premissa
do sistema. Os textos que o Onisciente mostra (telas, parecer, fichas) dizem o nome técnico de cada coisa:
origem do dinheiro, recurso vinculado ou livre, finalidade, receita por espécie, diferença da execução.

Os geradores já escrevem assim. ``direto`` reescreve os textos guardados antes da decisão (fichas dos
panoramas mensais, pareceres já publicados), sem tocar em número nenhum: só troca as expressões da lista.
``METAFORA`` é a régua das travas: acha a palavra da metáfora e deixa passar nome de lugar ("Rio Verde",
"Rio de Janeiro", "Foz do Iguaçu"), razão social em caixa alta ("BEIRA RIO") e código de ficha ("RIO-ORIGEM").
"""

from __future__ import annotations

import re

# Da expressão mais longa para a mais curta, para a curta não comer o pedaço da longa.
_TROCAS: tuple[tuple[str, str], ...] = (
    # títulos e legendas do parecer
    ("O leito: água vinculada empenhada fora da sua finalidade", "Recurso vinculado empenhado fora da sua finalidade"),
    ("Rio: água vinculada no leito errado, receita sem fonte",
     "Origem e fonte: recurso vinculado fora da finalidade, receita sem fonte"),
    ("A fonte diz se a água é vinculada ou livre", "A fonte diz se o recurso é vinculado ou livre"),
    ("se a água é livre ou vinculada", "se o recurso é livre ou vinculado"),
    ("Quadros do mesmo relatório: confere a montagem do rio, mas não é outra via e não entra na coerência.",
     "Quadros do mesmo relatório: confere a soma por espécie, mas não é outra via e não entra na coerência."),
    ("O rio e a receita realizada do RREO se separam em mais de 1%: a montagem do rio está errada e o número do rio "
     "não vale até ser corrigida (falha do sistema).",
     "A soma por espécie e a receita realizada do RREO se separam em mais de 1%: a soma está errada e não vale até "
     "ser corrigida (falha do sistema)."),
    ("rio: soma dos afluentes menos o FUNDEB entregue", "soma das espécies menos o FUNDEB entregue"),
    ("rio: IPTU, ISS, ITBI, IRRF e taxas", "soma das espécies: IPTU, ISS, ITBI, IRRF e taxas"),
    ("rio: transferências menos o FUNDEB entregue", "soma das transferências menos o FUNDEB entregue"),
    ("O rio do Município inteiro", "A receita do Município inteiro"),
    ("O rio contra o próprio RREO", "A soma por espécie contra o próprio RREO"),
    ("O rio mostra o previsto na LOA", "A origem do dinheiro mostra o previsto na LOA"),
    ("O rio e o desvio de finalidade", "A receita por fonte e o desvio de finalidade"),
    ("Receita realizada pelo rio", "Receita realizada pela soma das espécies"),
    ("Afluentes somados", "Espécies de receita somadas"),
    ("FUNDEB entregue ao fundo (sangria)", "FUNDEB entregue ao fundo (dedução)"),
    ("Destinações sem leito no catálogo", "Destinações sem finalidade definida no catálogo"),
    ("Margem do Município inteiro", "Diferença da execução do Município inteiro"),
    ("Margem: o que não chegou", "Diferença da execução"),
    ("As margens (previsto e não empenhado", "As diferenças da execução (previsto e não empenhado"),
    ("Leito (função)", "Funções permitidas"),
    ('aria-label="Rio de afluentes"', 'aria-label="Receita por espécie"'),
    ("Sem afluente publicado para a competência: o rio não pode ser desenhado",
     "Sem receita publicada para a competência: a origem do dinheiro não pode ser desenhada"),
    ("<h2>2. O rio</h2>", "<h2>2. Origem do dinheiro</h2>"),
    ("<th>O leito</th>", "<th>Conferência da receita</th>"),
    ("o leito não pôde ser conferido", "a finalidade não pôde ser conferida"),
    ("os demais estão na tela do rio, mês a mês", "os demais estão na tela Origem do dinheiro, mês a mês"),
    ("Os tributos próprios entram pelo rio", "Os tributos próprios aparecem na tela Origem do dinheiro"),
    ("o rio fica com a fonte padrão de cada espécie", "a receita fica com a fonte padrão de cada espécie"),
    # fichas e textos curtos
    ("empenhada fora do seu leito", "empenhada fora da sua finalidade"),
    ("empenhado fora do seu leito", "empenhado fora da sua finalidade"),
    ("fora do seu leito", "fora da sua finalidade"),
    ("fora do leito", "fora da finalidade"),
    ("no leito errado", "fora da finalidade"),
    ("água vinculada", "recurso vinculado"),
    ("Água vinculada", "Recurso vinculado"),
    ("água livre", "recurso livre"),
    ("Água livre", "Recurso livre"),
    ("água parada", "arrecadado e não empenhado"),
    ("Água parada", "Arrecadado e não empenhado"),
    ("Demais afluentes", "Demais receitas"),
)
_PADRAO = re.compile("|".join(re.escape(a) for a, _ in _TROCAS))
_PARA = dict(_TROCAS)

# A régua das travas. Minúscula: qualquer uso é a metáfora. Maiúscula inicial: só quando não é nome de lugar
# (seguida de outra palavra com maiúscula, ou de "de/do/da" e maiúscula). Caixa alta inteira não entra.
_MINUSCULA = r"rio|rios|afluentes?|nascentes?|correntezas?|leito|foz|margens|sangria|rio-mapa"
_INICIAL = r"Rio|Rios|Afluentes?|Nascentes?|Correntezas?|Leito|Foz|Margens|Sangria"
METAFORA = re.compile(
    rf"(?<![\wÀ-ÿ-])(?:(?:{_MINUSCULA})|(?:{_INICIAL})(?!\s+(?:[A-ZÀ-Ý]|d[eoa]s?\s+[A-ZÀ-Ý])))(?![\wÀ-ÿ-])"
    r"|água (?:vinculada|livre|parada)|Água (?:vinculada|livre|parada)")


def direto(texto: str) -> str:
    """O texto com as expressões da metáfora trocadas pelo nome técnico (nenhum número muda)."""
    if not texto or not isinstance(texto, str):
        return texto
    return _PADRAO.sub(lambda m: _PARA[m.group(0)], texto)


# Palavra com maiúscula logo antes ("Tres Rios", "Pires Do Rio") também é nome de lugar; artigo não ("A Foz").
_ANTES_DE_LUGAR = re.compile(r"(?:^|[^\wÀ-ÿ])(?:[A-ZÀ-Ý][\wÀ-ÿ]{2,}|D[eoa]s?)\s+$")


def metaforas(texto: str) -> list[str]:
    """As palavras da metáfora que sobraram num texto visível (para as travas)."""
    texto = texto or ""
    out = []
    for m in METAFORA.finditer(texto):
        palavra = m.group(0)
        if palavra[0].isupper() and _ANTES_DE_LUGAR.search(texto[max(0, m.start() - 40):m.start()]):
            continue
        out.append(palavra)
    return out
