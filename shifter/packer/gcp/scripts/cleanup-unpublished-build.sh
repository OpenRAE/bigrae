#!/usr/bin/env bash
# Delete the GCE resources of a packer-gcp.yml build that did not publish (#2747).
#
# The templates name the builder VM packer-<build id>, Packer names its disk
# after the VM, and the image carries the label build-run=<build id>. A failed,
# timed-out, or cancelled build can leave all three in the build project.
#
# Inputs (environment): GCP_PROJECT_ID, ZONE, BUILD_ID (<run ID>-<run attempt>),
# and optionally IMAGE_WAIT_SECONDS (default 1800) and POLL_SECONDS (default 20).
set -euo pipefail

: "${GCP_PROJECT_ID:?GCP_PROJECT_ID is required}"
: "${ZONE:?ZONE is required}"
: "${BUILD_ID:?BUILD_ID is required}"
if [[ ! "${BUILD_ID}" =~ ^[0-9]+-[0-9]+$ ]]; then
  echo "::error::BUILD_ID must be <run ID>-<run attempt>." >&2
  exit 1
fi

name="packer-${BUILD_ID}"
project=(--project="${GCP_PROJECT_ID}")

# Each lookup is a plain assignment so that set -e stops on a gcloud error
# instead of reading it as "nothing to delete".
list_images() {
  local status="${1:-}"
  gcloud compute images list "${project[@]}" --no-standard-images \
    --filter="labels.build-run=${BUILD_ID}${status:+ AND status=${status}}" --format='value(name)'
}

# Packer can stop waiting while GCE still creates the image, and GCE cannot
# delete a PENDING image. Wait until the image is READY or FAILED.
deadline=$((SECONDS + ${IMAGE_WAIT_SECONDS:-1800}))
pending="$(list_images PENDING)"
while [[ -n "${pending}" ]]; do
  if ((SECONDS >= deadline)); then
    echo "::error::Image ${pending} of build ${BUILD_ID} is still PENDING; delete it manually." >&2
    exit 1
  fi
  sleep "${POLL_SECONDS:-20}"
  pending="$(list_images PENDING)"
done

images="$(list_images)"
if [[ -n "${images}" ]]; then
  mapfile -t image_names <<<"${images}"
  gcloud compute images delete "${image_names[@]}" "${project[@]}" --quiet
fi

instance="$(gcloud compute instances list "${project[@]}" --zones="${ZONE}" \
  --filter="name=${name}" --format='value(name)')"
if [[ -n "${instance}" ]]; then
  gcloud compute instances delete "${name}" "${project[@]}" --zone="${ZONE}" --delete-disks=all --quiet
fi

disk="$(gcloud compute disks list "${project[@]}" --zones="${ZONE}" \
  --filter="name=${name}" --format='value(name)')"
if [[ -n "${disk}" ]]; then
  gcloud compute disks delete "${name}" "${project[@]}" --zone="${ZONE}" --quiet
fi

echo "Deleted the unpublished resources of build ${BUILD_ID}."
