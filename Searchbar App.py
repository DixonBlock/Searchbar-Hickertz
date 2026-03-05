# Searchbar App.py
# Hickertz Quick Finder — keyboard-friendly results → batch list (duplicates allowed + highlighted)
# Uses robust loader for BOTH uploads and default_data.csv (EU/US CSV compatible)
# Layout: Search controls on top; Results (left) + Batch (right) underneath
# Column widths: autosize-to-content with sensible caps; user-resizable

import io
import re
from pathlib import Path

import pandas as pd
import streamlit as st
from st_aggrid import (
    AgGrid,
    GridOptionsBuilder,
    GridUpdateMode,
    DataReturnMode,
    JsCode,
)

st.set_page_config(page_title="Quick Finder", page_icon="🧀", layout="wide")


# ---------------------------------------------------
# SESSION STATE
# ---------------------------------------------------
if "batch" not in st.session_state:
    st.session_state.batch = pd.DataFrame()


# ---------------------------------------------------
# LOADERS (robust + EU/US CSV compatible)
# ---------------------------------------------------
@st.cache_data(show_spinner=False)
def _read_csv_bytes(file_bytes: bytes) -> pd.DataFrame:
    encodings = ["utf-8-sig", "utf-8", "cp1252", "latin-1"]

    last_err = None
    for enc in encodings:
        try:
            df = pd.read_csv(
                io.BytesIO(file_bytes),
                encoding=enc,
                sep=None,          # auto-detect delimiter (, ; \t |)
                engine="python",   # more tolerant parser
                dtype=str,
                keep_default_na=False,
            )
            if df.shape[1] > 1:
                return df
        except Exception as e:
            last_err = e
            continue

    raise RuntimeError(
        f"Unable to read CSV (tried multiple encodings/delimiters). Last error: {last_err}"
    )


@st.cache_data(show_spinner=False)
def load_file(file_bytes: bytes, filename: str, sheet=None) -> pd.DataFrame:
    name = (filename or "").lower()
    if name.endswith(("xlsx", "xls")):
        target = 0 if not sheet else sheet
        # dtype=str keeps codes like 01-01 from becoming dates
        return pd.read_excel(io.BytesIO(file_bytes), sheet_name=target, dtype=str)

    return _read_csv_bytes(file_bytes)


@st.cache_data(show_spinner=False)
def load_default() -> pd.DataFrame | None:
    default_path = Path("default_data.csv")
    if not default_path.exists():
        return None
    return _read_csv_bytes(default_path.read_bytes())


# ---------------------------------------------------
# NORMALIZATION (fix "01. Jan" / date-like LP values)
# ---------------------------------------------------
def _normalize_colname(c: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(c).strip().lower()).strip()


MONTHS = {
    # German
    "jan": "01", "januar": "01",
    "feb": "02", "februar": "02",
    "mär": "03", "maer": "03", "maerz": "03", "märz": "03",
    "apr": "04", "april": "04",
    "mai": "05",
    "jun": "06", "juni": "06",
    "jul": "07", "juli": "07",
    "aug": "08", "august": "08",
    "sep": "09", "sept": "09", "september": "09",
    "okt": "10", "oktober": "10",
    "nov": "11", "november": "11",
    "dez": "12", "dezember": "12",
    # English
    "jan.": "01", "feb.": "02", "mar": "03", "mar.": "03",
    "apr.": "04", "may": "05", "jun.": "06", "jul.": "07",
    "aug.": "08", "sep.": "09", "oct": "10", "oct.": "10",
    "nov.": "11", "dec": "12", "dec.": "12",
}


