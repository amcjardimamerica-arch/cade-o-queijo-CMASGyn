"""Monitor do IGD — percentual do Bolsa Família e do CadÚnico devido ao conselho.

Regra jurídica aplicada:

  Até o exercício de 2025 — piso de 3% dos recursos do IGD, conforme a
  Portaria MDS 1.041/2024, artigo 11, § 1º, e a Resolução CNAS 33/2012,
  artigo 121, inciso VII.

  A partir de janeiro de 2026 — piso de 10% do valor repassado mensalmente
  pelo IGD/SUAS e pelo IGD/PBF, conforme o artigo 6º da Resolução CNAS/MDS
  202/2025, que revogou a Resolução CNAS 15/2014. O descumprimento sujeita o
  ente ao bloqueio dos repasses.

  Registre-se a antinomia: a Portaria MDS 1.041/2024 ainda enuncia 3%. Ao
  conselho e ao controle social interessa a norma superveniente do CNAS.

O agente não presume o valor repassado. Se não houver publicação do plano de
aplicação e da execução, o achado é a própria opacidade — e a saída é o pedido
com base na Lei 12.527/2011.
"""
from __future__ import annotations

import re
from datetime import date

from util import ACERVO, ESTADO, agora, ler_json, log

PISO_ATE_2025 = 0.03
PISO_DESDE_2026 = 0.10

RE_VALOR = re.compile(r"R\$ ?([\d.]{1,15},\d{2})")
RE_IGD = re.compile(
    r"(IGD[\s\-]?(?:M|PBF|SUAS)|[ÍI]ndice de Gest[ãa]o Descentralizada)",
    re.IGNORECASE,
)
RE_CONTROLE_SOCIAL = re.compile(
    r"(fortalecimento do controle social|apoio t[ée]cnico e operacional|"
    r"controle social|CMAS)", re.IGNORECASE,
)


def piso_vigente(quando: date | None = None) -> float:
    q = quando or agora().date()
    return PISO_DESDE_2026 if q.year >= 2026 else PISO_ATE_2025


def _valor(texto: str) -> float | None:
    m = RE_VALOR.search(texto)
    if not m:
        return None
    try:
        return float(m.group(1).replace(".", "").replace(",", "."))
    except ValueError:
        return None


def rastrear(trechos_do_dia: list) -> list[dict]:
    """Procura menções ao IGD nos trechos já filtrados e avalia o percentual."""
    achados: list[dict] = []
    piso = piso_vigente()

    for t in trechos_do_dia:
        texto = t.texto if hasattr(t, "texto") else t.get("texto", "")
        if not RE_IGD.search(texto):
            continue

        total = _valor(texto)
        tem_controle_social = bool(RE_CONTROLE_SOCIAL.search(texto))

        if not tem_controle_social:
            achados.append({
                "regra": "IGD-04", "severidade": "media",
                "titulo": "Menção ao IGD sem destinação declarada ao controle social",
                "detalhe": (
                    "Ato menciona recursos do Índice de Gestão Descentralizada sem "
                    f"indicar a parcela destinada ao controle social. O piso vigente é "
                    f"de {piso:.0%} do valor repassado, nos termos do artigo 6º da "
                    "Resolução CNAS/MDS 202/2025."
                ),
                "documento": getattr(t, "documento", None) or t.get("documento"),
                "valor_identificado": total,
                "saida_sugerida": "minuta_lai",
                "detectado_em": agora().isoformat(),
            })
            continue

        if total:
            devido = round(total * piso, 2)
            achados.append({
                "regra": "IGD-01", "severidade": "media",
                "titulo": "Verificar aplicação do piso do IGD no controle social",
                "detalhe": (
                    f"Valor identificado de R$ {total:,.2f}. Piso de {piso:.0%} "
                    f"corresponde a R$ {devido:,.2f} devidos ao CMASGyn. Confrontar "
                    "com a execução efetiva no demonstrativo do Fundo."
                ).replace(",", "@").replace(".", ",").replace("@", "."),
                "documento": getattr(t, "documento", None) or t.get("documento"),
                "valor_total": total, "piso": piso, "valor_devido": devido,
                "detectado_em": agora().isoformat(),
            })
    return achados


def auditar_opacidade() -> list[dict]:
    """Se em 90 dias nenhuma fonte publicou dado de IGD, a opacidade é o achado."""
    registro = ler_json(ESTADO / "igd_observado.json", {})
    ultimo = registro.get("ultima_mencao")
    if ultimo:
        try:
            dias = (agora().date() - date.fromisoformat(ultimo[:10])).days
        except ValueError:
            dias = 999
    else:
        dias = 999

    if dias < 90:
        return []

    return [{
        "regra": "IGD-04", "severidade": "alta",
        "titulo": "Ausência de transparência ativa sobre a aplicação do IGD",
        "detalhe": (
            f"Decorridos {dias if dias < 999 else 'mais de 90'} dias sem qualquer "
            "publicação, no Diário Oficial, no portal da transparência ou no sítio "
            "do conselho, acerca do plano de aplicação e da execução dos recursos do "
            "IGD-PBF e do IGD-SUAS. A partir do exercício de 2026 tais recursos devem "
            "constar de dotação orçamentária específica no Quadro de Detalhamento de "
            "Despesas, com prestação de contas quadrimestral ao conselho, nos termos "
            "da Resolução CNAS/MDS 202/2025."
        ),
        "saida_sugerida": "minuta_lai",
        "detectado_em": agora().isoformat(),
    }]


def registrar_mencao() -> None:
    from util import gravar_json
    gravar_json(ESTADO / "igd_observado.json",
                {"ultima_mencao": agora().isoformat()})
