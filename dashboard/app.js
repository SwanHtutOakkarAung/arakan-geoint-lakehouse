// ─────────────────────────────────────────────────────────────────────────────
// ARAKAN GEOINT LAKEHOUSE — HIGH-SPEED CLIENT ENGINE
// ─────────────────────────────────────────────────────────────────────────────

let map;
let eventsLayer;
let corridorsLayer;
let rawEvents = [];
let rawCorridors = [];

// 1. Initialize Map with Free, Reliable, Watermark-Free Basemaps
function initMap() {
  // A. ESRI Dark Tactical Canvas (Primary)
  const esriDarkBase = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}', {
    attribution: 'Esri, HERE, Garmin, &copy; OpenStreetMap contributors | MIMU Standards',
    maxZoom: 16
  });

  const esriDarkLabels = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}', {
    maxZoom: 16
  });

  const darkTacticalGroup = L.layerGroup([esriDarkBase, esriDarkLabels]);

  // B. ESRI Satellite Reconnaissance (Secondary)
  const esriSatellite = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
    attribution: 'Esri, Maxar, Earthstar Geographics | UN MIMU Standards',
    maxZoom: 18
  });

  const esriBorders = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}', {
    maxZoom: 18
  });

  const satelliteGroup = L.layerGroup([esriSatellite, esriBorders]);

  // C. OpenStreetMap (Fallback)
  const osmLayer = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; OpenStreetMap contributors',
    maxZoom: 18
  });

  // Base map container
  map = L.map('map', {
    center: [20.0, 93.3],
    zoom: 8,
    zoomControl: false,
    layers: [darkTacticalGroup]
  });

  L.control.zoom({ position: 'bottomright' }).addTo(map);

  // Basemap Switcher (Dark Tactical vs. Satellite Imagery)
  const baseMaps = {
    "🕶️ Dark Tactical": darkTacticalGroup,
    "🛰️ Satellite Recon": satelliteGroup,
    "🗺️ OpenStreetMap": osmLayer
  };

  eventsLayer = L.layerGroup().addTo(map);
  corridorsLayer = L.layerGroup().addTo(map);

  const overlayMaps = {
    "⚡ Conflict Events": eventsLayer,
    "🌐 Strategic Corridors (25km)": corridorsLayer
  };

  L.control.layers(baseMaps, overlayMaps, { position: 'topright' }).addTo(map);
}

// 2. Tab Navigation
function switchTab(tabId) {
  document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(panel => panel.style.display = 'none');

  const activeBtn = Array.from(document.querySelectorAll('.tab-btn'))
    .find(b => b.getAttribute('onclick') && b.getAttribute('onclick').includes(tabId));
  if (activeBtn) activeBtn.classList.add('active');

  const targetPanel = document.getElementById(tabId);
  if (targetPanel) targetPanel.style.display = 'block';
}

