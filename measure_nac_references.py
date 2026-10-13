"""Remeasure fixed common68 NAC reference domains; no crater detection.

Inputs: official NAC DTM, optional confidence IMG, released paired CSV and
regional reference SHP. Optional source_grid_xy supplies the exact source-grid
coordinates for published resolution diagnostics. Outputs never replace inputs.
"""
import argparse
import json
import math
import warnings
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio
from affine import Affine
from pyproj import CRS, Transformer
from rasterio.features import geometry_mask
from rasterio.windows import Window, from_bounds
from rasterio.warp import reproject, Resampling
from scipy.ndimage import map_coordinates, median_filter
from scipy.spatial import cKDTree
from shapely.geometry import Point, Polygon, box
from shapely.ops import transform as geom_transform

MERC = None
DRIFT = None
class LocalRaster:
    def __init__(self, dataset, merc_bounds, scale=1):
        self.dataset = dataset
        self.transformer = Transformer.from_crs(MERC, dataset.crs, always_xy=True)
        bx = geom_transform(self.transformer.transform, box(*merc_bounds)).bounds
        pix = from_bounds(*bx, transform=dataset.transform)
        col, row = math.floor(pix.col_off)-3, math.floor(pix.row_off)-3
        endcol, endrow = math.ceil(pix.col_off+pix.width)+3, math.ceil(pix.row_off+pix.height)+3
        self.window = Window(col,row,endcol-col,endrow-row)
        self.affine = dataset.window_transform(self.window)
        a = dataset.read(1, window=self.window, boundless=True, masked=True)
        self.data = a.astype('float64').filled(np.nan)*scale
        self.crs = dataset.crs

    def sample(self, xs, ys):
        xs,ys = self.transformer.transform(np.asarray(xs),np.asarray(ys))
        cols,rows = (~self.affine)*(xs,ys)
        coords = np.array([np.asarray(rows)-.5,np.asarray(cols)-.5])
        values = map_coordinates(np.nan_to_num(self.data,nan=0), coords, order=1, mode='constant', cval=0)
        support = map_coordinates(np.isfinite(self.data).astype(float), coords, order=1, mode='constant', cval=0)
        values[support < .999999] = np.nan
        return values

    def coverage(self, merc_polygon):
        native = geom_transform(self.transformer.transform, merc_polygon)
        mask = geometry_mask([mapping(native)], self.data.shape, transform=self.affine, invert=True)
        return float(np.isfinite(self.data)[mask].mean()) if mask.any() else 0

def measure(raster, cx, cy, radius, step, ring=(.75,1.25), smooth=False):
    angles = np.arange(36)*2*np.pi/36
    distance = np.linspace(ring[0]*radius,ring[1]*radius,max(3,math.ceil((ring[1]-ring[0])*radius/step)+1))
    xx = cx + np.cos(angles)[:,None]*distance
    yy = cy + np.sin(angles)[:,None]*distance
    z = raster.sample(xx.ravel(),yy.ravel()).reshape(xx.shape)
    if smooth and z.shape[1]>=3:
        z = median_filter(z,size=(1,3),mode='nearest')
    ok = np.isfinite(z).all(axis=1)
    peaks = np.full(36,np.nan)
    peak_dist = np.full(36,np.nan)
    for a in np.where(ok)[0]:
        j=np.argmax(z[a]); peaks[a]=z[a,j]; peak_dist[a]=distance[j]
    center=float(raster.sample([cx],[cy])[0])
    rim=float(np.nanmedian(peaks)) if ok.any() else math.nan
    # Secondary floor definition for sensitivity, not silently substituted.
    grid = np.linspace(-.25*radius,.25*radius,max(3,math.ceil(.5*radius/step)+1))
    gx,gy=np.meshgrid(grid,grid); inside=gx*gx+gy*gy<=(.25*radius)**2
    floor=raster.sample(cx+gx[inside],cy+gy[inside]); validfloor=floor[np.isfinite(floor)]
    floorp05=float(np.percentile(validfloor,5)) if len(validfloor) else math.nan
    return {'depth':rim-center,'floor_p05_depth':rim-floorp05,'center':center,'rim':rim,
            'directions':int(ok.sum()),'diameter':2*float(np.nanmedian(peak_dist)) if ok.any() else math.nan,
            'rim_peaks':peaks,'peak_distances':peak_dist}

