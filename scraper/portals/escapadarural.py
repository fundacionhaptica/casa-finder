"""
casa-finder — portal escapadarural.com

Estrategia (basada en exploracion 2.6a):
1. Iteramos `/casas-rurales-grupos-{region-slug}?pagina=N` por cada region
   solicitada en query.regions (o las 17 comunidades por defecto).
2. Parseamos la lista (SSR, sin JS), filtramos en memoria por capacity_max.
3. Solo entramos a la ficha de los listings que pasan el filtro — ahi
   sacamos coordenadas, amenities, imagenes, direccion.
4. Respetamos request_delay_s entre requests al mismo host.
5. Errores parciales: log + continue, nunca abortamos todo el batch.

IDs:
- portal_listing_id = "{provincia}/{slug}" (estable mientras no renombren).
- ID numerico interno (visible en URLs de imagenes) va en raw como bonus.

Fragilidades conocidas:
- Selectores CSS no documentados — usamos patrones defensivos (regex en href,
  busqueda de texto plano del card). Si escapadarural rehace el frontend,
  toca ajustar este modulo.
- Precio en lista = aprox/persona/noche. Precio real requiere meter fechas
  (no implementado en este scraper base).
- El sitio NO valida el parametro `pagina`: pedir una pagina fuera de rango
  devuelve el mismo HTML que la pagina 1 (confirmado 2026-07-01), en vez de
  una lista vacia o 404. Por eso el bucle de paginacion tiene un tope duro
  MAX_PAGES_PER_REGION ademas del corte por `empty_streak` — no podemos
  confiar solo en "pagina vacia" para saber que hemos llegado al final.
- Filtro multi-unidad (2026-07-03): algunas fichas de escapadarural agregan
  varias casas o apartamentos independientes (o son un hotel) bajo un unico
  listing -- se detectan por nombres tipo "Casas ...", "Apartamentos ..."
  (plural) e "Hotel ...", y suelen tener un numero de dormitorios anormalmente
  alto (23-40) porque suman varias unidades. La familia quiere alquilar una
  UNICA casa entera para todos juntos, asi que estos se descartan en
  _build_listing usando la misma funcion que la capa API (scraper.store).
"""

from __future__ import annotations

import logging
import re
import time
import unicodedata
from typing import ClassVar

from bs4 import BeautifulSoup, Tag
from pydantic import ValidationError

from ..models import Listing, SearchQuery
from ..store import _is_multi_unit_name
from .base import BasePortal

log = logging.getLogger(__name__)


# Mapping de region/comunidad humana → slug URL de escapadarural.
# Acepta tambien provincias (URL /casas-rurales-grupos-{provincia} funciona).
REGION_SLUGS: dict[str, str] = {
    # Comunidades autonomas (cubierta total Espana)
    "andalucia": "andalucia",
    "aragon": "aragon",
    "asturias": "asturias",
    "cantabria": "cantabria",
    "castilla y leon": "castilla-y-leon",
    "castilla-leon": "castilla-y-leon",
    "castilla la mancha": "castilla-la-mancha",
    "castilla-la-mancha": "castilla-la-mancha",
    "cataluna": "cataluna",
    "catalunya": "cataluna",
    "comunidad valenciana": "comunidad-valenciana",
    "valencia": "comunidad-valenciana",
    "extremadura": "extremadura",
    "galicia": "galicia",
    "islas baleares": "islas-baleares",
    "baleares": "islas-baleares",
    "islas canarias": "islas-canarias",
    "canarias": "islas-canarias",
    "la rioja": "la-rioja",
    "rioja": "la-rioja",
    "madrid": "madrid",
    "murcia": "murcia",
    "navarra": "navarra",
    "pais vasco": "pais-vasco",
    "euskadi": "pais-vasco",
}

# Las 17 comunidades por defecto cuando query.regions = None.
ALL_COMMUNITIES = [
    "andalucia", "aragon", "asturias", "cantabria", "castilla-y-leon",
    "castilla-la-mancha", "cataluna", "comunidad-valenciana", "extremadura",
    "galicia", "islas-baleares", "islas-canarias", "la-rioja", "madrid",
    "murcia", "navarra", "pais-vasco",
]

