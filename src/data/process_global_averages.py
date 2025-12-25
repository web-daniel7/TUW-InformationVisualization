import argparse
import os
import numpy as np
import pandas as pd
import pygrib
import geopandas as gpd
from shapely import Point
from tqdm import tqdm
from typing import Dict, List, Any

# --- Configuration ---
CACHE_DIR = "data/processed/global"
SHAPEFILE_PATH = 'data/natural_earth_110m/ne_110m_admin_0_countries.shp'


def create_country_mapping(lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    """Creates a mapping from grid to ISO_A3 codes using a spatial join."""
    print(f"Creating country mapping for grid {lats.shape}...")
    countries_gdf = gpd.read_file(SHAPEFILE_PATH)[['ADM0_A3', 'geometry']]

    # Handle longitudes > 180
    lons_norm = np.where(lons > 180, lons - 360, lons)

    points_geom = [Point(lon, lat) for lon, lat in zip(lons_norm.flatten(), lats.flatten())]
    points_gdf = gpd.GeoDataFrame(geometry=points_geom, crs="EPSG:4326")

    joined_gdf = gpd.sjoin(points_gdf, countries_gdf, how='left')
    iso_codes = joined_gdf['ADM0_A3'].fillna('XXX').astype(str).values
    return iso_codes.reshape(lats.shape)


def get_buffer_data(buffer: List[Any], iso_map: np.ndarray) -> List[Dict]:
    """Process a timestep buffer, compute derived vars, and return row dicts."""
    results = []
    vars_dict = {grb.shortName: grb for grb in buffer}

    # 1. Derive Wind Speed (10u, 10v -> 10si)
    if '10u' in vars_dict and '10v' in vars_dict:
        u_grb, v_grb = vars_dict['10u'], vars_dict['10v']
        speed = np.sqrt(u_grb.values ** 2 + v_grb.values ** 2)

        # Masking and Averaging
        mask = (iso_map != 'XXX') & ~np.isnan(speed)
        if hasattr(u_grb, 'missingValue'):
            mask &= (speed != u_grb.missingValue)

        df = pd.DataFrame({'code': iso_map[mask], 'val': speed[mask]})
        avgs = df.groupby('code')['val'].mean().to_dict()

        year = u_grb.validDate.year
        month = u_grb.validDate.month

        for country, val in avgs.items():
            results.append({'year': year, 'month': month, 'country_code': country,
                            'value': val, 'variable': '10si'})

        del vars_dict['10u']
        del vars_dict['10v']

    # 2. Process remaining variables
    for name, grb in vars_dict.items():
        vals = grb.values
        if name == 'sde': vals = np.maximum(vals, 0)  # Snow depth fix

        mask = (iso_map != 'XXX') & ~np.isnan(vals)
        if hasattr(grb, 'missingValue'):
            mask &= (vals != grb.missingValue)

        df = pd.DataFrame({'code': iso_map[mask], 'val': vals[mask]})
        avgs = df.groupby('code')['val'].mean().to_dict()

        year = grb.validDate.year
        month = grb.validDate.month

        for country, val in avgs.items():
            results.append({'year': year, 'month': month, 'country_code': country,
                            'value': val, 'variable': name})

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("data_path", type=str)
    args = parser.parse_args()

    os.makedirs(CACHE_DIR, exist_ok=True)

    grbs = pygrib.open(args.data_path)

    # Init Grid and Map
    first = grbs.message(1)
    lats, lons = first.latlons()

    # Cache the heavy spatial join
    iso_map = create_country_mapping(lats, lons)

    # Process Stream
    grbs.seek(0)
    buffer = []
    curr_time = None
    all_data = []

    print("Processing global averages...")
    for grb in tqdm(grbs):
        time_key = (str(grb.validDate), grb.step)

        if curr_time and time_key != curr_time:
            all_data.extend(get_buffer_data(buffer, iso_map))
            buffer = []

        curr_time = time_key
        buffer.append(grb)

    if buffer:
        all_data.extend(get_buffer_data(buffer, iso_map))

    # Save to separate CSVs
    print("Saving files...")
    full_df = pd.DataFrame(all_data)

    # Variable name mapping for cleaner filenames (optional)
    var_names = full_df['variable'].unique()

    for var in var_names:
        sub_df = full_df[full_df['variable'] == var].copy()
        # Drop variable column as it's in the filename
        sub_df = sub_df[['year', 'month', 'country_code', 'value']]

        # Clean variable name for filename
        safe_var = var.replace('_', '').lower()
        fname = f"country_avg_{safe_var}.csv"
        sub_df.to_csv(os.path.join(CACHE_DIR, fname), index=False)
        print(f"Saved {fname}")
