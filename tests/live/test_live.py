"""Smoke tests against the EUDR acceptance environment.

Skipped unless EUDR_USERNAME and EUDR_AUTHENTICATION_KEY are set. Each run submits
and withdraws one DDS (V3 only, to keep the footprint small).
"""

import os
import random
import time

import pytest
from payloads import dds_statement, sd_statement

from py_eudr import ClientV3, ClientV4, PermissionDeniedError, ValidationError

USERNAME = os.environ.get("EUDR_USERNAME", "")
AUTHENTICATION_KEY = os.environ.get("EUDR_AUTHENTICATION_KEY", "")

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not (USERNAME and AUTHENTICATION_KEY),
        reason="EUDR_USERNAME and EUDR_AUTHENTICATION_KEY are not set",
    ),
]


@pytest.fixture(scope="module", params=["v3", "v4"])
def live_client(request):
    client = ClientV3() if request.param == "v3" else ClientV4()
    with client.authenticated(username=USERNAME, authentication_key=AUTHENTICATION_KEY):
        yield client


def test_echo(live_client):
    assert "Py-EUDR" in live_client.test_echo("Py-EUDR")


def test_verify_unknown_declaration(live_client):
    result = live_client.verify_declaration("25EEAAAAAAAAAA", "NOPE1234")
    assert result.result == "NON_EXISTENT"


def test_sd_submit_is_not_authorized(live_client):
    with pytest.raises((PermissionDeniedError, ValidationError)) as excinfo:
        live_client.submit_sd(
            "MICRO_OPERATOR",
            sd_statement(live_client, f"PYEUDR-SD-{random.randint(10000, 99999)}"),
        )
    assert "not authorized" in str(excinfo.value)


def test_dds_lifecycle():
    client = ClientV3()
    reference = f"PYEUDR-{random.randint(10000, 99999)}"
    with client.authenticated(username=USERNAME, authentication_key=AUTHENTICATION_KEY):
        uuid = client.submit_dds("OPERATOR", dds_statement(client, reference))
        assert uuid
        try:
            overview = []
            for _ in range(10):
                overview = client.get_dds([uuid])
                if overview and overview[0].status != "SUBMITTED":
                    break
                time.sleep(2)
            assert overview[0].uuid == uuid
            assert overview[0].internalReferenceNumber == reference
            by_reference = client.get_dds_by_internal_reference(reference)
            assert uuid in [item.uuid for item in by_reference]
        finally:
            withdrawn = client.withdraw_dds(uuid)
        assert withdrawn.uuid == uuid
        assert withdrawn.status == "WITHDRAWN"
