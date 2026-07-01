"""
casa-finder — API FastAPI (paso 3).

Capa HTTP fina de solo lectura sobre `data/casas.db`. Toda la logica SQL
vive en `scraper/store.py` (list_listings, get_listing, list_seeds, etc.) —
este modulo solo valida parametros de query, llama a esas funciones y
serializa filas de sqlite3.Row a JSON.

Decisiones:
- Sin autenticacion: es una API publica de solo lectura, sin datos
  sensibles (igual que el dashboard web al que sirve).
- CORS abierto (allow_origins=["*"]): el futuro frontend Alpine.js puede
  llamar desde cualquier origen mientras no tengamos dominio fijo definido.
- No escribe nunca en la DB — el scraper es el unico escritor. Si en el
  futuro hace falta un endpoint de escritura (ej marcar "favorito"),
  anadir entonces con su propia validacion.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from scraper.store import (
    count_listings,
    count_listings_filtered,
    count_seeds,
    count_seeds_filtered,
    get_listing,
    list_listings,
    list_seeds,
    session,
)

app = FastAPI(
    title="casa-finder API",
    description="Busqueda de casas de vacaciones para grupos grandes (~25 pax).",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


# ---------- modelos de respuesta ----------

class ListingOut(BaseModel):
    key: str
    portal: str
    portal_listing_id: str
    url: str
    name: str
    location: str
    region: str | None
    country: str
    capacity_min: int | None
    capacity_max: int
    bedrooms: int | None
    bathrooms: int | None
    price_per_night: float | None
    price_per_stay: float | None
    price_currency: str
    price_context: str | None
    main_image_url: str | None
    image_urls: list[str]
    amenities: list[str]
    description: str | None
    raw: dict | None
    first_seen_at: str
    last_seen_at: str


class ListingsPage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[ListingOut]


class SeedOut(BaseModel):
    id: int
    source: str
    name: str
    url_original: str | None
    location: str | None
    country: str | None
    capacity_pax: int | None
    bedrooms_or_rooms: str | None
    has_pool: bool | None
    price_total_eur: float | None
    stay_nights: int | None
    price_per_night_eur: float | None
    personal_notes: str | None
    decision: str
    investigated_at: str | None
    imported_at: str


class SeedsPage(BaseModel):
    total: int
    items: list[SeedOut]


class HealthOut(BaseModel):
    status: Literal["ok"]
    listings_count: int
    seeds_count: int


# ---------- helpers de serializacion ----------

def _row_to_listing(row: sqlite3.Row) -> ListingOut:
    d: dict[str, Any] = dict(row)
    return ListingOut(
        key=d["key"],
        portal=d["portal"],
        portal_listing_id=d["portal_listing_id"],
        url=d["url"],
        name=d["name"],
        location=d["location"],
        region=d["region"],
        country=d["country"],
        capacity_min=d["capacity_min"],
        capacity_max=d["capacity_max"],
        bedrooms=d["bedrooms"],
        bathrooms=d["bathrooms"],
        price_per_night=d["price_per_night"],
        price_per_stay=d["price_per_stay"],
        price_currency=d["price_currency"],
        price_context=d["price_context"],
        main_image_url=d["main_image_url"],
        image_urls=json.loads(d["image_urls_json"] or "[]"),
        amenities=json.loads(d["amenities_json"] or "[]"),
        description=d["description"],
        raw=json.loads(d["raw_json"]) if d["raw_json"] else None,
        first_seen_at=d["first_seen_at"],
        last_seen_at=d["last_seen_at"],
    )


def _row_to_seed(row: sqlite3.Row) -> SeedOut:
    d: dict[str, Any] = dict(row)
    return SeedOut(
        id=d["id"],
        source=d["source"],
        name=d["name"],
        url_original=d["url_original"],
        location=d["location"],
        country=d["country"],
        capacity_pax=d["capacity_pax"],
        bedrooms_or_rooms=d["bedrooms_or_rooms"],
        has_pool=bool(d["has_pool"]) if d["has_pool"] is not None else None,
        price_total_eur=d["price_total_eur"],
        stay_nights=d["stay_nights"],
        price_per_night_eur=d["price_per_night_eur"],
        personal_notes=d["personal_notes"],
        decision=d["decision"],
        investigated_at=d["investigated_at"],
        imported_at=d["imported_at"],
    )


# ---------- endpoints ----------

@app.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    with session() as conn:
        return HealthOut(
            status="ok",
            listings_count=count_listings(conn),
            seeds_count=count_seeds(conn),
        )


@app.get("/listings", response_model=ListingsPage)
def get_listings(
    min_capacity: int | None = Query(default=20, ge=1, description="Plazas minimas"),
    max_capacity: int | None = Query(default=None, ge=1),
    region: str | None = Query(default=None, description="Coincidencia parcial, ej 'catalu'"),
    country: str | None = Query(default=None, description="Codigo ISO, ej 'ES'"),
    portal: str | None = Query(default=None, description="Filtrar por portal de origen"),
    max_price_per_night: float | None = Query(default=None, gt=0),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ListingsPage:
    with session() as conn:
        rows = list_listings(
            conn,
            min_capacity=min_capacity,
            max_capacity=max_capacity,
            region=region,
            country=country,
            portal=portal,
            max_price_per_night=max_price_per_night,
            limit=limit,
            offset=offset,
        )
        total = count_listings_filtered(
            conn,
            min_capacity=min_capacity,
            max_capacity=max_capacity,
            region=region,
            country=country,
            portal=portal,
            max_price_per_night=max_price_per_night,
        )
    return ListingsPage(
        total=total,
        limit=limit,
        offset=offset,
        items=[_row_to_listing(r) for r in rows],
    )


@app.get("/listings/{portal}/{portal_listing_id:path}", response_model=ListingOut)
def get_listing_detail(portal: str, portal_listing_id: str) -> ListingOut:
    # portal_listing_id puede contener '/'  (ej escapadarural: provincia/slug),
    # de ahi el conversor :path en la ruta -- sin el, la ruta devolvia 404 generico
    # (detectado al probar contra un listing real, 2026-07-01).
    key = f"{portal}:{portal_listing_id}"
    with session() as conn:
        row = get_listing(conn, key)
    if row is None:
        raise HTTPException(status_code=404, detail=f"listing '{key}' no encontrado")
    return _row_to_listing(row)


@app.get("/seeds", response_model=SeedsPage)
def get_seeds(
    source: str | None = Query(default=None, description="ej 'gav24'"),
    decision: str | None = Query(
        default=None, description="chosen | ruled-out | pending | unknown"
    ),
    min_capacity: int | None = Query(default=None, ge=1),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> SeedsPage:
    with session() as conn:
        rows = list_seeds(
            conn,
            source=source,
            decision=decision,
            min_capacity=min_capacity,
            limit=limit,
            offset=offset,
        )
        total = count_seeds_filtered(
            conn, source=source, decision=decision, min_capacity=min_capacity
        )
    return SeedsPage(total=total, items=[_row_to_seed(r) for r in rows])