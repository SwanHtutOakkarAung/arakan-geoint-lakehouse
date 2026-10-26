// ─────────────────────────────────────────────────────────────────────────────
// ARAKAN GEOINT LAKEHOUSE — HIGH-SPEED REDESIGNED ENGINE
// ─────────────────────────────────────────────────────────────────────────────

let map;
let eventsLayer;
let corridorsLayer;
let rawEvents = [];
let rawCorridors = [];

// Filtering & UI State
let activeChip = 'ALL';
let searchQuery = '';
let sortOrder = 'DESC'; // 'DESC' = newest first, 'ASC' = oldest first
let timelinePercent = 100;
let timelineInterval = null;
let isPlaying = false;

// 1. Initialize Map with Free, Reliable, Watermark-Free Basemaps
function initMap() {
  // A. ESRI Dark Tactical Canvas (Default)
  const esriDarkBase = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}', {
    attribution: 'Esri, HERE, Garmin, &copy; OpenStreetMap | MIMU Standards',
    maxZoom: 16
  });

  const esriDarkLabels = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}', {
    maxZoom: 16
  });

  const darkTacticalGroup = L.layerGroup([esriDarkBase, esriDarkLabels]);

  // B. ESRI Satellite Reconnaissance (Alternative)
  const esriSatellite = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
    attribution: 'Esri, Maxar, Earthstar Geographics | UN MIMU Standards',
    maxZoom: 18
  });

  const esriBorders = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}', {
    maxZoom: 18
  });

  const satelliteGroup = L.layerGroup([esriSatellite, esriBorders]);

  // Base map container
  map = L.map('map', {
    center: [20.0, 93.3],
    zoom: 8,
    zoomControl: false,
    layers: [darkTacticalGroup]
  });

  L.control.zoom({ position: 'bottomright' }).addTo(map);

  const baseMaps = {
    "🕶️ Dark Tactical": darkTacticalGroup,
    "🛰️ Satellite Recon": satelliteGroup
  };

  eventsLayer = L.layerGroup().addTo(map);
  corridorsLayer = L.layerGroup().addTo(map);

  const overlayMaps = {
    "⚡ Conflict Events": eventsLayer,
    "🌐 Strategic Corridors (25km)": corridorsLayer
  };

  L.control.layers(baseMaps, overlayMaps, { position: 'topright' }).addTo(map);
}

// 2. Drawer Navigation & Toggling
function switchDrawerTab(tabId) {
  document.querySelectorAll('.nav-tab').forEach(btn => btn.classList.remove('active'));
  document.querySelectorAll('.tab-panel').forEach(panel => panel.style.display = 'none');

  const activeBtn = Array.from(document.querySelectorAll('.nav-tab'))
    .find(b => b.getAttribute('onclick') && b.getAttribute('onclick').includes(tabId));
  if (activeBtn) activeBtn.classList.add('active');

  const targetPanel = document.getElementById(tabId);
  if (targetPanel) targetPanel.style.display = 'block';
}

function toggleIntelDrawer(open) {
  const drawer = document.getElementById('intel-drawer');
  if (open) {
    drawer.classList.remove('collapsed');
  } else {
    drawer.classList.add('collapsed');
  }
}