// 3. Ultra-Fast Data Fetching Engine (Single-Trip /api/bundle)
async function loadLakehouseData() {
  const startTime = performance.now();
  console.log("⚡ Fetching lakehouse data...");

  try {
    let metrics = {};
    let corridorsGeo = { features: [] };
    let eventsGeo = { features: [] };

    // Strategy 1: Fetch bundled payload in a single HTTP roundtrip
    const bundleRes = await fetch('/api/bundle');
    if (bundleRes.ok) {
      const bundle = await bundleRes.json();
      metrics = bundle.metrics || {};
      corridorsGeo = bundle.corridors || { features: [] };
      eventsGeo = bundle.events || { features: [] };
      console.log(`✅ Loaded bundle in ${(performance.now() - startTime).toFixed(1)}ms`);
    } else {
      // Strategy 2: Parallel fetch fallback with Promise.all
      console.warn("Falling back to parallel Promise.all fetch...");
      const [mRes, cRes, eRes] = await Promise.all([
        fetch('/data/gold/summary_metrics.json'),
        fetch('/data/gold/corridors.geojson'),
        fetch('/data/gold/events.geojson')
      ]);

      if (mRes.ok) metrics = await mRes.json();
      if (cRes.ok) corridorsGeo = await cRes.json();
      if (eRes.ok) eventsGeo = await eRes.json();
    }

    // A. Render Header KPIs
    document.getElementById('kpi-total-events').innerText = metrics.total_incidents ?? '--';
    document.getElementById('kpi-airstrikes').innerText = metrics.total_airstrikes ?? '--';
    document.getElementById('kpi-corridor-alerts').innerText = metrics.corridor_threat_alerts_25km ?? '--';
    document.getElementById('kpi-kia-claims').innerText = metrics.total_claimed_kia ?? '--';

    // B. Render Corridors
    rawCorridors = corridorsGeo.features || [];
    renderCorridors(rawCorridors);

    // C. Render Events & Populate All Intelligence Tabs
    rawEvents = eventsGeo.features || [];
    renderEvents(rawEvents);
    renderEventFeed(rawEvents);
    renderNarrativeDigest(rawEvents);
    renderOSINTCatalog(rawEvents);
    renderTownshipRiskTable(rawEvents);

    console.log(`🎉 Dashboard rendered in ${(performance.now() - startTime).toFixed(1)}ms (${rawEvents.length} events, ${rawCorridors.length} corridors)`);

  } catch (err) {
    console.error("❌ Failed to load lakehouse data:", err);
    document.getElementById('events-feed-list').innerHTML = `
      <div style="color:var(--accent-red); font-size:12px; padding:12px;">
        Error loading intelligence feed: ${err.message}
      </div>
    `;
  }
}

// 4. Render Strategic Corridors on Map
function renderCorridors(features) {
  corridorsLayer.clearLayers();
  const listContainer = document.getElementById('corridor-threat-list');
  listContainer.innerHTML = '';

  features.forEach(feat => {
    const coords = feat.geometry.coordinates; // [lon, lat]
    const p = feat.properties;

    // Cyan Tactical Diamond Marker
    const marker = L.circleMarker([coords[1], coords[0]], {
      radius: 9,
      fillColor: '#00f0ff',
      color: '#ffffff',
      weight: 2,
      opacity: 1,
      fillOpacity: 0.9
    });

    // 25km Threat Buffer Circle
    const bufferCircle = L.circle([coords[1], coords[0]], {
      radius: 25000,
      color: '#00f0ff',
      weight: 1.5,
      dashArray: '5, 8',
      fillColor: '#00f0ff',
      fillOpacity: 0.05
    });

    marker.bindPopup(`
      <div style="font-family: var(--font-ui); color: #111; max-width: 250px;">
        <div style="font-size: 10px; font-weight: 700; color: #0088cc; text-transform: uppercase;">Strategic Asset</div>
        <div style="font-size: 14px; font-weight: 700; margin: 4px 0;">${p.corridor_name}</div>
        <div style="font-size: 11px; color: #444; margin-bottom: 6px;">Sponsor: <strong>${p.sponsor_nation}</strong></div>
        <div style="font-size: 11px; line-height: 1.4; color: #222;">${p.description}</div>
      </div>
    `);

    corridorsLayer.addLayer(marker);
    corridorsLayer.addLayer(bufferCircle);

    // Tab 1 Card
    const card = document.createElement('div');
    card.className = 'event-card';
    card.style.borderLeftColor = '#00f0ff';
    card.innerHTML = `
      <div class="card-meta">
        <span class="badge cyan">${p.asset_type || 'CORRIDOR'}</span>
        <span>${(p.sponsor_nation || '').split(' ')[0]}</span>
      </div>
      <div class="card-title">${p.corridor_name}</div>
      <div class="card-desc">${p.description}</div>
      <div class="card-footer">
        <span>GPS: ${coords[1].toFixed(4)}, ${coords[0].toFixed(4)}</span>
        <button style="background:none; border:none; color:var(--accent-cyan); cursor:pointer; font-size:11px; font-weight:600;" onclick="zoomTo([${coords[1]}, ${coords[0]}])">Focus Map ↗</button>
      </div>
    `;
    listContainer.appendChild(card);
  });
}

