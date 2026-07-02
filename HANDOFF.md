# /volume1/docker/casa-finder/HANDOFF.md

_Ultima actualizacion: 2026-07-02 (cierre de sesion 6)_

## Objetivo

Montar web publica `gav.ruizespana.com` que busque casas de vacaciones grupales (~25 pax) en Espana y sur de Francia. La familia GAV ("La Gran Aventura del Verano · Familia Espana Morales") hace un viaje anual desde 2020; en 2026 ya esta elegida **Masia Escrigas (Barcelona)**, asi que la web es para futuros viajes (GAV27+), sin presion de plazo.

## Completado en sesion 6 (2026-07-02)

### 1. Logo correcto en la cabecera (commits `d5b14c4`, tras un primer intento erroneo)

- Primer intento uso por error `image1.png` (logo cronologico 2020-2026) en vez del logo correcto.
- El usuario pego en el chat el logo real: sello estilo Hokusai "AVENTURA DEL VERANO · FAMILIA ESPAÑA & CO | 2026". Resultó ser exactamente `image0.png`, que ya existía en `C:\Cowork\IA-local-NAS\casa-finder-design-assets\logos\` desde sesion 2 (memoria antigua decaía "pendiente de descargar" -- estaba desactualizada, el archivo ya estaba ahi).
- `web/dist/assets/logo.png`: `image0.png` reescalado a 90px + cuantizado a 32 colores (1.6KB) para no engordar la imagen de Docker.
- Subtitulo del header corregido a peticion explícita: "Buscador de casas para las GAVs de la familia España Morales" (antes un texto generico).

### 2. Filtro por habitaciones minimas + visualizacion de banos (commit `04a2de7`)

El usuario pidio que el filtro principal sea **10+ habitaciones** (no capacidad/pax, que a menudo incluye supletorias) y que se vea el numero de banos o el ratio bano/habitacion.

- `scraper/store.py`: nuevo filtro `min_bedrooms` en `_listings_where`, `list_listings`, `count_listings_filtered`. Pasa a ser el filtro por defecto (`min_bedrooms=10`), sustituyendo a `min_capacity` (que antes defaulteaba a 20 y ahora es opcional sin default).
- `api/main.py`: `GET /listings` expone `min_bedrooms` (default 10).
- `web/dist/index.html`: input "Habitaciones minimas" (antes "Capacidad minima"); la tarjeta siempre muestra banos ("N/D" si falta el dato) + ratio bano/habitacion cuando ambos existen.
- **Verificado**: `min_bedrooms=10` (default) -> 4/9 casas; `min_bedrooms=1` -> 9/9. Los banos salen "N/D" para las 9 casas actuales porque **escapadarural no publica ese campo** -- no es un bug, es una limitacion de la fuente de datos. El ratio aparecera solo cuando algun portal futuro (o un fix de scraping) aporte el dato de banos.

### Gotcha nuevo: relay manual de imagenes binarias via base64 es fragil por encima de ~10-15KB

Al intentar subir el logo original (37KB -> ~50K caracteres base64) trocenado en chunks de 20000 caracteres para pegarlo via `nas_write_file`, **2 de los 3 chunks se corrompieron silenciosamente** al reconstruir el tool call (probablemente error de transcripcion manual, no del tool en si). `base64 -d` falló con "invalid input". **Leccion**: para archivos binarios (logos, imagenes) que hay que subir al NAS via este canal, primero **reescalar/comprimir agresivamente** (miniatura + cuantizacion de color con Pillow) hasta que el base64 quepa en un unico chunk de ~2-6KB, y **verificar el tamaño exacto** (`wc -c`) tras escribir en el NAS antes de decodificar -- si no coincide con el original, no seguir adelante y volver a intentarlo con un archivo mas pequeño en vez de reintentar el mismo chunk grande.

## En curso

Nada bloqueante. `casa-finder-api-1` y `casa-finder-web-1` arriba y sanos en el NAS (`192.168.1.205:8401` y `:8400`). Todo commiteado y pusheado a `origin/main` (`04a2de7`).

**Pendiente del usuario (no bloqueante para el codigo)**: la ruta Cloudflare `gav.ruizespana.com` -- el usuario confirmo en sesion 5 que la corregiria el mismo manualmente (apuntaba a 8401/API en vez de 8400/web). No verificado en esta sesion si ya lo hizo.

## Proximo paso exacto (siguiente sesion)

**Meter el resto de portales/buscadores.** El usuario confirmo explícitamente empezar por **VRBO** (prioridad alta: 5 de las 31 casas GAV24 vinieron de ahi), sabiendo que tiene anti-bot Akamai y puede llevar una sesion entera. Nada se implemento aun para VRBO en esta sesion (solo se discutió y se aparco por cierre de sesion).

1. Investigar el anti-bot de vrbo.com antes de escribir codigo: probar primero con `httpx` + cabeceras de navegador real (User-Agent, Accept-Language, etc.) como en escapadarural -- **no asumir que hace falta Playwright sin comprobarlo primero** (regla de "no asumir" del CLAUDE.md del proyecto). Si falla con 403/challenge, entonces sí evaluar Playwright.
2. Seguir el patron ya establecido: `scraper/portals/vrbo.py` heredando de `BasePortal`, registrar en `scraper/run.py` (lista `PORTALS`), documentar quirks del portal (paginacion, JS, cookies, anti-bot) en el README.
3. Reusar el mismo pipeline de persistencia (`store.py` / `upsert_listing`) -- no debe hacer falta tocar el schema salvo que VRBO exponga campos nuevos utiles.
4. Probar con `docker compose run --rm scraper python -m scraper.run --only vrbo --limit 5 --dry-run` antes de un scrape completo.
5. Despues de VRBO, seguir con el resto por prioridad: booking.com (MCP conversacional, NO pipeline), airbnb.com (anti-bot duro), clubrural.com / gitedegroupe.fr / somrurals.com / calarquer.com (sin anti-bot conocido, probablemente mas rapidos aunque aporten menos casas historicas).
6. Cada portal nuevo aumenta el dataset -- una vez haya mas de un portal, revisar si el filtro `min_bedrooms=10` sigue siendo razonable o si conviene exponerlo como slider en vez de input numerico simple.

## Decisiones tomadas (acumulado, nuevas de sesion 6 al final)

| Decision | Por que |
|---|---|
| Sin Playwright (YAGNI) | Escapadarural es SSR, basta httpx+BS4. A revisar caso a caso para VRBO/Airbnb. |
| Booking MCP solo conversacional | No para el catalogo persistente. |
| VRBO alta prioridad futura | 5/31 casas GAV24 vinieron de ahi; anti-bot fuerte. |
| Tabla `seeds` separada de `listings` | Sin `portal_listing_id` estable en las seeds; link futuro por similitud nombre+ubicacion. |
| Aragon = preferencia aspiracional | 7 anos de viajes GAV, Aragon nunca aparece; UI ya sesga visualmente (sesion 5). |
| `network_mode: bridge` en scraper, red `ia-net` compartida en api+web | Ver sesion 5 / CLAUDE.md. |
| API (8401) no se expone publicamente | Confirmado de nuevo en sesion 6: con la web publica (8400) es suficiente. |
| **(sesion 6)** Filtro principal pasa de `min_capacity` (pax) a `min_bedrooms` (habitaciones), default 10 | La capacidad publicada por el portal a menudo incluye supletorias; el numero de habitaciones es un proxy mas fiable para "casa apta para grupo grande", pedido explicito del usuario. |
| **(sesion 6)** Imagenes binarias grandes se reescalan agresivamente antes de subirlas al NAS via este canal | Relay manual de base64 >15-20KB es propenso a corrupcion silenciosa (ver gotcha arriba). |

## Problemas y soluciones (acumulado, nuevas de sesion 6 al final)

| Problema | Solucion |
|---|---|
| `httpx` no decodifica brotli sin el paquete `brotli` -> 0 cards con HTTP 200 | `brotli~=1.2.0` en requirements.txt. |
| Ascenso de 5 ancestros insuficiente en `_extract_list_cards` | Subir `MAX_ANCESTOR_CLIMB` a 9. |
| `?pagina=N` fuera de rango devuelve el mismo HTML que pagina 1, sin fin | Tope duro `MAX_PAGES_PER_REGION = 15`. |
| `DEFAULT_DB_PATH` hardcodeado a `/app/data/casas.db` crea DB fantasma en bare-metal sin `--db` | Pasar `--db data/casas.db` fuera de Docker, o usar `docker compose run`. |
| `docker compose run`/`up` falla por pool de subredes agotado | `network_mode: bridge`, o reusar una red externa YA EXISTENTE (`ia-net`). |
| `git push` falla con "could not read Username" pese a `nas_git_auth_status` en verde | `git -c credential.helper='store --file=/volume1/docker/.deploy/.git-credentials' push origin main`. |
| Ruta `/listings/{portal}/{portal_listing_id}` 404 generico | Conversor `{portal_listing_id:path}`. |
| `curl localhost:PUERTO` desde `nas_run_command` da "Connection refused" | Usar la IP LAN real (`192.168.1.205`), nunca `localhost`. |
| `nas_run_command` en foreground puede reportar timeout aunque el proceso termine bien server-side | Usar `background=True` + `nas_job_status`, o verificar directamente con un comando corto (`docker ps`) si hay dudas -- confirmado varias veces mas en sesion 6. |
| **(sesion 6)** Relay manual de base64 de un logo de 37KB (~50K caracteres) corrompido en 2 de 3 chunks de 20000 caracteres | Reescalar/cuantizar la imagen con Pillow hasta que quepa en un chunk unico de pocos KB, y verificar `wc -c` exacto tras escribir antes de decodificar. |
| **(sesion 6)** Cloudflare dashboard colgado en spinner al navegar desde pestana nueva de Claude-in-Chrome MCP (visto tambien en sesion 5) | No se investigo la causa; para ediciones triviales en un dashboard que el usuario ya tiene abierto y logueado, mejor pedirselo directamente. |

## Lecciones nuevas (sesion 6, para futuras sesiones)

- Antes de asumir que un archivo de assets "falta" o esta "pendiente", comprobar primero si ya existe en la carpeta del proyecto -- la memoria persistente puede quedar desactualizada (el logo del sello llevaba ya descargado desde sesion 2, la memoria decia lo contrario).
- Para binarios grandes relayados manualmente via chat -> NAS, la regla practica es: si el base64 no cabe comodo en una sola llamada de escritura (ordenes de unos pocos KB), reducir el archivo en origen (resize/quantize) en vez de trocearlo en múltiples llamadas -- trocear aumenta el riesgo de corrupcion silenciosa y es dificil de depurar (el error solo aparece al decodificar, lejos de la causa).
- Verificar SIEMPRE el tamaño en bytes de un archivo binario recién escrito en el NAS (`wc -c`) contra el tamaño esperado antes de decodificar/usar -- deteccion barata de corrupcion de transferencia.
- Cuando el usuario pide un cambio de negocio (ej. "deberian ser casas de 10+ habitaciones") que afecta a la capa de datos, propagar el cambio en las 3 capas a la vez en el mismo commit: `store.py` (SQL), `api/main.py` (contrato HTTP), `web/dist/index.html` (UI) -- evita quedar con capas desincronizadas.

## Pendientes operativos (para arrancar la proxima sesion)

- [ ] Leer este HANDOFF y CLAUDE.md del proyecto.
- [ ] Verificar que `casa-finder-api-1` y `casa-finder-web-1` siguen arriba (`docker ps --filter name=casa-finder`, IP LAN no localhost).
- [ ] Preguntar al usuario si ya corrigio manualmente la ruta Cloudflare `gav.ruizespana.com` -> 8400.
- [ ] Empezar VRBO: investigar anti-bot antes de escribir codigo (ver "Proximo paso exacto").
- [ ] Tras VRBO (o en paralelo si es rapido): valorar los portales "faciles" (clubrural, gitedegroupe, somrurals, calarquer).

## Estado actual del repo

```
/volume1/docker/casa-finder/
├── .gitignore
├── CLAUDE.md
├── HANDOFF.md                             (este archivo)
├── README.md
├── docker-compose.yml                     (scraper + api + web)
├── scraper/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── __init__.py
│   ├── models.py
│   ├── store.py                           (+ filtro min_bedrooms, sesion 6)
│   ├── run.py
│   ├── seeds_import.py
│   └── portals/
│       ├── __init__.py
│       ├── base.py
│       └── escapadarural.py               (unico portal implementado)
├── api/
│   ├── __init__.py
│   ├── main.py                            (+ min_bedrooms, sesion 6)
│   ├── requirements.txt
│   └── Dockerfile
├── web/
│   ├── dist/
│   │   ├── index.html                     (logo + filtro habitaciones, sesion 6)
│   │   └── assets/
│   │       └── logo.png                   (NUEVO sesion 6, sello Hokusai)
│   ├── nginx.conf
│   └── Dockerfile
└── data/                                  (gitignored)
    ├── casas.db                           (31 seeds + 9 listings escapadarural/cataluna)
    └── raw/
        └── gav24.csv
```

Adicionalmente en el PC del user:
```
C:\Cowork\IA-local-NAS\casa-finder-design-assets\logos\
├── image0.png                          (logo sello Hokusai -- el que se usa en la web)
└── image1.png                          (logo historico viajes GAV -- no usado en la web)
```

## Servicios corriendo ahora mismo en el NAS

| Contenedor | Puerto | Estado |
|---|---|---|
| `casa-finder-api-1` | `192.168.1.205:8401` -> 8000 | Up, `restart: unless-stopped`, red `ia-net` |
| `casa-finder-web-1` | `192.168.1.205:8400` -> 80 | Up, `restart: unless-stopped`, red `ia-net` |

(`scraper` no queda corriendo -- es un CLI de un solo uso via `docker compose run --rm scraper`.)

## Commits de esta sesion (sesion 6)

- `d5b14c4` -- feat(web): logo sello Hokusai en cabecera + corrige subtitulo.
- `04a2de7` -- feat(filters): filtra por habitaciones minimas (10 por defecto) y muestra banos.

Ambos pusheados a `origin/main`.