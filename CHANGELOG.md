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
* EUDR faults are raised as `ValidationError`, `PermissionDeniedError` or `NotFoundError`
  (subclasses of `zeep.exceptions.Fault`); `py_eudr.exceptions.ValidationError` now
  subclasses `Fault`.
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
* CLI: `--v4`, `--production`, SD commands (`--submit-random-sd`, `--retrieve-sd`,
  `--retract-sd`) and `--verify`. Random DDS/SD set `percentageEstimationOrDeviation`,
  which the server requires.
* Offline test-suite (requests validated against the vendored XSDs) and optional live
  smoke tests against the acceptance environment.

### Fixed
* `authenticated()` now resets credentials when an exception is raised inside the context.

## 0.1.0

### Added
* Initial version of the EUDR client that is capable of passing the echo-test
* `ClientV3` supporting EUDR V3 API (Due Diligence Statement, Simplified Declaration and Verify Declaration services)
* `--v3` flag for the integration test CLI
