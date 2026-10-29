import argparse
import json
import math
import os
import re
import sys
import requests
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from iiif_prezi3 import config, Manifest, KeyValueString, ResourceItem, ProviderItem, HomepageItem, Annotation, AnnotationPage, Choice, ServiceItem1

### Album metadata, one entry per album
albums = {
    "SGV_10A_00031": {
        "title": "[Gebundenes Album mit blauem Textileinband zu einer Familienreise nach Norditalien und Gruppenreisen nach Frankreich]",
        "description": "Grossformatiges Album in Kordelbindung im Querformat. Blauer Textileinband mit Lochung aber ohne erhaltene Kordel. Hellgrau marmoriertes Vorsatzpapier, ein Leinengewebe verstärkt den Buchrücken. 40 dunkelgraue Albumseiten mit Pergamin-Schutzblättern mit jeweils sechs oder mehr Silbergelatine-Abzügen DOP pro Seite. Das Album zeigt die Familie Kreis auf einer Norditalienreise 1927 durch Mailand, Venedig, Pisa und Florenz sowie Gruppenausflügen von Walter Kreis nach Grenoble, Arles, Lyon und Strassburg und ins Wallis. Die Reisen sind mit Ortsangabe und Datum handschriftlich betitelt. Das Album gehörte sehr wahrscheinlich Walter Kreis und ein Grossteil der Fotografien wurden von ihm hergestellt. Die Fotografien wurden mit doppelseitigen, dreieckigen Fotoklebern montiert. Das letzte Albumdrittel wurde leer gelassen. Kleine Etikette im hinteren Buchdeckel unten rechts “Papyrus Basel AG Basel”. Das Album und die enthaltenen Fotografien wurden gereinigt und restauriert.",
        "period": "1926-1928",
    },
    "SGV_10A_00050": {
        "title": "[Gebundenes Album mit Rosenmuster mit Fotografien eines Patenkindes]",
        "description": None,
        "period": "1949",
    },
}

### Shared metadata
collection_name = "SGV_10 Familie Kreis"
summary = "A photo album of the SGV_10 Familie Kreis collection, digitised within the Participatory Knowledge Practices in Analogue and Digital Image Archives (PIA) research project"
rights = "http://creativecommons.org/licenses/by-nc/4.0/"
attribution = "Cultural Anthropology Switzerland (CAS / EKWS) photo archive, Basel"

### Manifests to generate: (sequence_file, behavior)
manifests_to_generate = [
    ("sequence.txt", "individuals"),
    ("sequence_paged.txt", "paged"),
]

### IIIF Presentation server (Manifest ids must not change, they are cited)
manifestserver = "https://julsraemy.ch/hostiiing/manifests"
collectionserver = "https://julsraemy.ch/hostiiing/collections"

### Removable notice while the Manifests are rebuilt: set enabled to False and
### rerun to remove it from the Manifests and the Collections
status_note = {"enabled": True, "built": "2026-10-29"}

def status_text(served, total, layers=False, short=False):
    """Under construction notice, with the image coverage of this run."""
    if short:
        text = ("Under construction. Images are currently served by Memobase (Memoriav); "
                "the page variants and the pages without photographs await the original files from the EKWS.")
    else:
        text = ("Under construction. The images of this Manifest are currently served by Memobase (Memoriav), "
                "which holds only the default capture of pages with photographs. The page variants "
                "(with and without protective interleaf, loose photographs, cord binding) and the pages "
                "without photographs are awaiting delivery of the original files from the EKWS and do not "
                "display yet.")
    text += f" Image coverage: {served} of {total} images."
    if layers:
        text += " The Choice layers are in place, but their variant images do not display yet."
    return text

### IIIF Image sources, tried in order for each file stem: the first source
### whose info.json answers with HTTP 200 wins. A source is skipped when it is
### disabled or has no base URL.
def memobase_service(stem):
    # Loose photographs are filed on Memobase under SGV_10P_<number>_<r|v>,
    # without the album number, e.g. SGV_10A_00031_09861_r -> SGV_10P_09861_r
    loose = re.match(r"SGV_10[AP]_\d{5}_(\d{5}_[rv])$", stem)
    if loose:
        stem = "SGV_10P_" + loose.group(1)
    # The meaning of the -1 suffix is not documented; only -1 has been seen
    memobase_id = f"sgv-002-{stem}-1"
    return f"https://media.memobase.ch/iiif/{memobase_id}/open/iiif/2/{memobase_id}.jpg"

