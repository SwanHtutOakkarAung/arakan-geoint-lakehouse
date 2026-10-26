// ─────────────────────────────────────────────────────────────────────────────
// ARAKAN GEOINT LAKEHOUSE — DASHBOARD APPLICATION ENGINE
// ─────────────────────────────────────────────────────────────────────────────

let map;
let eventsLayer;
let corridorsLayer;
let rawEvents = [];
let rawCorridors = [];

// 1. Initialize Map
function initMap() {
  map = L.map('map', {
    center: [20.0, 93.3],
    zoom: 8,
    zoomControl: false
  });

  L.control.zoom({ position: 'bottomright' }).addTo(map);

  // CartoDB Dark Matter Base Tiles
  L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; <a href="https://carto.com/">CARTO</a> | MIMU UN Standards',
    maxZoom: 18,
    subdomains: 'abcd'
  }).addTo(map);

  eventsLayer = L.layerGroup().addTo(map);
  corridorsLayer = L.layerGroup().addTo(map);
}

// 2. Tab Navigation
function switchTab(tabId) {
  document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(panel => panel.style.display = 'none');

  const activeBtn = Array.from(document.querySelectorAll('.tab-btn'))
    .find(b => b.getAttribute('onclick').includes(tabId));
  if (activeBtn) activeBtn.classList.add('active');

  const targetPanel = document.getElementById(tabId);
  if (targetPanel) targetPanel.style.display = 'block';
}

// 3. Load Lakehouse Data
async function loadLakehouseData() {
  try {
    // A. Summary Metrics
    const metricsRes = await fetch('/data/gold/summary_metrics.json');
    if (metricsRes.ok) {
      const metrics = await metricsRes.json();
      document.getElementById('kpi-total-events').innerText = metrics.total_incidents || 0;
      document.getElementById('kpi-airstrikes').innerText = metrics.total_airstrikes || 0;
      document.getElementById('kpi-corridor-alerts').innerText = metrics.corridor_threat_alerts_25km || 0;
      document.getElementById('kpi-kia-claims').innerText = metrics.total_claimed_kia || 0;
    }

    // B. Strategic Corridors GeoJSON
    const corridorsRes = await fetch('/data/gold/corridors.geojson');
    if (corridorsRes.ok) {
      const corridorsGeo = await corridorsRes.json();
      rawCorridors = corridorsGeo.features || [];
      renderCorridors(rawCorridors);
    }

    // C. Conflict Events GeoJSON
    const eventsRes = await fetch('/data/gold/events.geojson');
    if (eventsRes.ok) {
      const eventsGeo = await eventsRes.json();
      rawEvents = eventsGeo.features || [];
      renderEvents(rawEvents);
      renderEventFeed(rawEvents);
      renderNarrativeDigest(rawEvents);
      renderOSINTCatalog(rawEvents);
    }

    // D. Township Risk Table
    renderTownshipRiskTable();

  } catch (err) {
    console.error("Failed to load lakehouse data:", err);
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

    // Marker
    const marker = L.circleMarker([coords[1], coords[0]], {
      radius: 8,
      fillColor: '#00f0ff',
      color: '#fff',
      weight: 2,
      opacity: 0.9,
      fillOpacity: 0.8
    });

    // 25km Buffer Circle
    const bufferCircle = L.circle([coords[1], coords[0]], {
      radius: 25000, // 25km in meters
      color: '#00f0ff',
      weight: 1,
      dashArray: '4, 8',
      fillColor: '#00f0ff',
      fillOpacity: 0.04
    });

    marker.bindPopup(`
      <div style="font-family: var(--font-ui); color: #111; max-width: 240px;">
        <div style="font-size: 10px; font-weight: 700; color: #0088cc; text-transform: uppercase;">Strategic Asset</div>
        <div style="font-size: 13px; font-weight: 700; margin: 4px 0;">${p.corridor_name}</div>
        <div style="font-size: 11px; color: #555; margin-bottom: 6px;">Sponsor: <strong>${p.sponsor_nation}</strong></div>
        <div style="font-size: 11px; line-height: 1.4;">${p.description}</div>
      </div>
    `);

    corridorsLayer.addLayer(marker);
    corridorsLayer.addLayer(bufferCircle);

    // Populate Tab 1 Card
    const card = document.createElement('div');
    card.className = 'event-card';
    card.style.borderLeftColor = '#00f0ff';
    card.innerHTML = `
      <div class="card-meta">
        <span class="badge cyan">${p.asset_type}</span>
        <span>${p.sponsor_nation.split(' ')[0]}</span>
      </div>
      <div class="card-title">${p.corridor_name}</div>
      <div class="card-desc">${p.description}</div>
      <div class="card-footer">
        <span>Coordinates: ${coords[1].toFixed(4)}, ${coords[0].toFixed(4)}</span>
        <button style="background:none; border:none; color:var(--accent-cyan); cursor:pointer; font-size:11px;" onclick="zoomTo([${coords[1]}, ${coords[0]}])">View on Map ↗</button>
      </div>
    `;
    listContainer.appendChild(card);
  });
}

