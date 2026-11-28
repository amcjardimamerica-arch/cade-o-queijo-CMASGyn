"""Contas de governo e de gestão de cada unidade, e os prazos (família CTA).

* **Cadastro das unidades.** O Município (contas de governo do prefeito) e cada fundo, autarquia,
  estatal e a Câmara (contas de gestão), pelos órgãos que publicam no PNCP e pelas unidades que a
  matriz de saldos contábeis abre (Executivo, regime próprio e Legislativo).
* **Conferência possível, parcial ou impossível.** Para cada unidade e exercício, quais peças estão
  no banco: balanço anual, RREO do 6º bimestre, RGF do 3º quadrimestre, matriz de encerramento e a
  matriz dos doze meses, ou, para a gestão, a execução própria na matriz e os contratos.
* **Prazos.** Os demonstrativos homologados no SICONFI contra os prazos da LRF (RREO e RGF em 30
  dias, contas anuais até 30 de abril); e os prazos da Lei Orgânica (entrega, parecer prévio,
  julgamento) a partir do registro ``estado/contas_tcm.json``, quando o Tribunal e a Câmara
  informarem as datas. Sem esse registro, a falta vira pedido de acesso ao Tribunal e à Câmara.
"""

from __future__ import annotations

import json
from datetime import date

from .. import contas as contas_mod
from ..nucleo.ausencias import Ausencia
from ..nucleo.selos import Selo
from .banco import CAMARA, TCM, Base, Linha, Parte, Quadro

ENTREGAVEIS = {"Relatório Resumido de Execução Orçamentária": "RREO", "Relatório de Gestão Fiscal": "RGF",
               "Balanço Anual (DCA)": "DCA"}
PODER_ORGAO = {"10132": "INSTITUTO DE PREVIDENCIA", "20231": "CAMARA MUNICIPAL"}


def unidades(base: Base) -> list[contas_mod.Unidade]:
    saida = [contas_mod.Unidade("Município de Goiânia (contas de governo do prefeito)", "governo", "", "10131")]
    orgaos: dict[str, str] = {}
    if base.tem("meta"):
        linha = base.con.execute("select valor from meta where chave = 'pncp_orgaos'").fetchone()
        if linha and linha[0]:
            try:
                orgaos.update(json.loads(linha[0]))
            except ValueError:
                pass
    if base.tem("contratos_pncp"):
        orgaos.update({c: o for c, o in base.con.execute("select distinct orgao_cnpj, orgao from contratos_pncp")
                       if c and o})
    for cnpj, nome in sorted(orgaos.items(), key=lambda kv: kv[1]):
        tipo = contas_mod.classificar_unidade(nome)
        if tipo == "órgão":
            continue                      # administração direta: entra nas contas de governo
        poder = next((p for p, t in PODER_ORGAO.items() if t in nome.upper()), "")
        saida.append(contas_mod.Unidade(" ".join(nome.split()).title(), tipo, cnpj, poder))
    return saida


def homologacoes(base: Base) -> dict[tuple[str, int, int], date]:
    """A última homologação de cada demonstrativo (com dois poderes, vale a mais tardia)."""
    if not base.tem("siconfi_entregas"):
        return {}
    saida: dict[tuple[str, int, int], date] = {}
    for ex, ent, per, status, quando in base.con.execute(
            "select exercicio, entregavel, periodo, status, data_status from siconfi_entregas"):
        dem = ENTREGAVEIS.get(ent)
        if dem is None or status != "HO" or not quando:
            continue
        d = date.fromisoformat(quando[:10])
        if d > base.ate:
            continue
        chave = (dem, int(ex), int(per or 1))
        saida[chave] = max(saida.get(chave, d), d)
    return saida


def _registro_tcm(base: Base) -> dict[tuple[int, str], dict]:
    caminho = base.raiz / "estado" / "contas_tcm.json"
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}
    return {(int(c["exercicio"]), c["unidade"]): c for c in dados.get("contas", [])}


