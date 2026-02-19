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
    initCommandPalette();
    initOfflineDetection();
    startHeartbeat();
    loadProjects();
    checkFirstRun();
    // Silent update check (non-blocking)
    checkForUpdates(true);
};
