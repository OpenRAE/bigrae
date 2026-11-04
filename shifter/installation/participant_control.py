"""Explicit deployment intent for the fixed native participant-control worker."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, StrictBool, model_validator
from shared.participant_control_installation import NativeControlInstallation, NativeControlLimits

ResourceName = Annotated[str, Field(max_length=253, pattern=r"^$|^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")]


class ParticipantControlSettings(NativeControlLimits):
    """Operator-owned TLS, storage and limits; images come from the verified release."""

    enabled: StrictBool = False
    tls_secret_name: ResourceName = ""
    trust_ca_pem: str = Field(default="", max_length=16_384, repr=False)
    storage_class_name: ResourceName = ""
    storage_gib: int = Field(default=8, ge=1, le=128)

    @model_validator(mode="after")
    def validate_explicit_installation(self) -> ParticipantControlSettings:
        """Require complete public trust and transport references only when enabled."""
        if self.enabled:
            if not self.tls_secret_name or not self.trust_ca_pem:
                raise ValueError("Participant control requires a TLS Secret reference and public trust CA")
            NativeControlInstallation.public_certificate_bundle(self.trust_ca_pem)
        elif self.tls_secret_name or self.trust_ca_pem or self.storage_class_name:
            raise ValueError("Disabled participant control cannot carry active transport or storage references")
        return self


def project_participant_control(
    raw: object,
    *,
    namespace: str,
    owner_image: str,
    provisioner_image: str,
) -> tuple[dict[str, object], dict[str, str]]:
    """Bind runtime configuration to actual deployment coordinates, never process-local overrides."""
    policy = ParticipantControlSettings.model_validate(raw if raw is not None else {})
    environment = {
        "PARTICIPANT_CONTROL_ENABLED": "false",
        "PARTICIPANT_CONTROL_OWNER_PROCESS": "false",
        "PARTICIPANT_CONTROL_CONFIGURATION": "",
    }
    if not policy.enabled:
        return {"enabled": False}, environment
    installation = NativeControlInstallation(
        protocol="shifter-native-power-installation/v1",
        namespace=namespace,
        owner_image=owner_image,
        provisioner_image=provisioner_image,
        trust_ca_pem=policy.trust_ca_pem,
        max_contexts=policy.max_contexts,
        idle_seconds=policy.idle_seconds,
        budgets=policy.budgets,
    )
    environment.update(
        PARTICIPANT_CONTROL_ENABLED="true",
        PARTICIPANT_CONTROL_CONFIGURATION=installation.model_dump_json(),
    )
    return {
        "enabled": True,
        "configuration": installation.model_dump_json(),
        "tlsSecretName": policy.tls_secret_name,
        "storageClassName": policy.storage_class_name,
        "storageGiB": policy.storage_gib,
    }, environment
