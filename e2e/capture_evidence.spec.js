/**
 * E2E Evidence Capture: Take screenshots of all fixed features.
 * Saves to test-evidence/ folder for manual verification.
 */
import { test, expect } from '@playwright/test';

const EVIDENCE_DIR = 'test-evidence';

test.describe('Bug Fix Evidence Capture', () => {
    let projectId;
    let csrf;

    test.beforeAll(async ({ request }) => {
        // Get CSRF token
        const pageResp = await request.get('/');
        const html = await pageResp.text();
        const csrfMatch = html.match(/name="csrf-token" content="([^"]+)"/);
        csrf = csrfMatch ? csrfMatch[1] : '';

        // Create test project
        const resp = await request.post('/api/projects', {
            headers: { 'X-CSRF-Token': csrf, 'Content-Type': 'application/json' },
            data: {
                name: 'Evidence Capture ' + Date.now(),
                purpose: 'Bug fix evidence capture',
                seed_categories: 'Digital Health\nInsurTech\nHealthcare AI\nTelemedicine',
            },
        });
        const project = await resp.json();
        projectId = project.id;

        // Add test companies with diverse geographies
        const companies = [
            { name: 'Oscar Health', url: 'https://hioscar.com', hq_city: 'New York', hq_country: 'US', geography: 'United States', category_name: 'Digital Health' },
            { name: 'Babylon Health', url: 'https://babylonhealth.com', hq_city: 'London', hq_country: 'UK', geography: 'United Kingdom', category_name: 'Telemedicine' },
            { name: 'Lemonade', url: 'https://lemonade.com', hq_city: 'New York', hq_country: 'US', geography: 'US', category_name: 'InsurTech' },
            { name: 'Veeva Systems', url: 'https://veeva.com', hq_city: 'San Francisco', hq_country: 'US', geography: 'USA', category_name: 'Healthcare AI' },
            { name: 'Ada Health', url: 'https://ada.com', hq_city: 'Berlin', hq_country: 'Germany', geography: 'Germany', category_name: 'Healthcare AI' },
            { name: 'Doctolib', url: 'https://doctolib.fr', hq_city: 'Paris', hq_country: 'France', geography: 'France', category_name: 'Telemedicine' },
            { name: 'Niva Bupa', url: 'https://nivabupa.com', hq_city: 'Mumbai', hq_country: 'India', geography: 'India', category_name: 'InsurTech' },
            { name: 'Ping An Health', url: 'https://health.pingan.com', hq_city: 'Shanghai', hq_country: 'China', geography: 'China', category_name: 'Digital Health' },
            { name: 'Clover Health', url: 'https://cloverhealth.com', hq_city: 'San Francisco', hq_country: 'US', geography: 'United States', category_name: 'InsurTech' },
            { name: 'Bright Health', url: 'https://brighthealthgroup.com', hq_city: 'Minneapolis', hq_country: 'US', geography: 'US', category_name: 'Digital Health' },
            { name: 'Alan', url: 'https://alan.com', hq_city: 'Paris', hq_country: 'France', geography: 'France', category_name: 'InsurTech' },
            { name: 'Sword Health', url: 'https://swordhealth.com', hq_city: 'Porto', hq_country: 'Portugal', geography: 'Portugal', category_name: 'Digital Health' },
        ];

        for (const c of companies) {
            await request.post('/api/companies/add', {
                headers: { 'X-CSRF-Token': csrf, 'Content-Type': 'application/json' },
                data: { project_id: projectId, ...c },
            });
        }
    });

    test('Bug1: Graph View renders with nodes', async ({ page }) => {
        await page.goto('/');
        await page.waitForTimeout(1000);

        // Inject CSRF token into page so safeFetch works
        await page.evaluate((token) => {
            const meta = document.querySelector('meta[name="csrf-token"]');
            if (meta) meta.setAttribute('content', token);
        }, csrf);

        // Select project
        await page.evaluate((id) => { if (typeof selectProject === 'function') selectProject(id); }, projectId);
        await page.waitForTimeout(2000);

        // Navigate to taxonomy tab
        await page.evaluate(() => { if (typeof showTab === 'function') showTab('taxonomy'); });
        await page.waitForTimeout(1000);

        // Click Graph View button
        const graphBtn = page.locator('#graphViewBtn');
        if (await graphBtn.count() > 0) {
            await graphBtn.click();
            await page.waitForTimeout(4000); // Wait for graph to render
        }

        // Take screenshot
        await page.screenshot({ path: EVIDENCE_DIR + '/bug1_graph_view.png', fullPage: false });

        // Check if cytoscape canvas was rendered
        const graph = page.locator('#taxonomyGraph');
        const canvasCount = await graph.locator('canvas').count();
        console.log('Graph View canvas elements: ' + canvasCount);

        // Check for error messages
        const errorText = await graph.locator('.graph-loading').textContent().catch(() => '');
        console.log('Graph error text: "' + errorText + '"');
    });

    test('Bug2: Knowledge Graph renders', async ({ page }) => {
        await page.goto('/');
        await page.waitForTimeout(1000);

        await page.evaluate((token) => {
            const meta = document.querySelector('meta[name="csrf-token"]');
            if (meta) meta.setAttribute('content', token);
        }, csrf);

        await page.evaluate((id) => { if (typeof selectProject === 'function') selectProject(id); }, projectId);
        await page.waitForTimeout(2000);

        await page.evaluate(() => { if (typeof showTab === 'function') showTab('taxonomy'); });
        await page.waitForTimeout(1000);

        // Click Knowledge Graph button
        const kgBtn = page.locator('#kgViewBtn');
        if (await kgBtn.count() > 0) {
            await kgBtn.click();
            await page.waitForTimeout(4000);
        }

        await page.screenshot({ path: EVIDENCE_DIR + '/bug2_knowledge_graph.png', fullPage: false });

        const kg = page.locator('#knowledgeGraph');
        const canvasCount = await kg.locator('canvas').count();
        console.log('Knowledge Graph canvas elements: ' + canvasCount);
    });

    test('Bug3: Geographic Map renders markers', async ({ page }) => {
        await page.goto('/');
        await page.waitForTimeout(1000);

        await page.evaluate((token) => {
            const meta = document.querySelector('meta[name="csrf-token"]');
            if (meta) meta.setAttribute('content', token);
        }, csrf);

        await page.evaluate((id) => { if (typeof selectProject === 'function') selectProject(id); }, projectId);
        await page.waitForTimeout(2000);

        // Go to Map tab
        await page.evaluate(() => { if (typeof showTab === 'function') showTab('map'); });
        await page.waitForTimeout(1000);

        // Click Geographic map button
        const geoBtn = page.locator('#geoMapBtn');
        if (await geoBtn.count() > 0) {
            await geoBtn.click();
            await page.waitForTimeout(4000);
        }

        await page.screenshot({ path: EVIDENCE_DIR + '/bug3_geographic_map.png', fullPage: false });

        // Check for map tiles loaded (Leaflet creates tile images)
        const tiles = page.locator('.leaflet-tile');
        const tileCount = await tiles.count();
        console.log('Geo map tiles: ' + tileCount);

        // Check for map markers
        const markers = page.locator('.geo-marker-square');
        const markerCount = await markers.count();
        console.log('Geo map markers: ' + markerCount);
    });

    test('Bug4: Canvas creates and renders', async ({ page }) => {
        await page.goto('/');
        await page.waitForTimeout(1000);

        await page.evaluate((token) => {
            const meta = document.querySelector('meta[name="csrf-token"]');
            if (meta) meta.setAttribute('content', token);
        }, csrf);

        await page.evaluate((id) => { if (typeof selectProject === 'function') selectProject(id); }, projectId);
        await page.waitForTimeout(2000);

        // Go to Canvas tab
        await page.evaluate(() => { if (typeof showTab === 'function') showTab('canvas'); });
        await page.waitForTimeout(3000); // Wait for Excalidraw to load

        // Take screenshot of canvas tab
        await page.screenshot({ path: EVIDENCE_DIR + '/bug4_canvas_tab.png', fullPage: false });

        // Check if canvas functions are defined (Excalidraw-based)
        const canvasFuncsAvailable = await page.evaluate(() => {
            return {
                loadCanvasList: typeof loadCanvasList === 'function',
                createNewCanvas: typeof createNewCanvas === 'function',
                excalidrawRootExists: !!document.getElementById('excalidrawRoot'),
            };
        });
        console.log('Canvas functions available: ' + JSON.stringify(canvasFuncsAvailable));

        // Try creating a canvas via custom prompt dialog
        const newCanvasBtn = page.locator('button:has-text("New Canvas")');
        if (await newCanvasBtn.count() > 0) {
            await newCanvasBtn.click();
            await page.waitForTimeout(500);

            // Fill in the custom prompt dialog
            const promptSheet = page.locator('#promptSheet');
            if (await promptSheet.isVisible().catch(() => false)) {
                await page.locator('#promptSheetInput').fill('Evidence Test Canvas');
                await page.locator('#promptSheetConfirm').click();
            }
            await page.waitForTimeout(3000);

            await page.screenshot({ path: EVIDENCE_DIR + '/bug4_canvas_created.png', fullPage: false });

            // Check if Excalidraw container is rendered
            const excalidrawRoot = page.locator('#excalidrawRoot');
            const visible = await excalidrawRoot.isVisible().catch(() => false);
            console.log('Excalidraw root visible: ' + visible);
        }
    });

    test('Bug5: AI Discovery shows UI elements', async ({ page }) => {
        await page.goto('/');
        await page.waitForTimeout(1000);

        await page.evaluate((token) => {
            const meta = document.querySelector('meta[name="csrf-token"]');
            if (meta) meta.setAttribute('content', token);
        }, csrf);

        await page.evaluate((id) => { if (typeof selectProject === 'function') selectProject(id); }, projectId);
        await page.waitForTimeout(2000);

        // Go to Process tab where AI Discovery is
        await page.evaluate(() => { if (typeof showTab === 'function') showTab('process'); });
        await page.waitForTimeout(1000);

        await page.screenshot({ path: EVIDENCE_DIR + '/bug5_ai_discovery_tab.png', fullPage: false });

        // Check if discovery UI is visible
        const discoverySection = page.locator('#discoveryQuery, #discoveryBtn');
        const count = await discoverySection.count();
        console.log('AI Discovery UI elements: ' + count);
    });

    test('Overview: All tabs screenshot', async ({ page }) => {
        await page.goto('/');
        await page.waitForTimeout(1000);

        await page.evaluate((token) => {
            const meta = document.querySelector('meta[name="csrf-token"]');
            if (meta) meta.setAttribute('content', token);
        }, csrf);

        await page.evaluate((id) => { if (typeof selectProject === 'function') selectProject(id); }, projectId);
        await page.waitForTimeout(2000);

        // Screenshot each main tab
        const tabs = ['companies', 'taxonomy', 'map', 'matrix', 'canvas', 'process', 'settings'];
        for (const tab of tabs) {
            await page.evaluate((t) => { if (typeof showTab === 'function') showTab(t); }, tab);
            await page.waitForTimeout(1500);
            await page.screenshot({ path: EVIDENCE_DIR + '/overview_' + tab + '_tab.png', fullPage: false });
        }
    });
});