def normalize_lagerplatz_values(df: pd.DataFrame) -> pd.DataFrame:
    """If an LP column contains '01. Jan' or date-like strings, convert to 'DD-MM' text."""
    cols = list(df.columns)
    lp_cols = []
    for c in cols:
        nc = _normalize_colname(c)
        if (
            nc == "lp"
            or " neue lp" in f" {nc} "
            or "lagerplatz" in nc
            or nc.endswith(" lp")
            or " lp " in f" {nc} "
        ):
            lp_cols.append(c)

    if not lp_cols:
        return df

    def convert_one(x: str) -> str:
        s = str(x).strip()
        if not s or s.lower() in ("nan", "none"):
            return ""

        # Already looks like DD-MM (keep)
        if re.fullmatch(r"\d{1,2}-\d{1,2}", s):
            dd, mm = s.split("-")
            return f"{dd.zfill(2)}-{mm.zfill(2)}"

        # "01. Jan" / "1. Jan" / "01. Januar"
        m = re.match(r"^\s*(\d{1,2})\.\s*([A-Za-zÄÖÜäöü\.]+)\s*$", s)
        if m:
            dd = m.group(1).zfill(2)
            mon_raw = m.group(2).strip().lower()
            mon_raw = mon_raw.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
            mon_raw = mon_raw.strip(".")
            mm = MONTHS.get(mon_raw)
            if mm:
                return f"{dd}-{mm}"

        # "2026-01-01" or "2026-01-01 00:00:00"
        m = re.match(r"^\s*(\d{4})[-/](\d{1,2})[-/](\d{1,2}).*$", s)
        if m:
            mm = m.group(2).zfill(2)
            dd = m.group(3).zfill(2)
            return f"{dd}-{mm}"

        # Excel-ish "01/01/2026"
        m = re.match(r"^\s*(\d{1,2})[./-](\d{1,2})[./-](\d{2,4}).*$", s)
        if m:
            dd = m.group(1).zfill(2)
            mm = m.group(2).zfill(2)
            return f"{dd}-{mm}"

        return s

    out = df.copy()
    for c in lp_cols:
        out[c] = out[c].astype(str).map(convert_one)
    return out


# ---------------------------------------------------
# SEARCH
# ---------------------------------------------------
def search_df(df: pd.DataFrame, query: str, cols: list[str]) -> pd.DataFrame:
    if not query:
        return df

    terms = re.findall(r'"([^"]+)"|(\S+)', query)
    terms = [t[0] or t[1] for t in terms if (t[0] or t[1])]
    if not terms:
        return df

    mask = pd.Series(False, index=df.index)
    for term in terms:
        matches = pd.Series(False, index=df.index)
        term_esc = re.escape(term)
        for c in cols:
            matches |= df[c].astype(str).str.contains(term_esc, case=False, na=False, regex=True)
        mask |= matches

    return df[mask]


# ---------------------------------------------------
# DATA SOURCE UI
# ---------------------------------------------------
st.sidebar.header("Data Source")
uploaded = st.sidebar.file_uploader("Upload CSV or Excel", type=["csv", "xlsx", "xls"])

sheet = None
if uploaded and uploaded.name.lower().endswith(("xlsx", "xls")):
    sheet = st.sidebar.text_input("Excel sheet name (optional)", value="").strip() or None

if uploaded:
    df = load_file(uploaded.getvalue(), uploaded.name, sheet)
else:
    df = load_default()
    if df is None:
        st.warning("Upload a file or include default_data.csv in the repo root.")
        st.stop()

# Ensure everything is text + normalize LP values (fix default data showing dates/months)
df = df.astype(str)
df = normalize_lagerplatz_values(df)


# ---------------------------------------------------
# AUTO DETECT ARTICLE COLUMN
# ---------------------------------------------------
possible_article_cols = ["Art. Nr.", "Art Nr", "Artikelnummer", "Article Number", "SKU"]

article_col = None
for col in df.columns:
    if col in possible_article_cols:
        article_col = col
        break
if article_col is None:
    article_col = df.columns[0]


# ---------------------------------------------------
# UI
# ---------------------------------------------------
st.title("🧀 Hickertz Quick Finder")

# Controls (search/filters) on top; then Results + Batch underneath
controls = st.container()
results_col, batch_col = st.columns([2.2, 1.8], gap="large")