def raster_points(local):
    row,col=np.indices(local.data.shape)
    xx,yy=local.affine*(col+.5,row+.5)
    to_merc=Transformer.from_crs(local.crs,MERC,always_xy=True)
    x,y=to_merc.transform(xx,yy)
    if getattr(local,'preserve_pointcloud_rounding',False):
        # Map to actual cached TXT floats, not an independently reconstructed
        # decimal lattice: sub-ULP differences can change boundary membership.
        target=np.column_stack(((x-DRIFT[0]).ravel(),(y-DRIFT[1]).ravel()))
        distance,index=local.source_point_tree.query(target)
        original=local.source_point_xy[index]
        found=(distance<1).reshape(x.shape)
        # Outside the original source footprint, do not fold lattice nodes onto
        # the closest boundary point: that would corrupt coverage denominators.
        matched_xy=np.where(found.ravel()[:,None],original,target)
        local.pointcloud_xy=(matched_xy[:,0].reshape(x.shape),matched_xy[:,1].reshape(y.shape))
        local.data[~found]=np.nan
        x=DRIFT[0]+local.pointcloud_xy[0]; y=DRIFT[1]+local.pointcloud_xy[1]
    latitude=Transformer.from_crs(local.crs,CRS.from_user_input(local.crs).geodetic_crs,always_xy=True).transform(xx,yy)[1]
    latitude=np.deg2rad(latitude)
    cell=abs(local.affine.a*local.affine.e)
    # Only use these checked projection parameters for the analytic Jacobian;
    # retain the full WKT for transformations and geospatial outputs.
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore',message='You will likely lose important projection information.*')
        params=local.crs.to_dict()
    proj=params.get('proj')
    if proj=='eqc':
        latts=np.deg2rad(float(params.get('lat_ts',40)))
        physical=cell*np.cos(latitude)/np.cos(latts)
        maparea=cell*np.cos(np.deg2rad(44.1))**2/(np.cos(latts)*np.cos(latitude))
    elif proj=='merc':
        maparea=np.full_like(x,cell)
        physical=cell*(np.cos(latitude)/np.cos(np.deg2rad(44.1)))**2
    else: raise ValueError('Unsupported lunar projection for pixel area')
    return x,y,maparea,physical

