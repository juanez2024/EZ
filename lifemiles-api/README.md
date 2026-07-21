# LifeMiles Deals API (no oficial)

Monitor que busca 1 vez al día disponibilidad de **premios (redención de millas)**
en LifeMiles para un conjunto de destinos y te **avisa cuando aparece una ganga**.
Expone una pequeña API HTTP para consultar las ofertas y los deals detectados.

**Toda Star Alliance, no solo Avianca.** LifeMiles permite redimir en cualquier
socio de Star Alliance (Lufthansa `LH`, Swiss `LX`, Turkish `TK`, United `UA`,
ANA `NH`, Air Canada `AC`, Austrian `OS`…). La búsqueda devuelve la
disponibilidad de esos socios, así que podés monitorear **rutas donde Avianca no
vuela directo** (ej. Tokio) o **premium economy a Europa** (Lufthansa/Swiss/
Turkish). Cada oferta y cada alerta muestran la aerolínea operadora (`carrier`).

> **Qué hace:** busca disponibilidad (economy / premium economy / business),
> guarda el histórico y alerta cuando las millas bajan de un umbral o caen
> respecto al mínimo histórico de esa ruta+cabina.
>
> **Qué NO hace (a propósito):** **no redime ni compra automáticamente.**
> Redimir es una transacción financiera irreversible (emisión de tickets,
> precios que cambian entre el clic y la confirmación, riesgo de bloqueo de
> cuenta). La herramienta te deja la ganga servida; **la redención la confirmás
> vos a mano.**

## Antes de usarlo — cosas importantes

- **LifeMiles no tiene API pública oficial.** El modo `live` reproduce la misma
  request que hace el sitio web de LifeMiles al buscar premios. Ese contrato no
  está documentado, cambia con el tiempo, y **capturarlo/usarlo puede violar los
  Términos y Condiciones de LifeMiles.** Usalo bajo tu responsabilidad y con tu
  propia cuenta.
- **Polling respetuoso.** El scheduler corre **1 vez al día** (± jitter de hasta
  1 h), 4 s entre requests. Bajarlo y "buscar todo el tiempo" de forma agresiva
  es la manera más rápida de que te **bloqueen la cuenta o la IP**. No lo hagas.
- Empezá siempre en **modo `mock`** (por defecto) para validar el pipeline sin
  tocar la red ni arriesgar la cuenta.

## Instalación

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # completá tus valores
```

## Configuración

- **`.env`** — credenciales, endpoint, modo (`mock`/`live`), webhook de alertas.
- **`config.yaml`** — destinos, cabinas, ventana de fechas, umbrales de deal y
  el ritmo del scheduler.

Rutas de ejemplo (editables en `config.yaml`):
- **Núcleo Avianca:** BOG→MAD, BOG→MIA, BOG→SCL, MDE→JFK, BOG→GRU.
- **Socios Star Alliance:** BOG→FRA (Lufthansa, premium economy), BOG→IST
  (Turkish, premium economy), BOG→ZRH (Swiss, premium economy), BOG→NRT
  (ANA/United, Avianca no vuela), EZE→FRA (Lufthansa).

Para alertar **solo** de ciertas aerolíneas, poné sus códigos IATA en
`deals.only_carriers` (ej. `[LH, LX, TK, OS]`). Vacío = todas las Star Alliance.

## Uso

### Servidor + monitor en segundo plano

```bash
python run.py
```

Endpoints:

| Método | Ruta        | Descripción                                        |
|--------|-------------|----------------------------------------------------|
| GET    | `/health`   | Estado y resumen del último ciclo                  |
| GET    | `/deals`    | Deals detectados (más recientes primero)           |
| GET    | `/offers`   | Mejores disponibilidades vistas (millas asc)       |
| GET    | `/routes`   | Rutas monitoreadas                                 |
| POST   | `/scan`     | Dispara un ciclo inmediato (corre en background)   |

### Un solo ciclo desde la terminal (o cron externo)

```bash
python scan_once.py          # respeta el rate limit
python scan_once.py --fast   # sin pausas (solo para pruebas)
```

## Modo `live`: el endpoint real (ya cableado)

El endpoint de premios ya está identificado y **`_build_request` /
`_parse_response` están cableados a su contrato real**:

- **URL:** `POST https://api.lifemiles.com/svc/air-redemption-find-flight-private`
- **Headers:** `Accept`, `Content-Type`, `realm: lifemiles`,
  `Authorization: Bearer <JWT>`
- **Body/respuesta:** ver `capture/samples/lifemiles_capture.json` (ejemplo real
  completo, con el token enmascarado) y el fixture
  `tests/fixtures/air_redemption_bog_mad.json` que ejercita el parser en los
  tests (`tests/test_live_parser.py`).

### Autenticación: token que se renueva solo

El endpoint es privado y exige un **Bearer JWT del SSO de LifeMiles (Keycloak)**
que **vive solo unos minutos**. Hay dos caminos:

**A) Monitoreo autónomo — `refresh_token` (recomendado).** El módulo
`app/auth.py` renueva el access token solo contra el SSO en cada ciclo. Solo
tenés que darle un **refresh token una vez** (login manual en tu navegador,
nadie más toca tu contraseña):

1. `lifemiles.com` → logueate.
2. `F12` → **Network** → filtrá por `token`.
3. Abrí la request a `…/openid-connect/token`; en la respuesta JSON copiá el
   valor de `refresh_token`.
4. Pegalo en `.env` como `LIFEMILES_REFRESH_TOKEN=…`, dejá `LIFEMILES_API_KEY`
   vacío, poné `LIFEMILES_MODE=live`.

A partir de ahí el provider pide access tokens nuevos con
`grant_type=refresh_token` (client `lm-prd`), y como Keycloak **rota** el
refresh token en cada uso, lo persiste en `.lifemiles_token.json`
(gitignoreado) para sobrevivir reinicios. Fallback: si en vez del refresh token
ponés `LIFEMILES_USERNAME`/`LIFEMILES_PASSWORD`, intenta `grant_type=password`
(puede no andar si tu cuenta está federada).

> **Que dure meses, no minutos.** Un refresh token normal muere cuando expira la
> sesión SSO (~horas). Para un daemon conviene un refresh token
> **`offline_access`**, que no depende de la sesión. Si al loguearte agregás
> `offline_access` al scope, el `refresh_token` resultante es offline. Tu cuenta
> ya tiene el rol `offline_access` habilitado (visto en el JWT capturado).

**B) Corrida puntual — token manual.** Copiá un access token fresco de las
DevTools (header `Authorization`, sin `Bearer `), pegalo en `LIFEMILES_API_KEY`
y corré `python scan_once.py` **mientras el token siga vivo** (~minutos). Útil
para una prueba rápida sin configurar el refresh.

> **Nota sobre campos de sesión.** El body real trae `idCoti` y unos hashes
> `sch` derivados de la sesión web. El cliente los manda como opcionales
> (`LIFEMILES_ID_COTI`). El parser está 100% verificado contra la respuesta
> real; si el server llegara a exigir esos campos, se confirma con el primer
> round-trip en vivo y es un ajuste chico en `_build_request`.

### Re-capturar el contrato (si LifeMiles lo cambia)

> **Ojo con dónde corrés la captura.** LifeMiles requiere login y suele estar
> detrás de protección anti-bots. **La captura hay que hacerla en tu propia
> máquina**, con tu sesión iniciada. (En entornos de nube con egress
> restringido, lifemiles.com puede estar directamente bloqueado por política de
> red — ahí no se puede capturar; corré el tooling local.)

Tenés dos formas de capturar la request de disponibilidad. Ambas están en
`capture/` y no envían nada a ningún lado (todo el análisis es local).

### Opción A — HAR de Chrome DevTools (la más simple)

1. Chrome → lifemiles.com → logueate y hacé una búsqueda de premios.
2. `F12` → pestaña **Network** → repetí la búsqueda con Network abierto.
3. Click derecho en la lista → **"Save all as HAR with content"**.
4. `python capture/har_to_config.py lifemiles.har`

El script detecta el endpoint de premios y te imprime los valores para `.env`
(`LIFEMILES_BASE_URL`, `LIFEMILES_SEARCH_PATH`), los headers (los sensibles
enmascarados), el body de la request y las claves de la respuesta.

### Opción B — captura interactiva con Playwright

```bash
pip install -r capture/requirements-capture.txt
playwright install chromium
python capture/capture_playwright.py   # abre Chromium; buscá premios; Enter
```

Guarda las requests relevantes en `capture_out.json`.

### Si cambió la forma de la request/respuesta

Ajustá los dos puntos marcados en `app/client.py`: **`_build_request`** (cómo se
arma el body) y **`_parse_response`** (cómo se leen millas/cabina/aerolínea).
Actualizá también el fixture `tests/fixtures/air_redemption_bog_mad.json` con la
respuesta nueva y corré `pytest` para verificar el parser.

## Arquitectura

```
run.py            -> levanta FastAPI + monitor
scan_once.py      -> un ciclo suelto (CLI)
app/
  config.py       -> carga config.yaml + .env
  client.py       -> cliente de búsqueda (Mock / Live)  <- ajustar para live
  models.py       -> Offer, Deal
  storage.py      -> SQLite (histórico + dedup de deals)
  deals.py        -> detección de ofertas (umbral + caída histórica)
  notifier.py     -> alertas (log + webhook opcional)
  monitor.py      -> scheduler con rate limiting y jitter
  api.py          -> endpoints HTTP
tests/            -> pruebas del pipeline con el cliente mock
capture/          -> tooling LOCAL para capturar el endpoint real de LifeMiles
  har_to_config.py       -> HAR de Chrome -> valores de .env + mapeo (solo stdlib)
  capture_playwright.py  -> captura interactiva con Chromium
```

## Tests

```bash
pip install pytest
python -m pytest tests/ -q
```
