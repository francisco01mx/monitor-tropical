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
  light: L.tileLayer(
    "https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png",
    {
      subdomains: "abcd",
      maxZoom: 20,
      attribution: "© OpenStreetMap © CARTO",
    }
  ),
  osm: L.tileLayer(
    "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    {
      maxZoom: 19,
      attribution: "© OpenStreetMap contributors",
    }
  ),
  satellite: L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    {
      maxZoom: 19,
      attribution: "Tiles © Esri",
    }
  ),
  topographic: L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
    {
      maxZoom: 19,
      attribution: "Tiles © Esri",
    }
  ),
};

baseLayers.dark.addTo(map);

const layerGroups = {
  cyclones: L.layerGroup().addTo(map),
  cones: L.layerGroup().addTo(map),
  cycloneTrack: L.layerGroup().addTo(map),
  warnings: L.layerGroup().addTo(map),
  areas: L.layerGroup().addTo(map),
  lines: L.layerGroup().addTo(map),
  points: L.layerGroup().addTo(map),
  labels: L.layerGroup().addTo(map),
  grid: L.layerGroup(),
};

let currentBasin = "all";
let currentBase = "dark";
let latestPayload = null;
let latestCyclones = null;
let pointIndex = new Map();
let cycloneIndex = new Map();
let deferredInstallPrompt = null;
const ALERT_STATE_KEY = "monitor-tropical-alert-state-v1";
let alertBaselineReady = false;

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
  cycloneIndex.clear();
}

function renderPayload(payload, cyclonePayload) {
  clearDataLayers();
  latestPayload = payload;
  latestCyclones = cyclonePayload;

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

  renderCyclones(cyclonePayload);
  renderActivityList(
    areaFeatures.length ? areaFeatures : pointFeatures,
    cyclonePayload.storms || []
  );
  evaluateTropicalAlerts(payload, cyclonePayload);

  const allFeatures = [...areaFeatures, ...lineFeatures, ...pointFeatures];
  if (allFeatures.length && currentBasin !== "all") {
    const bounds = L.geoJSON({
      type: "FeatureCollection",
      features: allFeatures,
    }).getBounds();
    if (bounds.isValid()) map.fitBounds(bounds.pad(0.3), { maxZoom: 6 });
  }
}

function cycloneColor(storm) {
  const type = String(storm.type || "").toLowerCase();
  if (type.includes("hurricane")) return "#ff4d56";
  if (type.includes("tropical storm")) return "#ff9e3d";
  if (type.includes("depression")) return "#efd843";
  return "#79e2d1";
}

function renderCyclones(payload) {
  const stormsById = new Map((payload.storms || []).map((storm) => [storm.id, storm]));

  L.geoJSON(payload.cones, {
    style: {
      color: "#79e2d1",
      weight: 2,
      opacity: 0.9,
      fillColor: "#79e2d1",
      fillOpacity: 0.18,
    },
  }).addTo(layerGroups.cones);

  L.geoJSON(payload.tracks, {
    style: {
      color: "#ffffff",
      weight: 2.4,
      opacity: 0.9,
      dashArray: "6 6",
    },
  }).addTo(layerGroups.cycloneTrack);

  L.geoJSON(payload.forecastPoints, {
    pointToLayer: (feature, latlng) => {
      const wind = Number(prop(feature, "MAXWIND")) || 0;
      const color = wind >= 64 ? "#ff4d56" : wind >= 34 ? "#ff9e3d" : "#efd843";
      const marker = L.circleMarker(latlng, {
        radius: 6,
        color: "#ffffff",
        weight: 1.5,
        fillColor: color,
        fillOpacity: 0.95,
      });
      const label = prop(feature, "FLDATELBL", "DATELBL", "DVLBL");
      marker.bindPopup(`
        <div style="min-width:170px;color:#102326;font-family:DM Sans,sans-serif">
          <strong>Pronóstico oficial NHC</strong>
          <p style="margin:7px 0 2px">${escapeHtml(label || "Posición prevista")}</p>
          <span>Viento máximo: <b>${wind || "—"} kt</b></span>
        </div>
      `);
      return marker;
    },
  }).addTo(layerGroups.cycloneTrack);

  L.geoJSON(payload.warnings, {
    style: (feature) => {
      const warning = String(prop(feature, "TCWW", "TYPE", "WARNING")).toLowerCase();
      const hurricane = warning.includes("hurricane");
      return {
        color: hurricane ? "#ff4d56" : "#ff9e3d",
        weight: 5,
        opacity: 1,
      };
    },
  }).addTo(layerGroups.warnings);

  (payload.storms || []).forEach((storm) => {
    if (!Array.isArray(storm.center) || storm.center.length !== 2) return;
    const latlng = [storm.center[1], storm.center[0]];
    const color = cycloneColor(storm);
    const marker = L.circleMarker(latlng, {
      radius: 12,
      color: "#ffffff",
      weight: 3,
      fillColor: color,
      fillOpacity: 1,
    }).addTo(layerGroups.cyclones);
    marker.bindPopup(cyclonePopup(storm));
    cycloneIndex.set(storm.id, marker);
    L.marker(latlng, {
      interactive: false,
      icon: L.divIcon({
        className: "cyclone-label",
        html: escapeHtml(storm.name),
        iconSize: null,
        iconAnchor: [-15, 19],
      }),
    }).addTo(layerGroups.cyclones);
  });
}

