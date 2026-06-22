"""Servidor local para el visor interactivo de disturbios tropicales del NHC."""

from __future__ import annotations

from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import time
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET
import zipfile


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
DATA_DIR = ROOT / "data"
ZIP_PATH = DATA_DIR / "gtwo_shapefiles.zip"
NHC_ZIP_URL = "https://www.nhc.noaa.gov/xgtwo/gtwo_shapefiles.zip"
NHC_GIS_FEEDS = {
    "atlantic": "https://www.nhc.noaa.gov/gis-at.xml",
    "pacific": "https://www.nhc.noaa.gov/gis-ep.xml",
}
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "4173"))
CACHE_SECONDS = 15 * 60

_cache_lock = threading.Lock()
_data_cache: dict | None = None
_cache_time = 0.0
_cyclone_cache: dict | None = None
_cyclone_cache_time = 0.0


def _find_layer(directory: Path, keyword: str) -> Path | None:
    matches = [
        path
        for path in directory.rglob("*.shp")
        if keyword.lower() in path.name.lower()
    ]
    return matches[0] if matches else None


def _empty_collection() -> dict:
    return {"type": "FeatureCollection", "features": []}


def _read_geojson(path: Path | None) -> dict:
    if path is None:
        return _empty_collection()

    import shapefile

    features = []
    with shapefile.Reader(
        str(path), encoding="utf-8", encodingErrors="replace"
    ) as reader:
        fields = [field[0] for field in reader.fields[1:]]
        for shape_record in reader.iterShapeRecords():
            properties = dict(zip(fields, list(shape_record.record)))
            features.append(
                {
                    "type": "Feature",
                    "properties": properties,
                    "geometry": shape_record.shape.__geo_interface__,
                }
            )
    return {"type": "FeatureCollection", "features": features}


def _download_zip(force: bool = False) -> tuple[Path, str]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if ZIP_PATH.exists() and not force:
        age = time.time() - ZIP_PATH.stat().st_mtime
        if age < CACHE_SECONDS:
            stamp = datetime.fromtimestamp(
                ZIP_PATH.stat().st_mtime, tz=timezone.utc
            ).isoformat()
            return ZIP_PATH, stamp

    request = Request(
        NHC_ZIP_URL,
        headers={"User-Agent": "NHC-Tropical-Monitor/1.0"},
    )
    with urlopen(request, timeout=45) as response:
        ZIP_PATH.write_bytes(response.read())
        stamp = response.headers.get("Last-Modified") or datetime.now(
            timezone.utc
        ).isoformat()
    return ZIP_PATH, stamp


def _download_bytes(url: str) -> tuple[bytes, str]:
    request = Request(url, headers={"User-Agent": "NHC-Tropical-Monitor/1.0"})
    with urlopen(request, timeout=45) as response:
        return (
            response.read(),
            response.headers.get("Last-Modified")
            or datetime.now(timezone.utc).isoformat(),
        )


def load_nhc_data(force: bool = False) -> dict:
    global _cache_time, _data_cache

    with _cache_lock:
        if (
            _data_cache is not None
            and not force
            and time.time() - _cache_time < CACHE_SECONDS
        ):
            return _data_cache

        zip_path, source_time = _download_zip(force=force)
        with tempfile.TemporaryDirectory(prefix="nhc_gtwo_") as temp:
            extract_dir = Path(temp)
            with zipfile.ZipFile(zip_path) as archive:
                archive.extractall(extract_dir)

            payload = {
                "areas": _read_geojson(_find_layer(extract_dir, "areas")),
                "lines": _read_geojson(_find_layer(extract_dir, "lines")),
                "points": _read_geojson(_find_layer(extract_dir, "points")),
                "meta": {
                    "source": "National Hurricane Center / NOAA",
                    "sourceUrl": "https://www.nhc.noaa.gov/gtwo.php",
                    "retrievedAt": datetime.now(timezone.utc).isoformat(),
                    "sourceUpdatedAt": source_time,
                    "cacheSeconds": CACHE_SECONDS,
                },
            }

        _data_cache = payload
        _cache_time = time.time()
        return payload


