# /volume1/docker/casa-finder/HANDOFF.md

_Ultima actualizacion: 2026-07-01 (cierre de sesion 4)_

## Objetivo

Montar web publica `gav.ruizespana.com` que busque casas de vacaciones grupales (~25 pax) en Espana y sur de Francia. La familia GAV ("Aventura del Verano · Familia Espana & Co") hace un viaje anual desde 2020; en 2026 ya esta elegida **Masia Escrigas (Barcelona)**, asi que la web es para futuros viajes (GAV27+), sin presion de plazo.

## Completado en sesion 4 (2026-07-01) — Paso 3: API FastAPI (commit `e75f146`)

### Funciones de consulta en `scraper/store.py`

Toda la logica SQL vive junto al resto de la capa de persistencia (no en la API):
- `list_listings(conn, *, min_capacity=20, max_capacity=None, region=None, country=None, portal=None, max_price_per_night=None, limit=50, offset=0)`
- `count_listings_filtered(...)` — mismos filtros, para el `total` de paginacion.
- `get_listing(conn, key)` — una casa por `cache_key` ("portal:portal_listing_id").
- `list_seeds(conn, *, source=None, decision=None, min_capacity=None, limit=200, offset=0)`
- `count_seeds_filtered(...)`
- Helpers privados `_listings_where` / `_seeds_where` para no duplicar la logica de filtros entre `list_*` y `count_*_filtered`.

### `api/` (nuevo modulo)

- `api/main.py` — FastAPI, capa HTTP fina. Endpoints:
  - `GET /health` — counts de listings/seeds.
  - `GET /listings` — filtros `min_capacity` (default 20), `max_capacity`, `region` (LIKE parcial), `country`, `portal`, `max_price_per_night`; paginacion `limit`/`offset` con `total` real.
  - `GET /listings/{portal}/{portal_listing_id:path}` — detalle de una casa. **Nota el `:path`** (ver bug abajo).
  - `GET /seeds` — filtros `source`, `decision`, `min_capacity`.
  - CORS abierto (`allow_origins=["*"]`), sin autenticacion (API publica de solo lectura).
- `api/requirements.txt` — solo `fastapi`, `uvicorn[standard]`, `pydantic` (NO httpx/bs4/lxml — la API nunca scrapea).
- `api/Dockerfile` — copia solo `scraper/__init__.py`, `models.py`, `store.py` del scraper (reusa la logica sin arrastrar sus deps de scraping). `PYTHONPATH=/app`, `CMD python -m uvicorn api.main:app --host 0.0.0.0 --port 8000`.
- `docker-compose.yml` — nuevo servicio `api`: puerto **8401:8000**, `network_mode: bridge` (mismo motivo que `scraper`), `restart: unless-stopped`, monta `./data:/app/data`.

### Bug real encontrado y corregido durante las pruebas

**Ruta de detalle con 404 generico**: `/listings/{portal}/{portal_listing_id}` devolvia `{"detail":"Not Found"}` (404 de FastAPI, no el nuestro) al probar con un listing real (`escapadarural/lleida/la-neneta`). Causa: `portal_listing_id` de escapadarural tiene formato `"provincia/slug"` (con `/` dentro), y la ruta con parametro simple `{portal_listing_id}` solo matchea un segmento sin `/`. Fix: conversor `{portal_listing_id:path}`, que permite `/` dentro del parametro. Verificado despues: detalle real -> 200 OK; ID inexistente -> 404 con mensaje propio (`"listing 'escapadarural:no-existe' no encontrado"`).

### Verificacion end-to-end (contra la DB real: 9 listings, 31 seeds)

```
curl http://192.168.1.205:8401/health
  -> {"status":"ok","listings_count":9,"seeds_count":31}

curl 'http://192.168.1.205:8401/listings?region=catalu&limit=3'
  -> total:9, 3 items con todos los campos (image_urls, amenities, raw parseados desde JSON)

curl 'http://192.168.1.205:8401/listings/escapadarural/lleida/la-neneta'
  -> 200 OK, listing completo

curl 'http://192.168.1.205:8401/listings/escapadarural/no-existe'
  -> 404 {"detail":"listing 'escapadarural:no-existe' no encontrado"}

curl 'http://192.168.1.205:8401/seeds?decision=chosen'
  -> total:1, Mas Huix (coincide con lo esperado: GAV24 chosen)
```