# Regex para detectar enlaces a fichas de alojamiento.
# /casa-rural/{provincia}/{slug}  (sin segmentos adicionales)
LISTING_HREF_RE = re.compile(r"^/casa-rural/([^/]+)/([^/?#]+)/?$")

# Patrones para extraer datos del texto plano del card.
CAPACITY_RE = re.compile(r"(\d+)\s*(?:-\s*(\d+))?\s*personas?", re.IGNORECASE)
BEDROOMS_RE = re.compile(r"(\d+)\s*dormitorios?", re.IGNORECASE)
BEDS_RE = re.compile(r"(\d+)\s*camas?", re.IGNORECASE)
PRICE_PER_NIGHT_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*€\s*pers\.?\s*/?\s*noche", re.IGNORECASE
)
# Coordenadas en ficha: "Latitud 41.687... - Longitud 1.705..."
COORDS_RE = re.compile(
    r"Latitud\s+(-?\d+\.\d+)\s*-\s*Longitud\s+(-?\d+\.\d+)",
    re.IGNORECASE,
)
# ID numerico interno extraido de URLs de imagenes:
# https://webp.er2.co/es/{provincia}/{ID-10-digitos}/...
INTERNAL_ID_RE = re.compile(r"webp\.er2\.co/[^/]+/[^/]+/(\d{10,})/")

# Cuantos niveles de ancestro subimos desde el <a> de la ficha buscando el
# contenedor que agrupa nombre+descripcion+personas+dormitorios+precio.
# Bug detectado 2026-07-01: con 5 niveles el contenedor seguia vacio (el sitio
# anade un wrapper extra respecto a la exploracion original); a partir del
# nivel 6 aparece el texto completo. Subimos el limite con margen.
MAX_ANCESTOR_CLIMB = 9

# Tope duro de paginas por region. El sitio no valida `pagina`: pedir una
# fuera de rango devuelve el mismo HTML que la pagina 1 (confirmado
# 2026-07-01 comparando pagina=1 vs pagina=50 byte a byte), asi que no
# podemos fiarnos solo del corte por `empty_streak` para no bucle infinito.
MAX_PAGES_PER_REGION = 15


def _normalize_region(name: str) -> str | None:
    """Acepta nombres humanos o slugs y devuelve el slug URL. None si no mapea."""
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    n = n.lower().strip().replace("_", " ")
    if n in REGION_SLUGS:
        return REGION_SLUGS[n]
    # Quiza viene ya como slug (ej "castilla-y-leon")
    if n in REGION_SLUGS.values():
        return n
    # Slug con espacios -> kebab-case
    n_kebab = n.replace(" ", "-")
    if n_kebab in REGION_SLUGS.values():
        return n_kebab
    return None