self_hosted_base = None  # e.g. "https://example.org/iiif/3/"
pia_cantaloupe_base = "https://sipi.participatory-archives.ch/iiif/3/"

image_sources = [
    {
        "name": "memobase",
        "label": "Memobase (Memoriav)",
        "enabled": True,
        "api": 2,
        "service": memobase_service,
    },
    {
        # Placeholder: to be filled once the EKWS delivers the full resolution
        # files and they are served by a Cantaloupe (Image API 3.0) instance
        "name": "self_hosted",
        "label": None,
        "enabled": False,
        "api": 3,
        "base": self_hosted_base,
        "service": lambda stem: self_hosted_base + stem + ".tif",
    },
    {
        # Legacy PIA Cantaloupe server, reachable only via VPN since 2026
        "name": "pia_cantaloupe",
        "label": None,
        "enabled": False,
        "api": 3,
        "base": pia_cantaloupe_base,
        "service": lambda stem: pia_cantaloupe_base + stem + ".tif",
    },
]

### Images that no source serves yet keep their place in the Manifests as
### pending images: they point to the self hosted base once it is set, else to
### their legacy PIA URL, with the dimensions recorded in the earlier Manifests
### (see record_dimensions.py).
pending_source = {"name": "pending", "label": None, "api": 3}
recorded_dimensions_file = "recorded_dimensions.json"

# TODO: Memobase reuse terms and the wording of the credit to Memoriav are not
# confirmed. Ask Julien before publishing; do not add terms until then.

### CAS Photo Archive Website and GND
caslogo = "https://www.ekws.ch/_next/static/media/ekws-logo-full.bd88c732.svg"
cas = "https://www.ekws.ch/de/archiv"
gnd = "https://d-nb.info/gnd/1186091584"

### Language maps only in English
config.configs['helpers.auto_fields.AutoLang'].auto_lang = "en"

### Cache for resolved images (shared across manifests and albums)
image_cache = {}

extension = ".json"
http = requests.Session()

def stem_of(image_name):
    return image_name.strip().removesuffix(".tif")

def resolve(stem):
    """Return the first image source answering for a stem, with its dimensions, or None."""
    if stem in image_cache:
        return image_cache[stem]
    image_cache[stem] = None
    for source in image_sources:
        if not source["enabled"] or source.get("base", True) is None:
            continue
        service = source["service"](stem)
        try:
            response = http.get(f"{service}/info.json", timeout=20)
            if response.status_code != 200:
                continue
            info = response.json()
        except Exception as e:
            print(f"Warning: {source['name']} did not answer for {stem}: {e}")
            continue
        w = info["width"]
        h = info["height"]
        if source["api"] == 3:
            # Image API 3.0 servers may limit the full image with maxArea
            max_area = info.get("maxArea")
            if max_area and w * h > max_area:
                scale = math.sqrt(max_area / (w * h))
                w = int(w * scale)
                h = int(h * scale)
        image_cache[stem] = {"source": source, "service": service, "width": w, "height": h}
        break
    return image_cache[stem]

def add_pending(stem, recorded):
    """Keep an unserved image as pending, with its recorded dimensions if known."""
    dims = recorded.get(stem, {})
    image_cache[stem] = {"source": pending_source,
                         "service": (self_hosted_base or pia_cantaloupe_base) + stem + ".tif",
                         "width": dims.get("width"), "height": dims.get("height")}

def default_stem(stem):
    """Default capture of a page, e.g. SGV_10A_00031_005_mit_Schutz -> SGV_10A_00031_005."""
    return re.sub(r"_mit_.*$", "", stem)

def canvas_dimensions(stems):
    """Dimensions of the first image with known dimensions, else of the page's default capture."""
    for stem in stems + [default_stem(stems[0])]:
        image = image_cache.get(stem)
        if image and image["width"]:
            return image["width"], image["height"]
    return None

def make_service(service, api):
    if api == 2:
        return ServiceItem1(id=service, type="ImageService2", profile="level2")
    return {"id": service, "type": "ImageService3", "profile": "level2"}

def make_body(stem, label=None):
    """Image body for a stem; Image API 2.x uses full, 3.0 uses max."""
    image = image_cache[stem]
    size = "full" if image["source"]["api"] == 2 else "max"
    body = ResourceItem(id=f"{image['service']}/full/{size}/0/default.jpg",
                        type="Image", format="image/jpeg")
    if image["width"]:
        body.height = image["height"]
        body.width = image["width"]
    if label:
        body.label = {"en": [label]}
    body.service = [make_service(image["service"], image["source"]["api"])]
    return body

