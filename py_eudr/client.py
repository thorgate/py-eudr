import typing as t
from contextlib import ExitStack, contextmanager

from py_eudr.base import (
    DueDiligenceStatementClientV3,
    EchoClient,
    RetrievalClient,
    SimplifiedDeclarationClientV3,
    SubmissionClient,
    VerifyDeclarationClientV3,
)

EUDR_NAMESPACE_PREFIX = "http://ec.europa.eu/tracesnt/certificate/eudr/"


class Client:
    def __init__(
        self,
        *,
        test: bool = True,
    ):
        self.echo_client = EchoClient(test=test)
        self.retrieval_client = RetrievalClient(test=test)
        self.submission_client = SubmissionClient(test=test)

        self.test_echo: t.Callable[[str], str] = self.echo_client.service.testEcho
        self.get_dds_info: t.Callable[[str], t.List[str]] = (
            self.retrieval_client.service.getDdsInfo
        )
        self.get_dds_info_by_internal_reference_number = (
            self.retrieval_client.service.getDdsInfoByInternalReferenceNumber
        )
        self.get_statement_by_identifiers = (
            self.retrieval_client.service.getStatementByIdentifiers
        )
        self.amend_dds = self.submission_client.service.amendDds
        self.retract_dds = self.submission_client.service.retractDds
        self.submit_dds = self.submission_client.service.submitDds

        types = {
            dynamic_type.__class__.__name__: dynamic_type
            for dynamic_type in self.submission_client.wsdl.types.types
        }
        types.update(
            {
                dynamic_type.__class__.__name__: dynamic_type
                for dynamic_type in self.retrieval_client.wsdl.types.types
            }
        )
        self.types = type(
            "Types",
            (object,),
            types,
        )

    def authenticate(
        self,
        *,
        username: str,
        authentication_key: str,
        client_id: t.Optional[str] = None,
    ) -> "Client":
        kwargs = {
            "username": username,
            "authentication_key": authentication_key,
            "client_id": client_id,
        }
        self.echo_client.authenticate(**kwargs)
        self.retrieval_client.authenticate(**kwargs)
        self.submission_client.authenticate(**kwargs)
        return self

    @contextmanager
    def authenticated(
        self,
        *,
        username: str,
        authentication_key: str,
        client_id: t.Optional[str] = None,
    ):
        with self.echo_client.authenticated(
            username=username,
            authentication_key=authentication_key,
            client_id=client_id,
        ), self.retrieval_client.authenticated(
            username=username,
            authentication_key=authentication_key,
            client_id=client_id,
        ), self.submission_client.authenticated(
            username=username,
            authentication_key=authentication_key,
            client_id=client_id,
        ):
            yield self


def _collect_types(client: EchoClient) -> type:
    """Collect WSDL types of a single service into a class, keyed by type name.

    A service may define types with the same name in different namespaces (e.g. `CountryType` in both TRACES base
    and EUDR common schemas). In that case the EUDR one is kept, as that is what EUDR payloads use. The other one is
    still available with `client.get_type("{namespace}Name")`.
    """
    types = {}
    for dynamic_type in client.wsdl.types.types:
        name = dynamic_type.__class__.__name__
        if name in types and not dynamic_type.qname.namespace.startswith(
            EUDR_NAMESPACE_PREFIX
        ):
            continue
        types[name] = dynamic_type
    return type("Types", (object,), types)


class ClientV3:
    def __init__(
        self,
        *,
        test: bool = True,
    ):
        self.echo_client = EchoClient(test=test)
        self.dds_client = DueDiligenceStatementClientV3(test=test)
        self.sd_client = SimplifiedDeclarationClientV3(test=test)
        self.verify_client = VerifyDeclarationClientV3(test=test)

        self.test_echo: t.Callable[[str], str] = self.echo_client.service.testEcho

        self.submit_dds = self.dds_client.service.submitDds
        self.amend_dds = self.dds_client.service.amendDds
        self.withdraw_dds = self.dds_client.service.withdrawDds
        self.get_dds = self.dds_client.service.getDds
        self.get_dds_by_internal_reference = (
            self.dds_client.service.getDdsByInternalReference
        )
        self.get_dds_by_identifiers = self.dds_client.service.getDdsByIdentifiers

        self.submit_sd = self.sd_client.service.submitSd
        self.update_sd = self.sd_client.service.updateSd
        self.withdraw_sd = self.sd_client.service.withdrawSd
        self.get_sd = self.sd_client.service.getSd
        self.get_sd_by_internal_reference = (
            self.sd_client.service.getSdByInternalReference
        )
        self.get_sd_by_identifiers = self.sd_client.service.getSdByIdentifiers

        self.verify_declaration = self.verify_client.service.verifyDeclaration

        # Types are kept per service, as merging them would silently replace same-named types from other services.
        self.types = type(
            "Types",
            (object,),
            {
                "dds": _collect_types(self.dds_client),
                "sd": _collect_types(self.sd_client),
                "verify": _collect_types(self.verify_client),
            },
        )

    @property
    def _clients(self) -> t.Tuple[EchoClient, ...]:
        return (self.echo_client, self.dds_client, self.sd_client, self.verify_client)

    def authenticate(
        self,
        *,
        username: str,
        authentication_key: str,
        client_id: t.Optional[str] = None,
    ) -> "ClientV3":
        for client in self._clients:
            client.authenticate(
                username=username,
                authentication_key=authentication_key,
                client_id=client_id,
            )
        return self

    @contextmanager
    def authenticated(
        self,
        *,
        username: str,
        authentication_key: str,
        client_id: t.Optional[str] = None,
    ):
        with ExitStack() as stack:
            for client in self._clients:
                stack.enter_context(
                    client.authenticated(
                        username=username,
                        authentication_key=authentication_key,
                        client_id=client_id,
                    )
                )
            yield self
