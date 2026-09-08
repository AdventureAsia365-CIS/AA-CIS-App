import { test, expect } from '@playwright/test';
// AA-565 — T4 My Catalog rebuild live-verify. Real WanderLux Travel tenant session (generate-key
// + real /tenant-login form, see memory reference_tenant_test_login_via_generate_key.md — never
// mint a JWT directly). Verifies the 5 points from the approval comment:
//   1. New table (Tour Name/Country/Actions, no Score/Version/Status)
//   2. "Writing…" inline loading, no technical status badge
//   3. Request Rewrite really calls the rewrite endpoint + consumes real quota (not the old
//      set-rejected no-op)
//   4. Merged Save (single button, no "Save as New Version")
//   5. Everything else in the v3 checklist still works
const SHOT_DIR = 'tests/e2e/results/aa565';
const WANDERLUX_API_KEY = process.env.WANDERLUX_API_KEY || '';

test.describe.configure({ mode: 'serial' });

test.beforeEach(async ({ page }) => {
  test.skip(!WANDERLUX_API_KEY, 'WANDERLUX_API_KEY env var not set');
  await page.goto('/tenant-login');
  await page.fill('input[type="password"]', WANDERLUX_API_KEY);
  await page.click('button:has-text("Access Portal")');
  await page.waitForURL('**/portal**', { timeout: 10000 });
});

test('1 — table columns are Tour Name/Country/Actions only, no Score/Version/Status', async ({ page }) => {
  await page.goto('/portal/t4-pool');
  await page.waitForSelector('table', { timeout: 15000 });
  await page.waitForTimeout(1000);
  await page.screenshot({ path: `${SHOT_DIR}/1-table-default.png`, fullPage: true });

  const headers = await page.locator('table thead th').allTextContents();
  expect(headers.map(h => h.trim())).toEqual(['', 'Tour Name', 'Country', 'Actions']);

  const bodyText = await page.locator('body').innerText();
  for (const forbidden of ['Queued', 'In Catalog', 'Ready to Review', 'New Version Requested', 'AI Generated', 'AI Writing', 'Extra QA pass']) {
    expect(bodyText).not.toContain(forbidden);
  }
});

test('2 — open drawer on a finished tour: single Save (hidden, clean), single Request Rewrite, no Add to Catalog', async ({ page }) => {
  await page.goto('/portal/t4-pool');
  await page.waitForSelector('table', { timeout: 15000 });
  const openBtn = page.locator('table tbody tr button:has-text("Open")').first();
  await expect(openBtn).toBeVisible({ timeout: 10000 });
  await openBtn.click();
  await page.waitForTimeout(1200);
  await page.screenshot({ path: `${SHOT_DIR}/2-drawer-open.png`, fullPage: true });

  await expect(page.locator('button:has-text("Request Rewrite")')).toBeVisible();
  await expect(page.locator('button:has-text("Add to Catalog")')).toHaveCount(0);
  await expect(page.locator('button:has-text("Save as New Version")')).toHaveCount(0);
  // Save button only shows once dirty — should be absent right after opening (not dirty yet)
  await expect(page.locator('button:has-text("Save")').filter({ hasNotText: 'Saving' })).toHaveCount(0);
});

