"""recon.py - core reconciliation logic: purchase register (books) vs GSTR-2B."""
import re
from datetime import date
import numpy as np
import pandas as pd

REQUIRED = ["invoice_no", "invoice_date", "supplier_gstin", "supplier_name",
            "taxable_value", "igst", "cgst", "sgst"]
TOLERANCE = 1.0  # differences up to Rs.1 are treated as rounding


def clean_invoice_no(x):
    """Normalise invoice numbers: 'inv-0045' and 'INV 0045' become the same key."""
    return re.sub(r"[^A-Z0-9]", "", str(x).upper())


def prepare(df, label):
    """Validate columns, clean numbers, and add the matching key and total tax."""
    df = df.copy()
    df.columns = [c.strip().lower() for c in df.columns]
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"{label} is missing required columns: {', '.join(missing)}")
    for c in ["taxable_value", "igst", "cgst", "sgst"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    df["supplier_gstin"] = df["supplier_gstin"].astype(str).str.strip().str.upper()
    df["key"] = df["invoice_no"].map(clean_invoice_no)
    df["tax"] = df["igst"] + df["cgst"] + df["sgst"]  # total GST = ITC amount
    return df


def _combine(d):
    """Merge repeated rows of the same invoice so duplicates do not inflate totals."""
    return d.groupby(["supplier_gstin", "key"], as_index=False).agg(
        invoice_no=("invoice_no", "first"), supplier_name=("supplier_name", "first"),
        taxable_value=("taxable_value", "sum"), tax=("tax", "sum"))


def reconcile(books, gstr2b):
    """Join both sources on GSTIN + invoice key and classify every invoice."""
    b, g = _combine(prepare(books, "Purchase register")), _combine(prepare(gstr2b, "GSTR-2B"))
    m = b.merge(g, on=["supplier_gstin", "key"], how="outer",
                suffixes=("_books", "_2b"), indicator=True)  # outer join keeps rows from both sides
    m["tax_books"] = m["tax_books"].fillna(0)
    m["tax_2b"] = m["tax_2b"].fillna(0)
    m["difference"] = (m["tax_books"] - m["tax_2b"]).round(2)
    m["status"] = np.select(
        [m["_merge"] == "left_only", m["_merge"] == "right_only", m["difference"].abs() > TOLERANCE],
        ["Missing in GSTR-2B", "Missing in Books", "Amount Mismatch"], default="Matched")
    # ITC at risk: full tax if absent from 2B, otherwise only the shortfall
    m["itc_at_risk"] = np.where(m["status"] == "Missing in GSTR-2B", m["tax_books"],
                       np.where((m["status"] == "Amount Mismatch") & (m["difference"] > 0), m["difference"], 0))
    m["invoice_no"] = m["invoice_no_books"].fillna(m["invoice_no_2b"])
    m["supplier_name"] = m["supplier_name_books"].fillna(m["supplier_name_2b"])
    cols = ["supplier_gstin", "supplier_name", "invoice_no", "tax_books", "tax_2b",
            "difference", "status", "itc_at_risk"]
    return m[cols].sort_values(["status", "itc_at_risk"], ascending=[True, False]).reset_index(drop=True)


def summarise(r):
    """Headline KPIs."""
    return {
        "itc_books": r["tax_books"].sum(),
        "itc_2b": r["tax_2b"].sum(),
        "itc_at_risk": r["itc_at_risk"].sum(),
        "extra_in_2b": r.loc[r["status"] == "Missing in Books", "tax_2b"].sum(),
        "matched": int((r["status"] == "Matched").sum()),
        "total": len(r),
    }


def vendor_risk(r, n=8):
    """Suppliers holding back the most ITC."""
    return (r.groupby("supplier_name")["itc_at_risk"].sum()
             .sort_values(ascending=False).head(n).loc[lambda s: s > 0])


def upcoming_due_dates(today=None, n=6):
    """Next statutory dates for a monthly filer. Verify on the official portal: dates can change."""
    today = today or date.today()
    items = []
    for i in range(4):
        y, mth = today.year + (today.month - 1 + i) // 12, (today.month - 1 + i) % 12 + 1
        for name, d in [("TDS deposit", 7), ("GSTR-1 filing", 11), ("GSTR-3B filing", 20)]:
            items.append((name, date(y, mth, d)))
    for mth in (3, 6, 9, 12):
        for y in (today.year, today.year + 1):
            items.append(("Advance tax instalment", date(y, mth, 15)))
    df = pd.DataFrame(items, columns=["Obligation", "Due date"])
    df = df[df["Due date"] >= today].sort_values("Due date").head(n).reset_index(drop=True)
    df["Days left"] = [(d - today).days for d in df["Due date"]]
    return df
