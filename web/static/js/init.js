/**
 * App initialization.
 *
 * Core init (loadProjects, theme, heartbeat) runs IMMEDIATELY — no waiting
 * for CDN scripts.  CDN-dependent inits (notyf, dayjs, tippy, etc.) run
 * after window.onload when all external resources have finished loading,
 * then a second time is not needed because each init function has its own
 * "if (window.X)" guard and is idempotent.
 */

// Mermaid setup (CDN-dependent, runs after deferred scripts)
document.addEventListener('DOMContentLoaded', () => {
    if (window.mermaid) {
        mermaid.initialize({
            startOnLoad: false,
            theme: document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'default',
            securityLevel: 'strict',
        });
    }
});

// ---------- Core init: NO CDN dependencies, runs immediately ----------
// At this point all local <script> files above have executed and the DOM
// elements exist (this file is the last <script> in the body).
initTheme();
initOfflineDetection();
startHeartbeat();
loadProjects();
checkFirstRun();
checkForUpdates(true);   // silent, non-blocking

// ---------- CDN-dependent init: runs after all resources load ----------
window.addEventListener('load', () => {
    initNotyf();
    initDayjs();
    initHotkeys();
    initAutosize();
    initMediumZoom();
    initFlatpickr();
    initNProgress();
    initCommandPalette();           // ninja-keys (core.js)
    _initLegacyCommandPalette();    // Fallback lightweight palette (integrations.js)
    initLucideIcons();              // Lucide icons (core.js)
    initSortable();                 // SortableJS drag-to-reorder (core.js)
    initChoicesDropdowns();         // Choices.js enhanced selects (core.js)
    initTooltips();                 // Tippy.js tooltips for icon-only buttons (core.js)
});
