"""AA-210: unit tests for the _is_uuid guard on the pipeline_runs accounting UPDATE.

Pure truth-table tests — no DB, no network. Confirms non-UUID batch_ids (e.g. ad-hoc
verification labels) are rejected so the `WHERE batch_id = $N::uuid` cast cannot crash.
"""

import uuid

import pytest

from api.routers.admin_pipeline import _is_uuid


@pytest.mark.parametrize("value", [
    str(uuid.uuid4()),
    "ca893afe-27e2-431b-9596-b92514e7f98c",
])
def test_is_uuid_accepts_valid_uuid(value):
    assert _is_uuid(value) is True


@pytest.mark.parametrize("value", [
    "verify-s68-sonnet",
    "",
    None,
    12345,
])
def test_is_uuid_rejects_non_uuid(value):
    assert _is_uuid(value) is False
