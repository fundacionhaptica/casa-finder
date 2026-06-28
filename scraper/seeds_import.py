"""
casa-finder — importador de seeds desde el CSV de GAV24 (Excel familiar).

El Excel original (Google Sheets 'GAV24-26 al 30 de Junio') tiene 31 casas
investigadas para las vacaciones del 26-30 junio 2024. Estancia = 4 noches.
Casa elegida = Mas Huix. El resto fueron descartadas.

Cabecera del CSV exportado (14 columnas):
    URL, Imagen, [columna vacia], Habitaciones, Personas, Precio/noche,
    Piscina, Disponibilidad, Precio total, Ubicacion, Desde Zaragoza,
    Desde Madrid, desde Pamplona, COMENTARIOS

Basura conocida:
- Celdas con 'Quota exceeded. Please upgrade your plan: Extensions...'
  (de un plugin de GPT del Sheets que se quedo sin cuota). Las tratamos como None.
- Fila 'susana' al final (1 unica celda con texto, sin URL ni datos). Skip.
- Filas sin name y sin url. Skip.
- Google Sheets exporta CSV recortando trailing empty cells, asi que algunas
  filas tienen 13 cols en lugar de 14. Para esas, los comentarios viven en la
  ultima columna (no necesariamente row[13]).
- Dos casas se llaman 'Casanova' (duplicado real, distintas localizaciones).
  Para no romper UNIQUE(source, name), la segunda se renombra a 'Casanova (2)'.

Uso:
    docker compose run --rm scraper python -m scraper.seeds_import \\
        --csv /app/data/raw/gav24.csv \\
        --source gav24 \\
        --stay-nights 4 \\
        --investigated-at 2024-01

Idempotente: re-ejecutar actualiza filas existentes (clave: source + name).
"""

from __future__ import annotations

import argparse
import csv
import logging
import re
import sys
from pathlib import Path
from typing import Any

from .store import DEFAULT_DB_PATH, session, upsert_seed

log = logging.getLogger("seeds_import")

QUOTA_NOISE = "Quota exceeded"

# Patrones de pais por palabra clave en location/name.
FR_HINTS = (
    "francia", "france", "(fr)", "saint-jean-de-luz", "saint jean de luz",
    "ondarreta", "azur", "biarritz", "lit et mixe", "souraide", "ascarat",
    "pyrénées", "pyrenees", "aquitania", "aquitaine",
)

# Casas marcadas explicitamente.
CHOSEN_NAMES = ("mas huix",)            # GAV24 = Mas Huix
PENDING_HINTS = ("pendiente de respuesta",)

# Parsers
INT_RE = re.compile(r"(\d+)")
# Precios espanoles: '3.661 €', '3.430,00 €', '4256', '3.730,67 €'
# La alternativa A requiere al menos 1 grupo de miles (`+`, no `*`), si no
# '4256' matcheaba como '425'.
PRICE_RE = re.compile(r"(\d{1,3}(?:[.\s]\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)\s*€?")


def _clean(value: str | None) -> str | None:
    """Limpia ruido y normaliza vacios."""
    if value is None:
        return None
    # Normaliza saltos de linea + multiples espacios a un espacio.
    v = re.sub(r"\s+", " ", value).strip()
    if not v:
        return None
    if QUOTA_NOISE in v:
        return None
    return v


def _parse_int(value: str | None) -> int | None:
    """Extrae el primer int del string. None si no hay."""
    v = _clean(value)
    if not v:
        return None
    m = INT_RE.search(v)
    return int(m.group(1)) if m else None


def _parse_price(value: str | None) -> float | None:
    """Convierte '3.430,00 €' → 3430.00. '4256' → 4256.0. '3.964 €' → 3964.0."""
    v = _clean(value)
    if not v:
        return None
    m = PRICE_RE.search(v)
    if not m:
        return None
    raw = m.group(1).strip()
    if "," in raw:
        # '3.430,00' o '697,5' → quitar puntos miles, coma decimal
        raw = raw.replace(".", "").replace(",", ".")
    else:
        # Solo digitos + posibles puntos como miles. La regex A ya garantiza
        # que aqui hay puntos solo si son separadores de miles.
        raw = raw.replace(".", "")
    try:
        return float(raw)
    except ValueError:
        return None


