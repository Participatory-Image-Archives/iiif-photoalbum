# IIIF Manifests for SGV_10 Photo Albums
The purpose of this repository is to develop a script that can generate [IIIF Presentation API 3.0](https://iiif.io/api/presentation/3.0/) resources for photo albums of the SGV_10 Kreis Family Collection.

The photo albums that have been generated are SGV_10A_00031 and SGV_10A_00050.

## Script

The `iiif-album.py` script was rewritten to accommodate the migration from a Sipi (IIIF Image API 2.1) to a Cantaloupe (IIIF Image API 3.0) server. Key changes include:

- The script now fetches `info.json` for each image and accounts for the `maxArea` constraint when calculating canvas and image dimensions
- All three manifest types (individuals, paged, layers) are generated in a single run
- Image dimensions are cached across manifests to avoid redundant API calls
- Configurable variables at the top of the script allow easy switching between albums
- Graceful error handling: if an image's `info.json` is unavailable, the canvas is still created

The script requires a virtual environment with the dependencies listed in `requirements.txt`:

```bash
cd iiif-photoalbum
source venv/bin/activate
pip install -r requirements.txt
python iiif-album.py
```

## Manifests

The Manifests are currently hosted at `https://julsraemy.ch/hostiiing/manifests/{id}`.

- _All scans_: A Manifest containing all digitised pages, with scans of pages with protective film and loose photographs: https://julsraemy.ch/hostiiing/manifests/SGV_10A_00031.json and https://julsraemy.ch/hostiiing/manifests/SGV_10A_00050.json
- _Paged_: A Manifest tagged with the `paged` behavior containing only the digitised pages, i.e. without protective film and loose photographs: https://julsraemy.ch/hostiiing/manifests/SGV_10A_00031_paged.json and https://julsraemy.ch/hostiiing/manifests/SGV_10A_00050_paged.json
- _Layers_: A Manifest containing all digitised pages and the scans with protective film are annotated as layers onto the relevant Canvases: https://julsraemy.ch/hostiiing/manifests/SGV_10A_00031_layers.json and https://julsraemy.ch/hostiiing/manifests/SGV_10A_00050_layers.json

Dedicated IIIF Collections pointing to the above Manifests have also been created:
- https://julsraemy.ch/hostiiing/collections/SGV_10A_00031.json
- https://julsraemy.ch/hostiiing/collections/SGV_10A_00050.json
