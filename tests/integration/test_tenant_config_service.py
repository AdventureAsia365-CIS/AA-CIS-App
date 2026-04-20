"""
Integration tests — Gap 2: Tenant Config Service
PRD v4: Services load tenant-specific config before processing.
"""

import json
import pytest
import asyncpg
import fakeredis
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../'))

TENANT_A = "aa_internal"
TENANT_B = "wl_tenant_b2b_test"

DB_DSN = "postgresql://cistest:cistest@127.0.0.1:5432/cis_integration_test"


class SyncCacheAdapter:
    """Wrap fakeredis (sync) to match async cache interface."""
    def __init__(self, client):
        self.client = client

    async def get(self, key):
        return self.client.get(key)

    async def set(self, key, value, ex=None):
        self.client.set(key, value, ex=ex)

    async def delete(self, key):
        self.client.delete(key)


# ── Fixtures ──────────────────────────────────────────────────

@pytest.fixture
async def aconn():
    """Async asyncpg connection — one per test."""
    conn = await asyncpg.connect(DB_DSN)
    yield conn
    await conn.close()


@pytest.fixture
def fake_cache():
    server = fakeredis.FakeServer(version=(7, 0, 0))
    client = fakeredis.FakeRedis(server=server, decode_responses=True)
    yield client
    client.flushall()


@pytest.fixture
async def svc(aconn, fake_cache):
    from shared.services.tenant_config_service import TenantConfigService
    return TenantConfigService(aconn, SyncCacheAdapter(fake_cache))


@pytest.fixture
async def svc_no_cache(aconn):
    from shared.services.tenant_config_service import TenantConfigService
    return TenantConfigService(aconn, cache=None)


# ── Brand Rules ───────────────────────────────────────────────

class TestBrandRulesLoading:

    async def test_load_brand_rules_aa_internal(self, svc):
        rules = await svc.get_brand_rules(TENANT_A)
        assert rules.tenant_id == TENANT_A
        assert len(rules.system_prompt) > 0
        assert "Adventure Asia" in rules.system_prompt
        assert isinstance(rules.forbidden_words, list)
        assert len(rules.forbidden_words) > 0

    async def test_load_brand_rules_b2b_tenant(self, svc):
        rules = await svc.get_brand_rules(TENANT_B)
        assert rules.tenant_id == TENANT_B
        assert "WorldLux" in rules.system_prompt
        assert "cheap" in rules.forbidden_words

    async def test_brand_rules_differ_per_tenant(self, svc):
        rules_a = await svc.get_brand_rules(TENANT_A)
        rules_b = await svc.get_brand_rules(TENANT_B)
        assert rules_a.system_prompt != rules_b.system_prompt
        assert rules_a.forbidden_words != rules_b.forbidden_words

    async def test_unknown_tenant_returns_default(self, svc):
        rules = await svc.get_brand_rules("nonexistent_tenant")
        assert rules.tenant_id == "nonexistent_tenant"
        assert rules.system_prompt == ""
        assert rules.forbidden_words == []

    async def test_brand_rules_cache_hit(self, svc, fake_cache):
        rules1 = await svc.get_brand_rules(TENANT_A)
        cached = fake_cache.get(f"config:brand:{TENANT_A}")
        assert cached is not None

        rules2 = await svc.get_brand_rules(TENANT_A)
        assert rules1.system_prompt == rules2.system_prompt

    async def test_update_brand_rules_invalidates_cache(self, svc, fake_cache):
        await svc.get_brand_rules(TENANT_A)
        assert fake_cache.get(f"config:brand:{TENANT_A}") is not None

        await svc.update_brand_rules(TENANT_A, {"style_guide": "Updated v2"})
        assert fake_cache.get(f"config:brand:{TENANT_A}") is None

    async def test_brand_rules_no_cache_still_works(self, svc_no_cache):
        rules = await svc_no_cache.get_brand_rules(TENANT_A)
        assert rules.tenant_id == TENANT_A
        assert len(rules.system_prompt) > 0


# ── SEO Config ────────────────────────────────────────────────

class TestSEOConfigLoading:

    async def test_load_seo_config_aa_internal(self, svc):
        config = await svc.get_seo_config(TENANT_A)
        assert config.tenant_id == TENANT_A
        assert config.seo_provider == "dataforseo"
        assert "primary" in config.target_market

    async def test_load_seo_config_b2b_custom(self, svc):
        config = await svc.get_seo_config(TENANT_B)
        assert config.seo_provider == "custom"
        assert config.target_market.get("primary") == "en_UK"

    async def test_seo_provider_differs_per_tenant(self, svc):
        config_a = await svc.get_seo_config(TENANT_A)
        config_b = await svc.get_seo_config(TENANT_B)
        assert config_a.seo_provider != config_b.seo_provider

    async def test_seo_config_cached(self, svc, fake_cache):
        await svc.get_seo_config(TENANT_A)
        cached = fake_cache.get(f"config:seo:{TENANT_A}")
        assert cached is not None
        data = json.loads(cached)
        assert data["seo_provider"] == "dataforseo"


# ── Export Config ─────────────────────────────────────────────

class TestExportConfigLoading:

    async def test_load_export_config_aa_internal(self, svc):
        config = await svc.get_export_config(TENANT_A)
        assert config.tenant_id == TENANT_A
        assert config.export_format == "json"

    async def test_unknown_tenant_export_config_default(self, svc):
        config = await svc.get_export_config("nonexistent")
        assert config.export_format == "json"
        assert config.webhook_url is None


# ── Tenant Validation ─────────────────────────────────────────

class TestTenantValidation:

    async def test_active_tenant_returns_true(self, svc):
        assert await svc.is_active_tenant(TENANT_A) is True

    async def test_unknown_tenant_returns_false(self, svc):
        assert await svc.is_active_tenant("ghost_tenant") is False

    async def test_get_tenant_returns_metadata(self, svc):
        tenant = await svc.get_tenant(TENANT_A)
        assert tenant is not None
        assert tenant["tenant_id"] == TENANT_A
        assert tenant["is_active"] is True
        assert "plan_tier" in tenant

    async def test_tenant_cached_after_first_call(self, svc, fake_cache):
        await svc.get_tenant(TENANT_A)
        cached = fake_cache.get(f"config:tenant:{TENANT_A}")
        assert cached is not None
