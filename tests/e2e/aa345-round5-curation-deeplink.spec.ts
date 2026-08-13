import { test, expect } from '@playwright/test';

// AA-345 round 5 — real, confirmed bug (screenshot + Network tab from
// Nghiep): after atomizing exactly 1 tour on /admin/atomize and clicking
// "View in Atom Curation", the browser URL correctly carried
// ?tour_ids=<the real tour_id>, but Curation rendered the FULL unfiltered
// atom list — the just-atomized tour didn't appear, no "Filtering to"
// banner, as if the query param had never been read.
//
// Root cause (confirmed via this exact repro, not theorized): Curation's
// highlightTourIds used to be a lazy useState() initializer reading
// window.location.search once at mount. On a client-side router.push()
// navigation FROM /admin/atomize (not a hard reload), this page can mount
// and run that initializer before Next.js's router has actually applied
// the new URL — it silently reads the OLD (pre-navigation, tour_ids-less)
// location and initializes highlightTourIds to []. A hard page.goto() to
// the exact same URL works correctly every time (proven separately during
// investigation) — only the soft-navigation path was broken, which is
// exactly the real user flow (click a button, not paste a URL). Fixed by
// switching to Next's useSearchParams() (see frontend/app/admin/curation/
// page.tsx), which is router-synced by construction and can't race the
// navigation it's reading params from.
//
// Uses a real admin login (e2e-test-admin), not loginAsContent — this repo's
// content-role login is known-401 on every /admin/* data fetch (AA-253,
// frontend/lib/auth-server.ts's requireAdmin() only accepts the
// cis_admin_token cookie a JWT admin login sets), which the existing
// aa300-curation.spec.ts already documents and silently tolerates. That
// gap makes it impossible to prove real filtered data renders via
// content-role — this suite needs the real thing to actually catch this
// class of bug, which is exactly what let round 4 (PR #135, curl-only
// verification) miss it. e2e-test-admin's password was reset for this
// investigation (round 5, with Nghiep's explicit authorization) to the
// value below — it's a pre-existing dev-only DB fixture, not a real
// person's account.
async function loginAsAdmin(page) {
  await page.goto('/login');
  await page.fill('input[type="text"]', 'e2e-test-admin');
  await page.fill('input[type="password"]', 'aa345-repro-temp-2026');
  await page.click('button:has-text("Login")');
  await page.waitForURL(/\/admin\/dashboard/, { timeout: 8000 });
}

test.describe('AA-345 round 5 — Atomize -> Curation single-tour deep link', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  // Consumes a real "not yet atomized" tour from the dev DB's 763-tour floor
  // on every run (idempotent decompose means re-running on the SAME tour
  // later is a safe no-op, but it also becomes non-selectable — has_atoms
  // flips true — so this test always picks whichever tour is currently
  // first in the list rather than a hardcoded name). Matches this repo's
  // existing E2E convention of testing against real live data, no mocks.
  test('single-tour atomize -> "View in Atom Curation" shows the real atomized tour, not the full unfiltered list', async ({ page }) => {
    await page.goto('/admin/atomize');
    await expect(page.getByRole('heading', { name: 'Atomize (N2 Decompose)' })).toBeVisible({ timeout: 10000 });

    const firstCheckbox = page.locator('tbody tr input[type="checkbox"]:not([disabled])').first();
    await firstCheckbox.waitFor({ state: 'visible', timeout: 10000 });
    const row = firstCheckbox.locator('xpath=ancestor::tr[1]');
    const tourName = (await row.locator('td').nth(1).innerText()).trim();
    await firstCheckbox.check();

    await page.getByRole('button', { name: 'Atomize', exact: true }).click();
    await page.waitForSelector('text=/succeeded/', { timeout: 60000 });

    // The literal user flow: click through, not a pasted/reloaded URL —
    // this is the exact step that raced and lost before the fix.
    await page.click('button:has-text("View in Atom Curation")');
    await page.waitForURL(/\/admin\/curation\?tour_ids=/, { timeout: 10000 });

    await expect(page.getByRole('heading', { name: 'Atom Curation' })).toBeVisible({ timeout: 10000 });
    await expect(page.getByText(/Filtering to 1 tour just atomized/)).toBeVisible({ timeout: 10000 });
    await expect(page.getByText(tourName, { exact: false }).first()).toBeVisible({ timeout: 10000 });

    // AA-345 round 6 — a real, confirmed regression from this fix: clicking
    // "Clear filter" did nothing at all in a real production build (next
    // build && next start), even though it worked fine under `next dev`.
    // Root cause: router.replace() to a same-pathname, search-params-only
    // URL (?tour_ids=X -> no query) is a known flaky class of navigation in
    // Next's App Router — confirmed via a console.log placed directly in
    // the onClick that it fired and router.replace() was called, but
    // neither the URL nor useSearchParams()'s output changed afterward.
    // Only reproduced against a production build; `next dev` masked it
    // completely, same as this repo's own Playwright suite would if run
    // against a dev server instead of BASE_URL pointed at a `next start`
    // instance — this test needs the real thing to mean anything for this
    // specific case. Fixed by driving the filter off a plain React state
    // flag (guaranteed to trigger a re-render, doesn't depend on the
    // router) and clearing the URL via a raw history.replaceState() call
    // instead of router.replace().
    await page.click('text=Clear filter');
    // URL/banner update synchronously with the click (history.replaceState
    // + the `cleared` flag) — a short wait covers those. The tour SECTIONS
    // re-rendering below waits separately (via expect.poll) because round
    // 7 made pagination tour-based (see curation/page.tsx's `sortedTours`/
    // `loadAtoms` comments): "Clear filter" now re-fetches a whole batch of
    // tours' atoms from scratch, which takes noticeably longer than the
    // single fixed-size atom-row page it used to re-fetch pre-round-7 — a
    // fixed short timeout here was flaky for exactly that reason.
    await page.waitForTimeout(300);
    expect(new URL(page.url()).searchParams.has('tour_ids')).toBe(false);
    expect(new URL(page.url()).searchParams.has('tour_id')).toBe(false);
    await expect(page.getByText(/Filtering to.*just atomized/)).not.toBeVisible();
    // The just-cleared tour's own section should still be present (it's
    // real data, not deleted) — but no longer the ONLY section, proving
    // the list actually went back to unfiltered rather than just hiding
    // the banner text. Each tour section header renders a "<N> atoms"
    // Badge (adminUi.tsx) — counting those counts sections.
    await expect.poll(
      async () => page.getByText(/^\d+ atoms$/).count(),
      { timeout: 8000 },
    ).toBeGreaterThan(1);
  });
});
