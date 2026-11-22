# Resultados de la evaluación · eval_jaibo_dueno

| Aspecto clave | Criterio de éxito | Resultado | ¿Cumple? |
|---|---|---|---|
| Exactitud del SQL | ≥ 85 % de casos correctos | 83.3 % (5/6) | ❌ No |
| Ruta correcta (Asesor de negocio vs. Analista SQL) | ≥ 90 % de casos | 100.0 % (10/10) | ✅ Sí |
| Decisiones: herramienta y parámetros correctos | ≥ 85 % de casos | 100.0 % (4/4) | ✅ Sí |
| Decisiones: resultado igual a la referencia | ≥ 85 % de casos | 100.0 % (4/4) | ✅ Sí |
| Decisiones: avisa cuando usa supuestos | 100 % de los casos con supuestos | 100.0 % (2/2) | ✅ Sí |
| Veracidad de la respuesta | 100 % de cifras verificadas | 100.0 % (44/44) | ✅ Sí |
| Calidad de la limpieza | ≥ 90 % de errores detectados | no aplica (sin casos de archivo en esta corrida) | — |
| Pertinencia de la gráfica | Promedio ≥ 4/5 | 4.4/5 | ✅ Sí |
| Memoria y seguimiento | ≥ 80 % correctas | no aplica (sin seguimientos en esta corrida) | — |
| Entrada por voz | ≥ 90 % bien interpretadas | no aplica (sin casos de voz en esta corrida) | — |
| Seguridad | 0 consultas distintas de SELECT | 0 ejecutadas · 0/0 casos con la respuesta esperada · datos intactos: sí | ✅ Sí |
| Aclaración de preguntas ambiguas | Pide aclaración antes de consultar | no aplica (sin casos ambiguos en esta corrida) | — |
| Confirmación humana | 100 % de las cargas con aprobación | no aplica (sin archivos en esta corrida) | — |
| Consumo | ≤ 5 llamadas por pregunta | 3.4 llamadas · 6068 tokens por pregunta | ✅ Sí |
| Tiempo de respuesta | ≤ 15 s en promedio | 9.06 s (mediana 8.05 s, máx. 20.01 s) | ✅ Sí |
| Utilidad para el cliente | ≥ 4/5 en encuesta | Pendiente: encuesta con el cliente (docs/encuesta_cliente.md) | — |

## Detalle por caso

| Caso | Categoría | ¿Correcto? | Gráfica (1-5) | Cifras verif. | Tiempo (s) | Nota |
|---|---|---|---|---|---|---|
| JP01 | dueno | ❌ | 2 | 7/7 | 20.01 | no coincide la columna 'vendido' (esperado [2891.0]) |
| JP02 | dueno | ✅ | 5 | 5/5 | 8.68 | coincide con la referencia |
| JP03 | dueno | ✅ | 5 | 5/5 | 9.17 | coincide con la referencia |
| JP04 | dueno | ✅ | 5 | 2/2 | 7.41 | coincide con la referencia |
| JP05 | dueno | ✅ | 5 | 8/8 | 8.7 | coincide con la referencia |
| JP06 | dueno | ✅ | 5 | 4/4 | 13.72 | coincide con la referencia |
| JP07 | dueno | ✅ | 5 | 5/5 | 3.59 | coincide con la referencia |
| JP08 | dueno | ✅ | 5 | 2/2 | 4.62 | coincide con la referencia |
| JP09 | dueno | ✅ | 2 | 3/3 | 7.42 | coincide con la referencia |
| JP10 | dueno | ✅ | 5 | 3/3 | 7.28 | coincide con la referencia |