function cyclonePopup(storm) {
  return `
    <div style="min-width:210px;color:#102326;font-family:DM Sans,sans-serif">
      <strong style="font-size:15px">${escapeHtml(storm.typeEs)} ${escapeHtml(storm.name)}</strong>
      <p style="margin:8px 0 3px">${escapeHtml(storm.movement || "Movimiento no disponible")}</p>
      <p style="margin:3px 0">Presión: <b>${escapeHtml(storm.pressure || "—")}</b></p>
      <p style="margin:7px 0 0">${escapeHtml(storm.headline || "")}</p>
    </div>
  `;
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

function renderActivityList(features, storms = []) {
  const list = document.getElementById("activityList");
  const count = document.getElementById("disturbanceCount");
  count.textContent = storms.length + features.length;

  if (!features.length && !storms.length) {
    list.innerHTML = `
      <div class="empty-state">
        <strong>Sin áreas activas</strong>
        El NHC no muestra disturbios en esta cuenca para los próximos 7 días.
      </div>
    `;
    return;
  }

  const cycloneMarkup = storms.length
    ? `
      <div class="activity-divider">Ciclones activos</div>
      ${storms.map((storm) => `
        <article class="cyclone-card" data-storm-id="${escapeHtml(storm.id)}">
          <div class="cyclone-card-header">
            <h3>${escapeHtml(storm.name)}</h3>
            <span class="cyclone-type">${escapeHtml(storm.typeEs)}</span>
          </div>
          <p>${escapeHtml(storm.movement || "Movimiento no disponible")} · ${escapeHtml(storm.pressure || "Presión no disponible")}</p>
          ${storm.headline ? `<p class="headline">${escapeHtml(storm.headline)}</p>` : ""}
        </article>
      `).join("")}
    `
    : "";

  const disturbanceMarkup = features.length
    ? `<div class="activity-divider">Disturbios en vigilancia</div>` +
      features
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
    .join("")
    : "";

  list.innerHTML = cycloneMarkup + disturbanceMarkup;

  list.querySelectorAll(".activity-item").forEach((item) => {
    item.addEventListener("click", () => {
      const marker = pointIndex.get(item.dataset.name);
      if (marker) {
        map.flyTo(marker.getLatLng(), Math.max(map.getZoom(), 6), { duration: 0.7 });
        marker.openPopup();
      }
    });
  });

  list.querySelectorAll(".cyclone-card").forEach((item) => {
    item.addEventListener("click", () => {
      const marker = cycloneIndex.get(item.dataset.stormId);
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
    const disturbanceResponse = await fetch(`/api/disturbances?${query}`);
    const payload = await disturbanceResponse.json();
    if (!disturbanceResponse.ok) throw new Error(payload.detail || payload.error);

    let cyclonePayload = emptyCyclonePayload();
    try {
      const cycloneResponse = await fetch(`/api/cyclones?${query}`);
      if (cycloneResponse.ok) {
        cyclonePayload = await cycloneResponse.json();
      } else {
        console.warn("Las capas de ciclones activos aún no están disponibles.");
      }
    } catch (cycloneError) {
      console.warn("No se pudieron actualizar los ciclones activos.", cycloneError);
    }

    renderPayload(payload, cyclonePayload);
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

function emptyCyclonePayload() {
  const collection = () => ({ type: "FeatureCollection", features: [] });
  return {
    storms: [],
    cones: collection(),
    tracks: collection(),
    forecastPoints: collection(),
    warnings: collection(),
  };
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

document.querySelectorAll(".basemap-option[data-basemap]").forEach((button) => {
  button.addEventListener("click", () => {
    map.removeLayer(baseLayers[currentBase]);
    currentBase = button.dataset.basemap;
    baseLayers[currentBase].addTo(map);
    baseLayers[currentBase].bringToBack();
    document.querySelectorAll(".basemap-option[data-basemap]").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    closeBasemapPanel();
  });
});

const basemapPanel = document.getElementById("basemapPanel");
const basemapButton = document.getElementById("basemapButton");
basemapButton.addEventListener("click", () => {
  const willOpen = basemapPanel.hidden;
  basemapPanel.hidden = !willOpen;
  basemapButton.setAttribute("aria-expanded", String(willOpen));
  if (willOpen) document.querySelector(".layer-panel").classList.add("collapsed");
});
function closeBasemapPanel() {
  basemapPanel.hidden = true;
  basemapButton.setAttribute("aria-expanded", "false");
}
document.getElementById("closeBasemaps").addEventListener("click", closeBasemapPanel);

document.getElementById("collapseLayers").addEventListener("click", (event) => {
  const panel = document.querySelector(".layer-panel");
  panel.classList.toggle("collapsed");
  event.currentTarget.textContent = panel.classList.contains("collapsed") ? "+" : "−";
});

document.getElementById("refreshButton").addEventListener("click", () => loadData(true));

const installButton = document.getElementById("installButton");
const installToast = document.getElementById("installToast");
const offlineNotice = document.getElementById("offlineNotice");
const alertsButton = document.getElementById("alertsButton");
const alertToast = document.getElementById("alertToast");

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

alertsButton.addEventListener("click", async () => {
  if (!("Notification" in window)) {
    showAlertToast("Alertas no compatibles", "Este navegador no admite notificaciones.");
    return;
  }
  const permission = await Notification.requestPermission();
  updateAlertsButton();
  if (permission === "granted") {
    localStorage.removeItem(ALERT_STATE_KEY);
    alertBaselineReady = false;
    showAlertToast("Alertas activadas", "Te avisaremos de cambios tropicales mientras la app esté activa.");
  } else {
    showAlertToast("Permiso no concedido", "Puedes habilitar las notificaciones desde los permisos del sitio.");
  }
});

alertToast.querySelector("button").addEventListener("click", () => {
  alertToast.hidden = true;
});

function updateAlertsButton() {
  const enabled = "Notification" in window && Notification.permission === "granted";
  alertsButton.classList.toggle("enabled", enabled);
  alertsButton.innerHTML = enabled
    ? '<span aria-hidden="true">◆</span> Alertas activas'
    : '<span aria-hidden="true">♢</span> Activar alertas';
}

function alertState(payload, cyclonePayload) {
  const disturbances = (payload.areas?.features || []).map((feature) => ({
    id: `${prop(feature, "BASIN")}-${prop(feature, "AREA", "ID")}`,
    probability: probability(feature),
    risk: riskInfo(feature).key,
  }));
  const cyclones = (cyclonePayload.storms || []).map((storm) => ({
    id: storm.id,
    name: storm.name,
    type: storm.typeEs,
  }));
  return { disturbances, cyclones };
}

function evaluateTropicalAlerts(payload, cyclonePayload) {
  const current = alertState(payload, cyclonePayload);
  const previousRaw = localStorage.getItem(ALERT_STATE_KEY);
  localStorage.setItem(ALERT_STATE_KEY, JSON.stringify(current));
  if (!previousRaw) {
    alertBaselineReady = true;
    return;
  }

  let previous;
  try {
    previous = JSON.parse(previousRaw);
  } catch {
    return;
  }

  const previousDisturbances = new Map((previous.disturbances || []).map((item) => [item.id, item]));
  const previousCyclones = new Set((previous.cyclones || []).map((item) => item.id));

  current.cyclones.forEach((cyclone) => {
    if (!previousCyclones.has(cyclone.id)) {
      sendTropicalNotification(
        `Nuevo ${cyclone.type}`,
        `${cyclone.name} se encuentra activo según el NHC.`
      );
    }
  });

  current.disturbances.forEach((disturbance) => {
    const old = previousDisturbances.get(disturbance.id);
    if (!old) {
      sendTropicalNotification(
        "Nuevo disturbio tropical",
        `El NHC vigila una nueva zona con probabilidad de ${disturbance.probability}.`
      );
    } else if (old.probability !== disturbance.probability || old.risk !== disturbance.risk) {
      sendTropicalNotification(
        "Cambio en disturbio tropical",
        `La probabilidad cambió de ${old.probability} a ${disturbance.probability}.`
      );
    }
  });
}

async function sendTropicalNotification(title, body) {
  showAlertToast(title, body);
  if (!("Notification" in window) || Notification.permission !== "granted") return;
  const registration = await navigator.serviceWorker?.ready;
  if (registration) {
    registration.showNotification(title, {
      body,
      icon: "/icons/icon-192.png",
      badge: "/icons/icon-192.png",
      tag: `tropical-${title}-${body}`,
      data: { url: "/" },
    });
  }
}

function showAlertToast(title, text) {
  document.getElementById("alertToastTitle").textContent = title;
  document.getElementById("alertToastText").textContent = text;
  alertToast.hidden = false;
}

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
updateAlertsButton();
loadData();
setInterval(() => loadData(), 5 * 60 * 1000);
