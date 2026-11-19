# Diccionario de datos · Tienda de abarrotes (DataVoz)

Base de datos DuckDB con las ventas de un año (2025) de una tienda de abarrotes familiar en Ciudad Madero, Tamaulipas. Todos los montos están en pesos mexicanos (MXN). Los datos son sintéticos y no contienen información personal.

## Tabla ventas (una fila por producto vendido en un ticket)
Cada fila es un renglón de un ticket de venta: un producto, la cantidad vendida, su precio y el importe. Columnas principales: id_venta (entero, identificador del renglón), ticket (texto, folio del ticket; varios renglones pueden compartir ticket), fecha (DATE), hora (texto 'HH:MM'), producto (texto, nombre exacto del producto), categoria (texto), cantidad (entero, unidades vendidas), precio_unitario (decimal, precio cobrado por unidad, ya con descuento si hubo promoción), total (decimal, cantidad × precio_unitario, importe del renglón en pesos), metodo_pago ('efectivo', 'tarjeta' o 'transferencia'), promocion (texto con el nombre de la promoción aplicada; NULL si no hubo), en_promocion (BOOLEAN).

## Columnas de calendario en ventas
La tabla ventas incluye columnas derivadas de la fecha para facilitar filtros: anio (entero, 2025), mes (entero 1 a 12; 1 = enero, 12 = diciembre), nombre_mes (texto en minúsculas: 'enero', 'febrero', ..., 'diciembre'), dia (día del mes 1 a 31), dia_semana (texto en minúsculas sin acento: 'lunes', 'martes', 'miercoles', 'jueves', 'viernes', 'sabado', 'domingo'), num_dia_semana (1 = lunes ... 7 = domingo), semana (semana ISO del año, 1 a 53), trimestre (1 a 4), hora_del_dia (entero 0 a 23, hora en que se hizo la venta), es_fin_de_semana (BOOLEAN, sábado o domingo), es_quincena (BOOLEAN, días de pago de quincena: 15, 16, 17 y los dos últimos días del mes y los días 1 y 2).

## Métricas de venta: unidades, importe, tickets
"Ventas" puede significar unidades o dinero. Unidades vendidas = SUM(cantidad). Importe o ingresos vendidos en pesos = SUM(total). Número de tickets o de compras = COUNT(DISTINCT ticket). Ticket promedio = SUM(total) / COUNT(DISTINCT ticket). Si el usuario pregunta "qué se vendió más/menos" de un producto sin aclarar, se usan unidades (SUM(cantidad)); si pregunta "cuánto vendí", "cuánto dinero", "ingresos" o "ventas totales", se usa SUM(total).

## Tabla productos (catálogo)
Catálogo con los 150 productos de la tienda. Columnas: producto (texto, nombre exacto, mismo valor que ventas.producto), categoria (texto), precio_lista (decimal, precio normal de venta), costo_unitario (decimal, lo que le cuesta a la tienda), margen_unitario (precio_lista - costo_unitario, ganancia por unidad), margen_pct (margen como porcentaje del precio de lista). Se une con ventas por la columna producto.

## Tabla inventario_diario (existencias por día)
Una fila por producto y por día del año. Columnas: fecha (DATE), producto, categoria, existencia_inicial (unidades al abrir), entradas (unidades recibidas del proveedor ese día; el resurtido es lunes y jueves), unidades_vendidas, existencia_final (unidades al cierre), sin_existencia (BOOLEAN, TRUE si el producto terminó el día en cero, es decir, un día sin existencias o agotado), anio, mes. Para contar días sin existencias de un producto en un mes: COUNT(*) FILTER (WHERE sin_existencia) o SUM(CASE WHEN sin_existencia THEN 1 ELSE 0 END), consultando inventario_diario directamente (FROM inventario_diario WHERE producto = ... AND mes = ...). NO se debe unir inventario_diario con ventas por fecha para contar días sin existencias: los días agotados no tienen ventas, así que esa unión siempre da cero.

## Tabla promociones
Una fila por producto incluido en cada promoción. Columnas: promocion (texto, nombre de la promoción), producto, categoria, fecha_inicio (DATE), fecha_fin (DATE), descuento_pct (porcentaje de descuento sobre el precio de lista; un 2x1 equivale a 50 y un 3x2 a 33), dias_duracion (entero). Para evaluar si una promoción funcionó se comparan las unidades vendidas por día durante la promoción contra el mismo número de días inmediatamente antes de que empezara. Las unidades por día se calculan dividiendo entre los días calendario del periodo (dias_duracion), NO entre COUNT(DISTINCT fecha) de ventas, porque hay días en que un producto no se vende y contarlos subiría el promedio.

## Categorías de productos
Hay 10 categorías (valores exactos de la columna categoria): 'Abarrotes', 'Bebidas', 'Lácteos y huevo', 'Botanas', 'Dulces y galletas', 'Limpieza del hogar', 'Higiene personal', 'Panadería y tortillas', 'Enlatados y conservas', 'Cervezas y vinos'. Las categorías llevan acentos y mayúscula inicial; para filtrar de forma flexible se puede usar categoria ILIKE '%lacteos%' o comparar con el valor exacto.

## Nombres de productos
Los nombres de producto incluyen la presentación, por ejemplo 'Refresco 3 L sabor uva', 'Refresco de cola 600 ml', 'Huevo blanco 12 pzas', 'Cerveza clara lata 355 ml', 'Tortillas de maíz 1 kg'. Cuando el usuario menciona un producto de forma aproximada ("el refresco de uva", "las tortillas") se debe usar el nombre exacto del catálogo o un filtro ILIKE con las palabras clave (producto ILIKE '%uva%'). Si hay varias presentaciones posibles (por ejemplo refresco de cola de 600 ml, 2 L y 3 L) y el usuario no especifica, se agrupan todas con ILIKE o se muestran por separado.

## Convenciones de SQL (DuckDB)
Solo se permiten consultas SELECT de lectura. Los meses se filtran con la columna mes (entero) o nombre_mes. Para comparar periodos se usan agregaciones condicionales, por ejemplo SUM(cantidad) FILTER (WHERE mes = 11) AS noviembre. Para porcentajes usar ROUND(100.0 * a / NULLIF(b, 0), 1). Redondear dinero con ROUND(x, 2). Para sumar o restar días a una fecha usar fecha - INTERVAL 7 DAY o fecha - CAST(n AS INTEGER) (restar un BIGINT a un DATE produce error). Limitar listados largos con LIMIT. Los datos cubren del 1 de enero al 31 de diciembre de 2025; si el usuario menciona un mes sin año, se asume 2025.