# JS: Enter selects focused row; prevents Streamlit focus weirdness
enter_select = JsCode(
    """
function(e){
  if(!e || !e.event) return;
  if(e.event.key === 'Enter'){
    const api = e.api;
    const focused = api.getFocusedCell();
    if(!focused) return;
    const node = api.getDisplayedRowAtIndex(focused.rowIndex);
    if(node){
      node.setSelected(true, true);
    }
    e.event.preventDefault();
  }
}
"""
)

# JS: autosize-to-content with sensible caps; NO sizeColumnsToFit (prevents messed proportions)
first_data_rendered = JsCode(
    """
function(e){
  try{
    const allCols = e.columnApi.getAllColumns().map(c => c.getColId());

    // Autosize to content
    e.columnApi.autoSizeColumns(allCols, false);

    // Cap overly wide columns so key text columns keep space
    allCols.forEach(id => {
      const col = e.columnApi.getColumn(id);
      if(!col) return;

      const w = col.getActualWidth();
      const low = (id || '').toLowerCase();

      const maxW =
        (low.includes('beschreib') || low.includes('description')) ? 650 :
        (low.includes('liefer')   || low.includes('vendor') || low.includes('supplier')) ? 360 :
        (low.includes('art')      || low.includes('artikel') || low.includes('sku')) ? 160 :
        (low.includes('lp')       || low.includes('lagerplatz')) ? 190 :
        320;

      const minW =
        (low.includes('beschreib') || low.includes('description')) ? 260 :
        (low.includes('liefer')   || low.includes('vendor') || low.includes('supplier')) ? 180 :
        (low.includes('art')      || low.includes('artikel') || low.includes('sku')) ? 110 :
        (low.includes('lp')       || low.includes('lagerplatz')) ? 120 :
        120;

      if(w > maxW) e.columnApi.setColumnWidth(id, maxW, false);
      if(w < minW) e.columnApi.setColumnWidth(id, minW, false);
    });

  } catch(err) {}
}
"""
)


def _apply_column_layout(gb: GridOptionsBuilder, cols: list[str]):
    """Prefer wide text columns, keep ID/LP compact; still resizable."""
    for c in cols:
        nc = _normalize_colname(c)

        if "beschreib" in nc or "description" in nc:
            gb.configure_column(c, minWidth=260, flex=3, wrapText=True, autoHeight=True)
        elif "lieferant" in nc or "vendor" in nc or "supplier" in nc:
            gb.configure_column(c, minWidth=180, flex=2, wrapText=True, autoHeight=True)
        elif "artikelnummer" in nc or "article number" in nc or "sku" in nc or nc in ("art nr", "art nr.", "art. nr", "art. nr."):
            gb.configure_column(c, width=120, minWidth=95, maxWidth=160, flex=0)
        elif "lp" in nc or "lagerplatz" in nc:
            gb.configure_column(c, width=140, minWidth=110, maxWidth=190, flex=0)
        else:
            gb.configure_column(c, minWidth=120, flex=1, wrapText=True, autoHeight=True)


# ---------------------------------------------------
# CONTROLS (top)
# ---------------------------------------------------
with controls:
    st.write(f"Rows loaded: {len(df):,}")

    # moved above search input (as requested)
    cols = st.multiselect(
        "Columns to search",
        options=list(df.columns),
        default=list(df.columns),
    )

    search_query = st.text_input("Search", key="search_box")


