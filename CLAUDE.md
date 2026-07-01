# casa-finder — Reglas del proyecto

Hereda de `/volume1/docker/CLAUDE.md` (global) y `/volume1/docker/ruizespana/CLAUDE.md` si aplica.

## Resumen del proyecto

Web pública en `gav.ruizespana.com` que busca casas de vacaciones para grupos grandes (~25 pax) en España y sur de Francia. Scrapea portales rurales, persiste en SQLite con histórico de precios, y rankea con LLM vía `vision-router`.

Referencias iniciales (perfil que buscamos): Mas Huix, Masia Escrigas, Finca Savanna.

## Stack

- **Scraper:** Python 3.11 + httpx + BeautifulSoup (SSR, sin Playwright -- YAGNI) + cron diario
- **Persistencia:** SQLite (`data/casas.db`) con tablas `listings`, `seeds`, `prices`, `scrape_runs`
- **API:** FastAPI, solo lectura (puerto interno 8000 → host **8401**)
- **Web:** estática con Alpine.js + nginx (puerto interno 80 → host **8400**), proxy `/api/*` -> `api:8000`
- **LLM:** llamadas HTTP a `http://vision-router:8003` (red `ia-net`) -- pendiente de integrar
- **Subdominio público:** `gav.ruizespana.com` vía Cloudflare Tunnel (`cloudflare-maja-2`)

## Reglas operativas

1. **Un paso a la vez.** Esperar confirmación entre pasos.
2. **Nunca auto-commit.** Tras cambios funcionales: listar archivos modificados, proponer commit message, preguntar "¿Ejecuto el push a GitHub via NAS MCP?".
3. **No dar la tarea por cerrada hasta confirmar el push.**
4. **Actualizar `HANDOFF.md` y este `CLAUDE.md`** ante decisiones nuevas o lecciones.
5. **No asumir.** Si no conozco una API o el comportamiento de una librería, lo digo o lo verifico antes de proponer código.
6. **No tocar otros proyectos del NAS** salvo necesidad explicada.
7. **No tocar Cloudflare sin confirmar antes con el usuario** -- es infraestructura compartida con otros proyectos del NAS.

## Cómo añadir un portal

1. Crear `scraper/portals/<nombre>.py` con una clase que herede de `BasePortal` y exponga `def fetch(self, query: SearchQuery) -> list[Listing]`.
2. Registrarla en `scraper/run.py` (lista `PORTALS`).
3. Probar en local: `docker compose run --rm scraper python -m scraper.run --only <nombre>`.
4. Documentar quirks del portal (paginación, JS, cookies) en una sección del README.

## Contrato con `vision-router`

- Endpoint: `POST http://vision-router:8003/rank` (a definir cuando integremos)
- Auth: header `X-Internal-Key: ${VISION_INTERNAL_API_KEY}`
- Provider por defecto: Gemini 2.5 Flash. Para usar Ollama: variable `PROVIDER_CASA_FINDER=ollama` y arrancar `vision-ollama` con `--profile experimental`.

## Restricciones del NAS

- RAM total: 5.8 GB. Libre habitual: ~700 MB.
- **Ollama (`vision-ollama`) tiene `mem_limit: 5g`** -- arrancarlo expulsa contenedores. Solo a demanda.
- Modelos descargados: `qwen2.5vl` (3 GB).
- **Pool de subredes Docker agotado** ("could not find an available, non-overlapping IPv4 address pool"): no crear redes `compose` nuevas. Para que dos servicios del mismo proyecto se resuelvan por nombre, reusar una red externa ya existente (`ia-net`) declarándola `external: true` en `docker-compose.yml`, en vez de dejar que compose cree una red propia. Servicios que no necesitan hablar con otros contenedores (ej. `scraper`, solo HTTPS saliente) siguen en `network_mode: bridge`.

## Puertos asignados

| Puerto host | Servicio |
|---|---|
| 8400 | web (nginx) |
| 8401 | api (FastAPI) |

## Subdominio

- Hostname: `gav.ruizespana.com`
- Service esperado: `http://192.168.1.205:8400` (web, no la API).
- **Estado 2026-07-01:** la ruta existente en Cloudflare Zero Trust ("Synology-MaJa" tunnel, published application routes #16) apunta todavía a `http://192.168.1.205:8401` (API) en vez de 8400. Pendiente de corregir manualmente por el usuario -- Claude no edita Cloudflare sin confirmación explícita (regla 7), y en el intento de esta sesión el dashboard se quedó colgado cargando en la pestaña controlada por la extensión.
- Decisión 2026-07-01: la API (8401) **no** se expone públicamente. Solo `gav.ruizespana.com` -> 8400 (web). El proxy nginx (`/api/*` -> `api:8000`) es la única vía pública a los datos.