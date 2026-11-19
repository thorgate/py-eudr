"""Every operation of ClientV3 and ClientV4, through zeep, against a fake server."""

import base64
import datetime
import typing as t

import pytest
import zeep.exceptions
from conftest import (
    BASE,
    EUDR,
    REFERENCE_NUMBER,
    UUID,
    VERIFICATION_NUMBER,
    WSSE,
    assert_valid,
    fault,
    namespaces,
    xml_schema,
)
from lxml import etree
from payloads import GEOJSON, dds_statement, sd_statement
from zeep.exceptions import Fault

from py_eudr import (
    BodyIdentity,
    BusinessRulesError,
    EUDRError,
    EUDRFault,
    NotFoundError,
    PermissionDeniedError,
)

SERVICES = {
    "echo": ("EudrEchoService", "3"),
    "dds": ("EUDRDueDiligenceStatementService{V}", "4"),
    "sd": ("EUDRSimplifiedDeclarationService{V}", "4"),
    "verify": ("EUDRVerifyDeclarationService{V}", "3"),
}


def soap_action(version: str, service: str, operation: str) -> str:
    """SOAPActions as published in the WSDLs (V3 SD get* use the DDS namespace)."""
    if service == "echo":
        return "http://ec.europa.eu/tracesnt/eudr/echo"
    if service == "verify":
        return f"{EUDR}/verification/{version}/verify-declaration"
    if service == "sd" and version == "v3" and operation.startswith("get"):
        return f"{EUDR}/due-diligence-statement/v3/{operation}"
    return f"{namespaces(version)[service]}/{operation}"


def check_overview(result: t.Any, version: str) -> bool:
    assert isinstance(result, list) and len(result) == 1
    item = result[0]
    assert item.uuid == UUID
    assert item.referenceNumber == REFERENCE_NUMBER
    assert item.verificationNumber == VERIFICATION_NUMBER
    assert item.status == "AVAILABLE"
    assert isinstance(item.date, datetime.datetime)
    if version == "v4":
        assert item.referenceNumberInfo == "Info"
    return True


def check_modification(result: t.Any, version: str) -> bool:
    return result.uuid == UUID and result.status == "AVAILABLE"


def check_sd_modification(result: t.Any, version: str) -> bool:
    return check_modification(result, version) and result.version == 2


# (method, service, WSDL operation, call, result check)
OPERATIONS: t.List[t.Tuple[str, str, str, t.Callable, t.Optional[t.Callable]]] = [
    ("test_echo", "echo", "testEcho", lambda c: c.test_echo("Py-EUDR"),
     lambda r, v: r == "Echo: Py-EUDR"),
    ("submit_dds", "dds", "submitDds",
     lambda c: c.submit_dds("OPERATOR", dds_statement(c), body_identity="OP123"),
     lambda r, v: r == UUID),
    ("amend_dds", "dds", "amendDds",
     lambda c: c.amend_dds(UUID, dds_statement(c), body_identity="OP123"),
     check_modification),
    ("withdraw_dds", "dds", "withdrawDds",
     lambda c: c.withdraw_dds(UUID, body_identity="OP123"), check_modification),
    ("get_dds", "dds", "getDds",
     lambda c: c.get_dds([UUID, UUID], body_identity="OP123"), check_overview),
    ("get_dds_by_internal_reference", "dds", "getDdsByInternalReference",
     lambda c: c.get_dds_by_internal_reference("REF-1", body_identity="OP123"),
     check_overview),
    ("get_dds_by_identifiers", "dds", "getDdsByIdentifiers",
     lambda c: c.get_dds_by_identifiers(
         REFERENCE_NUMBER, VERIFICATION_NUMBER, body_identity="OP123"), None),
    ("submit_sd", "sd", "submitSd",
     lambda c: c.submit_sd("MICRO_OPERATOR", sd_statement(c), body_identity="OP123"),
     lambda r, v: r == UUID),
    ("update_sd", "sd", "updateSd",
     lambda c: c.update_sd(UUID, sd_statement(c), body_identity="OP123"),
     check_sd_modification),
    ("withdraw_sd", "sd", "withdrawSd",
     lambda c: c.withdraw_sd(UUID, body_identity="OP123"), check_sd_modification),
    ("get_sd", "sd", "getSd",
     lambda c: c.get_sd([UUID, (UUID, 2)], body_identity="OP123"), check_overview),
    ("get_sd_by_internal_reference", "sd", "getSdByInternalReference",
     lambda c: c.get_sd_by_internal_reference("SD-1", body_identity="OP123"),
     check_overview),
    ("get_sd_by_identifiers", "sd", "getSdByIdentifiers",
     lambda c: c.get_sd_by_identifiers(
         REFERENCE_NUMBER, VERIFICATION_NUMBER, body_identity="OP123"), None),
    ("verify_declaration", "verify", "verifyDeclaration",
     lambda c: c.verify_declaration(REFERENCE_NUMBER, VERIFICATION_NUMBER),
     lambda r, v: r.result == "EXISTING_USABLE"
     and r.status == "AVAILABLE"
     and isinstance(r.dateTime, datetime.datetime)),
]  # fmt: skip


