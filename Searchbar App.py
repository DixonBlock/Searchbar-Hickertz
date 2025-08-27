import io
import re
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Quick Finder", page_icon="🧀", layout="wide")

st.title("🧀 Quick Finder — Warehouse Article Search")
st.caption("Search your existing Excel/CSV and get just the fields you need.")

# -----------------------------
# Helpers
# -----------------------------
@st.cache_data(show_spinner=False)
def load_file(file_bytes: bytes, filename: str, sheet_name=None):
    """Load CSV or Excel from bytes. Returns a DataFrame."""
    name_lower = (filename or "").lower()
    if name_lower.endswith((".xlsx", ".xls")):
        try:
            # If no sheet specified, use the first sheet
            target_sheet = 0 if sheet_name in (None, "", "None") else sheet_name
            return pd.read_excel(io.BytesIO(file_bytes), sheet_name=target_sheet, dtype=str)
        except Exception as e:
            raise RuntimeError(f"Failed to read Excel file: {e}")
    else:
        # CSV fallback: try several encodings and delimiters
        encodings = ["utf-8", "utf-8-sig", "cp1252", "latin-1"]
        for enc in encodings:
            try:
                df = pd.read_csv(io.BytesIO(file_bytes), encoding=enc, sep=None, engine="python", dtype=str)
                if df.shape[1] > 1:
                    return df
            except Exception:
                continue
        raise RuntimeError("Failed to read CSV. Try re-exporting as UTF-8 or Excel (.xlsx).")

def normalize_col(col: str) -> str:
    """Normalize a column name for matching (lowercase, alphanumeric)."""
    return re.sub(r'[^a-z0-9]+', ' ', str(col).strip().lower()).strip()

def best_default_output_cols(cols):
    """Pick default output columns based on common names, else first four."""
    wanted = [
        ["article number","articlenumber","article no","artikelnummer","item number","sku"],
        ["description","desc","item description"],
        ["main vendor","vendor","supplier","lieferant"],
        ["article type","type","category","kategorie","warengruppe"],
    ]
    norm_index = {normalize_col(c): c for c in cols}
    picked = []
    for aliases in wanted:
        for alias in aliases:
            if alias in norm_index and norm_index[alias] not in picked:
                picked.append(norm_index[alias])
                break
    return picked[:4] if picked else cols[:4]

def search_df(df, query, search_cols, mode="any", case=False, startswith=False, exact=False):
    """Search the DataFrame for one or more terms across given columns."""
    if not query:
        return df

    # Split into terms, supporting quoted phrases
    import re
    terms = re.findall(r'"([^"]+)"|(\S+)', query)
    terms = [t[0] or t[1] for t in terms if (t[0] or t[1])]
    if not terms:
        terms = [query]

    def make_matcher(series: pd.Series, term: str):
        if not case:
            series = series.str.lower()
            term = term.lower()
        if exact:
            return series == term
        if startswith:
            return series.str.startswith(term, na=False)
        return series.str.contains(re.escape(term), na=False)

    # Build mask
    mask = pd.Series(True if mode == "all" else False, index=df.index)
    for term in terms:
        col_matches = pd.Series(False, index=df.index)
        for c in search_cols:
            s = df[c].astype(str)
            col_matches = col_matches | make_matcher(s, term)
        if mode == "all":
            mask = mask & col_matches
        else:  # any
            mask = mask | col_matches

    return df[mask]


# -----------------------------
# Sidebar: Data source
# -----------------------------
with st.sidebar:
    st.header("Data Source")
    up = st.file_uploader("Upload your Excel or CSV file", type=["csv","xlsx","xls"])
    sheet = None
    if up and up.name.lower().endswith((".xlsx",".xls")):
        sheet = st.text_input("Excel sheet name (optional)", value="")
        sheet = sheet or None

    if up:
        try:
            df = load_file(up.getvalue(), up.name, sheet_name=sheet)
        except Exception as e:
            st.error(str(e))
            st.stop()
    else:
        st.info("Upload a CSV or Excel file to begin.")
        st.stop()

# Clean column names for selection controls but keep originals
all_columns = list(df.columns)
st.write(f"**Loaded rows:** {len(df):,} — **Columns:** {len(all_columns)}")

# -----------------------------
# Search controls
# -----------------------------
search_query = st.text_input("Search terms (use quotes for phrases)", placeholder='e.g., "gouda young" 12345 acme')
col_choice = st.multiselect(
    "Columns to search (default: all)",
    options=all_columns,
    default=all_columns,
)

mode = st.radio("Match terms using", options=["Any term", "All terms"], horizontal=True, index=0)
mode_key = "any" if mode == "Any term" else "all"

c1, c2, c3 = st.columns(3)
with c1:
    startswith = st.checkbox("Starts with", value=False, help="Match only the beginning of words/fields.")
with c2:
    exact = st.checkbox("Exact match", value=False, help="Exact field match.")
with c3:
    case = st.checkbox("Case sensitive", value=False)

# -----------------------------
# Output columns
# -----------------------------
default_out = best_default_output_cols(all_columns)
out_cols = st.multiselect(
    "Output columns (add or remove as needed)",
    options=all_columns,
    default=default_out,
    help="By default shows Article Number, Description, Main Vendor, and Article Type if found."
)

# -----------------------------
# Do the search
# -----------------------------
res = search_df(df, search_query.strip(), col_choice, mode=mode_key, case=case, startswith=startswith, exact=exact)

# Keep selected output cols that exist
out_cols = [c for c in out_cols if c in res.columns]
if not out_cols:
    out_cols = default_out[:]

res_view = res[out_cols].copy()

st.subheader("Results")
st.caption("Showing only selected output columns.")
st.dataframe(res_view, use_container_width=True, hide_index=True)

# Summary + download
st.write(f"**Matches:** {len(res_view):,}")

csv = res_view.to_csv(index=False).encode("utf-8")
st.download_button("Download results as CSV", data=csv, file_name="quick_finder_results.csv", mime="text/csv")

st.markdown("---")
with st.expander("Tips"):
    st.markdown(
        """
- Put phrases in quotes: `"gouda young"`
- Toggle **Any/All** to control whether all terms must appear.
- Use **Starts with** for prefix searches like vendor codes.
- Use **Exact match** for precise SKU/ID lookups.
- Add more columns to results via **Output columns**.
        """
    )
