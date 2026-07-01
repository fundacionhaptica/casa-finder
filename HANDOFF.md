# /volume1/docker/casa-finder/HANDOFF.md

_Ultima actualizacion: 2026-07-01 (cierre de sesion 5)_

## Objetivo

Montar web publica `gav.ruizespana.com` que busque casas de vacaciones grupales (~25 pax) en Espana y sur de Francia. La familia GAV ("Aventura del Verano · Familia Espana & Co") hace un viaje anual desde 2020; en 2026 ya esta elegida **Masia Escrigas (Barcelona)**, asi que la web es para futuros viajes (GAV27+), sin presion de plazo.

## Completado en sesion 5 (2026-07-01) — Paso 4: Web publica (commit `3817132`)

### `web/dist/index.html` (nuevo)

HTML+JS estatico con Alpine.js (sin build step, `x-data`/`x-model`/`x-for`). Contra `GET /api/listings` (via proxy nginx, ver abajo):
- Filtros: `min_capacity` (default 20), `region` (parcial), `max_price_per_night`.
- Grid de tarjetas: imagen, nombre, ubicacion, capacidad, habitaciones, banos, precio/noche o precio/estancia, link al portal original.
- **Sesgo hacia Aragon** (preferencia aspiracional de la familia, ver decisiones): las tarjetas cuya `region`/`location` matchea `/arag/i` se destacan con borde+badge y se ordenan primero (`sortedListings`), y aparece un banner si hay al menos una.
- Estados vacio/error manejados explicitamente.

### `web/nginx.conf` + `web/Dockerfile` (nuevo)

- nginx sirve `web/dist/` como estaticos en `/`.
- `location /api/` hace proxy a `http://api:8000/` (el slash final en ambos hace que nginx sustituya el prefijo, es decir `/api/listings` -> `http://api:8000/listings`). El navegador nunca llama directo al puerto 8401.
- Imagen base `nginx:1.27-alpine`.

### `docker-compose.yml` (modificado)

- Nuevo servicio `web`: build `web/Dockerfile`, puerto host **8400:80**, `restart: unless-stopped`, `depends_on: api`.
- **Cambio de red en `web` y `api`**: pasan de `network_mode: bridge` a `networks: [ia-net]` (red bridge externa YA EXISTENTE en el NAS, usada tambien por `vision-router`). Se declara `ia-net` como `external: true` en el compose para NO crear una subred nueva (el pool de Docker esta agotado en este NAS, gotcha ya conocido de sesion 3). Esto permite que `web` resuelva `api` por nombre de servicio Docker, cosa que `network_mode: bridge` no permitia.
- `scraper` sigue en `network_mode: bridge` sin cambios (no necesita hablar con otros contenedores).
- `api` mantiene su publish `8401:8000` para acceso directo (LAN), ademas de estar en `ia-net`.

### Verificacion end-to-end (contra el NAS real)

```
docker compose build web          -> OK, casa-finder-web:local
docker compose up -d web          -> casa-finder-web-1 y casa-finder-api-1 (recreado por cambio de red) Up

curl -s -o /dev/null -w '%{http_code}' http://192.168.1.205:8400/
  -> 200

curl -s http://192.168.1.205:8400/api/health
  -> {"status":"ok","listings_count":9,"seeds_count":31}   (proxy nginx -> api funciona)

curl -s http://192.168.1.205:8401/health
  -> {"status":"ok","listings_count":9,"seeds_count":31}   (api sigue respondiendo directo tras el cambio de red)

curl -s 'http://192.168.1.205:8400/api/listings?min_capacity=20&limit=2'
  -> total:9, items con todos los campos (via proxy)
```

### Decision tomada en sesion 5: API no se expone publicamente

El usuario confirmo que con la web publica (8400) es suficiente; la API (8401) se queda solo en LAN/uso interno. No se crea una ruta publica adicional tipo `api-gav.ruizespana.com`.

### Pendiente real: ruta Cloudflare `gav.ruizespana.com` mal apuntada

Se detecto (captura de pantalla del usuario, tunnel "Synology-MaJa", Published application routes, fila 16) que `gav.ruizespana.com` apunta **hoy** a `http://192.168.1.205:8401` (la API), cuando deberia apuntar a **8400** (la web, que es lo que un visitante deberia ver). El usuario confirmo que quiere corregirlo a 8400.