### Gotcha operativo nuevo: `nas_run_command` no corre en el host, corre dentro del contenedor `nas-mcp`

`curl http://localhost:8401/...` desde `nas_run_command` da **"Connection refused"** aunque `docker ps` muestre el puerto publicado correctamente (`0.0.0.0:8401->8000/tcp`). Motivo: las sesiones de `nas_run_command` se ejecutan dentro del propio contenedor `nas-mcp`, no en el host Synology directo — `localhost` ahi es el contenedor `nas-mcp`, no el host que publica el puerto de otro contenedor. **Fix: usar la IP LAN real del NAS** (`192.168.1.205`, la misma que ya usa el README del proyecto) en vez de `localhost` para probar servicios expuestos por otros contenedores.

### Gotcha operativo: el NAS esta compartido con otras sesiones/agentes

Durante esta sesion se observo un job de otra automatizacion (`n8n-mcp`) corriendo en paralelo, y en un momento un resultado de `nas_run_command` parecio devolver el stdout de un comando distinto al que se habia enviado (salida sobre `n8n.ruizespana.com` en vez de `docker images`). **Mitigacion aplicada**: envolver comandos ambiguos con marcadores `echo MARKER_X ... echo MARKER_END` para verificar sin ambiguedad que la salida corresponde al comando enviado. Recomendado seguir haciendolo en comandos cortos que puedan ser ambiguos, especialmente tras timeouts o si hay sospecha de carga compartida en el NAS.

### Gotcha operativo: comandos largos en foreground de `nas_run_command` pueden reportar timeout aunque el proceso siga y termine bien

Confirmado de nuevo esta sesion (build de `docker compose build api` reporto timeout mientras el build seguia en curso server-side y termino con exito). **Patron a seguir**: para comandos que puedan tardar >60-90s (docker build, pip install grandes, etc.), lanzar siempre con `background=True` y sondear con `nas_job_status`; si el job tambien reporta timeout, verificar el resultado real con un comando de estado corto (`docker images`, `docker ps`) en vez de asumir fallo.

## Completado en sesiones anteriores (resumen — detalle completo en el historial de commits y en la memoria del proyecto)

- **Sesion 2 (2026-06-28)**: scraper `escapadarural` completo (httpx+BS4, SQLite 4 tablas, CLI), 31 seeds GAV24 importadas, logos localizados.
- **Sesion 3 (2026-07-01, misma fecha que sesion 4 — dias de trabajo distintos)**: 3 bugs reales corregidos en el scraper (brotli, ascenso de ancestros, tope de paginacion), gotcha de DB path hardcodeado, `docker-compose.yml` minimo para `scraper` con fix de red (`network_mode: bridge`), gotcha de `git push` con credential.helper.

## En curso

Nada bloqueante. API funcionando y expuesta en `192.168.1.205:8401` (contenedor `casa-finder-api-1`, `restart: unless-stopped`, deberia sobrevivir a reinicios del NAS). Todo commiteado y pusheado a `origin/main` (`e75f146`).

## Proximo paso exacto (siguiente sesion)

**Paso 4: Web publica** (carpeta `web/dist/`, vacia todavia) — segun README: Alpine.js (sin build step) + nginx, puerto host **8400**.

1. HTML/JS estatico minimo: tabla o grid de casas, llamando a `GET http://<host>:8401/listings` (o via proxy nginx si se prefiere evitar CORS/exponer el puerto 8401 publicamente — decidir esto primero).
2. Filtros basicos en el UI: capacidad minima, region, precio maximo — mapean 1:1 a los query params ya soportados por la API.
3. Sesgar visualmente hacia Aragon si aparece en los resultados (ver "Aragon es preferencia aspiracional" en memoria del proyecto).
4. `nginx.conf` minimo sirviendo estaticos + `docker-compose.yml`: anadir servicio `web` (puerto 8400:80, mismo patron `network_mode: bridge` salvo que se decida que web SI necesite hablar con `api` por nombre de servicio Docker — en ese caso evaluar una red compartida en vez de bridge para esos dos servicios).
5. Antes de exponer publicamente: decidir si `api` (8401) debe quedar accesible solo en LAN/tunnel interno, o si se expone tal cual — revisar con Jaime antes de tocar Cloudflare Tunnel.
6. Alta en Cloudflare Zero Trust (`cloudflare-maja-2`) para `gav.ruizespana.com` → `http://192.168.1.205:8400` (paso manual documentado en CLAUDE.md del proyecto).

