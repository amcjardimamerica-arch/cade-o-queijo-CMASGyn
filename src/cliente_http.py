"""Cliente HTTP cortês.

Três garantias: intervalo mínimo entre requisições ao mesmo domínio,
respeito ao robots.txt e GET condicional (ETag / If-Modified-Since).
O condicional é regra R7 de economia — HTTP 304 encerra o processamento
da fonte sem gastar CPU, banda nem token.
"""
from __future__ import annotations

import time
import urllib.robotparser
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import requests

from util import ESTADO, gravar_json, ler_json, log, sha256_bytes

CACHE_META = ESTADO / "http_cache.json"


@dataclass
class Resposta:
    url: str
    status: int
    conteudo: bytes | None
    tipo: str
    sha256: str | None
    inalterado: bool = False


@dataclass
class ClienteHTTP:
    user_agent: str
    intervalo: float = 3.0
    timeout: int = 45
    tentativas: int = 3
    respeitar_robots: bool = True

    _ultimo: dict = field(default_factory=dict)
    _robots: dict = field(default_factory=dict)
    _meta: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._meta = ler_json(CACHE_META, {})
        self.sessao = requests.Session()
        self.sessao.headers["User-Agent"] = self.user_agent

    # ---------------------------------------------------------------- cortesia
    def _esperar(self, dominio: str) -> None:
        ultimo = self._ultimo.get(dominio, 0.0)
        espera = self.intervalo - (time.monotonic() - ultimo)
        if espera > 0:
            time.sleep(espera)
        self._ultimo[dominio] = time.monotonic()

    def _permitido(self, url: str) -> bool:
        if not self.respeitar_robots:
            return True
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        if base not in self._robots:
            rp = None
            try:
                # Busca com a NOSSA sessão: o urllib padrão é barrado por
                # proteções tipo Cloudflare, e o RobotFileParser interpreta
                # um 403 como proibição total — falso bloqueio.
                resp = self.sessao.get(f"{base}/robots.txt", timeout=15)
                if resp.status_code == 200:
                    rp = urllib.robotparser.RobotFileParser()
                    rp.parse(resp.text.splitlines())
                elif resp.status_code in (401, 403):
                    log.info("robots.txt de %s inacessível (HTTP %s); "
                             "prossigo com cortesia reforçada", base, resp.status_code)
            except Exception as e:
                log.debug("robots.txt de %s indisponível: %s", base, e)
            self._robots[base] = rp
        rp = self._robots[base]
        return True if rp is None else rp.can_fetch(self.user_agent, url)

    # ------------------------------------------------------------------- busca
    def obter(self, url: str, headers: dict | None = None,
              condicional: bool = True) -> Resposta:
        if not self._permitido(url):
            log.warning("robots.txt proíbe %s — pulando", url)
            return Resposta(url, 999, None, "", None)

        dominio = urlparse(url).netloc
        h = dict(headers or {})
        meta = self._meta.get(url, {})
        if condicional:
            if meta.get("etag"):
                h["If-None-Match"] = meta["etag"]
            if meta.get("last_modified"):
                h["If-Modified-Since"] = meta["last_modified"]

        ultimo_erro = None
        for tentativa in range(1, self.tentativas + 1):
            self._esperar(dominio)
            try:
                r = self.sessao.get(url, headers=h, timeout=self.timeout)
            except requests.RequestException as e:
                ultimo_erro = e
                time.sleep(min(2 ** tentativa, 30))
                continue

            if r.status_code == 304:
                log.debug("304 inalterado: %s", url)
                return Resposta(url, 304, None, meta.get("tipo", ""),
                                meta.get("sha256"), inalterado=True)

            if r.status_code == 429 or 500 <= r.status_code < 600:
                espera = int(r.headers.get("Retry-After", min(2 ** tentativa, 60)))
                log.warning("HTTP %s em %s; aguardando %ss", r.status_code, url, espera)
                time.sleep(espera)
                continue

            if r.status_code != 200:
                log.warning("HTTP %s em %s", r.status_code, url)
                return Resposta(url, r.status_code, None, "", None)

            digest = sha256_bytes(r.content)
            self._meta[url] = {
                "etag": r.headers.get("ETag"),
                "last_modified": r.headers.get("Last-Modified"),
                "sha256": digest,
                "tipo": r.headers.get("Content-Type", ""),
            }
            gravar_json(CACHE_META, self._meta)
            return Resposta(url, 200, r.content,
                            r.headers.get("Content-Type", ""), digest)

        log.error("Falha definitiva em %s: %s", url, ultimo_erro)
        return Resposta(url, 0, None, "", None)

    def baixar(self, url: str, destino: Path, headers: dict | None = None) -> Resposta:
        """Baixa preservando o arquivo original e íntegro.

        O PDF assinado do Diário Oficial é guardado tal como veio: é ele que
        carrega a assinatura ICP-Brasil e a presunção do artigo 10, § 1º, da
        Medida Provisória 2.200-2/2001. Texto extraído é conveniência de busca,
        jamais o documento probatório.
        """
        r = self.obter(url, headers=headers)
        if r.status == 200 and r.conteudo:
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_bytes(r.conteudo)
        return r
