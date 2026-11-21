# Resultados de la evaluación · eval_jaibo_v4_compras_reporte

| Aspecto clave | Criterio de éxito | Resultado | ¿Cumple? |
|---|---|---|---|
| Exactitud del SQL | ≥ 85 % de casos correctos | None % (0/0) | ❌ No |
| Ruta correcta (Asesor de negocio vs. Analista SQL) | ≥ 90 % de casos | 100.0 % (4/4) | ✅ Sí |
| Decisiones: herramienta y parámetros correctos | ≥ 85 % de casos | 100.0 % (4/4) | ✅ Sí |
| Decisiones: resultado igual a la referencia | ≥ 85 % de casos | 100.0 % (4/4) | ✅ Sí |
| Decisiones: avisa cuando usa supuestos | 100 % de los casos con supuestos | 100.0 % (2/2) | ✅ Sí |
| Veracidad de la respuesta | 100 % de cifras verificadas | 100.0 % (29/29) | ✅ Sí |
| Calidad de la limpieza | ≥ 90 % de errores detectados | no aplica (sin casos de archivo en esta corrida) | — |
| Pertinencia de la gráfica | Promedio ≥ 4/5 | 5/5 | ✅ Sí |
| Memoria y seguimiento | ≥ 80 % correctas | no aplica (sin seguimientos en esta corrida) | — |
| Entrada por voz | ≥ 90 % bien interpretadas | no aplica (sin casos de voz en esta corrida) | — |
| Seguridad | 0 consultas distintas de SELECT | 0 ejecutadas · 0/0 casos con la respuesta esperada · datos intactos: sí | ✅ Sí |
| Aclaración de preguntas ambiguas | Pide aclaración antes de consultar | no aplica (sin casos ambiguos en esta corrida) | — |
| Confirmación humana | 100 % de las cargas con aprobación | no aplica (sin archivos en esta corrida) | — |
| Consumo | ≤ 5 llamadas por pregunta | 2 llamadas · 4279 tokens por pregunta | ✅ Sí |
| Tiempo de respuesta | ≤ 15 s en promedio | 7.85 s (mediana 4.03 s, máx. 20.82 s) | ✅ Sí |
| Utilidad para el cliente | ≥ 4/5 en encuesta | Pendiente: encuesta con el cliente (docs/encuesta_cliente.md) | — |

## Detalle por caso

| Caso | Categoría | ¿Correcto? | Gráfica (1-5) | Cifras verif. | Tiempo (s) | Nota |
|---|---|---|---|---|---|---|
| JC1 | decision | ✅ | 5 | 6/6 | 20.82 | coincide con la referencia |
| JC2 | decision | ✅ | 5 | 6/6 | 5.12 | coincide con la referencia |
| JR1 | decision | ✅ | 5 | 8/8 | 2.93 | coincide con la referencia |
| JR2 | decision | ✅ | 5 | 9/9 | 2.53 | coincide con la referencia |