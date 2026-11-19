import typing as t
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from typing import Mapping

import requests
from zeep import Plugin
from zeep.exceptions import Fault
from zeep.settings import Settings
from zeep.transports import Transport

from py_eudr.base import (
    DueDiligenceStatementClientV3,
    DueDiligenceStatementClientV4,
    EchoClient,
    ServiceClient,
    SimplifiedDeclarationClientV3,
    SimplifiedDeclarationClientV4,
    VerifyDeclarationClientV3,
    VerifyDeclarationClientV4,
    default_settings,
    warn_on_replaced_credentials,
)
from py_eudr.exceptions import translate_fault
from py_eudr.transport import make_transport

if t.TYPE_CHECKING:
    from py_eudr.types import v3, v4

EUDR_NAMESPACE_PREFIX = "http://ec.europa.eu/tracesnt/certificate/eudr/"

_BODY_IDENTITY_ELEMENTS = {
    "operator": "OperatorAccessIdentifier",
    "authority_activity": "AuthorityActivityAccessIdentifier",
    "organic_control_body": "OrganicControlBodyAccessIdentifier",
    "other_body": "OtherBodyAccessIdentifier",
}


@dataclass(frozen=True)
class BodyIdentity:
    """Value of the ``BodyIdentity`` SOAP header (exactly one identifier).

    ``OperatorAccessIdentifier`` (``operator``) is the only kind accepted by the EUDR
    endpoints. Methods also accept a plain string, meaning an operator identifier.
    """

    operator: t.Optional[str] = None
    authority_activity: t.Optional[str] = None
    organic_control_body: t.Optional[str] = None
    other_body: t.Optional[str] = None

    def __post_init__(self) -> None:
        given = [name for name in _BODY_IDENTITY_ELEMENTS if getattr(self, name)]
        if len(given) != 1:
            raise ValueError("BodyIdentity requires exactly one identifier")

    def to_header(self) -> t.Dict[str, str]:
        return {
            element: getattr(self, name)
            for name, element in _BODY_IDENTITY_ELEMENTS.items()
            if getattr(self, name)
        }


BodyIdentityArg = t.Union[BodyIdentity, str, None]


def _collect_types(client: ServiceClient) -> type:
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


def _soapheaders(body_identity: BodyIdentityArg) -> t.Dict[str, t.Any]:
    if body_identity is None:
        return {}
    if isinstance(body_identity, str):
        body_identity = BodyIdentity(operator=body_identity)
    return {"_soapheaders": {"bodyIdentity": body_identity.to_header()}}


def _as_list(items: t.Any) -> t.List[t.Any]:
    if isinstance(items, (str, bytes)):
        raise TypeError("Expected a sequence of UUIDs, not a single string")
    return list(items)


def _uuid_and_version(item: t.Any) -> t.Any:
    if isinstance(item, str):
        return {"uuid": item}
    if isinstance(item, (tuple, list)):
        if len(item) == 2 and isinstance(item[0], str):
            return {"uuid": item[0], "versionNumber": item[1]}
    elif isinstance(item, Mapping) or hasattr(item, "uuid"):
        return item
    raise TypeError(
        "get_sd() items must be a UUID string, a (uuid, version_number) pair, a "
        f"UuidAndVersionNumberType or a dict, not {item!r}"
    )


