"""Diagnóstico da coleta histórica: onde o sistema falha e onde pode melhorar.

Lê o banco da coleta histórica e devolve três listas, que nunca se misturam:

- **falha**: o sistema não alcançou a fonte (vermelho). É problema nosso.
- **lacuna**: a fonte respondeu e o dado do município não estava lá (roxo).
- **melhoria**: o sistema funciona, mas pode alcançar mais ou errar menos.

Além do banco, faz conferências estáticas nos coletores antigos do Cadê o
Queijo, para apontar o que já se sabe que está quebrado antes de rodar.
"""

from __future__ import annotations

import json
import re
import tomllib
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

from . import RAIZ
from .historico import Banco, _norm, meses

NOME_DOS_MOTORES = {
    "siconfi": "SICONFI (Tesouro Nacional)",
    "siconfi-antiga": "SICONFI pelos endereços antigos",
    "qd": "Diário Oficial pelo Querido Diário",
    "sileg": "Diário Oficial pelo índice do SILEG",
    "fnas": "Repasses federais (FNAS)",
    "pncp": "Contratações (PNCP)",
    "fontes": "Portais e endereços configurados",
    "ctresb": "Normas federais (ctresb/leis)",
    "tesouro": "Transferências constitucionais (Tesouro)",
    "siops": "Demonstrativo da saúde (SIOPS)",
    "siope": "Demonstrativo da educação (SIOPE)",
    "transferencias": "Transferências federais (Portal da Transparência)",
    "msc": "Matriz de Saldos Contábeis (SICONFI)",
    "pncp_detalhe": "Detalhe das compras e contratos (PNCP e Compras.gov.br)",
    "sileg-normas": "Leis de Goiânia baixadas do SILEG",
    "sileg-procura": "Procura das leis não localizadas no SILEG",
    "fns": "Fundo Nacional de Saúde (repasses fundo a fundo)",
    "fnde": "FNDE (liberações da educação)",
    "transferegov": "Transferegov (transferências especiais e convênios)",
    "sancoes": "Empresas punidas (CEIS e CNEP)",
    "economia_go": "Cota-parte do Estado (Secretaria da Economia de Goiás)",
    "tcu": "Decisões do TCU",
    "tcm": "Decisões do TCM-GO",
    "execucao_goiania": "Execução item a item no portal de Goiânia (TransWeb)",
    "cnpj": "Cadastro das empresas na Receita Federal (CNPJ e QSA)",
    "impedimentos": "Impedimentos (CEPIM e inidôneos do TCU)",
}


@dataclass
class Achado:
    tipo: str          # falha | lacuna | melhoria
    motor: str
    titulo: str
    detalhe: str
    proposta: str = ""


def _meta(banco: Banco) -> dict[str, str]:
    return dict(banco.consultar("SELECT chave, valor FROM meta"))


def _faixas(lista: list[str]) -> str:
    """'2024-11, 2024-12, 2025-01, 2025-03' -> '2024-11 a 2025-01, 2025-03'."""
    if not lista:
        return ""
    ordem = {m: i for i, m in enumerate(meses(min(lista), max(lista)))}
    grupos: list[list[str]] = []
    for m in sorted(lista):
        if grupos and ordem[m] == ordem[grupos[-1][-1]] + 1:
            grupos[-1].append(m)
        else:
            grupos.append([m])
    return ", ".join(g[0] if len(g) == 1 else f"{g[0]} a {g[-1]}" for g in grupos)


def _reais(valor: float) -> str:
    return "R$ " + f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def resumo_por_motor(banco: Banco) -> list[dict]:
    linhas = banco.consultar(
        "SELECT motor, COUNT(*), SUM(ok), SUM(segundos), SUM(tentativas), "
        "SUM(CASE WHEN http = 429 THEN 1 ELSE 0 END) FROM coletas GROUP BY motor ORDER BY motor")
    saida = []
    for motor, total, ok, segundos, tentativas, n429 in linhas:
        erros = Counter(e for (e,) in banco.consultar(
            "SELECT erro FROM coletas WHERE motor = ? AND ok = 0", motor))
        saida.append({"motor": motor, "nome": NOME_DOS_MOTORES.get(motor, motor),
                      "chamadas": total, "ok": ok or 0, "falhas": total - (ok or 0),
                      "tentativas": tentativas or 0, "http_429": n429 or 0,
                      "segundos": round(segundos or 0, 1),
                      "erros": dict(erros.most_common(5))})
    return saida


# --- Conferências por motor ---------------------------------------------------------

