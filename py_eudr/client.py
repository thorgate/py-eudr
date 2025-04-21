import typing as t
from contextlib import contextmanager

from py_eudr.base import EchoClient, RetrievalClient, SubmissionClient


class Client:
    def __init__(
        self,
    ):
        self.echo_client = EchoClient()
        self.retrieval_client = RetrievalClient()
        self.submission_client = SubmissionClient()

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
        client_id: str,
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
        client_id: str,
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
