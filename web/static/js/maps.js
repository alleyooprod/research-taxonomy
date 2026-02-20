/**
 * Market map (drag-drop tiles), compare companies, geographic map (Leaflet).
 * Includes marker clustering, heatmap toggle, and Turf.js geographic utilities.
 */

let compareSelection = new Set();
let leafletMap = null;
let markerClusterGroup = null;
let _heatLayer = null;
let _geoHeatmapOn = false;
let _geoCompaniesCache = []; // cache companies for heatmap toggle and turf operations

async function loadMarketMap() {
    const [compRes, taxRes] = await Promise.all([
        fetch(`/api/companies?project_id=${currentProjectId}`),
        fetch(`/api/taxonomy?project_id=${currentProjectId}`),
    ]);
    const companies = await compRes.json();
    const categories = await taxRes.json();

    const topLevel = categories.filter(c => !c.parent_id).sort((a, b) => a.name.localeCompare(b.name));

    const byCategory = {};
    companies.forEach(c => {
        const catId = c.category_id || 0;
        byCategory[catId] = byCategory[catId] || [];
        byCategory[catId].push(c);
    });

    const mapDiv = document.getElementById('marketMap');
    mapDiv.innerHTML = topLevel.map(cat => {
        const catColor = getCategoryColor(cat.id);
        return `
        <div class="map-column"
             ondragover="event.preventDefault();this.classList.add('drag-over')"
             ondragleave="this.classList.remove('drag-over')"
             ondrop="handleMapDrop(event, ${cat.id})"
             data-category-id="${cat.id}"
             style="${catColor ? `border-top: 3px solid ${catColor}` : ''}">
            <div class="map-column-header"><span class="cat-color-dot" style="background:${catColor || 'transparent'}"></span> ${esc(cat.name)} <span class="count">(${(byCategory[cat.id] || []).length})</span></div>
            <div class="map-tiles">
                ${(byCategory[cat.id] || []).sort((a,b) => a.name.localeCompare(b.name)).map(c => `
                    <div class="map-tile ${compareSelection.has(c.id) ? 'tile-selected' : ''}"
                         draggable="true"
                         ondragstart="event.dataTransfer.setData('text/plain', '${c.id}')"
                         onclick="toggleCompareSelect(${c.id}, this)"
                         title="${esc(c.what || '')}">
                        <img class="map-tile-logo" src="${c.logo_url || `https://logo.clearbit.com/${extractDomain(c.url)}`}" alt="" onerror="this.style.display='none'">
                        <span class="map-tile-name">${esc(c.name)}</span>
                    </div>
                `).join('')}
            </div>
        </div>`;
    }).join('');

    updateCompareBar();
    setTimeout(initMapPanzoom, 100);
}

