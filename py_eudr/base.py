from __future__ import annotations

import contextvars
import typing as t
from contextlib import contextmanager

from zeep import Client as ZeepClient
from zeep import Plugin
from zeep.settings import Settings
from zeep.transports import Transport

from py_eudr.exceptions import EUDRError
from py_eudr.transport import make_transport
from py_eudr.username_token import EUDRUsernameToken

ACCEPTANCE_HOST = "acceptance.eudr.webcloud.ec.europa.eu"
PRODUCTION_HOST = "eudr.webcloud.ec.europa.eu"


def service_address(service_name: str, *, test: bool) -> str:
    """Return the SOAP endpoint address of an EUDR service."""
    host = ACCEPTANCE_HOST if test else PRODUCTION_HOST
    return f"https://{host}/tracesnt/ws/{service_name}"


def default_settings() -> Settings:
    """zeep settings used by default: tolerate unknown elements in responses, so an
    optional element added by the server does not break every call."""
    return Settings(strict=False)


class _RequireAuthentication(Plugin):
    """Refuse to send a request without WS-Security credentials."""

    def __init__(self, client: ServiceClient) -> None:
        self.client = client

    def egress(self, envelope, http_headers, operation, binding_options):
        if self.client.wsse is None:
            raise EUDRError(
                "Client is not authenticated: use authenticate() or authenticated()"
            )
        return envelope, http_headers


_NOT_SET: t.Any = object()


class ServiceClient(ZeepClient):
    """Zeep client of a single EUDR web service.

    WSDL and XSD files are loaded from the schemas vendored in the package (no
    network access), and the service is bound to the acceptance (``test=True``) or
    production endpoint regardless of the ``soap:address`` in the WSDL.

    Pass ``vendored_schemas=False`` to load the definitions from the live server
    instead, e.g. to debug a schema drift. A ``transport`` given explicitly is used
    as is: a plain :class:`zeep.transports.Transport` loads the definitions from the
    network; use :func:`py_eudr.transport.make_transport` to configure the vendored one.

    Credentials: :meth:`authenticate` sets them on the instance (used by all threads
    and tasks); :meth:`authenticated` overrides them in the current context only.
    Calls without credentials raise :class:`py_eudr.exceptions.EUDRError`.
    """

    service_name: str = ""

    def __init__(
        self,
        service_name: t.Optional[str] = None,
        *,
        test: bool = True,
        vendored_schemas: bool = True,
        transport: t.Optional[Transport] = None,
        settings: t.Optional[Settings] = None,
    ):
        if service_name is not None:
            self.service_name = service_name
        if not self.service_name:
            raise ValueError("service_name is required")
        self._test = test
        # Instance level credentials (authenticate()) and context overrides (authenticated()).
        # The context variables are only set inside authenticated(), never on construction.
        self._instance_wsse: t.Optional[EUDRUsernameToken] = None
        self._instance_soapheaders: t.Optional[t.Dict[str, str]] = None
        self._wsse_context: contextvars.ContextVar[t.Any] = contextvars.ContextVar(
            f"eudr_wsse_{id(self)}", default=_NOT_SET
        )
        self._soapheaders_context: contextvars.ContextVar[t.Any] = (
            contextvars.ContextVar(f"eudr_soapheaders_{id(self)}", default=_NOT_SET)
        )
        if transport is None:
            transport = make_transport(vendored_schemas=vendored_schemas)
        super().__init__(
            f"{self.address}?wsdl",
            transport=transport,
            settings=settings or default_settings(),
            plugins=[_RequireAuthentication(self)],
        )

        # The vendored WSDL points at acceptance; always bind to the selected environment.
        (service,) = self.wsdl.services.values()
        (port,) = service.ports.values()
        self._bound_service = self.create_service(port.binding.name, self.address)

    @property
    def service(self):
        """The service proxy bound to the acceptance or production address."""
        return self._bound_service

    @property
    def test(self) -> bool:
        return self._test

    @property
    def address(self) -> str:
        return service_address(self.service_name, test=self.test)

    def get_client_id(self, client_id: t.Optional[str]):
        if client_id is not None:
            return client_id

        if self.test:
            return "eudr-test"

        return "eudr-repository"

    def authenticate(
        self,
        *,
        username: str,
        authentication_key: str,
        client_id: t.Optional[str] = None,
    ):
        """Set the credentials of this client instance (all threads and tasks).

        Nothing is stored in the current context; :meth:`authenticated` blocks
        override these credentials.
        """
        self.wsse = EUDRUsernameToken(username, authentication_key)
        self.set_default_soapheaders(
            {"webServiceClientId": self.get_client_id(client_id)},
        )

    @contextmanager
    def authenticated(
        self,
        *,
        username: str,
        authentication_key: str,
        client_id: t.Optional[str] = None,
    ):
        """Use the given credentials in the current context (thread or asyncio task).

        Code run in another thread does not see them unless the context is copied
        (``asyncio.to_thread`` and ``contextvars.copy_context().run`` do,
        ``run_in_executor`` and plain threads do not).
        """
        wsse_token = self._wsse_context.set(
            EUDRUsernameToken(username, authentication_key)
        )
        header_token = self._soapheaders_context.set(
            {"webServiceClientId": self.get_client_id(client_id)}
        )
        try:
            yield self
        finally:
            self._wsse_context.reset(wsse_token)
            self._soapheaders_context.reset(header_token)

    # zeep reads `wsse` and `_default_soapheaders` on every call; assignments (including
    # the ones in zeep's constructor) go to the instance level.

    @property
    def wsse(self):
        value = self._wsse_context.get()
        return self._instance_wsse if value is _NOT_SET else value

    @wsse.setter
    def wsse(self, value):
        self._instance_wsse = value

    @property
    def _default_soapheaders(self):
        value = self._soapheaders_context.get()
        return self._instance_soapheaders if value is _NOT_SET else value

    @_default_soapheaders.setter
    def _default_soapheaders(self, value):
        self._instance_soapheaders = value


class EchoClient(ServiceClient):
    service_name = "EudrEchoService"


class DueDiligenceStatementClientV3(ServiceClient):
    service_name = "EUDRDueDiligenceStatementServiceV3"


class SimplifiedDeclarationClientV3(ServiceClient):
    service_name = "EUDRSimplifiedDeclarationServiceV3"


class VerifyDeclarationClientV3(ServiceClient):
    service_name = "EUDRVerifyDeclarationServiceV3"


class DueDiligenceStatementClientV4(ServiceClient):
    service_name = "EUDRDueDiligenceStatementServiceV4"


class SimplifiedDeclarationClientV4(ServiceClient):
    service_name = "EUDRSimplifiedDeclarationServiceV4"


class VerifyDeclarationClientV4(ServiceClient):
    service_name = "EUDRVerifyDeclarationServiceV4"
