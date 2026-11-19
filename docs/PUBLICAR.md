# Publicar la app para usarla desde el celular (Streamlit Community Cloud)

La app se publica gratis en Streamlit Community Cloud a partir del repositorio de GitHub. Tus ventas **no se
suben a GitHub**: la app publicada descarga su propia copia del POS con el usuario de solo lectura, y
pide **contraseña** para entrar.

## 1. Repositorio

El código vive en un repositorio **privado** de GitHub. Nunca se suben `.env`, `data/jaibo/` (copia del POS, costos,
reportes, permiso de Gmail), `trazas/` ni `reportes/`.

## 2. Crear la app

1. Entra a <https://share.streamlit.io> con tu cuenta de GitHub y autoriza el acceso a repositorios privados.
2. **Create app**:
   - el repositorio;
   - la rama `main`;
   - el archivo `app.py`;
   - en **Advanced settings**, Python **3.12**.
3. En **Secrets** pega esto, cambiando los valores:

```toml
APP_PASSWORD = "una-contraseña-para-entrar"
GOOGLE_API_KEY = "tu llave de Gemini"
GEMINI_MODELO = "gemini-3.1-flash-lite"
GEMINI_MODELO_SQL = "gemini-3.5-flash-lite"
GEMINI_MODELOS_RESPALDO = "gemini-3.5-flash-lite,gemini-3.1-flash-lite,gemini-2.5-flash"

JAIBO_PG_HOST = "aws-0-us-east-2.pooler.supabase.com"
JAIBO_PG_PORT = "5432"
JAIBO_PG_DB = "postgres"
JAIBO_PG_USUARIO = "datavoz_lector.<id-del-proyecto>"
JAIBO_PG_CONTRASENA = "la contraseña del usuario de solo lectura"
JAIBO_PG_SSLMODE = "require"

# contenido completo de data/jaibo/gmail_token.json
GMAIL_TOKEN_JSON = '''{ ... }'''

# contenido completo de data/jaibo/costos.yaml
JAIBO_COSTOS_YAML = '''
...
'''
```

4. **Deploy**. La primera carga tarda unos minutos, porque instala librerías y arma el índice. Te queda una dirección
   como `https://tortas-jaibo.streamlit.app`. Ábrela en el celular y agrégala a la pantalla de inicio.

## 3. Qué cambia en la nube

- **Voz:** no hay entrada por voz. El modelo Whisper es pesado para el plan gratuito; en tu computadora sí funciona.
- **Conversaciones:** las guardadas en la nube se pierden cuando Streamlit reinicia la app (por inactividad o
  actualización). La copia del POS y los reportes se vuelven a descargar solos.
- **Actualizaciones:** cada vez que se suban cambios a GitHub, la app publicada se actualiza sola.