def _motores_quebrados(meta: dict) -> list[Achado]:
    saida = []
    for chave, valor in meta.items():
        if chave.startswith("motor:"):
            info = json.loads(valor)
            if info.get("erro"):
                motor = chave.split(":", 1)[1]
                saida.append(Achado("falha", motor, f"O motor {motor} quebrou no meio da coleta",
                                    info["erro"], "Corrigir o código do motor; os outros motores "
                                    "seguiram rodando."))
    return saida


def _chamadas(resumo: list[dict]) -> list[Achado]:
    saida = []
    for r in resumo:
        # SICONFI, Diário Oficial, portais e normas têm conferência própria, mais precisa
        if r["falhas"] and r["motor"] in ("fnas", "pncp"):
            erro, vezes = next(iter(r["erros"].items()), ("?", 0))
            saida.append(Achado(
                "falha", r["motor"],
                f"{r['nome']}: {r['falhas']} de {r['chamadas']} chamadas falharam",
                f"Erro mais comum: {erro} ({vezes} vezes).",
                "Ver a tabela coletas do banco para os endereços exatos."))
        if r["http_429"]:
            saida.append(Achado(
                "melhoria", r["motor"], f"{r['nome']} pediu para ir mais devagar",
                f"{r['http_429']} respostas 429 (muitas requisições).",
                "Aumentar a pausa entre chamadas e coletar em janelas menores, todo dia, "
                "em vez de tudo de uma vez."))
    return saida


def _siconfi(banco: Banco, dominios: dict, raiz: Path = RAIZ) -> list[Achado]:
    saida = []
    periodos = banco.consultar("SELECT rotulo, situacao, prazo, erro FROM siconfi_periodos "
                               "ORDER BY demonstrativo, exercicio, periodo")
    if not periodos:
        return saida
    por = defaultdict(list)
    for rotulo, situacao, prazo, erro in periodos:
        por[situacao].append((rotulo, prazo, erro))
    if por["falha"]:
        saida.append(Achado(
            "falha", "siconfi", f"{len(por['falha'])} declarações ao Tesouro não foram lidas",
            "; ".join(f"{r} ({e})" for r, _, e in por["falha"][:8]),
            "Rodar de novo; se persistir, conferir se a API mudou de endereço ou de parâmetro."))
    if por["ausente"]:
        saida.append(Achado(
            "lacuna", "siconfi",
            f"{len(por['ausente'])} declarações vencidas não estão no SICONFI",
            "; ".join(f"{r} (prazo {p})" for r, p, _ in por["ausente"]),
            "Ausência de declaração obrigatória (LRF, arts. 52 e 55) vira alerta roxo e ofício "
            "à Controladoria."))
    rotulos = {a for (a,) in banco.consultar("SELECT DISTINCT anexo FROM siconfi_anexos")}
    for dom, anexo in dominios.items():
        if rotulos and anexo not in rotulos:
            parecidos = [r for r in rotulos if _numero_do_anexo(r) == _numero_do_anexo(anexo)
                         and r.split("-")[0] == anexo.split("-")[0]]
            if parecidos:
                saida.append(Achado(
                    "melhoria", "siconfi",
                    f"O domínio {dom} procura o anexo “{anexo}”, que o SICONFI escreve de outro jeito",
                    f"O Tesouro chama o anexo de “{parecidos[0]}”; a consulta com o nome errado "
                    "volta vazia e a segunda via do piso fica sem dado.",
                    f"Trocar em dominios/{dom}.toml para “{parecidos[0]}”."))
                continue
            origem = FONTE_PROPRIA_DO_ANEXO.get(_numero_do_anexo(anexo))
            saida.append(Achado(
                "melhoria", "siconfi",
                f"O domínio {dom} procura o anexo “{anexo}”, que não veio do SICONFI",
                "Nenhum período coletado traz um anexo com esse número; a consulta volta vazia "
                "e a segunda via do piso fica sem dado." + (
                    f" Provavelmente porque esse anexo nasce no {origem} e não chega à base de "
                    "dados abertos do SICONFI (a conferir)." if origem else ""),
                (f"Ler o piso direto do {origem} e manter o SICONFI como conferência." if origem else
                 "Conferir o nome na lista de anexos do banco (tabela siconfi_anexos).")))
    antigas = banco.consultar("SELECT alvo, ok, erro FROM coletas WHERE motor = 'siconfi-antiga'")
    novas_ok = banco.consultar("SELECT COUNT(*) FROM coletas WHERE motor = 'siconfi' AND ok = 1")
    coletor_antigo = raiz / "cadeoqueijo" / "coleta_siconfi.py"
    ja_corrigido = coletor_antigo.exists() and "apidatalake" in coletor_antigo.read_text(encoding="utf-8")
    if antigas and not any(ok for _, ok, _ in antigas) and novas_ok[0][0] and not ja_corrigido:
        saida.append(Achado(
            "falha", "siconfi",
            "O coletor antigo do SICONFI usa endereços que não respondem mais",
            "cadeoqueijo/coleta_siconfi.py chama " + " e ".join(a for a, _, _ in antigas) +
            f" ({antigas[0][2]}); o endereço novo (apidatalake) respondeu.",
            "Trocar a base do coletor antigo pela apidatalake.tesouro.gov.br."))
    return saida


