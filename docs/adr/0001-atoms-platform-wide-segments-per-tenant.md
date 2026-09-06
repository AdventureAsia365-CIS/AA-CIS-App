# Atoms are platform-wide; Segments/Score/Route stay per-tenant

Atomize used to be a tenant-triggered, per-tenant step (old T5). AA-526 (05/09/2026) moved atom
generation to A3 (`services/export/handler.py::process_export()`, right after a tour enters
`gold_aa_internal.published_tours`) — atoms are now generated exactly once, platform-wide
(`owner_scope='platform'`), the moment a tour becomes Master Content, not once per tenant that
later rewrites it.

Segment matching, Atom Ranking (Score), and Route/Hub detection were deliberately NOT moved to
that same platform-wide, computed-once model. Nghiệp's own confirmation during AA-526's build:
atoms are shared platform-wide, but a Segment/Score/Route is a PER-TENANT product, built the
first time that tenant picks or rewrites a given tour — not a single global Segment set every
tenant shares. `acp_contract.atom_segment.tenant_id` and `atom_ranking`'s tenant-scoped read are
real, enforced foreign keys, not an oversight to "fix" later.

## Status

accepted

## Considered Options

Building Segment/Score/Route platform-wide too (one shared set every tenant reads) was the
alternative — rejected because two different tenants rewriting the same tour into different
brand voices can produce genuinely different Segment groupings and rankings from the same atom
pool; a single shared Segment set would force one tenant's grouping onto another's differently-
voiced content.

## Consequences

A future spec or glossary that assumes "Segment/Score/Route are computed once for the whole
Master Content, admin-side" (as AA-539's own initial description did, one day after this was
decided) contradicts this ADR and the live schema — `CONTEXT.md`'s Open Questions section flags
this explicitly rather than silently picking a side. Any UI or pipeline work built on the
Admin/Tenant boundary must re-read this ADR, not assume the more intuitive-sounding "all computed
once" model.
