"""Probe Memobase for the images listed in the album sequence files.

For every image in albums/<album>/images.csv (default captures and variants), test
sgv-002-<stem>-1 .. -N on the Memobase IIIF Image API and write the result
to memobase_check.csv. Standard library only.

Usage: python tools/check_memobase.py [ALBUM_ID ...] [--max-suffix N]
"""
import argparse
import csv
import json
import re
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

MEMOBASE = "https://media.memobase.ch/iiif/{mid}/open/iiif/2/{mid}.jpg"


def memobase_stem(stem):
    # Loose photographs are filed under SGV_10P_<number>_<r|v>, without the album number
    loose = re.match(r"SGV_10[AP]_\d{5}_(\d{5}_[rv])$", stem)
    return "SGV_10P_" + loose.group(1) if loose else stem


def probe(stem, suffix):
    mid = f"sgv-002-{memobase_stem(stem)}-{suffix}"
    url = MEMOBASE.format(mid=mid) + "/info.json"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            info = json.load(r)
            return stem, suffix, r.status, info.get("width"), info.get("height"), url
    except urllib.error.HTTPError as e:
        return stem, suffix, e.code, None, None, url
    except Exception as e:
        return stem, suffix, type(e).__name__, None, None, url


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("albums", nargs="*", default=["SGV_10A_00031", "SGV_10A_00050"])
    parser.add_argument("--max-suffix", type=int, default=3)
    parser.add_argument("--output", default="memobase_check.csv")
    args = parser.parse_args()

    stems = []
    for album in args.albums:
        with open(f"albums/{album}/images.csv", newline="", encoding="utf-8-sig") as f:
            stems += [row["image"].strip().removesuffix(".tif") for row in csv.DictReader(f) if row["image"].strip()]

    jobs = [(s, n) for s in stems for n in range(1, args.max_suffix + 1)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda j: probe(*j), jobs))

    with open(args.output, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["stem", "variant", "suffix", "status", "width", "height", "info_json"])
        for stem, suffix, status, w, h, url in results:
            variant = "_mit_" in stem
            writer.writerow([stem, variant, suffix, status, w, h, url])

    found = {}
    for stem, suffix, status, *_ in results:
        if status == 200:
            found.setdefault(stem, []).append(suffix)
    defaults = [s for s in stems if "_mit_" not in s]
    variants = [s for s in stems if "_mit_" in s]
    print(f"Defaults found: {sum(s in found for s in defaults)}/{len(defaults)}")
    print(f"Variants found: {sum(s in found for s in variants)}/{len(variants)}")
    print("Suffixes seen:", sorted({n for v in found.values() for n in v}))
    print("Missing:", ", ".join(s for s in stems if s not in found) or "none")
    print(f"Details written to {args.output}")


if __name__ == "__main__":
    main()
