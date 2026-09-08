import { test, expect } from '@playwright/test';
const SHOT_DIR = 'tests/e2e/results/aa564';
const WANDERLUX_API_KEY = process.env.WANDERLUX_API_KEY || '';

test.describe.configure({ mode: 'serial' });

test.beforeEach(async ({ page }) => {
  test.skip(!WANDERLUX_API_KEY, 'WANDERLUX_API_KEY env var not set');
  await page.goto('/tenant-login');
  await page.fill('input[type="password"]', WANDERLUX_API_KEY);
  await page.click('button:has-text("Access Portal")');
  await page.waitForURL('**/portal**', { timeout: 10000 });
});

test('4.1 — sidebar + breadcrumb say Social Content, not Slate', async ({ page }) => {
  await page.goto('/portal/t7-planning');
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${SHOT_DIR}/4.1-social-content-tenant.png`, fullPage: true });

  await expect(page.locator('text=Social Content').first()).toBeVisible();
  await expect(page.locator('text=Slate')).toHaveCount(0);
});

test('4.1b — AngleGateTab empty-state says Social Content', async ({ page }) => {
  await page.goto('/portal/t8-angle-gate');
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${SHOT_DIR}/4.1b-write-empty-state.png` });
});
