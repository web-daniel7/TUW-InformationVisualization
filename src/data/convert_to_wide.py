import argparse
import os
import glob
import pandas as pd
from tqdm import tqdm


def convert_file(file_path, output_dir):
    filename = os.path.basename(file_path)

    # 1. Read the Long Format CSV
    # We define dtype to ensure precision and speed
    try:
        df = pd.read_csv(file_path)
    except Exception as e:
        print(f"Skipping {filename}: Could not read CSV ({e})")
        return

    # 2. Validation: Check if it's actually Long Format
    required_cols = {'year', 'month', 'variable_shortname', 'value'}
    if not required_cols.issubset(df.columns):
        # Check if it might use 'lat'/'lon' or 'latitude'/'longitude'
        print(f"Skipping {filename}: Missing required columns (likely already wide or wrong format).")
        return

    # Normalize coordinate names if necessary (long -> lon)
    if 'long' in df.columns:
        df = df.rename(columns={'long': 'lon'})

    # 3. Pivot the Data
    # Index: The unique identifier for a row (Time + Location)
    # Columns: The variable names (e.g., t2m, tp)
    # Values: The actual data
    try:
        wide_df = df.pivot_table(
            index=['year', 'month', 'lat', 'lon'],
            columns='variable_shortname',
            values='value',
            aggfunc='first'  # 'first' is faster than 'mean' if we assume no duplicates
        ).reset_index()
    except KeyError as e:
        print(f"Skipping {filename}: Key Error during pivot ({e})")
        return

    # 4. Cleanup and Optimization
    # Remove the name of the columns index (which is currently 'variable_shortname')
    wide_df.columns.name = None

    # Round coordinates to 4 decimals (sufficient for 9km grid) to prevent floating point drift
    wide_df['lat'] = wide_df['lat'].round(4)
    wide_df['lon'] = wide_df['lon'].round(4)

    # Round data values to 2 decimals to save space
    # (Exclude year/month/lat/lon from this rounding if strict, but simple iteration works)
    data_cols = [c for c in wide_df.columns if c not in ['year', 'month', 'lat', 'lon']]
    wide_df[data_cols] = wide_df[data_cols].round(2)

    # 5. Save
    output_path = os.path.join(output_dir, filename)
    wide_df.to_csv(output_path, index=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert Long-Format ERA5 CSVs to Wide-Format")
    parser.add_argument("input_dir", type=str, help="Directory containing the long-format CSVs")
    parser.add_argument("output_dir", type=str, help="Directory to save wide CSVs")

    args = parser.parse_args()

    # Setup Output Directory
    if args.output_dir:
        out_dir = args.output_dir
    else:
        out_dir = os.path.join(args.input_dir, "wide_converted")

    os.makedirs(out_dir, exist_ok=True)

    # Find CSVs
    files = glob.glob(os.path.join(args.input_dir, "*.csv"))
    print(f"Found {len(files)} files in {args.input_dir}")
    print(f"Saving converted files to: {out_dir}")

    # Process
    for file_path in tqdm(files, desc="Converting"):
        convert_file(file_path, out_dir)

    print("Conversion complete.")