class _VersionedClient:
    """Shared implementation of :class:`ClientV3` and :class:`ClientV4`.

    Both API versions have the same 13 operations; only namespaces and some types differ.
    Version specific signatures are declared for type checkers on the subclasses.
    """

    dds_client_class: t.Type[ServiceClient]
    sd_client_class: t.Type[ServiceClient]
    verify_client_class: t.Type[ServiceClient]

    def __init__(
        self,
        *,
        test: bool = True,
        vendored_schemas: bool = True,
        operation_timeout: t.Optional[float] = 60,
        timeout: float = 300,
        session: t.Optional[requests.Session] = None,
        transport: t.Optional[Transport] = None,
        settings: t.Optional[Settings] = None,
        plugins: t.Sequence[Plugin] = (),
    ):
        """
        :param test: use the acceptance environment (``False``: production).
        :param vendored_schemas: load WSDL/XSD files from the package (default) or,
            with ``False``, from the server.
        :param operation_timeout: timeout of SOAP calls in seconds.
        :param timeout: timeout of loading WSDL/XSD files (``vendored_schemas=False``).
        :param session: :class:`requests.Session` providing the HTTP configuration
            (proxies, TLS, retry adapters, ...). It is copied, not modified; the copy
            is shared by the four service clients.
        :param transport: zeep transport shared by the service clients, replacing
            ``vendored_schemas``, ``operation_timeout`` and ``timeout`` (``session``
            can not be combined with it).
            A plain :class:`zeep.transports.Transport` loads the definitions from the
            network; use :func:`py_eudr.transport.make_transport` to keep vendored ones.
        :param settings: zeep settings; defaults to ``Settings(strict=False)`` so that
            new optional elements in responses are tolerated (malformed responses are
            still rejected by the transport).
        :param plugins: zeep plugins, applied after the authentication check.
        """
        self._test = test
        if transport is None:
            transport = make_transport(
                vendored_schemas=vendored_schemas,
                timeout=timeout,
                operation_timeout=operation_timeout,
                session=session,
            )
        elif session is not None:
            raise ValueError("Pass either session or transport, not both")
        self.transport = transport
        options: t.Dict[str, t.Any] = {
            "test": test,
            "transport": transport,
            "settings": settings or default_settings(),
            "plugins": plugins,
        }
        self.echo_client = EchoClient(**options)
        self.dds_client = self.dds_client_class(**options)
        self.sd_client = self.sd_client_class(**options)
        self.verify_client = self.verify_client_class(**options)

        # Types are kept per service, as merging them would silently replace same-named types from other services.
        self.types: t.Any = type(
            "Types",
            (object,),
            {
                "dds": _collect_types(self.dds_client),
                "sd": _collect_types(self.sd_client),
                "verify": _collect_types(self.verify_client),
            },
        )

    @property
    def test(self) -> bool:
        """``True`` for the acceptance environment (read-only)."""
        return self._test

    @property
    def _clients(self) -> t.Tuple[ServiceClient, ...]:
        return (self.echo_client, self.dds_client, self.sd_client, self.verify_client)

    def authenticate(
        self,
        *,
        username: str,
        authentication_key: str,
        client_id: t.Optional[str] = None,
    ) -> t.Any:
        """Set the credentials of this client instance, shared by all threads and tasks.

        Nothing is stored in the current context; :meth:`authenticated` overrides
        these credentials. For concurrent requests on behalf of different users use
        :meth:`authenticated`; a :class:`RuntimeWarning` is emitted when different
        credentials replace already-set ones.
        """
        warn_on_replaced_credentials(
            self.echo_client, username, authentication_key, client_id
        )
        for client in self._clients:
            client._set_credentials(
                username=username,
                authentication_key=authentication_key,
                client_id=client_id,
            )
        return self

    def authenticated(
        self,
        *,
        username: str,
        authentication_key: str,
        client_id: t.Optional[str] = None,
    ) -> t.ContextManager[t.Any]:
        """Use the given credentials inside the ``with`` block (thread and async safe).

        Credentials are kept in context variables, so one client instance can be shared
        between threads and asyncio tasks using different credentials.
        """
        return self._authenticated(
            username=username,
            authentication_key=authentication_key,
            client_id=client_id,
        )

    @contextmanager
    def _authenticated(
        self,
        *,
        username: str,
        authentication_key: str,
        client_id: t.Optional[str] = None,
    ) -> t.Iterator[t.Any]:
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

    @staticmethod
    def _call(client: ServiceClient, operation: str, **kwargs: t.Any) -> t.Any:
        try:
            return getattr(client.service, operation)(**kwargs)
        except Fault as fault:
            translated = translate_fault(fault)
            if translated is fault:
                raise
            raise translated from fault

    # Echo

    def test_echo(self, query: str) -> str:
        """Call the echo service; returns the echoed status string."""
        return self._call(self.echo_client, "testEcho", query=query)

    # Due Diligence Statements

    def submit_dds(
        self,
        operator_role: t.Any,
        statement: t.Any,
        *,
        body_identity: BodyIdentityArg = None,
    ) -> str:
        """Submit a Due Diligence Statement; returns its UUID.

        ``operator_role`` is ``"OPERATOR"`` or ``"REPRESENTATIVE_OPERATOR"``.
        """
        return self._call(
            self.dds_client,
            "submitDds",
            operatorRole=operator_role,
            statement=statement,
            **_soapheaders(body_identity),
        )

    def amend_dds(
        self, uuid: str, statement: t.Any, *, body_identity: BodyIdentityArg = None
    ) -> t.Any:
        """Amend a DDS (within the amendment window); returns its new status."""
        return self._call(
            self.dds_client,
            "amendDds",
            uuid=uuid,
            statement=statement,
            **_soapheaders(body_identity),
        )

    def withdraw_dds(
        self, uuid: str, *, body_identity: BodyIdentityArg = None
    ) -> t.Any:
        """Withdraw a DDS (within the amendment window); returns its new status."""
        return self._call(
            self.dds_client, "withdrawDds", uuid=uuid, **_soapheaders(body_identity)
        )

    def get_dds(
        self, uuids: t.Sequence[str], *, body_identity: BodyIdentityArg = None
    ) -> t.List[t.Any]:
        """Return the overview (status, reference and verification number) of DDSs."""
        uuids = _as_list(uuids)
        if not uuids:
            return []
        result = self._call(
            self.dds_client,
            "getDds",
            uuidList=uuids,
            **_soapheaders(body_identity),
        )
        return list(result or [])

    def get_dds_by_internal_reference(
        self, internal_reference: str, *, body_identity: BodyIdentityArg = None
    ) -> t.List[t.Any]:
        """Return the overview of DDSs with the given internal reference number."""
        result = self._call(
            self.dds_client,
            "getDdsByInternalReference",
            internalReference=internal_reference,
            **_soapheaders(body_identity),
        )
        return list(result or [])

    def get_dds_by_identifiers(
        self,
        reference_number: str,
        verification_number: str,
        *,
        body_identity: BodyIdentityArg = None,
    ) -> t.Any:
        """Retrieve a DDS by reference and verification number.

        The server no longer returns statement content over the API: this always
        raises :class:`py_eudr.exceptions.NotFoundError` (kept for API compatibility).
        """
        return self._call(
            self.dds_client,
            "getDdsByIdentifiers",
            referenceAndVerificationNumber={
                "referenceNumber": reference_number,
                "verificationNumber": verification_number,
            },
            **_soapheaders(body_identity),
        )

    # Simplified Declarations

    def submit_sd(
        self,
        operator_role: t.Any,
        statement: t.Any,
        *,
        body_identity: BodyIdentityArg = None,
    ) -> str:
        """Submit a Simplified Declaration; returns its identifier (UUID).

        ``operator_role`` is ``"MICRO_OPERATOR"``, ``"REPRESENTATIVE_MSPO"`` or
        ``"MEMBER_STATE"``.
        """
        return self._call(
            self.sd_client,
            "submitSd",
            operatorRole=operator_role,
            statement=statement,
            **_soapheaders(body_identity),
        )

    def update_sd(
        self,
        sd_identifier: str,
        statement: t.Any,
        *,
        body_identity: BodyIdentityArg = None,
    ) -> t.Any:
        """Update a Simplified Declaration; returns its new version and status."""
        return self._call(
            self.sd_client,
            "updateSd",
            sdIdentifier=sd_identifier,
            statement=statement,
            **_soapheaders(body_identity),
        )

    def withdraw_sd(
        self, sd_identifier: str, *, body_identity: BodyIdentityArg = None
    ) -> t.Any:
        """Withdraw a Simplified Declaration; returns its new status."""
        return self._call(
            self.sd_client,
            "withdrawSd",
            sdIdentifier=sd_identifier,
            **_soapheaders(body_identity),
        )

    def get_sd(
        self, uuids: t.Sequence[t.Any], *, body_identity: BodyIdentityArg = None
    ) -> t.List[t.Any]:
        """Return the overview of Simplified Declarations.

        Each item is a UUID string, a ``(uuid, version_number)`` tuple, or a
        ``UuidAndVersionNumberType``/dict.
        """
        uuids = _as_list(uuids)
        if not uuids:
            return []
        result = self._call(
            self.sd_client,
            "getSd",
            uuidAndVersionNumberList=[_uuid_and_version(item) for item in uuids],
            **_soapheaders(body_identity),
        )
        return list(result or [])

    def get_sd_by_internal_reference(
        self, internal_reference: str, *, body_identity: BodyIdentityArg = None
    ) -> t.List[t.Any]:
        """Return the overview of SDs with the given internal reference number."""
        result = self._call(
            self.sd_client,
            "getSdByInternalReference",
            internalReference=internal_reference,
            **_soapheaders(body_identity),
        )
        return list(result or [])

    def get_sd_by_identifiers(
        self,
        reference_number: str,
        verification_number: str,
        *,
        body_identity: BodyIdentityArg = None,
    ) -> t.Any:
        """Retrieve an SD by reference and verification number.

        The server no longer returns declaration content over the API: this always
        raises :class:`py_eudr.exceptions.NotFoundError` (kept for API compatibility).
        """
        return self._call(
            self.sd_client,
            "getSdByIdentifiers",
            referenceAndVerificationNumber={
                "referenceNumber": reference_number,
                "verificationNumber": verification_number,
            },
            **_soapheaders(body_identity),
        )

    # Verification

    def verify_declaration(
        self, reference_number: str, verification_number: str
    ) -> t.Any:
        """Verify a DDS or SD by its reference and verification number.

        Returns ``result`` (e.g. ``EXISTING_USABLE``, ``NON_EXISTENT``), ``status`` and
        ``dateTime``.
        """
        return self._call(
            self.verify_client,
            "verifyDeclaration",
            referenceNumber=reference_number,
            verificationNumber=verification_number,
        )