async function handleMapDrop(event, targetCategoryId) {
    event.preventDefault();
    event.currentTarget.classList.remove('drag-over');
    const companyId = event.dataTransfer.getData('text/plain');
    if (!companyId) return;

    await safeFetch(`/api/companies/${companyId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ category_id: targetCategoryId, project_id: currentProjectId }),
    });

    loadMarketMap();
    loadTaxonomy();
}

function toggleCompareSelect(id, el) {
    if (compareSelection.has(id)) {
        compareSelection.delete(id);
        el.classList.remove('tile-selected');
    } else if (compareSelection.size < 4) {
        compareSelection.add(id);
        el.classList.add('tile-selected');
    } else {
        showToast('Maximum 4 companies for comparison. Deselect one first.');
    }
    updateCompareBar();
}

function updateCompareBar() {
    const bar = document.getElementById('compareBar');
    if (compareSelection.size > 0) {
        bar.classList.remove('hidden');
        document.getElementById('compareCount').textContent = `${compareSelection.size} selected`;
    } else {
        bar.classList.add('hidden');
    }
}

function clearCompareSelection() {
    compareSelection.clear();
    document.querySelectorAll('.map-tile.tile-selected').forEach(el => el.classList.remove('tile-selected'));
    updateCompareBar();
}

async function runComparison() {
    if (compareSelection.size < 2) { showToast('Select at least 2 companies'); return; }
    const ids = Array.from(compareSelection).join(',');
    const res = await safeFetch(`/api/companies/compare?ids=${ids}`);
    const companies = await res.json();

    const fields = ['what', 'target', 'products', 'funding', 'geography',
        'employee_range', 'founded_year', 'funding_stage', 'total_funding_usd',
        'hq_city', 'hq_country', 'tam'];

    let html = '<table class="compare-table"><thead><tr><th>Field</th>';
    companies.forEach(c => { html += `<th>${esc(c.name)}</th>`; });
    html += '</tr></thead><tbody>';

    const labels = {
        what: 'What', target: 'Target', products: 'Products', funding: 'Funding',
        geography: 'Geography', employee_range: 'Employees', founded_year: 'Founded',
        funding_stage: 'Stage', total_funding_usd: 'Total Raised',
        hq_city: 'HQ City', hq_country: 'HQ Country', tam: 'TAM',
    };

    fields.forEach(f => {
        html += `<tr><td><strong>${labels[f] || f}</strong></td>`;
        companies.forEach(c => {
            let val = c[f];
            if (f === 'total_funding_usd' && val) val = typeof formatCurrency === 'function' ? formatCurrency(val) : '$' + Number(val).toLocaleString();
            html += `<td>${esc(String(val || 'N/A'))}</td>`;
        });
        html += '</tr>';
    });

    html += '<tr><td><strong>Tags</strong></td>';
    companies.forEach(c => { html += `<td>${(c.tags || []).join(', ') || 'None'}</td>`; });
    html += '</tr>';

    html += '</tbody></table>';

    document.getElementById('compareContent').innerHTML = html;
    document.getElementById('compareSection').classList.remove('hidden');
    document.getElementById('compareSection').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function clearComparison() {
    document.getElementById('compareSection').classList.add('hidden');
    clearCompareSelection();
}

async function exportMapPng() {
    if (typeof html2canvas === 'undefined') {
        showToast('html2canvas is still loading. Please try again in a moment.');
        return;
    }
    const mapEl = document.getElementById('marketMap');
    const canvas = await html2canvas(mapEl, { backgroundColor: getComputedStyle(document.documentElement).getPropertyValue('--bg-container').trim() });
    const link = document.createElement('a');
    link.download = 'market-map.png';
    link.href = canvas.toDataURL();
    link.click();
}

// --- Geographic Map (Leaflet) ---
const GEO_COORDS = {
    // --- Countries ---
    'US': [39.8, -98.5], 'USA': [39.8, -98.5], 'United States': [39.8, -98.5], 'United States of America': [39.8, -98.5],
    'UK': [54.0, -2.0], 'United Kingdom': [54.0, -2.0], 'GB': [54.0, -2.0], 'England': [52.4, -1.5], 'Scotland': [56.5, -4.2], 'Wales': [52.1, -3.8],
    'Canada': [56.1, -106.3], 'CA': [56.1, -106.3],
    'Germany': [51.2, 10.5], 'DE': [51.2, 10.5], 'Deutschland': [51.2, 10.5],
    'France': [46.6, 2.2], 'FR': [46.6, 2.2],
    'Israel': [31.0, 34.8], 'IL': [31.0, 34.8],
    'India': [20.6, 78.9], 'IN': [20.6, 78.9],
    'Australia': [-25.3, 133.8], 'AU': [-25.3, 133.8],
    'Singapore': [1.35, 103.8], 'SG': [1.35, 103.8],
    'Japan': [36.2, 138.3], 'JP': [36.2, 138.3],
    'China': [35.9, 104.2], 'CN': [35.9, 104.2],
    'Brazil': [-14.2, -51.9], 'BR': [-14.2, -51.9],
    'South Korea': [35.9, 127.8], 'Korea': [35.9, 127.8], 'KR': [35.9, 127.8],
    'Netherlands': [52.1, 5.3], 'NL': [52.1, 5.3], 'Holland': [52.1, 5.3],
    'Sweden': [60.1, 18.6], 'SE': [60.1, 18.6],
    'Switzerland': [46.8, 8.2], 'CH': [46.8, 8.2],
    'Spain': [40.5, -3.7], 'ES': [40.5, -3.7],
    'Italy': [41.9, 12.6], 'IT': [41.9, 12.6],
    'Ireland': [53.4, -8.2], 'IE': [53.4, -8.2],
    'Mexico': [23.6, -102.5], 'MX': [23.6, -102.5],
    'Portugal': [39.4, -8.2], 'PT': [39.4, -8.2],
    'Belgium': [50.5, 4.5], 'BE': [50.5, 4.5],
    'Austria': [47.5, 14.6], 'AT': [47.5, 14.6],
    'Denmark': [56.3, 9.5], 'DK': [56.3, 9.5],
    'Norway': [60.5, 8.5], 'NO': [60.5, 8.5],
    'Finland': [61.9, 25.7], 'FI': [61.9, 25.7],
    'Poland': [51.9, 19.1], 'PL': [51.9, 19.1],
    'Czech Republic': [49.8, 15.5], 'Czechia': [49.8, 15.5], 'CZ': [49.8, 15.5],
    'Romania': [45.9, 24.97], 'RO': [45.9, 24.97],
    'Hungary': [47.2, 19.5], 'HU': [47.2, 19.5],
    'Greece': [39.1, 21.8], 'GR': [39.1, 21.8],
    'Turkey': [38.9, 35.2], 'TR': [38.9, 35.2], 'Türkiye': [38.9, 35.2],
    'Russia': [61.5, 105.3], 'RU': [61.5, 105.3],
    'Ukraine': [48.4, 31.2], 'UA': [48.4, 31.2],
    'South Africa': [30.6, 22.9], 'ZA': [30.6, 22.9],
    'Nigeria': [9.1, 8.7], 'NG': [9.1, 8.7],
    'Kenya': [-0.02, 37.9], 'KE': [-0.02, 37.9],
    'Egypt': [26.8, 30.8], 'EG': [26.8, 30.8],
    'UAE': [23.4, 53.8], 'United Arab Emirates': [23.4, 53.8],
    'Saudi Arabia': [23.9, 45.1], 'SA': [23.9, 45.1],
    'Qatar': [25.4, 51.2],
    'Bahrain': [26.1, 50.6],
    'Kuwait': [29.3, 47.5],
    'Oman': [21.5, 55.9],
    'Thailand': [15.9, 100.9], 'TH': [15.9, 100.9],
    'Vietnam': [14.1, 108.3], 'VN': [14.1, 108.3],
    'Indonesia': [-0.8, 113.9], 'ID': [-0.8, 113.9],
    'Malaysia': [4.2, 101.9], 'MY': [4.2, 101.9],
    'Philippines': [12.9, 121.8], 'PH': [12.9, 121.8],
    'Taiwan': [23.7, 121.0], 'TW': [23.7, 121.0],
    'Hong Kong': [22.3, 114.2], 'HK': [22.3, 114.2],
    'New Zealand': [-40.9, 174.9], 'NZ': [-40.9, 174.9],
    'Argentina': [-38.4, -63.6], 'AR': [-38.4, -63.6],
    'Colombia': [4.6, -74.1], 'CO': [4.6, -74.1],
    'Chile': [-35.7, -71.5], 'CL': [-35.7, -71.5],
    'Peru': [-9.2, -75.0], 'PE': [-9.2, -75.0],
    'Luxembourg': [49.8, 6.1], 'LU': [49.8, 6.1],
    'Estonia': [58.6, 25.0], 'EE': [58.6, 25.0],
    'Latvia': [56.9, 24.1], 'LV': [56.9, 24.1],
    'Lithuania': [55.2, 23.9], 'LT': [55.2, 23.9],
    'Croatia': [45.1, 15.2],
    'Serbia': [44.0, 21.0],
    'Bulgaria': [42.7, 25.5],
    'Slovakia': [48.7, 19.7],
    'Slovenia': [46.2, 14.9],
    'Iceland': [64.9, -19.0],
    'Malta': [35.9, 14.5],
    'Cyprus': [35.1, 33.4],
    'Morocco': [31.8, -7.1],
    'Tunisia': [33.9, 9.5],
    'Ghana': [7.9, -1.0],
    'Ethiopia': [9.1, 40.5],
    'Tanzania': [-6.4, 34.9],
    'Rwanda': [-1.9, 29.9],
    'Bangladesh': [23.7, 90.4],
    'Pakistan': [30.4, 69.3],
    'Sri Lanka': [7.9, 80.8],
    'Cambodia': [12.6, 104.99],
    'Myanmar': [21.9, 95.96],
    // --- Major Cities (Americas) ---
    'New York': [40.7, -74.0], 'NYC': [40.7, -74.0], 'New York City': [40.7, -74.0],
    'San Francisco': [37.8, -122.4], 'SF': [37.8, -122.4],
    'Los Angeles': [34.1, -118.2], 'LA': [34.1, -118.2],
    'Chicago': [41.9, -87.6],
    'Boston': [42.4, -71.1],
    'Austin': [30.3, -97.7],
    'Seattle': [47.6, -122.3],
    'Denver': [39.7, -105.0],
    'Dallas': [32.8, -96.8],
    'Houston': [29.8, -95.4],
    'Miami': [25.8, -80.2],
    'Atlanta': [33.7, -84.4],
    'Philadelphia': [40.0, -75.2],
    'Washington': [38.9, -77.0], 'Washington DC': [38.9, -77.0], 'DC': [38.9, -77.0], 'Washington, D.C.': [38.9, -77.0],
    'Phoenix': [33.4, -112.1],
    'San Diego': [32.7, -117.2],
    'San Jose': [37.3, -121.9],
    'Portland': [45.5, -122.7],
    'Minneapolis': [44.97, -93.3],
    'Nashville': [36.2, -86.8],
    'Charlotte': [35.2, -80.8],
    'Salt Lake City': [40.8, -111.9],
    'Raleigh': [35.8, -78.6],
    'Pittsburgh': [40.4, -80.0],
    'Indianapolis': [39.8, -86.2],
    'Detroit': [42.3, -83.0],
    'Columbus': [39.96, -83.0],
    'San Antonio': [29.4, -98.5],
    'Tampa': [27.95, -82.5],
    'Orlando': [28.5, -81.4],
    'Palo Alto': [37.4, -122.1],
    'Mountain View': [37.4, -122.1],
    'Menlo Park': [37.5, -122.2],
    'Sunnyvale': [37.4, -122.0],
    'Redwood City': [37.5, -122.2],
    'Santa Monica': [34.0, -118.5],
    'Venice': [34.0, -118.5],
    'Brooklyn': [40.7, -73.9],
    'Manhattan': [40.8, -74.0],
    'Cambridge': [42.4, -71.1],
    'Somerville': [42.4, -71.1],
    'Boulder': [40.0, -105.3],
    'Toronto': [43.7, -79.4],
    'Vancouver': [49.3, -123.1],
    'Montreal': [45.5, -73.6], 'Montréal': [45.5, -73.6],
    'Ottawa': [45.4, -75.7],
    'Calgary': [51.0, -114.1],
    'Waterloo': [43.5, -80.5],
    'São Paulo': [23.6, -46.6], 'Sao Paulo': [-23.6, -46.6],
    'Rio de Janeiro': [-22.9, -43.2],
    'Mexico City': [19.4, -99.1], 'Ciudad de México': [19.4, -99.1],
    'Buenos Aires': [-34.6, -58.4],
    'Bogotá': [4.7, -74.1], 'Bogota': [4.7, -74.1],
    'Santiago': [-33.4, -70.7],
    'Lima': [-12.0, -77.0],
    'Medellín': [6.2, -75.6], 'Medellin': [6.2, -75.6],
    // --- Major Cities (Europe) ---
    'London': [51.5, -0.1],
    'Berlin': [52.5, 13.4],
    'Paris': [48.9, 2.3],
    'Amsterdam': [52.4, 4.9],
    'Munich': [48.1, 11.6], 'München': [48.1, 11.6],
    'Frankfurt': [50.1, 8.7],
    'Hamburg': [53.6, 10.0],
    'Zurich': [47.4, 8.5], 'Zürich': [47.4, 8.5],
    'Geneva': [46.2, 6.1], 'Genève': [46.2, 6.1],
    'Stockholm': [59.3, 18.1],
    'Copenhagen': [55.7, 12.6], 'København': [55.7, 12.6],
    'Oslo': [59.9, 10.8],
    'Helsinki': [60.2, 24.9],
    'Dublin': [53.3, -6.3],
    'Madrid': [40.4, -3.7],
    'Barcelona': [41.4, 2.2],
    'Milan': [45.5, 9.2], 'Milano': [45.5, 9.2],
    'Rome': [41.9, 12.5], 'Roma': [41.9, 12.5],
    'Vienna': [48.2, 16.4], 'Wien': [48.2, 16.4],
    'Brussels': [50.8, 4.4], 'Bruxelles': [50.8, 4.4],
    'Lisbon': [38.7, -9.1], 'Lisboa': [38.7, -9.1],
    'Prague': [50.1, 14.4], 'Praha': [50.1, 14.4],
    'Warsaw': [52.2, 21.0], 'Warszawa': [52.2, 21.0],
    'Budapest': [47.5, 19.0],
    'Bucharest': [44.4, 26.1], 'București': [44.4, 26.1],
    'Athens': [37.98, 23.7],
    'Istanbul': [41.0, 29.0],
    'Tallinn': [59.4, 24.7],
    'Riga': [56.9, 24.1],
    'Vilnius': [54.7, 25.3],
    'Edinburgh': [55.95, -3.2],
    'Manchester': [53.5, -2.2],
    'Birmingham': [52.5, -1.9],
    'Bristol': [51.5, -2.6],
    'Leeds': [53.8, -1.5],
    'Glasgow': [55.9, -4.3],
    'Cambridge UK': [52.2, 0.1],
    'Oxford': [51.8, -1.3],
    'Lyon': [45.8, 4.8],
    'Marseille': [43.3, 5.4],
    'Cologne': [50.9, 6.96], 'Köln': [50.9, 6.96],
    'Düsseldorf': [51.2, 6.8], 'Dusseldorf': [51.2, 6.8],
    'Stuttgart': [48.8, 9.2],
    'Gothenburg': [57.7, 12.0], 'Göteborg': [57.7, 12.0],
    'Malmö': [55.6, 13.0], 'Malmo': [55.6, 13.0],
    'Rotterdam': [51.9, 4.5],
    'The Hague': [52.1, 4.3],
    'Eindhoven': [51.4, 5.5],
    'Antwerp': [51.2, 4.4],
    'Basel': [47.6, 7.6],
    'Lausanne': [46.5, 6.6],
    'Bern': [46.9, 7.4],
    'Krakow': [50.1, 19.9], 'Kraków': [50.1, 19.9],
    'Wroclaw': [51.1, 17.0], 'Wrocław': [51.1, 17.0],
    'Zagreb': [45.8, 16.0],
    'Belgrade': [44.8, 20.5],
    'Sofia': [42.7, 23.3],
    'Bratislava': [48.1, 17.1],
    'Ljubljana': [46.1, 14.5],
    'Reykjavik': [64.1, -21.9], 'Reykjavík': [64.1, -21.9],
    'Nicosia': [35.2, 33.4],
    'Valletta': [35.9, 14.5],
    'Kiev': [50.5, 30.5], 'Kyiv': [50.5, 30.5],
    'Moscow': [55.8, 37.6], 'Moskva': [55.8, 37.6],
    'St. Petersburg': [59.9, 30.3], 'Saint Petersburg': [59.9, 30.3],
    // --- Major Cities (Middle East & Africa) ---
    'Tel Aviv': [32.1, 34.8], 'Tel Aviv-Yafo': [32.1, 34.8],
    'Jerusalem': [31.8, 35.2],
    'Haifa': [32.8, 35.0],
    'Dubai': [25.2, 55.3],
    'Abu Dhabi': [24.5, 54.7],
    'Riyadh': [24.7, 46.7],
    'Jeddah': [21.5, 39.2],
    'Doha': [25.3, 51.5],
    'Manama': [26.2, 50.6],
    'Muscat': [23.6, 58.5],
    'Kuwait City': [29.4, 48.0],
    'Amman': [31.9, 35.9],
    'Beirut': [33.9, 35.5],
    'Cairo': [30.0, 31.2],
    'Cape Town': [-33.9, 18.4],
    'Johannesburg': [-26.2, 28.0],
    'Nairobi': [-1.3, 36.8],
    'Lagos': [6.5, 3.4],
    'Accra': [5.6, -0.2],
    'Casablanca': [33.6, -7.6],
    'Kigali': [-1.9, 30.1],
    'Addis Ababa': [9.0, 38.7],
    'Dar es Salaam': [-6.8, 39.3],
    // --- Major Cities (Asia-Pacific) ---
    'Mumbai': [19.1, 72.9],
    'Bangalore': [12.97, 77.6], 'Bengaluru': [12.97, 77.6],
    'Delhi': [28.7, 77.1], 'New Delhi': [28.6, 77.2],
    'Hyderabad': [17.4, 78.5],
    'Chennai': [13.1, 80.3],
    'Pune': [18.5, 73.9],
    'Kolkata': [22.6, 88.4],
    'Ahmedabad': [23.0, 72.6],
    'Gurgaon': [28.5, 77.0], 'Gurugram': [28.5, 77.0],
    'Noida': [28.6, 77.3],
    'Tokyo': [35.7, 139.7],
    'Osaka': [34.7, 135.5],
    'Shanghai': [31.2, 121.5],
    'Beijing': [39.9, 116.4], 'Peking': [39.9, 116.4],
    'Shenzhen': [22.5, 114.1],
    'Guangzhou': [23.1, 113.3],
    'Hangzhou': [30.3, 120.2],
    'Chengdu': [30.6, 104.1],
    'Nanjing': [32.1, 118.8],
    'Wuhan': [30.6, 114.3],
    'Taipei': [25.0, 121.5],
    'Seoul': [37.6, 127.0],
    'Busan': [35.2, 129.1],
    'Bangkok': [13.8, 100.5],
    'Ho Chi Minh City': [10.8, 106.7], 'Saigon': [10.8, 106.7],
    'Hanoi': [21.0, 105.9],
    'Jakarta': [-6.2, 106.8],
    'Kuala Lumpur': [3.1, 101.7], 'KL': [3.1, 101.7],
    'Manila': [14.6, 121.0],
    'Sydney': [-33.9, 151.2],
    'Melbourne': [-37.8, 145.0],
    'Brisbane': [-27.5, 153.0],
    'Perth': [-31.95, 115.9],
    'Auckland': [-36.8, 174.8],
    'Wellington': [-41.3, 174.8],
    'Dhaka': [23.8, 90.4],
    'Karachi': [24.9, 67.0],
    'Lahore': [31.6, 74.4],
    'Islamabad': [33.7, 73.0],
    'Colombo': [6.9, 79.9],
    'Phnom Penh': [11.6, 104.9],
    'Yangon': [16.9, 96.2],
};

// Build a case-insensitive lookup for broader matching
const _GEO_LOOKUP = {};
Object.keys(GEO_COORDS).forEach(k => {
    _GEO_LOOKUP[k.toLowerCase()] = GEO_COORDS[k];
});

function getCoords(company) {
    const city = (company.hq_city || '').trim();
    const country = (company.hq_country || company.geography || '').trim();

    // Exact match on city
    if (city && GEO_COORDS[city]) return GEO_COORDS[city];
    // Exact match on country
    if (country && GEO_COORDS[country]) return GEO_COORDS[country];

    // Case-insensitive match on city
    if (city && _GEO_LOOKUP[city.toLowerCase()]) return _GEO_LOOKUP[city.toLowerCase()];
    // Case-insensitive match on country
    if (country && _GEO_LOOKUP[country.toLowerCase()]) return _GEO_LOOKUP[country.toLowerCase()];

    // Try first comma-separated segment (e.g. "US, Europe" → "US")
    const firstWord = (country || '').split(',')[0].trim();
    if (firstWord && GEO_COORDS[firstWord]) return GEO_COORDS[firstWord];
    if (firstWord && _GEO_LOOKUP[firstWord.toLowerCase()]) return _GEO_LOOKUP[firstWord.toLowerCase()];

    // Try second comma-separated segment
    const parts = (country || '').split(',').map(s => s.trim());
    for (const part of parts) {
        if (_GEO_LOOKUP[part.toLowerCase()]) return _GEO_LOOKUP[part.toLowerCase()];
    }

    // Try city + country combined match (e.g. "San Francisco" from "San Francisco, CA")
    const cityParts = (city || '').split(',').map(s => s.trim());
    for (const part of cityParts) {
        if (_GEO_LOOKUP[part.toLowerCase()]) return _GEO_LOOKUP[part.toLowerCase()];
    }

    return null;
}

async function renderGeoMap() {
    const container = document.getElementById('geoMap');
    if (!container) return;
    if (!window.L) {
        _waitForLib('map library', () => window.L, () => renderGeoMap(), container);
        return;
    }

    // --- Task 4: Grayscale CartoDB tile layer with label overlay ---
    if (!leafletMap) {
        leafletMap = L.map('geoMap', { zoomControl: false }).setView([30, 0], 2);
        // Base: grayscale tiles without labels
        L.tileLayer('https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png', {
            attribution: '&copy; <a href="https://carto.com/">CARTO</a> &copy; <a href="https://www.openstreetmap.org/copyright">OSM</a>',
            maxZoom: 19,
            subdomains: 'abcd',
        }).addTo(leafletMap);
        // Overlay: labels only, rendered on top of markers
        L.tileLayer('https://{s}.basemaps.cartocdn.com/light_only_labels/{z}/{x}/{y}{r}.png', {
            maxZoom: 19,
            subdomains: 'abcd',
            pane: 'overlayPane',
        }).addTo(leafletMap);
        // Minimal black/white zoom control, bottom-right
        L.control.zoom({ position: 'bottomright' }).addTo(leafletMap);
    }

    // --- Task 1: Marker clustering with custom instrument-style icons ---
    if (markerClusterGroup) leafletMap.removeLayer(markerClusterGroup);

    if (L.markerClusterGroup) {
        markerClusterGroup = L.markerClusterGroup({
            chunkedLoading: true,
            maxClusterRadius: 50,
            iconCreateFunction: function(cluster) {
                const count = cluster.getChildCount();
                const size = count < 10 ? 'small' : count < 50 ? 'medium' : 'large';
                const px = size === 'small' ? 32 : size === 'medium' ? 38 : 44;
                return L.divIcon({
                    html: '<div style="font-family:\'Plus Jakarta Sans\',\'JetBrains Mono\',sans-serif;font-size:12px;font-weight:600;color:#000;background:#fff;border:1px solid #000;width:' + px + 'px;height:' + px + 'px;display:flex;align-items:center;justify-content:center;">' + count + '</div>',
                    className: 'marker-cluster-instrument marker-cluster-instrument--' + size,
                    iconSize: [px, px],
                });
            },
        });
    } else {
        markerClusterGroup = L.layerGroup();
    }

    const res = await safeFetch(`/api/companies?project_id=${currentProjectId}`);
    const companies = await res.json();
    _geoCompaniesCache = companies;

    // --- Task 4: Simple black square markers, instrument-style popups ---
    companies.forEach(c => {
        const coords = getCoords(c);
        if (!coords) return;
        const cat = c.category_name || 'Unknown';

        const icon = L.divIcon({
            html: '<div class="geo-marker-square"></div>',
            className: 'geo-marker-icon',
            iconSize: [10, 10],
            iconAnchor: [5, 5],
        });
        const marker = L.marker(
            [coords[0] + (Math.random() - 0.5) * 0.5, coords[1] + (Math.random() - 0.5) * 0.5],
            { icon }
        );
        marker.bindPopup(
            `<div class="geo-popup-instrument"><strong>${esc(c.name)}</strong><br><span class="geo-popup-cat">${esc(cat)}</span>${c.geography ? '<br>' + esc(c.geography) : ''}</div>`,
            { className: 'leaflet-popup-instrument', closeButton: false, minWidth: 120 }
        );
        markerClusterGroup.addLayer(marker);
    });

    leafletMap.addLayer(markerClusterGroup);

    // --- Task 2: Build heatmap layer (grayscale gradient) ---
    if (window.L && L.heatLayer) {
        if (_heatLayer) leafletMap.removeLayer(_heatLayer);
        const heatPoints = [];
        companies.forEach(c => {
            const coords = getCoords(c);
            if (!coords) return;
            // Weight by funding if available, otherwise default 0.5
            const weight = c.total_funding_usd ? Math.min(1, Math.log10(c.total_funding_usd + 1) / 10) : 0.5;
            heatPoints.push([coords[0], coords[1], weight]);
        });
        _heatLayer = L.heatLayer(heatPoints, {
            radius: 25, blur: 15, maxZoom: 17,
            gradient: { 0.4: '#E5E5E5', 0.6: '#999999', 0.8: '#333333', 1: '#000000' },
        });
        if (_geoHeatmapOn) _heatLayer.addTo(leafletMap);
    }

    // --- Task 3: Auto-fit map to all markers using Turf.js ---
    _fitMapToCompanies(companies, leafletMap);

    setTimeout(() => leafletMap.invalidateSize(), 100);
}

// --- Task 3: Turf.js geographic utilities ---

/**
 * Auto-fit map bounds to contain all company markers.
 * Uses turf.bbox() for precise bounding box calculation.
 */
function _fitMapToCompanies(companies, map) {
    if (!window.turf) return;
    const points = companies
        .filter(c => getCoords(c))
        .map(c => {
            const coords = getCoords(c);
            return turf.point([coords[1], coords[0]]); // turf uses [lng, lat]
        });
    if (points.length === 0) return;
    const fc = turf.featureCollection(points);
    const [minLng, minLat, maxLng, maxLat] = turf.bbox(fc);
    map.fitBounds([[minLat, minLng], [maxLat, maxLng]], { padding: [30, 30] });
}

/**
 * Find companies near a given lat/lng within radiusKm.
 * Uses turf.buffer() + turf.pointsWithinPolygon().
 * Returns array of company objects that fall within the buffer zone.
 */
function findCompaniesNear(lat, lng, radiusKm) {
    if (!window.turf) return [];
    const center = turf.point([lng, lat]);
    const buffered = turf.buffer(center, radiusKm, { units: 'kilometers' });
    const companies = _geoCompaniesCache || [];
    const companyPoints = [];
    const companyMap = {};

    companies.forEach(c => {
        const coords = getCoords(c);
        if (!coords) return;
        const pt = turf.point([coords[1], coords[0]], { id: c.id });
        companyPoints.push(pt);
        companyMap[c.id] = c;
    });

    if (companyPoints.length === 0) return [];
    const fc = turf.featureCollection(companyPoints);
    const within = turf.pointsWithinPolygon(fc, buffered);
    return within.features.map(f => companyMap[f.properties.id]).filter(Boolean);
}

/**
 * Calculate the geographic center (centroid) for companies in a given category.
 * Returns [lat, lng] or null if no geo-located companies.
 */
function getCategoryCentroid(categoryId) {
    if (!window.turf) return null;
    const companies = (_geoCompaniesCache || []).filter(c => c.category_id === categoryId);
    const points = companies
        .filter(c => getCoords(c))
        .map(c => {
            const coords = getCoords(c);
            return turf.point([coords[1], coords[0]]);
        });
    if (points.length === 0) return null;
    const fc = turf.featureCollection(points);
    const centroid = turf.centroid(fc);
    const [lng, lat] = centroid.geometry.coordinates;
    return [lat, lng];
}

function toggleGeoHeatmap() {
    if (!leafletMap) return;

    // If heatLayer library is not loaded, try building it from cache
    if (!_heatLayer && window.L && L.heatLayer && _geoCompaniesCache.length) {
        const heatPoints = [];
        _geoCompaniesCache.forEach(c => {
            const coords = getCoords(c);
            if (!coords) return;
            const weight = c.total_funding_usd ? Math.min(1, Math.log10(c.total_funding_usd + 1) / 10) : 0.5;
            heatPoints.push([coords[0], coords[1], weight]);
        });
        _heatLayer = L.heatLayer(heatPoints, {
            radius: 25, blur: 15, maxZoom: 17,
            gradient: { 0.4: '#E5E5E5', 0.6: '#999999', 0.8: '#333333', 1: '#000000' },
        });
    }

    if (!_heatLayer) return;

    _geoHeatmapOn = !_geoHeatmapOn;
    if (_geoHeatmapOn) {
        _heatLayer.addTo(leafletMap);
        // Hide markers when heatmap is on for cleaner view
        if (markerClusterGroup) leafletMap.removeLayer(markerClusterGroup);
    } else {
        leafletMap.removeLayer(_heatLayer);
        // Restore markers when heatmap is off
        if (markerClusterGroup) leafletMap.addLayer(markerClusterGroup);
    }
    const btn = document.getElementById('heatmapToggleBtn');
    if (btn) btn.classList.toggle('active', _geoHeatmapOn);
}

function switchMapView(view) {
    document.getElementById('marketMap').classList.add('hidden');
    document.getElementById('autoLayoutMap').classList.add('hidden');
    document.getElementById('geoMap').classList.add('hidden');
    document.getElementById('marketMapBtn').classList.remove('active');
    document.getElementById('autoMapBtn').classList.remove('active');
    document.getElementById('geoMapBtn').classList.remove('active');

    if (view === 'market') {
        document.getElementById('marketMap').classList.remove('hidden');
        document.getElementById('marketMapBtn').classList.add('active');
    } else if (view === 'auto') {
        document.getElementById('autoLayoutMap').classList.remove('hidden');
        document.getElementById('autoMapBtn').classList.add('active');
        renderAutoLayoutMap();
    } else {
        document.getElementById('geoMap').classList.remove('hidden');
        document.getElementById('geoMapBtn').classList.add('active');
        renderGeoMap();
    }
}

// --- Auto-Layout Market Map (structured grid) ---
let _autoLayoutCy = null;

async function renderAutoLayoutMap() {
    const container = document.getElementById('autoLayoutMap');
    if (!container) return;
    if (!window.cytoscape) {
        _waitForLib('graph library', () => window.cytoscape, () => renderAutoLayoutMap(), container);
        return;
    }

    const [compRes, taxRes] = await Promise.all([
        safeFetch(`/api/companies?project_id=${currentProjectId}`),
        safeFetch(`/api/taxonomy?project_id=${currentProjectId}`),
    ]);
    const companies = await compRes.json();
    const categories = await taxRes.json();
    const topLevel = categories.filter(c => !c.parent_id)
        .sort((a, b) => (b.company_count || 0) - (a.company_count || 0));
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';

    if (!topLevel.length) {
        container.innerHTML = '<div class="graph-loading"><p>No categories to display. Add categories first.</p></div>';
        return;
    }

    // Group companies by category
    const byCategory = {};
    companies.forEach(c => {
        if (!c.category_id) return;
        if (!byCategory[c.category_id]) byCategory[c.category_id] = [];
        byCategory[c.category_id].push(c);
    });

    // Grid layout: structured placement of categories and companies
    const COLS = Math.min(4, topLevel.length);
    const NODE_SIZE = 32;
    const NODE_GAP = 10;
    const CAT_PADDING_X = 30;
    const CAT_PADDING_TOP = 40;
    const CAT_PADDING_BOTTOM = 20;
    const GRID_GAP = 50;

    const elements = [];
    let maxRowHeight = [];  // track height per row for vertical positioning

    // First pass: calculate cell dimensions
    const cellDims = topLevel.map(cat => {
        const catCompanies = byCategory[cat.id] || [];
        const innerCols = Math.max(2, Math.min(6, Math.ceil(Math.sqrt(catCompanies.length))));
        const innerRows = Math.ceil(catCompanies.length / innerCols);
        const cellW = Math.max(180, innerCols * (NODE_SIZE + NODE_GAP) + CAT_PADDING_X * 2);
        const cellH = Math.max(100, innerRows * (NODE_SIZE + NODE_GAP) + CAT_PADDING_TOP + CAT_PADDING_BOTTOM);
        return { cat, companies: catCompanies, innerCols, cellW, cellH };
    });

    // Calculate column widths and row heights
    const colWidths = [];
    const rowHeights = [];
    for (let i = 0; i < cellDims.length; i++) {
        const col = i % COLS;
        const row = Math.floor(i / COLS);
        colWidths[col] = Math.max(colWidths[col] || 0, cellDims[i].cellW);
        rowHeights[row] = Math.max(rowHeights[row] || 0, cellDims[i].cellH);
    }

    // Second pass: place elements with calculated positions
    cellDims.forEach((cell, idx) => {
        const col = idx % COLS;
        const row = Math.floor(idx / COLS);

        // Calculate absolute X/Y for this cell's center
        let cx = 0;
        for (let c = 0; c < col; c++) cx += colWidths[c] + GRID_GAP;
        cx += colWidths[col] / 2;

        let cy = 0;
        for (let r = 0; r < row; r++) cy += rowHeights[r] + GRID_GAP;
        cy += rowHeights[row] / 2;

        const color = getCategoryColor(cell.cat.id) || '#999';
        const companyCount = cell.companies.length;

        // Category parent node
        elements.push({
            group: 'nodes',
            data: {
                id: 'cat-' + cell.cat.id,
                label: cell.cat.name + (companyCount ? ` (${companyCount})` : ''),
                type: 'category',
                color: color,
            },
            position: { x: cx, y: cy },
        });

        // Company child nodes arranged in mini-grid inside category
        const sorted = cell.companies.sort((a, b) => a.name.localeCompare(b.name));
        const startX = cx - (cell.innerCols * (NODE_SIZE + NODE_GAP) - NODE_GAP) / 2 + NODE_SIZE / 2;
        const startY = cy - (rowHeights[row] - CAT_PADDING_TOP - CAT_PADDING_BOTTOM) / 2 + NODE_SIZE / 2;

        sorted.forEach((c, i) => {
            const ic = i % cell.innerCols;
            const ir = Math.floor(i / cell.innerCols);
            elements.push({
                group: 'nodes',
                data: {
                    id: 'co-' + c.id,
                    label: c.name,
                    parent: 'cat-' + cell.cat.id,
                    type: 'company',
                    color: color,
                    companyId: c.id,
                },
                position: {
                    x: startX + ic * (NODE_SIZE + NODE_GAP),
                    y: startY + ir * (NODE_SIZE + NODE_GAP),
                },
            });
        });
    });

    if (_autoLayoutCy) _autoLayoutCy.destroy();

    _autoLayoutCy = cytoscape({
        container: container,
        elements: elements,
        style: [
            {
                selector: 'node[type="category"]',
                style: {
                    'label': 'data(label)',
                    'text-valign': 'top',
                    'text-halign': 'center',
                    'font-size': '13px',
                    'font-weight': '600',
                    'color': isDark ? '#e0ddd5' : '#3D4035',
                    'background-color': 'data(color)',
                    'background-opacity': 0.06,
                    'border-width': 2,
                    'border-color': 'data(color)',
                    'border-opacity': 0.35,
                    'padding': '25px',
                    'shape': 'round-rectangle',
                    'text-margin-y': -10,
                },
            },
            {
                selector: 'node[type="company"]',
                style: {
                    'label': 'data(label)',
                    'background-color': 'data(color)',
                    'background-opacity': 0.18,
                    'color': isDark ? '#bbb' : '#555',
                    'text-valign': 'center',
                    'text-halign': 'center',
                    'font-size': '9px',
                    'width': NODE_SIZE,
                    'height': NODE_SIZE,
                    'border-width': 1.5,
                    'border-color': 'data(color)',
                    'text-wrap': 'ellipsis',
                    'text-max-width': '55px',
                },
            },
            {
                selector: 'node[type="company"]:active',
                style: {
                    'overlay-color': '#bc6c5a',
                    'overlay-opacity': 0.15,
                },
            },
        ],
        layout: { name: 'preset' },
        wheelSensitivity: 0.3,
    });

    // Fit to view with some padding
    _autoLayoutCy.fit(undefined, 40);

    // Click company node to open detail
    _autoLayoutCy.on('tap', 'node[type="company"]', (e) => {
        const companyId = e.target.data('companyId');
        if (companyId) navigateTo('company', companyId, e.target.data('label'));
    });
}
