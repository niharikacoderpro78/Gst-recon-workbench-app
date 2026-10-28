"""app.py - GST Recon Workbench: purchase register vs GSTR-2B."""
from pathlib import Path
import pandas as pd
import streamlit as st
from recon import reconcile, summarise, upcoming_due_dates
from db import save_results

HERE = Path(__file__).parent
st.set_page_config(page_title="GST Recon Workbench", page_icon="▤", layout="wide")
STATUSES = ["Matched", "Amount Mismatch", "Missing in GSTR-2B", "Missing in Books"]
FOLLOW = ["Pending", "Mail sent", "Awaiting reply", "Resolved"]

st.markdown("""<style>
html,body,.stApp{font-family:'Segoe UI',system-ui,sans-serif;color:#1b2430}
.stApp{background:#eef1f5}
#MainMenu,footer,header,[data-testid="stToolbar"],[data-testid="stDecoration"],[data-testid="stSidebar"],[data-testid="collapsedControl"],[data-testid="stHeaderActionElements"]{display:none!important}
.block-container{max-width:1280px;padding:1rem 1.4rem 2rem}
.top{background:#1f2f46;color:#e8eef7;padding:11px 18px;border-radius:4px;display:flex;justify-content:space-between;align-items:center;margin-bottom:14px}
.top b{font-size:16px;letter-spacing:.2px}.top span{font-size:12px;color:#9fb0c8}
.strip{display:grid;grid-template-columns:repeat(5,1fr);background:#fff;border:1px solid #cfd6e0;border-radius:4px;margin:10px 0 14px}
.strip div{padding:10px 16px;border-right:1px solid #e1e6ee}.strip div:last-child{border:0}
.strip small{display:block;font-size:11px;text-transform:uppercase;letter-spacing:.6px;color:#5d6b7e}
.strip b{font:600 20px Consolas,'Courier New',monospace;color:#1b2430}.strip .r b{color:#a4262c}
.stTabs [data-baseweb="tab-list"]{gap:2px;border-bottom:1px solid #cfd6e0}
.stTabs [data-baseweb="tab"]{font-weight:600;padding:8px 16px;font-size:14px}
.stTabs [aria-selected="true"]{color:#1f4e8c}
label,.stRadio label{font-size:12px!important}
.stButton>button,.stDownloadButton>button{border-radius:3px;background:#1f4e8c;color:#fff;border:0;font-weight:600;padding:.4rem 1rem}
.stButton>button:hover,.stDownloadButton>button:hover{background:#173b6b;color:#fff}
.note{font-size:12px;color:#5d6b7e;margin-top:18px}
</style>""", unsafe_allow_html=True)


def inr(x):
    s, neg = f"{abs(x):.0f}", x < 0
    if len(s) > 3:
        head, tail, parts = s[:-3], s[-3:], []
        while len(head) > 2:
            parts.insert(0, head[-2:]); head = head[:-2]
        s = ",".join(([head] if head else []) + parts + [tail])
    return ("-" if neg else "") + "₹" + s


def read(f):
    return pd.read_excel(f) if f.name.lower().endswith((".xlsx", ".xls")) else pd.read_csv(f)


st.markdown('<div class="top"><b>GST Recon Workbench</b><span>Purchase register vs GSTR-2B</span></div>', unsafe_allow_html=True)
months = list(pd.period_range(end=pd.Timestamp.today(), periods=12, freq="M").strftime("%b %Y"))[::-1]
c1, c2, c3, c4 = st.columns([1.4, 1, 1.2, 1])
client = c1.text_input("Client", "Demo Traders Pvt Ltd")
period = c2.selectbox("Return period", months, index=months.index("Sep 2026") if "Sep 2026" in months else 0)
source = c3.radio("Data source", ["Demo data", "Upload files"], horizontal=True)

if source == "Demo data":
    books = pd.read_csv(HERE / "sample_data" / "purchase_register.csv")
    g2b = pd.read_csv(HERE / "sample_data" / "gstr2b.csv")
else:
    u1, u2 = st.columns(2)
    fb = u1.file_uploader("Purchase register (CSV or Excel)", type=["csv", "xlsx"])
    fg = u2.file_uploader("GSTR-2B data (CSV or Excel)", type=["csv", "xlsx"])
    if not (fb and fg):
        st.stop()
    books, g2b = read(fb), read(fg)
try:
    res = reconcile(books, g2b)
except ValueError as e:
    st.error(str(e)); st.stop()
s = summarise(res)
c4.markdown("<div style='height:26px'></div>", unsafe_allow_html=True)
if c4.button("Save to database"):
    st.toast(f"{save_results(res, period)} rows saved for {period}")

