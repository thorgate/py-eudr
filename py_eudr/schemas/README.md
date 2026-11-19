# Vendored EUDR WSDL/XSD files

Verbatim copies of the WSDL and XSD documents published by the EUDR Information
System (release 8.2.2), fetched from the acceptance environment
(`https://acceptance.eudr.webcloud.ec.europa.eu/tracesnt/ws/<Service>?wsdl`) on
2026-11-19. They are byte-identical to the 8.2.2 snapshot in the
`mfrntic/eudr-api-client` repository (`docs/eudr_docs 8.2.2/`).

`py_eudr.transport.VendoredSchemaTransport` serves these files to zeep, so creating
a client needs no network access. The files are kept verbatim (including the
absolute acceptance URLs in imports and `soap:address`); the client binds each
service to the acceptance or production endpoint explicitly.

## Layout

```
echo/                                  EudrEchoService
v3/EUDRDueDiligenceStatementServiceV3/
v3/EUDRSimplifiedDeclarationServiceV3/
v3/EUDRVerifyDeclarationServiceV3/
v4/EUDRDueDiligenceStatementServiceV4/
v4/EUDRSimplifiedDeclarationServiceV4/
v4/EUDRVerifyDeclarationServiceV4/
```

Each service is published by JAX-WS under its URL with a query parameter:

| URL suffix | File             |
|------------|------------------|
| `?wsdl`    | `<Service>.wsdl` |
| `?wsdl=N`  | `wsdlN.wsdl`     |
| `?xsd=N`   | `xsdN.xsd`       |

The `?xsd=N` numbering is per service (always check the `targetNamespace`):

| N | DDS / SD services (V3, V4)         | Verify services (V3, V4)          | Echo                     |
|---|------------------------------------|-----------------------------------|--------------------------|
| 1 | TRACES base v4                     | TRACES base v4                    | TRACES base v4           |
| 2 | body vN (BodyIdentity header)      | eudr-common vN                    | body v3                  |
| 3 | eudr-common vN                     | verify-declaration v3 / verification v4 | echo               |
| 4 | service schema (DDS or SD)         | error v01                         | UN/CEFACT language code  |
| 5 | error v01                          | UN/CEFACT language code           |                          |
| 6 | UN/CEFACT language code            | UN/CEFACT unqualified data type   |                          |
| 7 | UN/CEFACT unqualified data type    |                                   |                          |

`wsdl1.wsdl` is the TRACES base WSDL (`WebServiceClientId` header) and
`wsdl2.wsdl` the body WSDL (`BodyIdentity` header). Verify services do not
publish a `?wsdl=2`.

## Refreshing

```
python scripts/fetch_schemas.py              # from acceptance
python scripts/fetch_schemas.py --check      # report differences only
python scripts/fetch_schemas.py --production # from production
python scripts/generate_stubs.py             # regenerate py_eudr/types/*.pyi
```

The fetch script starts at `<Service>?wsdl`, follows every import of the same
service and prints which files changed. Review the `git diff`, regenerate the type
stubs and run the tests.