// 5. Render Conflict Incidents on Map
function renderEvents(features) {
  eventsLayer.clearLayers();

  features.forEach(feat => {
    const coords = feat.geometry.coordinates;
    const p = feat.properties;

    const isAirstrike = p.category === 'AIRSTRIKE' || p.category === 'ARTILLERY_SHELLING';
    const markerColor = isAirstrike ? '#ff3366' : '#ffaa00';

    const marker = L.circleMarker([coords[1], coords[0]], {
      radius: isAirstrike ? 7 : 5,
      fillColor: markerColor,
      color: '#fff',
      weight: 1.5,
      opacity: 0.9,
      fillOpacity: 0.85
    });

    marker.bindPopup(`
      <div style="font-family: var(--font-ui); color: #111; max-width: 260px;">
        <div style="display:flex; justify-content:space-between; font-size:10px; font-weight:700; color:${markerColor};">
          <span>${p.category}</span>
          <span>${p.incident_date || 'Undated'}</span>
        </div>
        <div style="font-size: 13px; font-weight: 700; margin: 4px 0;">
          ${p.township || 'Rakhine'} (${p.mimu_pcode || 'MIMU'})
        </div>
        <div style="font-size: 11px; color: #444; margin-bottom: 6px; line-height: 1.4;">
          ${p.summary}
        </div>
        <div style="font-size: 10px; color: #777; border-top: 1px solid #ddd; padding-top: 4px; display:flex; justify-content:space-between;">
          <span>Proximity: <strong>${p.corridor_dist_km ? p.corridor_dist_km + 'km to ' + p.nearest_corridor : 'N/A'}</strong></span>
          <a href="${p.source_url}" target="_blank" style="color:#0088cc;">Source ↗</a>
        </div>
      </div>
    `);

    eventsLayer.addLayer(marker);
  });
}

// 6. Chronological Incident Feed
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

    const card = document.createElement('div');
    card.className = `event-card ${catClass}`;
    card.innerHTML = `
      <div class="card-meta">
        <span class="badge ${badgeColor}">${p.category}</span>
        <span>${p.incident_date || 'Date N/A'} • ${p.township || 'Rakhine'}</span>
      </div>
      <div class="card-title">${p.headline}</div>
      <div class="card-desc">${p.summary}</div>
      <div class="card-footer">
        <span>${p.nearest_corridor ? p.corridor_dist_km + 'km from ' + p.nearest_corridor : ''}</span>
        <div style="display:flex; gap:10px;">
          <button style="background:none; border:none; color:var(--accent-cyan); cursor:pointer; font-size:11px;" onclick="zoomTo([${coords[1]}, ${coords[0]}])">Focus Map ↗</button>
          <a href="${p.source_url}" target="_blank">Source ↗</a>
        </div>
      </div>
    `;
    container.appendChild(card);
  });
}

// 7. Township Risk Hierarchy
function renderTownshipRiskTable() {
  const container = document.getElementById('township-risk-table');
  
  // Aggregate from raw events
  const aggregates = {};
  rawEvents.forEach(feat => {
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
    if (p.category === 'AIRSTRIKE') aggregates[ts].airstrikes += 1;
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
    const statusTag = r.airstrikes > 1 ? '<span class="threat-tag danger">CRITICAL</span>' : (r.total > 1 ? '<span class="threat-tag warning">ACTIVE</span>' : '<span class="threat-tag safe">MONITORED</span>');
    html += `
      <tr>
        <td style="color:#fff; font-weight:600;">${r.township}</td>
        <td style="color:var(--text-muted);">${r.pcode}</td>
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

// 8. Strategic Narrative Digest
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
        <span>Lineage: AA Telegram Post #${p.source_message_id}</span>
        <a href="${p.source_url}" target="_blank">Full Post ↗</a>
      </div>
    `;
    container.appendChild(card);
  });
}

// 9. OSINT & Order of Battle (ORBAT)
function renderOSINTCatalog(features) {
  const container = document.getElementById('osint-catalog-list');
  container.innerHTML = '';

  const unitsFound = new Set();
  const materielFound = new Set();

  features.forEach(feat => {
    const p = feat.properties;
    if (p.opposing_actors) {
      p.opposing_actors.split(',').forEach(u => {
        if (u.trim()) unitsFound.add(u.trim());
      });
    }
  });

  let html = `
    <div style="margin-bottom:14px;">
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
        Tracked Tactical Threat Categories
      </h3>
      <div class="event-card" style="border-left-color:var(--accent-red);">
        <div class="card-title">SAC Aviation & Air Superiority</div>
        <div class="card-desc">Mi-35 Attack Helicopters, Y-12 Transport Bombers, Jet Fighters flying out of Magway and Sittwe airbases.</div>
      </div>
      <div class="event-card" style="border-left-color:#3b82f6;">
        <div class="card-title">Myanmar Navy Flotilla & Riverine Patrols</div>
        <div class="card-desc">Armed gunboats and landing craft operating in Kaladan and Mayu river corridors.</div>
      </div>
    </div>
  `;

  container.innerHTML = html;
}

// 10. Map Navigation Helper
function zoomTo(coords) {
  if (map && coords) {
    map.flyTo(coords, 11, { duration: 1.2 });
  }
}

// On Page Load
document.addEventListener('DOMContentLoaded', () => {
  initMap();
  loadLakehouseData();
});
