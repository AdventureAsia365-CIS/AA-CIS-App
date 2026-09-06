# Search Demand (DataForSEO cache) is shared across every tenant, not scoped per tenant

`acp_contract.search_demand` (migration 130) and its companion freshness marker
`acp_contract.segment_research_log` have no `tenant_id` column, unlike every other
AA-508/509/510/511/515 table. A search-volume/PAA row is keyed purely on `(keyword, market)`;
the research-freshness marker purely on `(canonical_place, market)`. Confirmed in code, not just
schema: `services/acp_contract/segment_research.py::_cached_volume()`/`_store_volume()` and
`_stale_markets()`/`run_segment_research()`'s own skip check never reference `tenant_id` at all.

This means: if tenant A's research loop already bought "kyoto temples" in the `japan` market, or
already researched the place "Kyoto" in that market within the 182-day freshness window, tenant
B's research for the exact same keyword/place skips the DataForSEO call — and, for an
already-fresh place, skips the entire LLM ReAct loop too, not just the DataForSEO leg of it.

## Status

accepted

## Considered Options

Scoping `search_demand`/`segment_research_log` by `tenant_id` (as every sibling table in this
build is) was the alternative — rejected because a keyword's search volume and a place's PAA
questions are facts about the outside world, not about any one tenant's content (migration 130's
own comment: "a keyword's search volume in a market is a fact about the outside world, not
tenant content"). Two tenants both researching "Kyoto" sharing one row and one DataForSEO
purchase avoids a real, repeated cost with no privacy or correctness downside — this matches
Ms. Thư's own reference design (`search_demand` keyed on `(keyword, market)` alone, no per-brand
scoping either, despite her schema otherwise being single-tenant by construction).

## Consequences

An admin-oversight UI (A4-class, cross-tenant) that wants to show "how much has this keyword/
place cost us" must query `search_demand`/`segment_research_log` directly — there is no
per-tenant attribution recorded anywhere (which tenant's research loop first bought a given row
is not tracked). A future feature wanting to know that would need a new column or a separate
attribution log; this ADR does not create one, since no such need exists yet (AA-540's own scope
is investigate-only).
