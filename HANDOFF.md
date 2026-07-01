# /volume1/docker/casa-finder/HANDOFF.md

_Ultima actualizacion: 2026-07-01 (cierre de sesion 3)_

## Objetivo

Montar web publica `gav.ruizespana.com` que busque casas de vacaciones grupales (~25 pax) en Espana y sur de Francia. La familia GAV ("Aventura del Verano · Familia Espana & Co") hace un viaje anual desde 2020; en 2026 ya esta elegida **Masia Escrigas (Barcelona)**, asi que la web es para futuros viajes (GAV27+), sin presion de plazo.

## Completado en sesion 3 (2026-07-01) — test e2e del scraper + docker-compose

### Bugs reales encontrados y corregidos (commit `8a6e639`)

El paso pendiente de sesion 2 era "test e2e + commit". El dry-run inicial devolvio **0 cards** con HTTP 200 OK — nada de error visible, asi que se investigo en capas (curl crudo -> comparar con lo que espera el regex -> reproducir en el interprete real) en vez de tocar el parser a ciegas. Aparecieron 3 problemas reales encadenados:

1. **Falta `brotli`**: `base.py` pide `Accept-Encoding: gzip, deflate, br`. CloudFront (escapadarural) responde en brotli. Sin el paquete `brotli` instalado, `httpx` no puede decodificar -> `r.text` es basura binaria -> BeautifulSoup no encuentra nada. Fix: `brotli~=1.2.0` anadido a `scraper/requirements.txt`.
2. **Ascenso de ancestros desalineado**: `_extract_list_cards` subia 5 niveles de `<a>.parent` buscando el contenedor con "personas/dormitorios". El sitio real necesita 6+ niveles (probablemente anadieron un wrapper div desde la exploracion 2.6a original). Con 5 niveles el texto seguia vacio -> `capacity_max` quedaba `None` en todas las cards -> el filtro de capacidad las descartaba todas. Fix: `MAX_ANCESTOR_CLIMB = 9` en `escapadarural.py`.
3. **Paginacion sin techo**: escapadarural.com **no valida** `?pagina=N` — pedir `pagina=50` devuelve el mismo HTML byte a byte que `pagina=1` (confirmado comparando ambas respuestas). Combinado con el bug 2 (nunca se llenaba `out`), el bucle de paginacion no tenia forma de parar via `empty_streak` y timeout a los 90s tras 31 paginas. Fix: `MAX_PAGES_PER_REGION = 15` como tope duro independiente de `empty_streak`.

Verificado tras el fix: dry-run con 5 listings (`capacity_max` 20-92, precio en todos) y run real con 9 nuevos listings persistidos en `data/casas.db` (`scrape_runs.status='ok'`).

### Gotcha operativo: DB path hardcodeado

`store.py` tiene `DEFAULT_DB_PATH = Path("/app/data/casas.db")`, pensado para el volumen Docker. Correr `python -m scraper.run` en el NAS **sin Docker y sin `--db`** escribe silenciosamente en otra base en `/app/data/casas.db` del host (sin las 31 seeds), no en `data/casas.db` del repo. Se limpio el archivo residual creado durante la investigacion. **Siempre pasar `--db data/casas.db` en pruebas bare-metal**, o usar `docker compose run` (ver abajo), donde el volumen resuelve la ruta correctamente sin flags extra.

### docker-compose minimo (commit `0715a0c`)

- `docker-compose.yml` en la raiz: servicio `scraper` (CLI de un solo uso, `--rm`, sin `ports`/`restart`), build desde `scraper/Dockerfile`, monta `./data:/app/data`.
- **Gotcha de infra**: el primer `docker compose run` fallo con "could not find an available, non-overlapping IPv4 address pool" — el NAS aloja muchos proyectos compose y el pool de subredes por defecto de Docker esta agotado. Fix: `network_mode: bridge` en vez de dejar que compose cree una red propia (el scraper solo hace HTTPS saliente, no necesita hablar con otros contenedores).
- Verificado: `docker compose build scraper` + `docker compose run --rm scraper python -m scraper.run --only escapadarural --limit 3 --regions cataluna --dry-run` -> 3 listings OK.

### Gotcha de git push desde nas_run_command

`nas_git_auth_status` mostraba credenciales OK, pero `git push` fallaba con "could not read Username for 'https://github.com'". Causa: el `credential.helper=store` vive en `/volume1/docker/.deploy/.gitconfig`, pero `$HOME` de las sesiones de `nas_run_command` es `/root` (con su propio `.gitconfig` sin ese helper). Fix puntual sin tocar la config global: `git -c credential.helper='store --file=/volume1/docker/.deploy/.git-credentials' push origin main`.

## Completado en sesion 2 (2026-06-28)

