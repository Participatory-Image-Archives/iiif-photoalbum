"""Check the generated Manifests.

Three separate checks, since the IIIF validator only checks the schema:
1. Schema: the IIIF Presentation validator (okay: 1 is the target). Local
   files are posted to the validator; files too large for it are checked
   locally against the validator's own JSON Schema (needs jsonschema).
   With --url, the published Manifests are validated by URL instead.
2. Images: every image body id, thumbnail and image service info.json answers.
3. Collections: every Manifest listed in the published Collections exists
   among the generated Manifests.

Usage: python validate.py [MANIFEST.json ...] [--url] [--skip-images]
"""
import argparse
import glob
import json
import sys
from concurrent.futures import ThreadPoolExecutor

import requests

validator = "https://presentation-validator.iiif.io/validate"
schema_url = "https://raw.githubusercontent.com/IIIF/presentation-validator/main/schema/iiif_3_0.json"
collections = [
    "https://julsraemy.ch/hostiiing/collections/SGV_10A_00031.json",
    "https://julsraemy.ch/hostiiing/collections/SGV_10A_00050.json",
]
max_post = 100 * 1024  # request size limit of the public validator

http = requests.Session()


def validate_schema(manifest, use_url):
    """Return (okay, list of error titles, method)."""
    if use_url:
        r = http.get(validator, params={"version": "3.0", "url": manifest["id"]}, timeout=120)
        result = r.json()
        return result["okay"] == 1, [e["title"] for e in result.get("errorList", [])], "validator (url)"
    data = json.dumps(manifest, separators=(",", ":"))
    if len(data.encode()) <= max_post:
        r = http.post(validator, params={"version": "3.0"}, data=data,
                      headers={"Content-Type": "application/json"}, timeout=120)
        result = r.json()
        return result["okay"] == 1, [e["title"] for e in result.get("errorList", [])], "validator (post)"
    import jsonschema
    schema = http.get(schema_url, timeout=60).json()
    errors = [f"{'/'.join(map(str, e.absolute_path))}: {e.message[:200]}"
              for e in jsonschema.Draft7Validator(schema).iter_errors(manifest)]
    return not errors, errors, "local schema"


def image_urls(manifest):
    """Collect image body ids and service info.json URLs."""
    urls = set()

    def add(resource):
        urls.add(resource["id"])
        for service in resource.get("service", []):
            urls.add((service.get("id") or service["@id"]) + "/info.json")

    for thumbnail in manifest.get("thumbnail", []):
        add(thumbnail)
    for canvas in manifest["items"]:
        for page in canvas.get("items", []):
            for anno in page["items"]:
                body = anno["body"]
                for item in body["items"] if body["type"] == "Choice" else [body]:
                    add(item)
    return urls


def answers(url):
    try:
        r = http.get(url, timeout=60, stream=True)
        r.close()
        return url, r.status_code
    except Exception as e:
        return url, type(e).__name__


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("manifests", nargs="*",
                        default=sorted(glob.glob("SGV_10A_000*/SGV_10A_000*.json")))
    parser.add_argument("--url", action="store_true", help="validate the published Manifests by URL")
    parser.add_argument("--skip-images", action="store_true")
    args = parser.parse_args()

    ok = True
    ids = set()
    for path in args.manifests:
        with open(path) as f:
            manifest = json.load(f)
        ids.add(manifest["id"])
        valid, errors, method = validate_schema(manifest, args.url)
        print(f"{path}: schema {'okay: 1' if valid else 'okay: 0'} ({method})")
        for error in errors:
            print(f"  {error}")
        ok &= valid
        if not args.skip_images:
            urls = sorted(image_urls(manifest))
            with ThreadPoolExecutor(max_workers=8) as pool:
                failed = [(u, s) for u, s in pool.map(answers, urls) if s != 200]
            print(f"  images: {len(urls) - len(failed)}/{len(urls)} URLs answer with HTTP 200")
            for url, status in failed:
                print(f"  {status} {url}")
            ok &= not failed

    for url in collections:
        try:
            items = [i["id"] for i in http.get(url, timeout=60).json()["items"]]
        except Exception as e:
            print(f"{url}: could not be read ({e})")
            ok = False
            continue
        unknown = [i for i in items if i not in ids]
        print(f"{url}: {len(items) - len(unknown)}/{len(items)} Manifests generated")
        for i in unknown:
            print(f"  not generated: {i}")
        ok &= not unknown

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