def descriptor(local,cx,cy,cz,radius,confidence=None):
    x,y,area,physical=raster_points(local); z=local.data
    if getattr(local,'preserve_pointcloud_rounding',False):
        lc=local.catalog_local_center
        dx=local.pointcloud_xy[0]-lc[0]; dy=local.pointcloud_xy[1]-lc[1]
    else: dx=x-cx; dy=y-cy
    rr=np.sqrt(dx**2+dy**2); angle=np.mod(np.arctan2(dy,dx),2*np.pi)
    valid=np.isfinite(z)
    def mask(a,b): return valid&(rr>=a*radius)&(rr<=b*radius)
    def coverage(a,b):
        m=(rr>=a*radius)&(rr<=b*radius)
        return valid[m].mean() if m.any() else 0
    rim=mask(.75,1.25); peaks=[]; radii=[]; peak_good=[]
    for j in range(36):
        m=rim&(angle>=j*2*np.pi/36)&(angle<(j+1)*2*np.pi/36)
        if not m.any(): continue
        inds=np.flatnonzero(m); best=inds[np.argmax(z.ravel()[inds])]
        peaks.append(z.ravel()[best]); radii.append(rr.ravel()[best])
        if confidence is not None: peak_good.append(10<=confidence.ravel()[best]<=15)
    # Match the existing sector-maximum definition, including its sparse fallback.
    if len(peaks)<8:
        peaks=z[rim].tolist(); radii=rr[rim].tolist()
    ze=float(np.median(peaks)) if len(peaks) else np.nan
    reference=mask(1.05,1.5); ref=float(np.median(z[reference])) if reference.any() else np.nan
    inside=mask(0,1); wall=mask(.35,1); floor=mask(0,.25); rimvol=mask(1,1.05)&(rr>radius)
    slopes=np.degrees(np.arctan2(np.maximum(z[wall]-cz,0),rr[wall]+1e-8))
    floor_std=float(np.std(z[floor])) if floor.sum()>3 else np.nan
    out={'center':cz,'rim_elevation':ze,'reference_elevation':ref,
         'rim_sector_count':len(peaks),'floor_pixel_count':int(floor.sum()),
         'wall_pixel_count':int(wall.sum()),'rim_volume_pixel_count':int(rimvol.sum()),
         'context_valid_fraction':coverage(0,1.5),'floor_valid_fraction':coverage(0,.25),
         'crater_valid_fraction':coverage(0,1),
         'wall_valid_fraction':coverage(.35,1),'reference_valid_fraction':coverage(1.05,1.5),
         'rim_valid_fraction':coverage(.75,1.25),
         'depth_scaled':max(ze-cz,0),'mean_slope':float(slopes.mean()) if len(slopes) else np.nan,
         'max_slope':float(slopes.max()) if len(slopes) else np.nan,
         'slope_std':float(slopes.std()) if len(slopes) else np.nan,
         'high_slope_fraction':float(np.mean(slopes>20)) if len(slopes) else np.nan,
         'rim_height_signed':ze-ref,'rim_height':max(ze-ref,0),
         'crater_volume':float(np.sum(np.maximum(ref-z[inside],0)*area[inside])),
         'crater_volume_ground_area':float(np.sum(np.maximum(ref-z[inside],0)*physical[inside])),
         'rim_volume':float(np.sum(np.maximum(z[rimvol]-ref,0)*area[rimvol])),
         'rim_volume_ground_area':float(np.sum(np.maximum(z[rimvol]-ref,0)*physical[rimvol])),
         'floor_rms':floor_std,'relief':float(np.ptp(z[inside])) if inside.any() else np.nan,
         'rim_radius_std':float(np.std(radii)) if len(radii)>1 else 0,
         'circularity':max(0,1-np.std(radii)/(np.mean(radii)+1e-8)) if len(radii) else np.nan,
         'rim_success_fraction':float(np.mean(peak_good)) if peak_good else np.nan}
    if confidence is not None:
        for name,m in [('floor',floor),('wall',wall),('reference',reference),('crater',inside),('rim_volume',rimvol)]:
            out[name+'_confidence_success_fraction']=float(np.mean((confidence[m]>=10)&(confidence[m]<=15))) if m.any() else np.nan
    # Do not report values from partially missing measurement domains as complete.
    for key,needed in [('crater_volume',['context_valid_fraction']),('rim_height',['rim_valid_fraction','reference_valid_fraction']),
                       ('rim_volume',['reference_valid_fraction','context_valid_fraction']),('relief',['crater_valid_fraction']),
                       ('floor_rms',['floor_valid_fraction']),('mean_slope',['wall_valid_fraction']),
                       ('max_slope',['wall_valid_fraction']),('slope_std',['wall_valid_fraction']),('high_slope_fraction',['wall_valid_fraction'])]:
        if any(out[n]<.995 for n in needed): out[key]=np.nan
    for key in ['crater_volume','rim_volume']:
        if not np.isfinite(out[key]): out[key+'_ground_area']=np.nan
    if not np.isfinite(out['rim_height']): out['rim_height_signed']=np.nan
    if out['reference_valid_fraction']<.995:
        out['partial_domain_reference_elevation']=out['reference_elevation']
        out['reference_elevation']=np.nan
    return out,(x,y,rr,area)

def positive_triangle_integral(vertices,heights):
    """Exact integral of max(linear height,0) over a planar triangle."""
    p=[(np.array(v,float),float(h)) for v,h in zip(vertices,heights)]
    q=[]
    for a,b in zip(p,p[1:]+p[:1]):
        if a[1]>=0: q.append(a)
        if (a[1]>=0)!=(b[1]>=0):
            t=a[1]/(a[1]-b[1]); q.append((a[0]+t*(b[0]-a[0]),0.0))
    if len(q)<3: return 0.0
    total=0.0
    for i in range(1,len(q)-1):
        vs=np.array([q[0][0],q[i][0],q[i+1][0]])
        area=abs(np.cross(vs[1]-vs[0],vs[2]-vs[0]))/2
        total+=area*(q[0][1]+q[i][1]+q[i+1][1])/3
    return float(total)

