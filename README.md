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

Cuando el NHC emite avisos para un ciclón tropical activo, el visor incorpora
automáticamente:

- posición y tipo del ciclón;
- trayectoria y posiciones pronosticadas;
- cono oficial de incertidumbre;
- vigilancias y avisos costeros disponibles;
- movimiento, presión y titular del boletín.

Estas capas se alimentan de los feeds GIS oficiales del NHC y pueden activarse
o desactivarse desde el panel del mapa.

## Mapas base

El selector independiente **Mapas base** incluye:

- CARTO oscuro y claro;
- OpenStreetMap;
- Esri World Imagery;
- Esri World Topographic.

Google Maps Tiles, Azure Maps (sustituto actual de Bing Maps) y ArcGIS Modern
Antique necesitan claves y cuentas oficiales de sus respectivos proveedores.
No se utilizan accesos directos no autorizados a sus mosaicos.

## Alertas tropicales

El botón **Activar alertas** solicita permiso para mostrar notificaciones. La
aplicación revisa los productos cada cinco minutos y avisa cuando:

- aparece un disturbio nuevo;
- cambia su probabilidad o nivel de riesgo;
- aparece un ciclón tropical activo.

Estas alertas funcionan mientras la PWA está abierta o permanece activa en
segundo plano. Para recibir notificaciones con la aplicación completamente
cerrada se necesita añadir posteriormente un servicio de Web Push, como
Firebase Cloud Messaging, junto con un monitor permanente en el servidor.

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
