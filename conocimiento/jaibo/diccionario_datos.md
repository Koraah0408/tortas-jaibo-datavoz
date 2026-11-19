# Diccionario de datos · Tortas Jaibo (copia de solo lectura del POS)

Copia local (DuckDB) de las ventas del punto de venta de Tortas Jaibo, actualizada desde Supabase con un usuario de solo lectura. Montos en pesos mexicanos (MXN); fechas y horas en hora de Monterrey. No contiene empleados, créditos personales ni notas de los pedidos.

## Tabla ventas (una fila por producto vendido en una orden completada)
Cada fila es un renglón de una orden cobrada (las órdenes canceladas no están aquí). Columnas: id_venta (renglón), ticket (texto, número de orden; varios renglones comparten ticket), id_orden (entero, mismo valor que ticket), fecha (DATE), hora ('HH:MM'), producto (nombre exacto), categoria ('Principal', 'Desayuno', 'Del Dia', 'Bebidas' o 'Interno'), cantidad (piezas u órdenes, entero), precio_unitario (precio cobrado en ese momento: los precios han subido con el tiempo), total (cantidad × precio_unitario, SIN descuentos de promociones ni extras), canal ('Local', 'Didi', 'Rappi', 'Legacy', 'Automatas'), tipo_orden ('Para Llevar' o 'Para Aquí'), metodo_pago.

## Tabla ordenes (una fila por orden o ticket, incluye canceladas)
Columnas: id_orden, fecha, hora, numero_orden_dia (empieza en 1 cada día), canal, tipo_orden, metodo_pago, subtotal (suma de renglones), monto_total (lo que realmente se cobró, sin IVA), descuento (cuánto quedó el total por debajo del subtotal: promociones), extras (cuánto quedó por encima: guisos o ingredientes extra y el sobreprecio de las apps), iva, total_con_iva (IVA solo cuando se pidió factura), estado ('Completada' o 'Cancelada por Modificación'), cancelada (BOOLEAN), renglones. Para dinero cobrado, número de órdenes y ticket promedio usar esta tabla con WHERE NOT cancelada. Los pedidos que se corrigieron, se rehicieron, se tuvieron que rehacer o se capturaron mal son las órdenes con cancelada = TRUE (estado 'Cancelada por Modificación'): cuéntalos con COUNT(*) WHERE cancelada; nunca busques palabras como 'rehacer' o 'corregir' en estado.

## Columnas de calendario en ventas y ordenes
Ambas tablas tienen: anio, mes (1-12), nombre_mes ('enero'...'diciembre'), dia, dia_semana ('lunes', 'martes', 'miercoles', 'jueves', 'viernes', 'sabado', 'domingo'), num_dia_semana (1 = lunes ... 7 = domingo), semana (ISO), trimestre, hora_del_dia (0-23), es_fin_de_semana (BOOLEAN) y es_quincena (BOOLEAN: días 15, 16, 17, los dos últimos del mes y los días 1 y 2).

## Métricas de Tortas Jaibo
Unidades vendidas de un producto = SUM(cantidad) en ventas. Dinero realmente cobrado = SUM(monto_total) en ordenes WHERE NOT cancelada (ya incluye descuentos y extras). Venta de un producto = SUM(total) en ventas (precio del renglón; no incluye extras ni descuentos). Órdenes = COUNT(*) en ordenes WHERE NOT cancelada. Ticket promedio = AVG(monto_total) de órdenes no canceladas. Si preguntan "cuánto vendí" en dinero se usa monto_total de ordenes; si preguntan por un producto se usa ventas. Para rankings de productos excluir la categoría 'Interno' (cargos, no productos) con WHERE categoria <> 'Interno'.

## Tortas y pan
Las tortas son 'Barda normal', 'Mega barda', 'Pierna normal', 'Mega pierna', 'Mixta normal', 'Mega mixta', 'Barbacoa normal' y 'Mega barbacoa' (estas dos son las tortas de barbacoa). Están en la categoría 'Principal' junto con gorditas, bocoles y tacos: no existe una categoría 'Tortas', se filtran con producto IN (...). Cada torta usa un pan: las "normal" usan pan normal y las "Mega" pan mega. Panes normales = SUM(cantidad) FILTER (WHERE producto IN ('Barda normal', 'Pierna normal', 'Mixta normal', 'Barbacoa normal')); panes mega = SUM(cantidad) FILTER (WHERE producto IN ('Mega barda', 'Mega pierna', 'Mega mixta', 'Mega barbacoa')).

