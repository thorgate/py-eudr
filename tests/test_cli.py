"""Offline smoke tests of the integration test CLI."""

import logging

import pytest
from conftest import UUID

from py_eudr.__main__ import main

CREDENTIALS = ["-u", "user", "-a", "key"]


@pytest.mark.parametrize("version_flag", [[], ["--v4"]])
def test_echo(server, caplog, version_flag):
    with caplog.at_level(logging.INFO, logger="py_eudr.__main__"):
        main([*CREDENTIALS, *version_flag, "--echo"])
    assert "Echo response: Echo: Py-EUDR" in caplog.text
    assert server.last.address.endswith("/EudrEchoService")
    assert server.last.address.startswith("https://acceptance.")


def test_submit_and_withdraw_random_dds(server, caplog):
    with caplog.at_level(logging.INFO, logger="py_eudr.__main__"):
        main([*CREDENTIALS, "--submit-random"])
        main([*CREDENTIALS, "--retract", UUID])
    assert f"Submission result: {UUID}" in caplog.text
    goods_measure = server.sent[0].body.find(".//{*}goodsMeasure")
    assert goods_measure.find("{*}percentageEstimationOrDeviation") is not None


@pytest.mark.parametrize("command", ["--submit-random", "--submit-random-sd"])
def test_production_writes_need_explicit_flag(server, command):
    with pytest.raises(SystemExit):
        main([*CREDENTIALS, "--production", command])
    assert server.sent == []
    main([*CREDENTIALS, "--production", "--allow-production-writes", command])
    assert server.last.address.startswith("https://eudr.webcloud.ec.europa.eu/")
