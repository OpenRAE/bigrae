"""Native compiler references, separate from portable runtime state."""

from uuid import uuid4

from django.db import models

from shared.field_encryption import EncryptedStringField


class RaesCompilerInputBinding(models.Model):
    """Retain one compilation selection for an exact resource incarnation and custody."""

    binding_ref = models.UUIDField(default=uuid4, unique=True, editable=False)
    range = models.ForeignKey("engine.Range", on_delete=models.CASCADE, related_name="compiler_input_bindings")
    resource_generation = models.UUIDField(editable=False)
    scope_digest = models.CharField(max_length=71, editable=False)
    source_package_digest = models.CharField(max_length=71, editable=False)
    compiler_input_digest = models.CharField(max_length=71, editable=False)
    raes_version = models.CharField(max_length=64, editable=False)
    parameters_json = EncryptedStringField(default="", editable=False)
    artifact_planning_json = EncryptedStringField(default="", editable=False)
    participant_references = models.JSONField(default=list, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "engine_raes_compiler_input_binding"
        constraints = [
            models.UniqueConstraint(
                fields=["range", "resource_generation", "scope_digest"], name="engine_compiler_input_scope_unique"
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(scope_digest__regex=r"^sha256:[0-9a-f]{64}$")
                    & models.Q(source_package_digest__regex=r"^sha256:[0-9a-f]{64}$")
                    & models.Q(compiler_input_digest__regex=r"^sha256:[0-9a-f]{64}$")
                ),
                name="engine_compiler_input_digests_valid",
            ),
        ]

    def __str__(self) -> str:
        """Expose only the opaque binding reference in model displays."""
        return str(self.binding_ref)
