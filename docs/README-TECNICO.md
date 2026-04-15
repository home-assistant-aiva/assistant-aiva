# AIVA Home Assistant - README tecnico

## Instalacion

Instalar como custom integration de Home Assistant:

```text
custom_components/aiva
```

Luego reiniciar Home Assistant y agregar la integracion desde:

```text
Ajustes > Dispositivos y servicios > Anadir integracion > AIVA
```

## Configuracion

El config flow solicita al iniciar la activacion:

- `base_url`: URL base del backend AIVA.
- `home_name`: nombre visible de la casa, opcional.
- `plan`: `base`, `smart` o `premium`.

Luego el backend genera el `pairing_code` y la integracion muestra los estados:

- `installed`: AIVA esta instalado, pero todavia no activado.
- `awaiting_pairing`: se genero el codigo y falta completar la vinculacion externa.
- `awaiting_payment`: la vinculacion ya fue recibida y falta confirmar el pago de instalacion.
- `active`: el backend ya confirmo la activacion y devolvio las credenciales finales.

La integracion guarda:

- `base_url`
- `home_id`
- `home_name`
- `secret`
- `plan`

La integracion mantiene lectura de `pairing_code` y `linking_code` solo para compatibilidad con config entries antiguas.

## Options flow

Desde las opciones de la integracion se puede cambiar sin reinstalar:

- `base_url`
- `scan_interval`

Home Assistant recarga la config entry al guardar opciones para aplicar el nuevo cliente y el nuevo intervalo.

## Backend esperado

Los endpoints son relativos a `base_url`:

- `POST /pairing/start`
- `POST /pairing/status`
- `POST /pair`
- `POST /heartbeat`
- `POST /entities/sync`

Las llamadas posteriores al pairing usan:

```http
x-aiva-secret: <redacted>
```

## Pairing

### Activacion comercial

Request:

```http
POST /pairing/start
Content-Type: application/json
```

```json
{
  "home_name": "Casa Principal",
  "plan": "smart"
}
```

Response:

```json
{
  "ok": true,
  "pairing_code": "<redacted>",
  "home_name": "Casa Principal",
  "plan": "smart",
  "state": "awaiting_pairing"
}
```

Consulta de estado:

```http
POST /pairing/status
Content-Type: application/json
```

```json
{
  "pairing_code": "<redacted>"
}
```

Mientras falta pago:

```json
{
  "ok": true,
  "state": "awaiting_payment"
}
```

Cuando queda activo:

```json
{
  "ok": true,
  "state": "active",
  "home_id": "uuid-del-hogar",
  "home_name": "Casa Principal",
  "secret": "<redacted>",
  "plan": "smart"
}
```

### Pairing legacy

Request:

```http
POST /pair
Content-Type: application/json
```

```json
{
  "pairing_code": "<redacted>",
  "home_name": "Casa Principal"
}
```

Response:

```json
{
  "ok": true,
  "home_id": "uuid-del-hogar",
  "home_name": "Casa Principal",
  "secret": "<redacted>",
  "plan": "smart"
}
```

## Heartbeat

```json
{
  "home_id": "uuid-del-hogar"
}
```

Response:

```json
{
  "ok": true,
  "home_id": "uuid-del-hogar",
  "heartbeat_at": "2026-04-14T00:00:00+00:00"
}
```

## Sync de entidades

```json
{
  "home_id": "uuid-del-hogar",
  "entities": [
    {
      "entity_id": "light.luz_living",
      "domain": "light",
      "friendly_name": "Luz Living",
      "state": "on",
      "area": "Living",
      "device_class": null,
      "unit_of_measurement": null,
      "last_changed": "2026-04-14T00:00:00+00:00",
      "last_updated": "2026-04-14T00:00:00+00:00"
    }
  ]
}
```

## URL directa hoy

Usar una URL accesible desde Home Assistant:

```text
http://<host>:<puerto>
```

## Proxy o reverse proxy manana

Usar el dominio como `base_url`:

```text
https://<dominio-publico>
```

El proxy debe reenviar estos paths al backend AIVA:

```text
/pair
/heartbeat
/entities/sync
```

Tambien debe preservar el header:

```text
x-aiva-secret
```

No hace falta cambiar la arquitectura de la integracion mientras el proxy mantenga esos paths.
