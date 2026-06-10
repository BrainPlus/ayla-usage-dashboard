# All PostgreSQL queries: users, organisations, bundles, feedback_questions, feedback_answers.
# Never use SELECT * FROM bundles — always write targeted queries.

from datetime import date, timedelta

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text


@st.cache_resource
def get_engine(region: str):
    """
    Returns a SQLAlchemy engine for the given region using st.secrets[region].
    Cached as a shared resource so only one connection pool exists per region.

    Args:
        region: "uk" or "eu"

    Returns:
        sqlalchemy.engine.Engine (postgresql+psycopg2 dialect)
    """
    cfg = st.secrets[region]
    url = (
        f"postgresql+psycopg2://{cfg['db_user']}:{cfg['db_password']}"
        f"@{cfg['db_host']}:{cfg['db_port']}/{cfg['db_name']}"
    )
    return create_engine(url)


def _organisation_filter(org_id, prefix: str = "WHERE") -> tuple[str, dict | None]:
    if org_id == "unassigned":
        return f"{prefix} u.organisation_id IS NULL", None
    if org_id is not None:
        return f"{prefix} u.organisation_id = :org_id", {"org_id": org_id}
    return "", None


def get_organisations(region: str) -> pd.DataFrame:
    """Returns all organisations ordered by name."""
    sql = text("""
        SELECT
            id   AS organisation_id,
            name AS organisation_name
        FROM organisations
        ORDER BY name
    """)
    with get_engine(region).connect() as conn:
        df = pd.read_sql(sql, conn)
    df["organisation_id"] = df["organisation_id"].astype(int)
    df["organisation_name"] = df["organisation_name"].astype(str)
    return df


def load_users_and_orgs(region: str, org_id=None) -> pd.DataFrame:
    """
    Loads all users joined with their organisation name.

    Returns one row per user with columns:
        user_id (str), email (str), organisation_name (str)

    Users with no organisation are labelled "Unassigned / No organisation".
    """
    filter_sql, params = _organisation_filter(org_id)
    sql = text(f"""
        SELECT
            u.id            AS user_id,
            u.email,
            o.name          AS organisation_name
        FROM users u
        LEFT JOIN organisations o ON o.id = u.organisation_id
        {filter_sql}
        ORDER BY u.id
    """)
    with get_engine(region).connect() as conn:
        df = pd.read_sql(sql, conn, params=params)

    df["user_id"] = df["user_id"].astype(str)
    df["organisation_name"] = df["organisation_name"].fillna("Unassigned / No organisation")
    df["email"] = df["email"].fillna("")

    return df


def get_org_user_counts(region: str, org_id=None) -> pd.DataFrame:
    """
    Counts users per organisation.

    Returns columns: organisation_name (str), user_count (int)
    Users with no organisation are counted under "Unassigned / No organisation".
    """
    filter_sql, params = _organisation_filter(org_id)
    sql = text(f"""
        SELECT
            COALESCE(o.name, 'Unassigned / No organisation') AS organisation_name,
            COUNT(u.id)                                       AS user_count
        FROM users u
        LEFT JOIN organisations o ON o.id = u.organisation_id
        {filter_sql}
        GROUP BY organisation_name
        ORDER BY organisation_name
    """)
    with get_engine(region).connect() as conn:
        df = pd.read_sql(sql, conn, params=params)

    return df


def get_bundle_counts_per_org(region: str, org_id=None) -> pd.DataFrame:
    """
    Counts the number of groups (bundles) created per organisation.

    Returns columns: organisation_name (str), total_groups (int)

    Note: never uses SELECT * FROM bundles — only fetches b.id and b.user_id.
    Relationship: bundles.user_id → users.id → users.organisation_id → organisations.id
    """
    filter_sql, params = _organisation_filter(org_id)
    sql = text(f"""
        SELECT
            COALESCE(o.name, 'Unassigned / No organisation') AS organisation_name,
            COUNT(b.id) AS total_groups
        FROM bundles b
        JOIN users u ON u.id = b.user_id
        LEFT JOIN organisations o ON o.id = u.organisation_id
        {filter_sql}
        GROUP BY organisation_name
        ORDER BY organisation_name
    """)
    with get_engine(region).connect() as conn:
        df = pd.read_sql(sql, conn, params=params)

    return df