// 3. Ultra-Fast Data Fetching Engine (Single-Trip /api/bundle)
async function loadLakehouseData() {
  const startTime = performance.now();
  console.log("⚡ Fetching lakehouse data...");

  try {
    let metrics = {};
    let corridorsGeo = { features: [] };
    let eventsGeo = { features: [] };

    const bundleRes = await fetch('/api/bundle');
    if (bundleRes.ok) {
      const bundle = await bundleRes.json();
      metrics = bundle.metrics || {};
      corridorsGeo = bundle.corridors || { features: [] };
      eventsGeo = bundle.events || { features: [] };
      console.log(`✅ Loaded bundle in ${(performance.now() - startTime).toFixed(1)}ms`);
    } else {
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
    renderEventFeed();
    renderNarrativeDigest(rawEvents);
    renderOSINTCatalog(rawEvents);
    renderTownshipRiskTable(rawEvents);

    console.log(`🎉 Redesigned Dashboard active (${rawEvents.length} events, ${rawCorridors.length} corridors)`);

  } catch (err) {
    console.error("❌ Failed to load lakehouse data:", err);
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

    const marker = L.circleMarker([coords[1], coords[0]], {
      radius: 9,
      fillColor: '#00f0ff',
      color: '#ffffff',
      weight: 2,
      opacity: 1,
      fillOpacity: 0.9
    });

    const bufferCircle = L.circle([coords[1], coords[0]], {
      radius: 25000,
      color: '#00f0ff',
      weight: 1.5,
      dashArray: '5, 8',
      fillColor: '#00f0ff',
      fillOpacity: 0.05
    });

    marker.on('click', () => {
      showCorridorBriefing(p, coords);
    });

    corridorsLayer.addLayer(marker);
    corridorsLayer.addLayer(bufferCircle);

    const card = document.createElement('div');
    card.className = 'event-card';
    card.style.borderLeftColor = '#00f0ff';
    card.onclick = () => {
      zoomTo([coords[1], coords[0]]);
      showCorridorBriefing(p, coords);
    };

    card.innerHTML = `
      <div class="card-top">
        <span class="tag-badge cyan">${p.asset_type || 'CORRIDOR'}</span>
        <span class="card-date">${(p.sponsor_nation || '').split(' ')[0]}</span>
      </div>
      <div class="card-title">${p.corridor_name}</div>
      <div class="card-summary">${p.description}</div>
      <div class="card-bottom">
        <span>GPS: ${coords[1].toFixed(4)}, ${coords[0].toFixed(4)}</span>
        <span style="color:var(--accent-cyan); font-weight:600;">Focus Map ↗</span>
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
    const isEarly2022 = (p.source_message_id <= 50) || (p.incident_date && p.incident_date.startsWith('2022'));

    let markerColor = '#ffaa00';
    if (isAirstrike) markerColor = '#ff3366';
    if (isEarly2022) markerColor = '#00ffaa';

    const marker = L.circleMarker([coords[1], coords[0]], {
      radius: isAirstrike ? 8 : (isEarly2022 ? 5 : 6),
      fillColor: markerColor,
      color: '#ffffff',
      weight: 1.5,
      opacity: 1,
      fillOpacity: 0.85
    });

    marker.on('click', () => {
      showEventBriefing(p, coords);
    });

    eventsLayer.addLayer(marker);
  });
}

// 6. Chronological Incident Feed with Search & Filters
function renderEventFeed() {
  const container = document.getElementById('events-feed-list');
  container.innerHTML = '';

  let filtered = rawEvents.filter(feat => {
    const p = feat.properties;
    const is2022 = (p.source_message_id <= 50) || (p.incident_date && p.incident_date.startsWith('2022'));

    // Category Chip Filter
    if (activeChip === 'AIRSTRIKE' && p.category !== 'AIRSTRIKE' && p.category !== 'ARTILLERY_SHELLING') return false;
    if (activeChip === 'ARMED_CLASH' && p.category !== 'ARMED_CLASH') return false;
    if (activeChip === 'INCEPTION' && !is2022) return false;

    // Search Query Filter
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      const inText = (p.headline || '').toLowerCase().includes(q) ||
                     (p.summary || '').toLowerCase().includes(q) ||
                     (p.township || '').toLowerCase().includes(q) ||
                     (p.opposing_actors || '').toLowerCase().includes(q);
      if (!inText) return false;
    }

    return true;
  });

  // Sort
  filtered.sort((a, b) => {
    const idA = a.properties.source_message_id;
    const idB = b.properties.source_message_id;
    return sortOrder === 'ASC' ? (idA - idB) : (idB - idA);
  });

  if (filtered.length === 0) {
    container.innerHTML = `
      <div style="text-align:center; padding:30px 10px; color:var(--text-muted); font-size:12px;">
        No incidents match your filter.
      </div>
    `;
    return;
  }

  filtered.forEach((feat, index) => {
    const coords = feat.geometry.coordinates;
    const p = feat.properties;
    const is2022 = (p.source_message_id <= 50) || (p.incident_date && p.incident_date.startsWith('2022'));

    let catClass = p.category === 'AIRSTRIKE' ? 'airstrike' : (p.category === 'ARMED_CLASH' ? 'clash' : '');
    let tagColor = p.category === 'AIRSTRIKE' ? 'red' : 'amber';
    let tagText = p.category;

    if (is2022) {
      catClass = 'inception';
      tagColor = 'emerald';
      tagText = `🌱 INCEPTION • #${p.source_message_id}`;
    }

    const proximityStr = p.corridor_dist_km != null ? `${p.corridor_dist_km}km from ${p.nearest_corridor}` : (is2022 ? 'Political / Strategic' : 'Rakhine Theater');

    const card = document.createElement('div');
    card.className = `event-card ${catClass}`;
    card.onclick = (e) => {
      if (e.target.closest('.accordion-toggle') || e.target.closest('.card-details-drawer')) return;
      zoomTo([coords[1], coords[0]]);
      showEventBriefing(p, coords);
    };

    const cardId = `drawer-detail-${p.source_message_id}`;

    card.innerHTML = `
      <div class="card-top">
        <span class="tag-badge ${tagColor}">${tagText}</span>
        <span class="card-date">${p.incident_date || 'Date N/A'}</span>
      </div>
      <div class="card-title">${p.headline || p.summary}</div>
      <div class="card-summary">${p.summary}</div>
      
      <div class="card-bottom">
        <span>${p.township || 'Rakhine'}</span>
        <button class="accordion-toggle" onclick="toggleCardAccordion('${cardId}', event)">
          <span>Details</span> <span>▾</span>
        </button>
      </div>

      <div class="card-details-drawer" id="${cardId}">
        <div style="margin-bottom:6px;"><strong>Proximity:</strong> ${proximityStr}</div>
        <div style="margin-bottom:6px;"><strong>Reported Opponents:</strong> ${p.opposing_actors || 'None specified'}</div>
        <div style="margin-bottom:6px;"><strong>Claimed Casualties:</strong> ${p.kia_reported || 0} KIA, ${p.wounded_reported || 0} Wounded</div>
        <div style="margin-top:6px; display:flex; justify-content:space-between; align-items:center;">
          <span style="font-size:10px; color:var(--text-muted);">MIMU: ${p.mimu_pcode || 'THEATER'}</span>
          <a href="${p.source_url}" target="_blank" style="color:var(--accent-cyan); text-decoration:none; font-weight:600;">Telegram #${p.source_message_id} ↗</a>
        </div>
      </div>
    `;
    container.appendChild(card);
  });
}