class ClientV3(_VersionedClient):
    """Client of the EUDR API V3 (DDS, SD and Verify services)."""

    dds_client_class = DueDiligenceStatementClientV3
    sd_client_class = SimplifiedDeclarationClientV3
    verify_client_class = VerifyDeclarationClientV3

    if t.TYPE_CHECKING:
        types: v3.V3Types

        def authenticate(
            self,
            *,
            username: str,
            authentication_key: str,
            client_id: t.Optional[str] = None,
        ) -> "ClientV3": ...
        def authenticated(
            self,
            *,
            username: str,
            authentication_key: str,
            client_id: t.Optional[str] = None,
        ) -> t.ContextManager["ClientV3"]: ...
        def submit_dds(
            self,
            operator_role: "v3.OperatorRoleType",
            statement: "v3.DueDiligenceStatementBaseType | v3._Dict",
            *,
            body_identity: BodyIdentityArg = None,
        ) -> str: ...
        def amend_dds(
            self,
            uuid: str,
            statement: "v3.DueDiligenceStatementBaseType | v3._Dict",
            *,
            body_identity: BodyIdentityArg = None,
        ) -> "v3.DdsModificationResponseType": ...
        def withdraw_dds(
            self, uuid: str, *, body_identity: BodyIdentityArg = None
        ) -> "v3.DdsModificationResponseType": ...
        def get_dds(
            self, uuids: t.Sequence[str], *, body_identity: BodyIdentityArg = None
        ) -> t.List["v3.OverviewType"]: ...
        def get_dds_by_internal_reference(
            self, internal_reference: str, *, body_identity: BodyIdentityArg = None
        ) -> t.List["v3.OverviewType"]: ...
        def get_dds_by_identifiers(
            self,
            reference_number: str,
            verification_number: str,
            *,
            body_identity: BodyIdentityArg = None,
        ) -> "v3.DueDiligenceStatementBaseType": ...
        def submit_sd(
            self,
            operator_role: "v3.SdOperatorRoleType",
            statement: "v3.SimplifiedDeclarationBaseType | v3._Dict",
            *,
            body_identity: BodyIdentityArg = None,
        ) -> str: ...
        def update_sd(
            self,
            sd_identifier: str,
            statement: "v3.SimplifiedDeclarationBaseType | v3._Dict",
            *,
            body_identity: BodyIdentityArg = None,
        ) -> "v3.SdModificationResponseType": ...
        def withdraw_sd(
            self, sd_identifier: str, *, body_identity: BodyIdentityArg = None
        ) -> "v3.SdModificationResponseType": ...
        def get_sd(
            self,
            uuids: t.Sequence[
                "str | t.Tuple[str, int] | t.List[str | int] | v3.UuidAndVersionNumberType | v3._Dict"
            ],
            *,
            body_identity: BodyIdentityArg = None,
        ) -> t.List["v3.OverviewType"]: ...
        def get_sd_by_internal_reference(
            self, internal_reference: str, *, body_identity: BodyIdentityArg = None
        ) -> t.List["v3.OverviewType"]: ...
        def get_sd_by_identifiers(
            self,
            reference_number: str,
            verification_number: str,
            *,
            body_identity: BodyIdentityArg = None,
        ) -> "v3.SimplifiedDeclarationBaseType": ...
        def verify_declaration(
            self, reference_number: str, verification_number: str
        ) -> "v3.VerifyDeclarationResponseType": ...