def get_bundle_configurations(region: str, org_id=None) -> pd.DataFrame:
    """
    Loads each bundle's ordered configured session IDs and creation date.

    Returns columns: bundle_id, bundle_name, organisation_name,
    configured_session_ids, created_date.
    """
    filter_sql, params = _organisation_filter(org_id)
    sql = text(f"""
        SELECT
            b.id::text AS bundle_id,
            COALESCE(
                NULLIF(BTRIM(b.name), ''),
                NULLIF(BTRIM(b.configuration->>'title'), ''),
                'Bundle ' || b.id::text
            ) AS bundle_name,
            COALESCE(o.name, 'Unassigned / No organisation') AS organisation_name,
            ARRAY(
                SELECT configured_session->>'id'
                FROM jsonb_array_elements(
                    COALESCE(b.configuration->'sessions', '[]'::jsonb)
                ) WITH ORDINALITY AS configured(configured_session, session_order)
                WHERE configured_session->>'id' IS NOT NULL
                ORDER BY session_order
            ) AS configured_session_ids,
            b.created_at::date AS created_date
        FROM bundles b
        JOIN users u ON u.id = b.user_id
        LEFT JOIN organisations o ON o.id = u.organisation_id
        {filter_sql}
        ORDER BY organisation_name, bundle_name, b.id
    """)
    with get_engine(region).connect() as conn:
        return pd.read_sql(sql, conn, params=params)


def get_monthly_bundle_creations(
    region: str,
    start_date: date,
    end_date: date,
    org_id=None,
) -> pd.DataFrame:
    """
    Counts bundles created per calendar month and organisation.

    Returns columns: month (str "YYYY-MM"), organisation_name (str),
    bundles_created (int)

    Uses bundles.created_at as the canonical creation timestamp.
    """
    filter_sql, org_params = _organisation_filter(org_id, prefix="AND")
    params = {
        "start": start_date,
        "end_exclusive": end_date + timedelta(days=1),
        **(org_params or {}),
    }
    sql = text(f"""
        SELECT
            TO_CHAR(DATE_TRUNC('month', b.created_at), 'YYYY-MM') AS month,
            COALESCE(o.name, 'Unassigned / No organisation') AS organisation_name,
            COUNT(b.id) AS bundles_created
        FROM bundles b
        JOIN users u ON u.id = b.user_id
        LEFT JOIN organisations o ON o.id = u.organisation_id
        WHERE b.created_at >= :start AND b.created_at < :end_exclusive
        {filter_sql}
        GROUP BY month, organisation_name
        ORDER BY month, organisation_name
    """)
    with get_engine(region).connect() as conn:
        return pd.read_sql(sql, conn, params=params)


def get_bundle_filter_breakdown(
    region: str,
    start_date: date,
    end_date: date,
    org_id=None,
) -> pd.DataFrame:
    """
    Counts bundle filter preferences within the selected reporting period.

    Returns columns: filter_type (str), filter_value (str), bundle_count (int)
    Missing JSON values and empty strings are counted as "Not set".
    """
    filter_sql, org_params = _organisation_filter(org_id, prefix="AND")
    params = {
        "start": start_date,
        "end_exclusive": end_date + timedelta(days=1),
        **(org_params or {}),
    }
    sql = text(f"""
        WITH scoped_bundles AS (
            SELECT b.bundle_filters
            FROM bundles b
            JOIN users u ON u.id = b.user_id
            LEFT JOIN organisations o ON o.id = u.organisation_id
            WHERE b.created_at >= :start AND b.created_at < :end_exclusive
            {filter_sql}
        ),
        filter_values AS (
            SELECT
                'severity' AS filter_type,
                COALESCE(NULLIF(BTRIM(bundle_filters->>'severity'), ''), 'Not set')
                    AS filter_value
            FROM scoped_bundles
            UNION ALL
            SELECT
                'age' AS filter_type,
                COALESCE(NULLIF(BTRIM(bundle_filters->>'age'), ''), 'Not set')
                    AS filter_value
            FROM scoped_bundles
            UNION ALL
            SELECT
                'physical_requirement' AS filter_type,
                COALESCE(
                    NULLIF(BTRIM(bundle_filters->>'physical_requirement'), ''),
                    'Not set'
                ) AS filter_value
            FROM scoped_bundles
        )
        SELECT filter_type, filter_value, COUNT(*) AS bundle_count
        FROM filter_values
        GROUP BY filter_type, filter_value
        ORDER BY filter_type, bundle_count DESC, filter_value
    """)
    with get_engine(region).connect() as conn:
        return pd.read_sql(sql, conn, params=params)