function toggleCardAccordion(drawerId, evt) {
  evt.stopPropagation();
  const el = document.getElementById(drawerId);
  if (el) {
    el.classList.toggle('open');
  }
}

// 7. Tactical Briefing Flyout (Right Side)
function showEventBriefing(p, coords) {
  const flyout = document.getElementById('briefing-flyout');
  document.getElementById('bf-category').innerText = p.category;
  document.getElementById('bf-title').innerText = `${p.township || 'Rakhine'} Incident`;
  document.getElementById('bf-summary').innerText = p.summary || p.headline;
  document.getElementById('bf-date').innerText = p.incident_date || 'Undated';
  document.getElementById('bf-township').innerText = `${p.township || 'Rakhine'} (${p.mimu_pcode || 'THEATER'})`;
  document.getElementById('bf-casualties').innerText = `${p.kia_reported || 0} KIA claimed, ${p.wounded_reported || 0} wounded`;
  document.getElementById('bf-corridor').innerText = p.nearest_corridor ? `${p.corridor_dist_km}km to ${p.nearest_corridor}` : 'In theater';
  document.getElementById('bf-coords').innerText = `${coords[1].toFixed(4)}, ${coords[0].toFixed(4)}`;
  document.getElementById('bf-event-id').innerText = p.event_id;
  document.getElementById('bf-source-link').href = p.source_url;

  flyout.style.display = 'block';
}

