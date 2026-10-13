# NAC validation analysis

These scripts analyze fixed released crater circles. They do not detect, segment or extract new craters, and do not import the original morphology method.

- analyze_common68_errors.py recomputes the errors from released paired measurements.
- measure_nac_references.py remeasures native NAC reference domains from the official DTM, with optional confidence and exact-source-grid diagnostics. It retains the original smoothed 36-direction depth definition at the regional annotation center and the descriptor definitions at the catalog circle.
- source_grid_xy.npz contains only the local source-grid XY support coordinates needed to reproduce grid membership. It contains no extraction code or source heights.

Download NAC_DTM_RUMKERDOME.TIF and optional NAC_DTM_RUMKERDOME_CONF.IMG using the links in validation/NAC_common68/metadata.json. Run from the repository root:

```sh
python analysis/NAC_validation/analyze_common68_errors.py --input validation/NAC_common68/per_crater_common68.csv --output recomputed_errors
python analysis/NAC_validation/measure_nac_references.py --nac /path/to/NAC_DTM_RUMKERDOME.TIF --confidence /path/to/NAC_DTM_RUMKERDOME_CONF.IMG --pairs validation/NAC_common68/per_crater_common68.csv --reference-shp reference/CE5_reference_full/CE5_reference_full.shp --source-grid validation/NAC_common68/source_grid_xy.npz --grid-spacing 59.2252938 --output remeasured_NAC
```

Add --include-tin to reproduce the auxiliary TIN volume; it is more expensive and is not the primary grid-volume result. --limit can be used for a smoke check; partial runs are not a 68-crater validation result. Absolute errors use all 68 primary valid pairs. Relative-error statistics use positive references only. Inclinations are center-to-wall angles, not generic GIS surface-gradient slopes. Volumes use the documented projected-area convention; separate ground-area diagnostics are labeled accordingly.