# Anexos do RREO que os entes preenchem em sistemas próprios antes de chegarem ao Tesouro.
FONTE_PROPRIA_DO_ANEXO = {"8": "SIOPE (educação, FNDE)", "12": "SIOPS (saúde, Ministério da Saúde)"}


def _numero_do_anexo(nome: str) -> str:
    m = re.search(r"anexo\s+0*([0-9]+|[ivx]+-?[a-z]*)", nome.lower())
    return m.group(1) if m else nome.lower()


def _diario(banco: Banco, lista: list[str]) -> list[Achado]:
    saida = []
    linhas = banco.consultar("SELECT fonte, mes, edicoes, com_termos, erro FROM diario_oficial_mes")
    if not linhas:
        return saida
    tab = defaultdict(dict)
    for fonte, mes, edicoes, com_termos, erro in linhas:
        tab[fonte][mes] = (edicoes, com_termos, erro)
    for fonte, nome in (("querido_diario", "Querido Diário"), ("sileg", "índice do SILEG")):
        if fonte not in tab:
            continue
        com_erro = [m for m in lista if tab[fonte].get(m, (None, None, "não coletado"))[2]]
        vazios = [m for m in lista if m not in com_erro and not tab[fonte][m][0]]
        if com_erro:
            erro = tab[fonte][com_erro[0]][2] if com_erro[0] in tab[fonte] else "não coletado"
            saida.append(Achado("falha", fonte, f"O {nome} não respondeu em {len(com_erro)} "
                                f"de {len(lista)} meses", f"Meses: {_faixas(com_erro)}. Erro: {erro}.",
                                _proposta_de_rede(erro)))
        if vazios:
            saida.append(Achado("melhoria", fonte, f"O {nome} não tem edição em {len(vazios)} meses",
                                f"Meses sem nenhuma edição: {_faixas(vazios)}.",
                                "Completar esses meses pela outra via do Diário Oficial."))
    if "querido_diario" in tab and "sileg" in tab:
        diferentes = []
        for m in lista:
            a = tab["querido_diario"].get(m, (None,))[0]
            b = tab["sileg"].get(m, (None,))[0]
            if a is not None and b is not None and a != b:
                diferentes.append(f"{m} ({a} × {b})")
        if diferentes:
            saida.append(Achado(
                "melhoria", "qd",
                f"As duas vias do Diário Oficial contam edições diferentes em {len(diferentes)} meses",
                "Querido Diário × SILEG: " + "; ".join(diferentes[:12]) +
                ("…" if len(diferentes) > 12 else ""),
                "Conferir edição a edição: a que falta numa via é lida pela outra, e a diferença "
                "persistente vira alerta de publicação incompleta."))
    return saida


def _proposta_de_rede(erro: str) -> str:
    """O que fazer depende de como a fonte falhou."""
    e = (erro or "").upper()
    if "SSL" in e or "HANDSHAKE" in e or "TLS" in e:
        return ("O servidor recusou o aperto de mão TLS (alerta 40), também para o curl e o "
                "openssl com TLS 1.2 e 1.3 na mesma máquina: o bloqueio está do lado da fonte, "
                "não nas cifras do robô. A outra via fica como principal, e a coleta mensal tenta "
                "de novo e avisa quando a fonte voltar.")
    if "TIMEOUT" in e or "TIMED OUT" in e:
        return "A fonte demora demais: dar mais tempo à chamada e coletar um mês por dia."
    if "NÃO TENTADO" in e:
        return "A rodada parou de chamar a fonte depois de falhas seguidas; rodar de novo só este motor."
    if re.search(r"HTTP 4\d\d", e):
        return "A API recusou o pedido: conferir se o endereço ou os parâmetros mudaram."
    return "Conferir o endereço da API e manter a outra via como reserva."


