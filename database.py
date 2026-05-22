# All PostgreSQL queries: users, organisations, bundles, feedback_questions, feedback_answers.
# Never use SELECT * FROM bundles — always write targeted queries.

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text


def get_engine(region: str):
    """
    Returns a SQLAlchemy engine for the given region using st.secrets[region].

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


def load_users_and_orgs(region: str) -> pd.DataFrame:
    """
    Loads all users joined with their organisation name.

    Returns one row per user with columns:
        user_id (str), email (str), organisation_name (str)

    Users with no organisation are labelled "Unassigned / No organisation".
    """
    sql = text("""
        SELECT
            u.id            AS user_id,
            u.email,
            o.name          AS organisation_name
        FROM users u
        LEFT JOIN organisations o ON o.id = u.organisation_id
        ORDER BY u.id
    """)
    with get_engine(region).connect() as conn:
        df = pd.read_sql(sql, conn)

    df["user_id"] = df["user_id"].astype(str)
    df["organisation_name"] = df["organisation_name"].fillna("Unassigned / No organisation")
    df["email"] = df["email"].fillna("")

    return df


def get_org_user_counts(region: str) -> pd.DataFrame:
    """
    Counts users per organisation.

    Returns columns: organisation_name (str), user_count (int)
    Users with no organisation are counted under "Unassigned / No organisation".
    """
    sql = text("""
        SELECT
            COALESCE(o.name, 'Unassigned / No organisation') AS organisation_name,
            COUNT(u.id)                                       AS user_count
        FROM users u
        LEFT JOIN organisations o ON o.id = u.organisation_id
        GROUP BY organisation_name
        ORDER BY organisation_name
    """)
    with get_engine(region).connect() as conn:
        df = pd.read_sql(sql, conn)

    return df


def get_bundle_counts_per_org(region: str) -> pd.DataFrame:
    """
    Counts the number of groups (bundles) created per organisation.

    Returns columns: organisation_name (str), total_groups (int)

    Note: never uses SELECT * FROM bundles — only fetches b.id and b.organisation_id.
    """
    sql = text("""
        SELECT
            o.name      AS organisation_name,
            COUNT(b.id) AS total_groups
        FROM bundles b
        JOIN organisations o ON o.id = b.organisation_id
        GROUP BY o.name
        ORDER BY o.name
    """)
    with get_engine(region).connect() as conn:
        df = pd.read_sql(sql, conn)

    return df


def get_star_ratings_by_org(region: str) -> pd.DataFrame:
    """
    Calculates average star rating and response count per organisation and feedback target.

    feedback_questions.target is either "groups" (group/patient rating) or
    "therapists" (therapist self-rating). Ratings are stored as individual answer
    objects inside feedback_answers.answers->'answers' (jsonb array), each with
    an 'answer' key holding a numeric 1–5 value.

    Returns columns:
        organisation_name (str), target (str), avg_rating (float), total_responses (int)
    """
    sql = text("""
        SELECT
            o.name                              AS organisation_name,
            fq.target,
            AVG((ans->>'answer')::numeric)      AS avg_rating,
            COUNT(*)                            AS total_responses
        FROM feedback_answers fa
        CROSS JOIN LATERAL jsonb_array_elements(fa.answers->'answers') AS ans
        JOIN users u          ON u.id  = fa.user_id
        JOIN organisations o  ON o.id  = u.organisation_id
        JOIN feedback_questions fq ON fq.id = fa.feedback_question_id
        GROUP BY o.name, fq.target
        ORDER BY o.name
    """)
    with get_engine(region).connect() as conn:
        df = pd.read_sql(sql, conn)

    return df


def get_monthly_star_ratings(region: str) -> pd.DataFrame:
    """
    Calculates average star rating per month, organisation, and feedback target.

    Same join as get_star_ratings_by_org, additionally grouped by calendar month.

    Returns columns:
        month (str "YYYY-MM"), organisation_name (str), target (str),
        avg_rating (float), total_responses (int)

    Uses feedback_answers.created_at (confirmed timestamptz column).
    """
    sql = text("""
        SELECT
            TO_CHAR(fa.created_at, 'YYYY-MM')   AS month,
            o.name                               AS organisation_name,
            fq.target,
            AVG((ans->>'answer')::numeric)       AS avg_rating,
            COUNT(*)                             AS total_responses
        FROM feedback_answers fa
        CROSS JOIN LATERAL jsonb_array_elements(fa.answers->'answers') AS ans
        JOIN users u           ON u.id  = fa.user_id
        JOIN organisations o   ON o.id  = u.organisation_id
        JOIN feedback_questions fq ON fq.id = fa.feedback_question_id
        GROUP BY month, o.name, fq.target
        ORDER BY month, o.name
    """)
    with get_engine(region).connect() as conn:
        df = pd.read_sql(sql, conn)

    return df


if __name__ == "__main__":
    import sys
    region = sys.argv[1] if len(sys.argv) > 1 else "uk"
    df = load_users_and_orgs(region)
    print(f"Region: {region} — {len(df)} users loaded")
    print(df.head())
