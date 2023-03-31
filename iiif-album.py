from iiif_prezi3 import config, Manifest, KeyValueString, ResourceItem, ProviderItem, ExternalItem, HomepageItem

### IIIF Resource Servers
sipi = "http://sipi.participatory-archives.ch/SGV_10/album/"
manifestserver = "https://julsraemy.ch/hostiiing/manifests"
manifestid = "SGV_10A_00050"
extension = ".json"

### SGV Photo Archive Website and GND
sgvlogo = "https://sipi.participatory-archives.ch/SGV_logo.jp2/full/max/0/default.jpg"
sgv = "https://archiv.sgv-sstp.ch/"
gnd = "https://d-nb.info/gnd/1186091584"

### Language maps only in English
config.configs['helpers.auto_fields.AutoLang'].auto_lang = "en"

### Creation of the Manifest
manifest = Manifest(id=manifestserver+"/"+manifestid+extension,
                    label="Album SGV_10A_00050")

### Summary of the Resource
manifest.summary = ("A very nice album of the SGV_10 Familie Kreis Collection")

### Appending descriptive Metadata
manifest.metadata = [
    KeyValueString(label="Title", value="Photo Album SGV_10A_00050"),
    KeyValueString(label="Collection", value="SGV_10 Familie Kreis"),
    KeyValueString(label="Identifier", value="SGV_10A_00050"),
]   

### Appending provider
l = ResourceItem(id=sgvlogo,type="Image",format="image/jpg",height=149,width=500)
hsgv = HomepageItem(id=sgv,type="Text",format="text/html",label="SGV Fotoarchiv")
p = ProviderItem(id=gnd, label="Schweizerische Gesellschaft für Volkskunde. Fotoarchiv",homepage=[hsgv],logo=[l])
manifest.provider = [p]

### Rights and Required Statement
manifest.rights = "http://creativecommons.org/licenses/by-nc/4.0/"
manifest.requiredStatement = KeyValueString(label="Attribution", value="Swiss Society for Folklore Studies (SSFS)")

### Left-to-right
manifest.viewingDirection = "left-to-right"
manifest.behavior = ["paged"]

### Thumbnail

thumbnail = ResourceItem(id=sipi+"SGV_10A_00050_001.jp2/full/80,/0/default.jpg",
                         type="Image",
                         format="image/jpeg")

thumbnail.make_service(id=sipi+"SGV_10A_00050_001.jp2",
                       type="ImageService3",
                       profile="level2")

manifest.thumbnail = [thumbnail]

# Canvases

with open('sequence.txt','r') as x:
    for i in x:
        canvas = manifest.make_canvas_from_iiif(url=sipi+f"{i}",
                                        label=f"{i}",
                                        id=manifestserver + f"/canvas/p{i}",
                                        anno_id=manifestserver + f"/annotation/p{i}-image",
                                        anno_page_id=manifestserver + f"/page/p{i}/1")

output = open(manifestid+extension,'w')
print(manifest.json(indent=2), file=output)