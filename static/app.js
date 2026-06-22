const BASINS = {
  all: {
    center: [18, -100],
    zoom: 4,
    subtitle: "Atlántico Norte y Pacífico Oriental",
  },
  atlantic: {
    center: [20, -72],
    zoom: 4,
    subtitle: "Atlántico Norte · Caribe · Golfo de América",
  },
  pacific: {
    center: [16, -112],
    zoom: 4,
    subtitle: "Pacífico Oriental y Central",
  },
};

const map = L.map("map", {
  center: BASINS.all.center,
  zoom: BASINS.all.zoom,
  minZoom: 3,
  maxZoom: 10,
  zoomControl: false,
  worldCopyJump: true,
});

L.control.zoom({ position: "bottomleft" }).addTo(map);

const baseLayers = {
  dark: L.tileLayer(
    "https://{s}.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}{r}.png",
    {
      subdomains: "abcd",
      maxZoom: 20,
      attribution: "© OpenStreetMap © CARTO",
    }
  ),
  satellite: L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    {
      maxZoom: 19,
      attribution: "Tiles © Esri",
    }
  ),
};

baseLayers.dark.addTo(map);

const layerGroups = {
  areas: L.layerGroup().addTo(map),
  lines: L.layerGroup().addTo(map),
  points: L.layerGroup().addTo(map),
  labels: L.layerGroup().addTo(map),
  grid: L.layerGroup(),
};

let currentBasin = "all";
let currentBase = "dark";
let latestPayload = null;
let pointIndex = new Map();
let deferredInstallPrompt = null;

function prop(feature, ...names) {
  const properties = feature?.properties || {};
  for (const name of names) {
    if (properties[name] !== undefined && properties[name] !== null) {
      return properties[name];
    }
  }
  return "";
}

function riskInfo(feature) {
  const raw = String(prop(feature, "RISK7DAY", "RISK2DAY", "RISK", "risk")).toLowerCase();
  if (raw.includes("high") || raw.includes("alto")) {
    return { key: "high", label: "Riesgo alto", color: "#ff4d56" };
  }
  if (raw.includes("medium") || raw.includes("medio")) {
    return { key: "medium", label: "Riesgo medio", color: "#ff9e3d" };
  }
  return { key: "low", label: "Riesgo bajo", color: "#efd843" };
}

function probability(feature) {
  const value = prop(feature, "PROB7DAY", "PROB2DAY", "PROB", "probability");
  if (value === "" || value === null) return "—";
  const text = String(value);
  return text.includes("%") ? text : `${text}%`;
}

function featureName(feature, index = 0) {
  const descriptive = prop(feature, "NAME", "DISTURBANCE", "STORMNAME");
  if (descriptive) return descriptive;
  const area = prop(feature, "AREA", "ID");
  return area ? `Disturbio ${area}` : `Disturbio ${index + 1}`;
}

function basinLabel(feature) {
  const basin = String(prop(feature, "BASIN")).toLowerCase();
  return basin.includes("atlantic") ? "Atlántico" : "Pacífico";
}

function clearDataLayers() {
  Object.entries(layerGroups).forEach(([name, group]) => {
    if (name !== "grid") group.clearLayers();
  });
  pointIndex.clear();
}

