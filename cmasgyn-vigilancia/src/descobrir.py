"""Descoberta do endpoint do Diário Oficial do Município.

O portal de consulta é o SILEG. O padrão de URL do PDF da edição não é
documentado publicamente, e este agente não inventa endereço: ele inspeciona
a página, propõe candidatos e grava o que funcionou em estado/dom_endpoint.json.

Executar UMA VEZ, antes da primeira rotina diária:
    python src/descobrir.py
Se nada for encontrado, o roteiro imprime a minuta de pedido com base na
Lei 12.527/2011 para obter o endereço de acesso automatizado.
"""
from __future__ import annotations

import re
import sys
from urllib.parse import urljoin

from cliente_http import ClienteHTTP
from util import ESTADO, carregar_yaml, gravar_json, log

MINUTA_LAI = """\
PEDIDO DE ACESSO À INFORMAÇÃO — Lei 12.527/2011

Ao Serviço de Informação ao Cidadão da Prefeitura de Goiânia

Com fundamento no artigo 5º, inciso XXXIII, da Constituição Federal e no
artigo 8º, § 3º, incisos II e III, da Lei 12.527/2011, que impõem a divulgação
em formatos abertos, estruturados e legíveis por máquina, com possibilidade de
acesso automatizado por sistemas externos, requeiro:

a) o endereço eletrônico estável (URL) para obtenção direta dos arquivos das
   edições do Diário Oficial do Município, em formato PDF, por data de
   publicação e por número de edição;

b) a informação sobre a existência de interface de programação de aplicações
   (API), canal de dados abertos ou repositório que permita a coleta
   automatizada das edições;

c) a política de limite de requisições aplicável a tal acesso.

Registre-se que, nos termos do artigo 10, § 3º, da Lei 12.527/2011, é vedado
exigir do requerente os motivos determinantes da solicitação.
"""


def descobrir() -> dict | None:
    cfg = carregar_yaml("fontes.yml")
    padrao = cfg["defaults"]
    fonte = next(f for f in cfg["fontes"] if f["id"] == "dom_goiania")
    http = ClienteHTTP(
        user_agent=padrao["user_agent"],
        intervalo=padrao["intervalo_segundos"],
        timeout=padrao["timeout"],
        tentativas=padrao["tentativas"],
        respeitar_robots=padrao["respeitar_robots"],
    )

    achados: list[str] = []
    for pagina in (fonte["portal_consulta"], fonte["pagina_institucional"]):
        r = http.obter(pagina, condicional=False)
        if r.status != 200 or not r.conteudo:
            log.warning("Não foi possível ler %s (HTTP %s)", pagina, r.status)
            continue
        html = r.conteudo.decode("utf-8", errors="ignore")

        # Links diretos para PDF
        for m in re.finditer(r'href=["\']([^"\']+\.pdf[^"\']*)["\']', html, re.IGNORECASE):
            achados.append(urljoin(pagina, m.group(1)))

        # Rotas de download típicas de sistemas de legislação
        for m in re.finditer(
            r'href=["\']([^"\']*(?:download|arquivo|edicao|diario|doc)[^"\']*)["\']',
            html, re.IGNORECASE,
        ):
            achados.append(urljoin(pagina, m.group(1)))

    achados = sorted(set(achados))
    if not achados:
        log.error("Nenhum candidato encontrado. Use a minuta abaixo.\n\n%s", MINUTA_LAI)
        (ESTADO / "minuta_lai_dom.txt").write_text(MINUTA_LAI, encoding="utf-8")
        return None

    resultado = {
        "descoberto_em": None,
        "candidatos": achados[:50],
        "padrao_confirmado": None,
        "instrucao": (
            "Abra um dos candidatos, confirme que é a edição do Diário Oficial e "
            "escreva em 'padrao_confirmado' o gabarito com {ano}, {mes}, {dia} ou "
            "{numero}. Exemplo: https://host/caminho/{ano}/{mes}/{dia}.pdf"
        ),
    }
    gravar_json(ESTADO / "dom_endpoint.json", resultado)
    log.info("%d candidato(s) gravados em estado/dom_endpoint.json", len(achados))
    for c in achados[:15]:
        print("  ", c)
    return resultado


if __name__ == "__main__":
    sys.exit(0 if descobrir() else 1)
