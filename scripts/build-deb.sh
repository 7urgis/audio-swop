#!/bin/sh
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
package_version=$(awk '/^Version:/ {print $2}' "$project_dir/src/DEBIAN/control")
output=${1:-/tmp/audio-swop_${package_version}_all.deb}
staging=$(mktemp -d)
trap 'rm -rf "$staging"' EXIT HUP INT TERM
cp -a "$project_dir/src/." "$staging/"
find "$staging" -type d -name __pycache__ -exec rm -rf {} +
find "$staging" -type f -name '*.pyc' -delete
find "$staging" -type d -exec chmod 755 {} +
find "$staging" -type f -exec chmod 644 {} +
chmod 755 "$staging/usr/bin/audio_swop"
dpkg-deb --root-owner-group --build "$staging" "$output"
