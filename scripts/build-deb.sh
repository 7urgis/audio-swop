#!/bin/sh
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
output=${1:-/tmp/audio-swop_0.2.0_all.deb}
staging=$(mktemp -d)
trap 'rm -rf "$staging"' EXIT HUP INT TERM
cp -a "$project_dir/src/." "$staging/"
find "$staging" -type d -name __pycache__ -exec rm -rf {} +
find "$staging" -type f -name '*.pyc' -delete
find "$staging" -type d -exec chmod 755 {} +
find "$staging" -type f -exec chmod 644 {} +
chmod 755 "$staging/usr/bin/audio_swop"
dpkg-deb --root-owner-group --build "$staging" "$output"
