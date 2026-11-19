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

import requests
from lxml import etree
from zeep.transports import Transport

from py_eudr.exceptions import MalformedResponseError

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
    try:
        if "xsd" in query:
            file_name = f"xsd{int(query['xsd'][0])}.xsd"
        elif query.get("wsdl", [""])[0]:
            file_name = f"wsdl{int(query['wsdl'][0])}.wsdl"
        elif "wsdl" in query:
            file_name = f"{service_name}.wsdl"
        else:
            return None
    except ValueError:
        raise SchemaNotVendoredError(f"Malformed EUDR schema URL {url}") from None
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


def copy_session(session: requests.Session) -> requests.Session:
    """Return a new session with the configuration of ``session``.

    zeep's transport modifies its session (mounts a ``file://`` adapter and sets the
    ``User-Agent`` header), so the caller's session is never used directly. Proxies,
    TLS settings (``verify``, ``cert``), ``auth``, headers, cookies, parameters,
    redirect and environment settings and mounted adapters (e.g. retries) are copied;
    adapters are shared, so connection pools are reused.
    """
    copy = requests.Session()
    copy.headers.update(session.headers)
    copy.proxies.update(session.proxies)
    copy.params.update(session.params)
    copy.cookies.update(session.cookies)
    copy.verify = session.verify
    copy.cert = session.cert
    copy.auth = session.auth
    copy.trust_env = session.trust_env
    copy.max_redirects = session.max_redirects
    for prefix, adapter in session.adapters.items():
        copy.mount(prefix, adapter)
    return copy


def make_transport(
    *,
    vendored_schemas: bool = True,
    timeout: float = 300,
    operation_timeout: t.Optional[float] = 60,
    session: t.Optional[requests.Session] = None,
) -> Transport:
    """Build the transport used by the EUDR clients.

    ``timeout`` applies to loading WSDL/XSD files (only with ``vendored_schemas=False``),
    ``operation_timeout`` to SOAP calls. ``session`` provides the HTTP configuration
    (proxies, TLS, retry adapters, ...); it is copied with :func:`copy_session` and
    not modified.
    """
    transport_class = (
        VendoredSchemaTransport if vendored_schemas else WellFormedResponseTransport
    )
    return transport_class(
        timeout=timeout,
        operation_timeout=operation_timeout,
        session=copy_session(session) if session is not None else None,
    )


def check_well_formed(response: requests.Response) -> None:
    """Raise :class:`MalformedResponseError` unless the body is well-formed XML.

    zeep parses responses with lxml's recover mode when ``Settings(strict=False)`` is
    used, which would silently repair a truncated response (e.g. drop list items).
    """
    parser = etree.XMLParser(
        recover=False, resolve_entities=False, no_network=True, huge_tree=False
    )
    try:
        etree.fromstring(response.content, parser)
    except etree.XMLSyntaxError as exc:
        raise MalformedResponseError(
            f"Response is not well-formed XML: {exc}",
            status_code=response.status_code,
            content=response.content,
        ) from exc


class WellFormedResponseTransport(Transport):
    """A :class:`zeep.transports.Transport` that rejects responses that are not
    well-formed XML (see :func:`check_well_formed`)."""

    def post_xml(self, address, envelope, headers):
        response = super().post_xml(address, envelope, headers)
        check_well_formed(response)
        return response


class VendoredSchemaTransport(WellFormedResponseTransport):
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
