"""Zeep transport that serves the WSDL/XSD files vendored in ``py_eudr/schemas``.

EUDR services are published by JAX-WS: every document of a service is served under
the service URL with a query parameter (``?wsdl``, ``?wsdl=N``, ``?xsd=N``) and all
imports inside the documents are absolute URLs of the acceptance host. This
transport maps such URLs (on the acceptance or production host) to the package
files, so building a client needs no network access. SOAP calls (HTTP POST) are
not affected.
"""

import pkgutil
import re
import typing as t
from urllib.parse import parse_qs, urlparse

from zeep.transports import Transport

EUDR_HOSTS = frozenset(
    {
        "acceptance.eudr.webcloud.ec.europa.eu",
        "eudr.webcloud.ec.europa.eu",
    }
)

_VERSIONED_SERVICE = re.compile(r"^EUDR[A-Za-z]+Service(V\d+)$")


class SchemaNotVendoredError(LookupError):
    """Raised when a URL does not map to a vendored schema file."""


def service_directory(service_name: str) -> str:
    """Return the directory (relative to ``py_eudr/schemas``) of a service."""
    if service_name == "EudrEchoService":
        return "echo"
    match = _VERSIONED_SERVICE.match(service_name)
    if not match:
        raise SchemaNotVendoredError(f"Unknown EUDR service {service_name!r}")
    return f"{match.group(1).lower()}/{service_name}"


def vendored_path(url: str) -> t.Optional[str]:
    """Return the resource path (relative to the ``py_eudr`` package) of the file
    serving ``url``, or ``None`` when the URL is not an EUDR service document."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or parsed.hostname not in EUDR_HOSTS:
        return None
    service_name = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    query = parse_qs(parsed.query, keep_blank_values=True)
    if "xsd" in query:
        file_name = f"xsd{int(query['xsd'][0])}.xsd"
    elif query.get("wsdl", [""])[0]:
        file_name = f"wsdl{int(query['wsdl'][0])}.wsdl"
    elif "wsdl" in query:
        file_name = f"{service_name}.wsdl"
    else:
        return None
    return f"schemas/{service_directory(service_name)}/{file_name}"


def load_vendored(url: str) -> t.Optional[bytes]:
    """Return the vendored content for ``url``, or ``None`` if it is not an EUDR URL."""
    path = vendored_path(url)
    if path is None:
        return None
    try:
        data = pkgutil.get_data("py_eudr", path)
    except FileNotFoundError:
        data = None
    if data is None:
        raise SchemaNotVendoredError(f"No vendored schema for {url} (expected {path})")
    return data


class VendoredSchemaTransport(Transport):
    """A :class:`zeep.transports.Transport` that loads EUDR WSDL/XSD files from the
    package instead of the network.

    :param strict: when true (default), loading any non-EUDR URL raises
        :class:`SchemaNotVendoredError` instead of falling back to the network.
    """

    def __init__(self, *args: t.Any, strict: bool = True, **kwargs: t.Any) -> None:
        super().__init__(*args, **kwargs)
        self.strict = strict

    def load(self, url: str) -> bytes:
        data = load_vendored(url)
        if data is not None:
            return data
        if self.strict:
            raise SchemaNotVendoredError(
                f"Refusing to load {url}: not a vendored EUDR schema"
            )
        return super().load(url)
