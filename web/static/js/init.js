/**
 * App initialization: window.onload and mermaid setup.
 */

// Mermaid init (before DOMContentLoaded for early setup)
document.addEventListener('DOMContentLoaded', () => {
    if (window.mermaid) {
        mermaid.initialize({
            startOnLoad: false,
            theme: document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'default',
            securityLevel: 'strict',
        });
    }
});

// Main app init
window.onload = () => {
    initTheme();
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
    initOfflineDetection();
    startHeartbeat();
    loadProjects();
    checkFirstRun();
    // Silent update check (non-blocking)
    checkForUpdates(true);
};
