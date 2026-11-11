#!/usr/bin/env bash
# Install native dependencies on a dedicated Debian 13 / WSL2 Debian 13 host.
set -euo pipefail
source /etc/os-release
[[ "$ID" = debian && "$VERSION_ID" = 13 ]] || {
  echo "This setup script requires Debian 13." >&2; exit 1;
}
if (( EUID != 0 )); then
  echo "Run with sudo bash scripts/setup_dk_debian.sh" >&2
  exit 1
fi
apt-get update
apt-get install -y --no-install-recommends \
  attr bc bison brotli build-essential ca-certificates clang \
  cmake cpio curl device-tree-compiler dwarves e2fsprogs file \
  flex gawk gh git golang-go gperf kmod \
  lld llvm lz4 meson ninja-build openjdk-21-jdk-headless pcre2-utils \
  perl pkg-config protobuf-compiler python3 python3-dev python3-pip python3-venv \
  python3-protobuf python3-pyelftools python3-jinja2 rsync secilc swig unzip \
  wget xxd xz-utils zip zstd libbrotli-dev libdw-dev \
  libelf-dev libfmt-dev libgmock-dev libgtest-dev liblz4-dev libncurses-dev libpcre2-dev \
  libprotobuf-dev libsepol-dev libssl-dev libudev-dev libunwind-dev libusb-1.0-0-dev libzstd-dev \
  sudo shellcheck
