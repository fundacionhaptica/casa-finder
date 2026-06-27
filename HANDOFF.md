# HANDOFF — casa-finder

_Última actualización: 2026-06-27 (cierre de sesión 1)_

## Objetivo

Montar web pública `gav.ruizespana.com` que busque casas de vacaciones grupales (~25 pax) en España y sur de Francia, parecidas a Mas Huix / Masia Escrigas / Finca Savanna.

## Completado en esta sesión

- [x] Discovery NAS (docker, Ollama, vision-router, subdominios vía Cloudflare Tunnel).
- [x] Arquitectura definida (ver `CLAUDE.md` del proyecto).
- [x] Scaffold creado en `/volume1/docker/casa-finder/`:
  - `.gitignore`, `.env.example`
  - `CLAUDE.md` (reglas específicas)
  - `README.md` (arquitectura + setup)
  - `HANDOFF.md` (este archivo)
  - Carpetas: `scraper/portals/`, `api/`, `web/dist/`, `data/raw/`
- [x] Repo GitHub creado: https://github.com/fundacionhaptica/casa-finder (público)
- [x] Primer commit y push: `50c9123` en `main`, tracking OK.
- [x] `vision-ollama` arrancado con perfil `experimental` (modelo `qwen2.5vl:3b`, 3.2 GB). RAM libre estable en ~2.3 GB.

## En curso

_Nada pendiente. Sesión cerrada limpiamente._

## Próximo paso exacto (siguiente sesión)

**Paso 2 — Primer scraper (escapadarural.com):**

1. Crear `scraper/Dockerfile` (Python 3.11-slim + Playwright + Chromium).
2. Crear `scraper/requirements.txt` (playwright, httpx, beautifulsoup4, pydantic, sqlite via stdlib).
3. Crear `scraper/models.py` con dataclasses `Listing` y `SearchQuery`.
4. Crear `scraper/store.py` con esquema SQLite (`listings`, `prices`, `scrape_runs`) y función `upsert_listing`.
5. Crear `scraper/portals/base.py` con clase abstracta `BasePortal`.
6. Crear `scraper/portals/escapadarural.py` con scraper real para escapadarural.com (filtros: pax≥ 20, Cataluña primero).
7. Crear `scraper/run.py` (CLI con `--only <portal>` y `--limit N`).
8. Probar end-to-end: una búsqueda, ver que persiste en `data/casas.db`.

Criterio de "hecho" del paso 2: ejecutar `docker compose run --rm scraper python -m scraper.run --only escapadarural --limit 10` y obtener ≥5 listings en SQLite con datos completos (nombre, precio, capacidad, URL, foto).

Después del paso 2: API FastAPI → Web Alpine.js → docker-compose → Cloudflare Tunnel (via Chrome MCP).

## Decisiones tomadas

| Decisión | Por qué |
|---|---|
| LLM vía `vision-router` (Gemini 2.5 Flash por defecto) | Centraliza claves, reutiliza infra, no consume RAM del NAS |
| Ollama arrancado (qwen2.5vl:3b) | El usuario quiso probarlo. RAM aguanta. Multimodal → útil también para fotos. |
| SQLite con histórico de precios | Sin servidor extra, permite ver evolución |
| Web pública sin auth | El usuario lo pidió explícito |
| Alpine.js (no React build) | Cero build step, dashboard ligero |
| Puertos 8400 (web) y 8401 (api) | Dentro de rango libre 8302-8999 (`/volume1/docker/PUERTOS.md`) |
| Subdominio vía Cloudflare Zero Trust | Patrón existente con `cloudflare-maja-2`. Alta manual con Chrome MCP cuando levantemos. |

## Problemas y soluciones

| Problema | Solución |
|---|---|
| `docker compose up vision-ollama` fallaba con "no such service" | El servicio en compose se llama `ollama` (no `vision-ollama`, que es el container_name). Comando correcto: `docker compose --profile experimental up -d ollama`. |
| `POST /orgs/fundacionhaptica/repos` devolvió 404 | `fundacionhaptica` es un **User**, no una Org. Crear con `POST /user/repos` autenticado. |
| `curl` no existe dentro del contenedor Ollama oficial | Verificar Ollama desde fuera o con `ollama list`. |

## Lecciones para futuras sesiones

- El NAS tiene **`vision-router`** (puerto 8003, red `ia-net`) como hub LLM. Cualquier proyecto nuevo que necesite LLM debe llamar a `http://vision-router:8003` en lugar de hablar con Gemini/Ollama directamente.
- Las credenciales de GitHub viven en `/volume1/docker/.deploy/.git-credentials` con `HOME=/volume1/docker/.deploy` + `credential.helper=store`. Patrón para futuros pushes: `export HOME=/volume1/docker/.deploy && cd <proyecto> && git push`.
- Para crear repo en GitHub sin `gh` CLI: `curl POST /user/repos` con el PAT extraído de `.git-credentials`.
- Subdominios `*.ruizespana.com` se exponen vía `cloudflare-maja-2` (Cloudflare Tunnel). El alta de hostname se hace en Cloudflare Zero Trust dashboard — usar Chrome MCP.
- Rango de puertos libre en el NAS: **8302–8999** (ver `/volume1/docker/PUERTOS.md`).
- Ollama en NAS funciona pero **mem_limit: 5g**. RAM total del NAS: 5.8 GB. No tener arriba a la vez todo el stack pesado.

## Pendientes operativos (para arrancar la próxima sesión)

- [ ] Leer este HANDOFF.md y `CLAUDE.md` del proyecto.
- [ ] Verificar que `vision-ollama` sigue arriba (o decidir si pararlo).
- [ ] Actualizar `/volume1/docker/PUERTOS.md` con 8400/8401 (reservados, no asignados todavía).
- [ ] Empezar paso 2.