### Scraper escapadarural
- [x] `scraper/Dockerfile` — Python 3.11-slim, sin Playwright (decision YAGNI). httpx+BS4 puro.
- [x] `scraper/requirements.txt` — httpx, beautifulsoup4, lxml, pydantic, python-dateutil (+ `brotli` anadido en sesion 3).
- [x] `scraper/models.py` — Pydantic v2: `SearchQuery`, `Listing`.
- [x] `scraper/store.py` — SQLite con 4 tablas: `listings`, `prices`, `scrape_runs`, `seeds`. WAL mode.
- [x] `scraper/portals/base.py` — clase abstracta `BasePortal` con helper `_http_client()`.
- [x] `scraper/portals/escapadarural.py` — scraper SSR completo (corregido en sesion 3, ver arriba).
- [x] `scraper/run.py` — CLI con `--only`, `--limit`, `--regions`, `--min-capacity`, `--max-capacity`, `--dry-run`, `--verbose`, `--db`.

### Integracion seeds (GAV24)
- [x] `scraper/seeds_import.py` — parser tolerante CSV Google Sheets. **31 seeds GAV24 importadas** (29 ruled-out, 1 chosen=Mas Huix, 1 pending=Bonastre). 25 ES, 6 FR.

### Logos del proyecto
- [x] Logo 2 (historico 2020-2026) descargado en `C:\Cowork\IA-local-NAS\casa-finder-design-assets\logos\image1.png`.
- [ ] Logo 1 (sello Hokusai) pendiente: dialog "Guardar como" de Chrome requiere confirmacion manual del user.

## En curso

Nada bloqueante. Scraper end-to-end verificado y persistiendo datos reales. docker-compose probado. Todo commiteado y pusheado a `main`.

## Proximo paso exacto (siguiente sesion)

**Paso 3: API FastAPI** (carpeta `api/`, vacia todavia):

1. Definir endpoints minimos: `GET /listings` (con filtros por region/capacidad/precio), `GET /listings/{id}`, `GET /seeds`.
2. Reusar `scraper/models.py` (Pydantic `Listing`) y `scraper/store.py` para leer de `data/casas.db` (misma DB, solo lectura desde la API).
3. Puerto host reservado: **8401** (ver `/volume1/docker/PUERTOS.md`).
4. Anadir servicio `api` a `docker-compose.yml` (mismo patron: `network_mode: bridge` si no necesita hablar con `scraper`; revisar si necesita exponer puerto -> en ese caso SI hace falta mapear `ports: ["8401:8401"]`, que es distinto del caso del scraper CLI).
5. Cuando la API responda, siguiente paso = paso 4 (web Alpine.js, puerto 8400).

Antes de programar nada nuevo: **correr mas escapadas de regiones** (no solo cataluna) para tener mas datos reales con los que disenar los filtros de la API — opcional pero recomendado, usar `docker compose run --rm scraper python -m scraper.run --only escapadarural --regions <region>` para ir poblando `data/casas.db`.

Despues de la API: portales pendientes por prioridad — vrbo.com (anti-bot Akamai), booking.com (MCP conversacional, no pipeline), airbnb.com, clubrural.com/gitedegroupe.fr/somrurals.com/calarquer.com.

## Decisiones tomadas

| Decision | Por que |
|---|---|
| **Sin Playwright (YAGNI)** | Escapadarural es SSR, basta httpx+BS4. |
| **Booking MCP solo conversacional** | Util ad-hoc, no para el catalogo persistente (requeriria API REST directa). |
| **VRBO portal alta prioridad futuro** | 5 de las 31 casas del Excel GAV24 vinieron de VRBO. Anti-bot fuerte, puede requerir Playwright. |
| **Tabla `seeds` separada de `listings`** | Las seeds no tienen `portal_listing_id` estable. Link futuro por similitud nombre+ubicacion en la API. |
| **Aragon es preferencia aspiracional, no historica** | 7 anos de viajes GAV y Aragon NUNCA aparece. Sesgar ranking UI hacia Aragon cuando aparezca. |
| **Web NO urgente** | GAV26 ya elegido (Masia Escrigas). La web es para GAV27+, sin plazo. |
| **`network_mode: bridge` para el servicio scraper** | El NAS aloja muchos proyectos compose, el pool de subredes por defecto se agota. El scraper no necesita red propia (solo HTTPS saliente). |

## Problemas y soluciones

