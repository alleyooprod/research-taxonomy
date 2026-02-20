/**
 * E2E: Bulk select and bulk actions in company table.
 */
import { test, expect } from './fixtures.js';

test.describe('Bulk Actions', () => {
    test.beforeEach(async ({ page, seededProject }) => {
        await page.goto('/');
        await page.evaluate((id) => selectProject(id), seededProject.id);
        await expect(page.locator('#mainApp')).toBeVisible();

        // Seed a few companies via API
        for (const name of ['Bulk Co A', 'Bulk Co B', 'Bulk Co C']) {
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

        await page.evaluate(() => showTab('companies'));
        await page.waitForTimeout(500);
    });

    test('select-all checkbox toggles all row checkboxes', async ({ page }) => {
        const masterCb = page.locator('#selectAllCheckbox');
        await expect(masterCb).toBeVisible();

        await masterCb.check();
        const checked = await page.locator('.bulk-checkbox:checked').count();
        expect(checked).toBeGreaterThanOrEqual(3);

        await masterCb.uncheck();
        const unchecked = await page.locator('.bulk-checkbox:checked').count();
        expect(unchecked).toBe(0);
    });

    test('individual checkbox selection shows bulk action bar', async ({ page }) => {
        const bar = page.locator('#bulkActionBar');
        await expect(bar).toHaveClass(/hidden/);

        const firstCb = page.locator('.bulk-checkbox').first();
        await firstCb.check();

        await expect(bar).not.toHaveClass(/hidden/);
        await expect(page.locator('#bulkCount')).toContainText('1 selected');
    });

    test('escape key clears bulk selection', async ({ page }) => {
        const firstCb = page.locator('.bulk-checkbox').first();
        await firstCb.check();

        const bar = page.locator('#bulkActionBar');
        await expect(bar).not.toHaveClass(/hidden/);

        await page.keyboard.press('Escape');
        await expect(bar).toHaveClass(/hidden/);
    });

    test('bulk action bar has all action buttons', async ({ page }) => {
        await page.locator('#selectAllCheckbox').check();

        const bar = page.locator('#bulkActionBar');
        await expect(bar).not.toHaveClass(/hidden/);

        await expect(bar.locator('button:has-text("Assign Category")')).toBeVisible();
        await expect(bar.locator('button:has-text("Add Tags")')).toBeVisible();
        await expect(bar.locator('button:has-text("Set Relationship")')).toBeVisible();
        await expect(bar.locator('button:has-text("Delete")')).toBeVisible();
    });

    test('bulk delete removes selected companies', async ({ page }) => {
        await page.locator('#selectAllCheckbox').check();

        // Count before
        const beforeCount = await page.locator('.bulk-checkbox').count();
        expect(beforeCount).toBeGreaterThanOrEqual(3);

        // Click delete button — triggers custom confirm dialog
        await page.locator('#bulkActionBar button:has-text("Delete")').click();
        await expect(page.locator('#confirmSheet')).toBeVisible();
        await page.locator('#confirmSheetConfirm').click();
        await page.waitForTimeout(500);

        // Table should be updated
        const afterCount = await page.locator('.bulk-checkbox').count();
        expect(afterCount).toBeLessThan(beforeCount);
    });
});
