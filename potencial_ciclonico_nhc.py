# ============================================================
# POTENCIAL CICLONICO NHC
# Producto automatizado para redes sociales
# @francisco01
# ============================================================

from pathlib import Path
from datetime import datetime, timezone
import zipfile
import sys
import requests

try:
    import geopandas as gpd
    import matplotlib.pyplot as plt
    import matplotlib.patheffects as path_effects
    import matplotlib.patches as mpatches
    import cartopy.crs as ccrs
    import cartopy.feature as cfeature
except ModuleNotFoundError as exc:
    paquete = exc.name
    print("\nFalta una dependencia de Python para generar el mapa.")
    print(f"Modulo no encontrado: {paquete}")
    print("\nInstala las dependencias con:")
    print(
        f'"{sys.executable}" '
        r"-m pip install -r "
        r'"C:\Users\CAMPECHE\Documents\Weather NHC Meteorology\requirements.txt"'
    )
    print(
        "\nNota: cartopy suele instalar mejor en Python 3.12 o 3.13 que en "
        "versiones demasiado nuevas."
    )
    sys.exit(1)


# ============================================================
# CONFIGURACION GENERAL
# ============================================================

PROJECT_DIR = Path(r"C:\Users\CAMPECHE\Python_Meteorologia")

DATA_DIR = PROJECT_DIR / "Datos" / "NHC"
ZIP_DIR = DATA_DIR / "zip"
SHP_DIR = DATA_DIR / "shapefiles"
OUTPUT_DIR = PROJECT_DIR / "Salidas" / "NHC"

NHC_ZIP_URL = "https://www.nhc.noaa.gov/xgtwo/gtwo_shapefiles.zip"

PROB_FIELD = "PROB7DAY"
RISK_FIELD = "RISK7DAY"

FIRMA = "@francisco01"

FUENTE = (
    "Fuente: National Hurricane Center (NHC) / NOAA\n"
    "Producto experimental automatizado. No sustituye informacion oficial."
)

ATLANTICO_EXTENT_COMPLETO = [-100, -45, 5, 35]

CUENCAS = {
    "Atlantic": {
        "titulo": "POTENCIAL CICLONICO",
        "subtitulo": "Atlantico Tropical, Mar Caribe y Golfo de Mexico",
        "nombre": "Atlantico Tropical, Mar Caribe y Golfo de Mexico",
        "archivo": "potencial_ciclonico_atlantico.png",
        "extent_default": ATLANTICO_EXTENT_COMPLETO,
        "extent_completo": ATLANTICO_EXTENT_COMPLETO,
        "zoom_si_un_disturbio": True,
    },
    "East Pacific": {
        "titulo": "POTENCIAL CICLONICO",
        "subtitulo": "PACIFICO ORIENTAL / MEXICO / CENTROAMERICA",
        "nombre": "Pacifico Oriental, Mexico y Centroamerica",
        "archivo": "potencial_ciclonico_pacifico.png",
        "extent_default": [-125, -75, 5, 35],
    },
}

COLORES_RIESGO = {
    "Low": "#E5D600",
    "Medium": "#F4A000",
    "High": "#E60000",
}

RIESGO_ES = {
    "Low": "Riesgo bajo",
    "Medium": "Riesgo medio",
    "High": "Riesgo alto",
}


# ============================================================
# FUNCIONES DE DATOS
# ============================================================

def crear_carpetas():
    ZIP_DIR.mkdir(parents=True, exist_ok=True)
    SHP_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def descargar_shapefiles_nhc():
    zip_path = ZIP_DIR / "gtwo_shapefiles.zip"

    print("=" * 60)
    print("DESCARGANDO SHAPEFILES DEL NHC")
    print("=" * 60)

    response = requests.get(NHC_ZIP_URL, timeout=60)
    response.raise_for_status()

    zip_path.write_bytes(response.content)

    print("\nArchivo descargado:")
    print(zip_path)

    print("\nTamano:")
    print(f"{zip_path.stat().st_size / 1024:.1f} KB")

    return zip_path


def limpiar_carpeta_shapefiles():
    if SHP_DIR.exists():
        for archivo in SHP_DIR.rglob("*"):
            if archivo.is_file():
                archivo.unlink()


def extraer_zip(zip_path):
    print("\nExtrayendo archivos...")

    limpiar_carpeta_shapefiles()
    SHP_DIR.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        zip_ref.extractall(SHP_DIR)

    print("Extraccion completada.")


