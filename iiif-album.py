"""Build the IIIF Manifests (and Collections) of the albums in albums/.

Usage: python iiif-album.py [ALBUM_ID ...] [--project project.yml] [--report build-report.md]

Every album folder holds an images.csv and an album.yml; shared settings are
in project.yml. The Manifests are written to the output folder (site/ by
default) in the layout they are published in, with a report of what needs
attention in build-report.md.
"""
import argparse
import sys

from photoalbum.build import Builder, Report
from photoalbum.images import Images
from photoalbum.project import load_albums, load_project


def main():
    parser = argparse.ArgumentParser(description="Generate IIIF Presentation 3.0 Manifests for layered photo albums.")
    parser.add_argument("albums", nargs="*", help="album identifiers (default: all albums)")
    parser.add_argument("--project", default="project.yml")
    parser.add_argument("--report", default="build-report.md")
    args = parser.parse_args()

    project = load_project(args.project)
    report = Report()
    builder = Builder(project, Images(project), report)
    built = [builder.build_album(album) for album in load_albums(project, args.albums)]
    # The project Collection lists every album: only rewrite it when all of them were built
    if not args.albums and all(built):
        builder.write_project_collection()
    builder.write_index()
    report.write(args.report)
    errors = report.errors()
    print(f"\n{errors} error(s). Report written to {args.report}")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