@pytest.mark.parametrize(
    "method,service,operation,call,check", OPERATIONS, ids=[o[0] for o in OPERATIONS]
)
def test_operation(client, server, method, service, operation, call, check):
    version = "v4" if type(client).__name__ == "ClientV4" else "v3"
    service_name = SERVICES[service][0].format(V=version.upper())

    with client.authenticated(username="user", authentication_key="key") as c:
        if check is None:
            # get*ByIdentifiers: the server always answers NotFoundException.
            with pytest.raises(NotFoundError) as excinfo:
                call(c)
            assert isinstance(excinfo.value, Fault)
            assert excinfo.value.errors[0].id == "NOT-FOUND"
        else:
            result = call(c)
            assert check(result, version), result

    sent = server.last
    assert (
        sent.address
        == f"https://acceptance.eudr.webcloud.ec.europa.eu/tracesnt/ws/{service_name}"
    )
    assert sent.soap_action == soap_action(version, service, operation)

    # Request body is valid against the vendored service schema.
    assert_valid(xml_schema(service_name, SERVICES[service][1]), sent.body)

    # Headers: client id, WS-Security username token with timestamp, body identity.
    client_id = sent.header_element(BASE, "WebServiceClientId")
    assert client_id is not None and client_id.text == "eudr-test"
    security = sent.header_element(WSSE, "Security")
    assert security.find(f"{{{WSSE}}}UsernameToken/{{{WSSE}}}Username").text == "user"
    assert (
        security.find(
            "{http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd}Timestamp"
        )
        is not None
    )
    body_identity = sent.header_element(namespaces(version)["body"], "BodyIdentity")
    if service in ("dds", "sd"):
        assert body_identity is not None
        assert_valid(xml_schema(service_name, "2"), body_identity)
        assert [etree.QName(e).localname for e in body_identity] == [
            "OperatorAccessIdentifier"
        ]
        assert body_identity[0].text == "OP123"
    else:
        assert body_identity is None


def test_get_sd_uuid_and_version(client, server):
    client.get_sd([UUID, (UUID, 3), {"uuid": UUID, "versionNumber": 4}])
    items = [
        {etree.QName(e).localname: e.text for e in item} for item in server.last.body
    ]
    assert items == [
        {"uuid": UUID},
        {"uuid": UUID, "versionNumber": "3"},
        {"uuid": UUID, "versionNumber": "4"},
    ]


def test_geojson_bytes_are_base64_encoded_once(client, server):
    client.submit_dds("OPERATOR", dds_statement(client))
    geometry = server.last.body.find(".//{*}geometryGeojson")
    assert base64.b64decode(geometry.text) == GEOJSON


def test_dict_payloads_are_accepted(client, server):
    statement = {
        "activityType": "DOMESTIC",
        "geoLocationConfidential": False,
        "commodities": [
            {
                "hsHeading": "4401",
                "descriptors": {
                    "descriptionOfGoods": "Logs",
                    "goodsMeasure": {
                        "netWeight": 1,
                        "percentageEstimationOrDeviation": 5,
                    },
                },
                "producers": [{"country": "EE", "geometryGeojson": GEOJSON}],
            }
        ],
    }
    assert client.submit_dds("OPERATOR", statement) == UUID
    version = "v4" if type(client).__name__ == "ClientV4" else "v3"
    assert_valid(
        xml_schema(f"EUDRDueDiligenceStatementService{version.upper()}", "4"),
        server.last.body,
    )