// 5. Render Conflict Incidents on Map
function renderEvents(features) {
  eventsLayer.clearLayers();

  features.forEach(feat => {
    const coords = feat.geometry.coordinates; // [lon, lat]
    const p = feat.properties;

    const isAirstrike = p.category === 'AIRSTRIKE' || p.category === 'ARTILLERY_SHELLING';
    const markerColor = isAirstrike ? '#ff3366' : '#ffaa00';

    const marker = L.circleMarker([coords[1], coords[0]], {
      radius: isAirstrike ? 8 : 6,
      fillColor: markerColor,
      color: '#ffffff',
      weight: 1.5,
      opacity: 1,
      fillOpacity: 0.85
    });

    const proximityStr = p.corridor_dist_km != null ? `${p.corridor_dist_km}km from ${p.nearest_corridor}` : 'In theater';

    marker.bindPopup(`
      <div style="font-family: var(--font-ui); color: #111; max-width: 270px;">
        <div style="display:flex; justify-content:space-between; font-size:10px; font-weight:700; color:${markerColor};">
          <span>${p.category}</span>
          <span>${p.incident_date || 'Undated'}</span>
        </div>
        <div style="font-size: 13px; font-weight: 700; margin: 4px 0;">
          ${p.township || 'Rakhine'} ${p.mimu_pcode ? '(' + p.mimu_pcode + ')' : ''}
        </div>
        <div style="font-size: 11px; color: #333; margin-bottom: 6px; line-height: 1.4;">
          ${p.summary}
        </div>
        <div style="font-size: 10px; color: #666; border-top: 1px solid #ddd; padding-top: 4px; display:flex; justify-content:space-between;">
          <span>Proximity: <strong>${proximityStr}</strong></span>
          <a href="${p.source_url}" target="_blank" style="color:#0088cc; font-weight:600;">Telegram ↗</a>
        </div>
      </div>
    `);

    eventsLayer.addLayer(marker);
  });
}

// 6. Chronological Incident Feed (Tab 2)
function renderEventFeed(features) {
  const container = document.getElementById('events-feed-list');
  const countSpan = document.getElementById('event-feed-count');
  container.innerHTML = '';
  countSpan.innerText = `${features.length} Events Logged`;

  features.forEach(feat => {
    const coords = feat.geometry.coordinates;
    const p = feat.properties;
    const catClass = p.category === 'AIRSTRIKE' ? 'airstrike' : (p.category === 'NAVAL_ENGAGEMENT' ? 'naval' : 'clash');
    const badgeColor = p.category === 'AIRSTRIKE' ? 'red' : 'amber';
    const proximityStr = p.corridor_dist_km != null ? `${p.corridor_dist_km}km from ${p.nearest_corridor}` : '';

    const card = document.createElement('div');
    card.className = `event-card ${catClass}`;
    card.innerHTML = `
      <div class="card-meta">
        <span class="badge ${badgeColor}">${p.category}</span>
        <span>${p.incident_date || 'Undated'} • ${p.township || 'Rakhine'}</span>
      </div>
      <div class="card-title">${p.headline || p.summary}</div>
      <div class="card-desc">${p.summary}</div>
      <div class="card-footer">
        <span>${proximityStr}</span>
        <div style="display:flex; gap:12px;">
          <button style="background:none; border:none; color:var(--accent-cyan); cursor:pointer; font-size:11px; font-weight:600;" onclick="zoomTo([${coords[1]}, ${coords[0]}])">Focus Map ↗</button>
          <a href="${p.source_url}" target="_blank">Post ↗</a>
        </div>
      </div>
    `;
    container.appendChild(card);
  });
}