def _parse_pool(value: str | None) -> int | None:
    """Si la celda contiene 'si'/'sí'/'x' → 1. Si 'no' → 0. Vacio → None."""
    v = _clean(value)
    if not v:
        return None
    low = v.lower()
    if low.startswith("no"):
        return 0
    if low.startswith("si") or low.startswith("sí"):
        return 1
    if low == "x":
        return 1
    return None


def _detect_country(location: str | None, name: str | None) -> str:
    """Devuelve 'FR' si alguna senal de Francia, sino 'ES'."""
    blob = " ".join(filter(None, [location, name])).lower()
    if any(h in blob for h in FR_HINTS):
        return "FR"
    return "ES"


def _decide(name: str, comments: str | None) -> str:
    """Marca la decision basandose en pistas conocidas."""
    low_name = name.lower()
    if any(c in low_name for c in CHOSEN_NAMES):
        return "chosen"
    low_comments = (comments or "").lower()
    if any(h in low_comments for h in PENDING_HINTS):
        return "pending"
    return "ruled-out"


# Mapeo por posicion. La cabecera tiene 14 cols, pero Sheets recorta trailing
# vacios al exportar CSV, asi que algunas filas tienen <14 cols.
#  0=URL, 1=Imagen, 2=Nombre, 3=Habitaciones, 4=Personas, 5=Precio/noche,
#  6=Piscina, 7=Disponibilidad, 8=Precio total, 9=Ubicacion,
#  10=Desde Zaragoza, 11=Desde Madrid, 12=desde Pamplona, 13=COMENTARIOS
COL_URL, COL_IMAGEN, COL_NAME = 0, 1, 2
COL_HAB, COL_PAX, COL_PRICE_NIGHT = 3, 4, 5
COL_POOL, COL_AVAIL, COL_TOTAL = 6, 7, 8
COL_LOCATION = 9
COL_DIST_START = 10  # 10,11,12 son distancias
COL_COMMENTS = 13


def _extract_comments(row: list[str]) -> str | None:
    """Devuelve la columna COMENTARIOS, tolerando filas truncadas.

    Si la fila tiene 14 cols, comments = row[13].
    Si tiene <14 cols, los comentarios pueden estar desplazados: tomamos la
    ultima columna no vacia (que no sea distancia/Quota) como candidato.
    """
    if len(row) >= 14:
        return _clean(row[COL_COMMENTS])
    # Fila truncada — la ultima col no vacia, si no parece distancia, es comments.
    for i in range(len(row) - 1, COL_LOCATION, -1):
        candidate = _clean(row[i])
        if not candidate:
            continue
        # Las distancias suelen contener 'h', 'km', 'min', o numero corto.
        # Los comentarios son texto humano. Heuristica conservadora:
        # cualquier celda non-empty post-ubicacion que NO sea solo numero/distancia
        # se considera comentario.
        if re.fullmatch(r"[\d\s,.kmhins ]+", candidate.lower()):
            continue
        return candidate
    return None


def parse_row_by_index(
    row: list[str],
    *,
    source: str,
    stay_nights: int,
    investigated_at: str,
) -> dict[str, Any] | None:
    """Parsea por indice. Devuelve None si la fila es basura."""
    if not row:
        return None

    name = _clean(row[COL_NAME]) if len(row) > COL_NAME else None
    url = _clean(row[COL_URL]) if len(row) > COL_URL else None

    # Skip 'susana' (la fila final del Excel, con solo esa palabra).
    if (name and name.lower() == "susana") or (
        url and url.lower() == "susana"
    ):
        return None
    if not name and not url:
        return None

    # Si solo hay URL, usa el dominio como nombre.
    if not name and url:
        m = re.search(r"https?://(?:www\.)?([^/]+)", url)
        name = m.group(1) if m else url

    # _extract_comments necesita la longitud ORIGINAL para detectar trailing.
    comments = _extract_comments(row)

    # Rellena la fila a 14 cols para acceso seguro a campos intermedios.
    while len(row) < 14:
        row.append("")

    location = _clean(row[COL_LOCATION])
    capacity = _parse_int(row[COL_PAX])
    bedrooms_or_rooms = _clean(row[COL_HAB])
    has_pool = _parse_pool(row[COL_POOL])
    price_total = _parse_price(row[COL_TOTAL])

    country = _detect_country(location, name)
    decision = _decide(name, comments)

    return {
        "source": source,
        "name": name,
        "url_original": url,
        "location": location,
        "country": country,
        "capacity_pax": capacity,
        "bedrooms_or_rooms": bedrooms_or_rooms,
        "has_pool": has_pool,
        "price_total_eur": price_total,
        "stay_nights": stay_nights,
        "price_per_night_eur": None,  # se calcula en upsert_seed
        "personal_notes": comments,
        "decision": decision,
        "investigated_at": investigated_at,
        "raw": {
            "original_row": row,
            "price_per_night_raw": _clean(row[COL_PRICE_NIGHT]),
            "availability_raw": _clean(row[COL_AVAIL]),
        },
    }


