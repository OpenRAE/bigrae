"""Original selected artifact bytes retain the existing credential boundary."""

import base64
import json

import pytest
from raes_contracts.associated_artifacts import associated_artifact_set_digest
from raes_contracts.contracts import AssociatedArtifactManifestModel

from shared.raes.experiment_admission import _ArtifactCustody
from tests.cms.conftest import write_pack_content_manifest


@pytest.mark.parametrize("sensitive", [False, True])
@pytest.mark.parametrize("array", [False, True])
def test_structured_prompt_content_preserves_planted_credentials(make_pack, tmp_path, sensitive, array):
    root = make_pack(tmp_path / "scientific-artifact")
    document = {"api_key": "sensitive-material"} if sensitive else {"instruction": "Report confirmed findings."}
    if array:
        document = [document]
    original = json.dumps(document, indent=2).encode()
    (root / "prompt.json").write_bytes(original)
    write_pack_content_manifest(root, root.name)
    path = root / "associated-artifacts.json"
    manifest = AssociatedArtifactManifestModel.model_validate_json(path.read_bytes())
    artifact_id = next(key for key, item in manifest.artifacts.items() if item.uri.endswith("/prompt.json"))
    descriptor = manifest.artifacts[artifact_id].model_copy(update={"media_type": "application/json"})
    manifest.artifacts[artifact_id] = descriptor
    manifest = manifest.model_copy(update={"set_digest": associated_artifact_set_digest(manifest)})
    path.write_text(manifest.model_dump_json())
    custody = _ArtifactCustody(root)
    custody.retain([descriptor], exact_descriptor=True)
    assert base64.b64decode(custody.payload["prompt.json"]["base64"]) == original