def buscar_shapefile(nombre_clave):
    archivos = list(SHP_DIR.rglob("*.shp"))

    coincidencias = [
        archivo for archivo in archivos
        if nombre_clave.lower() in archivo.name.lower()
    ]

    if not coincidencias:
        print("\nShapefiles encontrados:")
        for archivo in archivos:
            print(f" - {archivo.name}")

        raise FileNotFoundError(
            f"No se encontro ningun shapefile que contenga: {nombre_clave}"
        )

    return coincidencias[0]


def leer_shapefiles():
    print("\nLeyendo shapefiles...")

    areas_path = buscar_shapefile("areas")
    points_path = buscar_shapefile("points")
    lines_path = buscar_shapefile("lines")

    print(f"Areas: {areas_path.name}")
    print(f"Puntos: {points_path.name}")
    print(f"Lineas: {lines_path.name}")

    areas = gpd.read_file(areas_path).to_crs(epsg=4326)
    points = gpd.read_file(points_path).to_crs(epsg=4326)
    lines = gpd.read_file(lines_path).to_crs(epsg=4326)

    print("\nShapefiles leidos correctamente.")

    return areas, points, lines


def filtrar_cuenca(gdf, cuenca):
    if gdf.empty:
        return gdf

    if "BASIN" not in gdf.columns:
        return gdf.iloc[0:0]

    return gdf[gdf["BASIN"] == cuenca].copy()


# ============================================================
# FUNCIONES DE DISENO
# ============================================================

def color_por_riesgo(riesgo):
    return COLORES_RIESGO.get(riesgo, "#E5D600")


def limitar_valor(valor, minimo, maximo):
    return max(minimo, min(maximo, valor))


def calcular_extent_dinamico(config, areas, points, lines):
    extent_default = config["extent_default"]

    if not config.get("zoom_si_un_disturbio"):
        return extent_default

    total_disturbios = max(len(points), len(areas))
    if total_disturbios != 1:
        return extent_default

    capas = [gdf for gdf in (areas, points, lines) if not gdf.empty]
    if not capas:
        return extent_default

    geometria = gpd.GeoSeries(
        [geom for gdf in capas for geom in gdf.geometry],
        crs="EPSG:4326",
    )

    minx, miny, maxx, maxy = geometria.total_bounds
    ancho = max(maxx - minx, 36)
    alto = max(maxy - miny, 22)

    centro_x = (minx + maxx) / 2
    centro_y = (miny + maxy) / 2

    extent_completo = config.get("extent_completo", extent_default)
    lon_min, lon_max, lat_min, lat_max = extent_completo

    oeste = centro_x - ancho / 2
    este = centro_x + ancho / 2
    sur = centro_y - alto / 2
    norte = centro_y + alto / 2

    if oeste < lon_min:
        este += lon_min - oeste
        oeste = lon_min
    if este > lon_max:
        oeste -= este - lon_max
        este = lon_max
    if sur < lat_min:
        norte += lat_min - sur
        sur = lat_min
    if norte > lat_max:
        sur -= norte - lat_max
        norte = lat_max

    return [
        limitar_valor(oeste, lon_min, lon_max),
        limitar_valor(este, lon_min, lon_max),
        limitar_valor(sur, lat_min, lat_max),
        limitar_valor(norte, lat_min, lat_max),
    ]


def crear_figura_mapa(extent):
    fig = plt.figure(figsize=(16, 9), facecolor="#050A12")
    ax = plt.axes(projection=ccrs.PlateCarree())

    fig.patch.set_facecolor("#050A12")
    ax.set_facecolor("#061826")

    ax.set_extent(extent, crs=ccrs.PlateCarree())

    ax.add_feature(cfeature.OCEAN, facecolor="#061826", zorder=0)
    ax.add_feature(cfeature.LAND, facecolor="#101820", zorder=1)
    ax.add_feature(cfeature.COASTLINE, linewidth=0.9, edgecolor="#AAB7C4", zorder=3)
    ax.add_feature(cfeature.BORDERS, linewidth=0.5, edgecolor="#556371", zorder=3)
    ax.add_feature(cfeature.STATES, linewidth=0.35, edgecolor="#3B4652", zorder=3)

    gl = ax.gridlines(
        draw_labels=True,
        linewidth=0.35,
        linestyle="--",
        alpha=0.22,
        color="#6D7A86"
    )

    gl.top_labels = False
    gl.right_labels = False
    gl.xlabel_style = {"color": "#D8DEE9", "size": 10}
    gl.ylabel_style = {"color": "#D8DEE9", "size": 10}

    return fig, ax


