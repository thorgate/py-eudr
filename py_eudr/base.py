import typing as t
import contextvars
from contextlib import contextmanager

from zeep import Client as ZeepClient


from py_eudr.username_token import EUDRUsernameToken


class EchoClient(ZeepClient):
    service_url = (
        "https://acceptance.eudr.webcloud.ec.europa.eu/tracesnt/ws/EudrEchoService?wsdl"
    )

    def __init__(self):
        self._wsse_context = contextvars.ContextVar(
            "_wsse_context",
            default=t.cast(t.Optional[EUDRUsernameToken], None),
        )
        self._default_soapheaders_context = contextvars.ContextVar(
            "_default_soapheaders_context",
            default=t.cast(t.Optional[t.Dict[str, str]], None),
        )
        super().__init__(
            self.service_url,
        )

    def authenticate(
        self,
        *,
        username: str,
        authentication_key: str,
        client_id: str,
    ):
        """Authenticate the client with a new username and authentication key."""
        self.wsse = EUDRUsernameToken(
            username,
            authentication_key,
        )
        self.set_default_soapheaders(
            {"webServiceClientId": client_id},
        )

    @contextmanager
    def authenticated(
        self,
        *args,
        username: str,
        authentication_key: str,
        client_id: str,
    ):
        """Provide a thread and async safe client authenticated with given credentials."""
        wsse_token = self._wsse_context.set(
            EUDRUsernameToken(
                username,
                authentication_key,
            )
        )
        header_token = self._default_soapheaders_context.set(
            {"webServiceClientId": client_id}
        )
        yield self
        self._wsse_context.reset(wsse_token)
        self._default_soapheaders_context.reset(header_token)

    # Making an instance of Zeep client is a heavy task, as it involved downloading and parsing service and schema
    # definitions. To allow using same client instance with different authentication credentials, context variables
    # are used together with `authenticated` context manager.

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


class RetrievalClient(EchoClient):
    service_url = "https://acceptance.eudr.webcloud.ec.europa.eu/tracesnt/ws/EUDRRetrievalServiceV1?wsdl"


class SubmissionClient(EchoClient):
    service_url = "https://acceptance.eudr.webcloud.ec.europa.eu/tracesnt/ws/EUDRSubmissionServiceV1?wsdl"
