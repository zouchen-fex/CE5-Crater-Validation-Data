# CE-5 Crater Data and NAC Morphometric Validation

Download all three packages and extract them into the same parent directory. Each archive contributes folders to `CE5_Crater_Validation_Data`; no files overlap between packages. The folders and commands below refer to that extracted directory.

- [Regional reference annotations](CE5_reference_data_20261013.zip)
- [Crater results, evaluation, sensitivity and catalog comparisons](CE5_results_evaluation_20261013.zip)
- [Common68 NAC validation data, analysis code and metadata](NAC_common68_validation_20261013.zip)

Selected NAC tables and the two public analysis scripts are also available separately for inspection. To remeasure NAC references, extract both the reference and NAC packages. The original large NAC DEM is available from the official download link below.


This repository contains regional reference annotations, crater outlines, DEM-derived morphometric descriptors, evaluation records, cloth-resolution experiment outputs, and the common 68-crater LROC NAC validation dataset.

## Data folders

| Folder | Content |
| --- | --- |
| reference | Full regional annotations (3,398) and the evaluation subset (1,079) |
| results/CE5_catalog | Morphometric catalog (6,667 craters, diameter >=350 m), CSV, GeoPackage and SHP outlines |
| evaluation | Evaluation predictions (1,064), exclusive IoU matches, TP/FP/FN and summary metrics |
| sensitivity | Regional 25/30/45/60 m detection results and separately reported stage timings |
| comparison | Three separate matched depth/d/D comparisons (375/318/315 pairs) |
| validation/NAC_common68 | Latest common 68-crater measurements, errors, GIS circles and official NAC download links |
| analysis/NAC_validation | Public NAC validation analysis; crater detection/segmentation/extraction source is not included |

## Coordinates, fields and versions

The CRS is lunar Mercator with sphere radius 1,737,400 m and standard parallel 44.1 degrees. This is not terrestrial WGS84. Coordinate units are metres; lunar longitude and latitude are degrees. The morphology CSV local x/y origin is (-69 degrees,45 degrees); GIS geometry uses absolute projected coordinates. D_m/r_m are diameter/radius in metres, Diam_km is diameter in kilometres. Depth, rim height, floor RMS and relief are metres; inclination is degrees, volume is projected cubic metres, and d/D is dimensionless.

The morphology CSV preserves both depth and depth_scaled as existing result fields; depth_scaled is the adjusted morphometric-depth descriptor and is not a second independent depth reference. The NAC primary depth comparison uses raw_ours_depth and nac_depth_previous_m as documented in that dataset. Do not silently substitute columns. Full geometry attributes are in GeoPackage/CSV; compact SHP attributes link through stable IDs.

The morphology catalog and the original precision-evaluation predictions are distinct result versions. Their counts and purposes are recorded separately. The evaluation subset uses both diameters >=0.35 km and inclusive longitudes -69 to -65 degrees. Footprint IoU must be strictly greater than the threshold. Matches are assigned by descending IoU, each prediction/reference at most once. Match indices are zero-based rows in the released evaluation datasets.

The NAC geometry is the existing predicted catalog circle, not a newly traced high-resolution crater rim. Selection of the common68 cohort depends on valid measurement domains, not an error threshold. Relative errors require positive reference values. Same-SLDEM2015 public-catalog comparisons are extraction-consistency evidence, not independent absolute topographic accuracy validation. Each comparison uses its own documented sample.

## LROC NAC DEM

- Product: https://data.lroc.im-ldi.com/lroc/view_rdr/NAC_DTM_RUMKERDOME
- GeoTIFF: https://pds.lroc.im-ldi.com/data/LRO-L-LROC-5-RDR-V1.0/LROLRC_2001/DATA/SDP/NAC_DTM/RUMKERDOME/NAC_DTM_RUMKERDOME.TIF
- Wang catalog: https://doi.org/10.5281/zenodo.4983248

The 5 m Mons Rumker DTM mosaic covers part of the CE-5 study region. Original large DEMs and third-party global catalogs are referenced rather than redistributed. The regional reference annotations are released separately from the public Wang kilometer-scale depth catalog.

## Recompute the paired-measurement errors

```sh
python analysis/NAC_validation/analyze_common68_errors.py --input validation/NAC_common68/per_crater_common68.csv --output recomputed_errors
```

The analysis writes to a new output directory and does not modify released input data. Checksums and record counts are supplied in metadata. CE-6, detection code, Fast-PGS/CSF implementations, crater-rim search/NMS code, and original morphology-extraction source are excluded.