**No se corrigio en esta sesion**: se intento via Claude-in-Chrome MCP (pestana nueva del grupo MCP, no la pestana donde el usuario ya tenia el dashboard abierto) navegando a la URL de edicion del tunnel, pero el dashboard de Cloudflare se quedo colgado en la pantalla de carga (spinner) mas de 20s sin resolver -- probablemente porque esa pestana nueva no comparte sesion/cookies de forma inmediata con el dashboard, o por lentitud propia del SPA. Se abandono el intento automatizado en vez de insistir a ciegas o probar a autenticar (fuera de las reglas: nunca introducir credenciales).

**Accion pendiente para el usuario** (paso manual, 2 minutos): en la pestana de Cloudflare que ya tenia abierta (dash.cloudflare.com -> Networks -> Connectors -> Synology-MaJa -> Published application routes), editar la fila 16 (`gav.ruizespana.com`) y cambiar el target de `http://192.168.1.205:8401` a `http://192.168.1.205:8400`.

## Completado en sesiones anteriores (resumen — detalle completo en el historial de commits y en la memoria del proyecto)

- **Sesion 2 (2026-06-28)**: scraper `escapadarural` completo (httpx+BS4, SQLite 4 tablas, CLI), 31 seeds GAV24 importadas, logos localizados.
- **Sesion 3 (2026-07-01)**: 3 bugs reales corregidos en el scraper (brotli, ascenso de ancestros, tope de paginacion), gotcha de DB path hardcodeado, `docker-compose.yml` minimo para `scraper` con fix de red (`network_mode: bridge`), gotcha de `git push` con credential.helper.
- **Sesion 4 (2026-07-01)**: API FastAPI de solo lectura (`api/`), commit `e75f146`. Bug de ruta `{portal_listing_id:path}`. Gotchas operativos de `nas_run_command` (corre dentro del contenedor `nas-mcp`, no en el host; comandos largos pueden timeoutear en foreground aunque terminen bien; NAS compartido con otras automatizaciones).

## En curso

Nada bloqueante para el codigo. Los 3 servicios (`scraper` on-demand, `api`, `web`) funcionan correctamente en el NAS. Todo commiteado y pusheado a `origin/main` (`3817132`).

**Bloqueante externo (no de codigo)**: la ruta publica `gav.ruizespana.com` en Cloudflare sigue apuntando al puerto equivocado (8401 en vez de 8400) hasta que el usuario la corrija manualmente -- ver seccion de arriba.

## Proximo paso exacto (siguiente sesion)

1. **Verificar si el usuario ya corrigio la ruta Cloudflare** (`gav.ruizespana.com` -> 8400). Si no, recordarselo.
2. Con eso resuelto, `gav.ruizespana.com` deberia servir la web real -- probar en un navegador normal (no solo curl) que carga bien, que el JS de Alpine se ejecuta y que los filtros funcionan contra datos reales.
3. **Poblar mas regiones** en `data/casas.db` para que la web tenga un dataset mas realista (ahora mismo: 9 listings, todos escapadarural/cataluna): `docker compose run --rm scraper python -m scraper.run --only escapadarural --regions <region>`.
4. Despues: portales pendientes por prioridad -- vrbo.com (anti-bot Akamai), booking.com (MCP conversacional, no pipeline), airbnb.com, clubrural.com/gitedegroupe.fr/somrurals.com/calarquer.com.
5. (Opcional, sin plazo) Integracion con `vision-router` para ranking de similitud con las casas de referencia (Mas Huix, Masia Escrigas, Finca Savanna) -- contrato aun sin definir, ver CLAUDE.md § "Contrato con vision-router".

## Decisiones tomadas (acumulado)

