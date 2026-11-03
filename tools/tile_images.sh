#!/usr/bin/env bash
# Make IIIF Image API 3.0 level 0 tiles, with iiif-tiler (the tool of the
# IIIF workbench's GitHub Action), for the images listed in a text file.
#
# Usage: tools/tile_images.sh LIST OUTPUT_DIR BASE_URL
#   LIST        text file with the path of one image per line
#   OUTPUT_DIR  folder of the web site the tiles go to, e.g. ~/Git/hostiiing/images
#   BASE_URL    its published address, e.g. https://julsraemy.ch/hostiiing/images/
#
# Each image gets a folder named after its file, without extension. Images
# already tiled are skipped, so the script can be run again after a stop.
set -uo pipefail
[ $# -eq 3 ] || { sed -n '5,8p' "$0" | cut -c3-; exit 2; }
LIST=$1; OUT=$2; BASE=${3%/}/
VERSION=1.0.2
JAR="${XDG_CACHE_HOME:-$HOME/.cache}/iiif-tiler/iiif-tiler-$VERSION.jar"

mkdir -p "$(dirname "$JAR")"
[ -f "$JAR" ] || curl -fL -o "$JAR" "https://github.com/glenrobson/iiif-tiler/releases/download/$VERSION/iiif-tiler.jar" || exit 1

n=0; failed=0; total=$(grep -c . "$LIST")
while read -r f; do
  [ -n "$f" ] || continue
  n=$((n + 1)); name=$(basename "$f"); name=${name%.*}
  if [ -f "$OUT/$name/info.json" ]; then echo "[$n/$total] $name exists, skipped"; continue; fi
  echo "[$n/$total] $name"
  # stdin closed, so java cannot use up the list; a failed image does not stop the run
  java -jar "$JAR" -version 3 -output "$OUT" -identifier "$BASE" "$f" < /dev/null \
    || { echo "FAILED: $name"; failed=$((failed + 1)); }
done < "$LIST"
echo "Finished: $n images, $failed failed"
du -sh "$OUT"
[ "$failed" -eq 0 ]