// 7. Township Risk Hierarchy (Tab 3)
function renderTownshipRiskTable(features) {
  const container = document.getElementById('township-risk-table');
  const aggregates = {};

  features.forEach(feat => {
    const p = feat.properties;
    const ts = p.township || 'Unspecified';
    if (!aggregates[ts]) {
      aggregates[ts] = {
        township: ts,
        pcode: p.mimu_pcode || 'UNKNOWN',
        total: 0,
        airstrikes: 0,
        kia: 0
      };
    }
    aggregates[ts].total += 1;
    if (p.category === 'AIRSTRIKE' || p.category === 'ARTILLERY_SHELLING') aggregates[ts].airstrikes += 1;
    aggregates[ts].kia += p.kia_reported || 0;
  });

  const rows = Object.values(aggregates).sort((a, b) => b.total - a.total);

  let html = `
    <table class="intel-table">
      <thead>
        <tr>
          <th>Township</th>
          <th>MIMU P-Code</th>
          <th>Events</th>
          <th>Airstrikes</th>
          <th>Claimed KIA</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>
  `;

  rows.forEach(r => {
    const statusTag = r.airstrikes >= 2 ? '<span class="threat-tag danger">CRITICAL</span>' : (r.total >= 1 ? '<span class="threat-tag warning">ACTIVE</span>' : '<span class="threat-tag safe">MONITORED</span>');
    html += `
      <tr>
        <td style="color:#fff; font-weight:600;">${r.township}</td>
        <td style="color:var(--text-muted); font-size:10px;">${r.pcode}</td>
        <td>${r.total}</td>
        <td style="color:var(--accent-red); font-weight:700;">${r.airstrikes}</td>
        <td style="color:var(--accent-amber);">${r.kia}</td>
        <td>${statusTag}</td>
      </tr>
    `;
  });

  html += '</tbody></table>';
  container.innerHTML = html;
}

// 8. Strategic Narrative Digest (Tab 4)
function renderNarrativeDigest(features) {
  const container = document.getElementById('narrative-feed-list');
  container.innerHTML = '';

  features.forEach(feat => {
    const p = feat.properties;
    const card = document.createElement('div');
    card.className = 'event-card';
    card.innerHTML = `
      <div class="card-meta">
        <span class="badge cyan">OFFICIAL COMMUNIQUE</span>
        <span>${p.incident_date || 'Date N/A'}</span>
      </div>
      <div class="card-title" style="font-size:12px; font-weight:500;">"${p.headline}"</div>
      <div class="card-desc" style="color:#ccd7e6;">${p.summary}</div>
      <div class="card-footer">
        <span>Event ID: ${p.event_id}</span>
        <a href="${p.source_url}" target="_blank">Full Post ↗</a>
      </div>
    `;
    container.appendChild(card);
  });
}

// 9. OSINT & Order of Battle (Tab 5)
function renderOSINTCatalog(features) {
  const container = document.getElementById('osint-catalog-list');
  container.innerHTML = '';

  const unitsFound = new Set();
  features.forEach(feat => {
    const p = feat.properties;
    if (p.opposing_actors) {
      p.opposing_actors.split(',').forEach(u => {
        if (u.trim()) unitsFound.add(u.trim());
      });
    }
  });

  let html = `
    <div style="margin-bottom:16px;">
      <h3 style="font-size:11px; text-transform:uppercase; color:var(--text-muted); margin-bottom:8px;">
        Identified Opponent Formations & Battalions
      </h3>
      <div style="display:flex; flex-wrap:wrap; gap:8px;">
  `;

  unitsFound.forEach(u => {
    html += `<span class="badge red" style="padding:4px 8px; font-size:10px;">${u}</span>`;
  });

  html += `
      </div>
    </div>
    <div style="margin-top:18px;">
      <h3 style="font-size:11px; text-transform:uppercase; color:var(--text-muted); margin-bottom:8px;">
        Tracked Military Assets & Strike Platforms
      </h3>
      <div class="event-card" style="border-left-color:var(--accent-red);">
        <div class="card-title">SAC Military Air Force (Aviation)</div>
        <div class="card-desc">Mi-35 combat helicopters, Y-12 transport bombers, and jet fighters providing close air support and heavy bombardments.</div>
      </div>
      <div class="event-card" style="border-left-color:#3b82f6;">
        <div class="card-title">Myanmar Navy Flotilla (Riverine & Coastal)</div>
        <div class="card-desc">Armed gunboats and landing craft firing heavy ordnance along Kaladan and Mayu river corridors.</div>
      </div>
    </div>
  `;

  container.innerHTML = html;
}

// 10. Map Navigation Helper
function zoomTo(coords) {
  if (map && coords) {
    map.flyTo(coords, 11, { duration: 1.0 });
  }
}

// Initialize on DOM Ready
document.addEventListener('DOMContentLoaded', () => {
  initMap();
  loadLakehouseData();
});