def _externos(banco: Banco) -> list[Achado]:
    """SIOPS, SIOPE e Tesouro: bimestre não homologado é lacuna do Município; leitura falha é do sistema."""
    saida = []
    for exercicio, periodo, situacao, erro in banco.consultar(
            "SELECT exercicio, periodo, situacao, erro FROM externos_periodos WHERE fonte = 'SIOPS' "
            "AND situacao <> 'homologado' ORDER BY exercicio, periodo"):
        if situacao == "no_prazo":
            saida.append(Achado("melhoria", "siops", f"Saúde: {periodo}º bimestre de {exercicio} ainda não "
                                "publicado no SIOPS", "O prazo de 30 dias depois do bimestre ainda corre.",
                                "A próxima coleta confere de novo; passado o prazo, vira lacuna."))
        elif situacao == "nao_entregue":
            saida.append(Achado("lacuna", "siops", f"Saúde: {periodo}º bimestre de {exercicio} sem demonstrativo "
                                "homologado no SIOPS", "O SIOPS respondeu que o Município não transmitiu.",
                                "Prazo da LC 141/2012, art. 39: o piso do bimestre fica sem dado (roxo)."))
        else:
            saida.append(Achado("falha", "siops", f"Saúde: {periodo}º bimestre de {exercicio} não foi lido",
                                f"{situacao}: {erro}", "Rodar de novo só o motor siops; se repetir, conferir "
                                "a página de consulta do SIOPS."))
    for exercicio, periodo, situacao, erro in banco.consultar(
            "SELECT exercicio, periodo, situacao, erro FROM externos_periodos WHERE fonte = 'SIOPE' "
            "AND situacao <> 'homologado' ORDER BY exercicio, periodo"):
        if situacao == "no_prazo":
            saida.append(Achado("melhoria", "siope", f"Educação: {periodo}º bimestre de {exercicio} ainda não "
                                "publicado no SIOPE", "O prazo de 30 dias depois do bimestre ainda corre.",
                                "A próxima coleta confere de novo; passado o prazo, vira lacuna."))
        elif situacao == "nao_entregue":
            saida.append(Achado("lacuna", "siope", f"Educação: {periodo}º bimestre de {exercicio} sem demonstrativo "
                                "no SIOPE", "O FNDE não tem o PDF do bimestre: o Município não transmitiu "
                                "ou o FNDE ainda não publicou.",
                                "Os pisos da educação e do FUNDEB do bimestre ficam com uma via só."))
        else:
            saida.append(Achado("falha", "siope", f"Educação: {periodo}º bimestre de {exercicio} não foi lido",
                                f"{situacao}: {erro}", "Rodar de novo só o motor siope; se repetir, conferir "
                                "o leitor do PDF do SIOPE."))
    por_situacao: dict[str, list[str]] = {}
    erros_msc: dict[str, str] = {}
    for mes, situacao, erro in banco.consultar(
            "SELECT mes, situacao, erro FROM msc_meses WHERE situacao <> 'entregue' ORDER BY mes"):
        por_situacao.setdefault(situacao, []).append(mes)
        erros_msc.setdefault(situacao, erro or "")
    for situacao, meses in por_situacao.items():
        if situacao == "no_prazo":
            saida.append(Achado("melhoria", "msc", "Matriz de saldos contábeis ainda não enviada: " + _faixas(meses),
                                "O prazo (último dia do mês seguinte) ainda corre.",
                                "A coleta mensal confere de novo; passado o prazo, vira lacuna."))
        elif situacao == "nao_entregue":
            saida.append(Achado("lacuna", "msc", "Matriz de saldos contábeis não enviada ao SICONFI: " + _faixas(meses),
                                "O SICONFI devolveu a matriz vazia depois do prazo.",
                                "A receita por fonte e o desvio de finalidade desses meses ficam sem a via por fonte e função."))
        else:
            saida.append(Achado("falha", "msc", "Matriz de saldos contábeis não lida: " + _faixas(meses),
                                f"{situacao}: {erros_msc[situacao]}",
                                "Rodar de novo só o motor msc; se repetir, conferir a API do SICONFI."))
    federais = json.loads(_meta(banco).get("transferencias_meses") or "null")
    if federais and federais.get("nao_publicados"):
        saida.append(Achado("melhoria", "transferencias", "O Portal da Transparência ainda não publicou "
                            + _faixas(federais["nao_publicados"]),
                            "O arquivo de transferências do mês sai depois do mês.",
                            "A coleta mensal confere de novo."))
    tesouro = json.loads(_meta(banco).get("tesouro_meses") or "null")
    if tesouro and tesouro.get("nao_publicados"):
        saida.append(Achado("melhoria", "tesouro", "O Tesouro ainda não publicou "
                            + _faixas(tesouro["nao_publicados"]),
                            "A planilha mensal das transferências constitucionais sai depois do mês.",
                            "A coleta mensal confere de novo."))
    return saida


