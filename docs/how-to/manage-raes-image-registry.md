# Manage the RAES Image Registry

The RAES image registry maps an authored RAES image `source` (a name and an
optional version) to a concrete provider image used at range realization. A
RAES scenario names its images by source; a tenant operator maps each source to
a real provider image here. Without a matching, enabled mapping (and no already
concrete image reference), realization fails explicitly.

This surface is part of the only supported range-provisioning path. The API and SPA serve current native installation-owned mappings.
The management command retains a separate legacy path.

## Before You Start

You need:

- Current `installation.prepare_content` authority and a matching native credential ceiling.
  Staff status and the historical Threat Research group alone do not supply that authority.
- The authored image `source` name and version from the scenario or package, and
  the concrete provider image reference to map it to (a GCE `source_image` or
  image family URL, or an AWS AMI id).

## Register or Update a Mapping

Registering is idempotent: it creates the mapping, or updates the existing one
for the same `(provider, source_name, source_version)`. A blank version is the
any-version fallback for that source name.

Use the SPA or authenticated API for current installation-scoped mappings.
The retained management command writes legacy unscoped rows and is not equivalent.

### SPA (Author area)

1. Open the portal and go to **Author > RAES Images**.
2. Fill in the provider, source name, optional version, and image reference,
   then choose **Register mapping**. Optional sizing fields (machine type, disk
   size, disk type) set backend defaults for that mapping.

Set **Management SSH port** to the SSH listener baked into the host image
(default `22`, valid range `1–65535`). For example, a container host can use
`2222` for provisioning while its participant container uses `22`. This field
does not reconfigure the image's SSH daemon or participant access. It selects
the management transport and the management-only firewall ingress. The launch
input freezes this value, so editing the mapping cannot redirect an in-flight
operation. The API field is `management_ssh_port`; the equivalent command option
is `--management-ssh-port`.

**Management SSH username** optionally selects the existing local administrator
account required by an image. Leave it blank to use the backend default. This
field is frozen with the port and never selects the participant account. The
API field is `management_ssh_username`, and the command option is
`--management-ssh-username`.

### API

Use operator-prepared private files for the session cookie and CSRF header.
Keep those files owner-only and outside the repository.
The header file contains the `X-CSRFToken` header; do not put its value in command arguments.

```sh
curl -sS -X POST https://<host>/api/v1/cms/raes-image-mappings/ \
    -H "Content-Type: application/json" \
    --cookie /private/operator/session.cookies --header @/private/operator/csrf.headers \
    -d '{"provider": "gce", "source_name": "alpine", "source_version": "3.19",
         "image_ref": "projects/<project>/global/images/family/<alpine-family>"}'
```

### Management command

The following command is retained legacy syntax.
It writes an unscoped compatibility row, not a native installation-owned mapping.
Use the SPA or API above for current deployments.
Do not use this command to bypass current content authority.

```sh
python manage.py raes_image_registry --action register \
    --provider gce --source-name alpine --source-version 3.19 \
    --image-ref projects/<project>/global/images/family/<alpine-family>
```

## List mappings

Use the SPA or `GET /api/v1/cms/raes-image-mappings/` for current mappings.
The retained command below lists legacy rows only.

```sh
python manage.py raes_image_registry --action list
```

Add `--enabled-only` to hide disabled rows, or `--provider <name>` to filter to
one provider. For the API, `include_disabled=false` hides disabled rows.
The SPA lists mappings on **RAES Images**.

## Disable a Mapping

Disabling keeps the row for audit and stops it from resolving at realization.
Use disable instead of deleting a mapping.
Use the SPA or API for current mappings; this retained command targets legacy rows.

```sh
python manage.py raes_image_registry --action disable \
    --provider gce --source-name alpine --source-version 3.19
```

The API is `POST /api/v1/cms/raes-image-mappings/disable/`; the SPA has a
**Disable** action on each enabled row. Re-enable a mapping by registering it
again with the same natural key.

## Validation Package Mapping

The in-repo validation pack (`shifter/environment-packs/shifter-raes-validation/`) authors a
single image with `source: {name: alpine, version: "3.19"}`. Before running the
RAES backend validation, register a `gce` mapping for `source_name=alpine`,
`source_version=3.19` pointing at a concrete Alpine-compatible GCE image or
image family. See
[scenario verification](../technical/shifter_platform/scenario-verification.md) for
the full validation evidence contract.
