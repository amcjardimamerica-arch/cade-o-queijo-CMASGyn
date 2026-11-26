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


def _siconfi(banco: Banco, dominios: dict) -> list[Achado]:
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
            saida.append(Achado(
                "melhoria", "siconfi",
                f"O domínio {dom} procura o anexo “{anexo}”, que o SICONFI não usa",
                "O Tesouro chama o anexo de " + (f"“{parecidos[0]}”" if parecidos else
                                                 "outro nome") + "; a consulta com o nome "
                "errado volta vazia e a segunda via do piso fica sem dado.",
                f"Trocar em dominios/{dom}.toml para “{parecidos[0]}”." if parecidos else
                "Conferir o nome na lista de anexos do banco (tabela siconfi_anexos)."))
    antigas = banco.consultar("SELECT alvo, ok, erro FROM coletas WHERE motor = 'siconfi-antiga'")
    novas_ok = banco.consultar("SELECT COUNT(*) FROM coletas WHERE motor = 'siconfi' AND ok = 1")
    if antigas and not any(ok for _, ok, _ in antigas) and novas_ok[0][0]:
        saida.append(Achado(
            "falha", "siconfi",
            "O coletor antigo do SICONFI usa endereços que não respondem mais",
            "cadeoqueijo/coleta_siconfi.py chama " + " e ".join(a for a, _, _ in antigas) +
            f" ({antigas[0][2]}); o endereço novo (apidatalake) respondeu.",
            "Trocar a base do coletor antigo pela apidatalake.tesouro.gov.br."))
    return saida


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
                                "Coletar de dentro do GitHub (rede aberta) e manter a outra via "
                                "como reserva."))
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
    sem = [m for m in lista if not por_mes.get(m)]
    if sem:
        saida.append(Achado(
            "lacuna", "pncp", f"Nenhum contrato do Município no PNCP em {len(sem)} meses",
            f"Meses: {_faixas(sem)}. Órgãos procurados: {len(orgaos)}.",
            "A Lei 14.133/2021 (art. 94) manda divulgar o contrato no PNCP; confirmar no portal "
            "municipal antes de tratar como ausência."))
    return saida


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
               + _siconfi(banco, _dominios_siconfi(raiz)) + _diario(banco, lista)
               + _fnas(banco, lista) + _pncp(banco, lista) + _fontes(banco) + _normas(banco)
               + _pareceres(lista, raiz) + _coletores_antigos(raiz))
    contagens = {
        "siconfi_itens": banco.consultar("SELECT COUNT(*) FROM siconfi_itens")[0][0],
        "siconfi_periodos": dict(banco.consultar(
            "SELECT situacao, COUNT(*) FROM siconfi_periodos GROUP BY situacao")),
        "edicoes_diario": dict(banco.consultar(
            "SELECT fonte, SUM(edicoes) FROM diario_oficial_mes GROUP BY fonte")),
        "repasses_fnas": banco.consultar("SELECT COUNT(*), ROUND(COALESCE(SUM(valor), 0), 2) "
                                         "FROM repasses_fnas")[0],
        "contratacoes_pncp": banco.consultar("SELECT COUNT(*) FROM contratacoes_pncp")[0][0],
        "contratos_pncp": banco.consultar("SELECT COUNT(*), SUM(da_pasta) FROM contratos_pncp")[0],
        "fontes": banco.consultar("SELECT COUNT(*), SUM(ok) FROM fontes")[0],
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
    pncp_erro = dict(banco.consultar(
        "SELECT mes, COUNT(*) FROM coletas WHERE motor = 'pncp' AND ok = 0 AND http != 204 GROUP BY mes"))
    tem_pncp = banco.consultar("SELECT COUNT(*) FROM coletas WHERE motor = 'pncp'")[0][0]
    for m in lista:
        if tem_fnas:
            tab[m]["fnas"] = "✓" if m in fnas else "·"
        if tem_pncp:
            tab[m]["pncp"] = "✓" if pncp.get(m) else ("✗" if pncp_erro.get(m) else "·")
    return tab


# --- Relatório legível --------------------------------------------------------------

COLUNAS = [("querido_diario", "Diário (QD)"), ("sileg", "Diário (SILEG)"), ("rreo", "RREO"),
           ("rgf", "RGF"), ("dca", "DCA"), ("fnas", "FNAS"), ("pncp", "PNCP")]


def markdown(d: dict) -> str:
    linhas = [f"# Diagnóstico da coleta histórica ({d['intervalo']})", "",
              f"Rodada de {d['rodada']}. Banco: `dados/onisciente/historico.db`.", "",
              "Vermelho é falha do sistema (a fonte não respondeu). Roxo é lacuna do município "
              "(a fonte respondeu e o dado não estava lá). As duas nunca se misturam.", "",
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
               f"{_reais(c['repasses_fnas'][1] or 0)}.",
               f"- **PNCP:** {c['contratacoes_pncp']} contratações e {c['contratos_pncp'][0]} contratos "
               f"de órgãos do Município ({c['contratos_pncp'][1] or 0} da pasta da assistência).",
               f"- **Endereços configurados:** {c['fontes'][1] or 0} de {c['fontes'][0]} abriram."]
    for tipo, titulo in (("falha", "Onde o sistema falha"), ("lacuna", "Onde o município deixou lacuna"),
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
