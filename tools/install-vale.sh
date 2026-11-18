#!/usr/bin/env bash
set -euo pipefail

readonly VALE_VERSION="3.9.1"
# SHA-256 of vale_3.9.1_Linux_64-bit.tar.gz from the release checksums file.
readonly VALE_SHA256="fbc2eb47d0b8c50220ed1a2c5c611fbe0904ed567d638143d482016a18fd2db0"
readonly INSTALL_DIR=".tools/vale/current"
readonly DOC_TOOLS_VERSION="0.1.0"
readonly DOC_TOOLS_SHA256="125104c0cc535698d1cc9bba3e57883bdf9d87db6da346ff583967c4ce42de6c"
readonly DOC_STYLE_SHA256="272ce4e4dd2c7bd2bf74c8bd820393f3038d6175cd99a80f1bd4bfa27bd6e29c"
readonly GOOGLE_SHA256="4b67fca1f2a88595b2a578ab98bbf3017a23af677b04f93e862843f3ea1a9a0b"
readonly PACKAGE_DIR=".tools/doc-tools/${DOC_TOOLS_VERSION}"

if [[ $# -gt 1 || ( $# -eq 1 && "$1" != --docs ) ]]; then
  echo "Usage: bash tools/install-vale.sh [--docs]" >&2
  exit 2
fi

if [[ "$(uname -s)" != "Linux" || "$(uname -m)" != "x86_64" ]]; then
  echo "Automatic Vale installation currently supports Linux x86_64 only." >&2
  echo "Install Vale 3.9.1 on PATH and rerun make policy." >&2
  exit 1
fi

archive_dir="$(mktemp -d)"
trap 'rm -rf "$archive_dir"' EXIT

download() {
  local url="$1" name="$2" digest="$3"
  curl --proto '=https' --proto-redir '=https' -sSfL "$url" -o "${archive_dir}/${name}"
  echo "${digest}  ${archive_dir}/${name}" | sha256sum -c - >/dev/null
}

download \
  "https://github.com/errata-ai/vale/releases/download/v${VALE_VERSION}/vale_${VALE_VERSION}_Linux_64-bit.tar.gz" \
  vale.tar.gz "$VALE_SHA256"
if [[ "${1:-}" == --docs ]]; then
  download \
    "https://github.com/OpenRAE/doc-tools/releases/download/v${DOC_TOOLS_VERSION}/doc-tools-${DOC_TOOLS_VERSION}.tar.gz" \
    doc-tools.tar.gz "$DOC_TOOLS_SHA256"
  download \
    "https://github.com/OpenRAE/doc-tools/releases/download/v${DOC_TOOLS_VERSION}/DocTools.zip" \
    DocTools.zip "$DOC_STYLE_SHA256"
  download https://github.com/vale-cli/Google/releases/download/v0.7.1/Google.zip \
    Google.zip "$GOOGLE_SHA256"
fi

# Verify every download before installing or running any of its contents.
mkdir -p "$INSTALL_DIR"
tar -xzf "${archive_dir}/vale.tar.gz" -C "$INSTALL_DIR" vale
"${INSTALL_DIR}/vale" --version

if [[ "${1:-}" == --docs ]]; then
  mkdir -p "$PACKAGE_DIR"
  tar -xzf "${archive_dir}/doc-tools.tar.gz" -C "$PACKAGE_DIR" --strip-components=1
  mkdir -p "${PACKAGE_DIR}/style-packages"
  cp "${archive_dir}/Google.zip" "${archive_dir}/DocTools.zip" "${PACKAGE_DIR}/style-packages/"
  bash "${PACKAGE_DIR}/tools/install-ste.sh"
  "${INSTALL_DIR}/vale" sync
fi