## Barbacoa, tacos, gorditas y bocoles
'Tacos de barbacoa', 'Gordita' y 'Bocoles' se venden por pieza (cantidad = piezas). 'Barbacoa' (sin otra palabra) es barbacoa por peso: precio_unitario 550 = 1 kg y 275 = 1/2 kg, así que kilos = SUM(cantidad * precio_unitario / 550.0) WHERE producto = 'Barbacoa' AND precio_unitario > 0. 'Consome Barbacoa' es un platillo de la categoría 'Del Dia'. La 'Gordita' cobra según el guiso: muchos renglones de gordita quedaron en $0 porque el cobro va en el total de la orden, así que para dinero de gorditas no sirve ventas.total.

## Canales y formas de pago
'Local' es el mostrador (metodo_pago 'Efectivo', 'Tarjeta' o 'Transferencia'). 'Didi' (pago 'Didi' o 'Didi Efectivo') y 'Rappi' (pago 'Rappi') son pedidos por aplicación; en esos canales el total cobrado suele ser mayor que la suma de renglones porque los precios en la app son más altos (columna extras). 'Legacy' y 'Automatas' son empresas cuyos empleados compran a crédito: Legacy paga con 'Crédito Empleado' y Automatas con 'Crédito Automatas'; ese dinero no entra a la caja el mismo día. 'Crédito y Efectivo' es un crédito con una parte en efectivo.

## Tabla productos (catálogo)
Columnas: id_producto, producto, categoria, precio (precio actual), stock (existencias; solo se lleva en bebidas, NULL en lo demás), activo, es_personalizable, permite_guisos_extra. Se une con ventas por la columna producto. Productos especiales: '--' es una bebida que se registró sin nombre; 'Cargo Extra' (categoría 'Interno') es un cargo adicional, no un platillo; 'Prueba4' y 'Pruebanumero3' son productos de prueba sin ventas.

## Guisos e ingredientes
Tabla ingredientes: id_ingrediente, ingrediente, precio_adicional (lo que cuesta como extra), categoria ('Guisos', 'Ingredientes' u 'Otros'). Tabla producto_ingredientes: producto, ingrediente, grupo, tipo_grupo, precio_adicional: qué guisos o ingredientes puede llevar cada producto. Las ventas no registran qué guiso se eligió.

## Tabla promociones
Una fila por producto incluido en cada promoción: promocion (nombre, por ejemplo '4 Tacos x $105' o 'Combo Mega pierna + Horchata'), precio_promocional, activa (hay promociones viejas inactivas), producto. El efecto de las promociones se ve en ordenes.descuento.

## Convenciones de SQL (DuckDB)
Solo SELECT. Para comparar periodos usar SUM(...) FILTER (WHERE ...). Porcentajes con ROUND(100.0 * a / NULLIF(b, 0), 1). Dinero con ROUND(x, 2). Para "la semana pasada" o "el último mes" usar la fecha máxima de los datos como referencia: WHERE fecha > (SELECT MAX(fecha) FROM ordenes) - INTERVAL 7 DAY. Para promedios por día dividir entre los días que abrió el negocio en el periodo (COUNT(DISTINCT fecha) de ordenes del periodo, contado aparte y sin filtrar productos), no entre los días en que se vendió un producto. Últimamente el negocio no abre los lunes. Los datos abarcan más de un año: si la pregunta dice un día o un mes SIN año, usa el más reciente que exista (p. ej. WHERE fecha = (SELECT MAX(fecha) FROM ordenes WHERE month(fecha) = 11 AND day(fecha) = 18)), nunca supongas un año.

## Tabla reportes_diarios (reportes financieros que se mandan por Gmail cada noche)
Un renglón por día con las cifras del PDF «Reporte Financiero de Ventas» que el POS envía por correo: fecha, ingresos_brutos (ventas reales del día), ingresos_netos (brutos + deuda pagada − egresos), egresos (gastos registrados en caja), deuda_pagada (créditos que se cobraron ese día), fondo_inicial (dinero con el que abrió la caja), efectivo, tarjeta, transferencia, didi, rappi, credito (ventas a crédito de Legacy y Automatas), credito_otorgado, total_apps, total_ordenes y ticket_promedio. Úsala para preguntas de caja, egresos, fondo inicial, cuánto entró en efectivo o «cómo acabó el reporte de un día»; para ventas por producto u hora usa ventas y ordenes. Puede no tener todos los días: solo los reportes que ya se descargaron de Gmail. Para un día sin año: WHERE fecha = (SELECT MAX(fecha) FROM reportes_diarios WHERE month(fecha) = 11 AND day(fecha) = 18).
