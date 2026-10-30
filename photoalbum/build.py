"""Turn albums into Manifests and Collections, and report what needs attention."""
import datetime
import html
import json
import os
import statistics
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

import requests
from iiif_prezi3 import (config, Annotation, AnnotationPage, Choice, ExternalItem, HomepageItem,
                         KeyValueString, Manifest, ProviderItem, ResourceItem, ServiceItem1)

from .project import is_url

CONTEXT = "http://iiif.io/api/presentation/3/context.json"
LINKED_ART_CONTEXT = "https://linked.art/ns/v1/linked-art.json"
DEFAULT_VIEWS = [{"suffix": "", "behavior": "paged", "canvases": "layers"}]


class Report:
    """Messages per album, printed as they come and written to a Markdown file."""
    prefixes = {"info": "", "note": "Note: ", "warning": "WARNING: ", "error": "ERROR: "}

    def __init__(self):
        self.sections = []

    def section(self, title):
        self.sections.append((title, []))
        print(f"\n=== {title}")

    def add(self, level, message):
        self.sections[-1][1].append((level, message))
        print(f"  {self.prefixes[level]}{message}")

    def errors(self):
        return sum(level == "error" for _, messages in self.sections for level, _ in messages)

    def write(self, path):
        with open(path, "w", encoding="utf-8") as f:
            f.write("# Build report\n")
            for title, messages in self.sections:
                f.write(f"\n## {title}\n\n")
                for level, message in messages:
                    f.write(f"- {'**' + self.prefixes[level].strip() + '** ' if level != 'info' else ''}{message}\n")


def short_list(items, limit=15):
    items = list(items)
    more = f" and {len(items) - limit} more" if len(items) > limit else ""
    return ", ".join(items[:limit]) + more


def size_of(image):
    return (image["width"], image["height"]) if image and image["width"] else None


def pages_of(rows):
    pages = OrderedDict()
    for row in rows:
        pages.setdefault(row.page, []).append(row)
    return pages


def plan_view(album, view):
    """List the canvases of a view as (label, rows, page)."""
    excluded = set(view.get("exclude_tags") or [])
    rows = [r for r in album.rows if not r.tags & excluded]
    kind = view.get("canvases", "layers")
    if kind == "images":
        return [(r.label, [r], r.page) for r in rows]
    if kind == "pages":
        return [(rs[0].label, rs[:1], page) for page, rs in pages_of(rows).items()]
    if kind == "layers":
        return [(rs[0].label, rs, page) for page, rs in pages_of(rows).items()]
    raise SystemExit(f"Unknown canvases '{kind}' in views: use layers, pages or images")


def make_service(image):
    if image["api"] == 2:
        return ServiceItem1(id=image["url"], type="ImageService2", profile=image["profile"])
    return {"id": image["url"], "type": "ImageService3", "profile": image["profile"]}


def make_body(image, label=None):
    """Image body; Image API 2.x uses full, 3.0 uses max."""
    if image["kind"] == "static":
        body = ResourceItem(id=image["url"], type="Image", format=image["format"])
    else:
        size = "full" if image["api"] == 2 else "max"
        body = ResourceItem(id=f"{image['url']}/full/{size}/0/default.jpg", type="Image", format="image/jpeg")
    if image["width"]:
        body.height = image["height"]
        body.width = image["width"]
    if label:
        body.label = {config.configs['helpers.auto_fields.AutoLang'].auto_lang: [label]}
    if image["kind"] != "static":
        body.service = [make_service(image)]
    return body


def make_thumbnail(image):
    if image["kind"] == "static":
        return ResourceItem(id=image["url"], type="Image", format=image["format"])
    thumbnail = ResourceItem(id=image["url"] + "/full/80,/0/default.jpg", type="Image", format="image/jpeg")
    thumbnail.service = [make_service(image)]
    return thumbnail


def timestamp(value, end=False):
    """A produced begin or end as written in album.yml; YAML may have read it as a date.

    A date alone becomes the start of that day for begin, its last second for end.
    """
    if isinstance(value, datetime.datetime):
        return value.isoformat().replace("+00:00", "Z")
    value = value.isoformat() if isinstance(value, datetime.date) else str(value)
    if len(value) == 10:
        value += "T23:59:59Z" if end else "T00:00:00Z"
    return value