| Decision | Por que |
|---|---|
| Sin Playwright (YAGNI) | Escapadarural es SSR, basta httpx+BS4. |
| Booking MCP solo conversacional | No para el catalogo persistente. |
| VRBO alta prioridad futura | 5/31 casas GAV24 vinieron de ahi; anti-bot fuerte. |
| Tabla `seeds` separada de `listings` | Sin `portal_listing_id` estable en las seeds; link futuro por similitud nombre+ubicacion. |
| Aragon = preferencia aspiracional | 7 anos de viajes GAV, Aragon nunca aparece; sesgar UI cuando aparezca (implementado en sesion 5). |
| Web no urgente | GAV26 ya elegido; la web es para GAV27+. |
| `network_mode: bridge` en scraper | HTTPS saliente unicamente, no necesita resolver otros servicios por nombre. |
| **(sesion 5)** `web` y `api` migran de `network_mode: bridge` a red externa `ia-net` | `web` necesita resolver `api` por nombre para el proxy; reusar `ia-net` (ya existente) evita crear una subred nueva con el pool agotado. |
| API sin autenticacion, CORS abierto | Es un dashboard publico de solo lectura, sin datos sensibles (aunque finalmente el cliente solo la llama via proxy, no directo). |
| **(sesion 5)** API (8401) no se expone publicamente en Cloudflare | El usuario confirmo que con la web publica (8400 via proxy) es suficiente. |
| `api/Dockerfile` copia solo models.py+store.py del scraper | Evita arrastrar httpx/bs4/lxml a la imagen de la API, que no los necesita. |

## Problemas y soluciones (acumulado, ver tambien memoria del proyecto para el detalle completo)

| Problema | Solucion |
|---|---|
| `httpx` no decodifica brotli sin el paquete `brotli` -> 0 cards con HTTP 200 | `brotli~=1.2.0` en requirements.txt. |
| Ascenso de 5 ancestros insuficiente en `_extract_list_cards` | Subir `MAX_ANCESTOR_CLIMB` a 9. |
| `?pagina=N` fuera de rango devuelve el mismo HTML que pagina 1, sin fin | Tope duro `MAX_PAGES_PER_REGION = 15`. |
| `DEFAULT_DB_PATH` hardcodeado a `/app/data/casas.db` crea DB fantasma en bare-metal sin `--db` | Pasar `--db data/casas.db` fuera de Docker, o usar `docker compose run`. |
| `docker compose run`/`up` falla por pool de subredes agotado | `network_mode: bridge`, o reusar una red externa YA EXISTENTE (`ia-net`) en vez de crear una nueva (sesion 5). |
| `git push` falla con "could not read Username" pese a `nas_git_auth_status` en verde | `git -c credential.helper='store --file=/volume1/docker/.deploy/.git-credentials' push origin main`. |
| Ruta `/listings/{portal}/{portal_listing_id}` 404 generico | `portal_listing_id` de escapadarural contiene `/` -> usar conversor `{portal_listing_id:path}`. |
| `curl localhost:PUERTO` desde `nas_run_command` da "Connection refused" pese a que el puerto esta publicado | `nas_run_command` corre dentro del contenedor `nas-mcp`, no en el host -> usar la IP LAN real (`192.168.1.205`) en vez de `localhost`. |
| Un resultado de `nas_run_command` parecio devolver la salida de otro comando (NAS compartido con otras automatizaciones/sesiones) | Envolver comandos con marcadores `echo MARKER_X ... echo MARKER_END` para verificar sin ambiguedad la correspondencia comando->salida. |
| **(sesion 5)** Ruta Cloudflare `gav.ruizespana.com` apuntaba al puerto de la API (8401) en vez de la web (8400) | Detectado por el usuario via captura de pantalla; pendiente de correccion manual (ver "Proximo paso"). No es un bug de codigo, es config externa desactualizada respecto al plan. |
| **(sesion 5)** Dashboard de Cloudflare colgado en spinner de carga al navegar desde una pestana nueva del grupo MCP de Claude-in-Chrome | No se investigo la causa raiz (podria ser session/cookies no compartidas de inmediato, o lentitud del SPA); se abandono el intento tras ~20s en vez de insistir a ciegas o intentar autenticar manualmente. Para cambios rapidos de un solo campo en dashboards ya abiertos por el usuario, puede ser mas eficiente pedirle que lo haga el mismo. |

## Lecciones nuevas (para futuras sesiones)

