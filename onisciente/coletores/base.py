"""Base dos coletores.

Toda fonte é lida com impressão digital. Quando uma fonte muda de endereço ou
de formato, o coletor falha às claras: registra a falha no estado da coleta, e
o parecer marca em vermelho o trecho não alcançado. Se uma fonte ficar sem
coleta por mais dias que o mapa legal permite (3), isso aparece como falha do
próprio sistema, nunca como silêncio do município.
"""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from .. import RAIZ, __version__
from ..nucleo.custodia import Original, impressao
from ..nucleo.indicios import Familia, Ficha, emitir

ESTADO = RAIZ / "estado" / "onisciente_coleta.json"
AGENTE = f"Onisciente/{__version__} (fiscalizacao civica; dados publicos)"


@dataclass
class Leitura:
    ok: bool
    url: str
    conteudo: bytes = b""
    erro: str = ""
    original: Original | None = None
    http: int | None = None

    @property
    def texto(self) -> str:
        return self.conteudo.decode("utf-8", errors="replace")


def ler(url: str, *, tempo: int = 60, fonte: str = "",
        cabecalhos: dict[str, str] | None = None, formulario: dict | None = None) -> Leitura:
    """Lê uma URL pública. Nunca levanta exceção: devolve a falha descrita.

    ``formulario`` envia os campos por POST, como o botão de consulta de uma página pública.
    """
    dados = urllib.parse.urlencode(formulario, doseq=True).encode() if formulario else None
    pedido = urllib.request.Request(url, data=dados, headers={"User-Agent": AGENTE, **(cabecalhos or {})})
    contexto = None
    for tentativa in (1, 2):
        try:
            with urllib.request.urlopen(pedido, timeout=tempo,  # noqa: S310 (URL do mapa)
                                        context=contexto) as resposta:
                conteudo = resposta.read()
                codigo = resposta.status
            break
        except urllib.error.HTTPError as e:
            return Leitura(False, url, erro=f"HTTP {e.code}", http=e.code)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            motivo = getattr(e, "reason", e)
            if tentativa == 1 and _aperto_de_mao_recusado(motivo):
                contexto = contexto_tls_compativel()   # servidor antigo: cifras mais velhas
                continue
            return Leitura(False, url, erro=f"{type(e).__name__}: {motivo}")
    original = Original(url=url, coletado_em=date.today().isoformat(),
                        sha256=impressao(conteudo), fonte=fonte)
    return Leitura(True, url, conteudo, original=original, http=codigo)


def contexto_tls_compativel() -> ssl.SSLContext:
    """Certificado conferido como sempre, mas aceitando as cifras de servidores mais antigos.

    Alguns servidores públicos (o do Querido Diário, por exemplo) só falam cifras que o
    OpenSSL recente recusa no nível de segurança padrão; baixar o nível não tira a
    conferência do certificado nem do nome do servidor.
    """
    contexto = ssl.create_default_context()
    contexto.set_ciphers("DEFAULT@SECLEVEL=1")
    return contexto


def _aperto_de_mao_recusado(motivo) -> bool:
    texto = str(motivo).upper()
    if "CERTIFICATE" in texto:            # certificado inválido nunca é contornado
        return False
    return "HANDSHAKE_FAILURE" in texto or "UNSUPPORTED_PROTOCOL" in texto


def _carregar_estado(caminho: Path = ESTADO) -> dict:
    if caminho.exists():
        return json.loads(caminho.read_text(encoding="utf-8"))
    return {"fontes": {}}


def registrar(fonte: str, leitura: Leitura, *, caminho: Path = ESTADO,
              ciclo_dias: int = 1) -> dict:
    """Guarda o resultado da coleta de uma fonte no estado do sistema.

    ``ciclo_dias`` é de quanto em quanto tempo a fonte é lida pelos robôs (1 = todo dia,
    31 = todo mês): o prazo de fonte parada conta a partir do fim do ciclo.
    """
    estado = _carregar_estado(caminho)
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    item = estado["fontes"].setdefault(fonte, {})
    item["ultima_tentativa"] = agora
    item["url"] = leitura.url
    item["ciclo_dias"] = ciclo_dias
    if leitura.ok:
        item["ultimo_sucesso"] = agora
        item["sha256"] = leitura.original.sha256 if leitura.original else None
        item.pop("erro", None)
    else:
        item["erro"] = leitura.erro
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(estado, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return estado


def fontes_paradas(estado: dict, hoje: date, limite_dias: int = 3) -> list[Ficha]:
    """Fonte sem coleta bem-sucedida há mais que o seu ciclo mais ``limite_dias``: falha do sistema.

    Uma fonte lida todo mês não é dada como parada no meio do mês; uma fonte que falhou
    na última tentativa é parada na hora, porque o próximo ciclo ainda não a corrigiu.
    """
    fichas = []
    for fonte, item in sorted(estado.get("fontes", {}).items()):
        sucesso = item.get("ultimo_sucesso")
        ciclo = int(item.get("ciclo_dias") or 1)
        tolerancia = ciclo + limite_dias
        dias = None
        if sucesso:
            dias = (hoje - datetime.fromisoformat(sucesso).date()).days
        falhou_por_ultimo = bool(item.get("erro"))
        if sucesso is None or dias > tolerancia or falhou_por_ultimo:
            quando = f"há {dias} dias" if dias is not None else "nunca"
            fichas.append(emitir(
                codigo=f"SIS-COLETA-{fonte.upper()}",
                familia=Familia.SIS,
                titulo=f"Coleta da fonte {fonte} parada",
                gravidade="alta",
                como_deveria=(f"A fonte é lida a cada {ciclo} dia(s) e não pode passar "
                              f"{limite_dias} dias além disso sem leitura bem-sucedida."),
                norma="Premissa do Onisciente: falha de coleta é falha do sistema",
                como_esta=f"Último sucesso {quando}. Erro registrado: {item.get('erro') or 'nenhum'}.",
                niveis=[],
                documento_faltante=True,
                providencia="Corrigir o coletor desta fonte; enquanto isso o parecer marca em "
                            "vermelho o que ela alimenta.",
                origem="sistema",
            ))
    return fichas
