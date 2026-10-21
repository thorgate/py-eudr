# Python EUDR client

Powered by zeep

This is a work in progress. Contributions are welcome.

## Running integration test

The following command will trigger the test EUDR echo service, and output the response
```shell
export EUDR_AUTHENTICATION_KEY=verysecret
export EUDR_USERNAME=notsosecret
python -m py_eudr --echo
```

Expected output:
```
INFO:root:Echo response: User notsosecret, using third party system eudr-test and IP address 1.2.3.4 says: Py-EUDR
```

You can also try submitting random DDS data with `--submit-random` flag, and then retracting it with `--retract` flag.

See `python -m py_eudr --help` for more information.


## EUDR V3 API

V3 support is available as a separate `ClientV3`. The existing `Client` keeps using the V1 API and is not affected.

```python
from py_eudr import ClientV3

client = ClientV3(test=True)

with client.authenticated(username="...", authentication_key="...") as client:
    dds = client.types.dds.DueDiligenceStatementBaseType(...)
    client.submit_dds("OPERATOR", dds)
    client.get_dds(["<dds uuid>"])
    client.verify_declaration("<reference number>", "<verification number>")
```

V3 is a different API, not just new endpoints: operations, parameters and payload types differ from V1
(e.g. `retractDds` is now `withdrawDds`).

Available operations:
* Due Diligence Statement: `submit_dds`, `amend_dds`, `withdraw_dds`, `get_dds`, `get_dds_by_internal_reference`, `get_dds_by_identifiers`
* Simplified Declaration: `submit_sd`, `update_sd`, `withdraw_sd`, `get_sd`, `get_sd_by_internal_reference`, `get_sd_by_identifiers`
* Verify Declaration: `verify_declaration`

Types are grouped per service (`client.types.dds`, `client.types.sd`, `client.types.verify`), as services define
types with the same names. If a service defines a type with the same name in several namespaces, the EUDR one is kept;
others can be accessed with e.g. `client.dds_client.get_type("{namespace}Name")`.

The optional `bodyIdentity` SOAP header can be passed per call:

```python
client.submit_dds(
    "OPERATOR",
    dds,
    _soapheaders={"bodyIdentity": {"OperatorAccessIdentifier": "..."}},
)
```

The integration test CLI supports V3 with the `--v3` flag, e.g. `python -m py_eudr --v3 --echo`.
