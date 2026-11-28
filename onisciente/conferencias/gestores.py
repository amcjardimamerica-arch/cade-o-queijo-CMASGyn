"""Aluguel por metro quadrado (ALUGUEL-M2) e benefícios dos gestores (BENEFICIOS-GESTORES).

* **Aluguel.** As locações de imóveis publicadas no PNCP pelos órgãos do Município. Quando o objeto
  traz a área, o aluguel mensal por metro quadrado é comparado com a mediana das locações do próprio
  Município; quando não traz, a área e o laudo de avaliação prévia viram pedido de acesso ao órgão
  que alugou.
* **Gestores.** O subsídio dos agentes políticos contra o teto, as diárias por beneficiário, os
  veículos, o suprimento de fundos e a verba de gabinete só se conferem com o que é publicado por
  pessoa. O banco tem o total de diárias e passagens da matriz de saldos contábeis, que entra como
  quadro; o resto vira ausência dirigida ao órgão que guarda cada documento.
"""

from __future__ import annotations

import re
from datetime import date
from statistics import median

from ..nucleo.ausencias import Ausencia
from ..nucleo.indicios import Familia, emitir
from ..nucleo.provas import Nivel
from ..nucleo.selos import Selo
from .banco import CAMARA, CASA_CIVIL, FAZENDA, SEMAD, SOMA, Base, Linha, Parte, Quadro, moeda, pct

LOCACAO = re.compile(r"loca[çc][ãa]o\s+(?:do|de|da)?\s*(?:andar|im[óo]vel|pr[ée]dio|galp[ãa]o|sala)|aluguel",
                     re.I)
AREA = re.compile(r"(\d{1,3}(?:\.\d{3})*(?:,\d+)?|\d+(?:[.,]\d+)?)\s*(?:m²|m2\b|metros\s+quadrados)", re.I)


def area_do_objeto(objeto: str) -> float | None:
    m = AREA.search(objeto or "")
    if not m:
        return None
    t = m.group(1)
    t = t.replace(".", "").replace(",", ".") if "," in t or re.fullmatch(r"\d{1,3}(\.\d{3})+", t) else t
    try:
        v = float(t)
    except ValueError:
        return None
    return v if v > 0 else None


def _meses(inicio: str | None, fim: str | None) -> float:
    try:
        a, b = date.fromisoformat((inicio or "")[:10]), date.fromisoformat((fim or "")[:10])
    except ValueError:
        return 12.0
    dias = (b - a).days + 1
    return max(1.0, round(dias / 30.4375, 2)) if dias > 0 else 12.0


def locacoes(base: Base) -> list[dict]:
    if not base.tem("contratos_pncp"):
        return []
    detalhe = base.tem("pncp_contratos_detalhe")
    sql = ("select c.pncp_id, c.orgao, c.fornecedor, c.objeto, c.valor_global, c.data_assinatura"
           + (", d.vigencia_inicio, d.vigencia_fim from contratos_pncp c left join pncp_contratos_detalhe d "
              "on d.contrato_id = c.pncp_id" if detalhe else ", null, null from contratos_pncp c")
           + " where coalesce(c.data_assinatura, c.mes) <= ?")
    saida = []
    for cid, orgao, forn, objeto, valor, assin, vini, vfim in base.con.execute(sql, (base.ate.isoformat(),)):
        if not LOCACAO.search(objeto or "") or "termo aditivo" in (objeto or "").lower()[:40]:
            continue
        area = area_do_objeto(objeto or "")
        meses = _meses(vini, vfim)
        mensal = (valor or 0.0) / meses if valor else None
        saida.append({"contrato": cid, "orgao": (orgao or "").title(), "fornecedor": forn or "",
                      "objeto": (objeto or "").strip(), "valor": valor, "meses": meses, "area": area,
                      "por_m2": round(mensal / area, 2) if (mensal and area) else None})
    return saida


def conferir(base: Base) -> Parte:
    parte = Parte()
    _aluguel(base, parte)
    _gestores(base, parte)
    return parte