function showCorridorBriefing(p, coords) {
  const flyout = document.getElementById('briefing-flyout');
  document.getElementById('bf-category').innerText = p.asset_type || 'STRATEGIC ASSET';
  document.getElementById('bf-title').innerText = p.corridor_name;
  document.getElementById('bf-summary').innerText = p.description;
  document.getElementById('bf-date').innerText = `Sponsor: ${p.sponsor_nation}`;
  document.getElementById('bf-township').innerText = 'Corridor Hub';
  document.getElementById('bf-casualties').innerText = 'International Infrastructure';
  document.getElementById('bf-corridor').innerText = 'Buffer Alert: 25km Radius';
  document.getElementById('bf-coords').innerText = `${coords[1].toFixed(4)}, ${coords[0].toFixed(4)}`;
  document.getElementById('bf-event-id').innerText = p.corridor_id;
  document.getElementById('bf-source-link').href = '#';

  flyout.style.display = 'block';
}

function closeBriefing() {
  document.getElementById('briefing-flyout').style.display = 'none';
}

// 8. Filter Helpers
function filterByChip(chip) {
  activeChip = chip;
  document.querySelectorAll('.filter-chips .chip').forEach(c => c.classList.remove('active'));
  if (chip === 'ALL') document.getElementById('chip-all').classList.add('active');
  if (chip === 'AIRSTRIKE') document.getElementById('chip-airstrike').classList.add('active');
  if (chip === 'ARMED_CLASH') document.getElementById('chip-clash').classList.add('active');
  if (chip === 'INCEPTION') document.getElementById('chip-inception').classList.add('active');
  renderEventFeed();
}

function onSearchFilter() {
  searchQuery = document.getElementById('event-search-input').value.trim();
  renderEventFeed();
}

function toggleSortOrder() {
  sortOrder = (sortOrder === 'DESC') ? 'ASC' : 'DESC';
  const btn = document.getElementById('chip-sort');
  btn.innerText = (sortOrder === 'ASC') ? '⬆️ Oldest' : '⬇️ Newest';
  renderEventFeed();
}

// 9. Interactive Bottom Timeline Scrubber
function jumpTimeline(val) {
  const slider = document.getElementById('timeline-slider');
  if (slider) {
    slider.value = val;
    onTimelineSlider(val);
  }
}

function onTimelineSlider(value) {
  timelinePercent = parseInt(value, 10);
  const badge = document.getElementById('timeline-current-label');
  const allChip = document.getElementById('chip-all');

  if (timelinePercent >= 98) {
    badge.innerText = 'ALL HISTORY (2022-2026)';
    renderEvents(rawEvents);
    if (allChip) allChip.innerText = `All (${rawEvents.length})`;
  } else {
    // Map percent 0-100 across items
    const cutoffIndex = Math.max(1, Math.floor((timelinePercent / 100) * rawEvents.length));
    const sorted = [...rawEvents].sort((a, b) => a.properties.source_message_id - b.properties.source_message_id);
    const sliced = sorted.slice(0, cutoffIndex);
    const lastItem = sliced[sliced.length - 1];
    badge.innerText = `Through #${lastItem.properties.source_message_id} (${lastItem.properties.incident_date || '2022'})`;
    renderEvents(sliced);
    if (allChip) allChip.innerText = `Timeline (${sliced.length}/${rawEvents.length})`;
  }
}

function toggleTimelinePlay() {
  const btn = document.getElementById('timeline-play-btn');
  const slider = document.getElementById('timeline-slider');

  if (isPlaying) {
    clearInterval(timelineInterval);
    isPlaying = false;
    btn.innerText = '▶';
  } else {
    isPlaying = true;
    btn.innerText = '⏸';
    if (parseInt(slider.value, 10) >= 98) slider.value = 5;

    timelineInterval = setInterval(() => {
      let cur = parseInt(slider.value, 10) + 4;
      if (cur >= 100) {
        cur = 100;
        slider.value = cur;
        onTimelineSlider(cur);
        clearInterval(timelineInterval);
        isPlaying = false;
        btn.innerText = '▶';
      } else {
        slider.value = cur;
        onTimelineSlider(cur);
      }
    }, 600);
  }
}