def _fnas(banco: Banco, lista: list[str]) -> list[Achado]:
    saida = []
    coletas = banco.consultar("SELECT alvo, ok, erro FROM coletas WHERE motor = 'fnas'")
    if not coletas:
        return saida
    for alvo, ok, erro in coletas:
        if not ok and erro and "não publicada" in erro:
            saida.append(Achado("lacuna", "fnas", f"O FNAS ainda não publicou a {alvo}",
                                "A página de extração de repasses não tem a planilha do ano.",
                                "Os repasses do ano ficam sem a via federal até a publicação; "
                                "a coleta mensal confere de novo."))
    bloqueios = [(a, e) for a, ok, e in coletas if not ok and e and "devolveu uma página" in e]
    if bloqueios:
        saida.append(Achado(
            "falha", "fnas", "O site do FNAS devolveu uma página curta no lugar do conteúdo",
            "; ".join(f"{a}: {e}" for a, e in bloqueios[:4]) + ".",
            "O servidor provavelmente barra robôs de nuvem. Pedir ao MDS a planilha por dados "
            "abertos, ou baixá-la pelo coletor diário que já guarda dados/repasses_federais.json."))
    do_arquivo = json.loads(_meta(banco).get("fnas_do_arquivo") or "[]")
    if do_arquivo:
        saida.append(Achado(
            "melhoria", "fnas",
            "Repasses de " + ", ".join(map(str, do_arquivo)) + " vieram do arquivo já guardado",
            "A fonte não entregou a planilha nesta rodada; o banco usou dados/repasses_federais.json, "
            "coletado antes pelo sistema, e marca cada linha com essa origem.",
            "Quando o site voltar a entregar a planilha, rodar de novo só o motor fnas."))
    com = {m for (m,) in banco.consultar("SELECT DISTINCT competencia FROM repasses_fnas")}
    sem = [m for m in lista if m not in com]
    if com and sem:
        saida.append(Achado(
            "melhoria", "fnas", f"Sem repasse federal registrado em {len(sem)} meses",
            f"Meses sem nenhuma linha de repasse para o município: {_faixas(sem)}.",
            "Para os meses do ano corrente, usar o Portal da Transparência da União "
            "(transferências) como segunda via enquanto a planilha anual não sai."))
    return saida


def _pncp(banco: Banco, lista: list[str]) -> list[Achado]:
    saida = []
    if not banco.consultar("SELECT 1 FROM coletas WHERE motor = 'pncp' LIMIT 1"):
        return saida
    meta = _meta(banco)
    orgaos = json.loads(meta.get("pncp_orgaos", "{}"))
    if not orgaos:
        saida.append(Achado(
            "falha", "pncp", "Nenhum órgão do Município foi achado no PNCP",
            "A busca de contratações pelo código IBGE não devolveu órgão municipal.",
            "Pôr os CNPJs dos órgãos em pncp_cnpjs, no arquivo do alvo."))
        return saida
    por_mes = dict(banco.consultar("SELECT mes, COUNT(*) FROM contratos_pncp GROUP BY mes"))
    lidos, por_orgao = meses_pncp_lidos(banco, lista)
    nao_lidos = [m for m in lista if m not in lidos]
    faltam = [c for c in orgaos if not por_orgao.get(c)]
    if nao_lidos or faltam:
        saida.append(Achado(
            "falha", "pncp",
            f"Contratos do PNCP não lidos por inteiro em {len(nao_lidos)} meses",
            (f"Meses sem todos os órgãos lidos: {_faixas(nao_lidos)}. " if nao_lidos else "") +
            f"Órgãos sem nenhum mês lido: {len(faltam)} de {len(orgaos)}.",
            "A API do PNCP leva cerca de 20 segundos por chamada: rodar de novo só o motor pncp, "
            "que continua dos órgãos já conhecidos."))
    sem = [m for m in lista if m in lidos and not por_mes.get(m)]
    if sem:
        saida.append(Achado(
            "lacuna", "pncp", f"Nenhum contrato do Município no PNCP em {len(sem)} meses",
            f"Meses: {_faixas(sem)}. Órgãos procurados: {len(orgaos)}.",
            "A Lei 14.133/2021 (art. 94) manda divulgar o contrato no PNCP; confirmar no portal "
            "municipal antes de tratar como ausência."))
    return saida


def meses_pncp_lidos(banco: Banco, lista: list[str]) -> tuple[set[str], dict[str, set[str]]]:
    """Meses em que os contratos de todos os órgãos conhecidos foram lidos, e os lidos por órgão.

    Só nesses meses a falta de contrato é lacuna do Município; nos outros é falha da coleta.
    """
    meta = _meta(banco)
    orgaos = json.loads(meta.get("pncp_orgaos") or "{}")
    por_orgao: dict[str, set[str]] = defaultdict(set)
    for janela in json.loads(meta.get("pncp_janelas") or "[]"):
        if janela.get("lida"):
            por_orgao[janela["cnpj"]].update(janela["meses"])
    if not orgaos:
        return set(), por_orgao
    lidos = {m for m in lista if all(m in por_orgao.get(c, ()) for c in orgaos)}
    return lidos, por_orgao