# ---------------------------------------------------
# RESULTS (left)
# ---------------------------------------------------
with results_col:
    res = search_df(df, search_query.strip(), cols)

    st.subheader("Results")

    gb = GridOptionsBuilder.from_dataframe(res)
    gb.configure_default_column(resizable=True, wrapText=True, autoHeight=True)
    gb.configure_selection(selection_mode="single", use_checkbox=False)

    _apply_column_layout(gb, list(res.columns))

    gb.configure_grid_options(
        onCellKeyDown=enter_select,
        onFirstDataRendered=first_data_rendered,
        suppressRowClickSelection=False,
        rowSelection="single",
    )

    grid = AgGrid(
        res,
        gridOptions=gb.build(),
        height=560,
        data_return_mode=DataReturnMode.FILTERED_AND_SORTED,
        update_mode=GridUpdateMode.SELECTION_CHANGED,
        allow_unsafe_jscode=True,
        fit_columns_on_grid_load=False,
        theme="alpine",
    )

    selected = grid.get("selected_rows", [])
    sel_df = selected if isinstance(selected, pd.DataFrame) else pd.DataFrame(selected)

    # Allow duplicates (append whatever was selected)
    if not sel_df.empty:
        st.session_state.batch = pd.concat([st.session_state.batch, sel_df], ignore_index=True)


# ---------------------------------------------------
# BATCH (right)
# ---------------------------------------------------
with batch_col:
    st.subheader("Batch List")

    batch = st.session_state.batch

    if batch.empty:
        st.info("No items added")
    else:
        # Duplicates allowed: highlight duplicates by article_col if present
        if article_col in batch.columns:
            dup_mask = batch[article_col].duplicated(keep=False)
        else:
            dup_mask = pd.Series(False, index=batch.index)

        batch_view = batch.copy()
        batch_view["dup"] = dup_mask

        highlight = JsCode(
            """
function(params){
  if(params.data && params.data.dup === true){
    return {backgroundColor:'#007672', color:'white'};
  }
  return {};
}
"""
        )

        gb2 = GridOptionsBuilder.from_dataframe(batch_view)
        gb2.configure_default_column(resizable=True, wrapText=True, autoHeight=True)
        gb2.configure_column("dup", hide=True)

        # Row drag reorder on first visible column
        first_col = batch_view.columns[0]
        gb2.configure_column(first_col, rowDrag=True)

        # Delete selected rows via checkbox selection
        gb2.configure_selection("multiple", use_checkbox=True)

        _apply_column_layout(gb2, [c for c in batch_view.columns if c != "dup"])

        gb2.configure_grid_options(
            rowDragManaged=True,
            animateRows=True,
            getRowStyle=highlight,
            onFirstDataRendered=first_data_rendered,
        )

        batch_grid = AgGrid(
            batch_view,
            gridOptions=gb2.build(),
            height=560,
            data_return_mode=DataReturnMode.FILTERED_AND_SORTED,
            update_mode=GridUpdateMode.MODEL_CHANGED | GridUpdateMode.SELECTION_CHANGED,
            allow_unsafe_jscode=True,
            fit_columns_on_grid_load=False,
            theme="alpine",
        )

        new_data = batch_grid.get("data")
        if isinstance(new_data, pd.DataFrame):
            if "dup" in new_data.columns:
                new_data = new_data.drop(columns=["dup"])
            st.session_state.batch = new_data

        selected = batch_grid.get("selected_rows", [])
        del_df = selected if isinstance(selected, pd.DataFrame) else pd.DataFrame(selected)

        c1, c2 = st.columns(2)
        with c1:
            if st.button("Delete Selected"):
                if not del_df.empty:
                    cur = st.session_state.batch.copy()

                    # Remove matching rows one-by-one (keeps duplicates distinct)
                    for _, row in del_df.iterrows():
                        idx = cur[(cur == row).all(axis=1)].index
                        if len(idx) > 0:
                            cur = cur.drop(idx[0])

                    st.session_state.batch = cur.reset_index(drop=True)
                    st.rerun()

        with c2:
            if st.button("Clear Batch"):
                st.session_state.batch = pd.DataFrame()
                st.rerun()

        st.write("Rows:", len(st.session_state.batch))

        csv = st.session_state.batch.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Download CSV for Excel",
            data=csv,
            file_name="batch_export.csv",
            mime="text/csv",
        )
