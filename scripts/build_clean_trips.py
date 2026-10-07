"""Apply the cleaning rule to the raw trip Parquet and report rows removed at each step.

Cleaning rule, applied in this order:
  1. duplicate ride_id (keep one)
  2. started_at outside the study window
  3. start station id or name missing
  4. start or end station is a depot / test / demo station (SYS*, Shop Morgan, Lab, LA Metro Demo)
  5. start station is in New Jersey (JC* / HB* ids)
  6. duration <= 0 (timestamps are local wall-clock, so these are DST fall-back artefacts)
  7. duration < 60 s
  8. duration > 24 h
Trips with a missing end station are kept and flagged, because ridership is counted at trip start.
Station ids are normalised: "7756.1" -> "7756.10", "6569.09_" / "5348.06_old" -> base id.
"""

import shutil

import pandas as pd

import config

NYC_ID = r"^\d{4}\.\d{1,2}(_.*)?$"
NJ_ID = r"^(JC|HB)\d+$"

STEPS = [
    "duplicate_ride_id",
    "start_outside_window",
    "missing_start_station",
    "depot_or_test_station",
    "start_station_in_nj",
    "duration_nonpositive",
    "duration_lt_60s",
    "duration_gt_24h",
]


def normalised_id(col):
    return f"""
        CASE WHEN regexp_matches({col}, '{NYC_ID}')
             THEN regexp_extract({col}, '^(\\d{{4}})', 1) || '.' ||
                  rpad(regexp_extract({col}, '^\\d{{4}}\\.(\\d{{1,2}})', 1), 2, '0')
             ELSE {col} END
    """


def station_kind(col):
    return f"""
        CASE WHEN {col} IS NULL THEN 'missing'
             WHEN regexp_matches({col}, '{NYC_ID}') THEN 'nyc'
             WHEN regexp_matches({col}, '{NJ_ID}') THEN 'nj'
             ELSE 'depot_or_test' END
    """


