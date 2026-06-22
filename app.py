"""Servidor local para el visor interactivo de disturbios tropicales del NHC."""

from __future__ import annotations

from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen
import zipfile


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
DATA_DIR = ROOT / "data"
ZIP_PATH = DATA_DIR / "gtwo_shapefiles.zip"
NHC_ZIP_URL = "https://www.nhc.noaa.gov/xgtwo/gtwo_shapefiles.zip"
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "4173"))
CACHE_SECONDS = 15 * 60

_cache_lock = threading.Lock()
_data_cache: dict | None = None
_cache_time = 0.0


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
