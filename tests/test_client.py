"""Client construction, endpoint binding and authentication contexts."""

import threading

import pytest
from conftest import BASE, UUID, WSSE

from py_eudr import ClientV3, ClientV4
from py_eudr.base import ServiceClient
from py_eudr.transport import (
    SchemaNotVendoredError,
    VendoredSchemaTransport,
    vendored_path,
)

ACCEPTANCE = "https://acceptance.eudr.webcloud.ec.europa.eu/tracesnt/ws/"
PRODUCTION = "https://eudr.webcloud.ec.europa.eu/tracesnt/ws/"


@pytest.mark.parametrize("client_class", [ClientV3, ClientV4])
def test_construct_without_network(client_class):
    # The autouse no_network fixture blocks sockets and requests sessions.
    client = client_class()
    assert client.dds_client.wsdl.services


@pytest.mark.parametrize(
    "url,path",
    [
        (
            "https://acceptance.eudr.webcloud.ec.europa.eu:443/tracesnt/ws/"
            "EUDRDueDiligenceStatementServiceV3?xsd=4",
            "schemas/v3/EUDRDueDiligenceStatementServiceV3/xsd4.xsd",
        ),
        (
            "https://eudr.webcloud.ec.europa.eu/tracesnt/ws/"
            "EUDRVerifyDeclarationServiceV4?wsdl",
            "schemas/v4/EUDRVerifyDeclarationServiceV4/EUDRVerifyDeclarationServiceV4.wsdl",
        ),
        (
            "https://acceptance.eudr.webcloud.ec.europa.eu/tracesnt/ws/EudrEchoService?wsdl=2",
            "schemas/echo/wsdl2.wsdl",
        ),
        ("https://example.com/tracesnt/ws/EudrEchoService?wsdl", None),
    ],
)
def test_vendored_path(url, path):
    assert vendored_path(url) == path


def test_transport_refuses_unknown_urls():
    transport = VendoredSchemaTransport()
    with pytest.raises(SchemaNotVendoredError):
        transport.load("https://example.com/schema.xsd")
    with pytest.raises(SchemaNotVendoredError):
        # Verify services publish no ?wsdl=2
        transport.load(f"{ACCEPTANCE}EUDRVerifyDeclarationServiceV3?wsdl=2")


@pytest.mark.parametrize("client_class", [ClientV3, ClientV4])
@pytest.mark.parametrize("test,host", [(True, ACCEPTANCE), (False, PRODUCTION)])
def test_endpoint_address(server, client_class, test, host):
    client = client_class(test=test)
    version = "V4" if client_class is ClientV4 else "V3"
    client.test_echo("x")
    client.get_dds([UUID])
    client.get_sd([UUID])
    client.verify_declaration("25EEABCDEFGHIJ", "ABCDEFGH")
    assert [sent.address for sent in server.sent] == [
        f"{host}EudrEchoService",
        f"{host}EUDRDueDiligenceStatementService{version}",
        f"{host}EUDRSimplifiedDeclarationService{version}",
        f"{host}EUDRVerifyDeclarationService{version}",
    ]


def test_service_client_requires_name():
    with pytest.raises(ValueError):
        ServiceClient()


def _identity(sent):
    client_id = sent.header_element(BASE, "WebServiceClientId")
    security = sent.header_element(WSSE, "Security")
    username = (
        None
        if security is None
        else security.find(f"{{{WSSE}}}UsernameToken/{{{WSSE}}}Username").text
    )
    return (None if client_id is None else client_id.text, username)


def test_authenticated_context_isolation(client_v3, server):
    client_v3.get_dds([UUID])
    with client_v3.authenticated(username="alice", authentication_key="a"):
        client_v3.get_dds([UUID])
        with client_v3.authenticated(
            username="bob", authentication_key="b", client_id="custom-id"
        ):
            client_v3.get_dds([UUID])
        client_v3.get_dds([UUID])
    client_v3.get_dds([UUID])
    assert [_identity(sent) for sent in server.sent] == [
        (None, None),
        ("eudr-test", "alice"),
        ("custom-id", "bob"),
        ("eudr-test", "alice"),
        (None, None),
    ]


def test_authenticated_resets_on_exception(client_v3, server):
    with pytest.raises(RuntimeError):
        with client_v3.authenticated(username="alice", authentication_key="a"):
            raise RuntimeError
    client_v3.get_dds([UUID])
    assert _identity(server.last) == (None, None)


def test_authenticated_threads(client_v4, server):
    barrier = threading.Barrier(2)
    results = {}

    def worker(name):
        with client_v4.authenticated(username=name, authentication_key=name):
            barrier.wait()
            client_v4.verify_declaration("25EEABCDEFGHIJ", name)
            barrier.wait()

    threads = [threading.Thread(target=worker, args=(n,)) for n in ("alice", "bob")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    for sent in server.sent:
        verification = sent.body.find("{*}verificationNumber").text
        results[verification] = _identity(sent)[1]
    assert results == {"alice": "alice", "bob": "bob"}


def test_production_client_id_default(server):
    client = ClientV3(test=False)
    with client.authenticated(username="u", authentication_key="k"):
        client.test_echo("x")
    assert _identity(server.last) == ("eudr-repository", "u")