def setup_manifest(album_id, manifest_id, behavior, label, first_stem, sources_used, note=None):
    """Create a manifest with shared metadata, provider, rights, thumbnail."""
    album = albums[album_id]
    manifest = Manifest(id=manifestserver+"/"+manifest_id+extension,
                        label=f"Album {album_id} ({label})")
    manifest.summary = {"en": [summary, note]} if note else summary
    manifest.metadata = [
        KeyValueString(label="Title", value=album["title"]),
        KeyValueString(label="Collection", value=collection_name),
        KeyValueString(label="Identifier", value=album_id),
        KeyValueString(label="Year/Period", value=album["period"]),
    ]
    if album["description"]:
        manifest.metadata.append(KeyValueString(label="Description", value=album["description"]))
    if note:
        manifest.metadata.append(KeyValueString(label="Status",
                                                value=f"Under construction (rebuilt {status_note['built']})"))
    l = ResourceItem(id=caslogo,type="Image",format="image/svg+xml")
    hcas = HomepageItem(id=cas,type="Text",format="text/html",label="EKWS Fotoarchiv")
    p = ProviderItem(id=gnd, label="Empirische Kulturwissenschaft Schweiz. Fotoarchiv",homepage=[hcas],logo=[l])
    manifest.provider = [p]
    manifest.rights = rights
    credit = attribution
    providers = [s["label"] for s in image_sources if s["name"] in sources_used and s["label"]]
    if providers:
        credit += ". Images served by " + " and ".join(providers)
    manifest.requiredStatement = KeyValueString(label="Attribution", value=credit)
    manifest.viewingDirection = "left-to-right"
    manifest.behavior = [behavior]
    first = image_cache[first_stem]
    thumbnail = ResourceItem(id=first["service"]+"/full/80,/0/default.jpg",
                             type="Image",
                             format="image/jpeg")
    thumbnail.service = [make_service(first["service"], first["source"]["api"])]
    manifest.thumbnail = [thumbnail]
    return manifest

def add_canvas(manifest, manifest_id, canvas_id, label, stems):
    """Add a canvas painted with one image, or with a Choice of its states."""
    w, h = canvas_dimensions(stems)
    canvas = manifest.make_canvas(id=manifestserver + "/" + manifest_id + f"/canvas/p{canvas_id}",
                                  label=label,
                                  height=h,
                                  width=w)
    if len(stems) == 1:
        body = make_body(stems[0])
    else:
        # Each body of the Choice carries its own dimensions
        body = Choice(items=[make_body(s, re.sub(r"^SGV_10[AP]_\d{5}_", "", s)) for s in stems])
    anno = Annotation(id=manifestserver + "/" + manifest_id + f"/annotation/p{canvas_id}",
                      type="Annotation", motivation="painting",
                      body=body,
                      target=canvas.id)
    canvas.items = [AnnotationPage(id=manifestserver + "/" + manifest_id + f"/page/p{canvas_id}",
                                   type="AnnotationPage", items=[anno])]

def write_manifest(manifest, album_id, manifest_id):
    """Write manifest JSON to the album directory."""
    output_path = f'{album_id}/{manifest_id}{extension}'
    with open(output_path, 'w') as output:
        print(manifest.json(indent=2), file=output)
    print(f"Manifest written to {output_path}")

def read_sequence(album_id, sequence_file):
    with open(f'{album_id}/{sequence_file}', 'r') as x:
        return [i.strip() for i in x if i.strip()]

def layer_groups(album_id):
    """Group images: base images start new canvases, _mit_ variants are layers."""
    groups = OrderedDict()
    for image_name in read_sequence(album_id, "sequence.txt"):
        mit_match = re.search(r'_mit_', image_name)
        if mit_match:
            base = image_name[:mit_match.start()] + ".tif"
            if base in groups:
                groups[base].append(image_name)
            else:
                # _mit_ image without a matching base, treat as its own canvas
                groups[image_name] = [image_name]
        else:
            groups[image_name] = [image_name]
    return groups

def plan_album(album_id):
    """List the manifests of an album as (manifest_id, behavior, label, canvases).

    Each canvas is (canvas_number, label, [stems]). Canvas numbers follow the
    position in the sequence, as in the published Manifests.
    """
    plans = []
    for sequence_file, behavior in manifests_to_generate:
        sequence_suffix = sequence_file.replace("sequence", "").replace(".txt", "")
        canvases = [(n, name, [stem_of(name)])
                    for n, name in enumerate(read_sequence(album_id, sequence_file), 1)]
        plans.append((f"{album_id}{sequence_suffix}", behavior, behavior.title(), canvases))
    canvases = [(n, base, [stem_of(i) for i in images])
                for n, (base, images) in enumerate(layer_groups(album_id).items(), 1)]
    plans.append((f"{album_id}_layers", "paged", "Layers", canvases))
    return plans