function renderPayload(payload) {
  clearDataLayers();
  latestPayload = payload;

  const areaFeatures = payload.areas?.features || [];
  const lineFeatures = payload.lines?.features || [];
  const pointFeatures = payload.points?.features || [];

  L.geoJSON(payload.areas, {
    style: (feature) => {
      const risk = riskInfo(feature);
      return {
        color: risk.color,
        weight: 2,
        opacity: 0.95,
        fillColor: risk.color,
        fillOpacity: 0.23,
      };
    },
    onEachFeature: (feature, layer) => {
      layer.bindPopup(popupMarkup(feature));
      layer.on("click", () => highlightActivity(feature));
    },
  }).addTo(layerGroups.areas);

  L.geoJSON(payload.lines, {
    style: { color: "#e8f3f3", weight: 2, opacity: 0.82, dashArray: "7 7" },
  }).addTo(layerGroups.lines);

  L.geoJSON(payload.points, {
    pointToLayer: (feature, latlng) => {
      const risk = riskInfo(feature);
      const marker = L.circleMarker(latlng, {
        radius: 8,
        color: "#fff",
        weight: 2,
        fillColor: risk.color,
        fillOpacity: 0.9,
      });
      const name = featureName(feature, pointIndex.size);
      pointIndex.set(name, marker);
      marker.bindPopup(popupMarkup(feature));
      L.marker(latlng, {
        interactive: false,
        icon: L.divIcon({
          className: "disturbance-label",
          html: probability(feature),
          iconSize: null,
          iconAnchor: [-12, 16],
        }),
      }).addTo(layerGroups.labels);
      return marker;
    },
  }).addTo(layerGroups.points);

  renderActivityList(areaFeatures.length ? areaFeatures : pointFeatures);

  const allFeatures = [...areaFeatures, ...lineFeatures, ...pointFeatures];
  if (allFeatures.length && currentBasin !== "all") {
    const bounds = L.geoJSON({
      type: "FeatureCollection",
      features: allFeatures,
    }).getBounds();
    if (bounds.isValid()) map.fitBounds(bounds.pad(0.3), { maxZoom: 6 });
  }
}

function popupMarkup(feature) {
  const risk = riskInfo(feature);
  return `
    <div style="min-width:180px;color:#102326;font-family:DM Sans,sans-serif">
      <strong style="font-size:14px">${featureName(feature)}</strong>
      <p style="margin:8px 0 3px">Formación a 7 días: <b>${probability(feature)}</b></p>
      <span style="color:${risk.color};font-weight:700">${risk.label}</span>
    </div>
  `;
}

function renderActivityList(features) {
  const list = document.getElementById("activityList");
  const count = document.getElementById("disturbanceCount");
  count.textContent = features.length;

  if (!features.length) {
    list.innerHTML = `
      <div class="empty-state">
        <strong>Sin áreas activas</strong>
        El NHC no muestra disturbios en esta cuenca para los próximos 7 días.
      </div>
    `;
    return;
  }

  list.innerHTML = features
    .map((feature, index) => {
      const risk = riskInfo(feature);
      const name = featureName(feature, index);
      return `
        <article class="activity-item" data-name="${escapeHtml(name)}">
          <span class="risk-dot" style="background:${risk.color}"></span>
          <div>
            <h3>${escapeHtml(name)}</h3>
            <p>${basinLabel(feature)} · ${risk.label}</p>
          </div>
          <span class="probability">${probability(feature)}</span>
        </article>
      `;
    })
    .join("");

  list.querySelectorAll(".activity-item").forEach((item) => {
    item.addEventListener("click", () => {
      const marker = pointIndex.get(item.dataset.name);
      if (marker) {
        map.flyTo(marker.getLatLng(), Math.max(map.getZoom(), 6), { duration: 0.7 });
        marker.openPopup();
      }
    });
  });
}

function highlightActivity(feature) {
  const name = featureName(feature);
  document.querySelectorAll(".activity-item").forEach((item) => {
    item.style.background =
      item.dataset.name === name ? "rgba(121,226,209,.07)" : "transparent";
  });
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function loadData(force = false) {
  const status = document.getElementById("updateStatus");
  const refresh = document.getElementById("refreshButton");
  status.className = "status-chip loading";
  status.querySelector("span:last-child").textContent = "Consultando al NHC";
  refresh.disabled = true;
  refresh.classList.add("loading");

  try {
    const query = new URLSearchParams({ basin: currentBasin });
    if (force) query.set("refresh", "1");
    const response = await fetch(`/api/disturbances?${query}`);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || payload.error);
    renderPayload(payload);
    const time = new Date(payload.meta.retrievedAt);
    status.className = "status-chip";
    status.querySelector("span:last-child").textContent =
      `Actualizado ${time.toLocaleTimeString("es-MX", { hour: "2-digit", minute: "2-digit" })}`;
  } catch (error) {
    console.error(error);
    status.className = "status-chip error";
    status.querySelector("span:last-child").textContent = "NHC no disponible";
    document.getElementById("activityList").innerHTML = `
      <div class="empty-state">
        <strong>No se pudieron cargar los datos</strong>
        Comprueba la conexión e intenta actualizar de nuevo.
      </div>
    `;
    document.getElementById("disturbanceCount").textContent = "!";
  } finally {
    refresh.disabled = false;
    refresh.classList.remove("loading");
  }
}