- Ante un fallo silencioso (0 resultados, sin excepcion), diagnosticar en capas: 1) respuesta HTTP cruda, 2) comparar con lo que espera el codigo, 3) reproducir paso a paso en el interprete real. Evita "arreglar a ciegas".
- Un sitio que no valida parametros de paginacion puede convertir un bug de filtrado en un bucle sin techo aparente -- los bucles de paginacion necesitan SIEMPRE un tope duro.
- En rutas FastAPI/Starlette, si un segmento de path puede contener `/` (ej IDs compuestos tipo "categoria/slug"), usar el conversor `{param:path}` desde el principio -- no asumir que un ID nunca tendra `/`.
- En este NAS: `nas_run_command` ejecuta dentro de un contenedor (`nas-mcp`), no en el host -- para probar servicios de OTROS contenedores usar la IP LAN del NAS, nunca `localhost`.
- En este NAS: `nas_git_auth_status` en verde no garantiza que `git push` funcione desde `nas_run_command` -- pasar el `credential.helper` explicito en el comando.
- Comandos largos (docker build, etc.) pueden superar el timeout de `nas_run_command` incluso cuando el proceso termina bien server-side -- usar `background=True` + `nas_job_status`, y verificar con un comando corto si hay dudas.
- El NAS puede estar compartido con otras automatizaciones al mismo tiempo (visto: jobs de `n8n-mcp` corriendo en paralelo) -- en comandos cortos ambiguos, usar marcadores `echo MARKER...` para confirmar que la salida corresponde al comando enviado.
- **(sesion 5)** Si dos servicios Docker Compose necesitan resolverse por nombre y el NAS tiene el pool de subredes agotado, la solucion no es "crear una red nueva mas pequena" sino **reusar una red bridge externa ya existente** (`external: true` en el compose) que otro proyecto del NAS ya creo (ej. `ia-net`). Evita el problema de raiz sin negociar tamanos de subred.
- **(sesion 5)** No dar por hecho que una configuracion externa (Cloudflare, DNS, etc.) coincide con el plan documentado -- verificar el estado real (screenshot o dashboard) antes de asumir que "solo falta levantar el contenedor". En este caso la ruta llevaba tiempo apuntando al puerto equivocado sin que nadie lo hubiera notado.
- **(sesion 5)** Para ediciones triviales de un solo campo en un dashboard que el usuario YA tiene abierto y logueado, considerar pedirselo directamente en vez de replicar la navegacion en una pestana nueva del MCP (que puede no tener sesion activa de inmediato y quedarse colgada).

## Pendientes operativos (para arrancar la proxima sesion)

- [ ] Leer este HANDOFF y CLAUDE.md del proyecto.
- [ ] Preguntar al usuario si ya corrigio la ruta `gav.ruizespana.com` -> 8400 en Cloudflare.
- [ ] Verificar que `casa-finder-api-1` y `casa-finder-web-1` siguen arriba: `docker ps --filter name=casa-finder` (usar IP LAN, no localhost).
- [ ] Si la ruta Cloudflare ya esta corregida, probar `https://gav.ruizespana.com` en un navegador real.
- [ ] (Opcional) Poblar `data/casas.db` con mas regiones.
- [ ] (Opcional) Bajar `image0.png` (logo Hokusai) cuando el usuario lo apruebe.

## Estado actual del repo

```
/volume1/docker/casa-finder/
├── .gitignore
├── CLAUDE.md                              (actualizado sesion 5)
├── HANDOFF.md                             (este archivo)
├── README.md
├── docker-compose.yml                     (scraper + api + web, sesion 5)
├── scraper/
│   ├── Dockerfile
│   ├── requirements.txt                   (+ brotli)
│   ├── __init__.py
│   ├── models.py
│   ├── store.py                           (+ funciones de consulta)
│   ├── run.py
│   ├── seeds_import.py
│   └── portals/
│       ├── __init__.py
│       ├── base.py
│       └── escapadarural.py               (fix ancestros + tope paginas)
├── api/
│   ├── __init__.py
│   ├── main.py
│   ├── requirements.txt
│   └── Dockerfile
├── web/                                   (NUEVO sesion 5)
│   ├── dist/
│   │   └── index.html
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
└── image1.png                          (logo 2: historico viajes GAV)
```

## Servicios corriendo ahora mismo en el NAS

| Contenedor | Puerto | Estado |
|---|---|---|
| `casa-finder-api-1` | `192.168.1.205:8401` -> 8000 | Up, `restart: unless-stopped`, red `ia-net` |
| `casa-finder-web-1` | `192.168.1.205:8400` -> 80 | Up, `restart: unless-stopped`, red `ia-net` |

(`scraper` no queda corriendo -- es un CLI de un solo uso via `docker compose run --rm scraper`.)

## Commits de esta sesion (sesion 5)

- `3817132` -- feat(web): paso 4 -- web publica Alpine.js + nginx sobre la API.

Pusheado a `origin/main`.