def build_album(album_id, recorded):
    """Resolve every image of an album, keep the unserved ones as pending, write its manifests."""
    plans = plan_album(album_id)
    stems = sorted({s for plan in plans for canvas in plan[3] for s in canvas[2]})
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(resolve, stems))
    pending = [s for s in stems if image_cache[s] is None]
    for stem in pending:
        add_pending(stem, recorded)

    print(f"\n=== {album_id}: {len(stems) - len(pending)}/{len(stems)} images served")
    for source in image_sources:
        count = sum(1 for s in stems if image_cache[s]["source"] is source)
        if count:
            print(f"  {source['name']}: {count}")
    if pending:
        print(f"  Pending, not served by any source ({len(pending)}): " + ", ".join(pending))
    no_dims = [s for s in pending if not image_cache[s]["width"]]
    if no_dims:
        print("  No recorded dimensions (body written without them): " + ", ".join(no_dims))

    # A Canvas without dimensions is invalid: check before writing anything
    undimensioned = [(plan[0], c[1]) for plan in plans for c in plan[3] if not canvas_dimensions(c[2])]
    if undimensioned:
        print(f"Error: no dimensions for these canvases, no manifest written for {album_id}:")
        for manifest_id, canvas_label in undimensioned:
            print(f"  {manifest_id}: {canvas_label}")
        return False

    served = [s for s in stems if image_cache[s]["source"] is not pending_source]
    first_stem = served[0] if served else stems[0]
    for manifest_id, behavior, label, canvases in plans:
        sources_used = {image_cache[s]["source"]["name"] for c in canvases for s in c[2]}
        images = [s for c in canvases for s in c[2]]
        note = None
        if status_note["enabled"]:
            note = status_text(sum(s not in pending for s in images), len(images), layers=label == "Layers")
        manifest = setup_manifest(album_id, manifest_id, behavior, label, first_stem, sources_used, note)
        for n, canvas_label, canvas_stems in canvases:
            add_canvas(manifest, manifest_id, n, canvas_label, canvas_stems)
        write_manifest(manifest, album_id, manifest_id)
        waiting = [c[1] for c in canvases if any(s in pending for s in c[2])]
        print(f"  {len(canvases)} canvases, {len(waiting)} with pending images")
        if label == "Layers":
            layered = [c for c in canvases if len(c[2]) > 1]
            full = [c for c in layered if not any(s in pending for s in c[2])]
            partial = [c for c in layered if 0 < sum(s in pending for s in c[2]) < len(c[2])]
            none = [c for c in layered if all(s in pending for s in c[2])]
            print(f"  Pages with variants: {len(layered)}; all states served: {len(full)}, "
                  f"default served and variants pending: {len(partial)}, all pending: {len(none)}")
    write_collection(album_id, len(stems) - len(pending), len(stems))
    return True

def write_collection(album_id, served, total):
    """Add or remove the notice in the published Collection, written to collections/ for upload."""
    collection_id = f"{collectionserver}/{album_id}{extension}"
    collection = http.get(collection_id, timeout=30).json()
    if status_note["enabled"]:
        collection["summary"] = {"en": [status_text(served, total, short=True)]}
    elif collection.get("summary", {}).get("en", [""])[0].startswith("Under construction"):
        del collection["summary"]
    # Keep summary after label, as in the Manifests
    collection = {k: collection[k] for k in ["@context", "id", "type", "label", "summary"] if k in collection} | collection
    os.makedirs("collections", exist_ok=True)
    output_path = f"collections/{album_id}{extension}"
    with open(output_path, "w") as output:
        json.dump(collection, output, indent=2, ensure_ascii=False)
        output.write("\n")
    print(f"Collection written to {output_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate IIIF Presentation 3.0 Manifests for the SGV_10 photo albums.")
    parser.add_argument("albums", nargs="*", default=list(albums), help="album identifiers (default: all)")
    args = parser.parse_args()
    with open(recorded_dimensions_file) as f:
        recorded = json.load(f)
    ok = all([build_album(album_id, recorded) for album_id in args.albums])
    sys.exit(0 if ok else 1)
