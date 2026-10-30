"""Record the image dimensions found in the Manifests committed to git.

Writes recorded_dimensions.json, used by iiif-album.py for images that no
image source serves yet. The most recent commit wins, so the sizes reported
by the PIA Cantaloupe server (limited by maxArea) take precedence over the
older Sipi sizes.

Usage: python tools/record_dimensions.py
"""
import json
import re
import subprocess


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def images(o):
    if isinstance(o, dict):
        if o.get("type") == "Image" and o.get("width") and o.get("height"):
            yield o
        for v in o.values():
            yield from images(v)
    elif isinstance(o, list):
        for v in o:
            yield from images(v)


def main():
    dims = {}
    for commit in git("rev-list", "HEAD").split():
        for path in git("ls-tree", "-r", "--name-only", commit).split():
            # Manifests were in the album folders, then in site/manifests/
            if not re.match(r"(SGV_10A_000\d\d|site/manifests)/.+\.json$", path):
                continue
            try:
                manifest = json.loads(git("show", f"{commit}:{path}"))
            except (json.JSONDecodeError, subprocess.CalledProcessError):
                continue
            for image in images(manifest):
                match = re.search(r"(SGV_10[AP]_\d{5}_[^/.]+)", image.get("id", ""))
                if match and match.group(1) not in dims:
                    dims[match.group(1)] = {"width": image["width"], "height": image["height"],
                                            "commit": commit[:7]}
    with open("recorded_dimensions.json", "w") as f:
        json.dump(dict(sorted(dims.items())), f, indent=1)
    print(f"{len(dims)} stems written to recorded_dimensions.json")


if __name__ == "__main__":
    main()
