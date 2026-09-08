import { test, expect } from '@playwright/test';
const SHOT_DIR = 'tests/e2e/results/aa566-a';
const WANDERLUX_API_KEY = process.env.WANDERLUX_API_KEY || '';

test('Phần A — sidebar My Catalog count matches the heading count', async ({ page }) => {
  test.skip(!WANDERLUX_API_KEY, 'WANDERLUX_API_KEY env var not set');
  await page.goto('/tenant-login');
  await page.fill('input[type="password"]', WANDERLUX_API_KEY);
  await page.click('button:has-text("Access Portal")');
  await page.waitForURL('**/portal**', { timeout: 10000 });

  await page.goto('/portal/t4-pool');
  await page.waitForSelector('table', { timeout: 15000 });
  await page.waitForTimeout(1500); // sidebar count fetch is a separate call, give it a beat
  await page.screenshot({ path: `${SHOT_DIR}/1-count-match.png`, fullPage: true });

  const sidebarText = await page.locator('a:has-text("My Catalog"), button:has-text("My Catalog")').first().innerText();
  const sidebarCount = parseInt(sidebarText.replace(/\D+/g, ''), 10);

  const headingText = await page.locator('text=/\\d+ tours?/').first().innerText();
  const headingCount = parseInt(headingText.match(/\d+/)?.[0] ?? '-1', 10);

  console.log('sidebar:', sidebarCount, 'heading:', headingCount);
  expect(sidebarCount).toBe(headingCount);
});
