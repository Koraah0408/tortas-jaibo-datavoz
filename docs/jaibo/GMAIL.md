# Conectar los reportes diarios de Gmail (solo lectura)

El POS manda cada noche el correo **«Reporte Financiero: DD/MM/AAAA al DD/MM/AAAA»** con `Reporte_Ventas.pdf`.
La app los busca en tu Gmail, lee sus cifras y los muestra en la pestaña **Reportes**:

- ingresos;
- efectivo, tarjeta y apps;
- crédito;
- egresos;
- fondo de caja;
- órdenes.

También te deja descargar cada PDF, y los agentes pueden responder preguntas sobre ellos.

El permiso que das es **solo de lectura** (`gmail.readonly`): la app no puede enviar, borrar ni cambiar correos.
Los PDF y el permiso se guardan en `data/jaibo/`, que no se sube a GitHub.

## Paso 1. Crear la credencial en Google Cloud (una vez, unos 10 min)

1. Entra a <https://console.cloud.google.com/> con tu cuenta de Gmail y crea un proyecto, por ejemplo «Tortas Jaibo».
2. **APIs y servicios → Biblioteca**: busca **Gmail API** y pulsa **Habilitar**.
3. **APIs y servicios → Pantalla de consentimiento de OAuth**:
   - tipo **Externo**;
   - nombre «Tortas Jaibo»;
   - tu correo como soporte y contacto;
   - en **Usuarios de prueba**, agrega tu propio correo.
4. **APIs y servicios → Credenciales → Crear credenciales → ID de cliente de OAuth**:
   - tipo **App de escritorio**;
   - descarga el JSON.
5. Guarda ese archivo como `C:\proyectos\DataVoz\data\jaibo\gmail_cliente.json`.

## Paso 2. Dar el permiso (una vez)

```powershell
cd C:\proyectos\DataVoz
```

```powershell
.\.venv\Scripts\python.exe -m datavoz.conectores.gmail_reportes --autorizar
```

Se abre el navegador: elige tu cuenta y acepta el permiso de **solo lectura**. Google te va a mostrar un aviso de
«app no verificada», porque es tu propia app de prueba; pulsa **Continuar**. Queda guardado en
`data/jaibo/gmail_token.json`.

## Paso 3. Traer los reportes

En la app, pestaña **Reportes → Buscar nuevos**, o desde la terminal:

```powershell
.\.venv\Scripts\python.exe -m datavoz.conectores.gmail_reportes --sincronizar
```

La primera vez trae todos los reportes que encuentre (hasta 400). Las siguientes solo trae los nuevos. Si un día
mandaste el reporte varias veces, se queda el envío más reciente.

## En la versión publicada

Copia el contenido de `data/jaibo/gmail_token.json` en el secreto `GMAIL_TOKEN_JSON` (ver `docs/PUBLICAR.md`).
Para quitar el permiso cuando quieras, entra a <https://myaccount.google.com/permissions> y elimina «Tortas Jaibo».
