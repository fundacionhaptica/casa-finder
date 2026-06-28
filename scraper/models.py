"""
casa-finder — modelos de dominio.

Usamos Pydantic v2 (no dataclasses) para validacion automatica y serializacion.
Dos modelos principales:
- SearchQuery: parametros de busqueda que se pasan a cada portal.
- Listing: una casa concreta normalizada (esquema comun a todos los portales).

El precio se guarda en EUR. Si un portal devuelve precio total para una estancia
concreta (ej "3 noches"), se guarda en `price_per_stay` y se anota el contexto
en `price_context`. `price_per_night` solo se rellena si el portal lo expone
de forma fiable o si se puede derivar dividiendo por las noches.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator

CountryCode = Literal["ES", "FR", "PT", "AD"]


class SearchQuery(BaseModel):
    """Parametros de busqueda que recibe cada portal.

    Defaults pensados para el caso de uso de Jaime (~25 pax en Espana).
    """

    min_capacity: int = Field(default=20, ge=1, description="Plazas minimas")
    max_capacity: int | None = Field(default=None, ge=1)
    countries: list[CountryCode] = Field(default_factory=lambda: ["ES"])
    regions: list[str] | None = Field(
        default=None,
        description="Lista libre de regiones a filtrar (ej ['Cataluna', 'Aragon']). "
        "None = sin filtro de region.",
    )
    date_from: date | None = None
    date_to: date | None = None
    max_price_per_night: float | None = Field(default=None, gt=0)
    max_results: int = Field(default=50, ge=1, le=500)

    @model_validator(mode="after")
    def _check_capacity_range(self) -> "SearchQuery":
        if self.max_capacity is not None and self.max_capacity < self.min_capacity:
            raise ValueError("max_capacity debe ser >= min_capacity")
        return self

    @model_validator(mode="after")
    def _check_date_range(self) -> "SearchQuery":
        if self.date_from and self.date_to and self.date_to < self.date_from:
            raise ValueError("date_to debe ser >= date_from")
        return self


class Listing(BaseModel):
    """Una casa normalizada de cualquier portal.

    `portal` + `portal_listing_id` forman la clave natural para upserts.
    """

    # Identidad
    portal: str = Field(description="Slug del portal de origen, ej 'escapadarural'")
    portal_listing_id: str = Field(
        description="ID estable en el portal de origen (para upsert)"
    )
    url: HttpUrl

    # Datos basicos
    name: str
    location: str = Field(description="Texto libre tal como lo da el portal")
    region: str | None = None
    country: CountryCode = "ES"

    # Capacidad
    capacity_min: int | None = Field(default=None, ge=1)
    capacity_max: int = Field(ge=1, description="Plazas maximas — campo critico")
    bedrooms: int | None = Field(default=None, ge=0)
    bathrooms: int | None = Field(default=None, ge=0)

    # Precio (al menos uno de los dos deberia venir)
    price_per_night: float | None = Field(default=None, gt=0)
    price_per_stay: float | None = Field(default=None, gt=0)
    price_currency: str = Field(default="EUR", min_length=3, max_length=3)
    price_context: str | None = Field(
        default=None,
        description="Contexto del precio, ej '3 noches 15-18 julio 2026'",
    )

    # Multimedia
    main_image_url: HttpUrl | None = None
    image_urls: list[HttpUrl] = Field(default_factory=list)

    # Extras
    amenities: list[str] = Field(default_factory=list)
    description: str | None = None

    # Datos brutos por si los necesitamos despues sin re-scrapear
    raw: dict | None = None

    # Metadata
    scraped_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @field_validator("portal")
    @classmethod
    def _portal_slug(cls, v: str) -> str:
        v = v.strip().lower()
        if not v or " " in v:
            raise ValueError("portal debe ser un slug sin espacios, ej 'escapadarural'")
        return v

    @model_validator(mode="after")
    def _at_least_one_price(self) -> "Listing":
        if self.price_per_night is None and self.price_per_stay is None:
            # No bloqueante — hay portales que no muestran precio si no metes fechas.
            # Solo validamos que al menos exista capacidad y URL.
            pass
        return self

    def cache_key(self) -> str:
        """Clave estable para upsert en SQLite."""
        return f"{self.portal}:{self.portal_listing_id}"