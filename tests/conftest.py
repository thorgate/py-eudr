"""Offline test helpers: canned EUDR responses, envelope capture and XSD validation."""

import socket
import typing as t

import pytest
import requests
import zeep.transports
from lxml import etree

from py_eudr import ClientV3, ClientV4
from py_eudr.transport import load_vendored

SOAP_ENV = "http://schemas.xmlsoap.org/soap/envelope/"
WSSE = (
    "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
)
BASE = "http://ec.europa.eu/sanco/tracesnt/base/v4"
ERROR = "http://ec.europa.eu/sanco/tracesnt/error/v01"
ECHO = "http://ec.europa.eu/tracesnt/eudr/echo"
EUDR = "http://ec.europa.eu/tracesnt/certificate/eudr"

UUID = "11111111-2222-3333-4444-555555555555"
REFERENCE_NUMBER = "25EEABCDEFGHIJ"
VERIFICATION_NUMBER = "ABCDEFGH"


def namespaces(version: str) -> t.Dict[str, str]:
    return {
        "dds": f"{EUDR}/due-diligence-statement/{version}",
        "sd": f"{EUDR}/simplified-declaration/{version}",
        "common": f"{EUDR}/common/{version}",
        "verify": (
            f"{EUDR}/verify-declaration/v3"
            if version == "v3"
            else f"{EUDR}/verification/v4"
        ),
        "body": f"http://ec.europa.eu/tracesnt/body/{version}",
        "echo": ECHO,
        "error": ERROR,
    }


def overview(version: str) -> str:
    """Children of an OverviewType element (common namespace)."""
    fields = [
        ("uuid", UUID),
        ("internalReferenceNumber", "REF-1"),
        ("referenceNumber", REFERENCE_NUMBER),
    ]
    if version == "v4":
        fields.append(("referenceNumberInfo", "Info"))
    fields += [
        ("verificationNumber", VERIFICATION_NUMBER),
        ("status", "AVAILABLE"),
        ("date", "2026-11-19T12:00:00Z"),
    ]
    return "".join(f'<c:{n} xmlns:c="{{common}}">{v}</c:{n}>' for n, v in fields)


def fault(code_element: str, namespace_key: str, message: str, error_id: str) -> str:
    return (
        "<soap:Fault><faultcode>soap:Server</faultcode>"
        f"<faultstring>{message}</faultstring><detail>"
        f'<x:{code_element} xmlns:x="{{{namespace_key}}}" xmlns:e="{{error}}">'
        f"<e:Error><e:ID>{error_id}</e:ID><e:Message>{message}</e:Message>"
        "<e:Field>statement</e:Field></e:Error>"
        f"</x:{code_element}></detail></soap:Fault>"
    )


def responses(version: str) -> t.Dict[str, t.Tuple[int, str]]:
    """Canned SOAP bodies keyed by request element name: (HTTP status, body XML)."""
    ov = overview(version)
    modification = f"<uuid>{UUID}</uuid><status>AVAILABLE</status>"
    sd_modification = (
        f"<uuid>{UUID}</uuid><version>2</version><status>AVAILABLE</status>"
    )
    return {
        "EudrEchoRequest": (
            200,
            '<EudrEchoResponse xmlns="{echo}"><status>Echo: Py-EUDR</status></EudrEchoResponse>',
        ),
        "SubmitDdsRequest": (
            200,
            f'<SubmitDdsResponse xmlns="{{dds}}"><uuid>{UUID}</uuid></SubmitDdsResponse>',
        ),
        "AmendDdsRequest": (
            200,
            f'<AmendDdsResponse xmlns="{{dds}}">{modification}</AmendDdsResponse>',
        ),
        "WithdrawDdsRequest": (
            200,
            f'<WithdrawDdsResponse xmlns="{{dds}}">{modification}</WithdrawDdsResponse>',
        ),
        "GetDdsRequest": (
            200,
            f'<GetDdsResponse xmlns="{{dds}}"><ddsOverviewList>{ov}</ddsOverviewList>'
            "</GetDdsResponse>",
        ),
        "GetDdsByInternalReferenceRequest": (
            200,
            '<GetDdsByInternalReferenceResponse xmlns="{dds}">'
            f"<ddsOverviewList>{ov}</ddsOverviewList>"
            "</GetDdsByInternalReferenceResponse>",
        ),
        "GetDdsByIdentifiersRequest": (
            500,
            fault("NotFoundException", "dds", "DDS details are UI only", "NOT-FOUND"),
        ),
        "SubmitSdRequest": (
            200,
            f'<SubmitSdResponse xmlns="{{sd}}"><sdIdentifier>{UUID}</sdIdentifier>'
            "</SubmitSdResponse>",
        ),
        "UpdateSdRequest": (
            200,
            f'<UpdateSdResponse xmlns="{{sd}}">{sd_modification}</UpdateSdResponse>',
        ),
        "WithdrawSdRequest": (
            200,
            f'<WithdrawSdResponse xmlns="{{sd}}">{sd_modification}</WithdrawSdResponse>',
        ),
        "GetSdRequest": (
            200,
            f'<GetSdResponse xmlns="{{sd}}"><sdOverviewList>{ov}</sdOverviewList>'
            "</GetSdResponse>",
        ),
        "GetSdByInternalReferenceRequest": (
            200,
            '<GetSdByInternalReferenceResponse xmlns="{sd}">'
            f"<sdOverviewList>{ov}</sdOverviewList></GetSdByInternalReferenceResponse>",
        ),
        "GetSdByIdentifiersRequest": (
            500,
            fault("NotFoundException", "sd", "SD details are UI only", "NOT-FOUND"),
        ),
        "VerifyDeclarationRequest": (
            200,
            '<VerifyDeclarationResponse xmlns="{verify}"><result>EXISTING_USABLE</result>'
            "<status>AVAILABLE</status><dateTime>2026-11-19T12:00:00Z</dateTime>"
            "</VerifyDeclarationResponse>",
        ),
    }