def test_no_body_identity_header_by_default(client, server):
    client.get_dds([UUID])
    version = "v4" if type(client).__name__ == "ClientV4" else "v3"
    assert (
        server.last.header_element(namespaces(version)["body"], "BodyIdentity") is None
    )


def test_body_identity_kinds(client, server):
    client.get_dds([UUID], body_identity=BodyIdentity(other_body="CUSTOMS-1"))
    version = "v4" if type(client).__name__ == "ClientV4" else "v3"
    header = server.last.header_element(namespaces(version)["body"], "BodyIdentity")
    assert [(etree.QName(e).localname, e.text) for e in header] == [
        ("OtherBodyAccessIdentifier", "CUSTOMS-1")
    ]


@pytest.mark.parametrize("kwargs", [{}, {"operator": "A", "other_body": "B"}])
def test_body_identity_requires_exactly_one(kwargs):
    with pytest.raises(ValueError):
        BodyIdentity(**kwargs)


def test_business_rule_fault(client, server):
    message = "Percentage estimation or deviation is missing"
    server.overrides["SubmitDdsRequest"] = (
        500,
        fault(
            "BusinessRulesValidationException",
            "dds",
            message,
            "EUDR-COMMODITIES-DESCRIPTOR-PERCENTAGE-ESTIMATION-MISSING",
        ),
    )
    with pytest.raises(BusinessRulesError) as excinfo:
        client.submit_dds("OPERATOR", dds_statement(client))
    error = excinfo.value
    assert isinstance(error, Fault)
    assert error.message == message
    assert error.errors == [
        (
            "EUDR-COMMODITIES-DESCRIPTOR-PERCENTAGE-ESTIMATION-MISSING",
            message,
            "statement",
        )
    ]
    assert isinstance(error.__cause__, Fault)


def test_unknown_fault_is_raised_unchanged(client, server):
    server.overrides["GetDdsRequest"] = (
        500,
        "<soap:Fault><faultcode>soap:Server</faultcode>"
        "<faultstring>This API version has been discontinued.</faultstring></soap:Fault>",
    )
    with pytest.raises(Fault) as excinfo:
        client.get_dds([UUID])
    assert type(excinfo.value) is Fault


def test_schema_validation_detects_invalid_requests():
    dds = namespaces("v3")["dds"]
    element = etree.fromstring(
        f'<SubmitDdsRequest xmlns="{dds}"><operatorRole>BOGUS</operatorRole>'
        "</SubmitDdsRequest>"
    )
    with pytest.raises(AssertionError):
        assert_valid(xml_schema("EUDRDueDiligenceStatementServiceV3", "4"), element)


@pytest.mark.parametrize(
    "fault_element,exception_class",
    [
        ("BusinessRulesValidationException", BusinessRulesError),
        ("PermissionDeniedException", PermissionDeniedError),
        ("NotFoundException", NotFoundError),
    ],
)
def test_fault_mapping(client, server, fault_element, exception_class):
    server.overrides["SubmitDdsRequest"] = (
        500,
        fault(fault_element, "dds", "Rejected", "EUDR-ERROR-1"),
    )
    with pytest.raises(exception_class) as excinfo:
        client.submit_dds("OPERATOR", dds_statement(client))
    assert isinstance(excinfo.value, EUDRFault)
    assert isinstance(excinfo.value, EUDRError)
    assert isinstance(excinfo.value, Fault)
    assert excinfo.value.errors[0].id == "EUDR-ERROR-1"


def test_non_soap_error_response(client, server):
    server.raw_responses["GetDdsRequest"] = (
        503,
        "text/html",
        b"<html><body>Service Unavailable</body></html>",
    )
    with pytest.raises(zeep.exceptions.Error) as excinfo:
        client.get_dds([UUID])
    assert not isinstance(excinfo.value, EUDRFault)


@pytest.mark.parametrize("method", ["get_dds", "get_sd"])
def test_get_rejects_a_single_string(client, server, method):
    with pytest.raises(TypeError):
        getattr(client, method)(UUID)
    assert server.sent == []


@pytest.mark.parametrize("method", ["get_dds", "get_sd"])
def test_get_with_no_uuids(client, server, method):
    assert getattr(client, method)([]) == []
    assert server.sent == []
