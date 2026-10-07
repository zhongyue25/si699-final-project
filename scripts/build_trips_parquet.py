"""Convert each monthly Citi Bike zip into one typed Parquet file and write a file inventory."""

import argparse
import shutil
import zipfile

import pandas as pd

import config

CASTS = {
    "started_at": "TIMESTAMP",
    "ended_at": "TIMESTAMP",
    "start_lat": "DOUBLE",
    "start_lng": "DOUBLE",
    "end_lat": "DOUBLE",
    "end_lng": "DOUBLE",
}


def select_list():
    cols = []
    for col in config.TRIP_COLUMNS:
        if col in CASTS:
            cols.append(f"TRY_CAST({col} AS {CASTS[col]}) AS {col}")
        else:
            cols.append(f"NULLIF(TRIM({col}), '') AS {col}")
    cols.append("parse_filename(filename) AS source_file")
    return ", ".join(cols)


def keep_filter(month):
    """Spillover files contribute only trips that started inside the study window."""
    if month in config.SPILLOVER_MONTHS:
        return f"TRY_CAST(started_at AS TIMESTAMP) < TIMESTAMP '{config.STUDY_END}' + INTERVAL 1 DAY"
    return "true"


def convert_month(con, zip_path, force):
    month = zip_path.name[:6]
    out_path = config.TRIPS_RAW_DIR / f"{month}.parquet"
    inventory_path = config.TMP_DIR / f"inventory_{month}.csv"
    if out_path.exists() and inventory_path.exists() and not force:
        return pd.read_csv(inventory_path, dtype={"file_month": str})

    extract_dir = config.TMP_DIR / f"csv_{month}"
    shutil.rmtree(extract_dir, ignore_errors=True)
    extract_dir.mkdir(parents=True)

    with zipfile.ZipFile(zip_path) as zf:
        members = [
            m for m in zf.namelist() if m.endswith(".csv") and not m.startswith("__MACOSX")
        ]
        for member in members:
            zf.extract(member, extract_dir)

    rows = []
    for member in sorted(members):
        csv_path = extract_dir / member
        sniffed = con.execute(
            f"DESCRIBE SELECT * FROM read_csv('{csv_path}', sample_size = 100000)"
        ).fetchall()
        cast_failures = " + ".join(
            f"count(*) FILTER (WHERE {c} IS NOT NULL AND {c} <> '' AND TRY_CAST({c} AS {t}) IS NULL)"
            for c, t in CASTS.items()
        )
        n_rows, n_cast_fail = con.execute(
            f"SELECT count(*), {cast_failures} "
            f"FROM read_csv('{csv_path}', all_varchar = true, header = true)"
        ).fetchone()
        n_rows_kept = con.execute(
            f"""
            SELECT count(*) FROM read_csv('{csv_path}', all_varchar = true, header = true)
            WHERE {keep_filter(month)}
            """
        ).fetchone()[0]
        rows.append(
            {
                "file_month": month,
                "zip": zip_path.name,
                "csv": member,
                "n_rows_in_file": n_rows,
                "n_rows": n_rows_kept,
                "n_cast_failures": n_cast_fail,
                "columns": ",".join(r[0] for r in sniffed),
                "sniffed_types": ",".join(r[1] for r in sniffed),
            }
        )

    glob = f"{extract_dir}/**/*.csv"
    con.execute(
        f"""
        COPY (
            SELECT {select_list()}
            FROM read_csv('{glob}', all_varchar = true, header = true, filename = true,
                          union_by_name = true)
            WHERE {keep_filter(month)}
        ) TO '{out_path}' (FORMAT parquet, COMPRESSION zstd)
        """
    )
    shutil.rmtree(extract_dir)

    inventory = pd.DataFrame(rows)
    inventory.to_csv(inventory_path, index=False)
    print(
        f"{month}: {len(members)} files, {inventory.n_rows.sum():,} rows kept "
        f"of {inventory.n_rows_in_file.sum():,}"
    )
    return inventory


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    config.TRIPS_RAW_DIR.mkdir(parents=True, exist_ok=True)
    config.TABLES_DIR.mkdir(parents=True, exist_ok=True)
    con = config.connect()

    zips = sorted(config.RAW_TRIPS_DIR.glob("[0-9]*-citibike-tripdata.zip"))
    inventory = pd.concat([convert_month(con, z, args.force) for z in zips], ignore_index=True)
    inventory.to_csv(config.TABLES_DIR / "file_inventory.csv", index=False)

    missing = sorted(set(config.MONTHS) - set(inventory.file_month))
    schemas = inventory.groupby(["columns", "sniffed_types"]).size()
    print(f"missing months: {missing or 'none'}")
    print(f"distinct header sets: {inventory['columns'].nunique()}")
    print(f"distinct sniffed type sets: {len(schemas)}")
    print(f"cast failures: {inventory.n_cast_failures.sum():,}")


if __name__ == "__main__":
    main()
