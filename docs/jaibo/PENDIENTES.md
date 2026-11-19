# Integración Tortas Jaibo — estado al 18/11/2026

## Ya funciona (probado)
- **Conexión de solo lectura** a Supabase (`datavoz_lector`). `--verificar` da OK en todo. La copia real (7,199 órdenes) está en `data/jaibo/`, fuera de git.
- **Asesor de negocio** con 4 herramientas: pronóstico de pan con error medido, rentabilidad por canal (ahora también de un mes concreto), combinaciones de productos y simulador de promociones. Los costos salen de `data/jaibo/costos.yaml` o de la plantilla con supuestos.
- **Evaluación final**, con Gemini, sin caché y con 10 s de pausa:
  - Tienda de abarrotes, `eval_v5`: cumple todos los criterios medibles (100 % SQL, 9.5 s por pregunta).
  - Tortas Jaibo, `eval_jaibo_v3`: 36/36 casos y cumple todos los criterios medibles (100 % SQL, ruta, herramienta y resultado de las decisiones, aviso de supuestos, cifras y seguridad; 11.3 s por pregunta).
  - Historial: `eval_jaibo_v1` (69 % SQL, 4 fallos corregidos) → `v2` (no válida por un choque con el índice del RAG, ya corregido) → `v3`.
- 138 pruebas automáticas pasan.

## Nuevo (19/11/2026)
- **Lista de compras:** pan pronosticado × precio de referencia de **Chedraui Ciudad del Carmen** (CP 24180) o el precio de tu panadero (`compras` en `costos.yaml`). Por ahora se toma la «Telera» como pan normal y la «Telera Doble» como pan Mega (SUPUESTO).
- **Lista de compras completa:** pan + ingredientes de las tortas (carne de res, pulpa de cerdo, res para barbacoa, jamón, quesos, chorizo, frijol, tomate, cebolla, aguacate, crema y aderezo) con porciones por torta y productos de Chedraui en `ingredientes` de `costos.yaml`. El dueño pidió tomar como reales el margen del 10 %, la comisión del 25 % y las porciones (marcados `supuesto: false` en `data/jaibo/costos.yaml`).
- **Sugerencias para responder** debajo de cada respuesta.
- **Inicio despejado** y pestaña **Mi semana** con 4 gráficas.
- **Gráficas más claras:** valores sobre las barras, `$` en el dinero y títulos a la izquierda.
- 146 pruebas automáticas pasan.

## Falta
1. **Tú:**
   - confirmar qué pan usas (¿telera y telera doble?) y cuánto te cuesta con tu panadero;
   - llenar `data/jaibo/costos.yaml` con las comisiones reales, el margen de pan y los costos por pieza;
   - pedir el permiso del dueño;
   - cambiar la contraseña del POS en `DatabaseConfig.java`.
2. **Correr la suite contra los datos reales:** `python evaluacion/ejecutar_evaluacion.py --negocio jaibo --base real --sin-cache --pausa 10`. Los resultados se quedan en `data/jaibo/evaluacion/`.
3. **La encuesta con el dueño** (criterio «utilidad para el cliente»).
4. **Confirmar por qué bajan las órdenes desde mayo de 2026:** ¿parte de la venta ya se registra en el POS nuevo?
5. **Actualizar la ficha y el PDF final** con el giro a Tortas Jaibo: cliente real, Asesor de negocio, evaluación con historial y análisis de trazas. Buenas trazas para el análisis:
   - una exitosa: JD02 (pan del fin de semana, con error medido);
   - una fallida y corregida: J09 en v1 («qué día cobro más»: sumó renglones), contra v3, donde la revisión semántica lo detectó y reintentó.
6. **Agregar casos de evaluación** de la lista de compras (con precios fijos, sin red).
7. **Crear el repositorio en GitHub** (necesita tu permiso).
8. **Límites conocidos:**
   - «¿Cuánto más cobro en Didi?» se puede entender como «cuánto más vendo»;
   - en JH2 el SQL detecta las órdenes rehechas con `ILIKE '%canc%'`: funciona, pero es frágil.
