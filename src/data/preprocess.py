import argparse
import os
from typing import Dict, Optional

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

    # Standardize longitudes to -180 to 180
    lons = np.where(lons > 180, lons - 360, lons)
    points_geom = [Point(lon, lat) for lon, lat in zip(lons.flatten(), lats.flatten())]
    points_gdf = gpd.GeoDataFrame(geometry=points_geom, crs="EPSG:4326")

    print("Performing spatial join...")
    joined_gdf = gpd.sjoin(points_gdf, countries_gdf, how='left')

    iso_codes_flat = joined_gdf['ISO_A3'].fillna('XXX').astype(str)
    return iso_codes_flat.values.reshape(lats.shape)


def calculate_country_averages(values: np.ndarray,
                               iso_map: np.ndarray,
                               mask_value: Optional[float] = None) -> Dict[str, float]:
    """Calculate average values for each country using a vectorized approach."""
    # Handle masked arrays or standard arrays
    if np.ma.is_masked(values):
        valid_mask = ~values.mask.flatten()
        vals_flat = values.data.flatten()
    else:
        valid_mask = np.ones(values.size, dtype=bool)
        vals_flat = values.flatten()

    # Handle explicit missing values
    if mask_value is not None:
        if np.isnan(mask_value):
            valid_mask &= ~np.isnan(vals_flat)
        else:
            valid_mask &= (vals_flat != mask_value)

    # Filter for valid land points
    iso_flat = iso_map.flatten()
    land_mask = (iso_flat != 'XXX')
    final_mask = valid_mask & land_mask

    if not np.any(final_mask):
        return {}

    # Fast groupby mean
    df = pd.DataFrame({'country': iso_flat[final_mask], 'value': vals_flat[final_mask]})
    return df.groupby('country')['value'].mean().to_dict()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Aggregate all GRIB variables by country.")
    parser.add_argument("data_path", type=str, help="Path to the GRIB file")
    args = parser.parse_args()

    cache_dir = "data"
    os.makedirs(cache_dir, exist_ok=True)

    try:
        grbs = pygrib.open(args.data_path)
    except Exception as e:
        print(f"Error opening GRIB: {e}")
        exit(1)

    # --- Step 1: Establish Grid and Map ---
    # We use the first message to define the grid and create the map
    try:
        first_grb = grbs.message(1)
        lats, lons = first_grb.latlons()
    except Exception as e:
        print(f"Error reading first message for grid definition: {e}")
        exit(1)

    grid_shape_str = f"{lats.shape[0]}x{lats.shape[1]}"
    iso_map_file = os.path.join(cache_dir, f'iso_map_{grid_shape_str}.npy')

    if os.path.exists(iso_map_file):
        print(f"Loading cached country map: {iso_map_file}")
        iso_map = np.load(iso_map_file)
    else:
        iso_map = create_country_mapping(lats, lons)
        np.save(iso_map_file, iso_map)

    # --- Step 2: Iterate all messages ---
    # Rewind to start to process all messages including the first one
    grbs.seek(0)

    all_results = []
    print(f"Processing all messages in GRIB file...")

    for grb in tqdm(grbs, desc="Aggregating"):
        # Ensure the current message matches our cached grid map
        if grb.values.shape != iso_map.shape:
            # Skip messages with different grids (e.g. reduced gaussian vs regular latlon)
            continue

        try:
            # Calculate averages
            missing_val = getattr(grb, 'missingValue', None)
            country_avgs = calculate_country_averages(grb.values, iso_map, missing_val)

            # Store results
            for country, val in country_avgs.items():
                all_results.append({
                    'date': pd.Timestamp(year=grb.year, month=grb.month, day=grb.day,
                                         hour=grb.hour, minute=grb.minute),
                    'variable': grb.shortName,  # e.g., '2t', 'tp', 'msl'
                    'units': grb.units,
                    'country': country,
                    'value': val,
                    'level': grb.level,
                    'step': grb.step
                })
        except Exception as e:
            print(f"Skipping message due to error: {e}")
            continue

    grbs.close()

    # --- Step 3: Save Output ---
    if not all_results:
        print("No valid data processed.")
        exit(0)

    df = pd.DataFrame(all_results)

    # Pivot allows for a cleaner view: one row per date/country, columns for variables
    # Note: If multiple levels exist for the same variable, keep as long-format or refine pivot
    print("DataFrame Info:")
    df.info()

    output_csv = os.path.join(cache_dir, 'country_variable_averages.csv')
    df.to_csv(output_csv, index=False)
    print(f"\nResults saved to {output_csv}")