function drawGrid() {
  layerGroups.grid.clearLayers();
  for (let lat = 0; lat <= 40; lat += 10) {
    L.polyline([[lat, -180], [lat, 0]], {
      color: "#a9c1c2", weight: 0.6, opacity: 0.3, dashArray: "3 6", interactive: false,
    }).addTo(layerGroups.grid);
  }
  for (let lng = -180; lng <= 0; lng += 10) {
    L.polyline([[-5, lng], [45, lng]], {
      color: "#a9c1c2", weight: 0.6, opacity: 0.3, dashArray: "3 6", interactive: false,
    }).addTo(layerGroups.grid);
  }
}

document.querySelectorAll(".tab").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((tab) => tab.classList.remove("active"));
    button.classList.add("active");
    currentBasin = button.dataset.basin;
    const config = BASINS[currentBasin];
    document.getElementById("mapSubtitle").textContent = config.subtitle;
    map.flyTo(config.center, config.zoom, { duration: 0.8 });
    loadData();
  });
});

document.querySelectorAll("[data-layer]").forEach((checkbox) => {
  checkbox.addEventListener("change", () => {
    const group = layerGroups[checkbox.dataset.layer];
    if (checkbox.checked) group.addTo(map);
    else map.removeLayer(group);
  });
});

document.querySelectorAll("[data-basemap]").forEach((button) => {
  button.addEventListener("click", () => {
    map.removeLayer(baseLayers[currentBase]);
    currentBase = button.dataset.basemap;
    baseLayers[currentBase].addTo(map);
    baseLayers[currentBase].bringToBack();
    document.querySelectorAll("[data-basemap]").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
  });
});

document.getElementById("collapseLayers").addEventListener("click", (event) => {
  const panel = document.querySelector(".layer-panel");
  panel.classList.toggle("collapsed");
  event.currentTarget.textContent = panel.classList.contains("collapsed") ? "+" : "−";
});

document.getElementById("refreshButton").addEventListener("click", () => loadData(true));

const installButton = document.getElementById("installButton");
const installToast = document.getElementById("installToast");
const offlineNotice = document.getElementById("offlineNotice");

window.addEventListener("beforeinstallprompt", (event) => {
  event.preventDefault();
  deferredInstallPrompt = event;
  installButton.hidden = false;
});

installButton.addEventListener("click", async () => {
  if (!deferredInstallPrompt) return;
  deferredInstallPrompt.prompt();
  await deferredInstallPrompt.userChoice;
  deferredInstallPrompt = null;
  installButton.hidden = true;
});

window.addEventListener("appinstalled", () => {
  deferredInstallPrompt = null;
  installButton.hidden = true;
  installToast.hidden = false;
});

installToast.querySelector("button").addEventListener("click", () => {
  installToast.hidden = true;
});

function updateConnectionState() {
  offlineNotice.hidden = navigator.onLine;
}

window.addEventListener("online", () => {
  updateConnectionState();
  loadData();
});
window.addEventListener("offline", updateConnectionState);

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch((error) => {
      console.error("No se pudo registrar el modo instalable.", error);
    });
  });
}

const requestedBasin = new URLSearchParams(window.location.search).get("basin");
if (BASINS[requestedBasin]) {
  const targetTab = document.querySelector(`[data-basin="${requestedBasin}"]`);
  targetTab?.click();
}

drawGrid();
updateConnectionState();
loadData();
setInterval(() => loadData(), 15 * 60 * 1000);
