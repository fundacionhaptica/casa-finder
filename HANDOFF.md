# HANDOFF — casa-finder

_Ultima actualizacion: 2026-06-28 (cierre de sesion 2)_

## Objetivo

Montar web publica `gav.ruizespana.com` que busque casas de vacaciones grupales (~25 pax) en Espana y sur de Francia. La familia GAV ("Aventura del Verano · Familia Espana & Co") hace un viaje anual desde 2020; en 2026 ya esta elegida **Masia Escrigas (Barcelona)**, asi que la web es para futuros viajes (GAV27+), sin presion de plazo.

## Completado en esta sesion (sesion 2, 2026-06-28)

### Scraper escapadarural
- [x] **`scraper/Dockerfile`** — Python 3.11-slim, sin Playwright (decision YAGNI). httpx+BS4 puro.
- [x] **`scraper/requirements.txt`** — httpx, beautifulsoup4, lxml, pydantic, python-dateutil.
- [x] **`scraper/models.py`** — Pydantic v2: `SearchQuery`, `Listing`.
- [x] **`scraper/store.py`** — SQLite con 4 tablas: `listings`, `prices`, `scrape_runs`, `seeds`. WAL mode. Funciones: `upsert_listing`, `upsert_seed`, `start_run`, `finish_run`, `count_*`.
- [x] **`scraper/portals/base.py`** — clase abstracta `BasePortal` con helper `_http_client()` (UA realista, locale es-ES).
- [x] **`scraper/portals/escapadarural.py`** — scraper SSR del portal:
  - URL pattern `/casas-rurales-grupos-{region}` por defecto (filtra ya por grupos grandes).
  - Paginacion `?pagina=N` hasta 2 paginas vacias seguidas o agotar limit.
  - Filtro temprano por `capacity_max >= min_capacity` antes de pegar a fichas.
  - Solo entra a ficha de listings que pasan el filtro: extrae coordenadas GPS, amenities, imagenes, descripcion.
  - `request_delay_s = 1.0` entre requests.
  - Tolerancia a fallos: try/except por region/card/ficha. Loggea y sigue.
  - `portal_listing_id = "provincia/slug"`. ID numerico interno en `raw`.
- [x] **`scraper/run.py`** — CLI con `--only`, `--limit`, `--regions`, `--min-capacity`, `--max-capacity`, `--dry-run`, `--verbose`. Registry de portales. Aislamiento por portal.

### Integracion seeds (GAV24)
- [x] Descargado CSV del Google Sheets "GAV24-26 al 30 de Junio" → `data/raw/gav24.csv`.
- [x] Nueva tabla `seeds` en SQLite con metadatos cualitativos (notas, decision).
- [x] **`scraper/seeds_import.py`** — parser tolerante con fixes para CSV de Google Sheets (filas truncadas, separadores ES, dedup duplicados, deteccion de pais/decision).
- [x] Import ejecutado: **31 seeds** importadas (29 ruled-out, 1 chosen=Mas Huix, 1 pending=Bonastre). 25 ES, 6 FR.

