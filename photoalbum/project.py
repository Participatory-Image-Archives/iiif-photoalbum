"""Read project.yml, the album.yml files and their images.csv."""
import csv
import io
import os
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import yaml

COLUMNS = ["image", "page", "label", "layer", "tags"]
# A IIIF Image API request: {service}/{region}/{size}/{rotation}/{quality}.{format}
IMAGE_REQUEST = re.compile(r"^(?P<service>.+?)/(full|square|\d+,\d+,\d+,\d+|pct:[\d.,]+)"
                           r"/[^/]+/!?\d+(\.\d+)?/[a-z]+\.\w+$")


@dataclass
class Row:
    image: str   # file name, or URL of an image or of a IIIF image service
    page: str    # rows sharing a page are the layers of one Canvas
    label: str
    layer: str
    tags: set
    line: int    # line in images.csv, for messages

    @property
    def file(self):
        return file_name(self.image)


@dataclass
class Album:
    id: str
    folder: str
    settings: dict  # album.yml over project.yml
    rows: list


def is_url(ref):
    return ref.startswith(("http://", "https://"))


def service_of(url):
    """IIIF image service of an info.json or image request URL, else None."""
    if url.endswith("/info.json"):
        return url.removesuffix("/info.json")
    match = IMAGE_REQUEST.match(url)
    return match.group("service") if match else None


def file_name(ref):
    """File name of an image; for a IIIF URL, the last part of its service."""
    if not is_url(ref):
        return ref
    return os.path.basename(urlparse(service_of(ref) or ref).path.rstrip("/"))


def load_yaml(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def pages_url():
    """GitHub Pages address of the repository being built by GitHub Actions."""
    repository = os.environ.get("GITHUB_REPOSITORY")
    if not repository:
        return None
    owner, name = repository.split("/")
    if name.lower() == f"{owner.lower()}.github.io":
        return f"https://{name.lower()}"
    return f"https://{owner.lower()}.github.io/{name}"


def load_project(path="project.yml"):
    project = load_yaml(path)
    base_url = project.get("base_url") or pages_url()
    if not base_url:
        raise SystemExit(f"Set base_url in {path}: the address the Manifests will be published at.")
    project["base_url"] = base_url.rstrip("/")
    project.setdefault("output", "site")
    project.setdefault("albums", "albums")
    return project


def read_rows(path):
    """Read images.csv; comma, semicolon (Excel) and tab separators are accepted."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        text = f.read()
    try:
        dialect = csv.Sniffer().sniff(text.splitlines()[0], delimiters=",;\t")
    except (csv.Error, IndexError):
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    reader.fieldnames = [(n or "").strip().lower() for n in reader.fieldnames or []]
    if "image" not in reader.fieldnames:
        raise SystemExit(f"{path}: the first line must name the columns, with at least 'image' "
                         f"(columns: {', '.join(COLUMNS)})")
    rows = []
    for line, record in enumerate(reader, 2):
        value = {k: (record.get(k) or "").strip() for k in COLUMNS}
        if not value["image"]:
            continue
        rows.append(Row(image=value["image"],
                        page=value["page"] or value["image"],
                        label=value["label"] or file_name(value["image"]),
                        layer=value["layer"],
                        tags=set(value["tags"].replace(",", " ").split()),
                        line=line))
    return rows


def load_albums(project, ids=None):
    folder = project["albums"]
    available = sorted(d for d in os.listdir(folder)
                       if os.path.isfile(os.path.join(folder, d, "images.csv")))
    unknown = [i for i in ids or [] if i not in available]
    if unknown:
        raise SystemExit(f"Unknown album(s): {', '.join(unknown)}. Albums in {folder}/: {', '.join(available)}")
    albums = []
    for album_id in ids or available:
        path = os.path.join(folder, album_id)
        # The project Collection is not the album's Collection
        settings = {k: v for k, v in project.items() if k != "collection"}
        if os.path.isfile(os.path.join(path, "album.yml")):
            settings.update(load_yaml(os.path.join(path, "album.yml")))
        albums.append(Album(album_id, path, settings, read_rows(os.path.join(path, "images.csv"))))
    return albums