def _fontes(banco: Banco) -> list[Achado]:
    saida = []
    linhas = banco.consultar("SELECT nome, url, ok, erro, esperado FROM fontes")
    quebradas = [(n, u, e) for n, u, ok, e, esp in linhas if not ok and esp != "MORTO"]
    voltaram = [(n, u) for n, u, ok, e, esp in linhas if ok and esp == "MORTO"]
    if quebradas:
        saida.append(Achado(
            "falha", "fontes", f"{len(quebradas)} de {len(linhas)} endereços configurados não abriram",
            "; ".join(f"{n} ({e})" for n, _, e in quebradas[:12]),
            "Marcar cada um como morto em config/portais.yml com o substituto, ou corrigir o endereço."))
    if voltaram:
        saida.append(Achado(
            "melhoria", "fontes", f"{len(voltaram)} endereços dados como mortos voltaram a responder",
            "; ".join(u for _, u in voltaram), "Reavaliar se voltam a ser fonte."))
    return saida


def _normas(banco: Banco) -> list[Achado]:
    linhas = banco.consultar("SELECT caminho, ok, revogada, erro FROM normas")
    saida = []
    falhas = [c for c, ok, _, _ in linhas if not ok]
    revogadas = [c for c, ok, rev, _ in linhas if ok and rev]
    if falhas:
        saida.append(Achado("falha", "ctresb", f"{len(falhas)} normas federais não foram achadas",
                            "; ".join(falhas[:10]), "Corrigir o caminho no regras/mapa_legal.yml."))
    if revogadas:
        saida.append(Achado("melhoria", "ctresb", f"{len(revogadas)} normas do mapa legal estão revogadas",
                            "; ".join(revogadas[:10]), "Trocar pela norma vigente no mapa legal."))
    return saida


# --- Conferências sem rede: pareceres e coletores antigos ----------------------------

def _pareceres(lista: list[str], raiz: Path) -> list[Achado]:
    feitos = {p.stem.removeprefix("verificacao_")
              for p in (raiz / "relatorios" / "mensal").glob("verificacao_*.json")}
    faltam = [m for m in lista if m not in feitos]
    if not faltam:
        return []
    return [Achado(
        "melhoria", "pareceres", f"Não há verificação mensal em {len(faltam)} dos {len(lista)} meses",
        f"Meses sem verificação do Cadê o Queijo: {_faixas(faltam)}.",
        "Com o banco histórico, refazer as verificações retroativas desses meses "
        "(o motor antigo só roda o exercício corrente).")]


def _coletores_antigos(raiz: Path) -> list[Achado]:
    saida = []
    pncp = raiz / "cadeoqueijo" / "coleta_pncp.py"
    destinatarios = raiz / "dados" / "destinatarios_2026.json"
    if pncp.exists() and destinatarios.exists():
        dest = json.loads(destinatarios.read_text(encoding="utf-8")).get("destinatarios", [])
        do_ente = [d for d in dest if "MUNICIPIO DE GOIANIA" in _norm(d.get("razao_social"))
                   or "PREFEITURA" in _norm(d.get("razao_social"))]
        if not do_ente and "cnpjOrgao" in pncp.read_text(encoding="utf-8"):
            saida.append(Achado(
                "falha", "pncp",
                "O coletor antigo do PNCP consulta o Brasil inteiro",
                "cadeoqueijo/coleta_pncp.py tira os CNPJs do Município de dados/destinatarios_2026.json, "
                "que não tem nenhum; sem CNPJ, pede todos os contratos do país e filtra por "
                "“GOIANIA” só nas 20 primeiras páginas. Por isso recebeu 429 e achou zero contratos.",
                "Usar os órgãos descobertos pela coleta histórica (código IBGE) e consultar por CNPJ, "
                "mês a mês."))
    federal = raiz / "cadeoqueijo" / "coleta_federal.py"
    if federal.exists():
        texto = federal.read_text(encoding="utf-8")
        anos = sorted(int(a) for a in re.findall(r"^\s*(20\d\d)\s*:", texto, re.M))
        if anos:
            saida.append(Achado(
                "melhoria", "fnas",
                f"O coletor antigo do FNAS só conhece as planilhas até {anos[-1]}",
                "cadeoqueijo/coleta_federal.py tem os endereços escritos à mão e roda com "
                "anos=(2024, 2025) fixos.",
                "Achar as planilhas na própria página do FNAS, como faz a coleta histórica."))
    return saida


