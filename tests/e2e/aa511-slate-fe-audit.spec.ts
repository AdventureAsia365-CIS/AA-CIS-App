// tests/e2e/aa511-slate-fe-audit.spec.ts — AA-511 FE audit fix (2026-09-02), live-verify for
// the important one (#2): a failed pick() must never refresh the Slate and risk showing a stale
// error message next to a row that actually succeeded server-side.
//
// Runs against a real `next build && next start` (BASE_URL, default localhost:3001) fronting the
// REAL deployed backend (https://api-cis.lumiguides.it.com via NEXT_PUBLIC_API_URL's own
// default) — a real tenant JWT (wanderlux-travel, minted with the real JWT_SECRET, same
// mechanism `api/routers/auth.py::_create_jwt()` uses) is set as a cookie directly, skipping the
// /tenant-login UI. A real Segment (test_aa511feaudit_seg_pick_race) was set up beforehand via
// the S3-mediated ECS exec pattern so the Slate has one real, pickable Facebook Subject.
//
// The #2 scenario: `page.route()` lets the pick POST actually reach the real backend (a REAL
// pick happens, REAL DB write) but then aborts the response before it reaches the browser — this
// is exactly the race the bug report described ("network timeout giả... subject có thể đã pick
// THẬT THÀNH CÔNG ở backend nhưng UI vẫn hiện lỗi cũ"), not a simulated rejection.
import { test, expect } from '@playwright/test';

const WANDERLUX_JWT = process.env.WANDERLUX_JWT || '';

