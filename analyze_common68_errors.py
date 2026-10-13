"""Recompute published NAC common68 errors from released paired measurements.

No crater detection, boundary extraction or private algorithm import is used.
Example: python analyze_common68_errors.py --input per_crater_common68.csv --output analysis_outputs
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


PARAMETERS = ['depth', 'mean_slope', 'max_slope', 'crater_volume', 'rim_height', 'floor_rms', 'relief']


def error_statistics(reference, estimate):
    reference = np.asarray(reference, dtype=float)
    estimate = np.asarray(estimate, dtype=float)
    valid = np.isfinite(reference) & np.isfinite(estimate)
    reference, estimate = reference[valid], estimate[valid]
    if not len(reference):
        return {'n': 0, 'n_relative': 0}
    difference = estimate - reference
    absolute = np.abs(difference)
    positive = reference > 1e-9
    relative = 100 * absolute[positive] / reference[positive]
    results = {'n': int(len(reference)), 'n_relative': int(positive.sum()),
               'bias': float(difference.mean()), 'mae': float(absolute.mean()),
               'rmse': float(np.sqrt(np.mean(difference ** 2))),
               'median_absolute_error': float(np.median(absolute)),
               'median_absolute_percent_error': float(np.median(relative)) if len(relative) else None,
               'mean_absolute_percent_error': float(relative.mean()) if len(relative) else None,
               'maximum_absolute_error': float(absolute.max())}
    for threshold in [10, 15, 20]:
        count = int((relative > threshold).sum())
        results[f'over{threshold}_count'] = count
        results[f'over{threshold}_percent_of_relative_sample'] = 100 * count / len(relative) if len(relative) else None
        results[f'over{threshold}_percent_of_all_valid_pairs'] = 100 * count / len(reference)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    data = pd.read_csv(args.input)
    if len(data) != 68 or not data.truth_id.is_unique or not data.source_row.is_unique:
        raise ValueError('Expected exactly 68 unique matched craters.')
    required = ['nac_depth_previous_m'] + ['nac_' + name for name in PARAMETERS if name != 'depth']
    if not np.isfinite(data[required].to_numpy(dtype=float)).all():
        raise ValueError('All primary NAC references must be finite in the common68 cohort.')
    results = {}
    for name in PARAMETERS:
        reference = data.nac_depth_previous_m if name == 'depth' else data['nac_' + name]
        results[name] = error_statistics(reference, data['raw_ours_' + name])
        if results[name]['n'] != 68:
            raise ValueError('All primary absolute-error metrics must use 68 pairs.')
    if not (data.truth_diameter_m > 0).all():
        raise ValueError('Reference diameters must be positive.')
    results['depth_diameter'] = error_statistics(
        data.nac_depth_previous_m / data.truth_diameter_m, data.raw_ours_depth_diameter)
    args.output.mkdir(parents=True, exist_ok=True)
    targets = [args.output / 'error_summary.json', args.output / 'error_summary.csv']
    if any(path.exists() for path in targets):
        raise FileExistsError('Choose a new output directory to preserve existing results.')
    targets[0].write_text(json.dumps({'cohort_n': 68, 'primary_errors': results}, indent=2), encoding='utf-8')
    pd.DataFrame([{'parameter': name, **values} for name, values in results.items()]).to_csv(
        targets[1], index=False, encoding='utf-8-sig')
    print('Verified 68 paired measurements. Depth MAE/RMSE:',
          round(results['depth']['mae'], 2), round(results['depth']['rmse'], 2))


if __name__ == '__main__':
    main()
