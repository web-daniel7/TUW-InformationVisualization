import argparse
import os
import numpy as np
import pandas as pd
import pygrib
import geopandas as gpd
from shapely import Point
from tqdm import tqdm

# --- Configuration ---
CACHE_DIR = "data/processed/countries"
SHAPEFILE_PATH = 'data/natural_earth_110m/ne_110m_admin_0_countries.shp'
STRIDE = 5  # Downsampling factor (1 pixel every 5). 9km * 5 = ~45km resolution.


def create_downsampled_map(lats_full, lons_full):
    """Downsamples coordinates FIRST, then maps to countries (much faster)."""
    # Slice arrays
    lats = lats_full[::STRIDE, ::STRIDE]
    lons = lons_full[::STRIDE, ::STRIDE]

    print(f"Mapping reduced grid {lats.shape}...")
    countries_gdf = gpd.read_file(SHAPEFILE_PATH)[['ADM0_A3', 'geometry']]

    lons_norm = np.where(lons > 180, lons - 360, lons)
    points_geom = [Point(lon, lat) for lon, lat in zip(lons_norm.flatten(), lats.flatten())]

    points_gdf = gpd.GeoDataFrame(geometry=points_geom, crs="EPSG:4326")
    joined_gdf = gpd.sjoin(points_gdf, countries_gdf, how='left')

    iso_codes = joined_gdf['ADM0_A3'].fillna('XXX').astype(str).values
    return iso_codes.reshape(lats.shape), lats, lons


def process_buffer_to_files(buffer, iso_map, lats, lons, open_files):
    """
    Extracts data for all countries from the buffer and writes to open file handles.
    """
    vars_dict = {grb.shortName: grb for grb in buffer}

    # Determine date from one message
    ref_grb = buffer[0]
    year = ref_grb.validDate.year
    month = ref_grb.validDate.month

    # Helper to process and write a specific variable array
    def write_variable(var_name, data_grid):
        # Downsample data to match our map
        data_small = data_grid[::STRIDE, ::STRIDE]

        # Create a temporary DF for easier grouping
        # Note: We flatten everything to iterate quickly
        df = pd.DataFrame({
            'country': iso_map.flatten(),
            'lat': lats.flatten(),
            'lon': lons.flatten(),
            'val': data_small.flatten()
        })

        # Filter out missing values (ocean) and invalid countries
        df = df.dropna(subset=['val'])

        # Filter valid land
        df = df[df['country'] != 'XXX']

        # Group by country and write chunks
        for country, group in df.groupby('country'):
            # Format: year,month,variable_shortname,lat,long,value
            # We construct the CSV string manually or via pandas for speed
            # Adding columns for static data
            group['year'] = year
            group['month'] = month
            group['var'] = var_name

            # Reorder
            out_df = group[['year', 'month', 'var', 'lat', 'lon', 'val']]

            # Write header only if file is new (checked in main)
            # Here we just append.
            if country not in open_files:
                # Open file in append mode
                fpath = os.path.join(CACHE_DIR, f"era5_monthly_{country}.csv")
                is_new = not os.path.exists(fpath)
                f = open(fpath, 'a')
                open_files[country] = f
                if is_new:
                    f.write("year,month,variable_shortname,lat,long,value\n")

            # Write data (without header)
            out_df.to_csv(open_files[country], header=False, index=False)

    # 1. Handle Wind Speed
    if '10u' in vars_dict and '10v' in vars_dict:
        u_val = vars_dict['10u'].values
        v_val = vars_dict['10v'].values
        speed = np.sqrt(u_val ** 2 + v_val ** 2)
        write_variable('10si', speed)
        del vars_dict['10u']
        del vars_dict['10v']

    # 2. Handle others
    for name, grb in vars_dict.items():
        vals = grb.values
        if name == 'sde': vals = np.maximum(vals, 0)
        write_variable(name, vals)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("data_path", type=str)
    args = parser.parse_args()

    os.makedirs(CACHE_DIR, exist_ok=True)

    grbs = pygrib.open(args.data_path)

    # 1. Setup Map
    first = grbs.message(1)
    lats_full, lons_full = first.latlons()

    iso_map, lats_small, lons_small = create_downsampled_map(lats_full, lons_full)

    # 2. Process
    print(f"Processing with stride {STRIDE} (~{9 * STRIDE}km)...")
    grbs.seek(0)

    buffer = []
    curr_time = None
    open_files = {}

    try:
        for grb in tqdm(grbs):
            time_key = (str(grb.validDate), grb.step)

            if curr_time and time_key != curr_time:
                process_buffer_to_files(buffer, iso_map, lats_small, lons_small, open_files)
                buffer = []

            curr_time = time_key
            buffer.append(grb)

        if buffer:
            process_buffer_to_files(buffer, iso_map, lats_small, lons_small, open_files)

    finally:
        for f in open_files.values():
            f.close()

    print("Processing complete.")
