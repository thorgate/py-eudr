import typing as t

from lxml import etree
from zeep.exceptions import Fault


class EUDRError(Exception):
    """Base class of py-eudr errors.

    zeep's own errors (``zeep.exceptions.ValidationError`` for invalid values before
    sending, ``TransportError`` for non-SOAP HTTP errors, ``XMLSyntaxError``) are not
    part of this hierarchy; ``zeep.exceptions.Error`` catches those and every
    :class:`EUDRFault`.
    """


class ErrorDetail(t.NamedTuple):
    """One ``error:Error`` entry of an EUDR fault."""

    id: str
    message: str
    field: str


class EUDRFault(EUDRError, Fault):
    """A SOAP fault returned by an EUDR service.

    Subclasses :class:`zeep.exceptions.Fault`, so ``except Fault`` keeps working.
    ``errors`` lists the ``ID``/``Message``/``Field`` entries of the fault detail.
    """

    def __init__(self, *args: t.Any, **kwargs: t.Any) -> None:
        super().__init__(*args, **kwargs)
        self.errors: t.List[ErrorDetail] = parse_errors(self.detail)

    @classmethod
    def from_fault(cls, fault: Fault) -> "EUDRFault":
        return cls(
            fault.message,
            code=fault.code,
            actor=fault.actor,
            detail=fault.detail,
            subcodes=fault.subcodes,
        )

    def __str__(self) -> str:
        return str(self.message)


class BusinessRulesError(EUDRFault):
    """``BusinessRulesValidationException``: the request violates a business rule."""


class PermissionDeniedError(EUDRFault):
    """``PermissionDeniedException``: the user may not perform the operation."""


class NotFoundError(EUDRFault):
    """``NotFoundException``: the requested statement does not exist or is not accessible."""


FAULT_CLASSES: t.Dict[str, t.Type[EUDRFault]] = {
    "BusinessRulesValidationException": BusinessRulesError,
    "PermissionDeniedException": PermissionDeniedError,
    "NotFoundException": NotFoundError,
}


def _local_name(node: t.Any) -> str:
    return etree.QName(node).localname if isinstance(node.tag, str) else ""


def parse_errors(detail: t.Any) -> t.List[ErrorDetail]:
    # zeep sets `detail` to the raw response bytes for non-SOAP error responses.
    if not etree.iselement(detail):
        return []
    errors = []
    for node in detail.iter():
        if _local_name(node) != "Error":
            continue
        values = {_local_name(child): (child.text or "").strip() for child in node}
        errors.append(
            ErrorDetail(
                id=values.get("ID", ""),
                message=values.get("Message", ""),
                field=values.get("Field", ""),
            )
        )
    return errors


def translate_fault(fault: Fault) -> Fault:
    """Return the matching :class:`EUDRFault` subclass for a zeep fault, or the
    fault itself when its detail is not a known EUDR exception."""
    if isinstance(fault, EUDRFault) or not etree.iselement(fault.detail):
        return fault
    for child in fault.detail:
        cls = FAULT_CLASSES.get(_local_name(child))
        if cls is not None:
            return cls.from_fault(fault)
    return fault
