# casa-finder — Reglas del proyecto

Hereda de `/volume1/docker/CLAUDE.md` (global) y `/volume1/docker/ruizespana/CLAUDE.md` si aplica.

## Resumen del proyecto

Web pública en `gav.ruizespana.com` que busca casas de vacaciones para grupos grandes (~25 pax) en España y sur de Francia. Scrapea portales rurales, persiste en SQLite con histórico de precios, y rankea con LLM vía `vision-router`.

Referencias iniciales (perfil que buscamos): Mas Huix, Masia Escrigas, Finca Savanna.

## Stack

- **Scraper:** Python 3.11 + Playwright (Chromium headless) + cron diario
- **Persistencia:** SQLite (`data/casas.db`) con tablas `listings`, `prices`, `scrape_runs`
- **API:** FastAPI (puerto interno 8000 → host **8401**)
- **Web:** estática con Alpine.js + nginx (puerto interno 80 → host **8400**)
- **LLM:** llamadas HTTP a `http://vision-router:8003` (red `ia-net`)
- **Subdominio público:** `gav.ruizespana.com` vía Cloudflare Tunnel (`cloudflare-maja-2`)

## Reglas operativas

1. **Un paso a la vez.** Esperar confirmación entre pasos.
2. **Nunca auto-commit.** Tras cambios funcionales: listar archivos modificados, proponer commit message, preguntar "¿Ejecuto el push a GitHub via NAS MCP?".
3. **No dar la tarea por cerrada hasta confirmar el push.**
4. **Actualizar `HANDOFF.md` y este `CLAUDE.md`** ante decisiones nuevas o lecciones.
5. **No asumir.** Si no conozco una API o el comportamiento de una librería, lo digo o lo verifico antes de proponer código.
6. **No tocar otros proyectos del NAS** salvo necesidad explicada.

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
- **Ollama (`vision-ollama`) tiene `mem_limit: 5g`** — arrancarlo expulsa contenedores. Solo a demanda.
- Modelos descargados: `qwen2.5vl` (3 GB).

## Puertos asignados

| Puerto host | Servicio |
|---|---|
| 8400 | web (nginx) |
| 8401 | api (FastAPI) |

## Subdominio

Alta en Cloudflare Zero Trust vía Chrome MCP cuando el servicio esté levantado:
- Hostname: `gav.ruizespana.com`
- Service: `http://192.168.1.205:8400` (o nombre interno si están en la misma red)