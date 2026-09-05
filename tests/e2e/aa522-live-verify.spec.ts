// tests/e2e/aa522-live-verify.spec.ts — AA-522, permanent regression guard for the removed
// Luồng B (legacy 5-step atom-picker) — see docs/implementation-notes/AA-522.md.
//
// Runs against a real `next build && next start` (BASE_URL, default localhost:3001) fronting the
// REAL deployed backend (https://api-cis.lumiguides.it.com via NEXT_PUBLIC_API_URL's own
// default), same convention aa511-slate-fe-audit.spec.ts uses. A real WanderLux Travel tenant
// JWT is set as a cookie directly (Sidebar's "Write Content" link goes straight to
// /portal/t8-angle-gate with no query params — Luồng B's exact old entry point — so this only
// needs an authenticated tenant session, no specific Segment/Subject test data).
//
// NOT included here: a resume-restores-written-content check against a specific real
// request_id — that was this issue's own one-time live-verify (a real request this session
// wrote real content for via the live API), not a stable fixture to keep re-running against
// indefinitely. See docs/implementation-notes/AA-522.md for that evidence.
import { test, expect } from '@playwright/test';

const WANDERLUX_JWT = process.env.WANDERLUX_JWT || '';

test.describe('AA-522 — Luồng B removed', () => {
  test.beforeEach(async ({ context, baseURL }) => {
    test.skip(!WANDERLUX_JWT, 'WANDERLUX_JWT env var not set — see docs/implementation-notes/AA-522.md');
    const url = baseURL || 'http://localhost:3001';
    await context.addCookies([
      { name: 'cis_role', value: 'tenant', url },
      { name: 'cis_tenant_token', value: WANDERLUX_JWT, url },
    ]);
  });

  test('direct visit (Sidebar "Write Content", no query params) shows the Slate empty state, no raw atom dropdown', async ({ page }) => {
    await page.goto('/portal/t8-angle-gate');
    await expect(page.getByText('Nothing to write yet')).toBeVisible({ timeout: 10000 });
    await expect(page.getByRole('button', { name: 'Go to the Slate' })).toBeVisible();
    // The old raw atom <select> (Luồng B's own signature element) must not exist anywhere.
    await expect(page.locator('select')).toHaveCount(0);
  });
});
