# casa-finder

Búsqueda de casas de vacaciones para grupos grandes (~25 pax) en España y sur de Francia.

**Web pública:** https://gav.ruizespana.com

## ¿Qué hace?

- Scrapea diariamente portales de turismo rural (escapadarural, clubrural, gitedegroupe, etc.).
- Guarda anuncios en SQLite con histórico de precios.
- Sirve un dashboard público con filtros (capacidad, zona, fechas, precio).
- Rankea similitud con casas de referencia (Mas Huix, Masia Escrigas, Finca Savanna) usando LLM vía `vision-router`.

## Arquitectura

```
   Internet
      |
      v
   Cloudflare Tunnel (gav.ruizespana.com)
      |
      v
   nginx:80 (web estática)  --[fetch]-->  FastAPI:8000 (api)
                                              |
                                              v
                                          SQLite (data/casas.db)
                                              ^
                                              |
                                       Scraper (cron diario)
                                              |
                                              v
                                      vision-router:8003 → Gemini / Ollama
```

## Stack

- Python 3.11, Playwright, FastAPI, SQLite
- nginx (Alpine), Alpine.js (sin build step)
- Docker Compose, red externa `ia-net` para alcanzar `vision-router`

## Setup local (en NAS)

```bash
cd /volume1/docker/casa-finder
cp .env.example .env  # rellenar VISION_INTERNAL_API_KEY
docker compose build
docker compose up -d
```

- Web: http://192.168.1.205:8400
- API: http://192.168.1.205:8401/docs

## Ejecutar scrape manual

```bash
docker compose run --rm scraper python -m scraper.run --only escapadarural
docker compose run --rm scraper python -m scraper.run  # todos los portales
```

## Añadir un portal nuevo

Ver `CLAUDE.md` § "Cómo añadir un portal".

## Despliegue público

1. `docker compose up -d` en el NAS.
2. En Cloudflare Zero Trust dashboard: añadir Public Hostname `gav.ruizespana.com` apuntando a `http://192.168.1.205:8400`.
3. Esperar propagación DNS (~1 min).

## Estado actual

Ver `HANDOFF.md`.

## Limitaciones conocidas

- Algunos portales (Airbnb, Booking) tienen anti-bot — no los scrapeamos.
- Capacidades "25 pax" suelen incluir supletorias: el dashboard muestra el dato del portal, no garantiza camas reales.
- Ranking LLM depende de `vision-router` corriendo y con cuóta Gemini disponible.