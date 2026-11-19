# Resultados de la evaluación · eval_jaibo_voz_v1

| Aspecto clave | Criterio de éxito | Resultado | ¿Cumple? |
|---|---|---|---|
| Exactitud del SQL | ≥ 85 % de casos correctos | 100.0 % (7/7) | ✅ Sí |
| Ruta correcta (Asesor de negocio vs. Analista SQL) | ≥ 90 % de casos | 100.0 % (10/10) | ✅ Sí |
| Decisiones: herramienta y parámetros correctos | ≥ 85 % de casos | 100.0 % (3/3) | ✅ Sí |
| Decisiones: resultado igual a la referencia | ≥ 85 % de casos | 100.0 % (3/3) | ✅ Sí |
| Decisiones: avisa cuando usa supuestos | 100 % de los casos con supuestos | 100.0 % (2/2) | ✅ Sí |
| Veracidad de la respuesta | 100 % de cifras verificadas | 100.0 % (40/40) | ✅ Sí |
| Calidad de la limpieza | ≥ 90 % de errores detectados | no aplica (sin casos de archivo en esta corrida) | — |
| Pertinencia de la gráfica | Promedio ≥ 4/5 | 4.4/5 | ✅ Sí |
| Memoria y seguimiento | ≥ 80 % correctas | None % (0/0) | ❌ No |
| Entrada por voz | ≥ 90 % bien interpretadas | 100.0 % (10/10) · similitud 0.992 | ✅ Sí |
| Seguridad | 0 consultas distintas de SELECT | 0 ejecutadas · 0/0 casos rechazados correctamente · datos intactos: sí | ✅ Sí |
| Tiempo de respuesta | ≤ 15 s en promedio | 22.21 s (mediana 22.23 s, máx. 37.76 s) | ❌ No |
| Utilidad para el cliente | ≥ 4/5 en encuesta | Pendiente: encuesta con el cliente (docs/encuesta_cliente.md) | — |

## Detalle por caso

| Caso | Categoría | ¿Correcto? | Gráfica (1-5) | Cifras verif. | Tiempo (s) | Nota |
|---|---|---|---|---|---|---|
| JV01 | voz | ✅ | 2 | 3/3 | 29.13 | coincide con la referencia |
| JV02 | voz | ✅ | 5 | 9/9 | 37.76 | coincide con la referencia |
| JV03 | voz | ✅ | 5 | 2/2 | 27.49 | coincide con la referencia |
| JV04 | voz | ✅ | 2 | 3/3 | 12.55 | coincide con la referencia |
| JV05 | voz | ✅ | 5 | 4/4 | 23.52 | coincide con la referencia |
| JV06 | voz | ✅ | 5 | 4/4 | 28.06 | coincide con la referencia |
| JV07 | voz | ✅ | 5 | 5/5 | 18.62 | coincide con la referencia |
| JV08 | voz | ✅ | 5 | 4/4 | 13.36 | coincide con la referencia |
| JV09 | voz | ✅ | 5 | 4/4 | 20.95 | coincide con la referencia |
| JV10 | voz | ✅ | 5 | 2/2 | 10.64 | coincide con la referencia |