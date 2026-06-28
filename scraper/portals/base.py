"""
casa-finder — contrato de portal.

Cada portal hereda de BasePortal y expone `fetch(query, limit) -> list[Listing]`.
La base ofrece un helper `_http_client()` que devuelve un httpx.Client con
headers, user-agent y timeout sensatos.

Decisiones:
- API sincrona (httpx.Client, no AsyncClient). Mas simple y suficiente
  para el cron diario. Si en el futuro hace falta paralelismo, migramos.
- Sin Playwright. Si un portal lo necesita en el futuro, se anade en ese
  portal y en requirements/Dockerfile en ese momento.
- Cada fetch() abre y cierra su propio cliente HTTP.
- Timeout por defecto 30s.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import ClassVar, Iterator

import httpx

from ..models import Listing, SearchQuery

log = logging.getLogger(__name__)

# UA realista de Chrome — portales rurales filtran a UAs raros/vacios.
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/127.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


class BasePortal(ABC):
    """Contrato base para un portal.

    Subclases obligatorias: definir `slug`, `display_name`, `base_url` y
    sobreescribir `fetch()`.
    """

    # Identidad (obligatorio en subclases)
    slug: ClassVar[str] = ""
    display_name: ClassVar[str] = ""
    base_url: ClassVar[str] = ""

    # Configuracion opcional
    user_agent: ClassVar[str] = DEFAULT_USER_AGENT
    request_delay_s: ClassVar[float] = 1.0  # respeto entre requests al mismo host

    def __init__(self, *, timeout_s: float = 30.0) -> None:
        self.timeout_s = timeout_s
        if not self.slug or not self.base_url:
            raise TypeError(
                f"{type(self).__name__} debe definir 'slug' y 'base_url' como ClassVar"
            )

    @abstractmethod
    def fetch(self, query: SearchQuery, limit: int) -> list[Listing]:
        """Ejecuta la busqueda y devuelve hasta `limit` listings normalizados.

        Responsabilidades del portal:
        - Construir las URLs a partir de `query`.
        - Paginar hasta cubrir `limit` (o agotarse).
        - Normalizar cada resultado a un `Listing` valido.
        - Capturar errores parciales sin abortar todo el batch (loggear y seguir).
        - Respetar `request_delay_s` entre requests al mismo host.
        """
        ...

    # ---------- helpers para subclases ----------

    @contextmanager
    def _http_client(self) -> Iterator[httpx.Client]:
        """Cliente HTTP con headers y timeout sensatos.

        Uso tipico:
            with self._http_client() as client:
                r = client.get(url)
                r.raise_for_status()
        """
        headers = {**DEFAULT_HEADERS, "User-Agent": self.user_agent}
        with httpx.Client(
            headers=headers,
            timeout=self.timeout_s,
            follow_redirects=True,
            base_url=self.base_url,
        ) as client:
            yield client

    def __repr__(self) -> str:
        return f"<{type(self).__name__} slug={self.slug!r}>"