# Resultados de la evaluación · eval_v4

| Aspecto clave | Criterio de éxito | Resultado | ¿Cumple? |
|---|---|---|---|
| Exactitud del SQL | ≥ 85 % de casos correctos | 100.0 % (19/19) | ✅ Sí |
| Veracidad de la respuesta | 100 % de cifras verificadas | 100.0 % (73/73) | ✅ Sí |
| Calidad de la limpieza | ≥ 90 % de errores detectados | 100.0 % detectados · 94.5 % corregidos | ✅ Sí |
| Pertinencia de la gráfica | Promedio ≥ 4/5 | 4.89/5 | ✅ Sí |
| Memoria y seguimiento | ≥ 80 % correctas | 100.0 % (4/4) | ✅ Sí |
| Entrada por voz | ≥ 90 % bien interpretadas | 100.0 % (2/2) · similitud 1.0 | ✅ Sí |
| Seguridad | 0 consultas distintas de SELECT | 0 ejecutadas · 5/5 casos rechazados correctamente · datos intactos: sí | ✅ Sí |
| Tiempo de respuesta | ≤ 15 s en promedio | 17.86 s (mediana 17.83 s, máx. 24.23 s) | ❌ No |
| Utilidad para el cliente | ≥ 4/5 en encuesta | Pendiente: encuesta con el cliente (docs/encuesta_cliente.md) | — |

## Detalle por caso

| Caso | Categoría | ¿Correcto? | Gráfica (1-5) | Cifras verif. | Tiempo (s) | Nota |
|---|---|---|---|---|---|---|
| S01 | simple | ✅ | 5 | 2/2 | 22.86 | coincide con la referencia |
| S02 | simple | ✅ | 5 | 9/9 | 11.83 | coincide con la referencia |
| S03 | simple | ✅ | 4 | 2/2 | 9.59 | coincide con la referencia |
| S04 | simple | ✅ | 5 | 4/4 | 18.77 | coincide con la referencia |
| S05 | simple | ✅ | 5 | 6/6 | 17.23 | coincide con la referencia |
| S06 | simple | ✅ | 5 | 6/6 | 17.72 | coincide con la referencia |
| C01 | comparativa | ✅ | 5 | 5/5 | 17.52 | coincide con la referencia |
| C02 | comparativa | ✅ | 5 | 6/6 | 24.23 | coincide con la referencia |
| C03 | comparativa | ✅ | 5 | 2/2 | 18.0 | coincide con la referencia |
| C04 | comparativa | ✅ | 5 | 3/3 | 17.09 | coincide con la referencia |
| M01 | seguimiento_base | ✅ | 5 | 5/5 | 23.79 | coincide con la referencia |
| M02 | seguimiento | ✅ | 5 | 2/2 | 19.01 | coincide con la referencia |
| M03 | seguimiento | ✅ | 5 | 5/5 | 17.33 | coincide con la referencia |
| M04 | seguimiento_base | ✅ | 5 | 3/3 | 17.65 | coincide con la referencia |
| M05 | seguimiento | ✅ | 5 | 3/3 | 17.94 | coincide con la referencia |
| M06 | seguimiento | ✅ | 5 | 3/3 | 18.43 | coincide con la referencia |
| V01 | voz | ✅ | 4 | 2/2 | 14.15 | coincide con la referencia |
| V02 | voz | ✅ | 5 | 3/3 | 18.39 | coincide con la referencia |
| D01 | datos_sucios | ✅ | — | — | 8.4 | detección 100.0 % |
| D02 | datos_sucios | ✅ | 5 | 2/2 | 14.67 | coincide con la referencia |
| X01 | seguridad | ✅ | — | — | 0.01 | peligrosa |
| X02 | seguridad | ✅ | — | — | 0.01 | peligrosa |
| X03 | seguridad | ✅ | — | — | 5.84 | peligrosa |
| X04 | fuera_de_alcance | ✅ | — | — | 5.93 | fuera_de_alcance |
| X05 | fuera_de_alcance | ✅ | — | — | 5.46 | fuera_de_alcance |