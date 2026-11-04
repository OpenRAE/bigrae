"""Closed native installation identity, independent of Django and portable semantics."""

from __future__ import annotations

import base64
import hashlib
import json
import ssl
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_DNS_LABEL = r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$"
# Keep the deployment image grammar aligned with the existing preparation grant.
_IMAGE_DIGEST = (
    r"^[a-z0-9][a-z0-9.-]+(?::[0-9]{1,5})?/(?:[a-z0-9]+(?:[._-][a-z0-9]+)*/)*"
    r"[a-z0-9]+(?:[._-][a-z0-9]+)*@sha256:[a-f0-9]{64}$"
)


class NativeControlBudgets(BaseModel):
    """Finite installed durations; SDK admission and lifecycle semantics remain upstream-owned."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, hide_input_in_errors=True)

    admission_ms: int = Field(default=10_000, ge=100, le=60_000)
    execution_ms: int = Field(default=30_000, ge=100, le=120_000)
    observation_ms: int = Field(default=2_000, ge=100, le=60_000)
    commit_ms: int = Field(default=10_000, ge=100, le=60_000)
    drain_ms: int = Field(default=5_000, ge=100, le=30_000)


class NativeControlLimits(BaseModel):
    """Shared finite owner capacity and operation limits for deployment and runtime."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, hide_input_in_errors=True)

    max_contexts: int = Field(default=8, ge=1, le=32)
    idle_seconds: int = Field(default=300, ge=30, le=3600)
    budgets: NativeControlBudgets = Field(default_factory=NativeControlBudgets)


class NativeControlInstallation(NativeControlLimits):
    """Exact deployment images, protected storage and native worker capacity."""

    protocol: Literal["shifter-native-power-installation/v1"]
    namespace: Annotated[str, Field(max_length=63, pattern=_DNS_LABEL)]
    owner_image: Annotated[str, Field(max_length=1024, pattern=_IMAGE_DIGEST)]
    provisioner_image: Annotated[str, Field(max_length=1024, pattern=_IMAGE_DIGEST)]
    trust_ca_pem: str = Field(min_length=1, max_length=16_384, repr=False)

    @field_validator("trust_ca_pem")
    @classmethod
    def public_certificate_bundle(cls, value: str) -> str:
        """Admit only public PEM certificates, with bounded standard TLS validation."""
        try:
            blocks = value.split("-----END CERTIFICATE-----")
            if len(blocks) < 2 or blocks[-1].strip():
                raise ValueError
            header = "-----BEGIN CERTIFICATE-----"
            for block in blocks[:-1]:
                certificate = block.strip()
                if not certificate.startswith(header) or not base64.b64decode(
                    "".join(certificate[len(header) :].split()), validate=True
                ):
                    raise ValueError
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.load_verify_locations(cadata=value)
        except (ValueError, ssl.SSLError):
            raise ValueError("Participant control trust requires only public PEM certificates") from None
        return value

    @property
    def control_origin(self) -> str:
        """The namespace selects only this fixed private service, never an arbitrary URL."""
        return f"https://participant-control.{self.namespace}.svc:8445"

    @property
    def store_root(self) -> Path:
        """Fixed protected mount, distinct from temporary, participant or pack storage."""
        return Path("/var/lib/shifter/participant-control")

    @property
    def digest(self) -> str:
        """Use the native canonical JSON digest profile for the entire installation."""
        return _digest(self.model_dump(mode="json"))

    @property
    def policy_digest(self) -> str:
        """Pin control semantics and budgets independently of compatible deployment changes."""
        return _digest({"protocol": "shifter-native-power-policy/v1", "budgets": self.budgets.model_dump(mode="json")})


def _digest(value: dict[str, object]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()
