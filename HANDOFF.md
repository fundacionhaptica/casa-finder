# HANDOFF — casa-finder

_Última actualización: 2026-06-27_

## Objetivo

Montar web pública `gav.ruizespana.com` que busque casas de vacaciones grupales (~25 pax) en España y sur de Francia, parecidas a Mas Huix / Masia Escrigas / Finca Savanna.

## Completado

- [x] Discovery NAS: docker, modelos Ollama, vision-router, subdominios.
- [x] Arquitectura definida (ver `CLAUDE.md`).
- [x] Scaffold de carpetas creado en `/volume1/docker/casa-finder/`.
- [x] `CLAUDE.md` (reglas proyecto) escrito.
- [x] `README.md` escrito.
- [x] `.gitignore` escrito.
- [x] `HANDOFF.md` (este archivo) creado.

## En curso

- Decidir si arrancamos `vision-ollama` ya (riesgo RAM: NAS tiene 700 MB libres, contenedor pide hasta 5 GB).

## Próximo paso exacto

**Paso 2:** Implementar primer portal (escapadarural.com).
- Crear `scraper/Dockerfile`, `requirements.txt`.
- Crear `scraper/models.py` (dataclass `Listing`, `SearchQuery`).
- Crear `scraper/store.py` (esquema SQLite + funciones upsert).
- Crear `scraper/portals/base.py` (clase abstracta `BasePortal`).
- Crear `scraper/portals/escapadarural.py` (primer scraper real).
- Crear `scraper/run.py` (CLI con `--only <portal>`).
- Probar end-to-end con un par de búsquedas.

Antes de pasar al paso 3 (API), confirmar que el scraper guarda datos correctamente en SQLite.

## Decisiones tomadas

| Decisión | Por qué |
|---|---|
| LLM vía `vision-router` (Gemini 2.5 Flash) | Centraliza claves, reutiliza infra existente, no consume RAM del NAS |
| Ollama parado por defecto | RAM insuficiente para tenerlo siempre arriba |
| SQLite con histórico | Sin servidor extra, permite ver evolución de precios |
| Web pública sin auth | El usuario lo pidió explícito; sin datos sensibles |
| Alpine.js (no React build) | Cero build step, dashboard ligero, fácil de mantener |
| Puertos 8400 (web) y 8401 (api) | Dentro del rango libre 8302-8999 documentado en `/volume1/docker/PUERTOS.md` |

## Problemas y soluciones

_(Vacío por ahora.)_

## Pendientes operativos

- [ ] Crear repo `fundacionhaptica/casa-finder` en GitHub (con confirmación del usuario).
- [ ] Primer push tras paso 2 funcional.
- [ ] Alta de `gav.ruizespana.com` en Cloudflare Zero Trust (via Chrome MCP) tras paso 5.
- [ ] Actualizar `/volume1/docker/PUERTOS.md` con 8400/8401.