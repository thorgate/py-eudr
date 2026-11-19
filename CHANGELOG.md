# Changelog

## 1.0.0

### Breaking changes
* The V1 `Client` (and `RetrievalClient`, `SubmissionClient`) is removed: the EUDR
  Information System discontinued the V1/V2 APIs.
* `ClientV3` operations are real methods instead of zeep service attributes: arguments
  are snake_case positional/keyword arguments (e.g. `get_dds_by_identifiers(reference_number,
  verification_number)`, `get_sd([uuid, (uuid, version)])`), the `BodyIdentity` header is
  passed as `body_identity=` instead of `_soapheaders`, and list operations return lists
  (never `None`).
* EUDR faults are raised as `BusinessRulesError`, `PermissionDeniedError` or
  `NotFoundError` (subclasses of `EUDRFault`, a `zeep.exceptions.Fault`).
  `py_eudr.exceptions.ValidationError` is replaced by `BusinessRulesError` (avoids a clash
  with `zeep.exceptions.ValidationError`).
* `authenticate()` sets instance-level credentials used by all threads; `authenticated()`
  overrides them in the current context. Calls without credentials raise `EUDRError`
  instead of sending an unauthenticated request.
* `client.test` is read-only.
* Default zeep settings are `Settings(strict=False)` (unknown response elements are
  tolerated) and SOAP calls time out after 60 seconds (`operation_timeout`).
* `get_dds`/`get_sd` raise `TypeError` for a single string and return `[]` for no UUIDs.
* Dependencies: `zeep <5`, `lxml` and `requests` are runtime dependencies; `xmlschema`,
  `backports-strenum` and `backports-zoneinfo` are dropped.
* Live tests are deselected by default (`pytest -m live` runs them).
* The `--v3` CLI flag is removed (V3 is the default); the CLI logs through
  `logging.getLogger("py_eudr.__main__")`.

### Added
* `ClientV4` for the EUDR V4 API.
* WSDL/XSD files of all V3/V4 services and the echo service are vendored in the package;
  clients are built without network access (`vendored_schemas=False` loads them live).
  `scripts/fetch_schemas.py` refreshes them.
* Each service is bound to the acceptance or production endpoint explicitly, independent
  of the address in the WSDL.
* Generated type stubs for all V3/V4 payload types (`py_eudr/types/v3.pyi`, `v4.pyi`,
  `scripts/generate_stubs.py`), typed client methods and a `py.typed` marker.
* `BodyIdentity` helper for the `BodyIdentity` SOAP header.
* Client options `operation_timeout`, `timeout`, `session` (shared by the service clients),
  `transport` and `settings`.
* CLI: `--v4`, `--production` (writes need `--allow-production-writes`), SD commands (`--submit-random-sd`, `--retrieve-sd`,
  `--retract-sd`) and `--verify`. Random DDS/SD set `percentageEstimationOrDeviation`,
  which the server requires.
* Offline test-suite (requests validated against the vendored XSDs) and optional live
  smoke tests against the acceptance environment.

### Fixed
* `authenticated()` now resets credentials when an exception is raised inside the context.
* Concurrent requests with the same credentials could be sent without `wsu:Timestamp`
  (the shared token was mutated per request).
* Constructing a client no longer stores values in the current `contextvars` context.

## 0.1.0

### Added
* Initial version of the EUDR client that is capable of passing the echo-test
* `ClientV3` supporting EUDR V3 API (Due Diligence Statement, Simplified Declaration and Verify Declaration services)
* `--v3` flag for the integration test CLI