**Antes de disenar el UI, opcional pero recomendado**: poblar `data/casas.db` con mas regiones (`docker compose run --rm scraper python -m scraper.run --only escapadarural --regions <region>`, one a one o todas a la vez) para tener un dataset mas realista con el que probar filtros.

Despues de la web: portales pendientes por prioridad — vrbo.com (anti-bot Akamai), booking.com (MCP conversacional, no pipeline), airbnb.com, clubrural.com/gitedegroupe.fr/somrurals.com/calarquer.com.

## Decisiones tomadas (acumulado)

| Decision | Por que |
|---|---|
| Sin Playwright (YAGNI) | Escapadarural es SSR, basta httpx+BS4. |
| Booking MCP solo conversacional | No para el catalogo persistente. |
| VRBO alta prioridad futura | 5/31 casas GAV24 vinieron de ahi; anti-bot fuerte. |
| Tabla `seeds` separada de `listings` | Sin `portal_listing_id` estable en las seeds; link futuro por similitud nombre+ubicacion. |
| Aragon = preferencia aspiracional | 7 anos de viajes GAV, Aragon nunca aparece; sesgar UI cuando aparezca. |
| Web no urgente | GAV26 ya elegido; la web es para GAV27+. |
| `network_mode: bridge` en scraper y api | El NAS tiene el pool de subredes Docker agotado; ninguno de los dos necesita red propia (scraper: HTTPS saliente; api: solo expone puerto). |
| API sin autenticacion, CORS abierto | Es un dashboard publico de solo lectura, sin datos sensibles. |
| `api/Dockerfile` copia solo models.py+store.py del scraper | Evita arrastrar httpx/bs4/lxml a la imagen de la API, que no los necesita. |

## Problemas y soluciones (acumulado, ver tambien memoria del proyecto para el detalle completo)

| Problema | Solucion |
|---|---|
| `httpx` no decodifica brotli sin el paquete `brotli` -> 0 cards con HTTP 200 | `brotli~=1.2.0` en requirements.txt. |
| Ascenso de 5 ancestros insuficiente en `_extract_list_cards` | Subir `MAX_ANCESTOR_CLIMB` a 9. |
| `?pagina=N` fuera de rango devuelve el mismo HTML que pagina 1, sin fin | Tope duro `MAX_PAGES_PER_REGION = 15`. |
| `DEFAULT_DB_PATH` hardcodeado a `/app/data/casas.db` crea DB fantasma en bare-metal sin `--db` | Pasar `--db data/casas.db` fuera de Docker, o usar `docker compose run`. |
| `docker compose run`/`up` falla por pool de subredes agotado | `network_mode: bridge`. |
| `git push` falla con "could not read Username" pese a `nas_git_auth_status` en verde | `git -c credential.helper='store --file=/volume1/docker/.deploy/.git-credentials' push origin main`. |
| **(sesion 4)** Ruta `/listings/{portal}/{portal_listing_id}` 404 generico | `portal_listing_id` de escapadarural contiene `/` -> usar conversor `{portal_listing_id:path}`. |
| **(sesion 4)** `curl localhost:PUERTO` desde `nas_run_command` da "Connection refused" pese a que el puerto esta publicado | `nas_run_command` corre dentro del contenedor `nas-mcp`, no en el host -> usar la IP LAN real (`192.168.1.205`) en vez de `localhost`. |
| **(sesion 4)** Un resultado de `nas_run_command` parecio devolver la salida de otro comando (NAS compartido con otras automatizaciones/sesiones) | Envolver comandos con marcadores `echo MARKER_X ... echo MARKER_END` para verificar sin ambiguedad la correspondencia comando->salida. |