def dibujar_areas(ax, areas):
    if areas.empty:
        return

    for _, row in areas.iterrows():
        riesgo = row.get(RISK_FIELD, "Low")
        color = color_por_riesgo(riesgo)

        gpd.GeoSeries([row.geometry], crs="EPSG:4326").plot(
            ax=ax,
            transform=ccrs.PlateCarree(),
            facecolor=color,
            edgecolor=color,
            linewidth=3.2,
            alpha=0.80,
            zorder=5,
        )


def dibujar_lineas(ax, lines):
    if lines.empty:
        return

    lines.plot(
        ax=ax,
        transform=ccrs.PlateCarree(),
        color="#F8FAFC",
        linewidth=2.0,
        alpha=0.9,
        zorder=6,
    )


def dibujar_puntos(ax, points):
    if points.empty:
        return

    points.plot(
        ax=ax,
        transform=ccrs.PlateCarree(),
        marker="x",
        color="#FFFFFF",
        linewidth=2.4,
        markersize=90,
        zorder=8,
    )


def agregar_etiquetas(ax, areas, points):
    fuente_prob = 22
    fuente_riesgo = 13

    if not points.empty:
        for _, row in points.iterrows():
            x = row.geometry.x
            y = row.geometry.y

            prob = row.get(PROB_FIELD, "")
            riesgo = row.get(RISK_FIELD, "")
            riesgo_txt = RIESGO_ES.get(riesgo, riesgo)

            t1 = ax.text(
                x,
                y + 0.45,
                str(prob),
                transform=ccrs.PlateCarree(),
                ha="center",
                va="center",
                fontsize=fuente_prob,
                fontweight="bold",
                color="white",
                zorder=10,
            )

            t2 = ax.text(
                x,
                y - 0.45,
                riesgo_txt,
                transform=ccrs.PlateCarree(),
                ha="center",
                va="center",
                fontsize=fuente_riesgo,
                fontweight="bold",
                color="white",
                zorder=10,
            )

            for t in [t1, t2]:
                t.set_path_effects([
                    path_effects.Stroke(linewidth=5, foreground="black"),
                    path_effects.Normal()
                ])

    elif not areas.empty:
        for _, row in areas.iterrows():
            punto = row.geometry.representative_point()

            prob = row.get(PROB_FIELD, "")
            riesgo = row.get(RISK_FIELD, "")
            riesgo_txt = RIESGO_ES.get(riesgo, riesgo)

            t1 = ax.text(
                punto.x,
                punto.y + 0.45,
                str(prob),
                transform=ccrs.PlateCarree(),
                ha="center",
                va="center",
                fontsize=fuente_prob,
                fontweight="bold",
                color="white",
                zorder=10,
            )

            t2 = ax.text(
                punto.x,
                punto.y - 0.45,
                riesgo_txt,
                transform=ccrs.PlateCarree(),
                ha="center",
                va="center",
                fontsize=fuente_riesgo,
                fontweight="bold",
                color="white",
                zorder=10,
            )

            for t in [t1, t2]:
                t.set_path_effects([
                    path_effects.Stroke(linewidth=5, foreground="black"),
                    path_effects.Normal()
                ])


def agregar_mensaje_sin_actividad(ax):
    t = ax.text(
        0.5,
        0.52,
        "SIN AREAS DE POTENCIAL CICLONICO\nACTIVAS EN ESTE MOMENTO",
        transform=ax.transAxes,
        ha="center",
        va="center",
        fontsize=28,
        fontweight="bold",
        color="white",
        zorder=20,
        bbox=dict(
            boxstyle="round,pad=0.6",
            facecolor="#050A12",
            edgecolor="#607080",
            linewidth=1.6,
            alpha=0.92,
        )
    )

    t.set_path_effects([
        path_effects.Stroke(linewidth=3, foreground="black"),
        path_effects.Normal()
    ])


