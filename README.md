# Python EUDR client

Python client for the SOAP API of the EU Deforestation Regulation (EUDR) Information
System, powered by [zeep](https://docs.python-zeep.org/).

* EUDR API **V3** (`ClientV3`) and **V4** (`ClientV4`): Due Diligence Statements (DDS),
  Simplified Declarations (SD) and declaration verification.
* WSDL/XSD files are vendored in the package: creating a client needs no network access.
* Typed methods and generated type stubs for all payload types (`py.typed`).

The V1/V2 APIs have been discontinued by the EUDR Information System and are no longer
supported (py-eudr 1.0 removed the V1 `Client`).

## Usage

```python
from py_eudr import ClientV4

client = ClientV4(test=True)  # test=True: acceptance environment, False: production

with client.authenticated(username="...", authentication_key="...") as c:
    types = c.types.dds
    statement = types.DueDiligenceStatementBaseType(
        internalReferenceNumber="ORDER-1",
        activityType="DOMESTIC",
        countryOfActivity="EE",
        geoLocationConfidential=False,
        commodities=[
            types.DdsCommodityType(
                position=1,
                hsHeading="4401",
                speciesInfo=[
                    types.SpeciesInformationType(
                        scientificName="Abies sibirica", commonName="Fir"
                    )
                ],
                descriptors=types.CommercialDescriptionType(
                    descriptionOfGoods="Fir logs",
                    goodsMeasure=types.GoodsMeasureType(
                        netWeight=12.5,
                        percentageEstimationOrDeviation=5,
                    ),
                ),
                producers=[
                    types.DdsProducerType(
                        position=1,
                        country="EE",
                        name="Producer OÜ",
                        geometryGeojson=geojson_bytes,  # raw GeoJSON, zeep base64-encodes bytes
                    )
                ],
            )
        ],
    )
    uuid = c.submit_dds("OPERATOR", statement)  # -> "uuid"
    overview = c.get_dds([uuid])  # -> [OverviewType]
    print(
        overview[0].status, overview[0].referenceNumber, overview[0].verificationNumber
    )
    c.withdraw_dds(uuid)  # -> uuid + status
    c.verify_declaration("<reference number>", "<verification number>")
```

A client instance is relatively expensive to build, so build it once and share it.
Credentials can be set in two ways:

* `client.authenticate(username=..., authentication_key=...)` sets them on the instance;
  every thread and task uses them. Nothing is stored in the current context. Use it for a
  single set of credentials: replacing them while other requests run would send those
  requests with the new credentials, so `authenticate()` emits a `RuntimeWarning` when
  different credentials replace already-set ones.
* `with client.authenticated(...)` sets them in the current context (thread or asyncio
  task) only, overriding the instance credentials, so concurrent tasks can use different
  credentials with one instance. Work handed to other threads sees them only when the
  context is copied: `asyncio.to_thread` and `contextvars.copy_context().run(...)` do,
  `loop.run_in_executor` and plain threads do not. **For multi-tenant use (requests on
  behalf of different users), always use `authenticated()`.**

Combining both is possible but easy to get wrong: inside `with authenticated(B)`, work
dispatched to a thread that does not copy the context runs with the instance credentials
`A` set by `authenticate()`, i.e. as the wrong user. `authenticated()` therefore emits a
`RuntimeWarning` when instance credentials are set.

A call without credentials raises `py_eudr.EUDRError` instead of sending an
unauthenticated request; this also applies to zeep's `create_message()` on the service
clients.
The `webServiceClientId` header defaults to `eudr-test` on acceptance and
`eudr-repository` on production; pass `client_id=` to override it.

Other constructor options:

* `operation_timeout`: seconds per SOAP call (default 60).
* `session`: a `requests.Session` with the HTTP configuration (proxies, `verify`, `cert`,
  `auth`, headers, cookies, hooks, `stream`, mounted retry adapters). It is copied, never
  modified (zeep changes its session); the copy is shared by the service clients. The
  copy is a plain `requests.Session` (behaviour of a `Session` subclass is lost) and zeep
  sets its own `User-Agent` header.
* `settings`: zeep `Settings`. The default `Settings(strict=False)` tolerates new optional
  elements in server responses. It also makes zeep's XML parser repair malformed XML, so
  the transport checks that every response is well-formed first and raises
  `py_eudr.exceptions.MalformedResponseError` (an `EUDRError` and a zeep `TransportError`)
  for e.g. truncated responses.
* `transport`: a zeep transport used as is (not combinable with `session`). A plain
  `zeep.transports.Transport` loads the WSDL/XSD files from the network and skips the
  well-formedness check; `py_eudr.transport.make_transport()` builds the default one.
* `plugins`: zeep plugins, applied after the authentication check.

`client.test` is read-only. The service clients (`client.dds_client`, ...) are bound to
the selected environment: `service` and `bind()` use the acceptance or production
address, never the address in the vendored WSDL.

### Operations

`ClientV3` and `ClientV4` have the same methods:

| Method | Returns |
|--------|---------|
| `test_echo(query)` | echoed status string |
| `submit_dds(operator_role, statement)` | UUID of the new DDS |
| `amend_dds(uuid, statement)` | `uuid`, `status` |
| `withdraw_dds(uuid)` | `uuid`, `status` |
| `get_dds(uuids)` | list of `OverviewType` |
| `get_dds_by_internal_reference(internal_reference)` | list of `OverviewType` |
| `get_dds_by_identifiers(reference_number, verification_number)` | always raises `NotFoundError` (see below) |
| `submit_sd(operator_role, statement)` | UUID (SD identifier) of the new SD |
| `update_sd(sd_identifier, statement)` | `uuid`, `version`, `status` |
| `withdraw_sd(sd_identifier)` | `uuid`, `version`, `status` |
| `get_sd(uuids)` | list of `OverviewType`; items are UUIDs or `(uuid, version_number)` tuples |
| `get_sd_by_internal_reference(internal_reference)` | list of `OverviewType` |
| `get_sd_by_identifiers(reference_number, verification_number)` | always raises `NotFoundError` (see below) |
| `verify_declaration(reference_number, verification_number)` | `result`, `status`, `dateTime` |

DDS and SD methods accept a keyword-only `body_identity` for the optional `BodyIdentity`
SOAP header: either a `BodyIdentity(operator=...)` or a plain string, which means an
`OperatorAccessIdentifier` (the only kind accepted by the EUDR endpoints).

`get_dds_by_identifiers` and `get_sd_by_identifiers` are kept for API compatibility only:
the server no longer returns statement content over the API ("details can only be
accessed through the UI") and always answers with a `NotFoundException`.

### Types

Payload types are zeep types grouped per service: `client.types.dds`, `client.types.sd`
and `client.types.verify`. Nested values can also be given as plain dicts; zeep converts
them, but type checkers do not check dicts.

Type checkers and IDEs see generated stubs (`py_eudr/types/v3.pyi`, `v4.pyi`): attribute
and keyword argument names, `Literal` values of enumerations (e.g. `operator_role`,
`activityType`, `status`) and which fields are optional. Runtime objects stay dynamic
zeep objects. `py_eudr.types.v3` and `py_eudr.types.v4` are stub-only modules: import them
under `if typing.TYPE_CHECKING:` for annotations, e.g. `statement: "v4.DueDiligenceStatementBaseType"`.

Value conventions (zeep):

* `base64Binary` fields (`geometryGeojson`) take the raw content as `bytes`, which zeep
  base64-encodes, or an already base64-encoded `str`; they are returned decoded as `bytes`.
* Decimal fields (`netWeight`, `percentageEstimationOrDeviation`, ...) are returned as
  `Decimal`; pass `Decimal` or `str` values to avoid binary float rounding (`float` and
  `int` are accepted too).

### Errors

SOAP faults are raised as `zeep.exceptions.Fault`. Known EUDR faults are raised as
subclasses of `py_eudr.EUDRFault` (itself a `Fault` and a `py_eudr.EUDRError`) with the error
details in `.errors` (a list of `ErrorDetail(id, message, field)`):

* `py_eudr.BusinessRulesError` (`BusinessRulesValidationException`)
* `py_eudr.PermissionDeniedError` (`PermissionDeniedException`)
* `py_eudr.NotFoundError` (`NotFoundException`)

Requests that violate the XSD itself (e.g. a too long value) are rejected by the
server's XML parser with a plain `Fault` (a `SAXParseException` message, no EUDR error
details), not with `BusinessRulesError`.

Responses that zeep must not parse raise `py_eudr.MalformedResponseError`, which is both
an `EUDRError` and a `zeep.exceptions.TransportError` (with `status_code` and `content`):
a body that is not well-formed XML (e.g. truncated, or an HTML error page), or an HTTP
error status (>= 400) with an XML body that is not a SOAP envelope (e.g. an XHTML error
page). These checks are done by the default transport; empty bodies are left to zeep.

Errors outside the `EUDRError` hierarchy come from zeep and lxml:
`zeep.exceptions.ValidationError` (a value zeep cannot serialize, raised before sending),
other `zeep.exceptions.TransportError`s (zeep's own handling of non-SOAP responses) and
`zeep.exceptions.XMLSyntaxError` (e.g. XML without a SOAP envelope with a success
status). To catch everything, use `except zeep.exceptions.Error`
(which includes `EUDRFault`) together with `except py_eudr.EUDRError` (e.g. not
authenticated) and `requests.RequestException` (connection errors, timeouts).

```python
from py_eudr import BusinessRulesError

try:
    client.submit_dds("OPERATOR", statement)
except BusinessRulesError as error:
    for detail in error.errors:
        print(detail.id, detail.message, detail.field)
```

### Business rules and limits

* DDS: `goodsMeasure.percentageEstimationOrDeviation` is required by the server
  (`EUDR-COMMODITIES-DESCRIPTOR-PERCENTAGE-ESTIMATION-MISSING`), although it is optional
  in the XSD.
* zeep does not check XSD facets (lengths, patterns) before sending; the server rejects
  such requests. Note that V3 limits the SD `internalReferenceNumber` to 14 characters
  (V4: 50).

### V3 and V4

V4 is V3 with new namespaces and a few additions: `CANCELLED` status, optional
`summaryAddress`, `referenceNumberInfo` and `geometryData` fields, longer SD internal
reference numbers, and the `PermissionDeniedException` fault declared in the WSDL.
`ClientV3` and `ClientV4` share the implementation; switching is a matter of changing the
class (and handling the new optional fields).

## Vendored schemas

The WSDL and XSD files of all services are vendored in `py_eudr/schemas` (see its
[README](py_eudr/schemas/README.md)). Clients are always bound to the acceptance or
production endpoint, regardless of the address in the vendored WSDL. To load the
definitions from the server instead (e.g. to debug a schema change), use
`ClientV4(vendored_schemas=False)`.

To refresh the schemas and the type stubs:

```shell
python scripts/fetch_schemas.py      # downloads from acceptance, prints changed files
python scripts/generate_stubs.py     # regenerates py_eudr/types/*.pyi
pytest
```

## Development

```shell
poetry install --with dev
pytest                         # offline tests (network is blocked, live tests deselected)
ruff check . && ruff format --check .
mypy py_eudr tests/typing/example.py
```

The offline tests build every request through zeep, validate it against the vendored
XSDs, and parse canned responses. Live smoke tests against the acceptance environment
(echo, verify, SD permission check, one DDS submit/get/withdraw) never run with plain
`pytest`; select them with `-m live` and set credentials:

```shell
EUDR_USERNAME=... EUDR_AUTHENTICATION_KEY=... pytest -m live -v
```

## Integration test CLI

```shell
export EUDR_USERNAME=notsosecret
export EUDR_AUTHENTICATION_KEY=verysecret
python -m py_eudr --echo
```

Expected output:
```
INFO:__main__:Echo response: User notsosecret, using third party system eudr-test and IP address 1.2.3.4 says: Py-EUDR
```

Other commands: `--submit-random`, `--retrieve UUID`, `--retract UUID` (DDS),
`--submit-random-sd`, `--retrieve-sd UUID`, `--retract-sd UUID` (SD) and
`--verify REFERENCE_NUMBER VERIFICATION_NUMBER`. `--v4` uses the V4 API (V3 is the
default) and `--production` the production environment; submitting random data to
production additionally requires `--allow-production-writes`. See `python -m py_eudr --help`.
