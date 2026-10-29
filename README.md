# IIIF Manifests for SGV_10 Photo Albums
The purpose of this repository is to develop a script that can generate [IIIF Presentation API 3.0](https://iiif.io/api/presentation/3.0/) resources for photo albums of the SGV_10 Kreis Family Collection.

The photo albums that have been generated are SGV_10A_00031 and SGV_10A_00050.

## Script

`iiif-album.py` generates three Manifests per album (individuals, paged, layers) for both albums in a single run.

### Image sources

The images are no longer taken from a hard coded server. The script tries the image sources configured in `image_sources` at the top of the script, in order, for every file stem (for example `SGV_10A_00031_005_mit_Schutz`). The first source whose `info.json` answers with HTTP 200 is used.

| Source | Status | Image API | Notes |
| --- | --- | --- | --- |
| `memobase` | enabled | 2.x | Memobase (Memoriav) media service. `SGV_10A_00031_005` becomes `sgv-002-SGV_10A_00031_005-1`; loose photographs such as `SGV_10A_00031_09861_r` become `sgv-002-SGV_10P_09861_r-1`. Derivatives with a long side of 2400 px. |
| `self_hosted` | disabled | 3.0 | Placeholder for the full resolution files requested from the EKWS. Set `self_hosted_base` and `enabled` once they are served. |
| `pia_cantaloupe` | disabled | 3.0 | Legacy PIA server (`sipi.participatory-archives.ch`), reachable only via VPN since 2026. |

Why: the PIA image server is no longer public, so the Manifests stopped displaying images. Making the source a configuration choice means the Manifests can be rebuilt on another host without changing their `id`, which is what the published URLs rely on.

Behaviour:

- Image API 2.x services are written as `ImageService2` with `@id` and `@type`, and image bodies as `{service}/full/full/0/default.jpg`. Image API 3.0 services are written as `ImageService3`, with bodies as `{service}/full/max/0/default.jpg`, and `maxArea` is taken into account.
- Dimensions always come from `info.json` and are cached across Manifests. Canvas `height` and `width` come from the default image; each body of a `Choice` carries its own dimensions.
- If an image cannot be resolved from any source, the script stops for that album, lists the missing stems and writes nothing. With `--allow-gaps`, missing images are omitted and reported instead. A Canvas without dimensions is never written.
- Canvas ids keep the number of their position in the sequence file, so the ids of the remaining Canvases do not change when images are omitted.
- In the layers Manifest, a page whose variants are unavailable keeps its default image; a `Choice` reduced to one image is written as a plain image body. The script reports pages with full states, reduced states and a single view.
- `requiredStatement` credits the CAS / EKWS photo archive, Basel, and names the image host(s) actually used. `rights` stays CC BY-NC 4.0 as stated by the owner.

### Running

```bash
cd iiif-photoalbum
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python iiif-album.py                     # both albums, fails if an image is missing
python iiif-album.py --allow-gaps        # omit missing images and report them
python iiif-album.py SGV_10A_00050       # a single album
python validate.py                       # check the generated Manifests
python validate.py --url                 # check the published Manifests
python check_memobase.py                 # probe Memobase, writes memobase_check.csv
```

On Python 3.14, `iiif-prezi3` 1.x pins a Pillow version that has no wheel and fails to build. Install a recent Pillow wheel first and then `pip install --no-deps "iiif-prezi3<2" "pydantic<2" requests jsonschema`. Pillow is not used by the script.

`validate.py` runs three separate checks, because the IIIF Presentation validator checks schema conformance only:

1. Schema: the [IIIF Presentation validator](https://presentation-validator.iiif.io/) (target `okay: 1`). Local files are posted to it; files larger than its request limit are checked against the validator's JSON Schema locally.
2. Images: every image body, thumbnail and service `info.json` answers with HTTP 200.
3. Collections: every Manifest listed in the published Collections is among the generated Manifests.

Whether the chosen layers are meaningful is not checked automatically.

### Known gaps (October 2026)

Memobase holds only the default capture of pages that carry photographs. None of the variants (`_mit_Schutz`, `_mit_Zusatz`, `_mit_Kordel`, `_mit_Zusatzmaterial`) are on Memobase, so the layers Manifests currently contain no `Choice` at all.

- SGV_10A_00031: 35 of 128 images resolved. Missing: pages 032 to 081 (the last third of the album, left empty), all variants, and the verso of the loose photograph 09861. The paged Manifest has 34 of 84 pages.
- SGV_10A_00050: 24 of 71 images resolved. Missing: the even pages 004 to 022, every page from 023 to 038 (odd pages with photographs included), and all variants. The paged Manifest has 14 of 40 pages.

These gaps are expected to close once the EKWS files are served through `self_hosted`.

## Manifests

The Manifests are currently hosted at `https://julsraemy.ch/hostiiing/manifests/{id}`.

- _All scans_: A Manifest containing all digitised pages, with scans of pages with protective film and loose photographs: https://julsraemy.ch/hostiiing/manifests/SGV_10A_00031.json and https://julsraemy.ch/hostiiing/manifests/SGV_10A_00050.json
- _Paged_: A Manifest tagged with the `paged` behavior containing only the digitised pages, i.e. without protective film and loose photographs: https://julsraemy.ch/hostiiing/manifests/SGV_10A_00031_paged.json and https://julsraemy.ch/hostiiing/manifests/SGV_10A_00050_paged.json
- _Layers_: A Manifest containing all digitised pages and the scans with protective film are annotated as layers onto the relevant Canvases: https://julsraemy.ch/hostiiing/manifests/SGV_10A_00031_layers.json and https://julsraemy.ch/hostiiing/manifests/SGV_10A_00050_layers.json

Dedicated IIIF Collections pointing to the above Manifests have also been created:
- https://julsraemy.ch/hostiiing/collections/SGV_10A_00031.json
- https://julsraemy.ch/hostiiing/collections/SGV_10A_00050.json
