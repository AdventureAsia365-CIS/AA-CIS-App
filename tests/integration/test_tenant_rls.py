"""
Integration tests — Gap 1: Tenant RLS Isolation
PRD v4: mỗi tenant chỉ đọc/ghi data của mình.

IMPORTANT: Tests dùng app_conn (app_user role) — không phải db_conn (cistest/owner).
RLS chỉ enforce với non-owner roles.

Setup:
    sudo -u postgres psql -d cis_integration_test -c "
      CREATE ROLE app_user LOGIN PASSWORD 'appuser123';
      GRANT USAGE ON SCHEMA shared, silver_aa_internal, gold_aa_internal TO app_user;
      GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA silver_aa_internal TO app_user;
      GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA gold_aa_internal TO app_user;
      GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA shared TO app_user;
      GRANT USAGE ON ALL SEQUENCES IN SCHEMA silver_aa_internal TO app_user;
      GRANT USAGE ON ALL SEQUENCES IN SCHEMA gold_aa_internal TO app_user;
      GRANT USAGE ON ALL SEQUENCES IN SCHEMA shared TO app_user;
    "
"""

import uuid
import pytest
import psycopg2
from _constants import BATCH_ID, TENANT_ID
BATCH_B = '00000000-0000-0000-0000-000000000098'
TENANT_A_UUID = '00000000-0000-0000-0000-000000000001'
TENANT_B_UUID = '00000000-0000-0000-0000-000000000099'

TENANT_A = "00000000-0000-0000-0000-000000000001"
TENANT_B = "00000000-0000-0000-0000-000000000099"

# app_conn fixture — connects as app_user (non-owner → RLS enforced)
@pytest.fixture
def app_conn():
    conn = psycopg2.connect(
        host="127.0.0.1", port=5432,
        dbname="cis_integration_test",
        user="app_user", password="appuser123",
    )
    conn.autocommit = True
    yield conn
    # Cleanup — reconnect as owner to truncate
    owner = psycopg2.connect(
        host="127.0.0.1", port=5432,
        dbname="cis_integration_test",
        user="cistest", password="cistest",
    )
    owner.autocommit = True
    cur = owner.cursor()
    cur.execute("""
        TRUNCATE TABLE
            gold_aa_internal.published_tours,
            silver_aa_internal.quality_scores,
            silver_aa_internal.generated_content,
            silver_aa_internal.seo_context,
            silver_aa_internal.raw_tours,
            shared.pipeline_runs
        RESTART IDENTITY CASCADE
    """)
    cur.close()
    owner.close()
    conn.close()


def _insert_tour(conn, tenant_id: str, src_name: str = None) -> str:
    """Insert tour under specific tenant context via app_user connection."""
    tour_id = str(uuid.uuid4())
    cur = conn.cursor()
    # Set RLS context then insert in same transaction block
    cur.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant_id,))
    cur.execute("""
        INSERT INTO silver_aa_internal.raw_tours
            (tour_id, batch_id, tenant_id, country, src_name,
             src_subtitle, src_summary, src_highlights, src_itineraries,
             pipeline_status)
        VALUES (%s, %s, %s, 'Vietnam', %s, 'Sub', 'Sum', '[]', '[]', 'ingested')
    """, (tour_id,
          BATCH_B if tenant_id == TENANT_B_UUID else BATCH_ID,
          tenant_id,
          src_name or f"Tour by {tenant_id}"))
    cur.close()
    return tour_id


