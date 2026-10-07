"""Build the daily Central Park weather table for the study window with converted units.

GHCN-Daily raw units: PRCP tenths of mm, SNOW/SNWD mm, TMAX/TMIN tenths of deg C,
AWND tenths of m/s. Attribute strings are "mflag,qflag,sflag[,obs_time]".
"""

import pandas as pd

import config

FIELDS = ["TMAX", "TMIN", "PRCP", "SNOW", "SNWD", "AWND"]


def flag_columns():
    cols = []
    for field in FIELDS:
        attrs = f"string_split(coalesce({field}_ATTRIBUTES, ',,'), ',')"
        name = field.lower()
        cols += [
            f"NULLIF({attrs}[1], '') AS {name}_mflag",
            f"NULLIF({attrs}[2], '') AS {name}_qflag",
            f"NULLIF({attrs}[3], '') AS {name}_sflag",
        ]
    return ", ".join(cols)


def main():
    config.TABLES_DIR.mkdir(parents=True, exist_ok=True)
    con = config.connect()

    # The local copy has ISO dates before 1900 and Y/M/D dates after, so accept both.
    con.execute(
        f"""
        CREATE TABLE weather AS
        WITH raw AS (
            SELECT
                coalesce(try_strptime(DATE, '%Y-%m-%d'), try_strptime(DATE, '%Y/%m/%d'))::DATE AS date,
                *
            FROM read_csv('{config.RAW_WEATHER_CSV}', all_varchar = true, header = true)
        )
        SELECT
            date,
            TRY_CAST(TMAX AS DOUBLE) / 10 AS tmax_c,
            TRY_CAST(TMIN AS DOUBLE) / 10 AS tmin_c,
            TRY_CAST(TMAX AS DOUBLE) / 10 * 9 / 5 + 32 AS tmax_f,
            TRY_CAST(TMIN AS DOUBLE) / 10 * 9 / 5 + 32 AS tmin_f,
            TRY_CAST(PRCP AS DOUBLE) / 10 AS prcp_mm,
            TRY_CAST(PRCP AS DOUBLE) / 10 / 25.4 AS prcp_in,
            TRY_CAST(SNOW AS DOUBLE) AS snow_mm,
            TRY_CAST(SNWD AS DOUBLE) AS snwd_mm,
            TRY_CAST(AWND AS DOUBLE) / 10 AS awnd_ms,
            TRY_CAST(AWND AS DOUBLE) / 10 * 2.236936 AS awnd_mph,
            {flag_columns()}
        FROM raw
        WHERE date BETWEEN DATE '{config.STUDY_START}' AND DATE '{config.STUDY_END}'
        ORDER BY date
        """
    )
    con.execute(f"COPY weather TO '{config.WEATHER_PARQUET}' (FORMAT parquet)")

    n_unparsed = con.execute(
        f"""
        SELECT count(*) FROM read_csv('{config.RAW_WEATHER_CSV}', all_varchar = true, header = true)
        WHERE coalesce(try_strptime(DATE, '%Y-%m-%d'), try_strptime(DATE, '%Y/%m/%d')) IS NULL
        """
    ).fetchone()[0]
    n_expected = len(pd.date_range(config.STUDY_START, config.STUDY_END))
    n_days, n_distinct = con.execute("SELECT count(*), count(DISTINCT date) FROM weather").fetchone()

    value_col = {
        "TMAX": "tmax_c", "TMIN": "tmin_c", "PRCP": "prcp_mm",
        "SNOW": "snow_mm", "SNWD": "snwd_mm", "AWND": "awnd_ms",
    }
    rows = []
    for field, col in value_col.items():
        name = field.lower()
        rows.append(
            con.execute(
                f"""
                SELECT
                    '{field}' AS field,
                    count(*) FILTER (WHERE {col} IS NULL) AS missing_days,
                    count(*) FILTER (WHERE {name}_qflag IS NOT NULL) AS quality_flagged_days,
                    count(*) FILTER (WHERE {name}_mflag = 'T') AS trace_days,
                    string_agg(DISTINCT {name}_sflag, '/' ORDER BY {name}_sflag) AS source_flags,
                    min({col}) AS min, median({col}) AS median, max({col}) AS max
                FROM weather
                """
            ).fetchdf()
        )
    quality = pd.concat(rows, ignore_index=True)
    quality.to_csv(config.TABLES_DIR / "weather_quality.csv", index=False)

    print(f"days in window: {n_days} (distinct {n_distinct}, expected {n_expected})")
    print(f"unparseable dates in full file: {n_unparsed}")
    print(quality.to_string(index=False))
    missing = con.execute(
        "SELECT date FROM weather WHERE awnd_ms IS NULL OR tmax_c IS NULL OR prcp_mm IS NULL"
    ).fetchall()
    print("days with a missing core field:", [str(d[0]) for d in missing])


if __name__ == "__main__":
    main()
