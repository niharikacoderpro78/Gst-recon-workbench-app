"""db.py - saves results to PostgreSQL when DATABASE_URL is set, otherwise to a local SQLite file."""
import os
from sqlalchemy import create_engine


def get_engine():
    url = os.getenv("DATABASE_URL", "sqlite:///gst_helper.db")
    if url.startswith("postgres://"):  # some hosts still use the old scheme name
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return create_engine(url)


def save_results(df, period):
    out = df.copy()
    out["return_period"] = period
    out.to_sql("reconciliation_results", get_engine(), if_exists="append", index=False)
    return len(out)