test.describe('AA-511 Slate FE audit', () => {
  test.beforeEach(async ({ context, baseURL }) => {
    test.skip(!WANDERLUX_JWT, 'WANDERLUX_JWT env var not set — see docs/implementation-notes/AA-511.md');
    const url = baseURL || 'http://localhost:3001';
    await context.addCookies([
      { name: 'cis_role', value: 'tenant', url },
      { name: 'cis_tenant_token', value: WANDERLUX_JWT, url },
    ]);
  });

  test('#1/#5/#6 — tab strip shows a group divider+icon and scrolls horizontally, panel shows a skeleton while loading', async ({ page }) => {
    await page.goto('/portal/t7-planning');
    // CardHead's title renders as a plain <span>, no ARIA heading role -- locate the tab strip
    // itself instead, which is unique to SlateTab.
    await expect(page.locator('.aa511-slate-tabstrip')).toBeVisible({ timeout: 10000 });

    // #6 — the tab strip is a horizontally-scrolling container, not a flex-wrap block (no second
    // row of tabs even in a narrow viewport).
    await page.setViewportSize({ width: 375, height: 800 });
    const tabStrip = page.locator('.aa511-slate-tabstrip');
    await expect(tabStrip).toBeVisible();
    const overflowX = await tabStrip.evaluate(el => getComputedStyle(el).overflowX);
    expect(overflowX).toBe('auto');
    const tabTop = async (name: string) => (await page.getByRole('button', { name }).first().boundingBox())?.y;
    const blogY = await tabTop('Blog');
    const adsY = await tabTop('Ads');
    expect(blogY).toBeDefined();
    expect(adsY).toBeDefined();
    expect(Math.abs((blogY as number) - (adsY as number))).toBeLessThan(2); // same row, not wrapped

    // #5 — a divider sits between the last weekly tab (TikTok) and the first on-demand tab (Email).
    const dividerCount = await page.locator('.aa511-slate-tabstrip [aria-hidden="true"]').count();
    expect(dividerCount).toBeGreaterThanOrEqual(1);
  });

  test('#3 — a Channel with only decided history shows the "no new eligible" message, not the generic empty state', async ({ page }) => {
    // The setup Segment (needs_said=150) clears LinkedIn's bar too (identical thresholds to
    // Facebook) -- pick it for real via page.request (shares this page's own auth cookies, no
    // UI/interception involved) so LinkedIn ends this test with decided history + 0 currently-
    // eligible Subjects, independent of test #2's own separate Facebook pick.
    const slateRes = await page.request.get('/api/tenant/v1/slate');
    expect(slateRes.ok()).toBeTruthy();
    const slate = await slateRes.json();
    const linkedinSubject = slate.channels.linkedin.subjects.find(
      (s: { segment_id: string; state: string; subject_id: string }) =>
        s.segment_id === 'test_aa511feaudit_seg_pick_race' && s.state === 'proposed'
    );
    test.skip(!linkedinSubject, 'setup Segment not found under LinkedIn — run aa511_fe_e2e_setup.py first');
    const pickRes = await page.request.post(`/api/tenant/v1/subjects/${linkedinSubject.subject_id}/pick`);
    expect(pickRes.ok()).toBeTruthy();

    await page.goto('/portal/t7-planning');

    // Blog has never had any Subject in this scenario (Segment-grain data only, no Route built)
    // -- the ORIGINAL "never had any" message, unchanged, still correct.
    await page.getByRole('button', { name: 'Blog' }).click();
    await expect(page.getByText('Nothing here yet')).toBeVisible({ timeout: 10000 });

    // LinkedIn now has decided (picked) history but 0 currently-eligible Subjects -- the NEW,
    // distinct message this fix adds (was previously indistinguishable from the Blog case above).
    await page.getByRole('button', { name: 'LinkedIn' }).click();
    await expect(page.getByText('Không còn Subject mới đủ điều kiện lúc này')).toBeVisible({ timeout: 10000 });
    await expect(page.getByText('Already decided')).toBeVisible();
    await expect(page.getByText('picked', { exact: true })).toBeVisible();
  });

  test('#2 (the important one) — a lost response after a real successful pick never shows a stale error next to a picked row', async ({ page }) => {
    // TikTok, not Facebook — Facebook/LinkedIn's own copies of this shared Segment are used by
    // this file's other 2 tests and end up genuinely 'picked' by design; TikTok's stays
    // 'proposed' so this test starts from a clean, real "Chọn viết"-able row every run.
    await page.goto('/portal/t7-planning');
    await page.getByRole('button', { name: 'TikTok' }).click();

    // Only one Subject exists under this tab in the test scenario -- page-wide locators are
    // unambiguous here, and avoid a brittle `.last()`/`.filter()` guess at which nested <div>
    // around "Yanaka Ginza" is the actual row (title, bar-reason, and error box are 3 separate
    // sibling <div>s, not one containing element the text-filter reliably lands on).
    await expect(page.getByText('Yanaka Ginza', { exact: false })).toBeVisible({ timeout: 10000 });

    // Let the POST really reach the real backend (a REAL pick happens) but abort the response
    // before it reaches the browser -- simulates the exact "backend succeeded, client gave up"
    // race, not a fake rejected promise.
    let backendReallyRanOk = false;
    await page.route('**/api/tenant/v1/subjects/*/pick', async (route) => {
      const response = await route.fetch();
      backendReallyRanOk = response.ok();
      await route.abort('timedout');
    });

    await page.getByRole('button', { name: /Chọn viết/ }).click();

    // The error must show...
    await expect(page.getByText(/Couldn't pick this Subject/)).toBeVisible({ timeout: 10000 });
    // ...and the row must NOT have silently flipped to "picked" underneath the stale error --
    // the exact inconsistent state the bug report described.
    await expect(page.getByText('picked', { exact: true })).not.toBeVisible();
    // The pick button must still be there too (state genuinely untouched, not half-updated).
    await expect(page.getByRole('button', { name: /Chọn viết/ })).toBeVisible();

    expect(backendReallyRanOk).toBe(true); // confirms this was a REAL success, not a real failure

    // Now the tenant explicitly asks to refresh (the new manual "Refresh" link) -- THIS is where
    // the real 'picked' state should surface, never automatically.
    await page.unroute('**/api/tenant/v1/subjects/*/pick');
    await page.getByRole('button', { name: 'Refresh' }).click();
    await expect(page.getByText('picked', { exact: true })).toBeVisible({ timeout: 10000 });
  });
});