def _basin_name(feature: dict) -> str:
    props = feature.get("properties") or {}
    return str(props.get("BASIN") or props.get("basin") or "").lower()


def filter_by_basin(payload: dict, basin: str) -> dict:
    if basin == "all":
        return payload

    aliases = {
        "atlantic": {"atlantic"},
        "pacific": {
            "pacific",
            "east pacific",
            "eastern pacific",
            "central pacific",
        },
    }
    accepted = aliases.get(basin, {basin})
    result = {"meta": payload["meta"]}
    for layer in ("areas", "lines", "points"):
        result[layer] = {
            "type": "FeatureCollection",
            "features": [
                feature
                for feature in payload[layer]["features"]
                if _basin_name(feature) in accepted
            ],
        }
    return result


def _text(element: ET.Element | None, name: str) -> str:
    if element is None:
        return ""
    child = element.find(name)
    return (child.text or "").strip() if child is not None else ""


def _atcf_from_title(title: str) -> str:
    match = re.search(r"/([a-z]{2}\d{6})\)", title, re.IGNORECASE)
    return match.group(1).lower() if match else ""


def _storm_type_es(value: str) -> str:
    translations = {
        "hurricane": "Huracán",
        "tropical storm": "Tormenta tropical",
        "tropical depression": "Depresión tropical",
        "potential tropical cyclone": "Potencial ciclón tropical",
        "subtropical storm": "Tormenta subtropical",
        "subtropical depression": "Depresión subtropical",
        "post-tropical cyclone": "Ciclón postropical",
    }
    return translations.get(value.lower(), value.title())


def _parse_summary(item: ET.Element, basin: str) -> dict | None:
    namespace = {"nhc": "https://www.nhc.noaa.gov"}
    cyclone = item.find("nhc:Cyclone", namespace)
    if cyclone is None:
        return None

    values = {
        child.tag.split("}")[-1]: (child.text or "").strip()
        for child in cyclone
    }
    center = values.get("center", "")
    coordinates = []
    if "," in center:
        try:
            lat, lon = (float(part.strip()) for part in center.split(",", 1))
            coordinates = [lon, lat]
        except ValueError:
            pass

    title = _text(item, "title")
    atcf = values.get("atcf") or _atcf_from_title(title)
    storm_type = values.get("type", "")
    return {
        "id": atcf,
        "basin": basin,
        "name": values.get("name") or "Sin nombre",
        "type": storm_type,
        "typeEs": _storm_type_es(storm_type),
        "center": coordinates,
        "datetime": values.get("datetime", ""),
        "movement": values.get("movement", ""),
        "pressure": values.get("pressure", ""),
        "headline": values.get("headline", ""),
        "wallet": values.get("wallet", ""),
        "advisoryUrl": _text(item, "link"),
    }


def _features_from_zip(content: bytes, storm_id: str) -> dict:
    result = {
        "cones": _empty_collection(),
        "tracks": _empty_collection(),
        "forecastPoints": _empty_collection(),
        "warnings": _empty_collection(),
    }
    with tempfile.TemporaryDirectory(prefix="nhc_cyclone_") as temp:
        directory = Path(temp)
        with zipfile.ZipFile(BytesIO(content)) as archive:
            archive.extractall(directory)

        for shp_path in directory.rglob("*.shp"):
            name = shp_path.name.lower()
            if "wwa" in name or "warn" in name:
                target = "warnings"
            elif "_pgn" in name or "cone" in name:
                target = "cones"
            elif "_pts" in name or "points" in name:
                target = "forecastPoints"
            elif "_lin" in name or "track" in name:
                target = "tracks"
            else:
                continue
            collection = _read_geojson(shp_path)
            for feature in collection["features"]:
                feature.setdefault("properties", {})["_stormId"] = storm_id
            result[target]["features"].extend(collection["features"])
    return result


