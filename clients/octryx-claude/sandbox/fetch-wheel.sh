#!/bin/sh
# Build time only: the octryx-claude wheel the platform serves, refused unless its sha256 matches the published one.
# Usage: fetch-wheel.sh <base_url> <target_dir>   (base_url must be https)
set -eu
base_url="${1%/}"
target="$2"
case "$base_url" in https://*) ;; *) echo "fetch-wheel: base_url must be https" >&2; exit 2 ;; esac
mkdir -p "$target"
curl -fsSL "$base_url/octryx-claude/version" -o "$target/version.json"
read_field() { python3 -c "import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])" "$target/version.json" "$1"; }
version="$(read_field version)"
filename="$(read_field filename)"
sha256="$(read_field sha256)"
case "$filename" in "octryx_claude-$version-py3-none-any.whl") ;; *) echo "fetch-wheel: unexpected filename" >&2; exit 2 ;; esac
curl -fsSL "$base_url/octryx-claude/package/$version" -o "$target/$filename"
echo "$sha256  $target/$filename" | sha256sum -c -
rm -f "$target/version.json"
