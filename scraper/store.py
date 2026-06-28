"""
casa-finder — capa de persistencia (SQLite).

Cuatro tablas:
- listings: estado actual de cada casa, una fila por (portal, portal_listing_id).
- prices: historico de precios. Insert siempre que veamos un precio (incluso si
  no ha cambiado, para tener evidencia de "seguia activa este dia").
- scrape_runs: auditoria de cada ejecucion de scraper.
- seeds: casas conocidas importadas de fuentes externas (ej Excel GAV24) con
  metadatos cualitativos que ningun scraper expone (notas personales,
  decision tomada). Clave natural (source, name) o (source, url_original).

Decisiones:
- PK de listings = string "portal:portal_listing_id" (cache_key del Listing).
- Listas (image_urls, amenities) y raw se serializan como JSON en TEXT.
- WAL mode para evitar problemas de bloqueo si la API lee mientras scraper escribe.
- Sin ORM — sqlite3 stdlib + funciones puras. Vale para este volumen.
- seeds es tabla INDEPENDIENTE de listings: no comparten clave porque las seeds
  no tienen `portal_listing_id` estable. El link futuro seeds<->listings se
  hara por similitud de nombre + ubicacion en la capa API.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .models import Listing

# Path por defecto dentro del contenedor scraper (mapea a ./data en host)
DEFAULT_DB_PATH = Path("/app/data/casas.db")

# Valores validos para seeds.decision (no enforced por SQLite, solo doc)
SEED_DECISIONS = ("chosen", "ruled-out", "pending", "unknown")


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS listings (
    key                 TEXT PRIMARY KEY,           -- 'portal:portal_listing_id'
    portal              TEXT NOT NULL,
    portal_listing_id   TEXT NOT NULL,
    url                 TEXT NOT NULL,
    name                TEXT NOT NULL,
    location            TEXT NOT NULL,
    region              TEXT,
    country             TEXT NOT NULL,
    capacity_min        INTEGER,
    capacity_max        INTEGER NOT NULL,
    bedrooms            INTEGER,
    bathrooms           INTEGER,
    price_per_night     REAL,
    price_per_stay      REAL,
    price_currency      TEXT NOT NULL DEFAULT 'EUR',
    price_context       TEXT,
    main_image_url      TEXT,
    image_urls_json     TEXT NOT NULL DEFAULT '[]',
    amenities_json      TEXT NOT NULL DEFAULT '[]',
    description         TEXT,
    raw_json            TEXT,
    first_seen_at       TEXT NOT NULL,              -- ISO 8601 UTC
    last_seen_at        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_listings_portal ON listings(portal);
CREATE INDEX IF NOT EXISTS idx_listings_capacity_max ON listings(capacity_max);
CREATE INDEX IF NOT EXISTS idx_listings_country_region ON listings(country, region);

CREATE TABLE IF NOT EXISTS prices (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_key         TEXT NOT NULL REFERENCES listings(key) ON DELETE CASCADE,
    scraped_at          TEXT NOT NULL,              -- ISO 8601 UTC
    price_per_night     REAL,
    price_per_stay      REAL,
    price_currency      TEXT NOT NULL DEFAULT 'EUR',
    price_context       TEXT
);

CREATE INDEX IF NOT EXISTS idx_prices_listing_time ON prices(listing_key, scraped_at);

CREATE TABLE IF NOT EXISTS scrape_runs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    portal              TEXT NOT NULL,
    started_at          TEXT NOT NULL,
    finished_at         TEXT,
    status              TEXT NOT NULL DEFAULT 'running',  -- running|ok|error
    listings_found      INTEGER NOT NULL DEFAULT 0,
    error               TEXT
);

CREATE INDEX IF NOT EXISTS idx_scrape_runs_portal_time ON scrape_runs(portal, started_at);

CREATE TABLE IF NOT EXISTS seeds (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source              TEXT NOT NULL,              -- 'gav24', 'gav26', ...
    name                TEXT NOT NULL,
    url_original        TEXT,                       -- URL del portal original (puede repetir)
    location            TEXT,                       -- texto libre tal como venia
    country             TEXT,                       -- 'ES', 'FR', ...
    capacity_pax        INTEGER,                    -- normalizado a int cuando se pudo
    bedrooms_or_rooms   TEXT,                       -- formato libre, ej '10 hab.', '13', '3 apartamentos.'
    has_pool            INTEGER,                    -- 0/1/NULL (sqlite no tiene BOOL)
    price_total_eur     REAL,                       -- precio total de la estancia
    stay_nights         INTEGER,                    -- nº noches (4 para GAV24)
    price_per_night_eur REAL,                       -- calculado si hay total + nights
    personal_notes      TEXT,                       -- comentarios del usuario
    decision            TEXT,                       -- chosen|ruled-out|pending|unknown
    investigated_at     TEXT,                       -- ISO date o year-month, ej '2024-01'
    raw_json            TEXT,                       -- fila CSV original para debug
    imported_at         TEXT NOT NULL,              -- ISO 8601 UTC
    UNIQUE(source, name)
);

CREATE INDEX IF NOT EXISTS idx_seeds_source ON seeds(source);
CREATE INDEX IF NOT EXISTS idx_seeds_capacity ON seeds(capacity_pax);
CREATE INDEX IF NOT EXISTS idx_seeds_decision ON seeds(decision);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Abre la conexion y aplica pragmas. Crea el directorio si no existe."""
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p, isolation_level=None)  # autocommit
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Crea tablas e indices si no existen. Idempotente."""
    conn.executescript(SCHEMA_SQL)


@contextmanager
def session(db_path: Path | str = DEFAULT_DB_PATH) -> Iterator[sqlite3.Connection]:
    """Context manager: abre conexion, inicializa schema, cierra al salir."""
    conn = connect(db_path)
    try:
        init_schema(conn)
        yield conn
    finally:
        conn.close()


def upsert_listing(conn: sqlite3.Connection, listing: Listing) -> bool:
    """Inserta o actualiza una casa.

    Devuelve True si la fila era nueva, False si ya existia.
    Tambien anade siempre una fila a `prices` si hay precio.
    """
    key = listing.cache_key()
    now = _now_iso()

    row = conn.execute(
        "SELECT 1 FROM listings WHERE key = ?", (key,)
    ).fetchone()
    is_new = row is None

    payload = {
        "key": key,
        "portal": listing.portal,
        "portal_listing_id": listing.portal_listing_id,
        "url": str(listing.url),
        "name": listing.name,
        "location": listing.location,
        "region": listing.region,
        "country": listing.country,
        "capacity_min": listing.capacity_min,
        "capacity_max": listing.capacity_max,
        "bedrooms": listing.bedrooms,
        "bathrooms": listing.bathrooms,
        "price_per_night": listing.price_per_night,
        "price_per_stay": listing.price_per_stay,
        "price_currency": listing.price_currency,
        "price_context": listing.price_context,
        "main_image_url": str(listing.main_image_url) if listing.main_image_url else None,
        "image_urls_json": json.dumps([str(u) for u in listing.image_urls]),
        "amenities_json": json.dumps(listing.amenities, ensure_ascii=False),
        "description": listing.description,
        "raw_json": json.dumps(listing.raw, ensure_ascii=False) if listing.raw else None,
        "last_seen_at": now,
    }

    if is_new:
        payload["first_seen_at"] = now
        cols = ", ".join(payload.keys())
        placeholders = ", ".join(f":{k}" for k in payload.keys())
        conn.execute(
            f"INSERT INTO listings ({cols}) VALUES ({placeholders})", payload
        )
    else:
        set_clause = ", ".join(f"{k} = :{k}" for k in payload.keys())
        conn.execute(
            f"UPDATE listings SET {set_clause} WHERE key = :key", payload
        )

    # Snapshot de precio (solo si hay algun precio)
    if listing.price_per_night is not None or listing.price_per_stay is not None:
        conn.execute(
            "INSERT INTO prices (listing_key, scraped_at, price_per_night, "
            "price_per_stay, price_currency, price_context) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                key,
                now,
                listing.price_per_night,
                listing.price_per_stay,
                listing.price_currency,
                listing.price_context,
            ),
        )

    return is_new


def upsert_seed(conn: sqlite3.Connection, seed: dict[str, Any]) -> bool:
    """Inserta o actualiza una seed (casa conocida de fuente externa).

    Clave natural: (source, name) — enforced por UNIQUE constraint.
    Devuelve True si la fila era nueva, False si ya existia y se ha actualizado.

    Campos esperados en `seed` (todos opcionales menos source + name):
        source, name, url_original, location, country,
        capacity_pax, bedrooms_or_rooms, has_pool,
        price_total_eur, stay_nights, price_per_night_eur,
        personal_notes, decision, investigated_at, raw_json
    """
    if not seed.get("source") or not seed.get("name"):
        raise ValueError("upsert_seed: 'source' y 'name' son obligatorios")

    now = _now_iso()

    # Calcula price_per_night si tenemos total + nights y no viene calculado
    total = seed.get("price_total_eur")
    nights = seed.get("stay_nights")
    if (
        seed.get("price_per_night_eur") is None
        and total is not None
        and nights is not None
        and nights > 0
    ):
        seed["price_per_night_eur"] = round(total / nights, 2)

    # Decision por defecto
    if seed.get("decision") is None:
        seed["decision"] = "unknown"

    payload = {
        "source": seed["source"],
        "name": seed["name"],
        "url_original": seed.get("url_original"),
        "location": seed.get("location"),
        "country": seed.get("country"),
        "capacity_pax": seed.get("capacity_pax"),
        "bedrooms_or_rooms": seed.get("bedrooms_or_rooms"),
        "has_pool": seed.get("has_pool"),
        "price_total_eur": seed.get("price_total_eur"),
        "stay_nights": seed.get("stay_nights"),
        "price_per_night_eur": seed.get("price_per_night_eur"),
        "personal_notes": seed.get("personal_notes"),
        "decision": seed["decision"],
        "investigated_at": seed.get("investigated_at"),
        "raw_json": json.dumps(seed.get("raw"), ensure_ascii=False) if seed.get("raw") else None,
        "imported_at": now,
    }

    row = conn.execute(
        "SELECT id FROM seeds WHERE source = ? AND name = ?",
        (payload["source"], payload["name"]),
    ).fetchone()
    is_new = row is None

    if is_new:
        cols = ", ".join(payload.keys())
        placeholders = ", ".join(f":{k}" for k in payload.keys())
        conn.execute(
            f"INSERT INTO seeds ({cols}) VALUES ({placeholders})", payload
        )
    else:
        set_clause = ", ".join(
            f"{k} = :{k}" for k in payload.keys() if k not in ("source", "name")
        )
        conn.execute(
            f"UPDATE seeds SET {set_clause} WHERE source = :source AND name = :name",
            payload,
        )

    return is_new


def start_run(conn: sqlite3.Connection, portal: str) -> int:
    """Registra inicio de una ejecucion. Devuelve el run_id."""
    cur = conn.execute(
        "INSERT INTO scrape_runs (portal, started_at, status) VALUES (?, ?, 'running')",
        (portal, _now_iso()),
    )
    return cur.lastrowid


def finish_run(
    conn: sqlite3.Connection,
    run_id: int,
    listings_found: int,
    status: str = "ok",
    error: str | None = None,
) -> None:
    """Cierra la ejecucion con status final."""
    conn.execute(
        "UPDATE scrape_runs SET finished_at = ?, status = ?, "
        "listings_found = ?, error = ? WHERE id = ?",
        (_now_iso(), status, listings_found, error, run_id),
    )


def count_listings(conn: sqlite3.Connection, portal: str | None = None) -> int:
    """Util para tests rapidos."""
    if portal:
        row = conn.execute(
            "SELECT COUNT(*) FROM listings WHERE portal = ?", (portal,)
        ).fetchone()
    else:
        row = conn.execute("SELECT COUNT(*) FROM listings").fetchone()
    return row[0]


def count_seeds(conn: sqlite3.Connection, source: str | None = None) -> int:
    """Util para tests rapidos."""
    if source:
        row = conn.execute(
            "SELECT COUNT(*) FROM seeds WHERE source = ?", (source,)
        ).fetchone()
    else:
        row = conn.execute("SELECT COUNT(*) FROM seeds").fetchone()
    return row[0]