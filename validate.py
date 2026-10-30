"""Check the generated Manifests and Collections.

Three separate checks, since the IIIF validator only checks the schema:
1. Schema: the IIIF Presentation validator (okay: 1 is the target). Local
   files are posted to the validator; files too large for it are checked
   locally against the validator's own JSON Schema (needs jsonschema).
   With --url, the published Manifests are validated by URL instead.
2. Images: every image body id, thumbnail and image service info.json
   answers, and allows other websites to load it (CORS), which viewers need.
3. Collections: every item of the Collections is among the generated
   Manifests and Collections (with --url, the published Collections).
4. Linked Art: every record in objects/ is JSON with the Linked Art context,
   is a HumanMadeObject whose id is its own published address (as the
   Linked Art API 1.0 Object endpoint requires), points only to generated
   Manifests, and every seeAlso of a Manifest
   or Collection to {base_url}/objects/ has its record. The same for the
   VisualItem records in visual/, which objects refer to with shows.
   Local files only.

Usage: python validate.py [FILE.json ...] [--url] [--skip-images] [--images-warn]
"""
import argparse
import glob
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import requests

from photoalbum.images import ORIGIN, USER_AGENT
from photoalbum.project import load_yaml, pages_url

validator = "https://presentation-validator.iiif.io/validate"
linked_art_context = "https://linked.art/ns/v1/linked-art.json"
schema_url = "https://raw.githubusercontent.com/IIIF/presentation-validator/main/schema/iiif_3_0.json"
max_post = 100 * 1024  # request size limit of the public validator

http = requests.Session()
http.headers["Origin"] = ORIGIN
http.headers["User-Agent"] = USER_AGENT


def validate_schema(resource, use_url):
    """Return (okay, list of error titles, method)."""
    if use_url:
        r = http.get(validator, params={"version": "3.0", "url": resource["id"]}, timeout=120)
        result = r.json()
        return result["okay"] == 1, [e["title"] for e in result.get("errorList", [])], "validator (url)"
    data = json.dumps(resource, separators=(",", ":"))
    if len(data.encode()) <= max_post:
        r = http.post(validator, params={"version": "3.0"}, data=data,
                      headers={"Content-Type": "application/json"}, timeout=120)
        result = r.json()
        return result["okay"] == 1, [e["title"] for e in result.get("errorList", [])], "validator (post)"
    import jsonschema
    schema = http.get(schema_url, timeout=60).json()
    errors = [f"{'/'.join(map(str, e.absolute_path))}: {e.message[:200]}"
              for e in jsonschema.Draft7Validator(schema).iter_errors(resource)]
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
        # Short connect timeout: unreachable hosts (e.g. the VPN only PIA server) fail fast
        r = http.get(url, timeout=(5, 60), stream=True)
        r.close()
        return url, r.status_code, "Access-Control-Allow-Origin" in r.headers
    except Exception as e:
        return url, type(e).__name__, None


def access_points(record):
    """Ids of the Manifests a Linked Art record is the subject of."""
    return [point["id"] for subject in record.get("subject_of", [])
            for carrier in subject.get("digitally_carried_by", [])
            for point in carrier.get("access_point", [])]


