import math
import re
import requests
from collections import OrderedDict
from iiif_prezi3 import config, Manifest, KeyValueString, ResourceItem, ProviderItem, ExternalItem, HomepageItem, Annotation, AnnotationPage, Choice

### Variables to change per album
album_id = "SGV_10A_00050"
collection_name = "SGV_10 Familie Kreis"
summary = "A very nice album of the SGV_10 Familie Kreis Collection"
rights = "http://creativecommons.org/licenses/by-nc/4.0/"
attribution = "Cultural Anthropology Switzerland (CAS)"

### Manifests to generate: (sequence_file, behavior)
manifests_to_generate = [
    ("sequence.txt", "individuals"),
    ("sequence_paged.txt", "paged"),
]

### IIIF Resource Servers
imageserver = "https://sipi.participatory-archives.ch/iiif/3/"
manifestserver = "https://julsraemy.ch/hostiiing/manifests"

### CAS Photo Archive Website and GND
caslogo = "https://www.ekws.ch/_next/static/media/ekws-logo-full.bd88c732.svg"
cas = "https://www.ekws.ch/de/archiv"
gnd = "https://d-nb.info/gnd/1186091584"

### Language maps only in English
config.configs['helpers.auto_fields.AutoLang'].auto_lang = "en"

### Cache for info.json responses (shared across manifests)
info_cache = {}

extension = ".json"
first_image = f"{album_id}_001.tif"

def fetch_dimensions(image_name):
    """Fetch and cache image dimensions from info.json, accounting for maxArea."""
    if image_name in info_cache:
        return info_cache[image_name]
    image_url = imageserver + image_name
    try:
        response = requests.get(f"{image_url}/info.json")
        response.raise_for_status()
        info = response.json()
        w = info["width"]
        h = info["height"]
        max_area = info.get("maxArea")
        if max_area and w * h > max_area:
            scale = math.sqrt(max_area / (w * h))
            w = int(w * scale)
            h = int(h * scale)
        info_cache[image_name] = (w, h)
    except Exception as e:
        print(f"Warning: Could not fetch info.json for {image_name}: {e}")
        w = None
        h = None
        info_cache[image_name] = (w, h)
    return w, h

def setup_manifest(manifest_id, behavior):
    """Create a manifest with shared metadata, provider, rights, thumbnail."""
    manifest = Manifest(id=manifestserver+"/"+manifest_id+extension,
                        label=f"Album {album_id} ({behavior.title()})")
    manifest.summary = summary
    manifest.metadata = [
        KeyValueString(label="Title", value=f"Photo Album {album_id}"),
        KeyValueString(label="Collection", value=collection_name),
        KeyValueString(label="Identifier", value=album_id),
    ]
    l = ResourceItem(id=caslogo,type="Image",format="image/svg+xml")
    hcas = HomepageItem(id=cas,type="Text",format="text/html",label="EKWS Fotoarchiv")
    p = ProviderItem(id=gnd, label="Empirische Kulturwissenschaft Schweiz. Fotoarchiv",homepage=[hcas],logo=[l])
    manifest.provider = [p]
    manifest.rights = rights
    manifest.requiredStatement = KeyValueString(label="Attribution", value=attribution)
    manifest.viewingDirection = "left-to-right"
    manifest.behavior = [behavior]
    thumbnail = ResourceItem(id=imageserver+first_image+"/full/80,/0/default.jpg",
                             type="Image",
                             format="image/jpeg")
    thumbnail.make_service(id=imageserver+first_image,
                           type="ImageService3",
                           profile="level2")
    manifest.thumbnail = [thumbnail]
    return manifest

def write_manifest(manifest, manifest_id):
    """Write manifest JSON to the album directory."""
    output_path = f'{album_id}/{manifest_id}{extension}'
    output = open(output_path,'w')
    print(manifest.json(indent=2), file=output)
    print(f"Manifest written to {output_path}")

### Generate individuals and paged manifests
for sequence_file, behavior in manifests_to_generate:
    sequence_suffix = sequence_file.replace("sequence", "").replace(".txt", "")
    manifest_id = f"{album_id}{sequence_suffix}"
    manifest = setup_manifest(manifest_id, behavior)

    canvas_id = 1
    with open(f'{album_id}/{sequence_file}','r') as x:
        for i in x:
            image_name = i.strip()
            image_url = imageserver + image_name
            w, h = fetch_dimensions(image_name)

            canvas = manifest.make_canvas(id=manifestserver + "/" + manifest_id + f"/canvas/p{canvas_id}",
                                          label=image_name,
                                          height=h,
                                          width=w)
            canvas.add_image(image_url=image_url+"/full/max/0/default.jpg",
                             anno_id=manifestserver + "/" + manifest_id + f"/annotation/p{canvas_id}",
                             anno_page_id=manifestserver + "/" + manifest_id + f"/page/p{canvas_id}",
                             format="image/jpeg",
                             height=h,
                             width=w)

            canvas_id +=1

    write_manifest(manifest, manifest_id)

### Generate layers manifest
manifest_id = f"{album_id}_layers"
manifest = setup_manifest(manifest_id, "paged")
manifest.label = {"en": [f"Album {album_id} (Layers)"]}

# Group images: base images start new canvases, _mit_ variants are layers
groups = OrderedDict()
with open(f'{album_id}/sequence.txt','r') as x:
    for i in x:
        image_name = i.strip()
        # Extract base name by splitting on first _mit_
        mit_match = re.search(r'_mit_', image_name)
        if mit_match:
            base = image_name[:mit_match.start()] + ".tif"
            if base in groups:
                groups[base].append(image_name)
            else:
                # _mit_ image without a matching base — treat as its own canvas
                groups[image_name] = [image_name]
        else:
            groups[image_name] = [image_name]

canvas_id = 1
for base_image, layer_images in groups.items():
    image_url = imageserver + base_image
    w, h = fetch_dimensions(base_image)

    canvas = manifest.make_canvas(id=manifestserver + "/" + manifest_id + f"/canvas/p{canvas_id}",
                                  label=base_image,
                                  height=h,
                                  width=w)

    if len(layer_images) == 1:
        # Single image, no layers needed
        canvas.add_image(image_url=image_url+"/full/max/0/default.jpg",
                         anno_id=manifestserver + "/" + manifest_id + f"/annotation/p{canvas_id}",
                         anno_page_id=manifestserver + "/" + manifest_id + f"/page/p{canvas_id}",
                         format="image/jpeg",
                         height=h,
                         width=w)
    else:
        # Multiple layers: use a Choice body so viewers can toggle between them
        choice_items = []
        for layer_name in layer_images:
            lw, lh = fetch_dimensions(layer_name)
            # Derive a readable label from the filename
            label = layer_name.replace(".tif", "").replace(album_id + "_", "")
            item = ResourceItem(id=imageserver + layer_name + "/full/max/0/default.jpg",
                                type="Image", format="image/jpeg",
                                height=lh, width=lw,
                                label={"en": [label]})
            choice_items.append(item)

        choice_body = Choice(items=choice_items)
        anno = Annotation(id=manifestserver + "/" + manifest_id + f"/annotation/p{canvas_id}",
                          type="Annotation", motivation="painting",
                          body=choice_body,
                          target=manifestserver + "/" + manifest_id + f"/canvas/p{canvas_id}")
        anno_page = AnnotationPage(id=manifestserver + "/" + manifest_id + f"/page/p{canvas_id}",
                                   type="AnnotationPage", items=[anno])
        canvas.items = [anno_page]

    canvas_id +=1

write_manifest(manifest, manifest_id)