def _dominios_siconfi(raiz: Path) -> dict[str, str]:
    saida = {}
    for arq in sorted((raiz / "dominios").glob("*.toml")):
        bruto = tomllib.loads(arq.read_text(encoding="utf-8"))
        anexo = (bruto.get("siconfi") or {}).get("anexo")
        if anexo:
            saida[arq.stem] = anexo
    return saida


def diagnosticar(banco: Banco, *, raiz: Path = RAIZ) -> dict:
    meta = _meta(banco)
    desde, ate = meta["intervalo"].split(" a ")
    lista = meses(desde, ate)
    resumo = resumo_por_motor(banco)
    achados = (_motores_quebrados(meta) + _chamadas(resumo)
               + _siconfi(banco, _dominios_siconfi(raiz), raiz) + _diario(banco, lista)
               + _fnas(banco, lista) + _externos(banco) + _pncp(banco, lista) + _fontes(banco) + _normas(banco)
               + _pareceres(lista, raiz) + _coletores_antigos(raiz))
    contagens = {
        "siconfi_itens": banco.consultar("SELECT COUNT(*) FROM siconfi_itens")[0][0],
        "siconfi_periodos": dict(banco.consultar(
            "SELECT situacao, COUNT(*) FROM siconfi_periodos GROUP BY situacao")),
        "edicoes_diario": dict(banco.consultar(
            "SELECT fonte, SUM(edicoes) FROM diario_oficial_mes GROUP BY fonte")),
        "repasses_fnas": banco.consultar("SELECT COUNT(*), ROUND(COALESCE(SUM(valor), 0), 2) "
                                         "FROM repasses_fnas")[0],
        "repasses_fnas_arquivo": banco.consultar(
            "SELECT COUNT(*) FROM repasses_fnas WHERE origem LIKE 'arquivo%'")[0][0],
        "contratacoes_pncp": banco.consultar("SELECT COUNT(*) FROM contratacoes_pncp")[0][0],
        "contratos_pncp": banco.consultar("SELECT COUNT(*), SUM(da_pasta) FROM contratos_pncp")[0],
        "fontes": banco.consultar("SELECT COUNT(*), SUM(ok) FROM fontes")[0],
        "siops_bimestres": dict(banco.consultar(
            "SELECT situacao, COUNT(*) FROM externos_periodos WHERE fonte = 'SIOPS' GROUP BY situacao")),
        "siope_bimestres": dict(banco.consultar(
            "SELECT situacao, COUNT(*) FROM externos_periodos WHERE fonte = 'SIOPE' GROUP BY situacao")),
        "transferencias_federais": banco.consultar(
            "SELECT COUNT(DISTINCT mes), ROUND(COALESCE(SUM(valor), 0), 2) FROM transferencias_federais")[0],
        "msc_meses": banco.consultar(
            "SELECT COUNT(DISTINCT mes), COUNT(*) FROM msc_itens")[0],
        "transferencias_tesouro": banco.consultar(
            "SELECT COUNT(*), ROUND(COALESCE(SUM(total), 0), 2) FROM transferencias_tesouro")[0],
    }
    return {"intervalo": meta["intervalo"], "rodada": meta.get("rodada"), "meses": lista,
            "motores": resumo, "contagens": contagens,
            "cobertura": cobertura_mensal(banco, lista),
            "achados": [asdict(a) for a in achados]}


def cobertura_mensal(banco: Banco, lista: list[str]) -> dict[str, dict[str, str]]:
    """Para cada mês e via: ✓ coletado com dado, · coletado sem dado, ✗ falhou, '' não se aplica."""
    tab: dict[str, dict[str, str]] = {m: {} for m in lista}
    for fonte, mes, edicoes, _, erro in banco.consultar(
            "SELECT fonte, mes, edicoes, com_termos, erro FROM diario_oficial_mes"):
        if mes in tab:
            tab[mes][fonte] = "✗" if erro else ("✓" if edicoes else "·")
    sic = defaultdict(list)
    for dem, ex, per, situacao in banco.consultar(
            "SELECT demonstrativo, exercicio, periodo, situacao FROM siconfi_periodos"):
        tamanho = {"RREO": 2, "RGF": 4, "DCA": 12}[dem]
        for k in range((per - 1) * tamanho + 1, per * tamanho + 1):
            sic[(dem, f"{ex:04d}-{k:02d}")].append(situacao)
    marca = {"entregue": "✓", "ausente": "·", "no prazo": "…", "falha": "✗"}
    for (dem, mes), situacoes in sic.items():
        if mes in tab:
            tab[mes][dem.lower()] = marca.get(situacoes[-1], "?")
    fnas = {m for (m,) in banco.consultar("SELECT DISTINCT competencia FROM repasses_fnas")}
    tem_fnas = banco.consultar("SELECT COUNT(*) FROM coletas WHERE motor = 'fnas' AND ok = 1")[0][0]
    pncp = dict(banco.consultar("SELECT mes, COUNT(*) FROM contratos_pncp GROUP BY mes"))
    pncp_lidos, _ = meses_pncp_lidos(banco, lista)
    tem_pncp = banco.consultar("SELECT COUNT(*) FROM coletas WHERE motor = 'pncp'")[0][0]
    for m in lista:
        if tem_fnas:
            tab[m]["fnas"] = "✓" if m in fnas else "·"
        if tem_pncp:
            # ✓ achou contrato; · todos os órgãos lidos e nenhum contrato; ✗ algum órgão não lido
            tab[m]["pncp"] = "✓" if pncp.get(m) else ("·" if m in pncp_lidos else "✗")
    return tab


