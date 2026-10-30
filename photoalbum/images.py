"""Find where each image is served and how large it is."""
import io
import json
import math
import os
import re
import threading

import requests

from .project import is_url, service_of
STATIC_FORMATS = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                  ".gif": "image/gif", ".webp": "image/webp", ".tif": "image/tiff", ".tiff": "image/tiff"}
# Sent with every request, to learn whether viewers on other websites may load the image
ORIGIN = "https://example.org"
USER_AGENT = "iiif-photoalbum (https://github.com/Participatory-Image-Archives/iiif-photoalbum)"


def service_profile(info):
    profile = info.get("profile")
    if isinstance(profile, list):
        profile = profile[0] if profile else None
    match = re.search(r"level[0-2]", profile or "")
    return match.group(0) if match else "level2"


class Images:
    """Resolve image references from images.csv, with a cache shared by all albums.

    A resolved image is a dict with kind (iiif, static or pending), url (the
    service for iiif and pending, the file for static), api, profile, format,
    width and height (None when unknown), source and cors.
    """

    def __init__(self, project):
        self.sources = [s for s in project.get("image_sources") or []
                        if s.get("enabled", True) and s.get("service")]
        self.labels = {s["name"]: s.get("label") for s in self.sources}
        self.pending = project.get("pending") or {}
        self.known = {}
        known_file = project.get("known_dimensions")
        if known_file and os.path.isfile(known_file):
            with open(known_file) as f:
                self.known = json.load(f)
        self.cache = {}
        self.lock = threading.Lock()
        self.http = requests.Session()
        self.http.headers["Origin"] = ORIGIN
        self.http.headers["User-Agent"] = USER_AGENT

    def info(self, service):
        """Read info.json of a IIIF image service, or return None."""
        try:
            response = self.http.get(f"{service}/info.json", timeout=20)
            if response.status_code != 200:
                return None
            info = response.json()
            w, h = info["width"], info["height"]
        except Exception:
            return None
        api = 2 if "image/2" in json.dumps(info.get("@context", "")) else 3
        max_area = info.get("maxArea")
        if api == 3 and max_area and w * h > max_area:
            # Image API 3.0 servers may limit the full image with maxArea
            scale = math.sqrt(max_area / (w * h))
            w, h = int(w * scale), int(h * scale)
        return {"kind": "iiif", "url": service, "api": api, "profile": service_profile(info),
                "format": "image/jpeg", "width": w, "height": h,
                "cors": "Access-Control-Allow-Origin" in response.headers}

    def static(self, url):
        """Measure an image file from its first bytes, or return None."""
        try:
            from PIL import Image
        except ImportError:
            raise SystemExit("Pillow is needed to measure image files: pip install Pillow")
        try:
            response = self.http.get(url, stream=True, timeout=30)
            if response.status_code != 200:
                return None
            fmt = response.headers.get("Content-Type", "").split(";")[0].strip()
            if not fmt.startswith("image/"):
                return None
            data = b""
            for chunk in response.iter_content(65536):
                data += chunk
                try:
                    w, h = Image.open(io.BytesIO(data)).size
                    break
                except Exception:
                    if len(data) > 100 * 1024 * 1024:
                        return None
            else:
                return None
            response.close()
        except Exception:
            return None
        return {"kind": "static", "url": url, "api": None, "profile": None, "format": fmt,
                "width": w, "height": h, "cors": "Access-Control-Allow-Origin" in response.headers}

    def lookup(self, ref):
        """First answer for a reference: a URL, or a file name tried on each source."""
        if is_url(ref):
            service = service_of(ref)
            if service:
                return self.info(service)
            # A service base, or an image file
            return self.info(ref) or self.static(ref)
        name = os.path.splitext(ref)[0]
        for source in self.sources:
            source_name = name
            for rule in source.get("rewrite") or []:
                source_name = re.sub(rule["pattern"], rule["replace"], source_name)
            image = self.info(source["service"].format(name=source_name, file=ref))
            if image:
                image["source"] = source["name"]
                return image
        return None

    def placeholder(self, ref):
        """Keep an image that is not served yet at its pending address, or return None."""
        name = os.path.splitext(ref)[0]
        dims = self.known.get(name) or self.known.get(ref) or {}
        if is_url(ref):
            service = service_of(ref)
            ext = os.path.splitext(ref)[1].lower()
            iiif = bool(service) or ext not in STATIC_FORMATS
            return {"kind": "pending" if iiif else "static",
                    "url": service or ref,
                    "api": self.pending.get("api", 3) if iiif else None, "profile": "level2",
                    "format": "image/jpeg" if iiif else STATIC_FORMATS.get(ext, "image/jpeg"),
                    "width": dims.get("width"), "height": dims.get("height"),
                    "source": "pending", "cors": None}
        if not self.pending.get("service"):
            return None
        return {"kind": "pending", "url": self.pending["service"].format(name=name, file=ref),
                "api": self.pending.get("api", 3), "profile": self.pending.get("profile", "level2"),
                "format": "image/jpeg", "width": dims.get("width"), "height": dims.get("height"),
                "source": "pending", "cors": None}

    def resolve(self, ref):
        with self.lock:
            if ref in self.cache:
                return self.cache[ref]
        image = self.lookup(ref)
        if image is not None:
            image.setdefault("source", None)
        with self.lock:
            self.cache[ref] = image
        return image