| Problema | Solucion |
|---|---|
| `type` de computer-use usa clipboard fast path -> sobrescribe el `Ctrl+X` previo | Usar `cmd /c move` desde la barra de direcciones de File Explorer. |
| Gmail thread no muestra todos los mensajes al cargar por threadId | Usar `#search/subject:"..."` para ver lista expandida. |
| MCP de Gmail NO tiene tool de download attachment | Solo `search_threads`/`get_thread`. Para adjuntos: Chrome MCP o user manual. |
| Regex de precio matcheaba `4256` como `425` | Cambiar `*` por `+` en la alternativa de miles. |
| Duplicado real "Casanova" en CSV | Renombrar la segunda a `Casanova (2)` en `_dedup_names()`. |
| pip3 install falla sin `--break-system-packages` | Usar `pip3 install --break-system-packages` en DSM 7+. |
| **(sesion 3)** `httpx` no decodifica brotli sin el paquete `brotli` -> 0 cards con HTTP 200 | Anadir `brotli~=1.2.0` a requirements.txt. |
| **(sesion 3)** Ascenso de 5 ancestros insuficiente para llegar al contenedor con "personas/dormitorios" | Subir `MAX_ANCESTOR_CLIMB` a 9. |
| **(sesion 3)** `?pagina=N` fuera de rango devuelve el mismo HTML que pagina 1, sin fin | Tope duro `MAX_PAGES_PER_REGION = 15`. |
| **(sesion 3)** `DEFAULT_DB_PATH` hardcodeado a `/app/data/casas.db` crea una DB fantasma si se corre bare-metal sin `--db` | Pasar siempre `--db data/casas.db` fuera de Docker, o usar `docker compose run` (el volumen resuelve la ruta). |
| **(sesion 3)** `docker compose run` falla por pool de subredes agotado en el NAS | `network_mode: bridge` en el servicio (no crear red propia). |
| **(sesion 3)** `git push` falla con "could not read Username" pese a `nas_git_auth_status` en verde | El credential.helper vive en `/volume1/docker/.deploy/.gitconfig`, no en `$HOME=/root/.gitconfig` de las sesiones de shell. Usar `git -c credential.helper='store --file=/volume1/docker/.deploy/.git-credentials' push origin main`. |

## Lecciones nuevas (para futuras sesiones)

- CSV de Google Sheets recorta trailing empty cells. Cualquier parser que dependa de `len(row)` fijo debe tolerar esto.
- Precios espanoles: comas decimales, puntos miles.
- Computer-use en Windows: `type` usa clipboard internamente, nunca entre cut y paste.
- MCPs son herramientas del agente Claude, NO librerias para cron Python — para pipelines persistentes usar la API REST/SDK del servicio directamente.
- Gmail MCP no descarga adjuntos.
- **Ante un fallo silencioso (0 resultados, sin excepcion), diagnosticar en capas**: 1) respuesta HTTP cruda con curl, 2) comparar con lo que espera el regex/selector, 3) reproducir paso a paso en el interprete real del proyecto. Evita "arreglar a ciegas" cuando el sintoma (regex no matchea) tiene una causa raiz distinta (encoding roto).
- Un sitio que no valida `?pagina=N` (devuelve contenido repetido) puede convertir un bug de filtrado en un bucle sin techo aparente — los bucles de paginacion necesitan SIEMPRE un tope duro, no solo un corte por "pagina vacia".
- En este NAS: `nas_git_auth_status` en verde no garantiza que `git push` funcione desde `nas_run_command` — el `$HOME` de esas sesiones no carga el `.gitconfig` de `.deploy`. Pasar el `credential.helper` explicito en el comando.
- Comandos largos en el NAS (docker build, etc.) pueden superar el timeout de `nas_run_command` en foreground incluso cuando el proceso real termina bien server-side — usar `background=True` + `nas_job_status` para no interpretar un timeout de monitorizacion como un fallo real; verificar con `docker images`/`docker ps` si hay dudas.

## Pendientes operativos (para arrancar la proxima sesion)

- [ ] Leer este HANDOFF y CLAUDE.md del proyecto.
- [ ] Verificar deps incluyendo brotli: `python3 -c 'import httpx, brotli, bs4, lxml, pydantic'`.
- [ ] Empezar por paso 3: API FastAPI en `api/` (ver "Proximo paso exacto" arriba).
- [ ] (Opcional) Poblar `data/casas.db` con mas regiones antes de disenar los filtros de la API.
- [ ] (Opcional) Bajar `image0.png` (logo Hokusai) cuando user lo apruebe.

## Estado actual del repo

```
/volume1/docker/casa-finder/
├── .gitignore
├── CLAUDE.md
├── HANDOFF.md                           (este archivo)
├── README.md
├── docker-compose.yml                   (NUEVO sesion 3)
├── scraper/
│   ├── Dockerfile
│   ├── requirements.txt                 (+ brotli, sesion 3)
│   ├── __init__.py
│   ├── models.py
│   ├── store.py
│   ├── run.py
│   ├── seeds_import.py
│   └── portals/
│       ├── __init__.py
│       ├── base.py
│       └── escapadarural.py             (fix sesion 3: ancestros + tope paginas)
├── api/                                 (carpeta vacia — paso 3, siguiente)
├── web/dist/                            (carpeta vacia — paso 4)
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

## Commits de esta sesion

- `8a6e639` — fix(scraper): brotli decoding + ancestor climb + pagination cap.
- `0715a0c` — feat(infra): docker-compose minimo para el scraper.

Ambos pusheados a `origin/main`.