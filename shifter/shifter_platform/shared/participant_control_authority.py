"""Product-owned subject admission, without portable or persistence authority."""

from collections.abc import Callable
from dataclasses import dataclass, field
from uuid import UUID

from shared.credentials import CredentialContext


@dataclass(frozen=True, slots=True)
class NativeParticipantSubject:
    """Exact product assignment; names, source references and ownership grant nothing."""

    product: str
    subject_uuid: UUID
    event_uuid: UUID
    range_instance_pk: int


@dataclass(frozen=True, slots=True)
class NativeParticipantSubjectAdmission:
    """Invocation-local authority whose product fence precedes CMS/Engine locks."""

    subject: NativeParticipantSubject
    credential: CredentialContext = field(repr=False)
    _fence: Callable[[], None] = field(repr=False)

    def fence(self) -> None:
        """Keep product faults behind a bounded native admission boundary."""
        try:
            self._fence()
        except Exception:  # noqa: BLE001  # only the product owner interprets its private faults
            raise ValueError("Participant subject unavailable") from None


SubjectAdmitter = Callable[[CredentialContext, UUID], NativeParticipantSubjectAdmission]
_admitters: dict[str, SubjectAdmitter] = {}


def register_participant_subject_admitter(product: str, admitter: SubjectAdmitter) -> None:
    """Only application startup installs product owners; conflicting bindings fail."""
    if not product or not callable(admitter) or (product in _admitters and _admitters[product] is not admitter):
        raise ValueError("Participant subject authority already bound")
    _admitters[product] = admitter


def admit_participant_subject(
    credential: CredentialContext, product: str, subject_uuid: UUID
) -> NativeParticipantSubjectAdmission:
    """Require the real product owner and its exact native initiating credential."""
    try:
        admission = _admitters[product](credential, subject_uuid)
        if (
            admission.credential != credential
            or admission.subject.product != product
            or admission.subject.subject_uuid != subject_uuid
        ):
            raise ValueError("Participant subject changed")
        return admission
    except Exception:  # noqa: BLE001  # do not disclose product membership or policy faults
        raise ValueError("Participant subject unavailable") from None
