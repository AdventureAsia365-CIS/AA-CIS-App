import { test, expect } from '@playwright/test';
// AA-566 Phần B (My Catalog UX) + Phần C (Browse Pool simplify) + Phần D (Rewrite Config tab
// removed). Real WanderLux Travel tenant session (generate-key + real /tenant-login form, per
// reference_tenant_test_login_via_generate_key).
const SHOT_DIR = 'tests/e2e/results/aa566-bcd';
const WANDERLUX_API_KEY = process.env.WANDERLUX_API_KEY || '';

test.beforeEach(async ({ page }) => {
  test.skip(!WANDERLUX_API_KEY, 'WANDERLUX_API_KEY env var not set');
  await page.goto('/tenant-login');
  await page.fill('input[type="password"]', WANDERLUX_API_KEY);
  await page.click('button:has-text("Access Portal")');
  await page.waitForURL('**/portal**', { timeout: 10000 });
});

test('Phần B — My Catalog: row click-to-open, numbering, sort, country filter, Trip Details, SEO removed, DOCX export', async ({ page }) => {
  await page.goto('/portal/t4-pool'); // My Catalog = CatalogTab.tsx's own route
  await page.waitForTimeout(1200);
  await page.screenshot({ path: `${SHOT_DIR}/1-catalog-table.png`, fullPage: true });

  // Row numbering column present
  await expect(page.locator('th:has-text("#")')).toBeVisible();
  const firstRowNumber = await page.locator('tbody tr').first().locator('td').nth(1).innerText();
  expect(firstRowNumber.trim()).toBe('1');

  // Sortable Tour Name header exists and actually reorders rows (asc vs desc differ)
  const nameHeader = page.locator('th button:has-text("Tour Name")');
  await expect(nameHeader).toBeVisible();
  await nameHeader.click(); // asc
  await page.waitForTimeout(200);
  const namesAsc = await page.locator('tbody tr td:nth-child(3)').allTextContents();
  await nameHeader.click(); // desc
  await page.waitForTimeout(200);
  const namesDesc = await page.locator('tbody tr td:nth-child(3)').allTextContents();
  if (namesAsc.length > 1) expect(namesDesc.slice().reverse()).toEqual(namesAsc);

  // Country filter dropdown present
  const countrySelect = page.locator('select').first();
  await expect(countrySelect).toBeVisible();

  // Whole-row click opens the drawer (not just the Open button) — click the Country cell,
  // deliberately NOT the checkbox (col 1, has its own stopPropagation) or Actions (col 5).
  const firstRow = page.locator('tbody tr').first();
  await firstRow.locator('td').nth(3).click();
  await expect(page.locator('text=Your Version')).toBeVisible({ timeout: 8000 });
  await page.screenshot({ path: `${SHOT_DIR}/2-drawer-open-via-row-click.png`, fullPage: true });

  // SEO Title / SEO Meta / SEO Health Bar removed from the drawer
  await expect(page.locator('text=SEO Title')).toHaveCount(0);
  await expect(page.locator('text=SEO Meta')).toHaveCount(0);
  await expect(page.locator('text=SEO Health')).toHaveCount(0);

  // Export DOCX button present and triggers a real download
  const exportBtn = page.locator('button:has-text("Export DOCX")');
  await expect(exportBtn).toBeVisible();
  const [download] = await Promise.all([
    page.waitForEvent('download', { timeout: 15000 }),
    exportBtn.click(),
  ]);
  expect(download.suggestedFilename()).toMatch(/\.docx$/);
  await page.screenshot({ path: `${SHOT_DIR}/3-after-docx-export.png`, fullPage: true });
});

test('Phần C/D — Browse Pool: no Score badge, "Writing…" not "In progress", row numbering, no Rewrite Config tab, single-tour Rewrite via batch bar', async ({ page }) => {
  await page.goto('/portal/t1-rewrite'); // Browse Pool = PoolTab.tsx's own route
  await page.waitForTimeout(1200);
  await page.screenshot({ path: `${SHOT_DIR}/4-pool-list.png`, fullPage: true });

  // Score badge (★ N.N) gone from the list
  await expect(page.locator('text=/★\\s*\\d/')).toHaveCount(0);
  // "In progress" technical wording gone (replaced by "Writing…")
  await expect(page.locator('text=In progress')).toHaveCount(0);

  // Row numbering present in the pool list (a small index before the checkbox)
  const firstRowText = await page.locator('[data-testid="pool-tour-row"]').first().innerText();
  expect(firstRowText.trim().startsWith('1')).toBeTruthy();

  // Click a tour to open detail — wide layout unchanged, no Rewrite Config tab
  await page.locator('[data-testid="pool-tour-row"]').first().click();
  await expect(page.locator('text=📄 Tour Details')).toHaveCount(0); // tab bar itself removed
  await expect(page.locator('text=Rewrite Config')).toHaveCount(0);
  await page.screenshot({ path: `${SHOT_DIR}/5-pool-detail-no-tabs.png`, fullPage: true });

  // Single-tour selection alone (no checkbox) must still surface a Rewrite trigger — the batch
  // bar is now the ONLY rewrite entry point after Rewrite Config's removal.
  await expect(page.locator('button:has-text("Rewrite this tour")')).toBeVisible({ timeout: 5000 });
  await page.screenshot({ path: `${SHOT_DIR}/6-single-tour-rewrite-bar.png`, fullPage: true });
});
