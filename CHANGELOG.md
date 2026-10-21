# Changelog

## Unreleased

### Added
* Initial version of the EUDR client that is capable of passing the echo-test
* `ClientV3` supporting EUDR V3 API (Due Diligence Statement, Simplified Declaration and Verify Declaration services)
* `--v3` flag for the integration test CLI

### Fixed
* `authenticated()` now resets credentials when an exception is raised inside the context