def _data(t: str | None) -> date | None:
    return date.fromisoformat(t[:10]) if t else None


def conferir(base: Base) -> Parte:
    parte = Parte()
    if not base.tem("siconfi_periodos"):
        return parte
    regra = base.mapa.regra("PRAZO-DEMONSTRATIVOS")
    dias = int(regra.valor or 30)
    dca = regra.get("dca_ate") or {"mes": 4, "dia": 30}

    # Prazos dos demonstrativos no SICONFI.
    atrasos = []
    rotulos = {"RREO": "RREO do {p}º bimestre de {e}", "RGF": "RGF do {p}º quadrimestre de {e}",
               "DCA": "Balanço anual (DCA) de {e}"}
    for (dem, ex, per), quando in sorted(homologacoes(base).items()):
        prazo = contas_mod.prazo_demonstrativo(dem, ex, per, dias=dias, dca_ate=(dca["mes"], dca["dia"]))
        if quando > prazo:
            atrasos.append({"demonstrativo": dem, "exercicio": ex, "periodo": per, "prazo": prazo,
                            "homologado": quando, "dias": (quando - prazo).days,
                            "rotulo": rotulos[dem].format(p=per, e=ex)})
    parte.fichas += contas_mod.fichas_de_prazo(atrasos, norma=regra.norma, gravidade=regra.gravidade)
    if atrasos:
        parte.quadros.append(Quadro(
            6, "Demonstrativos homologados depois do prazo da LRF",
            "Extrato de entregas do SICONFI: a última homologação de cada demonstrativo.",
            ["Demonstrativo", "Prazo", "Homologado", "Dias depois"],
            [Linha(a["rotulo"], [f"{a['prazo']:%d/%m/%Y}", f"{a['homologado']:%d/%m/%Y}", str(a["dias"])],
                   Selo.AZUL, base.coleta("siconfi", f"extrato {a['exercicio']}")) for a in atrasos],
            regra=f"PRAZO-DEMONSTRATIVOS: {regra.get('justificativa', '')}"))

    # Cadastro das unidades e conferência possível, parcial ou impossível.
    periodos = {(d, e, p) for d, e, p in base.con.execute(
        "select demonstrativo, exercicio, periodo from siconfi_periodos where situacao = 'entregue' and termina <= ?",
        (base.ate.isoformat(),))}
    exercicios = sorted({e for d, e, _ in periodos if d == "DCA"})
    if not exercicios:
        return parte
    encerramento = {int(e) for (e,) in base.con.execute(
        "select distinct exercicio from siconfi_entregas where entregavel = 'MSC Encerramento' and status = 'HO'")} \
        if base.tem("siconfi_entregas") else set()
    meses = base.meses_msc()
    poderes = {p for (p,) in base.con.execute("select distinct poder_orgao from msc_itens")} \
        if base.tem("msc_itens") else set()
    com_contrato = {(c, a) for c, a in base.con.execute(
        "select distinct orgao_cnpj, substr(coalesce(data_assinatura, mes), 1, 4) from contratos_pncp")} \
        if base.tem("contratos_pncp") else set()
    registro = _registro_tcm(base)
    prazos = base.mapa.regra("CONTAS-PRAZOS").get("prazos") or {}
    abertura = (2, 1)
    try:
        from ..config import carregar_alvo
        abertura = tuple(getattr(carregar_alvo(), "abertura_sessao", None) or abertura)  # type: ignore[assignment]
    except Exception:  # noqa: BLE001 - alvo ausente nos testes: fica a abertura padrão
        pass
    q = Quadro(6, "Contas de governo e de gestão: o que o banco permite conferir",
               "Para cada unidade e exercício encerrado, as peças guardadas no banco. Possível: todas as peças; "
               "parcial: alguma; impossível: nenhuma, e a falta vira pedido de acesso.",
               ["Unidade", "Contas", "Exercício", "Peças no banco", "Conferência"],
               regra=f"CONTAS-PRAZOS: balancete em {prazos.get('balancete', 45)} dias; entrega em "
                     f"{prazos.get('entrega', 60)} dias da abertura da sessão; parecer em {prazos.get('parecer', 60)}; "
                     f"julgamento em {prazos.get('julgamento', 75)}.")
    for ex in exercicios:
        for u in unidades(base):
            if u.tipo == "governo":
                tem = {"balanço anual": ("DCA", ex, 1) in periodos,
                       "RREO do 6º bimestre": ("RREO", ex, 6) in periodos,
                       "RGF do 3º quadrimestre": ("RGF", ex, 3) in periodos,
                       "matriz de encerramento": ex in encerramento,
                       "matriz dos doze meses": sum(1 for m in meses if m.startswith(f"{ex}-")) == 12}
            else:
                tem = {"balanço próprio": False,
                       "execução própria na matriz": bool(u.poder_orgao) and u.poder_orgao in poderes,
                       "contratos no PNCP": (u.cnpj, str(ex)) in com_contrato}
            situacao = contas_mod.conferencia_possivel(tem)
            conta = contas_mod.Conta(ex, u.nome, "governo" if u.tipo == "governo" else "gestão",
                                     conferencia=situacao)
            r = registro.get((ex, u.nome)) or (registro.get((ex, "Município")) if u.tipo == "governo" else None)
            if r:
                conta.entregue_em, conta.parecer_em, conta.julgada_em = (
                    _data(r.get("entregue_em")), _data(r.get("parecer_em")), _data(r.get("julgada_em")))
                contas_mod.avaliar(conta, base.ate, abertura_sessao=abertura)  # type: ignore[arg-type]
            parte.contas.append(conta)
            pecas = ", ".join(k for k, v in tem.items() if v) or "nenhuma"
            q.linhas.append(Linha(u.nome, [conta.tipo, str(ex), pecas, situacao],
                                  Selo.AZUL if situacao != "impossível" else Selo.ROXO,
                                  base.original_do_periodo("DCA", ex, 1) if u.tipo == "governo" else None))
            if situacao != "possível" and u.tipo != "governo":
                faltam = ", ".join(k for k, v in tem.items() if not v)
                parte.ausencias.append(Ausencia(
                    o_que_falta=f"Prestação de contas de gestão de {ex} de {u.nome} ({faltam})",
                    conferencia_impedida="conferir as contas de gestão da unidade (balanço, execução e contratos)",
                    onde_deveria_estar="Portal da Transparência de Goiânia e sítio da unidade",
                    fundamento="Lei Orgânica, arts. 103 e 115, XXV; Lei estadual 15.958/2007; LC 101/2000, art. 48",
                    periodo=f"exercício {ex}", orgao=u.nome, bloco="Contas de gestão"))
        if not any(k[0] == ex for k in registro):
            parte.ausencias.append(Ausencia(
                o_que_falta=(f"Datas de entrega das contas de governo e de gestão de {ex} ao Tribunal, dos balancetes "
                             "mensais e do parecer prévio"),
                conferencia_impedida="conferir os prazos de 45 dias, 60 dias da abertura da sessão e 60 dias do parecer",
                onde_deveria_estar="Sítio do Tribunal de Contas dos Municípios (consulta de processos de contas)",
                fundamento="Lei Orgânica, arts. 103, 103-A e 103-B; Lei estadual 15.958/2007",
                periodo=f"exercício {ex}", orgao=TCM, bloco="Contas"))
            parte.ausencias.append(Ausencia(
                o_que_falta=f"Data do julgamento das contas de {ex} pela Câmara e o decreto legislativo",
                conferencia_impedida="conferir o prazo de 75 dias depois do parecer prévio e o fim do exercício seguinte",
                onde_deveria_estar="Sítio da Câmara Municipal de Goiânia (decretos legislativos)",
                fundamento="Lei Orgânica, arts. 64, XI e 115, XXV",
                periodo=f"exercício {ex}", orgao=CAMARA, bloco="Contas"))
    parte.fichas += contas_mod.fichas(parte.contas)
    parte.quadros.append(q)
    return parte