def get_star_ratings_by_org(
    region: str,
    start_date: date,
    end_date: date,
    org_id=None,
) -> pd.DataFrame:
    """
    Calculates average star rating and response count per organisation and feedback target.

    feedback_questions.target is either "groups" (group/patient rating) or
    "therapists" (therapist self-rating). Ratings are stored as individual answer
    objects inside feedback_answers.answers->'answers' (jsonb array), each with
    an 'answer' key holding a numeric 1–5 value.

    Returns columns:
        organisation_name (str), target (str), avg_rating (float), total_responses (int)
    """
    filter_sql, org_params = _organisation_filter(org_id, prefix="AND")
    params = {
        "start": start_date,
        "end_exclusive": end_date + timedelta(days=1),
        **(org_params or {}),
    }
    sql = text(f"""
        SELECT
            COALESCE(o.name, 'Unassigned / No organisation') AS organisation_name,
            fq.target,
            AVG((ans->>'answer')::numeric)                   AS avg_rating,
            COUNT(*)                                         AS total_responses
        FROM feedback_answers fa
        CROSS JOIN LATERAL jsonb_array_elements(fa.answers->'answers') AS ans
        JOIN users u           ON u.id  = fa.user_id
        LEFT JOIN organisations o  ON o.id  = u.organisation_id
        JOIN feedback_questions fq ON fq.id = fa.feedback_question_id
        WHERE fa.created_at >= :start AND fa.created_at < :end_exclusive
        {filter_sql}
        GROUP BY COALESCE(o.name, 'Unassigned / No organisation'), fq.target
        ORDER BY COALESCE(o.name, 'Unassigned / No organisation')
    """)
    with get_engine(region).connect() as conn:
        df = pd.read_sql(sql, conn, params=params)

    return df


def get_feedback_submissions(
    region: str,
    start_date: date,
    end_date: date,
    org_id=None,
) -> pd.DataFrame:
    """
    Loads feedback submissions in the selected reporting period.

    Returns one row per feedback submission with columns:
        organisation_name, target, bundle_id, session_id, has_comment
    """
    filter_sql, org_params = _organisation_filter(org_id, prefix="AND")
    params = {
        "start": start_date,
        "end_exclusive": end_date + timedelta(days=1),
        **(org_params or {}),
    }
    sql = text(f"""
        SELECT
            COALESCE(o.name, 'Unassigned / No organisation') AS organisation_name,
            fq.target,
            fa.answers->'metadata'->>'bundleId' AS bundle_id,
            fa.answers->'metadata'->>'sessionId' AS session_id,
            NULLIF(BTRIM(fa.answers->>'comment'), '') IS NOT NULL AS has_comment
        FROM feedback_answers fa
        JOIN users u ON u.id = fa.user_id
        LEFT JOIN organisations o ON o.id = u.organisation_id
        JOIN feedback_questions fq ON fq.id = fa.feedback_question_id
        WHERE fa.created_at >= :start AND fa.created_at < :end_exclusive
        {filter_sql}
        ORDER BY organisation_name, fq.target
    """)
    with get_engine(region).connect() as conn:
        return pd.read_sql(sql, conn, params=params)


def get_monthly_star_ratings(
    region: str,
    start_date: date,
    end_date: date,
    org_id=None,
) -> pd.DataFrame:
    """
    Calculates average star rating per month, organisation, feedback target,
    and question label.

    Answers are joined to the English question label by question ID so labels
    remain correct if question order changes.

    Returns columns:
        month (str "YYYY-MM"), organisation_name (str), target (str),
        question_label (str), avg_rating (float), total_responses (int)

    Uses feedback_answers.created_at (confirmed timestamptz column).
    """
    filter_sql, org_params = _organisation_filter(org_id, prefix="AND")
    params = {
        "start": start_date,
        "end_exclusive": end_date + timedelta(days=1),
        **(org_params or {}),
    }
    sql = text(f"""
        SELECT
            TO_CHAR(fa.created_at, 'YYYY-MM')                AS month,
            COALESCE(o.name, 'Unassigned / No organisation') AS organisation_name,
            fq.target,
            question->>'question_en'                         AS question_label,
            AVG((ans->>'answer')::numeric)                   AS avg_rating,
            COUNT(*)                                         AS total_responses
        FROM feedback_answers fa
        CROSS JOIN LATERAL jsonb_array_elements(fa.answers->'answers') AS ans
        JOIN users u           ON u.id  = fa.user_id
        LEFT JOIN organisations o  ON o.id  = u.organisation_id
        JOIN feedback_questions fq ON fq.id = fa.feedback_question_id
        JOIN LATERAL jsonb_array_elements(fq.questions->'questions') AS question
            ON question->>'id' = ans->>'questionId'
        WHERE fa.created_at >= :start AND fa.created_at < :end_exclusive
        {filter_sql}
        GROUP BY month, COALESCE(o.name, 'Unassigned / No organisation'),
                 fq.target, question_label
        ORDER BY month, COALESCE(o.name, 'Unassigned / No organisation'),
                 fq.target, question_label
    """)
    with get_engine(region).connect() as conn:
        df = pd.read_sql(sql, conn, params=params)

    return df


if __name__ == "__main__":
    import sys
    region = sys.argv[1] if len(sys.argv) > 1 else "uk"
    df = load_users_and_orgs(region)
    print(f"Region: {region} — {len(df)} users loaded")
    print(df.head())