class TestRLSTenantIsolation:
    """Core RLS tests — tenant A cannot see tenant B data."""

    def test_tenant_a_cannot_see_tenant_b_tours(self, app_conn):
        """Insert tour as tenant B → query as tenant A → must return 0 rows."""
        tour_id_b = _insert_tour(app_conn, TENANT_B, "Secret B2B Tour")

        cur = app_conn.cursor()
        cur.execute("SELECT set_config('app.tenant_id', %s, false)", (TENANT_A,))
        cur.execute(
            "SELECT COUNT(*) FROM silver_aa_internal.raw_tours WHERE tour_id = %s",
            (tour_id_b,)
        )
        count = cur.fetchone()[0]
        cur.close()
        assert count == 0, "Tenant A can see Tenant B tour — RLS not working!"

    def test_tenant_b_cannot_see_tenant_a_tours(self, app_conn):
        """Insert tour as tenant A → query as tenant B → must return 0 rows."""
        tour_id_a = _insert_tour(app_conn, TENANT_A, "Internal AA Tour")

        cur = app_conn.cursor()
        cur.execute("SELECT set_config('app.tenant_id', %s, false)", (TENANT_B,))
        cur.execute(
            "SELECT COUNT(*) FROM silver_aa_internal.raw_tours WHERE tour_id = %s",
            (tour_id_a,)
        )
        count = cur.fetchone()[0]
        cur.close()
        assert count == 0, "Tenant B can see Tenant A tour — RLS not working!"

    def test_tenant_sees_only_own_tours(self, app_conn):
        """Insert 3 tours for A, 2 for B → each sees only their own count."""
        for i in range(3):
            _insert_tour(app_conn, TENANT_A, f"Tour A {i}")
        for i in range(2):
            _insert_tour(app_conn, TENANT_B, f"Tour B {i}")

        cur = app_conn.cursor()

        cur.execute("SELECT set_config('app.tenant_id', %s, false)", (TENANT_A,))
        cur.execute("SELECT COUNT(*) FROM silver_aa_internal.raw_tours")
        count_a = cur.fetchone()[0]

        cur.execute("SELECT set_config('app.tenant_id', %s, false)", (TENANT_B,))
        cur.execute("SELECT COUNT(*) FROM silver_aa_internal.raw_tours")
        count_b = cur.fetchone()[0]

        cur.close()
        assert count_a == 3, f"Tenant A expected 3, got {count_a}"
        assert count_b == 2, f"Tenant B expected 2, got {count_b}"

    def test_tenant_a_cannot_update_tenant_b_tour(self, app_conn):
        """Tenant A UPDATE on Tenant B tour → affects 0 rows."""
        tour_id_b = _insert_tour(app_conn, TENANT_B, "B2B Tour")

        cur = app_conn.cursor()
        cur.execute("SELECT set_config('app.tenant_id', %s, false)", (TENANT_A,))
        cur.execute("""
            UPDATE silver_aa_internal.raw_tours
            SET pipeline_status = 'failed'
            WHERE tour_id = %s
        """, (tour_id_b,))
        rows_affected = cur.rowcount
        cur.close()
        assert rows_affected == 0, "Tenant A updated Tenant B tour — RLS not blocking writes!"

    def test_pipeline_runs_isolated_per_tenant(self, app_conn):
        """pipeline_runs: tenant A cannot see tenant B's batch costs."""
        cur = app_conn.cursor()
        run_id_b = str(uuid.uuid4())

        cur.execute("SELECT set_config('app.tenant_id', %s, false)", (TENANT_B,))
        cur.execute("""
            INSERT INTO shared.pipeline_runs
                (id, tenant_id, batch_id, tours_total, cost_usd)
            VALUES (%s, %s, %s, 10, 0.85)
        """, (run_id_b, TENANT_B, str(uuid.uuid4())))

        cur.execute("SELECT set_config('app.tenant_id', %s, false)", (TENANT_A,))
        cur.execute(
            "SELECT COUNT(*) FROM shared.pipeline_runs WHERE id = %s",
            (run_id_b,)
        )
        count = cur.fetchone()[0]
        cur.close()
        assert count == 0, "Tenant A can see Tenant B pipeline costs — billing leak!"

    def test_published_tours_isolated(self, app_conn):
        """gold layer: tenant A cannot access tenant B published tours."""
        cur = app_conn.cursor()
        tour_id = str(uuid.uuid4())

        cur.execute("SELECT set_config('app.tenant_id', %s, false)", (TENANT_B,))
        # Insert raw_tour first — published_tours.tour_id FK references raw_tours
        cur.execute("""
            INSERT INTO silver_aa_internal.raw_tours
                (tour_id, batch_id, tenant_id, country, src_name, pipeline_status)
            VALUES (%s, %s, %s, 'Vietnam', 'B2B Gold Test', 'published')
        """, (tour_id, BATCH_B, TENANT_B))
        cur.execute("""
            INSERT INTO gold_aa_internal.published_tours
                (tour_id, tenant_id, generated_content_id, aa_name, aa_subtitle,
                 aa_summary, aa_highlights, aa_itineraries, seo_title, seo_meta,
                 quality_score)
            VALUES (%s, %s, %s, 'B2B Tour', 'Sub', 'Sum', '[]', '...',
                    'T', 'M', 0.90)
        """, (tour_id, TENANT_B, str(uuid.uuid4())))

        cur.execute("SELECT set_config('app.tenant_id', %s, false)", (TENANT_A,))
        cur.execute(
            "SELECT COUNT(*) FROM gold_aa_internal.published_tours WHERE tour_id = %s",
            (tour_id,)
        )
        count = cur.fetchone()[0]
        cur.close()
        assert count == 0, "Tenant A can access Tenant B Gold content!"


class TestRLSTenantContext:
    """Test: tenant context correctly scopes queries."""

    def test_correct_tenant_sees_own_data(self, app_conn):
        """Tenant can read their own data when context is set correctly."""
        tour_id = _insert_tour(app_conn, TENANT_A, "My Tour")

        cur = app_conn.cursor()
        cur.execute("SELECT set_config('app.tenant_id', %s, false)", (TENANT_A,))
        cur.execute(
            "SELECT tenant_id FROM silver_aa_internal.raw_tours WHERE tour_id = %s",
            (tour_id,)
        )
        row = cur.fetchone()
        cur.close()
        assert row is not None, "Tenant cannot read own data!"
        assert row[0] == TENANT_A

    def test_no_context_returns_no_rows(self, app_conn):
        """Empty app.tenant_id → RLS returns 0 rows."""
        _insert_tour(app_conn, TENANT_A, "Should be hidden")

        cur = app_conn.cursor()
        cur.execute("SELECT set_config('app.tenant_id', '00000000-0000-0000-0000-000000000000', false)")
        cur.execute("SELECT COUNT(*) FROM silver_aa_internal.raw_tours")
        count = cur.fetchone()[0]
        cur.close()
        assert count == 0, "Rows visible without tenant context — RLS misconfigured!"
