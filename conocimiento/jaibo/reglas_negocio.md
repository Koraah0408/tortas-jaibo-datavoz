# Reglas y conocimiento del negocio · Tortas Jaibo

Lo marcado como SUPUESTO falta confirmarlo con el dueño; el Narrador debe presentarlo como estimación.

## Horario y momentos del día
El local vende aproximadamente de 9:00 a 19:00; la hora fuerte es de 14:00 a 16:00 y la mañana (9 a 12) es más tranquila. Los desayunos (huevos al gusto, quesadillas) se venden a lo largo del día, no solo en la mañana. Últimamente el negocio no abre los lunes. No hay que suponer que el fin de semana se vende más: hay que verlo en los datos de cada producto.

## Platillo del día
Los platillos de la categoría 'Del Dia' rotan según el día de la semana: lunes cecina de res, martes enmoladas, miércoles milanesa de pollo, jueves enchiladas con cecina o bistec a la mexicana, y viernes y sábado enchiladas suizas. Si un platillo del día se vende poco conviene compararlo contra el mismo día de otras semanas, no contra toda la semana.

## Compra y preparación de pan
Cada torta usa un pan: las "normal" pan normal y las "Mega" pan mega. El pan se compra cada mañana y lo que sobra se pierde o se vende como pan del día anterior. Una buena compra cubre la venta esperada del día más un margen de seguridad pequeño (SUPUESTO: 10 %). Para estimar el pan de mañana sirve el promedio de tortas del mismo día de la semana en las últimas 4 a 8 semanas, contando solo los días que abrió el negocio y ajustando si es quincena.

## Barbacoa
La barbacoa se usa en las tortas de barbacoa ('Barbacoa normal' y 'Mega barbacoa'), los tacos, el consomé y la barbacoa por peso. SUPUESTO: un taco lleva unos 40 g y una torta de barbacoa unos 120 g (normal) o 160 g (Mega).

## Canales de venta y comisiones
En Didi y Rappi los precios son más altos que en mostrador, pero las plataformas cobran comisión sobre la venta (SUPUESTO: alrededor de 25 a 30 %, por confirmar), así que el margen por pedido puede ser menor que en mostrador aunque el ticket sea más alto. Si preguntan cuánto más se cobra en Didi o Rappi, o qué tan caros están los precios en las apps, se compara por canal el sobreprecio: AVG(monto_total - subtotal) y 100 * SUM(monto_total - subtotal) / SUM(subtotal) en ordenes (columna extras), no las ventas totales de cada canal. Legacy y Automatas son empresas cuyos empleados compran a crédito; la empresa paga después, así que esas ventas no entran a la caja el mismo día.

## Promociones
Hay promociones de cantidad (por ejemplo 4 tacos por $105, 3 bocoles por $60, 3 gorditas por $85, 2 bardas o piernas por $170) y combos de platillo o torta más agua fresca. Una promoción conviene si aumenta las órdenes o el ticket lo suficiente para compensar el descuento. Para proponer una promoción nueva conviene empezar por lo que los clientes ya compran juntos en la misma orden y por los días u horas más flojos.

## Rentabilidad
El POS no guarda costos. Para hablar de ganancia se necesitan los costos por producto (pan, carne, tortillas, refrescos) y la comisión real de cada app, que debe dar el dueño; mientras tanto solo se puede hablar de ventas, descuentos, extras y mezcla de productos, y cualquier margen es una estimación.

## Cancelaciones
Las órdenes 'Cancelada por Modificación' son pedidos que se corrigieron: la orden original se cancela y se captura otra. No son ventas perdidas; sirven para medir cuántos pedidos se capturan mal.

## Recomendaciones típicas para el dueño
Comprar pan según el día de la semana y la quincena; empujar en Didi y Rappi los productos que dejan más; revisar promociones que solo regalan descuento; usar las horas flojas de la mañana para promociones; vigilar cuántas órdenes se corrigen.
