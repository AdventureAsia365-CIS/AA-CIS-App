import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

SERVICE_DIR = Path(__file__).parent.parent.parent / "services/acp_brand_brief_parser"
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

from db import upsert_brand_rules  # noqa: E402
from models import BrandRulesRow  # noqa: E402


def _make_row(tenant_id="a1b2c3d4-0001-4000-8000-000000000001"):
    return BrandRulesRow(
        tenant_id=tenant_id,
        brand_type="Luxury cultural travel brand",
        core_idea="Discreet executive adventure",
        target_markets=["US", "UK"],
        customer_segment="senior professionals",
        customer_mindset="time-poor, status-conscious",
        voice_examples={
            "tone_traits": ["Elegant", "Discreet"],
            "good_example": None,
            "preferred": [],
            "should_not_write": [],
        },
        style_guide="Formal, precise.",
        forbidden_words=["cheap", "budget"],
        system_prompt="You are writing travel content for Atlas.",
        source_docx_s3_key="brand-briefs/atlas/brief.docx",
        updated_at="2026-08-28T00:00:00+00:00",
    )


def _mock_conn(existing_id):
    """Build a mock psycopg2 connection whose cursor().fetchone() sequence
    mirrors a real INSERT/UPDATE followed by the version-snapshot INSERT."""
    cur = MagicMock()
    cur.fetchone.side_effect = [
        (existing_id,) if existing_id else None,  # existence check
        ("11111111-1111-1111-1111-111111111111",),  # INSERT/UPDATE ... RETURNING id
    ]
    cur.__enter__.return_value = cur
    cur.__exit__.return_value = False

    conn = MagicMock()
    conn.cursor.return_value = cur
    conn.__enter__.return_value = conn
    conn.__exit__.return_value = False
    return conn, cur


@patch.dict("os.environ", {"DATABASE_URL": "postgresql://user:pass@localhost/db"})
@patch("db.psycopg2.connect")
def test_insert_branch_sets_brand_name_default(mock_connect):
    """AA-383: a tenant with no existing tenant_brand_rules row must get
    brand_name='default' on INSERT, or the NOT NULL constraint fails live."""
    conn, cur = _mock_conn(existing_id=None)
    mock_connect.return_value = conn

    upsert_brand_rules(_make_row())

    insert_calls = [c for c in cur.execute.call_args_list if "INSERT INTO shared.tenant_brand_rules" in c.args[0]]
    assert len(insert_calls) == 1
    sql = insert_calls[0].args[0]
    assert "brand_name" in sql
    assert "'default'" in sql


@patch.dict("os.environ", {"DATABASE_URL": "postgresql://user:pass@localhost/db"})
@patch("db.psycopg2.connect")
def test_update_branch_sets_brand_name_default(mock_connect):
    """AA-383: the UPDATE branch must also keep brand_name pinned to
    'default' (it previously left the column untouched)."""
    conn, cur = _mock_conn(existing_id="262dea1c-3910-4d69-ac60-97644a9ac76f")
    mock_connect.return_value = conn

    upsert_brand_rules(_make_row())

    update_calls = [c for c in cur.execute.call_args_list if "UPDATE shared.tenant_brand_rules" in c.args[0]]
    assert len(update_calls) == 1
    sql = update_calls[0].args[0]
    assert "brand_name = 'default'" in sql