## Lecciones nuevas (para futuras sesiones)

- Ante un fallo silencioso (0 resultados, sin excepcion), diagnosticar en capas: 1) respuesta HTTP cruda, 2) comparar con lo que espera el codigo, 3) reproducir paso a paso en el interprete real. Evita "arreglar a ciegas".
- Un sitio que no valida parametros de paginacion puede convertir un bug de filtrado en un bucle sin techo aparente — los bucles de paginacion necesitan SIEMPRE un tope duro.
- En rutas FastAPI/Starlette, si un segmento de path puede contener `/` (ej IDs compuestos tipo "categoria/slug"), usar el conversor `{param:path}` desde el principio — no asumir que un ID nunca tendra `/`.
- En este NAS: `nas_run_command` ejecuta dentro de un contenedor (`nas-mcp`), no en el host — para probar servicios de OTROS contenedores usar la IP LAN del NAS, nunca `localhost`.
- En este NAS: `nas_git_auth_status` en verde no garantiza que `git push` funcione desde `nas_run_command` — pasar el `credential.helper` explicito en el comando.
- Comandos largos (docker build, etc.) pueden superar el timeout de `nas_run_command` incluso cuando el proceso termina bien server-side — usar `background=True` + `nas_job_status`, y verificar con un comando corto si hay dudas.
- El NAS puede estar compartido con otras automatizaciones al mismo tiempo (visto: jobs de `n8n-mcp` corriendo en paralelo) — en comandos cortos ambiguos, usar marcadores `echo MARKER...` para confirmar que la salida corresponde al comando enviado.

## Pendientes operativos (para arrancar la proxima sesion)

- [ ] Leer este HANDOFF y CLAUDE.md del proyecto.
- [ ] Verificar que `casa-finder-api-1` sigue arriba: `docker ps --filter name=casa-finder` (usar IP LAN, no localhost, para probar `curl http://192.168.1.205:8401/health`).
- [ ] Empezar por paso 4: web Alpine.js + nginx (ver "Proximo paso exacto" arriba).
- [ ] (Opcional) Poblar `data/casas.db` con mas regiones antes de disenar el UI.
- [ ] (Opcional) Bajar `image0.png` (logo Hokusai) cuando user lo apruebe.

## Estado actual del repo

```
/volume1/docker/casa-finder/
├── .gitignore
├── CLAUDE.md
├── HANDOFF.md                           (este archivo)
├── README.md
├── docker-compose.yml                   (scraper + api)
├── scraper/
│   ├── Dockerfile
│   ├── requirements.txt                 (+ brotli)
│   ├── __init__.py
│   ├── models.py
│   ├── store.py                         (+ funciones de consulta, sesion 4)
│   ├── run.py
│   ├── seeds_import.py
│   └── portals/
│       ├── __init__.py
│       ├── base.py
│       └── escapadarural.py             (fix ancestros + tope paginas)
├── api/                                 (NUEVO sesion 4)
│   ├── __init__.py
│   ├── main.py
│   ├── requirements.txt
│   └── Dockerfile
├── web/dist/                            (carpeta vacia — paso 4, siguiente)
└── data/                                (gitignored)
    ├── casas.db                         (31 seeds + 9 listings escapadarural/cataluna)
    └── raw/
        └── gav24.csv
```

Adicionalmente en el PC del user:
```
C:\Cowork\IA-local-NAS\casa-finder-design-assets\logos\
└── image1.png                          (logo 2: historico viajes GAV)
```

## Servicios corriendo ahora mismo en el NAS

| Contenedor | Puerto | Estado |
|---|---|---|
| `casa-finder-api-1` | `192.168.1.205:8401` -> 8000 | Up, `restart: unless-stopped` |

(`scraper` no queda corriendo — es un CLI de un solo uso via `docker compose run --rm scraper`.)

## Commits de esta sesion (sesion 4)

- `e75f146` — feat(api): paso 3 -- API FastAPI de solo lectura sobre casas.db.

Pusheado a `origin/main`.