### Logos del proyecto (descubrimiento clave)
- [x] Localizados en Gmail (thread "Camisetas GAV", 19/03/2026).
- [x] **Logo 1**: sello "Aventura del Verano · Familia Espana & Co 2026" con la gran ola de Hokusai. Paleta: azul navy + azul oceano.
- [x] **Logo 2**: historico cronologico de viajes GAV 2020-2026 (Sotogrande, Roda de Bara, Puerto Serrano, Jimena de la Frontera, Mas Huix, Ascain, Masia Escrigas).
- [x] `image1.png` (logo 2) descargado y movido a `C:\Cowork\IA-local-NAS\casa-finder-design-assets\logos\`.
- [ ] `image0.png` (logo 1, Hokusai) pendiente: dialog "Guardar como" de Chrome lo interceptó, requiere confirmacion manual del user.

### Housekeeping
- [x] Puertos 8400/8401 reservados en `/volume1/docker/PUERTOS.md`.
- [x] `vision-ollama` parado (libera ~3 GB RAM mientras desarrollamos el scraper).

## En curso

_Nada bloqueante. Sesion cerrada limpiamente. CSV de seeds importado, scraper listo para test e2e._

## Proximo paso exacto (siguiente sesion)

**Test end-to-end + commit del paso 2:**

1. **Dry-run** del scraper para validar el flujo HTTP+parse sin tocar SQLite:
   ```bash
   cd /volume1/docker/casa-finder
   python3 -m scraper.run --only escapadarural --limit 5 --regions cataluna --dry-run
   ```
   Criterio OK: trae ≥5 listings con `name`, `capacity_max≥20`, `price_per_night`.

2. **Run real** (sin --dry-run) y verificar en SQLite:
   ```bash
   python3 -m scraper.run --only escapadarural --limit 10 --regions cataluna
   sqlite3 data/casas.db 'SELECT COUNT(*) FROM listings;'
   sqlite3 data/casas.db 'SELECT name, capacity_max, price_per_night FROM listings LIMIT 5;'
   sqlite3 data/casas.db 'SELECT * FROM scrape_runs ORDER BY id DESC LIMIT 3;'
   ```
   Criterio OK: ≥5 listings en `listings`, scrape_runs con status='ok'.

3. **docker-compose minimo** (opcional pero recomendado para cron):
   - `docker-compose.yml` con servicio `scraper` (build context root + dockerfile scraper/Dockerfile, mount `./data:/app/data`).
   - Probar: `docker compose run --rm scraper python -m scraper.run --only escapadarural --limit 5 --dry-run`.

4. **Commit + push paso 2 completo** (siguiendo regla CLAUDE.md):
   - Listar archivos modificados.
   - Commit message propuesto.
   - Confirmacion explicita del user.
   - Push via NAS auth.

5. **Bajar `image0.png`** (logo Hokusai) cuando el user confirme el dialog Chrome. Mover a `casa-finder-design-assets/logos/`.

Despues del paso 2: **paso 3 = API FastAPI** (lee SQLite, expone JSON con filtros).

## Decisiones tomadas en sesion 2

| Decision | Por que |
|---|---|
| **Sin Playwright (YAGNI)** | Escapadarural es SSR, basta httpx+BS4. Ahorra ~2 GB de imagen Docker y velocidad. Si un portal futuro requiere JS, se anade entonces. |
| **Booking MCP solo conversacional** | El MCP de Booking solo se invoca desde Claude (Cowork), no desde cron Python. Util ad-hoc ("comprueba disponibilidad para 15-18 julio") pero NO para el catalogo persistente. Para integrarlo al pipeline habria que usar API REST de Booking directamente. |
| **VRBO portal alta prioridad futuro** | 5 de las 31 casas del Excel GAV24 vinieron de VRBO. Tiene anti-bot fuerte (Akamai), puede requerir reintroducir Playwright o sesiones httpx con cabeceras. |
| **Tabla `seeds` separada de `listings`** | Las seeds no tienen `portal_listing_id` estable. Link futuro por similitud nombre+ubicacion en la capa API. |
| **Aragon es preferencia aspiracional, no historica** | El logo 2 revela 7 anos de viajes GAV y Aragon NUNCA aparece. La preferencia del user es real, pero hay que buscar mas activamente. |
| **Web NO urgente** | GAV26 ya elegido (Masia Escrigas). La web es para GAV27+, sin plazo. |

## Problemas y soluciones (sesion 2)

| Problema | Solucion |
|---|---|
| `type` de computer-use usa clipboard fast path → sobrescribe el `Ctrl+X` previo | Para mover archivos en Windows: usar comando `cmd /c move` desde la barra de direcciones de File Explorer (no requiere clipboard). |
| Gmail thread no muestra todos los mensajes al cargar por threadId | Usar `#search/subject:"Camisetas GAV"` para ver lista expandida con mensajes individuales. |
| MCP de Gmail NO tiene tool de download attachment | Solo `search_threads` y `get_thread`. Para bajar adjuntos: Chrome MCP o user manual. |
| `_extract_comments` fallaba para filas truncadas de CSV (Sheets recorta trailing vacios) | Llamarlo ANTES del fill a 14 cols (en parse_row_by_index). |
| Regex de precio `\d{1,3}(?:[.\s]\d{3})*` matcheaba `4256` como `425` (perdiendo el 6) | Cambiar `*` por `+` para que esa alternativa exija al menos 1 grupo de miles real. |
| Duplicado real "Casanova" en CSV (dos casas distintas con mismo nombre) | Renombrar la segunda a `Casanova (2)` en `_dedup_names()` antes de upsert. |
| pip3 install pydantic falla sin --break-system-packages | Usar `pip3 install --break-system-packages` en el NAS Synology DSM 7+. |

