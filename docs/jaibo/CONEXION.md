# Conectar DataVoz al POS de Tortas Jaibo (solo lectura)

DataVoz **nunca escribe** en la base del POS ni consulta producción mientras los agentes trabajan.
Lo que hace es:

1. Con un usuario de solo lectura (`datavoz_lector`), abre **una** conexión, lee unas vistas y la cierra.
2. Guarda una copia local en `data/jaibo/jaibo.duckdb` (ignorada por git).
3. Los agentes hacen todas sus consultas sobre esa copia.

```
POS (Supabase, producción) ──solo lectura, 1 conexión──▶ data/jaibo/jaibo.duckdb ──▶ agentes DataVoz
```

## Qué protege a producción

| Protección | Dónde |
|---|---|
| El usuario solo ve el esquema `datavoz`, que contiene vistas con las columnas necesarias | `supabase_usuario_lectura.sql` |
| Sin acceso a `empleados`, `creditos_empleados`, `pagos_deuda` ni a `detalle_ventas.notas` (datos personales) | las vistas no los incluyen |
| Toda transacción es de solo lectura (`default_transaction_read_only = on`) | rol + opción de conexión |
| Máximo 2 conexiones, consultas de máximo 20 s, sesiones inactivas se cortan a los 30 s | rol |
| Una descarga cada 30 min como máximo, salvo que pulses «Actualizar» | `JAIBO_SINCRONIZAR_CADA_MIN` |

## Paso 1. Crear el usuario de solo lectura (una sola vez)

1. Abre tu proyecto en Supabase → **SQL Editor** → *New query*.
2. Pega el contenido de [`supabase_usuario_lectura.sql`](supabase_usuario_lectura.sql).
3. **Cambia `CAMBIA_ESTA_CONTRASEÑA`** por una contraseña nueva y larga (por ejemplo 24 letras y números).
   No reutilices la contraseña del POS.
4. Ejecuta la consulta (*Run*). Debe terminar sin errores.

> No agregues el esquema `datavoz` a *Settings → API → Exposed schemas*: así las vistas no quedan
> visibles por la API pública, solo por la conexión directa de este usuario.

Para deshacer todo, ejecuta las tres líneas del final del script (`drop owned by…`, `drop role…`, `drop schema…`).

## Paso 2. Copiar los datos de conexión al `.env`

1. En Supabase, pulsa **Connect** (arriba del panel) → pestaña *Connection string* → **Session pooler**.
   Funciona con IPv4; la conexión directa del plan gratuito solo funciona con IPv6.
2. De ahí toma el *host* (algo como `aws-0-<región>.pooler.supabase.com`) y el *usuario*, que aparece como
   `postgres.<id-del-proyecto>`. Cambia `postgres` por `datavoz_lector`.
3. En tu `.env` (copiado de `.env.example`) llena:

```ini
JAIBO_PG_HOST=aws-0-<región>.pooler.supabase.com
JAIBO_PG_PORT=5432
JAIBO_PG_DB=postgres
JAIBO_PG_USUARIO=datavoz_lector.<id-del-proyecto>
JAIBO_PG_CONTRASENA=<la contraseña que pusiste en el paso 1>
JAIBO_PG_SSLMODE=require
JAIBO_SINCRONIZAR_CADA_MIN=30
```

El `.env` nunca se sube a GitHub (está en `.gitignore`).

## Paso 3. Verificar que de verdad solo puede leer

```powershell
.\.venv\Scripts\python.exe -m datavoz.conectores.jaibo --verificar
```

Esta revisión no escribe nada: solo le pregunta a Postgres qué permisos tiene el usuario. Debe salir
`OK` en todo:

```
  OK    conectado como «datavoz_lector», sin privilegios de administrador
  OK    el rol es de solo lectura (default_transaction_read_only = on)
  OK    límites del rol: 2 conexiones, consultas de máximo 20s
  OK    lee datavoz.ventas (… filas)
  …
  OK    sin permiso de escritura en las vistas
  OK    sin acceso a las tablas originales (public)
  OK    sin permiso de escritura en public
  OK    no puede crear tablas en public
```

Si alguna línea dice `FALLA`, no uses la conexión hasta corregir los permisos.

## Paso 4. Usarlo

- Abre la app (`streamlit run app.py`). Trabaja directo con Tortas Jaibo: cada **Nueva conversación**
  actualiza la copia si tiene más de 30 min.
- **Actualizar ventas**, en la sección *Tus ventas* de la barra lateral, descarga una copia nueva en ese
  momento (≈1–3 s para ~8,000 órdenes).
- Sin conexión configurada ni copia, la app usa una **demostración con ventas simuladas** del mismo menú
  y lo indica en pantalla.
- Desde la terminal: `python -m datavoz.conectores.jaibo --sincronizar`.

## Paso 5 (opcional). Costos y comisiones reales

El **Asesor de negocio** (pan, rentabilidad por canal, promociones) usa supuestos mientras no tenga tus datos.
Para usar los reales:

```powershell
copy conocimiento\jaibo\costos.ejemplo.yaml data\jaibo\costos.yaml
```

Abre `data\jaibo\costos.yaml` y pon la comisión real de Didi y Rappi, tu margen de seguridad para el pan y, si los
tienes, los costos de ingredientes por pieza. Cambia `supuesto: true` a `supuesto: false` en lo que confirmes.
Ese archivo está dentro de `data/jaibo/`, así que **no se sube a GitHub**.

## Datos reales y privacidad

- `data/jaibo/` contiene ventas reales del cliente. Está en `.gitignore`: **no lo subas ni lo compartas**.
- Las trazas (`trazas/`) también pueden contener cifras reales y también están ignoradas.
- Para el repositorio y la evaluación se usan datos **sintéticos** con el mismo menú y estructura:
  `python scripts/generar_datos_jaibo.py` (ver `tests/jaibo/esquema_pos_anterior.sql`).
