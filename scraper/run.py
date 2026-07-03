"""
casa-finder — entry point del scraper.

CLI para ejecutar uno o varios portales. Cada portal se ejecuta de forma
independiente: un fallo en uno no aborta el resto.

Uso:
    # Todos los portales con limit por defecto:
    python -m scraper.run

    # Solo escapadarural, max 10 resultados, regiones especificas:
    python -m scraper.run --only escapadarural --limit 10 \\
        --regions aragon cataluna --min-capacity 20

    # Dry-run (no persiste en SQLite):
    python -m scraper.run --only escapadarural --limit 3 --dry-run

Flujo por portal:
    1. start_run() → row en scrape_runs con status='running'.
    2. portal.fetch(query, limit) → list[Listing].
    3. Por cada listing: upsert_listing() → contador nuevas/actualizadas.
    4. finish_run() con status='ok'|'error' y listings_found.

Log format: timestamp + nivel + modulo + mensaje. WARN/ERROR a stderr.
"""

from __future__ import annotations

import argparse
import logging
import sys
import traceback
from pathlib import Path
from typing import Type

from .models import SearchQuery
from .portals.base import BasePortal
from .portals.escapadarural import EscapadaRural
from .portals.gitedegroupe import GiteDeGroupe
from .store import DEFAULT_DB_PATH, finish_run, session, start_run, upsert_listing

log = logging.getLogger("scraper.run")

# Registry de portales disponibles. Slug → clase.
PORTAL_REGISTRY: dict[str, Type[BasePortal]] = {
    EscapadaRural.slug: EscapadaRural,
    GiteDeGroupe.slug: GiteDeGroupe,
}


def _build_query(args: argparse.Namespace) -> SearchQuery:
    """Construye SearchQuery desde los argumentos del CLI."""
    return SearchQuery(
        min_capacity=args.min_capacity,
        max_capacity=args.max_capacity,
        regions=args.regions or None,
        max_results=args.limit,
    )


def _run_portal(
    portal_cls: Type[BasePortal],
    query: SearchQuery,
    limit: int,
    db_path: Path,
    dry_run: bool,
) -> dict[str, int]:
    """Ejecuta un portal y devuelve contadores.

    En dry_run no se persiste en SQLite (ni listings ni scrape_runs).
    """
    portal = portal_cls()
    counters = {"fetched": 0, "new": 0, "updated": 0, "errors": 0}

    log.info("=== portal %s START (limit=%d) ===", portal.slug, limit)

    if dry_run:
        try:
            listings = portal.fetch(query, limit)
            counters["fetched"] = len(listings)
            for li in listings:
                log.info(
                    "  [DRY] %s | %s | pax=%s | %s€/noche",
                    li.name[:40], li.region or "-", li.capacity_max,
                    li.price_per_night,
                )
        except Exception:
            log.exception("fallo portal %s en dry-run", portal.slug)
            counters["errors"] = 1
        log.info("=== portal %s END (dry-run) ===", portal.slug)
        return counters

    with session(db_path) as conn:
        run_id = start_run(conn, portal.slug)
        try:
            listings = portal.fetch(query, limit)
            counters["fetched"] = len(listings)

            for li in listings:
                try:
                    is_new = upsert_listing(conn, li)
                    if is_new:
                        counters["new"] += 1
                    else:
                        counters["updated"] += 1
                except Exception:
                    log.exception("fallo upsert listing %s", li.cache_key())
                    counters["errors"] += 1

            finish_run(
                conn, run_id, counters["fetched"],
                status="ok" if counters["errors"] == 0 else "partial",
                error=None if counters["errors"] == 0 else f"{counters['errors']} upsert errors",
            )
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            log.exception("fallo portal %s", portal.slug)
            finish_run(conn, run_id, counters["fetched"], status="error", error=err)
            counters["errors"] += 1

    log.info(
        "=== portal %s END (fetched=%d new=%d updated=%d errors=%d) ===",
        portal.slug, counters["fetched"], counters["new"], counters["updated"],
        counters["errors"],
    )
    return counters


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="casa-finder scraper — ejecuta uno o varios portales",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--only", action="append", metavar="PORTAL",
        help="Limitar a un portal especifico (puede repetirse). "
             f"Disponibles: {', '.join(PORTAL_REGISTRY)}",
    )
    p.add_argument(
        "--limit", type=int, default=50,
        help="Maximo de listings POR PORTAL",
    )
    p.add_argument(
        "--db", default=DEFAULT_DB_PATH, type=Path,
        help="Path al SQLite",
    )
    p.add_argument(
        "--regions", nargs="+", default=None,
        help="Regiones a scrapear (ej 'aragon cataluna'). Default: todas.",
    )
    p.add_argument(
        "--min-capacity", type=int, default=20,
        help="Plazas minimas (filtro defensivo en cliente)",
    )
    p.add_argument(
        "--max-capacity", type=int, default=None,
        help="Plazas maximas (opcional)",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="No persiste en SQLite, solo logea lo que se traeria",
    )
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Resolver portales objetivo.
    if args.only:
        target_slugs = []
        for slug in args.only:
            if slug not in PORTAL_REGISTRY:
                log.error("portal desconocido: %s", slug)
                return 2
            target_slugs.append(slug)
    else:
        target_slugs = list(PORTAL_REGISTRY)

    try:
        query = _build_query(args)
    except Exception as exc:
        log.error("query invalida: %s", exc)
        return 2

    total = {"fetched": 0, "new": 0, "updated": 0, "errors": 0}
    for slug in target_slugs:
        portal_cls = PORTAL_REGISTRY[slug]
        try:
            c = _run_portal(portal_cls, query, args.limit, args.db, args.dry_run)
        except Exception:
            log.error("error inesperado en portal %s:\n%s", slug, traceback.format_exc())
            c = {"fetched": 0, "new": 0, "updated": 0, "errors": 1}
        for k in total:
            total[k] += c[k]

    print(
        f"\nResumen total ({len(target_slugs)} portal/es):\n"
        f"  fetched:        {total['fetched']}\n"
        f"  nuevas:         {total['new']}\n"
        f"  actualizadas:   {total['updated']}\n"
        f"  errores:        {total['errors']}\n"
        f"  db:             {args.db}\n"
    )
    return 0 if total["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())