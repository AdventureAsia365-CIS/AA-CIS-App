import { test, expect } from '@playwright/test';

// AA-345 round 7 — real, confirmed bug (live-verified by Nghiep): on
// /admin/curation with Sort = "Newest first", a tour just atomized did
// NOT appear at the top of the list, and clicking "Load more" repeatedly
// still didn't surface many other tours atomized the same day.
//
// Root cause (confirmed via a live DB query against the real dev DB, not
// theorized): GET /admin/atoms/summary's `by_tour` is a COMPLETE,
// unpaginated per-tour aggregate with the correct atomized_at for every
// tour — but the OLD orderedSections logic filtered that complete list
// down to only tours already present in `atomsByTour`, which was built
// from GET /admin/atoms's PAGINATED, offset/limit atom-row fetch,
// `ORDER BY ta.tour_id, ta.created_at` (tour_id/UUID order — unrelated to
// recency). Verified live: of 24 tours atomized on the day this was
// investigated, 23 were missing from the very first page under that
// ordering. So "Newest first" (and every other Sort option, which shared
// the same defect) was only ever sorting a near-arbitrary ~10-tour subset,
// not the real newest tours — and "Load more" surfaced tours in
// essentially random order with respect to recency, never guaranteed to
// eventually include every tour predictably.
//
// Fixed (frontend/app/admin/curation/page.tsx) by sorting the COMPLETE
// summary.by_tour list first, then paginating THAT sorted tour order —
// pagination now follows the sort instead of the sort being limited by
// whatever pagination happened to load first.
//
// This test proves BOTH symptoms are fixed in one flow: atomize a real,
// fresh tour (guaranteed newest), confirm it's first under "Newest first",
// then Load More to completion and confirm every tour that should be
// visible actually is (no under-count from the old bug).
//
// Uses a real admin login (e2e-test-admin) — see aa345-round5-curation-
// deeplink.spec.ts's header comment for why (AA-253: content-role 401s on
// every /admin/* data fetch, so this repo's only meaningful E2E path for
// real data is a JWT admin session).
async function loginAsAdmin(page) {
  await page.goto('/login');
  await page.fill('input[type="text"]', 'e2e-test-admin');
  await page.fill('input[type="password"]', 'aa345-repro-temp-2026');
  await page.click('button:has-text("Login")');
  await page.waitForURL(/\/admin\/dashboard/, { timeout: 8000 });
}

test.describe('AA-345 round 7 — Curation "Newest first" sort + Load more completeness', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test('a freshly atomized tour sorts first under "Newest first", and Load More eventually surfaces every tour with no gaps', async ({ page }) => {
    // Step 1 — atomize a real, currently-pending tour. This guarantees it
    // has the newest possible atomized_at of anything in the dataset at
    // the moment we check the sort, independent of whatever else has been
    // atomized by earlier test runs.
    await page.goto('/admin/atomize');
    await expect(page.getByRole('heading', { name: 'Atomize (N2 Decompose)' })).toBeVisible({ timeout: 10000 });

    const firstCheckbox = page.locator('tbody tr input[type="checkbox"]:not([disabled])').first();
    await firstCheckbox.waitFor({ state: 'visible', timeout: 10000 });
    const row = firstCheckbox.locator('xpath=ancestor::tr[1]');
    const tourName = (await row.locator('td').nth(1).innerText()).trim();
    await firstCheckbox.check();
    await page.getByRole('button', { name: 'Atomize', exact: true }).click();
    await page.waitForSelector('text=/succeeded/', { timeout: 60000 });

    // Step 2 — go to Curation fresh (hard nav, not the deep link — this
    // test is about the Sort dropdown + Load more, not the deep-link
    // filter round 5/6 already cover) and select "Newest first".
    await page.goto('/admin/curation');
    await expect(page.getByRole('heading', { name: 'Atom Curation' })).toBeVisible({ timeout: 10000 });
    const sortSelect = page.locator('select').nth(1); // Distinctiveness, then Sort
    await sortSelect.selectOption({ label: 'Newest first' });
    await page.waitForTimeout(1500);

    // Step 3 — the just-atomized tour must be the FIRST section, not
    // buried somewhere further down (the old bug's exact symptom).
    const firstSectionName = await page.locator('span[style*="font-weight: 600"]').first().innerText();
    expect(firstSectionName.trim()).toBe(tourName);

    // Step 4 — Load More to completion, then verify the count of rendered
    // tour sections matches the total the button itself reported (proves
    // no tour got silently dropped across pagination, the old bug's other
    // symptom). Poll for the button settling back to its non-"Loading…"
    // text between clicks so a slow response doesn't read as "done" early.
    let lastButtonText = '';
    let expectedTotal = 0;
    for (let clicks = 0; clicks < 60; clicks++) {
      const btn = page.locator('button', { hasText: /Load more \(/ });
      let visible = false;
      try {
        await btn.first().waitFor({ state: 'visible', timeout: 5000 });
        visible = true;
      } catch { visible = false; }
      if (!visible) break;
      lastButtonText = await btn.first().innerText();
      const match = lastButtonText.match(/\/\s*(\d+)\s*tours\)/);
      if (match) expectedTotal = parseInt(match[1], 10);
      await btn.first().click();
    }
    expect(expectedTotal).toBeGreaterThan(0);

    const renderedSectionCount = await page.locator('span', { hasText: /^\d+ atoms$/ }).count();
    expect(renderedSectionCount).toBe(expectedTotal);
  });
});