class EscapadaRural(BasePortal):
    slug: ClassVar[str] = "escapadarural"
    display_name: ClassVar[str] = "EscapadaRural"
    base_url: ClassVar[str] = "https://www.escapadarural.com"

    def fetch(self, query: SearchQuery, limit: int) -> list[Listing]:
        # Resolver regiones objetivo
        if query.regions:
            target_slugs: list[str] = []
            for r in query.regions:
                slug = _normalize_region(r)
                if slug:
                    target_slugs.append(slug)
                else:
                    log.warning("region desconocida, ignorada: %r", r)
        else:
            target_slugs = list(ALL_COMMUNITIES)

        if not target_slugs:
            log.warning("no hay regiones validas, no se hace nada")
            return []

        log.info(
            "fetch start: regions=%s limit=%d min_capacity=%d",
            target_slugs, limit, query.min_capacity,
        )

        results: list[Listing] = []
        with self._http_client() as client:
            for region_slug in target_slugs:
                if len(results) >= limit:
                    break
                try:
                    region_results = self._scrape_region(
                        client, region_slug, query, limit - len(results)
                    )
                    results.extend(region_results)
                    log.info(
                        "region %s: %d listings (acum %d/%d)",
                        region_slug, len(region_results), len(results), limit,
                    )
                except Exception:
                    log.exception("fallo scraping region %s, continuo", region_slug)
                    continue

        return results[:limit]

    # ---------- nivel region: paginar lista ----------

    def _scrape_region(
        self, client, region_slug: str, query: SearchQuery, remaining: int
    ) -> list[Listing]:
        out: list[Listing] = []
        page = 1
        empty_streak = 0

        while (
            len(out) < remaining
            and empty_streak < 2
            and page <= MAX_PAGES_PER_REGION
        ):
            url = f"/casas-rurales-grupos-{region_slug}"
            params = {"pagina": str(page)} if page > 1 else None
            try:
                r = client.get(url, params=params)
                r.raise_for_status()
            except Exception:
                log.exception("fallo GET %s pagina=%d", url, page)
                break

            cards = self._extract_list_cards(r.text)
            if not cards:
                empty_streak += 1
                log.info("sin cards en %s pagina=%d", region_slug, page)
            else:
                empty_streak = 0

            for card in cards:
                if len(out) >= remaining:
                    break
                # Filtro temprano por capacidad antes de pegar a la ficha
                cap_max = card.get("capacity_max")
                if cap_max is None or cap_max < query.min_capacity:
                    continue
                if (
                    query.max_capacity is not None
                    and (card.get("capacity_min") or cap_max) > query.max_capacity
                ):
                    continue

                # Enriquecer con la ficha
                time.sleep(self.request_delay_s)
                try:
                    listing = self._build_listing(client, card, region_slug)
                    if listing:
                        out.append(listing)
                except Exception:
                    log.exception(
                        "fallo construyendo listing para %s", card.get("href")
                    )
                    continue

            page += 1
            time.sleep(self.request_delay_s)

        if page > MAX_PAGES_PER_REGION:
            log.warning(
                "region %s: alcanzado tope MAX_PAGES_PER_REGION=%d sin llenar "
                "remaining=%d (posible pagina= sin validar en el sitio)",
                region_slug, MAX_PAGES_PER_REGION, remaining,
            )

        return out

    # ---------- parseo de la lista ----------

    def _extract_list_cards(self, html: str) -> list[dict]:
        """Devuelve dicts con datos crudos de cada card de la lista."""
        soup = BeautifulSoup(html, "lxml")
        seen: set[str] = set()
        cards: list[dict] = []

        for a in soup.find_all("a", href=True):
            href = a["href"]
            m = LISTING_HREF_RE.match(href)
            if not m:
                continue
            if href in seen:
                continue
            seen.add(href)

            province, slug = m.group(1), m.group(2)

            # Subimos al ancestor que contenga toda la card (heuristico).
            # Pillamos el bloque de texto del primer padre con suficiente contenido.
            container: Tag = a
            for _ in range(MAX_ANCESTOR_CLIMB):
                if container.parent is None:
                    break
                container = container.parent
                txt = container.get_text(" ", strip=True)
                if (
                    "personas" in txt.lower()
                    and ("dormitorio" in txt.lower() or "cama" in txt.lower())
                ):
                    break

            text = container.get_text(" ", strip=True)
            data = self._parse_card_text(text)
            data.update({
                "href": href,
                "province": province,
                "slug": slug,
                "portal_listing_id": f"{province}/{slug}",
            })
            cards.append(data)

        return cards

    def _parse_card_text(self, text: str) -> dict:
        """Extrae capacidad/dormitorios/camas/precio del texto plano de la card."""
        out: dict = {}

        m = CAPACITY_RE.search(text)
        if m:
            lo = int(m.group(1))
            hi = int(m.group(2)) if m.group(2) else lo
            out["capacity_min"] = lo if hi != lo else None
            out["capacity_max"] = hi

        m = BEDROOMS_RE.search(text)
        if m:
            out["bedrooms"] = int(m.group(1))

        m = BEDS_RE.search(text)
        if m:
            out["beds"] = int(m.group(1))

        m = PRICE_PER_NIGHT_RE.search(text)
        if m:
            try:
                out["price_per_night"] = float(m.group(1).replace(",", "."))
            except ValueError:
                pass

        return out

    # ---------- ficha individual ----------

    def _build_listing(
        self, client, card: dict, region_slug: str
    ) -> Listing | None:
        """Fetch a la ficha y construye el Listing final."""
        href = card["href"]
        url = f"{self.base_url}{href}"
        try:
            r = client.get(href)
            r.raise_for_status()
        except Exception:
            log.exception("fallo GET ficha %s", href)
            return None

        soup = BeautifulSoup(r.text, "lxml")

        # Nombre desde <h1> o <title>
        name = None
        h1 = soup.find("h1")
        if h1:
            name = h1.get_text(strip=True)
        if not name:
            title = soup.find("title")
            name = title.get_text(strip=True) if title else card["slug"]

        # Filtro multi-unidad (2026-07-03): complejos de varias casas,
        # apartamentos o un hotel no sirven -- la familia quiere alquilar
        # una unica casa entera. Misma funcion que usa la capa API
        # (scraper.store) para que el criterio sea identico en ambos sitios.
        if _is_multi_unit_name(name):
            log.info("descartado por nombre multi-unidad: %s (%s)", name, href)
            return None

        # Localidad: meta og:title suele ser "NOMBRE en LOCALIDAD"
        location = card["province"]
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            ct = og_title["content"]
            if " en " in ct:
                location = ct.split(" en ", 1)[1].strip()

        # Descripcion
        description = None
        og_desc = soup.find("meta", property="og:description")
        if og_desc and og_desc.get("content"):
            description = og_desc["content"]

        # Imagen principal
        main_image_url = None
        og_img = soup.find("meta", property="og:image")
        if og_img and og_img.get("content"):
            main_image_url = og_img["content"]

        # Imagenes adicionales
        image_urls: list[str] = []
        for img in soup.find_all("img"):
            src = img.get("src") or ""
            if "webp.er2.co" in src or "ucmedia.er2.co" in src:
                # _ipx puede envolver la URL real; sacamos la parte tras 'https://'
                clean = src.split("https://")[-1]
                clean = "https://" + clean if not clean.startswith("http") else clean
                if clean not in image_urls:
                    image_urls.append(clean)
        if main_image_url and main_image_url not in image_urls:
            image_urls.insert(0, main_image_url)

        # ID numerico interno (bonus)
        full_text = r.text
        internal_id = None
        m_id = INTERNAL_ID_RE.search(full_text)
        if m_id:
            internal_id = m_id.group(1)

        # Coordenadas
        lat = lon = None
        page_text = soup.get_text(" ", strip=True)
        m_co = COORDS_RE.search(page_text)
        if m_co:
            try:
                lat = float(m_co.group(1))
                lon = float(m_co.group(2))
            except ValueError:
                pass

        # Amenities: recolectamos <li> dentro de secciones con titulos conocidos
        amenities: list[str] = []
        for h in soup.find_all(["h2", "h3", "h4"]):
            ht = h.get_text(strip=True).lower()
            if any(k in ht for k in ("caracteristic", "servicio", "exterior",
                                      "interior", "actividad")):
                # Coge <li> en los siguientes 6 elementos
                sibling = h
                for _ in range(6):
                    sibling = sibling.find_next_sibling()
                    if sibling is None:
                        break
                    for li in sibling.find_all("li"):
                        t = li.get_text(strip=True)
                        if t and t not in amenities:
                            amenities.append(t)

        # Construir Listing
        raw = {
            "internal_id": internal_id,
            "region_slug": region_slug,
            "province_slug": card["province"],
            "coords": {"lat": lat, "lon": lon} if lat is not None else None,
            "beds": card.get("beds"),
        }

        try:
            return Listing(
                portal=self.slug,
                portal_listing_id=card["portal_listing_id"],
                url=url,
                name=name,
                location=location,
                region=region_slug,
                country="ES",
                capacity_min=card.get("capacity_min"),
                capacity_max=card["capacity_max"],
                bedrooms=card.get("bedrooms"),
                bathrooms=None,  # no expuesto en lista; podriamos sacarlo de la ficha
                price_per_night=card.get("price_per_night"),
                price_per_stay=None,
                price_currency="EUR",
                price_context="aprox. por persona/noche segun escapadarural",
                main_image_url=main_image_url,
                image_urls=image_urls[:20],  # limite sensato
                amenities=amenities,
                description=description,
                raw=raw,
            )
        except ValidationError:
            log.exception("Listing invalido para %s", href)
            return None