def tin_volume(local,cx,cy,radius,reference):
    """Piecewise-linear TIN below a plane, clipped to a 512-sided circle approximation.

    Grid cells become two triangles. Partial positive/negative triangles are
    clipped at the reference plane, and boundary triangles at the circle. This
    adapts the reference-plane/TIN principle, not the paper's watershed V/A depth.
    """
    x,y,_,_=raster_points(local); z=local.data
    base=np.arange(z.size).reshape(z.shape)
    sets=[(base[:-1,:-1],base[:-1,1:],base[1:,1:]),
          (base[:-1,:-1],base[1:,1:],base[1:,:-1])]
    total=0.0; bound=Point(0,0).buffer(radius,resolution=128)
    flat=np.column_stack((x.ravel()-cx,y.ravel()-cy)); zz=z.ravel()
    for a,b,c in sets:
        ids=np.column_stack((a.ravel(),b.ravel(),c.ravel()))
        v=flat[ids]; h=reference-zz[ids]
        dist=np.hypot(v[:,:,0],v[:,:,1]); edge=np.max(np.linalg.norm(v-np.roll(v,1,axis=1),axis=2),axis=1)
        finite=np.isfinite(h).all(axis=1)
        whole=finite&(dist.max(axis=1)<=radius)
        whollypositive=whole&(h.min(axis=1)>=0)
        areas=np.abs(np.cross(v[:,1]-v[:,0],v[:,2]-v[:,0]))/2
        total+=float(np.sum(areas[whollypositive]*h[whollypositive].mean(axis=1)))
        crossing=whole&(h.max(axis=1)>0)&(h.min(axis=1)<0)
        for j in np.where(crossing)[0]: total+=positive_triangle_integral(v[j],h[j])
        near=finite&~whole&(dist.min(axis=1)<=radius+edge)&(h.max(axis=1)>0)
        for j in np.where(near)[0]:
            poly=Polygon(v[j]).intersection(bound)
            if poly.is_empty: continue
            if poly.geom_type!='Polygon': continue
            coord=np.asarray(poly.exterior.coords)[:-1]
            # Linear heights in original TIN triangle, then fan triangulation.
            beta=np.linalg.solve(np.column_stack((v[j],np.ones(3))),h[j])
            height=np.column_stack((coord,np.ones(len(coord))))@beta
            for t in range(1,len(coord)-1):
                ix=[0,t,t+1]; total+=positive_triangle_integral(coord[ix],height[ix])
    return total

def downgrade_to_point_grid(nac,low_dataset,bounds):
    """Area-average NAC onto the ACTUAL source point-cloud grid.

    The TXT assigns (col*s,-row*s), i.e. pixel corner coordinates in the original
    TIFF, not its cell centers. This convention is retained, not silently fixed.
    Averaging cells here are centered on those points. A separate standard TIFF
    grid control is also output by main().
    """
    s=low_dataset.res[0]
    c0=math.floor((bounds[0]-DRIFT[0])/s)-3; c1=math.ceil((bounds[2]-DRIFT[0])/s)+3
    r0=math.floor((DRIFT[1]-bounds[3])/s)-3; r1=math.ceil((DRIFT[1]-bounds[1])/s)+3
    a=Affine(s,0,DRIFT[0]+(c0-.5)*s,0,-s,DRIFT[1]-(r0-.5)*s)
    arr=np.full((r1-r0,c1-c0),np.nan)
    reproject(nac.data,arr,src_transform=nac.affine,src_crs=nac.crs,src_nodata=np.nan,
              dst_transform=a,dst_crs=MERC,dst_nodata=np.nan,resampling=Resampling.average)
    result=object.__new__(LocalRaster)
    result.data,result.affine,result.crs=arr,a,MERC
    result.transformer=Transformer.from_crs(MERC,MERC,always_xy=True)
    result.preserve_pointcloud_rounding=True
    return result