class ClientV4(_VersionedClient):
    """Client of the EUDR API V4 (DDS, SD and Verify services)."""

    dds_client_class = DueDiligenceStatementClientV4
    sd_client_class = SimplifiedDeclarationClientV4
    verify_client_class = VerifyDeclarationClientV4

    if t.TYPE_CHECKING:
        types: v4.V4Types

        def authenticate(
            self,
            *,
            username: str,
            authentication_key: str,
            client_id: t.Optional[str] = None,
        ) -> "ClientV4": ...
        def authenticated(
            self,
            *,
            username: str,
            authentication_key: str,
            client_id: t.Optional[str] = None,
        ) -> t.ContextManager["ClientV4"]: ...
        def submit_dds(
            self,
            operator_role: "v4.OperatorRoleType",
            statement: "v4.DueDiligenceStatementBaseType | v4._Dict",
            *,
            body_identity: BodyIdentityArg = None,
        ) -> str: ...
        def amend_dds(
            self,
            uuid: str,
            statement: "v4.DueDiligenceStatementBaseType | v4._Dict",
            *,
            body_identity: BodyIdentityArg = None,
        ) -> "v4.DdsModificationResponseType": ...
        def withdraw_dds(
            self, uuid: str, *, body_identity: BodyIdentityArg = None
        ) -> "v4.DdsModificationResponseType": ...
        def get_dds(
            self, uuids: t.Sequence[str], *, body_identity: BodyIdentityArg = None
        ) -> t.List["v4.OverviewType"]: ...
        def get_dds_by_internal_reference(
            self, internal_reference: str, *, body_identity: BodyIdentityArg = None
        ) -> t.List["v4.OverviewType"]: ...
        def get_dds_by_identifiers(
            self,
            reference_number: str,
            verification_number: str,
            *,
            body_identity: BodyIdentityArg = None,
        ) -> "v4.DueDiligenceStatementBaseType": ...
        def submit_sd(
            self,
            operator_role: "v4.SdOperatorRoleType",
            statement: "v4.SimplifiedDeclarationBaseType | v4._Dict",
            *,
            body_identity: BodyIdentityArg = None,
        ) -> str: ...
        def update_sd(
            self,
            sd_identifier: str,
            statement: "v4.SimplifiedDeclarationBaseType | v4._Dict",
            *,
            body_identity: BodyIdentityArg = None,
        ) -> "v4.SdModificationResponseType": ...
        def withdraw_sd(
            self, sd_identifier: str, *, body_identity: BodyIdentityArg = None
        ) -> "v4.SdModificationResponseType": ...
        def get_sd(
            self,
            uuids: t.Sequence[
                "str | t.Tuple[str, int] | t.List[str | int] | v4.UuidAndVersionNumberType | v4._Dict"
            ],
            *,
            body_identity: BodyIdentityArg = None,
        ) -> t.List["v4.OverviewType"]: ...
        def get_sd_by_internal_reference(
            self, internal_reference: str, *, body_identity: BodyIdentityArg = None
        ) -> t.List["v4.OverviewType"]: ...
        def get_sd_by_identifiers(
            self,
            reference_number: str,
            verification_number: str,
            *,
            body_identity: BodyIdentityArg = None,
        ) -> "v4.SimplifiedDeclarationBaseType": ...
        def verify_declaration(
            self, reference_number: str, verification_number: str
        ) -> "v4.VerifyDeclarationResponseType": ...