def make_provider(provider):
    fields = {"id": provider["id"], "label": provider["label"]}
    if provider.get("homepage"):
        homepage = provider["homepage"]
        fields["homepage"] = [HomepageItem(id=homepage["id"], type="Text",
                                           format=homepage.get("format", "text/html"),
                                           label=homepage.get("label", provider["label"]))]
    if provider.get("logo"):
        logo = provider["logo"]
        fields["logo"] = [ResourceItem(id=logo["id"], type="Image", format=logo.get("format", "image/png"))]
    return ProviderItem(**fields)


def first_label(resource):
    label = resource.get("label") or resource.get("_label") or {}
    values = next(iter(label.values()), [""]) if isinstance(label, dict) else [label]
    return values[0] if values else ""


class Builder:
    def __init__(self, project, images, report):
        self.project = project
        self.images = images
        self.report = report
        self.base = project["base_url"]
        self.output = project["output"]
        self.lang = project.get("language", "en")
        config.configs['helpers.auto_fields.AutoLang'].auto_lang = self.lang
        self.collections = {}  # album id -> reference to its Collection
        self.manifests = {}    # album id -> references to its Manifests
        self.provider = None   # as written in the Manifests, reused in the Collections

    def manifest_id(self, manifest_id):
        return f"{self.base}/manifests/{manifest_id}.json"

    def notice(self, settings, key, served, total, extra=None):
        notice = settings.get("notice") or {}
        if not notice.get("enabled") or not notice.get(key):
            return None
        text = notice[key].format(served=served, total=total)
        return f"{text} {extra}" if extra else text

    def write_json(self, path, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")

    # --- Images ---------------------------------------------------------

    def resolve_album(self, album):
        """Resolve every image of the album; return False if one cannot be placed."""
        refs = list(OrderedDict.fromkeys(r.image for r in album.rows))
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(self.images.resolve, refs))
        lost = []
        for ref in refs:
            if self.images.cache[ref] is None:
                placeholder = self.images.placeholder(ref)
                if placeholder is None:
                    lost.append(ref)
                else:
                    self.images.cache[ref] = placeholder
        resolved = {ref: self.images.cache[ref] for ref in refs if ref not in lost}
        pending = [ref for ref, image in resolved.items() if image["source"] == "pending"]
        self.report.add("info", f"{len(refs) - len(pending) - len(lost)}/{len(refs)} images served")
        for source in self.images.sources:
            count = sum(image["source"] == source["name"] for image in resolved.values())
            if count:
                self.report.add("info", f"{source['name']}: {count}")
        urls = sum(image["source"] is None for image in resolved.values())
        if urls:
            self.report.add("info", f"given by URL: {urls}")
        broken = [ref for ref in pending if is_url(ref)]
        pending = [ref for ref in pending if not is_url(ref)]
        if pending:
            self.report.add("note", f"Not served yet, kept at their pending address ({len(pending)}): "
                                    + ", ".join(pending))
        if broken:
            self.report.add("warning", f"These URLs do not answer, they are kept as given but will not display "
                                       f"until they do; check them for typos ({len(broken)}): " + ", ".join(broken))
        if lost:
            self.report.add("error", f"Not found on any image source ({len(lost)}): {short_list(lost)}. "
                                     "Check the file names or URLs in images.csv, or set pending in "
                                     "project.yml to keep their place. No Manifest written for this album.")
            return False
        no_cors = [ref for ref, image in resolved.items() if image["cors"] is False]
        if no_cors:
            self.report.add("warning", f"These images do not allow other websites to load them (no CORS "
                                       f"header), most viewers will not show them: {short_list(no_cors)}")
        return True

    def check_pages(self, album):
        """Compare the images of each page with its first image, and check the page order."""
        checks = album.settings.get("checks") or {}
        tolerance = checks.get("aspect_ratio_tolerance", 0.02)
        ratio = checks.get("resolution_ratio", 2)
        seen, previous = set(), None
        for row in album.rows:
            if row.page in seen and row.page != previous:
                self.report.add("warning", f"images.csv line {row.line}: page '{row.page}' appears again after "
                                           "other pages; its images are gathered on its first occurrence")
            seen.add(row.page)
            previous = row.page
        for page, rows in pages_of(album.rows).items():
            sized = [(r, size_of(self.images.cache[r.image])) for r in rows]
            sized = [(r, s) for r, s in sized if s]
            if len(sized) < 2:
                continue
            (first, (w0, h0)), others = sized[0], sized[1:]
            for row, (w, h) in others:
                difference = (w / h) / (w0 / h0) - 1
                name, first_name = row.layer or row.label, first.layer or first.label
                if abs(difference) > tolerance:
                    self.report.add("warning", f"Page {page}: '{name}' ({w}×{h}) is {abs(difference):.0%} "
                                               f"{'wider' if difference > 0 else 'narrower'} in shape than "
                                               f"'{first_name}' ({w0}×{h0}). The viewer stretches it to the "
                                               "page, so it will look distorted when switching layers.")
                factor = max(w, h) / max(w0, h0)
                if factor > ratio or factor < 1 / ratio:
                    self.report.add("note", f"Page {page}: '{name}' ({w}×{h}) has {factor:.1f}× the resolution "
                                            f"of '{first_name}' ({w0}×{h0}). Nothing breaks, but details will "
                                            "not be equally sharp when zooming in on each layer.")

    def canvas_size(self, rows, page_rows, median, assumed):
        """Size of the first image with known size, else of its page, else the album median."""
        for row in rows:
            if size_of(self.images.cache[row.image]):
                return size_of(self.images.cache[row.image])
        for row in page_rows:
            size = size_of(self.images.cache[row.image])
            if size:
                assumed.setdefault(rows[0].image, ("note", f"size of {rows[0].file} unknown, its canvas takes "
                                                           f"the size of {row.file} of the same page ({size[0]}×{size[1]})"))
                return size
        if median:
            assumed.setdefault(rows[0].image, ("warning", f"size of {rows[0].file} unknown, its canvas takes the "
                                                          f"usual size of the album ({median[0]}×{median[1]}). "
                                                          "Check it once the image is served."))
            return median
        return None

    # --- Manifests -------------------------------------------------------

    def setup_manifest(self, album, view, manifest_id, note, sources_used, thumbnail):
        s = album.settings
        label = s.get("label") or album.id
        if view.get("label"):
            label = f"{label} ({view['label']})"
        manifest = Manifest(id=self.manifest_id(manifest_id), label=label)
        if note:
            manifest.summary = {self.lang: [s["summary"], note] if s.get("summary") else [note]}
        elif s.get("summary"):
            manifest.summary = s["summary"]
        metadata = [KeyValueString(label=str(k), value=str(v))
                    for k, v in (s.get("metadata") or {}).items() if v not in (None, "")]
        notice = s.get("notice") or {}
        if note and notice.get("status"):
            metadata.append(KeyValueString(label="Status", value=notice["status"].format(built=notice.get("built"))))
        if metadata:
            manifest.metadata = metadata
        if s.get("provider"):
            manifest.provider = [make_provider(s["provider"])]
        if s.get("rights"):
            manifest.rights = s["rights"]
        credit = s.get("attribution")
        hosts = [self.images.labels[n] for n in self.images.labels if n in sources_used and self.images.labels[n]]
        if hosts:
            credit = (credit + ". " if credit else "") + "Images served by " + " and ".join(hosts)
        if credit:
            manifest.requiredStatement = KeyValueString(label="Attribution", value=credit)
        if s.get("viewing_direction"):
            manifest.viewingDirection = s["viewing_direction"]
        manifest.behavior = [view.get("behavior", "paged")]
        manifest.thumbnail = [make_thumbnail(thumbnail)]
        record = self.linked_art_id(album)
        if record:
            # A list of ExternalItem, validated as the SeeAlso of the Manifest
            # (iiif-prezi3 1.x rejects a SeeAlso built directly)
            manifest.seeAlso = [ExternalItem(id=record, type="Dataset", label=self.see_also(record)["label"],
                                             format="application/ld+json", profile=LINKED_ART_CONTEXT)]
        return manifest

    def add_canvas(self, manifest, manifest_id, n, label, rows, size):
        """Add a canvas painted with one image, or with a Choice of its layers."""
        prefix = f"{self.base}/manifests/{manifest_id}"
        canvas = manifest.make_canvas(id=f"{prefix}/canvas/p{n}", label=label, height=size[1], width=size[0])
        if len(rows) == 1:
            body = make_body(self.images.cache[rows[0].image])
        else:
            # Each body of the Choice carries its own dimensions
            body = Choice(items=[make_body(self.images.cache[r.image], r.layer or r.label) for r in rows])
        anno = Annotation(id=f"{prefix}/annotation/p{n}", type="Annotation", motivation="painting",
                          body=body, target=canvas.id)
        canvas.items = [AnnotationPage(id=f"{prefix}/page/p{n}", type="AnnotationPage", items=[anno])]

    def previous_canvases(self, path, manifest_id):
        """Canvas labels by id of the last version of a Manifest, local or published."""
        try:
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as f:
                    manifest = json.load(f)
            else:
                manifest = requests.get(self.manifest_id(manifest_id), timeout=10).json()
            return {c["id"]: first_label(c) for c in manifest.get("items", [])}
        except Exception:
            return {}

    def check_stability(self, manifest_id, before, manifest):
        """Warn when canvas ids that may be cited change meaning or disappear."""
        if not before:
            return
        after = {c.id: first_label(json.loads(c.json())) for c in manifest.items}
        changed = [i for i in after if i in before and before[i] != after[i]]
        gone = [i for i in before if i not in after]
        if changed:
            self.report.add("warning", f"{manifest_id}: {len(changed)} canvases now show another image than before "
                                       f"(rows inserted, removed or reordered?), e.g. {changed[0].rsplit('/', 1)[1]} "
                                       f"was '{before[changed[0]]}', is now '{after[changed[0]]}'. "
                                       "Links to these canvases change meaning.")
        if gone:
            self.report.add("warning", f"{manifest_id}: {len(gone)} canvases of the previous version no longer "
                                       f"exist: {short_list(i.rsplit('/', 1)[1] for i in gone)}")

    def build_album(self, album):
        self.report.section(album.id)
        if not album.rows:
            self.report.add("error", "images.csv lists no image")
            return False
        if not self.resolve_album(album):
            return False
        self.check_pages(album)
        cache = self.images.cache
        sizes = [size_of(cache[r.image]) for r in album.rows if size_of(cache[r.image])]
        median = (int(statistics.median(w for w, _ in sizes)), int(statistics.median(h for _, h in sizes))) if sizes else None
        pages = pages_of(album.rows)

        views = album.settings.get("views") or DEFAULT_VIEWS
        plans, assumed = [], {}
        for view in views:
            canvases = plan_view(album, view)
            sized = [(label, rows, self.canvas_size(rows, pages[page], median, assumed))
                     for label, rows, page in canvases]
            plans.append((view, sized))
        for level, message in assumed.values():
            self.report.add(level, message)
        if not median:
            self.report.add("error", "No image of this album could be measured and no dimensions are known: "
                                     "a Canvas cannot be written without them. No Manifest written.")
            return False
        unsized = sorted({r.file for r in album.rows if not size_of(cache[r.image])})
        if unsized:
            self.report.add("note", "No dimensions known, image written without them: " + short_list(unsized))

        is_served = lambda ref: cache[ref]["source"] != "pending"
        refs = list(OrderedDict.fromkeys(r.image for r in album.rows))
        served_refs = [ref for ref in refs if is_served(ref)]
        thumbnail_ref = album.settings.get("thumbnail") or (served_refs or refs)[0]
        thumbnail = cache.get(thumbnail_ref) or self.images.resolve(thumbnail_ref) or cache[refs[0]]

        self.manifests[album.id] = []
        linked = []  # (Manifest id, view label) for the Linked Art record
        for view, canvases in plans:
            manifest_id = album.id + (view.get("suffix") or "")
            images = [r.image for _, rows, _ in canvases for r in rows]
            note = self.notice(album.settings, "manifest", sum(map(is_served, images)), len(images),
                               view.get("notice_extra"))
            sources_used = {cache[ref]["source"] for ref in images}
            manifest = self.setup_manifest(album, view, manifest_id, note, sources_used, thumbnail)
            for n, (label, rows, size) in enumerate(canvases, 1):
                self.add_canvas(manifest, manifest_id, n, label, rows, size)
            path = os.path.join(self.output, "manifests", manifest_id + ".json")
            self.check_stability(manifest_id, self.previous_canvases(path, manifest_id), manifest)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as output:
                print(manifest.json(indent=2), file=output)
            waiting = sum(any(not is_served(r.image) for r in rows) for _, rows, _ in canvases)
            self.report.add("info", f"Manifest written to {path}: {len(canvases)} canvases, "
                                    f"{waiting} with images not served yet")
            layered = [rows for _, rows, _ in canvases if len(rows) > 1]
            if layered:
                full = sum(all(is_served(r.image) for r in rows) for rows in layered)
                none = sum(not any(is_served(r.image) for r in rows) for rows in layered)
                self.report.add("info", f"Pages with layers: {len(layered)}; all layers served: {full}, "
                                        f"some served: {len(layered) - full - none}, none served: {none}")
            manifest_json = json.loads(manifest.json())
            self.manifests[album.id].append({k: manifest_json[k] for k in ["id", "type", "label", "thumbnail"]})
            linked.append((manifest_json["id"], view.get("label")))
            self.provider = manifest_json.get("provider")

        self.write_linked_art(album, linked)
        self.write_album_collection(album, len(served_refs), len(refs))
        return True

    # --- Linked Art --------------------------------------------------------

    def linked_art_id(self, album):
        """Id of the album's Linked Art record: the external one if given, else the generated one."""
        settings = album.settings.get("linked_art")
        if not settings:
            return None
        settings = settings if isinstance(settings, dict) else {}
        return settings.get("id") or f"{self.base}/objects/{album.id}.json"

    def see_also(self, record):
        return {"id": record, "type": "Dataset", "label": {self.lang: ["Linked Art description of the album"]},
                "format": "application/ld+json", "profile": LINKED_ART_CONTEXT}

    def write_linked_art(self, album, linked):
        """Describe the album as a physical object, pointing to each of its Manifests."""
        settings = album.settings.get("linked_art")
        if not settings:
            return
        settings = settings if isinstance(settings, dict) else {}
        if settings.get("id"):
            self.report.add("info", f"Linked Art: seeAlso to external record {settings['id']}")
            return
        label = settings.get("label") or album.settings.get("label") or album.id
        record = {"@context": LINKED_ART_CONTEXT, "id": self.linked_art_id(album),
                  "type": "HumanMadeObject", "_label": label,
                  "identified_by": [{"type": "Name", "content": label},
                                    {"type": "Identifier", "content": album.id}]}
        if settings.get("classified_as"):
            record["classified_as"] = [{"id": t["id"], "type": "Type", "_label": t.get("label")}
                                       if t.get("label") else {"id": t["id"], "type": "Type"}
                                       for t in settings["classified_as"]]
        produced = settings.get("produced") or {}
        if produced:
            timespan = {"type": "TimeSpan"}
            if produced.get("begin"):
                timespan["begin_of_the_begin"] = timestamp(produced["begin"])
            if produced.get("end"):
                timespan["end_of_the_end"] = timestamp(produced["end"], end=True)
            record["produced_by"] = {"type": "Production", "timespan": timespan}
        # Makers, places, materials and dimensions would go here (produced_by.carried_out_by,
        # produced_by.took_place_at, made_of, dimension), once curators choose their vocabularies.
        record["subject_of"] = [
            {"type": "LinguisticObject", "_label": f"IIIF Manifest ({view})" if view else "IIIF Manifest",
             "digitally_carried_by": [{
                 "type": "DigitalObject",
                 "access_point": [{"id": manifest_id, "type": "DigitalObject"}],
                 "conforms_to": [{"id": "http://iiif.io/api/presentation/", "type": "InformationObject"}],
                 "format": f'application/ld+json;profile="{CONTEXT}"'}]}
            for manifest_id, view in linked]
        path = os.path.join(self.output, "objects", album.id + ".json")
        self.write_json(path, record)
        self.report.add("info", f"Linked Art record written to {path} ({len(linked)} Manifests linked)")

    # --- Collections -----------------------------------------------------

    def collection(self, collection_id, label, summary, items, provider, see_also=None):
        collection = {"@context": CONTEXT, "id": f"{self.base}/collections/{collection_id}.json",
                      "type": "Collection", "label": {self.lang: [label]}}
        if summary:
            collection["summary"] = {self.lang: [summary]}
        if provider:
            collection["provider"] = provider
        if see_also:
            collection["seeAlso"] = [see_also]
        collection["items"] = items
        path = os.path.join(self.output, "collections", collection_id + ".json")
        self.write_json(path, collection)
        self.report.add("info", f"Collection written to {path}: {len(items)} items")
        return {"id": collection["id"], "type": "Collection", "label": collection["label"]}

    def write_album_collection(self, album, served, total):
        settings = album.settings.get("collection")
        if not settings:
            return
        settings = settings if isinstance(settings, dict) else {}
        summary = self.notice(album.settings, "collection", served, total) or settings.get("summary")
        record = self.linked_art_id(album)
        self.collections[album.id] = self.collection(
            album.id, settings.get("label") or album.settings.get("label") or album.id, summary,
            self.manifests[album.id], self.provider, self.see_also(record) if record else None)

    def write_project_collection(self):
        settings = self.project.get("collection")
        if not settings:
            return
        self.report.section(f"Collection {settings['id']}")
        items = []
        for album_id in self.manifests:
            items += [self.collections[album_id]] if album_id in self.collections else self.manifests[album_id]
        self.collection(settings["id"], settings.get("label") or settings["id"], settings.get("summary"),
                        items, self.provider)

    # --- Landing page ----------------------------------------------------

    def write_index(self):
        """List everything in the output folder, with links to open it in viewers."""
        entries = []
        for kind in ["collections", "manifests", "objects"]:
            folder = os.path.join(self.output, kind)
            for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
                if name.endswith(".json"):
                    with open(os.path.join(folder, name), encoding="utf-8") as f:
                        resource = json.load(f)
                    entries.append((kind, f"{kind}/{name}", resource["id"], first_label(resource)))
        def row(kind, path, rid, label):
            name = "Linked Art" if kind == "objects" else kind[:-1].title()
            cells = f'<td>{name}</td><td>{html.escape(label)}</td><td><a href="{html.escape(path)}">JSON</a></td>'
            if kind == "objects":
                # Linked Art records are not IIIF: no viewer or IIIF validator
                return f"<tr>{cells}</tr>"
            return (f'<tr>{cells}'
                    f'<td><a href="https://projectmirador.org/embed/?iiif-content={html.escape(rid)}">Mirador</a></td>'
                    f'<td><a href="https://theseusviewer.org/?iiif-content={html.escape(rid)}">Theseus</a></td>'
                    f'<td><a href="https://presentation-validator.iiif.io/validate?version=3.0&amp;url={html.escape(rid)}">'
                    f'Validator</a></td></tr>')
        rows = "\n".join(row(*entry) for entry in entries)
        page = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>IIIF Manifests</title>
<style>body{{font-family:system-ui,sans-serif;margin:2rem;max-width:70rem}}td{{padding:.2rem .6rem}}</style></head>
<body>
<h1>IIIF Manifests and Collections</h1>
<p>Copy the address of a JSON link into any IIIF viewer. Mirador shows the layers of a page in its layers panel.</p>
<table>
{rows}
</table>
</body>
</html>
"""
        os.makedirs(self.output, exist_ok=True)
        with open(os.path.join(self.output, "index.html"), "w", encoding="utf-8") as f:
            f.write(page)
        open(os.path.join(self.output, ".nojekyll"), "w").close()