def _dedup_names(seeds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Renombra duplicados de name dentro del lote (ej dos 'Casanova').

    La segunda ocurrencia pasa a 'Name (2)', tercera a 'Name (3)', etc.
    Necesario porque UNIQUE(source, name) si no machaca la primera.
    """
    seen: dict[str, int] = {}
    for s in seeds:
        base = s["name"]
        n = seen.get(base, 0) + 1
        seen[base] = n
        if n > 1:
            s["name"] = f"{base} ({n})"
    return seeds


def import_csv(
    csv_path: Path,
    db_path: Path,
    *,
    source: str,
    stay_nights: int,
    investigated_at: str,
    dry_run: bool = False,
) -> dict[str, int]:
    """Lee el CSV, parsea y upsertea en seeds. Devuelve contadores."""
    counters = {"read": 0, "skipped": 0, "new": 0, "updated": 0, "errors": 0}

    if not csv_path.exists():
        raise FileNotFoundError(f"CSV no encontrado: {csv_path}")

    rows_to_apply: list[dict[str, Any]] = []
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        header_skipped = False
        for raw_row in reader:
            counters["read"] += 1
            if not header_skipped:
                header_skipped = True
                if raw_row and raw_row[0].strip().lower() == "url":
                    continue
            try:
                parsed = parse_row_by_index(
                    raw_row,
                    source=source,
                    stay_nights=stay_nights,
                    investigated_at=investigated_at,
                )
            except Exception:
                log.exception("fallo parseando fila: %r", raw_row)
                counters["errors"] += 1
                continue
            if parsed is None:
                counters["skipped"] += 1
                continue
            rows_to_apply.append(parsed)

    # Dedup intra-lote para no romper UNIQUE(source, name).
    rows_to_apply = _dedup_names(rows_to_apply)

    log.info(
        "parsed %d filas (read=%d, skipped=%d, errors=%d)",
        len(rows_to_apply), counters["read"], counters["skipped"], counters["errors"],
    )

    if dry_run:
        log.info("dry-run: NO escribo en SQLite")
        for r in rows_to_apply:
            log.info(
                "  %-35s | pax=%-4s pool=%-4s total=%-8s decision=%s",
                r["name"][:35], r["capacity_pax"], r["has_pool"],
                r["price_total_eur"], r["decision"],
            )
        return counters

    with session(db_path) as conn:
        for r in rows_to_apply:
            try:
                is_new = upsert_seed(conn, r)
                if is_new:
                    counters["new"] += 1
                else:
                    counters["updated"] += 1
            except Exception:
                log.exception("fallo upsert seed %s", r.get("name"))
                counters["errors"] += 1

    return counters


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Import GAV24 CSV → seeds (SQLite)")
    p.add_argument("--csv", required=True, type=Path, help="Path al CSV exportado")
    p.add_argument("--db", default=DEFAULT_DB_PATH, type=Path, help="Path SQLite")
    p.add_argument("--source", default="gav24", help="Etiqueta source (def: gav24)")
    p.add_argument("--stay-nights", type=int, default=4, help="Noches de estancia")
    p.add_argument(
        "--investigated-at", default="2024-01",
        help="ISO date/month en que se hizo la investigacion",
    )
    p.add_argument("--dry-run", action="store_true", help="No escribe en SQLite")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    counters = import_csv(
        args.csv,
        args.db,
        source=args.source,
        stay_nights=args.stay_nights,
        investigated_at=args.investigated_at,
        dry_run=args.dry_run,
    )

    print(
        f"\nResumen:\n"
        f"  filas leidas:   {counters['read']}\n"
        f"  skipped:        {counters['skipped']}\n"
        f"  nuevas:         {counters['new']}\n"
        f"  actualizadas:   {counters['updated']}\n"
        f"  errores:        {counters['errors']}\n"
    )
    return 0 if counters["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())