st.markdown(
    f'<div class="strip"><div><small>ITC per books</small><b>{inr(s["itc_books"])}</b></div>'
    f'<div><small>ITC per GSTR-2B</small><b>{inr(s["itc_2b"])}</b></div>'
    f'<div><small>Difference</small><b>{inr(s["itc_books"] - s["itc_2b"])}</b></div>'
    f'<div class="r"><small>ITC at risk</small><b>{inr(s["itc_at_risk"])}</b></div>'
    f'<div><small>Matched</small><b>{s["matched"]} / {s["total"]}</b></div></div>', unsafe_allow_html=True)

notes = st.session_state.setdefault("notes", {})
t1, t2, t3 = st.tabs(["Reconciliation", "Vendor follow-up", "Due dates"])

with t1:
    f1, f2, f3 = st.columns([1.6, 1, 1])
    pick = f1.multiselect("Status", STATUSES, default=STATUSES[1:])
    q = f2.text_input("Search supplier or invoice")
    fu = f3.selectbox("Follow-up", ["All"] + FOLLOW)
    v = res[res["status"].isin(pick)].copy()
    if q:
        v = v[v["supplier_name"].str.contains(q, case=False, na=False) | v["invoice_no"].str.contains(q, case=False, na=False)]
    v["key_"] = v["supplier_gstin"] + "|" + v["invoice_no"]
    v["Follow-up"] = v["key_"].map(lambda k: notes.get(k, {}).get("s", "Pending"))
    v["Remarks"] = v["key_"].map(lambda k: notes.get(k, {}).get("r", ""))
    if fu != "All":
        v = v[v["Follow-up"] == fu]
    cols = ["supplier_name", "supplier_gstin", "invoice_no", "tax_books", "tax_2b", "difference", "status", "itc_at_risk", "Follow-up", "Remarks"]
    money = lambda t: st.column_config.NumberColumn(t, format="%.2f")
    edited = st.data_editor(v[cols], hide_index=True, width="stretch", height=430, key="grid",
        disabled=[c for c in cols if c not in ("Follow-up", "Remarks")],
        column_config={"supplier_name": "Supplier", "supplier_gstin": "GSTIN", "invoice_no": "Invoice no.",
                       "tax_books": money("Tax (books)"), "tax_2b": money("Tax (2B)"), "difference": money("Difference"),
                       "status": "Status", "itc_at_risk": money("ITC at risk"),
                       "Follow-up": st.column_config.SelectboxColumn("Follow-up", options=FOLLOW, required=True),
                       "Remarks": st.column_config.TextColumn("Remarks")})
    for i, row in edited.iterrows():
        notes[v.loc[i, "key_"]] = {"s": row["Follow-up"], "r": row["Remarks"]}
    st.download_button("Export to CSV", edited.to_csv(index=False).encode(), f"{client.replace(' ', '_')}_{period.replace(' ', '_')}_recon.csv", "text/csv")

with t2:
    risk = res[res["itc_at_risk"] > 0]
    grp = (risk.groupby(["supplier_name", "supplier_gstin"]).agg(Invoices=("invoice_no", "count"), ITC_at_risk=("itc_at_risk", "sum"))
           .reset_index().sort_values("ITC_at_risk", ascending=False))
    left, right = st.columns([1, 1])
    left.dataframe(grp, hide_index=True, width="stretch", height=380, column_config={
        "supplier_name": "Supplier", "supplier_gstin": "GSTIN", "ITC_at_risk": money("ITC at risk")})
    if len(grp):
        sup = right.selectbox("Draft message for", grp["supplier_name"])
        lines = "\n".join(f"- {r.invoice_no}: ITC Rs.{r.itc_at_risk:,.2f} ({r.status})" for r in risk[risk["supplier_name"] == sup].itertuples())
        msg = (f"Dear {sup},\n\nWhile reconciling our purchase records for {period}, we could not find the following invoices "
               f"(or found a different tax amount) in our GSTR-2B:\n\n{lines}\n\nKindly confirm that these were reported in your GSTR-1 "
               f"and share the filing status.\n\nRegards,\n{client}")
        right.text_area("Message (edit before sending)", msg, height=300)

with t3:
    st.dataframe(upcoming_due_dates(n=8), hide_index=True, width="stretch", column_config={"Due date": st.column_config.DateColumn(format="DD MMM YYYY")})
    st.markdown('<div class="note">Standard monthly-filer dates. Verify on the official GST portal, as extensions and QRMP schedules differ.</div>', unsafe_allow_html=True)

st.markdown('<div class="note">Reconciliation aid only, not tax advice. Confirm figures with your CA. Demo data is synthetic.</div>', unsafe_allow_html=True)