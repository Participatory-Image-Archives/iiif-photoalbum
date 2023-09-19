# IIIF Manifests for SGV_10 Photo Albums
The purpose of this repository is to develop a script that can generate [IIIF Presentation API 3.0](https://iiif.io/api/presentation/3.0/) resources for photo albums of the SGV_10 Kreis Family Collection.

The photo albums that have been generated are SGV_10A_00031 and SGV_10A_00050.

With the help of the script and for each object, the first two IIIF Manifests, currently hosted at `https://julsraemy.ch/hosting/manifests/{id}`, have been generated. The third IIIF Manifest is a copy of the second with some alterations described below.

- _All scans_: A Manifest containing all digitised pages, with scans of pages with protective film and loose photographs: https://julsraemy.ch/hostiiing/manifests/SGV_10A_00031.json and https://julsraemy.ch/hostiiing/manifests/SGV_10A_00050.json 
- _Paged_: A Manifest tagged with the `paged` behavior containing only the digitised pages, i.e. without protective film and loose photographs: https://julsraemy.ch/hostiiing/manifests/SGV_10A_00031_paged.json and https://julsraemy.ch/hostiiing/manifests/SGV_10A_00050_paged.json 
- _Layers_:A Manifest containing all digitised pages and the scans with protective film are annotated as layers onto the relevant Canvases: https://julsraemy.ch/hostiiing/manifests/SGV_10A_00031_layers.json and https://julsraemy.ch/hostiiing/manifests/SGV_10A_00050_layers.json

Dedicated IIIF Collections pointing to the above Manifests have also been created: 
- https://julsraemy.ch/hostiiing/collections/SGV_10A_00031.json 
- https://julsraemy.ch/hostiiing/collections/SGV_10A_00050.json