// 10. Township Risk Table (Tab 3)
function renderTownshipRiskTable(features) {
  const container = document.getElementById('township-risk-table');
  const aggregates = {};

  features.forEach(feat => {
    const p = feat.properties;
    const ts = p.township || 'Rakhine Theater (General)';
    if (!aggregates[ts]) {
      aggregates[ts] = {
        township: ts,
        pcode: p.mimu_pcode || 'THEATER',
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
          <th>MIMU</th>
          <th>Events</th>
          <th>Airstrikes</th>
          <th>KIA</th>
        </tr>
      </thead>
      <tbody>
  `;

  rows.forEach(r => {
    html += `
      <tr>
        <td style="color:#fff; font-weight:600;">${r.township}</td>
        <td style="color:var(--text-muted); font-size:10px;">${r.pcode}</td>
        <td>${r.total}</td>
        <td style="color:var(--accent-red); font-weight:700;">${r.airstrikes}</td>
        <td style="color:var(--accent-amber);">${r.kia}</td>
      </tr>
    `;
  });

  html += '</tbody></table>';
  container.innerHTML = html;
}

// 11. Narrative & Strategic Comms (Tab 4)
function renderNarrativeDigest(features) {
  const container = document.getElementById('narrative-feed-list');
  container.innerHTML = '';

  features.slice(0, 20).forEach(feat => {
    const p = feat.properties;
    const is2022 = (p.source_message_id <= 50) || (p.incident_date && p.incident_date.startsWith('2022'));

    const card = document.createElement('div');
    card.className = 'event-card';
    if (is2022) card.style.borderLeftColor = 'var(--accent-emerald)';

    card.innerHTML = `
      <div class="card-top">
        <span class="tag-badge ${is2022 ? 'emerald' : 'cyan'}">${is2022 ? '🌱 INCEPTION STATEMENT' : 'OFFICIAL BULLETIN'}</span>
        <span class="card-date">${p.incident_date || 'Date N/A'}</span>
      </div>
      <div class="card-title" style="font-size:12px; font-weight:500;">"${p.headline}"</div>
      <div class="card-summary">${p.summary}</div>
      <div class="card-bottom">
        <span>Post ID: #${p.source_message_id}</span>
        <a href="${p.source_url}" target="_blank" style="color:var(--accent-cyan); text-decoration:none; font-weight:600;">Telegram ↗</a>
      </div>
    `;
    container.appendChild(card);
  });
}

// 12. OSINT / ORBAT (Tab 5)
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
    <div style="margin-bottom:14px;">
      <h3 style="font-size:11px; text-transform:uppercase; color:var(--text-muted); margin-bottom:8px;">
        Identified Opponent Formations & Battalions
      </h3>
      <div style="display:flex; flex-wrap:wrap; gap:6px;">
  `;

  unitsFound.forEach(u => {
    html += `<span class="tag-badge red" style="padding:4px 8px; font-size:10px;">${u}</span>`;
  });

  html += `
      </div>
    </div>
    <div style="margin-top:16px;">
      <h3 style="font-size:11px; text-transform:uppercase; color:var(--text-muted); margin-bottom:8px;">
        Strike Platforms Monitored
      </h3>
      <div class="event-card airstrike">
        <div class="card-title">SAC Aviation & Air Superiority</div>
        <div class="card-summary">Mi-35 Attack Helicopters, Y-12 Transport Bombers, Jet Fighters flying out of Magway and Sittwe airbases.</div>
      </div>
      <div class="event-card clash">
        <div class="card-title">Myanmar Navy Flotilla (Riverine & Coastal)</div>
        <div class="card-summary">Armed gunboats and landing craft firing heavy ordnance along Kaladan and Mayu river corridors.</div>
      </div>
    </div>
  `;

  container.innerHTML = html;
}

// 13. Map Navigation Helper
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