def main():
    global MERC, DRIFT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--nac', required=True, type=Path)
    parser.add_argument('--pairs', required=True, type=Path)
    parser.add_argument('--reference-shp', required=True, type=Path)
    parser.add_argument('--confidence', type=Path)
    parser.add_argument('--source-grid', type=Path)
    parser.add_argument('--grid-spacing', type=float, default=59.2252938)
    parser.add_argument('--include-tin', action='store_true')
    parser.add_argument('--limit', type=int, default=68, help='Smaller values are diagnostic smoke checks only.')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        raise FileExistsError('Choose a new output directory.')
    pairs = pd.read_csv(args.pairs)
    if len(pairs) != 68 or not pairs.truth_id.is_unique or 1505 in set(pairs.truth_id):
        raise ValueError('Use the released common68 paired CSV.')
    if not 1 <= args.limit <= 68:
        raise ValueError('--limit must be between 1 and 68.')
    truth = gpd.read_file(args.reference_shp)
    if len(truth) != 3398:
        raise ValueError('Use the unfiltered 3398-row regional reference SHP; IDs retain original row order.')
    MERC = CRS.from_user_input(truth.crs)
    k = 1737400 * math.cos(math.radians(44.1))
    DRIFT = (k * math.radians(-69), k * math.log(math.tan(math.pi / 4 + math.radians(45) / 2)))
    xy = None
    if args.source_grid:
        xy = np.load(args.source_grid)['xy']
        tree = cKDTree(xy)
    confidence = rasterio.open(args.confidence) if args.confidence else None
    rows = []
    try:
        with rasterio.open(args.nac) as dataset:
            for index, r in pairs.head(args.limit).iterrows():
                cx, cy, radius = r.catalog_center_x, r.catalog_center_y, r.raw_ours_radius
                center = truth.geometry.iloc[int(r.truth_id) - 1].centroid
                tx, ty, tr = center.x, center.y, r.truth_diameter_m / 2
                a, b = Point(cx, cy).buffer(1.85 * radius).bounds, Point(tx, ty).buffer(1.8 * tr).bounds
                bounds = (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))
                native = LocalRaster(dataset, bounds, 1.0)
                codes = None
                if confidence:
                    if confidence.crs != dataset.crs or not np.allclose(tuple(confidence.transform), tuple(dataset.transform), rtol=0, atol=1e-6):
                        raise ValueError('Confidence raster must use the same grid as the DTM.')
                    codes = confidence.read(1, window=native.window, boundless=True, fill_value=0)
                d, _ = descriptor(native, cx, cy, float(native.sample([cx], [cy])[0]), radius, codes)
                previous = measure(native, tx, ty, tr, 5, smooth=True)
                row = {'truth_id': int(r.truth_id), 'source_row': int(r.source_row), 'nac_depth_previous_m': previous['depth']}
                row.update({'nac_' + key: value for key, value in d.items()})
                if args.include_tin:
                    row['nac_tin_volume'] = tin_volume(native, cx, cy, radius, d['reference_elevation']) if d['context_valid_fraction'] >= .995 else np.nan
                if xy is not None:
                    coarse = downgrade_to_point_grid(native, SimpleNamespace(res=(args.grid_spacing, args.grid_spacing)), bounds)
                    coarse.catalog_local_center = (r.raw_ours_x, r.raw_ours_y)
                    coarse.source_point_xy, coarse.source_point_tree = xy, tree
                    c, _ = descriptor(coarse, cx, cy, float(coarse.sample([cx], [cy])[0]), radius)
                    row.update({'coarse_' + key: value for key, value in c.items()})
                rows.append(row)
                print('NAC reference', index + 1, '/', args.limit, 'truth_id', int(r.truth_id), flush=True)
    finally:
        if confidence:
            confidence.close()
    args.output.mkdir(parents=True, exist_ok=True)
    result = pd.DataFrame(rows)
    result.to_csv(args.output / 'remeasured_references.csv', index=False, encoding='utf-8-sig')
    differences = {}
    for column in result.columns:
        if column not in pairs.columns or column in ['truth_id', 'source_row']:
            continue
        a = result[column].to_numpy(dtype=float)
        b = pairs.head(args.limit)[column].to_numpy(dtype=float)
        valid = np.isfinite(a) & np.isfinite(b)
        differences[column] = {'valid_n': int(valid.sum()), 'maximum_absolute_difference': float(np.max(np.abs(a[valid] - b[valid]))) if valid.any() else None}
    (args.output / 'comparison_to_released_references.json').write_text(json.dumps(differences, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
