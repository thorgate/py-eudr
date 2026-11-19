"""Client construction, endpoint binding and authentication contexts."""

import contextvars
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
import requests
from conftest import BASE, UUID, WSSE
from zeep.settings import Settings

from py_eudr import ClientV3, ClientV4, EUDRError
from py_eudr.base import ServiceClient
from py_eudr.transport import (
    SchemaNotVendoredError,
    VendoredSchemaTransport,
    make_transport,
    vendored_path,
)

WSU = (
    "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd"
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


@pytest.mark.parametrize("query", ["xsd=abc", "wsdl=x"])
def test_vendored_path_malformed(query):
    with pytest.raises(SchemaNotVendoredError):
        vendored_path(f"{ACCEPTANCE}EudrEchoService?{query}")


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
    client.authenticate(username="u", authentication_key="k")
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


def test_unauthenticated_call_is_refused(client_v3, server):
    with pytest.raises(EUDRError, match="not authenticated"):
        client_v3.get_dds([UUID])
    with pytest.raises(EUDRError):
        client_v3.dds_client.service.getDds(uuidList=[UUID])
    assert server.sent == []


def test_authenticated_context_isolation(client_v3, server):
    with client_v3.authenticated(username="alice", authentication_key="a"):
        client_v3.get_dds([UUID])
        with client_v3.authenticated(
            username="bob", authentication_key="b", client_id="custom-id"
        ):
            client_v3.get_dds([UUID])
        client_v3.get_dds([UUID])
    assert [_identity(sent) for sent in server.sent] == [
        ("eudr-test", "alice"),
        ("custom-id", "bob"),
        ("eudr-test", "alice"),
    ]
    with pytest.raises(EUDRError):
        client_v3.get_dds([UUID])


def test_authenticated_resets_on_exception(client_v3, server):
    with pytest.raises(RuntimeError):
        with client_v3.authenticated(username="alice", authentication_key="a"):
            raise RuntimeError
    with pytest.raises(EUDRError):
        client_v3.get_dds([UUID])


def test_authenticate_applies_to_all_threads(server):
    client = ClientV4()
    before = len(contextvars.copy_context())
    client.authenticate(username="carol", authentication_key="c")
    assert len(contextvars.copy_context()) == before  # nothing stored in the context
    client.get_dds([UUID])
    thread = threading.Thread(target=client.get_dds, args=([UUID],))
    thread.start()
    thread.join()
    with ThreadPoolExecutor(1) as executor:
        executor.submit(client.get_dds, [UUID]).result()
    # authenticated() overrides the instance credentials in its context only
    with client.authenticated(username="dave", authentication_key="d"):
        client.get_dds([UUID])
    client.get_dds([UUID])
    assert [_identity(sent) for sent in server.sent] == [
        ("eudr-test", "carol"),
        ("eudr-test", "carol"),
        ("eudr-test", "carol"),
        ("eudr-test", "dave"),
        ("eudr-test", "carol"),
    ]


def test_construction_leaves_context_untouched():
    context = contextvars.copy_context()
    before = len(context)
    context.run(ClientV3)
    assert len(context) == before


def test_concurrent_requests_each_get_a_timestamp(client_v4, server):
    sys_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        with client_v4.authenticated(username="u", authentication_key="k"):
            with ThreadPoolExecutor(8) as executor:
                # copy the context per call, like asyncio.to_thread does
                futures = [
                    executor.submit(
                        contextvars.copy_context().run,
                        client_v4.verify_declaration,
                        "25EEABCDEFGHIJ",
                        str(i),
                    )
                    for i in range(200)
                ]
                for future in futures:
                    future.result()
    finally:
        sys.setswitchinterval(sys_interval)
    assert len(server.sent) == 200
    for sent in server.sent:
        security = sent.header_element(WSSE, "Security")
        assert security.find(f"{{{WSU}}}Timestamp") is not None
        assert security.find(f"{{{WSSE}}}UsernameToken/{{{WSSE}}}Nonce") is not None


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


def test_transport_options():
    session = requests.Session()
    client = ClientV4(operation_timeout=12, session=session)
    transports = {id(c.transport) for c in client._clients}
    assert len(transports) == 1
    assert isinstance(client.transport, VendoredSchemaTransport)
    assert client.transport.operation_timeout == 12
    assert client.transport.session is session
    assert ClientV3().transport.operation_timeout == 60


def test_custom_transport_and_settings():
    transport = make_transport(operation_timeout=5)
    settings = Settings(strict=True)
    client = ClientV3(transport=transport, settings=settings)
    assert all(c.transport is transport for c in client._clients)
    assert all(c.settings is settings for c in client._clients)


def test_default_settings_are_lenient(client, server):
    assert client.dds_client.settings.strict is False
    server.overrides["WithdrawDdsRequest"] = (
        200,
        f'<WithdrawDdsResponse xmlns="{{dds}}"><uuid>{UUID}</uuid>'
        "<status>WITHDRAWN</status><newOptionalElement>x</newOptionalElement>"
        "</WithdrawDdsResponse>",
    )
    assert client.withdraw_dds(UUID).status == "WITHDRAWN"


def test_test_flag_is_read_only(client_v3):
    with pytest.raises(AttributeError):
        client_v3.test = False
    with pytest.raises(AttributeError):
        client_v3.dds_client.test = False


def test_service_is_bound_to_selected_address():
    client = ClientV3(test=False)
    service = client.dds_client.service
    assert service is client.dds_client.service
    assert service._binding_options["address"] == (
        f"{PRODUCTION}EUDRDueDiligenceStatementServiceV3"
    )