# --- Relatório legível --------------------------------------------------------------

COLUNAS = [("querido_diario", "Diário (QD)"), ("sileg", "Diário (SILEG)"), ("rreo", "RREO"),
           ("rgf", "RGF"), ("dca", "DCA"), ("fnas", "FNAS"), ("pncp", "PNCP")]


def markdown(d: dict) -> str:
    linhas = [f"# Diagnóstico da coleta histórica ({d['intervalo']})", "",
              f"Rodada de {d['rodada']}. Banco: `dados/onisciente/historico.db`.", "",
              "Vermelho é falha do sistema (a fonte não respondeu). Roxo é lacuna na fonte "
              "(ela respondeu e o dado não estava lá). As duas nunca se misturam.", "",
              "## Motores", "",
              "| Motor | Chamadas | Certas | Falhas | 429 | Tempo (s) |",
              "|---|---:|---:|---:|---:|---:|"]
    for r in d["motores"]:
        linhas.append(f"| {r['nome']} | {r['chamadas']} | {r['ok']} | {r['falhas']} | "
                      f"{r['http_429']} | {r['segundos']} |")
    c = d["contagens"]
    linhas += ["", "## O que entrou no banco", "",
               f"- **SICONFI:** {c['siconfi_itens']} itens; períodos por situação: "
               f"{json.dumps(c['siconfi_periodos'], ensure_ascii=False)}.",
               f"- **Diário Oficial:** edições somadas por via: "
               f"{json.dumps(c['edicoes_diario'], ensure_ascii=False)}.",
               f"- **Repasses do FNAS:** {c['repasses_fnas'][0]} linhas, "
               f"{_reais(c['repasses_fnas'][1] or 0)}"
               + (f" ({c['repasses_fnas_arquivo']} delas do arquivo já guardado)."
                  if c.get("repasses_fnas_arquivo") else "."),
               f"- **PNCP:** {c['contratacoes_pncp']} contratações e {c['contratos_pncp'][0]} contratos "
               f"de órgãos do Município ({c['contratos_pncp'][1] or 0} da pasta da assistência).",
               f"- **Endereços configurados:** {c['fontes'][1] or 0} de {c['fontes'][0]} abriram."]
    for tipo, titulo in (("falha", "Onde o sistema falha"), ("lacuna", "Onde a fonte respondeu sem o dado"),
                         ("melhoria", "Onde o sistema pode melhorar")):
        itens = [a for a in d["achados"] if a["tipo"] == tipo]
        linhas += ["", f"## {titulo}", ""]
        if not itens:
            linhas.append("Nada nesta rodada.")
        for n, a in enumerate(itens, 1):
            linhas.append(f"{n}. **{a['titulo']}.** {a['detalhe']}"
                          + (f" *Proposta:* {a['proposta']}" if a["proposta"] else ""))
    linhas += ["", "## Cobertura mês a mês", "",
               "✓ coletado com dado · · coletado sem dado · ✗ falhou · … ainda no prazo", "",
               "| Mês | " + " | ".join(n for _, n in COLUNAS) + " |",
               "|---|" + "---|" * len(COLUNAS)]
    for m in d["meses"]:
        linhas.append(f"| {m} | " + " | ".join(d["cobertura"][m].get(k, "") for k, _ in COLUNAS) + " |")
    return "\n".join(linhas) + "\n"


def gravar(d: dict, pasta: Path) -> tuple[Path, Path]:
    pasta.mkdir(parents=True, exist_ok=True)
    arq_json = pasta / "diagnostico_historico.json"
    arq_md = pasta / "diagnostico_historico.md"
    arq_json.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    arq_md.write_text(markdown(d), encoding="utf-8")
    return arq_json, arq_md
