/**
 * E2E: Canvas tab — create, select, sidebar, add notes, rename, delete.
 */
import { test, expect } from './fixtures.js';

test.describe('Canvas Tab', () => {
    test.beforeEach(async ({ page, seededProject }) => {
        await page.goto('/');
        await page.evaluate((id) => selectProject(id), seededProject.id);
        await expect(page.locator('#mainApp')).toBeVisible();
        await page.evaluate(() => showTab('canvas'));
        await page.waitForTimeout(300);
    });

    test('canvas tab is visible and has toolbar', async ({ page }) => {
        await expect(page.locator('#tab-canvas')).toHaveClass(/active/);
        await expect(page.locator('#canvasSelect')).toBeVisible();
        await expect(page.locator('button:has-text("New Canvas")')).toBeVisible();
    });

    test('empty state shows when no canvas selected', async ({ page }) => {
        await expect(page.locator('#canvasEmptyState')).toBeVisible();
    });

    test('toolbar buttons are disabled when no canvas selected', async ({ page }) => {
        await expect(page.locator('#renameCanvasBtn')).toBeDisabled();
        await expect(page.locator('#deleteCanvasBtn')).toBeDisabled();
        await expect(page.locator('#canvasExportPngBtn')).toBeDisabled();
        await expect(page.locator('#canvasExportSvgBtn')).toBeDisabled();
    });

    test('creating a canvas adds it to the select and enables buttons', async ({ page }) => {
        await page.locator('button:has-text("New Canvas")').click();

        // Wait for custom prompt dialog to appear
        await expect(page.locator('#promptSheet')).toBeVisible();
        await page.locator('#promptSheetInput').fill('My Test Canvas');
        await page.locator('#promptSheetConfirm').click();
        await page.waitForTimeout(500);

        // Canvas should be in the select
        const select = page.locator('#canvasSelect');
        const options = select.locator('option');
        expect(await options.count()).toBeGreaterThan(1);

        // Buttons should now be enabled
        await expect(page.locator('#renameCanvasBtn')).toBeEnabled();
        await expect(page.locator('#deleteCanvasBtn')).toBeEnabled();

        // Empty state should be hidden
        await expect(page.locator('#canvasEmptyState')).toHaveClass(/hidden/);
    });

    test('canvas sidebar shows companies', async ({ page, seededProject }) => {
        // Add a company first
        await page.evaluate(async (pid) => {
            await safeFetch('/api/companies/add', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    project_id: pid,
                    name: 'Canvas Test Co',
                    url: 'https://canvastest.example.com',
                }),
            });
        }, seededProject.id);

        // Refresh sidebar
        await page.evaluate(() => loadCanvasSidebarCompanies());
        await page.waitForTimeout(500);

        const items = page.locator('.canvas-sidebar-item');
        expect(await items.count()).toBeGreaterThanOrEqual(1);
    });

    test('canvas sidebar search filters companies', async ({ page, seededProject }) => {
        // Add companies
        for (const name of ['Alpha Corp', 'Beta Inc', 'Gamma LLC']) {
            await page.evaluate(async ({ pid, name }) => {
                await safeFetch('/api/companies/add', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        project_id: pid,
                        name: name,
                        url: `https://${name.toLowerCase().replace(/ /g, '')}.example.com`,
                    }),
                });
            }, { pid: seededProject.id, name });
        }

        await page.evaluate(() => loadCanvasSidebarCompanies());
        await page.waitForTimeout(300);

        // Search for "Alpha"
        await page.fill('#canvasCompanySearch', 'Alpha');
        await page.waitForTimeout(300);

        const items = page.locator('.canvas-sidebar-item');
        expect(await items.count()).toBe(1);
        await expect(items.first()).toContainText('Alpha Corp');
    });

    test('deleting a canvas clears the view', async ({ page }) => {
        // Create a canvas via custom prompt dialog
        await page.locator('button:has-text("New Canvas")').click();
        await expect(page.locator('#promptSheet')).toBeVisible();
        await page.locator('#promptSheetInput').fill('Temp Canvas');
        await page.locator('#promptSheetConfirm').click();
        await page.waitForTimeout(500);

        // Delete it — triggers custom confirm dialog
        await page.locator('#deleteCanvasBtn').click();
        await expect(page.locator('#confirmSheet')).toBeVisible();
        await page.locator('#confirmSheetConfirm').click();
        await page.waitForTimeout(500);

        // Empty state should be back
        await expect(page.locator('#canvasEmptyState')).toBeVisible();
        await expect(page.locator('#renameCanvasBtn')).toBeDisabled();
    });

    test('canvas CRUD via API works', async ({ page, seededProject }) => {
        // Create via API
        const createRes = await page.evaluate(async (pid) => {
            const res = await safeFetch('/api/canvases', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ project_id: pid, title: 'API Canvas' }),
            });
            return res.json();
        }, seededProject.id);
        expect(createRes.id).toBeTruthy();

        // List via API
        const list = await page.evaluate(async (pid) => {
            const res = await safeFetch(`/api/canvases?project_id=${pid}`);
            return res.json();
        }, seededProject.id);
        expect(list.length).toBeGreaterThanOrEqual(1);
        expect(list.some(c => c.title === 'API Canvas')).toBe(true);

        // Delete via API
        await page.evaluate(async (id) => {
            await safeFetch(`/api/canvases/${id}`, { method: 'DELETE' });
        }, createRes.id);

        const listAfter = await page.evaluate(async (pid) => {
            const res = await safeFetch(`/api/canvases?project_id=${pid}`);
            return res.json();
        }, seededProject.id);
        expect(listAfter.some(c => c.title === 'API Canvas')).toBe(false);
    });
});