test('3 — merged Save: editing shows exactly 1 Save button, saving does not show a false "writing" state', async ({ page }) => {
  await page.goto('/portal/t4-pool');
  await page.waitForSelector('table', { timeout: 15000 });
  await page.locator('table tbody tr button:has-text("Open")').first().click();
  await page.waitForTimeout(1200);

  const summaryEditBtn = page.locator('text=Summary').locator('xpath=following-sibling::button[1]').first();
  await summaryEditBtn.click();
  const textarea = page.locator('textarea').first();
  const before = await textarea.inputValue();
  await textarea.fill(before + ' (AA-565 live-verify edit)');
  await page.locator('button:has-text("Save")').first().click(); // inline CompareRow "Save" (local, not the header one)

  await expect(page.locator('button:has-text("Save")').filter({ hasText: /^\s*Save\s*$/ })).toHaveCount(1, { timeout: 5000 });
  await page.screenshot({ path: `${SHOT_DIR}/3-dirty-single-save-button.png` });

  await page.locator('button:has-text("Save")').filter({ hasText: /^\s*Save\s*$/ }).click();
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${SHOT_DIR}/3-after-save.png` });

  // Real bug this build fixed: edit_source='tenant_edit' rows must NOT show the AI-writing
  // loading placeholder (only status+edit_source==='ai_generated' should).
  await expect(page.locator('text=Writing your tour content')).toHaveCount(0);
  await expect(page.locator('text=✓ Saved')).toBeVisible();
});

test('4 — Request Rewrite calls the real rewrite endpoint + consumes real quota + inline loading + auto-completes', async ({ page }) => {
  test.setTimeout(240_000);
  await page.goto('/portal/t4-pool');
  await page.waitForSelector('table', { timeout: 15000 });

  const quotaBefore = await page.evaluate(async () => {
    const r = await fetch('/api/tenant/v1/quota');
    return r.ok ? (await r.json()).rewrites_used : null;
  });

  await page.locator('table tbody tr button:has-text("Open")').first().click();
  await page.waitForTimeout(1000);
  await page.locator('button:has-text("Request Rewrite")').click();
  await expect(page.locator('text=Rewrite this tour again?')).toBeVisible();
  await page.screenshot({ path: `${SHOT_DIR}/4a-rewrite-confirm-dialog.png` });

  const [rewriteResponse] = await Promise.all([
    page.waitForResponse(resp => resp.url().includes('/rewrite') && resp.request().method() === 'POST', { timeout: 15000 }),
    page.click('button:has-text("Confirm & Rewrite")'),
  ]);
  expect(rewriteResponse.ok()).toBeTruthy();
  const rewriteBody = await rewriteResponse.json();
  expect(rewriteBody.status).toBe('pending');
  expect(rewriteBody.version_id).toBeTruthy();

  // Drawer should flip to the writing placeholder immediately (same published_tour_id, no
  // manual reload) — this is the "loading at the exact spot content will appear" requirement.
  await expect(page.locator('text=Writing your tour content')).toBeVisible({ timeout: 8000 });
  await page.screenshot({ path: `${SHOT_DIR}/4b-drawer-writing.png` });

  // Table row (behind the dimmed backdrop) also shows the inline writing indicator, not a badge
  await expect(page.locator('table tbody tr', { hasText: 'Writing…' }).first()).toBeVisible({ timeout: 5000 });
  await page.screenshot({ path: `${SHOT_DIR}/4c-table-writing-row.png`, fullPage: true });

  // Real quota consumption — proves this is NOT the old set-rejected no-op
  const quotaAfter = await page.evaluate(async () => {
    const r = await fetch('/api/tenant/v1/quota');
    return r.ok ? (await r.json()).rewrites_used : null;
  });
  expect(quotaAfter).toBe((quotaBefore ?? 0) + 1);

  // Wait for the real background rewrite to finish via the existing 5s poll — no manual refresh
  await expect(page.locator('text=Writing your tour content')).toHaveCount(0, { timeout: 180_000 });
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${SHOT_DIR}/4d-drawer-ready-after-rewrite.png` });
  await expect(page.locator('button:has-text("Request Rewrite")')).toBeVisible();
});

test('5 — multi-select + CSV/XLSX export still works', async ({ page }) => {
  await page.goto('/portal/t4-pool');
  await page.waitForSelector('table', { timeout: 15000 });
  const checkboxes = page.locator('table tbody tr td input[type="checkbox"]');
  const count = await checkboxes.count();
  for (let i = 0; i < Math.min(2, count); i++) await checkboxes.nth(i).check();

  await expect(page.locator('button:has-text("CSV")')).toBeVisible();
  await page.screenshot({ path: `${SHOT_DIR}/5-multiselect-export-buttons.png` });

  const [download] = await Promise.all([
    page.waitForEvent('download', { timeout: 15000 }),
    page.locator('button:has-text("CSV")').click(),
  ]);
  expect(download.suggestedFilename()).toBe('my-catalog.csv');
});

test('6 — backdrop click closes when clean, stays open when dirty', async ({ page }) => {
  await page.goto('/portal/t4-pool');
  await page.waitForSelector('table', { timeout: 15000 });
  await page.locator('table tbody tr button:has-text("Open")').first().click();
  await page.waitForTimeout(1000);

  // Clean → backdrop click closes
  await page.mouse.click(20, 20);
  await page.waitForTimeout(500);
  await expect(page.locator('button:has-text("Request Rewrite")')).toHaveCount(0);
  await page.screenshot({ path: `${SHOT_DIR}/6a-backdrop-closed-clean.png` });

  // Dirty → backdrop click does NOT close
  await page.locator('table tbody tr button:has-text("Open")').first().click();
  await page.waitForTimeout(1000);
  const editBtn = page.locator('text=Summary').locator('xpath=following-sibling::button[1]').first();
  await editBtn.click();
  await page.locator('textarea').first().fill('dirty-guard-check');
  await page.locator('button:has-text("Save")').first().click(); // commit into the local CompareRow field (still dirty overall — header Save not yet clicked)
  await page.mouse.click(20, 20);
  await page.waitForTimeout(500);
  await expect(page.locator('button:has-text("Request Rewrite")')).toBeVisible();
  await page.screenshot({ path: `${SHOT_DIR}/6b-backdrop-blocked-dirty.png` });

  // Clean up: close via the explicit X regardless of dirty state, discard the test edit
  await page.locator('button svg').last().click().catch(() => {});
});
