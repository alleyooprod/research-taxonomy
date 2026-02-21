/**
 * Presentation Mode: full-screen slide presentation from map or reports.
 */

let _presSlides = [];
let _presCurrentSlide = 0;
let _presOverlay = null;

function startPresentation(source) {
    if (source === 'map') {
        _presSlides = buildMapSlides();
    } else if (source === 'report') {
        _presSlides = buildReportSlides();
    }
    if (!_presSlides.length) {
        showToast('No content for presentation');
        return;
    }
    _presCurrentSlide = 0;
    renderPresentationOverlay();
}

function buildMapSlides() {
    const slides = [];
    const title = document.getElementById('projectTitle')?.textContent || 'Market Map';

    // Title slide
    slides.push({
        html: `<div class="pres-title-slide">
            <h1>${esc(title)}</h1>
            <p>Market Map Overview</p>
        </div>`,
    });

    // One slide per map column
    const columns = document.querySelectorAll('.map-column');
    columns.forEach(col => {
        const catName = col.querySelector('.map-col-header')?.textContent?.trim() || 'Category';
        const companies = col.querySelectorAll('.map-company-tile');
        const compList = Array.from(companies).map(tile => {
            const name = tile.querySelector('.map-tile-name')?.textContent?.trim() || '';
            const desc = tile.querySelector('.map-tile-what')?.textContent?.trim() || '';
            return { name, desc };
        });

        slides.push({
            html: `<div class="pres-category-slide">
                <h2>${esc(catName)}</h2>
                <div class="pres-company-grid">
                    ${compList.map(c => `<div class="pres-company-card">
                        <strong>${esc(c.name)}</strong>
                        <p>${esc(c.desc)}</p>
                    </div>`).join('')}
                </div>
                <p class="pres-count">${compList.length} companies</p>
            </div>`,
        });
    });

    // Summary slide
    const statCompanies = document.getElementById('statCompanies')?.textContent || '';
    const statCategories = document.getElementById('statCategories')?.textContent || '';
    slides.push({
        html: `<div class="pres-title-slide">
            <h2>Summary</h2>
            <p>${esc(statCompanies)}</p>
            <p>${esc(statCategories)}</p>
        </div>`,
    });

    return slides;
}

function buildReportSlides() {
    const slides = [];
    const reportBody = document.querySelector('#researchResult .report-body, .report-body');
    if (!reportBody) return slides;

    const reportTitle = document.querySelector('#researchResult .report-header h3')?.textContent || 'Research Report';

    // Title slide
    slides.push({
        html: `<div class="pres-title-slide"><h1>${esc(reportTitle)}</h1></div>`,
    });

    // Split on h2 headings
    const sections = reportBody.innerHTML.split(/<h2[^>]*>/i);
    sections.forEach((section, i) => {
        if (i === 0 && !section.trim()) return;
        let content = section;
        // Re-add the h2 tag if this isn't the first section
        if (i > 0) {
            const endTag = content.indexOf('</h2>');
            if (endTag >= 0) {
                const heading = content.substring(0, endTag);
                content = `<h2>${heading}</h2>${content.substring(endTag + 5)}`;
            }
        }
        if (content.trim()) {
            slides.push({ html: `<div class="pres-content-slide">${content}</div>` });
        }
    });

    return slides;
}

function renderPresentationOverlay() {
    if (_presOverlay) _presOverlay.remove();

    _presOverlay = document.createElement('div');
    _presOverlay.className = 'presentation-overlay';
    _presOverlay.innerHTML = `
        <div class="pres-exit" data-action="exit-presentation" title="Exit (Esc)">&times;</div>
        <div class="pres-slide-container">
            <div id="presSlideContent" class="pres-slide"></div>
        </div>
        <div class="pres-controls">
            <button class="pres-nav" data-action="pres-navigate-prev"><span class="material-symbols-outlined">chevron_left</span></button>
            <span class="pres-counter" id="presCounter"></span>
            <button class="pres-nav" data-action="pres-navigate-next"><span class="material-symbols-outlined">chevron_right</span></button>
        </div>
        <div class="pres-progress-bar"><div id="presProgress" class="pres-progress-fill"></div></div>
    `;
    document.body.appendChild(_presOverlay);

    // Enter fullscreen
    try { _presOverlay.requestFullscreen?.() || _presOverlay.webkitRequestFullscreen?.(); } catch (e) {}

    renderCurrentSlide();

    // Keyboard navigation
    document.addEventListener('keydown', _presKeyHandler);
}

function _presKeyHandler(e) {
    if (e.key === 'Escape') exitPresentation();
    else if (e.key === 'ArrowRight' || e.key === ' ') { e.preventDefault(); presNavigate(1); }
    else if (e.key === 'ArrowLeft') presNavigate(-1);
    else if (e.key >= '1' && e.key <= '9') {
        const idx = parseInt(e.key) - 1;
        if (idx < _presSlides.length) { _presCurrentSlide = idx; renderCurrentSlide(); }
    }
}

function presNavigate(dir) {
    _presCurrentSlide = Math.max(0, Math.min(_presSlides.length - 1, _presCurrentSlide + dir));
    renderCurrentSlide();
}

function renderCurrentSlide() {
    const slide = _presSlides[_presCurrentSlide];
    if (!slide) return;
    document.getElementById('presSlideContent').innerHTML = slide.html;
    document.getElementById('presCounter').textContent = `${_presCurrentSlide + 1} / ${_presSlides.length}`;
    const pct = ((_presCurrentSlide + 1) / _presSlides.length) * 100;
    document.getElementById('presProgress').style.width = pct + '%';
}

function exitPresentation() {
    document.removeEventListener('keydown', _presKeyHandler);
    if (document.fullscreenElement) {
        try { document.exitFullscreen(); } catch (e) {}
    }
    if (_presOverlay) { _presOverlay.remove(); _presOverlay = null; }
    _presSlides = [];
    _presCurrentSlide = 0;
}

// --- Action Delegation ---
registerActions({
    'exit-presentation': () => exitPresentation(),
    'pres-navigate-prev': () => presNavigate(-1),
    'pres-navigate-next': () => presNavigate(1),
});
