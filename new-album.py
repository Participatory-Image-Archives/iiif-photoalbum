"""Start a new album: albums/ALBUM_ID/album.yml and images.csv.

Usage:
  python new-album.py ALBUM_ID [--images LIST] [--layer-pattern TEXT]

LIST is a text file with one image per line, in album order: a file name
(looked up on the image sources of project.yml) or a URL (IIIF image service,
info.json, or a JPEG/PNG file). Without it, images.csv only has its header.

--layer-pattern groups images into pages from their names: an image whose
name contains TEXT becomes a layer of the image named like the part before
TEXT, e.g. with _mit_, 005_mit_Schutz.tif is a layer of 005.tif.

Check images.csv afterwards: the page, label, layer and tags columns can be
edited in any spreadsheet program.
"""
import argparse
import csv
import os
import sys

from photoalbum.project import COLUMNS, file_name

ALBUM_YML = """# Album {album_id}. Values here replace those of project.yml.
label: Album {album_id}

# Shown as label: value pairs; empty values are left out
metadata:
  Title: {title}
  Identifier: {album_id}
  Year/Period:
  Description:

# summary: replaces the summary of project.yml
# thumbnail: an image of images.csv, otherwise the first one served

# Uncomment to also publish a Collection of the Manifests of this album
# collection:
#   label: IIIF Collection of the {album_id} Photo Album
"""


def stem(ref):
    return os.path.splitext(file_name(ref))[0]


def main():
    parser = argparse.ArgumentParser(description="Start a new album folder.")
    parser.add_argument("album_id")
    parser.add_argument("--images", help="text file with one file name or URL per line")
    parser.add_argument("--layer-pattern", help="text that marks a layer in a file name, e.g. _mit_")
    parser.add_argument("--title", default="")
    parser.add_argument("--albums", default="albums")
    args = parser.parse_args()

    folder = os.path.join(args.albums, args.album_id)
    if os.path.exists(os.path.join(folder, "images.csv")):
        sys.exit(f"{folder}/images.csv exists already; edit it instead.")
    images = []
    if args.images:
        with open(args.images, encoding="utf-8") as f:
            images = [line.strip() for line in f if line.strip()]

    rows, pages = [], {}
    for ref in images:
        name = stem(ref)
        page = name
        if args.layer_pattern and args.layer_pattern in name:
            base = name[:name.index(args.layer_pattern)]
            # A layer without its base image becomes a page of its own
            page = base if base in pages else name
        pages.setdefault(page, ref)
        rows.append({"image": ref, "page": page, "label": "", "layer": name, "tags": ""})

    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "images.csv"), "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    if not os.path.exists(os.path.join(folder, "album.yml")):
        with open(os.path.join(folder, "album.yml"), "w", encoding="utf-8") as f:
            f.write(ALBUM_YML.format(album_id=args.album_id, title=args.title or "''"))
    layered = sum(1 for p in pages if sum(r["page"] == p for r in rows) > 1)
    print(f"{folder}: {len(rows)} images on {len(pages)} pages, {layered} with layers.")
    print("Next: fill in album.yml, check images.csv, then run python iiif-album.py " + args.album_id)


if __name__ == "__main__":
    main()