def main():
    config.TABLES_DIR.mkdir(parents=True, exist_ok=True)
    con = config.connect()
    raw_glob = f"{config.TRIPS_RAW_DIR}/*.parquet"

    con.execute(
        f"""
        CREATE VIEW raw AS
        SELECT
            *,
            date_diff('millisecond', started_at, ended_at) / 1000.0 AS duration_s,
            {station_kind('start_station_id')} AS start_kind,
            {station_kind('end_station_id')} AS end_kind
        FROM read_parquet('{raw_glob}')
        """
    )
    con.execute(
        "CREATE TABLE dup_ids AS SELECT ride_id FROM raw GROUP BY ride_id HAVING count(*) > 1"
    )
    con.execute(
        """
        CREATE TABLE dup_extra AS
        SELECT ride_id, count(*) - 1 AS n_extra FROM raw SEMI JOIN dup_ids USING (ride_id)
        GROUP BY ride_id
        """
    )
    n_total = con.execute("SELECT count(*) FROM raw").fetchone()[0]
    n_dup_removed = con.execute("SELECT coalesce(sum(n_extra), 0) FROM dup_extra").fetchone()[0]

    con.execute(
        f"""
        CREATE VIEW deduped AS
        SELECT * FROM raw ANTI JOIN dup_ids USING (ride_id)
        UNION ALL
        SELECT * FROM raw SEMI JOIN dup_ids USING (ride_id)
        QUALIFY row_number() OVER (PARTITION BY ride_id ORDER BY started_at, source_file) = 1
        """
    )
    con.execute(
        f"""
        CREATE VIEW labelled AS
        SELECT *,
            CASE
                WHEN started_at < TIMESTAMP '{config.STUDY_START}'
                  OR started_at >= TIMESTAMP '{config.STUDY_END}' + INTERVAL 1 DAY
                    THEN 'start_outside_window'
                WHEN start_station_id IS NULL OR start_station_name IS NULL
                    THEN 'missing_start_station'
                WHEN start_kind = 'depot_or_test' OR end_kind = 'depot_or_test'
                    THEN 'depot_or_test_station'
                WHEN start_kind = 'nj' THEN 'start_station_in_nj'
                WHEN duration_s <= 0 THEN 'duration_nonpositive'
                WHEN duration_s < {config.MIN_DURATION_S} THEN 'duration_lt_60s'
                WHEN duration_s > {config.MAX_DURATION_S} THEN 'duration_gt_24h'
                ELSE 'keep'
            END AS drop_reason
        FROM deduped
        """
    )

    removed = dict(
        con.execute("SELECT drop_reason, count(*) FROM labelled GROUP BY 1").fetchall()
    )
    removed["duplicate_ride_id"] = int(n_dup_removed)
    remaining = n_total
    rows = [{"step": "raw", "removed": 0, "remaining": n_total, "pct_of_raw_removed": 0.0}]
    for step in STEPS:
        n = removed.get(step, 0)
        remaining -= n
        rows.append(
            {
                "step": step,
                "removed": n,
                "remaining": remaining,
                "pct_of_raw_removed": round(100 * n / n_total, 4),
            }
        )
    steps = pd.DataFrame(rows)
    steps.to_csv(config.TABLES_DIR / "cleaning_steps.csv", index=False)

    # Non-exclusive counts on the raw table: one trip can have several issues.
    issues = con.execute(
        f"""
        SELECT
            count(*) FILTER (WHERE end_station_id IS NULL) AS missing_end_station_id,
            count(*) FILTER (WHERE end_station_name IS NULL) AS missing_end_station_name,
            count(*) FILTER (WHERE end_lat IS NULL OR end_lng IS NULL) AS missing_end_coords,
            count(*) FILTER (WHERE end_lat = 0 OR end_lng = 0) AS zero_end_coords,
            count(*) FILTER (WHERE start_station_id IS NULL) AS missing_start_station,
            count(*) FILTER (WHERE start_lat IS NULL OR start_lng IS NULL) AS missing_start_coords,
            count(*) FILTER (WHERE duration_s <= 0) AS duration_nonpositive,
            count(*) FILTER (WHERE duration_s > 0 AND duration_s < {config.MIN_DURATION_S}) AS duration_lt_60s,
            count(*) FILTER (WHERE duration_s > {config.MAX_DURATION_S}) AS duration_gt_24h,
            count(*) FILTER (WHERE duration_s > {config.MAX_DURATION_S} AND end_station_id IS NULL)
                AS duration_gt_24h_and_no_end_station,
            count(*) FILTER (WHERE start_lng < {config.NJ_LNG_CUTOFF}) AS start_lng_west_of_cutoff,
            count(*) FILTER (WHERE start_lng < {config.NJ_LNG_CUTOFF} AND start_kind = 'nyc')
                AS start_lng_west_of_cutoff_but_nyc_station,
            count(*) FILTER (WHERE start_kind = 'nj') AS start_station_nj,
            count(*) FILTER (WHERE end_kind = 'nj') AS end_station_nj,
            count(*) FILTER (WHERE start_kind = 'depot_or_test') AS start_station_depot_or_test,
            count(*) FILTER (WHERE end_kind = 'depot_or_test') AS end_station_depot_or_test,
            count(*) FILTER (WHERE start_lng < -100) AS start_in_los_angeles_demo,
            count(*) FILTER (WHERE start_kind = 'nyc'
                             AND NOT regexp_matches(start_station_id, '^\\d{{4}}\\.\\d{{2}}$'))
                AS start_station_id_needs_normalising,
            count(*) FILTER (WHERE strftime(started_at, '%Y%m') <> left(source_file, 6))
                AS start_month_differs_from_file_month
        FROM raw
        """
    ).fetchdf().T.reset_index()
    issues.columns = ["issue", "n_trips"]
    issues["pct_of_raw"] = (100 * issues.n_trips / n_total).round(4)
    issues.to_csv(config.TABLES_DIR / "raw_issue_counts.csv", index=False)

    shutil.rmtree(config.TRIPS_CLEAN_DIR, ignore_errors=True)
    con.execute(
        f"""
        COPY (
            SELECT
                ride_id, rideable_type, member_casual, started_at, ended_at, duration_s,
                {normalised_id('start_station_id')} AS start_station_id,
                start_station_name,
                {normalised_id('end_station_id')} AS end_station_id,
                end_station_name,
                start_lat, start_lng, end_lat, end_lng,
                end_station_id IS NOT NULL AS has_end_station,
                strftime(started_at, '%Y%m') AS ym
            FROM labelled
            WHERE drop_reason = 'keep'
        ) TO '{config.TRIPS_CLEAN_DIR}' (FORMAT parquet, COMPRESSION zstd, PARTITION_BY (ym))
        """
    )

    print(steps.to_string(index=False))
    print()
    print(issues.to_string(index=False))


if __name__ == "__main__":
    main()
