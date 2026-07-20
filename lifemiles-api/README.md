# LifeMiles Deals API (no oficial)

Monitor que busca continuamente disponibilidad de **premios (redención de millas)**
en LifeMiles para un conjunto de destinos y te **avisa cuando aparece una ganga**.
Expone una pequeña API HTTP para consultar las ofertas y los deals detectados.

> **Qué hace:** busca disponibilidad, guarda el histórico y alerta cuando las
> millas bajan de un umbral o caen respecto al mínimo histórico de esa ruta.
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
- **Polling respetuoso.** El scheduler está configurado conservador a propósito
  (15 min por ciclo, 4 s entre requests, con jitter). Bajar esto y "buscar todo
  el tiempo" de forma agresiva es la manera más rápida de que te **bloqueen la
  cuenta o la IP**. No lo hagas.
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

Los 5 destinos que vienen de ejemplo (editables en `config.yaml`):
BOG→MAD, BOG→MIA, BOG→SCL, MDE→JFK, BOG→GRU.

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

## Pasar a modo `live`: capturar el endpoint real

1. Entrá a lifemiles.com con tu cuenta y hacé una búsqueda de premios.
2. Abrí las **DevTools → Network** y buscá la request XHR/fetch que devuelve la
   disponibilidad (JSON con millas por vuelo).
3. Copiá la **URL**, los **headers** (incluida la auth) y el **body**.
4. Volcá esos valores en `.env` (`LIFEMILES_BASE_URL`, `LIFEMILES_SEARCH_PATH`,
   `LIFEMILES_API_KEY`) y ajustá los dos puntos marcados en
   `app/client.py`: **`_build_request`** (cómo se arma el body) y
   **`_parse_response`** (cómo se leen las millas de la respuesta).
5. Poné `LIFEMILES_MODE=live` y probá con `python scan_once.py` (un solo ciclo)
   antes de dejar el monitor corriendo.

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
```

## Tests

```bash
pip install pytest
python -m pytest tests/ -q
```
