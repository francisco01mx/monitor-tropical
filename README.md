# Monitor Tropical

Aplicación web local para visualizar los disturbios tropicales actuales del
Atlántico y del Pacífico con los shapefiles oficiales del National Hurricane
Center (NHC).

## Ejecutar

```powershell
python -m pip install -r requirements.txt
python app.py
```

Abre `http://127.0.0.1:4173`.

La aplicación actualiza los datos cada 15 minutos y permite activar o
desactivar áreas de formación, trayectorias, centros, etiquetas y retícula,
además de alternar entre mapa oscuro e imagen satelital.

## Instalar en Android

Cuando la aplicación esté publicada mediante HTTPS:

1. Abre la dirección en Google Chrome para Android.
2. Pulsa **Instalar app**.
3. Confirma la instalación.

La aplicación aparecerá en la pantalla de inicio y se abrirá sin la barra del
navegador. Su interfaz y los últimos datos consultados pueden permanecer
disponibles ante una pérdida temporal de conexión; los mapas y las
actualizaciones nuevas requieren internet.

## Publicar en Render

El archivo `render.yaml` deja configurado el servicio. Sube el proyecto a un
repositorio de GitHub y, en Render, selecciona **New > Blueprint** y elige ese
repositorio.

> Este visor es informativo y no sustituye los avisos oficiales del NHC/NOAA.