class Sent(t.NamedTuple):
    address: str
    headers: t.Dict[str, str]
    envelope: t.Any

    @property
    def body(self) -> t.Any:
        return self.envelope.find(f"{{{SOAP_ENV}}}Body")[0]

    @property
    def header(self) -> t.Any:
        return self.envelope.find(f"{{{SOAP_ENV}}}Header")

    @property
    def soap_action(self) -> str:
        return self.headers["SOAPAction"].strip('"')

    def header_element(self, namespace: str, name: str) -> t.Any:
        header = self.header
        return None if header is None else header.find(f"{{{namespace}}}{name}")


class FakeServer:
    """Replaces ``Transport.post_xml``: records requests, answers canned responses."""

    def __init__(self) -> None:
        self.sent: t.List[Sent] = []
        self.overrides: t.Dict[str, t.Tuple[int, str]] = {}

    @property
    def last(self) -> Sent:
        return self.sent[-1]

    def post_xml(self, address: str, envelope: t.Any, headers: t.Dict[str, str]):
        sent = Sent(address, dict(headers), envelope)
        self.sent.append(sent)
        version = "v4" if address.endswith("V4") else "v3"
        request = etree.QName(sent.body).localname
        status, body = self.overrides.get(request) or responses(version)[request]
        body = body.format(**namespaces(version))
        xml = (
            f'<soap:Envelope xmlns:soap="{SOAP_ENV}"><soap:Body>{body}</soap:Body>'
            "</soap:Envelope>"
        )
        response = requests.Response()
        response.status_code = status
        response._content = xml.encode()
        response.headers["Content-Type"] = "text/xml; charset=utf-8"
        response.encoding = "utf-8"
        return response


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> FakeServer:
    fake = FakeServer()
    monkeypatch.setattr(
        zeep.transports.Transport,
        "post_xml",
        lambda self, address, envelope, headers: fake.post_xml(
            address, envelope, headers
        ),
    )
    return fake


def _blocked(*args: t.Any, **kwargs: t.Any) -> t.NoReturn:
    raise RuntimeError("Network access is not allowed in offline tests")


@pytest.fixture(autouse=True)
def no_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    if request.node.get_closest_marker("live") is None:
        monkeypatch.setattr(socket.socket, "connect", _blocked)
        monkeypatch.setattr(requests.Session, "send", _blocked)
    yield


@pytest.fixture(scope="session")
def client_v3() -> ClientV3:
    return ClientV3(test=True)


@pytest.fixture(scope="session")
def client_v4() -> ClientV4:
    return ClientV4(test=True)


@pytest.fixture(params=["v3", "v4"])
def client(request: pytest.FixtureRequest) -> t.Any:
    return request.getfixturevalue(f"client_{request.param}")


class _VendoredResolver(etree.Resolver):
    def resolve(self, system_url, public_id, context):
        data = load_vendored(system_url)
        return None if data is None else self.resolve_string(data, context)


_SCHEMAS: t.Dict[str, t.Any] = {}


def xml_schema(service_name: str, file_name: str) -> t.Any:
    """lxml XMLSchema of one vendored file, resolving imports to vendored files."""
    key = f"{service_name}/{file_name}"
    if key not in _SCHEMAS:
        parser = etree.XMLParser()
        parser.resolvers.add(_VendoredResolver())
        url = f"https://acceptance.eudr.webcloud.ec.europa.eu/tracesnt/ws/{service_name}?xsd={file_name}"
        document = etree.fromstring(load_vendored(url), parser, base_url=url)
        _SCHEMAS[key] = etree.XMLSchema(document)
    return _SCHEMAS[key]


def assert_valid(schema: t.Any, element: t.Any) -> None:
    copy = etree.fromstring(etree.tostring(element))
    if not schema.validate(copy):
        raise AssertionError(
            f"{etree.QName(element).localname} is invalid: {schema.error_log}\n"
            + etree.tostring(element, pretty_print=True).decode()
        )
