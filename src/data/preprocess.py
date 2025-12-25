import argparse
import os
from typing import Dict, List, Any, Optional

import numpy as np
import pandas as pd
import pygrib
import geopandas as gpd
from shapely import Point
from tqdm import tqdm


def create_country_mapping(lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    """Creates a mapping from a lat/lon grid to ISO_A3 country codes."""
    print(f"Creating country mapping for grid shape {lats.shape}...")

    shapefile_path = 'data/natural_earth_110m/ne_110m_admin_0_countries.shp'
    if not os.path.exists(shapefile_path):
        raise FileNotFoundError(f"Shapefile not found: {shapefile_path}")

    countries_gdf = gpd.read_file(shapefile_path)[['ISO_A3', 'geometry']]

    lons = np.where(lons > 180, lons - 360, lons)
    points_geom = [Point(lon, lat) for lon, lat in zip(lons.flatten(), lats.flatten())]
    points_gdf = gpd.GeoDataFrame(geometry=points_geom, crs="EPSG:4326")

    print("Performing spatial join...")
    joined_gdf = gpd.sjoin(points_gdf, countries_gdf, how='left')

    # Fix: Replace '-99' with 'XXX' and fill NaNs
    iso_codes_flat = joined_gdf['ISO_A3'].replace('-99', 'XXX').fillna('XXX').astype(str)
    return iso_codes_flat.values.reshape(lats.shape)


def calculate_country_averages(values: np.ndarray,
                               iso_map: np.ndarray,
                               mask_value: Optional[float] = None) -> Dict[str, float]:
    """Calculate average values for each country using vectorized groupby."""
    if np.ma.is_masked(values):
        valid_mask = ~values.mask.flatten()
        vals_flat = values.data.flatten()
    else:
        valid_mask = np.ones(values.size, dtype=bool)
        vals_flat = values.flatten()

    if mask_value is not None:
        if np.isnan(mask_value):
            valid_mask &= ~np.isnan(vals_flat)
        else:
            valid_mask &= (vals_flat != mask_value)

    iso_flat = iso_map.flatten()
    land_mask = (iso_flat != 'XXX')
    final_mask = valid_mask & land_mask

    if not np.any(final_mask):
        return {}

    df = pd.DataFrame({'country': iso_flat[final_mask], 'value': vals_flat[final_mask]})
    return df.groupby('country')['value'].mean().to_dict()


def process_timestep_buffer(buffer: List[Any], iso_map: np.ndarray) -> List[Dict]:
    """
    Process a list of GRIB messages belonging to the same timestep.
    Calculates Wind Speed, fixes Snow Depth, and averages all variables.
    """
    results = []

    # Organize buffer by shortName for cross-variable calculations (like Wind)
    vars_dict = {grb.shortName: grb for grb in buffer}

    # 1. Handle Wind Speed (10u + 10v -> 10si)
    if '10u' in vars_dict and '10v' in vars_dict:
        u_grb = vars_dict['10u']
        v_grb = vars_dict['10v']

        # Calculate speed
        speed_values = np.sqrt(u_grb.values ** 2 + v_grb.values ** 2)

        # Calculate average for derived speed
        # We use metadata from U component
        avgs = calculate_country_averages(speed_values, iso_map, getattr(u_grb, 'missingValue', None))

        for country, val in avgs.items():
            results.append({
                'date': u_grb.validDate,
                'step': u_grb.step,
                'variable': '10si',  # Derived wind speed
                'country': country,
                'value': val
            })

        # Remove components so we don't average them individually
        del vars_dict['10u']
        del vars_dict['10v']

    # 2. Process remaining variables
    for short_name, grb in vars_dict.items():
        values = grb.values

        # Fix: Clamp negative snow depth to 0
        if short_name == 'sde':
            values = np.maximum(values, 0)

        avgs = calculate_country_averages(values, iso_map, getattr(grb, 'missingValue', None))

        for country, val in avgs.items():
            results.append({
                'date': grb.validDate,
                'step': grb.step,
                'variable': short_name,
                'country': country,
                'value': val
            })

    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("data_path", type=str)
    args = parser.parse_args()

    cache_dir = "data"
    os.makedirs(cache_dir, exist_ok=True)

    try:
        grbs = pygrib.open(args.data_path)
    except Exception as e:
        print(f"Error opening GRIB: {e}")
        exit(1)

    # --- Step 1: Grid & Map Setup ---
    try:
        first_grb = grbs.message(1)
        lats, lons = first_grb.latlons()
    except Exception as e:
        print(f"Error reading grid: {e}")
        exit(1)

    grid_shape_str = f"{lats.shape[0]}x{lats.shape[1]}"
    iso_map_file = os.path.join(cache_dir, f'iso_map_{grid_shape_str}.npy')

    if os.path.exists(iso_map_file):
        print(f"Loading cached country map: {iso_map_file}")
        iso_map = np.load(iso_map_file)
    else:
        iso_map = create_country_mapping(lats, lons)
        np.save(iso_map_file, iso_map)

    # --- Step 2: Streaming Processing ---
    print("Processing messages stream...")
    grbs.seek(0)

    current_time_key = None
    timestep_buffer = []
    all_results = []

    # Iterate once. Logic: Accumulate same-time messages, process when time changes.
    for grb in tqdm(grbs, desc="Streaming GRIB"):
        if grb.values.shape != iso_map.shape:
            continue

        # Key defines unique timestep (Validity Date + Forecast Step)
        # Note: Use str(grb.validDate) to ensure consistency if types vary
        msg_key = (str(grb.validDate), grb.step)

        if msg_key != current_time_key:
            # New timestep detected: Process previous buffer
            if timestep_buffer:
                batch_results = process_timestep_buffer(timestep_buffer, iso_map)
                all_results.extend(batch_results)
                timestep_buffer = []  # Clear memory

            current_time_key = msg_key

        timestep_buffer.append(grb)

    # Process the very last buffer
    if timestep_buffer:
        batch_results = process_timestep_buffer(timestep_buffer, iso_map)
        all_results.extend(batch_results)

    grbs.close()

    # --- Step 3: Save ---
    if not all_results:
        print("No data processed.")
        exit(0)

    df = pd.DataFrame(all_results)

    # Convert date strings back to datetime objects if needed
    if not pd.api.types.is_datetime64_any_dtype(df['date']):
        df['date'] = pd.to_datetime(df['date'])

    print(f"Memory efficient processing complete. Rows: {len(df)}")
    output_csv = os.path.join(cache_dir, 'country_variable_averages.csv')
    df.to_csv(output_csv, index=False)
    print(f"Saved to {output_csv}")