## Lecciones nuevas (para futuras sesiones)

- **CSV de Google Sheets recorta trailing empty cells**. Cualquier parser que dependa del index `len(row)` fijo debe tolerar esto.
- **Precios espanoles**: comas son decimales, puntos son miles. La regex debe distinguir: si no hay separador (`4256`), tratar como entero puro; si hay puntos sin comas (`3.661`), miles; si hay comas (`3.430,00`), decimal.
- **Computer-use en Windows**: el `type` con `clipboardWrite` no concedido aun usa internamente el clipboard. Para operaciones cut/paste, NUNCA `type` entre el cut y el paste; usar clicks en sidebar/breadcrumbs o el truco `cmd /c move` en barra de direcciones.
- **MCPs vs cron**: los MCPs son herramientas del agente Claude, NO librerias que un script Python en cron pueda llamar. Para integrar un servicio a un pipeline persistente, hay que usar su API REST o SDK directamente.
- **Gmail MCP no tiene download attachment**. Para descargar imagenes/adjuntos hay que ir via Chrome MCP o pedir descarga manual.

## Pendientes operativos (para arrancar la proxima sesion)

- [ ] Leer este HANDOFF y CLAUDE.md del proyecto.
- [ ] Verificar Python deps en NAS: `python3 -c 'import httpx, bs4, lxml, pydantic'`.
- [ ] Comprobar que `data/casas.db` y `data/raw/gav24.csv` siguen ahi.
- [ ] **Empezar por dry-run del scraper escapadarural** (comando arriba).
- [ ] Si dry-run OK → run real → SQL verify → commit/push.
- [ ] (Opcional) Bajar `image0.png` (logo Hokusai) cuando user lo apruebe.

## Estado actual del repo

```
/volume1/docker/casa-finder/
├── .gitignore                          (versionado)
├── CLAUDE.md                           (versionado)
├── HANDOFF.md                          (versionado, este archivo)
├── README.md                           (versionado)
├── scraper/                            (NUEVO en sesion 2)
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── __init__.py
│   ├── models.py                       (Pydantic v2: SearchQuery, Listing)
│   ├── store.py                        (SQLite: 4 tablas + helpers)
│   ├── run.py                          (CLI entry point)
│   ├── seeds_import.py                 (importador CSV → tabla seeds)
│   └── portals/
│       ├── __init__.py
│       ├── base.py                     (BasePortal abstracto)
│       └── escapadarural.py            (scraper completo)
├── api/                                (carpeta vacia — paso 3)
├── web/dist/                           (carpeta vacia — paso 4)
└── data/                               (gitignored)
    ├── casas.db                        (31 seeds, 0 listings todavia)
    └── raw/
        └── gav24.csv                   (backup del Sheet)
```

Adicionalmente en el PC del user:
```
C:\Cowork\IA-local-NAS\casa-finder-design-assets\logos\
└── image1.png                          (logo 2: historico viajes GAV)
```