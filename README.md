# IIIF Manifests for SGV_10 Photo Albums
The purpose of this repository is to develop a script that can generate [IIIF Presentation API 3.0](https://iiif.io/api/presentation/3.0/) resources for photo albums of the SGV_10 Kreis Family Collection.

With the help of the script, the following IIIF Manifests, currently hosted at `https://julsraemy.ch/hosting/manifests/{id}`, have been generated and sometimes slithly altered (like the Manifest with layers).

- A Manifest containing all digitised pages, with scans of pages with protective film and loose photographs: https://julsraemy.ch/hostiiing/manifests/SGV_10A_00050.json 
- A Manifest tagged with the `paged` behavior containing only the digitised pages, i.e. without protective film and loose photographs: https://julsraemy.ch/hostiiing/manifests/SGV_10A_00050_paged.json 
- A Manifest containing all digitised pages and the scans with protective film are annotated as layers onto the relevant Canvases: https://julsraemy.ch/hostiiing/manifests/SGV_10A_00050_layers.json (`in progress`)

A dedicated IIIF Collection pointing to the above Manifests has also been created: https://julsraemy.ch/hostiiing/collections/SGV_10A_00050.json
