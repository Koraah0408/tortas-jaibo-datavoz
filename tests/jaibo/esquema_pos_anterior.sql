-- Réplica del esquema del POS anterior de Tortas Jaibo (inferido de sus DAO de Java).
-- SOLO para pruebas locales del conector de DataVoz; no se usa contra Supabase.

create table productos (
    id serial primary key, nombre text not null, precio numeric(10, 2), categoria text, ruta_imagen text,
    stock integer, es_personalizable boolean default false, permite_guisos_extra boolean default false,
    esta_activo boolean default true);

create table ingredientes (
    id serial primary key, nombre text not null, precio_adicional numeric(10, 2) default 0, categoria text);

create table producto_ingredientes (
    id_producto integer references productos (id), id_ingrediente integer references ingredientes (id),
    grupo text, tipo_grupo text);

create table promociones (
    id serial primary key, nombre text not null, precio_promocional numeric(10, 2), esta_activa boolean default true);

create table detalle_promociones (
    id_promocion integer references promociones (id), id_producto integer references productos (id));

create table ventas (
    id serial primary key, fecha_hora timestamptz not null, monto_total numeric(10, 2), metodo_pago text,
    canal_venta text, tipo_orden text, iva numeric(10, 2) default 0, total_con_iva numeric(10, 2),
    estado text, numero_orden_dia integer);

create table detalle_ventas (
    id serial primary key, id_venta integer references ventas (id), id_producto integer references productos (id),
    cantidad integer, precio_unitario numeric(10, 2), notas text);

-- Tablas con datos personales: existen en el POS pero DataVoz NO debe poder leerlas
create table empleados (id serial primary key, nombre text, empresa text, limite_credito numeric(10, 2));
create table creditos_empleados (
    id serial primary key, id_empleado integer references empleados (id), id_venta integer references ventas (id),
    monto_credito numeric(10, 2), monto_excedente_pagado numeric(10, 2), metodo_pago_excedente text, estado text,
    fecha date);
create table pagos_deuda (id serial primary key, id_empleado integer, monto numeric(10, 2), fecha date);
create table cortes_caja (id serial primary key, fecha date, fondo_inicial numeric(10, 2));
