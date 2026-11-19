from __future__ import annotations

import contextvars
import typing as t
from contextlib import contextmanager

from zeep import Client as ZeepClient
from zeep.transports import Transport

from py_eudr.transport import VendoredSchemaTransport
from py_eudr.username_token import EUDRUsernameToken

ACCEPTANCE_HOST = "acceptance.eudr.webcloud.ec.europa.eu"
PRODUCTION_HOST = "eudr.webcloud.ec.europa.eu"


def service_address(service_name: str, *, test: bool) -> str:
    """Return the SOAP endpoint address of an EUDR service."""
    host = ACCEPTANCE_HOST if test else PRODUCTION_HOST
    return f"https://{host}/tracesnt/ws/{service_name}"


class ServiceClient(ZeepClient):
    """Zeep client of a single EUDR web service.

    WSDL and XSD files are loaded from the schemas vendored in the package (no
    network access), and the service is bound to the acceptance (``test=True``) or
    production endpoint regardless of the ``soap:address`` in the WSDL.

    Pass ``vendored_schemas=False`` to load the definitions from the live server
    instead, e.g. to debug a schema drift.
    """

    service_name: str = ""

    def __init__(
        self,
        service_name: t.Optional[str] = None,
        *,
        test: bool = True,
        vendored_schemas: bool = True,
        transport: t.Optional[Transport] = None,
    ):
        if service_name is not None:
            self.service_name = service_name
        if not self.service_name:
            raise ValueError("service_name is required")
        self.test = test
        self._wsse_context: contextvars.ContextVar[t.Optional[EUDRUsernameToken]] = (
            contextvars.ContextVar("_wsse_context", default=None)
        )
        self._default_soapheaders_context: contextvars.ContextVar[
            t.Optional[t.Dict[str, str]]
        ] = contextvars.ContextVar("_default_soapheaders_context", default=None)
        if transport is None:
            transport = VendoredSchemaTransport() if vendored_schemas else Transport()
        super().__init__(f"{self.address}?wsdl", transport=transport)

        # The vendored WSDL points at acceptance; always bind to the selected environment.
        port = self._get_port(self._get_service(None), None)
        self._default_service = self.create_service(port.binding.name, self.address)

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
        """Authenticate the client with a new username and authentication key."""
        self.wsse = EUDRUsernameToken(
            username,
            authentication_key,
        )
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
        """Provide a thread and async safe client authenticated with given credentials."""
        wsse_token = self._wsse_context.set(
            EUDRUsernameToken(
                username,
                authentication_key,
            )
        )
        header_token = self._default_soapheaders_context.set(
            {"webServiceClientId": self.get_client_id(client_id)}
        )
        try:
            yield self
        finally:
            self._wsse_context.reset(wsse_token)
            self._default_soapheaders_context.reset(header_token)

    # To allow using the same client instance with different authentication credentials, context variables are
    # used together with the `authenticated` context manager.

    @property
    def wsse(self):
        return self._wsse_context.get()

    @wsse.setter
    def wsse(self, value):
        self._wsse_context.set(value)

    @property
    def _default_soapheaders(self):
        return self._default_soapheaders_context.get()

    @_default_soapheaders.setter
    def _default_soapheaders(self, value):
        self._default_soapheaders_context.set(value)


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