def agregar_leyenda(ax):
    leyenda = [
        mpatches.Patch(facecolor="#E5D600", edgecolor="#F4E85A", label="Bajo"),
        mpatches.Patch(facecolor="#F4A000", edgecolor="#FFC04D", label="Medio"),
        mpatches.Patch(facecolor="#E60000", edgecolor="#FF4D4D", label="Alto"),
    ]

    leg = ax.legend(
        handles=leyenda,
        title="Riesgo a 7 dias",
        loc="upper right",
        frameon=True,
        facecolor="#050A12",
        edgecolor="#607080",
        fontsize=10,
        title_fontsize=12,
        borderpad=0.55,
        labelspacing=0.35,
        handlelength=1.25,
        handleheight=0.8,
    )

    for text in leg.get_texts():
        text.set_color("white")

    leg.get_title().set_color("white")


def agregar_barra_superior(fig, config):
    hora_utc = datetime.now(timezone.utc).strftime("%d %b %Y | %H:%M UTC")

    barra = mpatches.Rectangle(
        (0, 0.865),
        1,
        0.135,
        transform=fig.transFigure,
        facecolor="#050A12",
        edgecolor="none",
        zorder=30,
    )

    fig.patches.append(barra)

    fig.text(
        0.045,
        0.955,
        config["titulo"],
        fontsize=30,
        fontweight="bold",
        color="white",
        ha="left",
        va="center",
        zorder=31,
    )

    fig.text(
        0.045,
        0.912,
        config["subtitulo"],
        fontsize=12,
        fontweight="bold",
        color="#D8DEE9",
        ha="left",
        va="center",
        zorder=31,
    )

    fig.text(
        0.045,
        0.882,
        f"Elaboracion: {hora_utc}",
        fontsize=12,
        color="#B8C2CC",
        ha="left",
        va="center",
        zorder=31,
    )


def agregar_pie(fig):
    pie = mpatches.Rectangle(
        (0, 0),
        1,
        0.075,
        transform=fig.transFigure,
        facecolor="#050A12",
        edgecolor="none",
        zorder=30,
    )

    fig.patches.append(pie)

    fig.text(
        0.045,
        0.043,
        FUENTE,
        fontsize=10,
        color="#C9D1D9",
        ha="left",
        va="center",
        zorder=31,
    )

    fig.text(
        0.955,
        0.035,
        f"Elaborado por: {FIRMA}",
        fontsize=12,
        fontweight="bold",
        color="#D8DEE9",
        ha="right",
        va="center",
        zorder=31,
    )


def guardar_figura(fig, config):
    output_path = OUTPUT_DIR / config["archivo"]

    fig.savefig(
        output_path,
        dpi=200,
        bbox_inches="tight",
        facecolor=fig.get_facecolor(),
    )

    plt.close(fig)

    print("\nMapa generado:")
    print(output_path)


# ============================================================
# PRODUCTO POR CUENCA
# ============================================================

def generar_producto_cuenca(cuenca, config, areas, points, lines):
    print("\n" + "=" * 60)
    print(f"GENERANDO PRODUCTO: {config['nombre']}")
    print("=" * 60)

    areas_c = filtrar_cuenca(areas, cuenca)
    points_c = filtrar_cuenca(points, cuenca)
    lines_c = filtrar_cuenca(lines, cuenca)

    print(f"Areas detectadas: {len(areas_c)}")
    print(f"Puntos detectados: {len(points_c)}")
    print(f"Lineas detectadas: {len(lines_c)}")

    extent = calcular_extent_dinamico(config, areas_c, points_c, lines_c)

    fig, ax = crear_figura_mapa(extent)

    dibujar_areas(ax, areas_c)
    dibujar_lineas(ax, lines_c)
    dibujar_puntos(ax, points_c)

    if areas_c.empty and points_c.empty:
        agregar_mensaje_sin_actividad(ax)
    else:
        agregar_etiquetas(ax, areas_c, points_c)

    agregar_leyenda(ax)
    agregar_barra_superior(fig, config)
    agregar_pie(fig)

    guardar_figura(fig, config)


# ============================================================
# MAIN
# ============================================================

def main():
    crear_carpetas()

    zip_path = descargar_shapefiles_nhc()
    extraer_zip(zip_path)

    areas, points, lines = leer_shapefiles()

    print("\nColumnas detectadas en gtwo_areas:")
    print(list(areas.columns))

    if "BASIN" in areas.columns:
        print("\nValores detectados en BASIN:")
        print(areas["BASIN"].unique())

    for cuenca, config in CUENCAS.items():
        generar_producto_cuenca(cuenca, config, areas, points, lines)

    print("\n" + "=" * 60)
    print("PROCESO FINALIZADO CORRECTAMENTE")
    print("=" * 60)


if __name__ == "__main__":
    main()
