"""
casa-finder — portal gitedegroupe.fr (sur de Francia)

Investigado 2026-07-03 antes de escribir codigo (regla "no asumir" del
CLAUDE.md del proyecto): se hicieron fetches reales de paginas de region y
departamento (`gites-region-aquitaine.html`, `gites-region-midi-pyrenees.html`,
`gites-region-languedoc-roussillon.html` y varias `gites-groupe-{depto}.html`)
y se confirmo que:
- El sitio es SSR puro, sin JS ni anti-bot detectado (a diferencia de VRBO).
- Cada ficha individual vive en `/gite-groupe-{ID}.html`, ID tipo "TH-bd96"
  (2 letras + 4 alfanumericos).
- Los listados por departamento viven en `/gites-groupe-{depto-slug}.html`
  y ya vienen filtrados a ese departamento (no hace falta paginar por region).
- La capacidad aparece en el listado como "N Personnes".
- Los 16 departamentos objetivo (sur de Francia segun mapa compartido por
  el usuario 2026-07-03: Gironde, Landes, Lot-et-Garonne, Gers, Pyrenees-
  Atlantiques, Hautes-Pyrenees, Haute-Garonne, Ariege, Tarn-et-Garonne,
  Tarn, Aveyron, Lot, Lozere, Aude, Herault, Pyrenees-Orientales) tienen
  todos pagina propia confirmada por fetch real -- ver DEPARTMENT_SLUGS.

Estrategia (calco de escapadarural.py, incluido el patron de "subir
 ancestros desde el <a>" para no depender de clases CSS no documentadas):
1. Iteramos `/gites-groupe-{depto-slug}.html` por cada departamento pedido
   (o los 16 de sur de Francia por defecto).
2. Parseamos la lista, filtramos en memoria por capacidad minima.
3. Entramos a la ficha de los que pasan el filtro para nombre limpio,
   descripcion, imagenes y (best-effort) numero de habitaciones.
4. Filtro multi-unidad compartido con la capa API (scraper.store) --
   descarta "Hotel"/"Hotel" en cualquier variante.

Fragilidades conocidas (a vigilar si el sitio cambia de frontend):
- Selectores CSS no documentados, igual que escapadarural -- climb de
  ancestros heuristico.
- No hay paginacion visible en las paginas de departamento exploradas (los
  16 departamentos objetivo tienen pocos resultados, <20 gites cada uno);
  si algun departamento resulta tener mas resultados de los que caben en
  una sola pagina, esto no esta contemplado todavia -- revisar si
  aparecen menos listings de los esperados.
- El numero de habitaciones no viene estructurado -- se intenta extraer
  con regex "N chambres" del texto libre de la ficha, best-effort (puede
  quedar None).
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


# Departamento (nombre humano) -> slug URL. Confirmados por fetch real
# 2026-07-03 contra gites-region-aquitaine.html, gites-region-midi-pyrenees.html
# y gites-region-languedoc-roussillon.html. Son los 16 departamentos del sur
# de Francia que aparecen en el mapa compartido por el usuario.
DEPARTMENT_SLUGS: dict[str, str] = {
    "gironde": "gironde",
    "landes": "landes",
    "lot-et-garonne": "lot-et-garonne",
    "lot et garonne": "lot-et-garonne",
    "gers": "gers",
    "pyrenees-atlantiques": "pyrenees-atlantiques",
    "pyrenees atlantiques": "pyrenees-atlantiques",
    "hautes-pyrenees": "hautes-pyrenees",
    "hautes pyrenees": "hautes-pyrenees",
    "haute-garonne": "haute-garonne",
    "haute garonne": "haute-garonne",
    "ariege": "ariege",
    "tarn-et-garonne": "tarn-et-garonne",
    "tarn et garonne": "tarn-et-garonne",
    "tarn": "tarn",
    "aveyron": "aveyron",
    "lot": "lot",
    "lozere": "lozere",
    "aude": "aude",
    "herault": "herault",
    "pyrenees-orientales": "pyrenees-orientales",
    "pyrenees orientales": "pyrenees-orientales",
}

# Los 16 departamentos por defecto cuando query.regions = None (sur de
# Francia, sin duplicar Lot que aparece solo una vez pese a tener alias).
DEFAULT_DEPARTMENTS = [
    "gironde", "landes", "lot-et-garonne", "gers", "pyrenees-atlantiques",
    "hautes-pyrenees", "haute-garonne", "ariege", "tarn-et-garonne", "tarn",
    "aveyron", "lot", "lozere", "aude", "herault", "pyrenees-orientales",
]

# Enlaces a fichas individuales: /gite-groupe-{ID}.html, ID tipo "TH-bd96"
# (2 letras + guion + 4 alfanumericos). Confirmado por fetch real.
LISTING_HREF_RE = re.compile(r"^/gite-groupe-([A-Za-z0-9]{2}-[0-9a-zA-Z]{4})\.html$")

# Capacidad en el listado: "20 Personnes".
CAPACITY_RE = re.compile(r"(\d+)\s*Personnes?", re.IGNORECASE)
# Habitaciones: best-effort desde texto libre de la ficha ("4 chambres").
BEDROOMS_RE = re.compile(r"(\d+)\s*chambres?", re.IGNORECASE)
# Codigo postal + localidad tal como aparece en el listado, ej "84190 Gigondas".
POSTAL_CITY_RE = re.compile(r"\b(\d{5})\s+([A-ZÀ-Ý][\wÀ-ÿ'\-]*(?:\s[A-ZÀ-Ýa-zà-ÿ'\-]+)*)")

# Igual que escapadarural: cuantos ancestros subimos desde el <a> buscando
# el contenedor con el texto completo de la card ("Personnes" + nombre).
MAX_ANCESTOR_CLIMB = 9


def _normalize_department(name: str) -> str | None:
    """Acepta nombre humano o slug y devuelve el slug URL. None si no mapea."""
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    n = n.lower().strip().replace("_", " ")
    if n in DEPARTMENT_SLUGS:
        return DEPARTMENT_SLUGS[n]
    if n in DEPARTMENT_SLUGS.values():
        return n
    n_kebab = n.replace(" ", "-")
    if n_kebab in DEPARTMENT_SLUGS.values():
        return n_kebab
    return None


class GiteDeGroupe(BasePortal):
    slug: ClassVar[str] = "gitedegroupe"
    display_name: ClassVar[str] = "GiteDeGroupe.fr"
    base_url: ClassVar[str] = "https://www.gitedegroupe.fr"

    def fetch(self, query: SearchQuery, limit: int) -> list[Listing]:
        if query.regions:
            target_slugs: list[str] = []
            for r in query.regions:
                slug = _normalize_department(r)
                if slug:
                    target_slugs.append(slug)
                else:
                    log.warning("departamento desconocido, ignorado: %r", r)
        else:
            target_slugs = list(DEFAULT_DEPARTMENTS)

        if not target_slugs:
            log.warning("no hay departamentos validos, no se hace nada")
            return []

        log.info(
            "fetch start: departments=%s limit=%d min_capacity=%d",
            target_slugs, limit, query.min_capacity,
        )

        results: list[Listing] = []
        with self._http_client() as client:
            for dept_slug in target_slugs:
                if len(results) >= limit:
                    break
                try:
                    dept_results = self._scrape_department(
                        client, dept_slug, query, limit - len(results)
                    )
                    results.extend(dept_results)
                    log.info(
                        "departamento %s: %d listings (acum %d/%d)",
                        dept_slug, len(dept_results), len(results), limit,
                    )
                except Exception:
                    log.exception("fallo scraping departamento %s, continuo", dept_slug)
                    continue

        return results[:limit]

    # ---------- nivel departamento: una sola pagina (sin paginacion conocida) ----------

    def _scrape_department(
        self, client, dept_slug: str, query: SearchQuery, remaining: int
    ) -> list[Listing]:
        out: list[Listing] = []
        url = f"/gites-groupe-{dept_slug}.html"
        try:
            r = client.get(url)
            r.raise_for_status()
        except Exception:
            log.exception("fallo GET %s", url)
            return out

        cards = self._extract_list_cards(r.text)
        if not cards:
            log.info("sin cards en departamento %s", dept_slug)
            return out

        for card in cards:
            if len(out) >= remaining:
                break
            cap_max = card.get("capacity_max")
            if cap_max is None or cap_max < query.min_capacity:
                continue
            if (
                query.max_capacity is not None
                and cap_max > query.max_capacity
            ):
                continue

            time.sleep(self.request_delay_s)
            try:
                listing = self._build_listing(client, card, dept_slug)
                if listing:
                    out.append(listing)
            except Exception:
                log.exception("fallo construyendo listing para %s", card.get("href"))
                continue

        return out

    # ---------- parseo de la lista ----------

    def _extract_list_cards(self, html: str) -> list[dict]:
        """Devuelve dicts con datos crudos de cada card de la lista."""
        soup = BeautifulSoup(html, "lxml")
        seen: set[str] = set()
        cards: list[dict] = []

        for a in soup.find_all("a", href=True):
            href = a["href"]
            # El sitio genera hrefs relativos SIN barra inicial (confirmado
            # 2026-07-03: "gite-groupe-xx-1234.html" en vez de
            # "/gite-groupe-xx-1234.html") -- normalizamos antes de matchear
            # y de usarlo en requests, si no el regex nunca matchea nada.
            if not href.startswith("/"):
                href = "/" + href
            m = LISTING_HREF_RE.match(href)
            if not m:
                continue
            if href in seen:
                continue
            seen.add(href)

            listing_id = m.group(1)

            container: Tag = a
            for _ in range(MAX_ANCESTOR_CLIMB):
                if container.parent is None:
                    break
                container = container.parent
                txt = container.get_text(" ", strip=True)
                if "personnes" in txt.lower():
                    break

            text = container.get_text(" ", strip=True)
            data = self._parse_card_text(text)
            data.update({
                "href": href,
                "listing_id": listing_id,
            })
            cards.append(data)

        return cards

    def _parse_card_text(self, text: str) -> dict:
        """Extrae capacidad y localidad del texto plano de la card."""
        out: dict = {}

        m = CAPACITY_RE.search(text)
        if m:
            out["capacity_max"] = int(m.group(1))

        m = POSTAL_CITY_RE.search(text)
        if m:
            out["postal_code"] = m.group(1)
            out["city"] = m.group(2).strip()

        return out

    # ---------- ficha individual ----------

    def _build_listing(
        self, client, card: dict, dept_slug: str
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

        # El <h1> real tiene un span kicker ("Gite de groupe {region}") pegado
        # sin separador al nombre real (confirmado 2026-07-03: BeautifulSoup
        # concatena "Gite de groupe AquitaineChateau Bouchereau" sin espacio).
        # El <title> es mas fiable: "{Nombre} :  location gite {Depto} - ...".
        name = None
        title_tag = soup.find("title")
        if title_tag:
            raw_title = title_tag.get_text(strip=True)
            candidate = raw_title.split(":")[0].strip()
            if candidate:
                name = candidate
        if not name:
            h1 = soup.find("h1")
            name = h1.get_text(" ", strip=True) if h1 else card["listing_id"]

        # Filtro multi-unidad compartido con la capa API (scraper.store) --
        # descarta "Hotel"/complejos de varias unidades. Ver escapadarural.py
        # para el mismo patron.
        if _is_multi_unit_name(name):
            log.info("descartado por nombre multi-unidad: %s (%s)", name, href)
            return None

        location = card.get("city") or dept_slug

        description = None
        og_desc = soup.find("meta", property="og:description")
        if og_desc and og_desc.get("content"):
            description = og_desc["content"]

        main_image_url = None
        og_img = soup.find("meta", property="og:image")
        if og_img and og_img.get("content"):
            main_image_url = og_img["content"]

        image_urls: list[str] = []
        for img in soup.find_all("img"):
            src = img.get("src") or ""
            if "gitedegroupe.fr" in src and ("/picts/" in src or "/img/" in src):
                clean = src if src.startswith("http") else f"{self.base_url}{src}"
                if clean not in image_urls:
                    image_urls.append(clean)
        if main_image_url and main_image_url not in image_urls:
            image_urls.insert(0, main_image_url)

        # Habitaciones: best-effort desde el texto completo de la ficha.
        bedrooms = None
        page_text = soup.get_text(" ", strip=True)
        m_bed = BEDROOMS_RE.search(page_text)
        if m_bed:
            bedrooms = int(m_bed.group(1))

        # Capacidad: usamos la del listado (card), no la de texto libre de la
        # ficha -- probado 2026-07-03 que la ficha puede mencionar otras
        # cifras de "N Personnes" en parrafos de precio/oferta que no son la
        # capacidad real, pisando el valor correcto del listado.
        capacity_max = card.get("capacity_max")
        if capacity_max is None:
            log.warning("sin capacidad para %s, descartado", href)
            return None
        # Guarda de cordura (2026-07-03): el climb de ancestros puede a veces
        # mezclar texto de una card vecina y capturar un numero de "Personnes"
        # que no es la capacidad real (visto: 335 pax en una casa cualquiera).
        # Ninguna casa de grupo real llega a este tamano -- descartamos en vez
        # de guardar un dato claramente corrupto.
        if capacity_max > 150:
            log.warning(
                "capacidad implausible (%d) para %s, descartado (probable "
                "contaminacion de card vecina)", capacity_max, href,
            )
            return None

        raw = {
            "listing_id": card["listing_id"],
            "department_slug": dept_slug,
            "postal_code": card.get("postal_code"),
        }

        try:
            return Listing(
                portal=self.slug,
                portal_listing_id=card["listing_id"],
                url=url,
                name=name,
                location=location,
                region=dept_slug,
                country="FR",
                capacity_min=None,
                capacity_max=capacity_max,
                bedrooms=bedrooms,
                bathrooms=None,
                price_per_night=None,
                price_per_stay=None,
                price_currency="EUR",
                price_context="gitedegroupe.fr no expone precio sin fechas",
                main_image_url=main_image_url,
                image_urls=image_urls[:20],
                amenities=[],
                description=description,
                raw=raw,
            )
        except ValidationError:
            log.exception("Listing invalido para %s", href)
            return None