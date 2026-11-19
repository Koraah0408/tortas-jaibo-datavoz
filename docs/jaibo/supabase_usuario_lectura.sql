-- =====================================================================================
-- DataVoz · Usuario de SOLO LECTURA para la base del POS de Tortas Jaibo (Supabase)
-- =====================================================================================
-- Qué hace:
--   1. Crea el esquema "datavoz" con VISTAS que muestran solo lo necesario para el análisis
--      (ventas, productos, ingredientes y promociones). NO incluye empleados, créditos,
--      pagos de deuda ni las notas libres de los pedidos.
--   2. Crea el usuario "datavoz_lector", que solo puede LEER esas vistas:
--        - no puede escribir, borrar ni modificar nada (transacciones de solo lectura),
--        - máximo 2 conexiones a la vez y consultas de máximo 20 segundos,
--        - no tiene acceso a las tablas originales del esquema public.
--
-- Qué NO hace: no modifica ninguna tabla ni dato, no cambia el programa del POS y no afecta
-- la venta en curso. Crear vistas no bloquea las tablas.
--
-- Cómo usarlo:
--   1. Supabase → tu proyecto → SQL Editor → New query.
--   2. Pega este archivo y cambia CAMBIA_ESTA_CONTRASEÑA por una contraseña larga y nueva
--      (no reutilices la del POS).
--   3. Run. Si algún nombre de columna no existe, Supabase lo dirá: avísale al equipo.
--   4. Para quitarlo todo en cualquier momento, usa el bloque "DESHACER" al final.
--
-- El esquema "datavoz" no queda expuesto en la API pública de Supabase (solo "public" lo está).
-- =====================================================================================

begin;

create schema if not exists datavoz;

-- Encabezado de cada venta (sin datos de empleados ni de clientes)
create or replace view datavoz.ventas as
select id, fecha_hora, monto_total, metodo_pago, canal_venta, tipo_orden,
       iva, total_con_iva, estado, numero_orden_dia
from public.ventas;

-- Productos vendidos en cada venta (sin la columna "notas", que es texto libre)
create or replace view datavoz.detalle_ventas as
select id_venta, id_producto, cantidad, precio_unitario
from public.detalle_ventas;

create or replace view datavoz.productos as
select id, nombre, precio, categoria, stock, es_personalizable, permite_guisos_extra, esta_activo
from public.productos;

create or replace view datavoz.ingredientes as
select id, nombre, precio_adicional, categoria
from public.ingredientes;

create or replace view datavoz.producto_ingredientes as
select id_producto, id_ingrediente, grupo, tipo_grupo
from public.producto_ingredientes;

create or replace view datavoz.promociones as
select id, nombre, precio_promocional, esta_activa
from public.promociones;

create or replace view datavoz.detalle_promociones as
select id_promocion, id_producto
from public.detalle_promociones;

-- Usuario de solo lectura con límites para no cargar la base de producción
create role datavoz_lector with login password 'CAMBIA_ESTA_CONTRASEÑA' connection limit 2;
alter role datavoz_lector set default_transaction_read_only = on;
alter role datavoz_lector set statement_timeout = '20s';
alter role datavoz_lector set idle_in_transaction_session_timeout = '30s';

revoke all on schema public from datavoz_lector;
grant usage on schema datavoz to datavoz_lector;
grant select on all tables in schema datavoz to datavoz_lector;

commit;

-- Comprobación (debe devolver números, no errores):
-- select (select count(*) from datavoz.ventas) as ventas, (select count(*) from datavoz.detalle_ventas) as renglones;

-- =====================================================================================
-- DESHACER (quita el usuario y las vistas; no toca tus datos):
-- drop owned by datavoz_lector;
-- drop role datavoz_lector;
-- drop schema datavoz cascade;
-- =====================================================================================