def check_linked_art(output, base_url):
    """Check the Linked Art records and the seeAlso pointing to them; return okay."""
    ok = True
    manifest_ids, linkers = set(), []
    for path in sorted(glob.glob(os.path.join(output, "manifests", "*.json"))
                       + glob.glob(os.path.join(output, "collections", "*.json"))):
        with open(path, encoding="utf-8") as f:
            resource = json.load(f)
        if resource["type"] == "Manifest":
            manifest_ids.add(resource["id"])
        linkers.append((path, resource))

    records = {}
    for folder, kind in [("objects", "HumanMadeObject"), ("visual", "VisualItem")]:
        for path in sorted(glob.glob(os.path.join(output, folder, "*.json"))):
            try:
                with open(path, encoding="utf-8") as f:
                    record = json.load(f)
            except json.JSONDecodeError as e:
                print(f"{path}: Linked Art not valid JSON ({e})")
                ok = False
                continue
            records[path] = record
            if record.get("@context") != linked_art_context:
                print(f"{path}: Linked Art @context is {record.get('@context')!r}, not {linked_art_context}")
                ok = False
            if record.get("type") != kind:
                print(f"{path}: Linked Art type is {record.get('type')!r}, not {kind!r}")
                ok = False
            expected = f"{base_url}/{folder}/{os.path.basename(path)}" if base_url else None
            if expected and record.get("id") != expected:
                print(f"{path}: Linked Art id is {record.get('id')!r}, not its published address {expected}")
                ok = False
            if kind == "HumanMadeObject":
                points = access_points(record)
                unknown = [i for i in points if i not in manifest_ids]
                print(f"{path}: Linked Art, {len(points) - len(unknown)}/{len(points)} Manifests generated")
                for i in unknown:
                    print(f"  not generated: {i}")
                ok &= not unknown
            else:
                print(f"{path}: Linked Art visual item, {len(record.get('represents', []))} places")

    if not base_url:
        print("Linked Art seeAlso not checked: no base_url in project.yml")
        return ok
    links = [(path, see_also["id"], "seeAlso") for path, resource in linkers
             for see_also in resource.get("seeAlso", [])]
    links += [(path, shown["id"], "shows") for path, record in records.items() for shown in record.get("shows", [])]
    for path, target, prop in links:
        for folder in ["objects", "visual"]:
            prefix = f"{base_url}/{folder}/"
            if target.startswith(prefix) and not os.path.isfile(os.path.join(output, folder, target[len(prefix):])):
                print(f"{path}: {prop} {target} has no record in {os.path.join(output, folder)}")
                ok = False
    return ok


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="*", help="Manifests and Collections (default: all in the output folder)")
    parser.add_argument("--project", default="project.yml")
    parser.add_argument("--url", action="store_true", help="validate the published versions by URL")
    parser.add_argument("--skip-images", action="store_true")
    parser.add_argument("--images-warn", action="store_true",
                        help="report images that do not answer without failing (e.g. images not served yet)")
    args = parser.parse_args()
    project = load_yaml(args.project) if os.path.isfile(args.project) else {}
    output = project.get("output", "site")
    base_url = (project.get("base_url") or pages_url() or "").rstrip("/")
    files = args.files or sorted(glob.glob(os.path.join(output, "manifests", "*.json"))
                                 + glob.glob(os.path.join(output, "collections", "*.json")))

    ok = True
    ids, collections = set(), []
    for path in files:
        with open(path, encoding="utf-8") as f:
            resource = json.load(f)
        ids.add(resource["id"])
        valid, errors, method = validate_schema(resource, args.url)
        print(f"{path}: schema {'okay: 1' if valid else 'okay: 0'} ({method})")
        for error in errors:
            print(f"  {error}")
        ok &= valid
        if resource["type"] == "Collection":
            collections.append((path, resource))
            continue
        if not args.skip_images:
            urls = sorted(image_urls(resource))
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(answers, urls))
            failed = [(u, s) for u, s, _ in results if s != 200]
            no_cors = [u for u, s, cors in results if s == 200 and not cors]
            print(f"  images: {len(urls) - len(failed)}/{len(urls)} URLs answer with HTTP 200")
            for url, status in failed:
                print(f"  {status} {url}")
            if no_cors:
                print(f"  {len(no_cors)} URLs answer without CORS header, viewers may not show them:")
                for url in no_cors:
                    print(f"  no CORS {url}")
            ok &= args.images_warn or not failed

    for path, collection in collections:
        if args.url:
            try:
                collection = http.get(collection["id"], timeout=60).json()
                path = collection["id"]
            except Exception as e:
                print(f"{collection['id']}: could not be read ({e})")
                ok = False
                continue
        items = [i["id"] for i in collection["items"]]
        unknown = [i for i in items if i not in ids]
        print(f"{path}: {len(items) - len(unknown)}/{len(items)} items generated")
        for i in unknown:
            print(f"  not generated: {i}")
        ok &= not unknown

    ok &= check_linked_art(output, base_url)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