def _aluguel(base: Base, parte: Parte) -> None:
    regra = base.mapa.regra("ALUGUEL-M2")
    limite = float(regra.valor or 15.0)
    minimo = int(regra.get("minimo_de_locacoes", 3))
    lista = locacoes(base)
    if not lista:
        return
    medidas = [x["por_m2"] for x in lista if x["por_m2"]]
    med = median(medidas) if len(medidas) >= minimo else None
    q = Quadro(5, "Locações de imóveis: aluguel mensal por metro quadrado",
               "Locações publicadas no PNCP pelos órgãos do Município (uma via: o PNCP). A área vem do objeto do "
               "contrato; sem ela, o aluguel não se mede.",
               ["Contrato", "Órgão", "Área", "Aluguel mensal", "Por m²", "Contra a mediana"],
               regra=f"ALUGUEL-M2: até {limite:g}% acima da mediana do Município, com pelo menos {minimo} locações "
                     f"medidas. {regra.get('justificativa', '')}")
    sem_area: dict[str, int] = {}
    for x in sorted(lista, key=lambda x: -(x["por_m2"] or 0)):
        mensal = x["valor"] / x["meses"] if x["valor"] else None
        rel = (100.0 * (x["por_m2"] / med - 1)) if (med and x["por_m2"]) else None
        q.linhas.append(Linha(x["contrato"], [x["orgao"][:50], f"{x['area']:g} m²".replace(".", ",") if x["area"] else "não publicada",
                                              moeda(mensal), moeda(x["por_m2"]) if x["por_m2"] else "sem medida",
                                              pct(rel) if rel is not None else "sem comparação"],
                              Selo.AZUL if x["area"] else Selo.ROXO, base.coleta("pncp")))
        if not x["area"]:
            sem_area[x["orgao"]] = sem_area.get(x["orgao"], 0) + 1
        if rel is not None and rel > limite:
            parte.fichas.append(emitir(
                codigo=f"PRC-ALUGUEL-{x['contrato']}",
                familia=Familia.PRC,
                titulo=f"Aluguel por metro quadrado {pct(rel)} acima da mediana do Município",
                gravidade=regra.gravidade,
                como_deveria=(f"Locação precedida de avaliação prévia; o aluguel por m² não deve passar de {limite:g}% "
                              "da mediana das locações do próprio Município sem justificativa (limiar do mapa legal)."),
                norma=regra.norma,
                como_esta=(f"{x['orgao']}; {x['fornecedor']}; {x['area']:g} m²; aluguel mensal {moeda(mensal)}; "
                           f"{moeda(x['por_m2'])} por m² contra mediana de {moeda(med)} ({len(medidas)} locações "
                           "medidas).").replace(".0 m²", " m²"),
                niveis=[Nivel.C],
                providencia="Pedir o laudo de avaliação prévia, as cotações de mercado e a justificativa da escolha do imóvel.",
                observacao="indício, não acusação",
            ))
    parte.quadros.append(q)
    if med is None:
        q.notas.append(f"Só {len(medidas)} locação(ões) com área publicada: abaixo de {minimo}, a mediana não se forma.")
    for orgao, n in sorted(sem_area.items()):
        parte.ausencias.append(Ausencia(
            o_que_falta=f"Área, laudo de avaliação prévia e valor mensal de {n} locação(ões) de imóveis",
            conferencia_impedida="medir o aluguel por metro quadrado contra a mediana do Município (ALUGUEL-M2)",
            onde_deveria_estar="Portal da Transparência de Goiânia (locações de imóveis) e PNCP",
            fundamento="Lei 14.133/2021, art. 51; Lei 9.262/2013, art. 7º, § 3º, alterada pela Lei 11.478/2025",
            periodo=f"até {base.ate:%m/%Y}", orgao=orgao or SEMAD, bloco="Locações de imóveis"))


GESTORES = (
    ("Lei de subsídios dos agentes políticos de 2025 a 2028 e a remuneração mensal de cada um, com todas as parcelas",
     "conferir cada remuneração contra o teto do subsídio do prefeito (BENEFICIOS-GESTORES)", CAMARA),
    ("Relação de diárias pagas por beneficiário, cargo, destino, período e valor, com os relatórios de viagem",
     "conferir diárias de gestores contra a tabela e a devolução em 5 dias (LC 011/1992, art. 71)", SEMAD),
    ("Relação dos veículos oficiais e de representação, com o órgão, o usuário e o custo",
     "conferir o uso de veículos pelos gestores (BENEFICIOS-GESTORES)", SEMAD),
    ("Suprimentos de fundos concedidos, com o suprido, o valor e a prestação de contas",
     "conferir o suprimento de fundos e a sua prestação (BENEFICIOS-GESTORES)", FAZENDA),
    ("Verba de gabinete e de representação por gestor, com a base legal",
     "conferir a verba de gabinete contra o teto (BENEFICIOS-GESTORES)", CASA_CIVIL),
)


def _gestores(base: Base, parte: Parte) -> None:
    regra = base.mapa.regra("BENEFICIOS-GESTORES")
    q = Quadro(4, "Benefícios dos gestores: o que o banco mostra e o que falta",
               "Diárias e passagens pela matriz de saldos contábeis (naturezas 3.3.90.14 e 3.3.90.33), no exercício. "
               "O teto e cada benefício por pessoa dependem da publicação por beneficiário.",
               ["Natureza", "Exercício", "Liquidado"],
               regra=f"BENEFICIOS-GESTORES: até {regra.valor:g}% do subsídio do prefeito. {regra.get('justificativa', '')}")
    meses = [m for m in base.meses_msc() if m.startswith(f"{base.ate.year}-")] or \
            [m for m in base.meses_msc() if m.startswith(f"{base.ate.year - 1}-")]
    if base.tem("msc_itens") and meses:
        marcas = ",".join("?" for _ in meses)
        for nat, nome in (("339014", "Diárias"), ("339033", "Passagens e locomoção")):
            v = base.con.execute(
                f"select {SOMA} from msc_itens where (conta_contabil like '6221303%' or conta_contabil like '6221304%' "
                f"or conta_contabil like '6221307%') and natureza_despesa like ? and mes in ({marcas})",
                [nat + "%", *meses]).fetchone()[0]
            q.linhas.append(Linha(nome, [f"{meses[0]} a {meses[-1]}", moeda(v or 0.0)], Selo.AZUL,
                                  base.original_msc(meses[-1])))
    for falta, _impedida, _orgao in GESTORES:
        q.linhas.append(Linha(falta.split(",")[0], ["não publicado", "sem medida"], Selo.ROXO))
    parte.quadros.append(q)
    for falta, impedida, orgao in GESTORES:
        parte.ausencias.append(Ausencia(
            o_que_falta=falta, conferencia_impedida=impedida,
            onde_deveria_estar="Portal da Transparência de Goiânia (pessoal, diárias e gestores)",
            fundamento=("CF, art. 37, XI; Lei 8.902/2010; Lei 9.262/2013, art. 7º, § 3º; "
                        "Lei 12.527/2011, art. 8º"),
            periodo=f"exercício {base.ate.year}", orgao=orgao, bloco="Gestores"))