def load_active_cyclones(force: bool = False) -> dict:
    global _cyclone_cache, _cyclone_cache_time

    with _cache_lock:
        if (
            _cyclone_cache is not None
            and not force
            and time.time() - _cyclone_cache_time < CACHE_SECONDS
        ):
            return _cyclone_cache

        payload = {
            "storms": [],
            "cones": _empty_collection(),
            "tracks": _empty_collection(),
            "forecastPoints": _empty_collection(),
            "warnings": _empty_collection(),
            "meta": {
                "source": "National Hurricane Center / NOAA",
                "sourceUrl": "https://www.nhc.noaa.gov/gis/",
                "retrievedAt": datetime.now(timezone.utc).isoformat(),
            },
        }

        products: dict[str, list[str]] = {}
        for basin, feed_url in NHC_GIS_FEEDS.items():
            xml_bytes, _ = _download_bytes(feed_url)
            root = ET.fromstring(xml_bytes)
            for item in root.findall("./channel/item"):
                title = _text(item, "title")
                storm = _parse_summary(item, basin)
                if storm:
                    payload["storms"].append(storm)
                    continue
                storm_id = _atcf_from_title(title)
                link = _text(item, "link")
                if (
                    storm_id
                    and link.lower().endswith(".zip")
                    and ("forecast [shp]" in title.lower() or "watches/warnings [shp]" in title.lower())
                ):
                    products.setdefault(storm_id, []).append(link)

        for storm_id, urls in products.items():
            for url in dict.fromkeys(urls):
                try:
                    content, _ = _download_bytes(url)
                    layers = _features_from_zip(content, storm_id)
                    for layer_name, collection in layers.items():
                        payload[layer_name]["features"].extend(
                            collection["features"]
                        )
                except Exception as exc:
                    print(f"No se pudo cargar {url}: {exc}")

        _cyclone_cache = payload
        _cyclone_cache_time = time.time()
        return payload


def filter_cyclones_by_basin(payload: dict, basin: str) -> dict:
    if basin == "all":
        return payload

    storm_ids = {
        storm["id"] for storm in payload["storms"] if storm["basin"] == basin
    }
    result = {
        "storms": [
            storm for storm in payload["storms"] if storm["basin"] == basin
        ],
        "meta": payload["meta"],
    }
    for layer in ("cones", "tracks", "forecastPoints", "warnings"):
        result[layer] = {
            "type": "FeatureCollection",
            "features": [
                feature
                for feature in payload[layer]["features"]
                if (feature.get("properties") or {}).get("_stormId")
                in storm_ids
            ],
        }
    return result


class AppHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def guess_type(self, path):
        if path.endswith(".webmanifest"):
            return "application/manifest+json"
        return super().guess_type(path)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/disturbances":
            query = parse_qs(parsed.query)
            basin = query.get("basin", ["all"])[0].lower()
            force = query.get("refresh", ["0"])[0] == "1"
            try:
                payload = filter_by_basin(load_nhc_data(force), basin)
                self._send_json(payload)
            except Exception as exc:
                self._send_json(
                    {
                        "error": "No fue posible obtener los datos del NHC.",
                        "detail": str(exc),
                    },
                    HTTPStatus.SERVICE_UNAVAILABLE,
                )
            return

        if parsed.path == "/api/cyclones":
            query = parse_qs(parsed.query)
            basin = query.get("basin", ["all"])[0].lower()
            force = query.get("refresh", ["0"])[0] == "1"
            try:
                payload = filter_cyclones_by_basin(
                    load_active_cyclones(force), basin
                )
                self._send_json(payload)
            except Exception as exc:
                self._send_json(
                    {
                        "error": "No fue posible obtener los ciclones activos.",
                        "detail": str(exc),
                    },
                    HTTPStatus.SERVICE_UNAVAILABLE,
                )
            return

        if parsed.path == "/health":
            self._send_json({"status": "ok"})
            return

        if parsed.path == "/":
            self.path = "/index.html"
        super().do_GET()

    def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        print(f"[web] {self.address_string()} - {format % args}")


def main():
    if not STATIC_DIR.exists():
        raise FileNotFoundError(f"No existe la carpeta web: {STATIC_DIR}")
    server = ThreadingHTTPServer((HOST, PORT), AppHandler)
    print(f"Monitor Tropical disponible en http://{HOST}:{PORT}")
    print("Presiona Ctrl+C para detenerlo.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor detenido.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
