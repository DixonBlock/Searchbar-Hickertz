# Searchbar App.py
# Hickertz Quick Search — keyboard-friendly results → batch list (duplicates allowed + highlighted)
# Dark mode + tight padding + robust loader (EU/US CSV compatible)
# Layout: Controls on top; Results (left) + Batch (right) underneath
# Column widths: autosize-to-content with caps + enforced minimums; user-resizable

import io
import re
import unicodedata
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

st.set_page_config(page_title="Quick Search", page_icon="🧀", layout="wide")

st.markdown("""
<link rel="manifest" href="manifest.json">

<script>
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('service-worker.js')
}
</script>
""", unsafe_allow_html=True)

# ---------------------------------------------------
# TIGHT UI (reduce padding / maximize data space)
# ---------------------------------------------------
st.markdown(
    """
<style>
/* Reduce Streamlit default padding/margins */
.block-container { padding-top: 4.2rem; padding-bottom: 0.6rem; padding-left: 0.6rem; padding-right: 0.6rem; }
div[data-testid="stVerticalBlock"] { gap: 0.35rem; }
div[data-testid="column"] { padding-left: 0.15rem; padding-right: 0.15rem; }

/* Reduce header spacing but keep title readable */
h1 { margin-top: 4.2rem; margin-bottom: 0.4rem; }
h2, h3 { margin-top: 0.2rem; margin-bottom: 0.35rem; }

/* Reduce widget spacing slightly */
div[data-testid="stMultiselect"], div[data-testid="stTextInput"] { margin-bottom: 0.15rem; }

/* Slightly tighten AgGrid wrapper spacing */
.stAgGrid { margin-top: 0.15rem; margin-bottom: 0.15rem; }
</style>
""",
    unsafe_allow_html=True,
)

# ---------------------------------------------------
# SESSION STATE
# ---------------------------------------------------
if "batch" not in st.session_state:
    st.session_state.batch = pd.DataFrame()

if "results_grid_key" not in st.session_state:
    st.session_state.results_grid_key = 0


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
                engine="python",   # tolerant parser
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

        if re.fullmatch(r"\d{1,2}-\d{1,2}", s):
            dd, mm = s.split("-")
            return f"{dd.zfill(2)}-{mm.zfill(2)}"

        m = re.match(r"^\s*(\d{1,2})\.\s*([A-Za-zÄÖÜäöü\.]+)\s*$", s)
        if m:
            dd = m.group(1).zfill(2)
            mon_raw = m.group(2).strip().lower()
            mon_raw = mon_raw.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
            mon_raw = mon_raw.strip(".")
            mm = MONTHS.get(mon_raw)
            if mm:
                return f"{dd}-{mm}"

        m = re.match(r"^\s*(\d{4})[-/](\d{1,2})[-/](\d{1,2}).*$", s)
        if m:
            mm = m.group(2).zfill(2)
            dd = m.group(3).zfill(2)
            return f"{dd}-{mm}"

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


def strip_accents(s: str) -> str:
    # NFKD decomposes accented chars into base + combining marks
    s = unicodedata.normalize("NFKD", str(s))
    # remove combining marks
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s


# ---------------------------------------------------
# SEARCH
# ---------------------------------------------------
def search_df(df: pd.DataFrame, query: str, cols: list[str]) -> pd.DataFrame:
    if not query:
        return df

    # Split into terms, supporting quoted phrases
    terms = re.findall(r'"([^"]+)"|(\S+)', query)
    terms = [t[0] or t[1] for t in terms if (t[0] or t[1])]
    if not terms:
        return df

    # Normalize query (lower + strip accents)
    terms_norm = [strip_accents(t).lower() for t in terms]

    mask = pd.Series(True, index=df.index)

    for term_norm in terms_norm:
        # Match across any selected column
        matches = pd.Series(False, index=df.index)

        # Use escaped regex term
        term_esc = re.escape(term_norm)

        for c in cols:
            # Normalize cell text (lower + strip accents) on the fly
            s = df[c].astype(str).map(strip_accents).str.lower()
            matches |= s.str.contains(term_esc, case=False, na=False, regex=True)

        mask &= matches

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

df = df.astype(str)
df = normalize_lagerplatz_values(df)


# ---------------------------------------------------
# AUTO DETECT ARTICLE COLUMN (unique identifier)
# ---------------------------------------------------
possible_article_cols = ["Art. Nr.", "Art Nr", "Artikelnummer", "Article Number", "SKU"]

article_col = None
for col in df.columns:
    if col in possible_article_cols:
        article_col = col
        break
if article_col is None:
    article_col = df.columns[0]


def reorder_columns(df: pd.DataFrame, first: list[str] | None = None) -> pd.DataFrame:
    """
    Move columns in `first` to the front (in that order), keep the rest after.
    Ignores names that don't exist.
    """
    if not first:
        return df
    first_existing = [c for c in first if c in df.columns]
    rest = [c for c in df.columns if c not in first_existing]
    return df[first_existing + rest]


# ---------------------------------------------------
# UI
# ---------------------------------------------------
st.title("🧀 Hickertz Quick Search")

controls = st.container()
results_col, batch_col = st.columns([2.25, 1.75], gap="medium")


# ---------------------------------------------------
# JS helpers
# ---------------------------------------------------
enter_select = JsCode(
    """
function(e){
  if(!e || !e.event) return;
  if(e.event.key === 'Enter'){
    const api = e.api;
    const focused = api.getFocusedCell();
    if(!focused) return;
    const node = api.getDisplayedRowAtIndex(focused.rowIndex);
    if(node){ node.setSelected(true, true); }
    e.event.preventDefault();
  }
}
"""
)

# Autosize + enforce mins (prevents Art.Nr shrinking past min)
first_data_rendered = JsCode(
    """
function(e){
  try{
    const allCols = e.columnApi.getAllColumns().map(c => c.getColId());

    // Autosize to content first
    e.columnApi.autoSizeColumns(allCols, false);

    // Cap max and enforce mins
    allCols.forEach(id => {
      const low = (id || '').toLowerCase();
      const col = e.columnApi.getColumn(id);
      if(!col) return;

      const w = col.getActualWidth();

      const minW =
        (low.includes('beschreib') || low.includes('description')) ? 260 :
        (low.includes('liefer')   || low.includes('vendor') || low.includes('supplier')) ? 180 :
        (low.includes('art')      || low.includes('artikel') || low.includes('sku')) ? 110 :
        (low.includes('lp')       || low.includes('lagerplatz')) ? 120 :
        120;

      const maxW =
        (low.includes('beschreib') || low.includes('description')) ? 650 :
        (low.includes('liefer')   || low.includes('vendor') || low.includes('supplier')) ? 360 :
        (low.includes('art')      || low.includes('artikel') || low.includes('sku')) ? 170 :
        (low.includes('lp')       || low.includes('lagerplatz')) ? 200 :
        320;

      if(w < minW) e.columnApi.setColumnWidth(id, minW, false);
      if(w > maxW) e.columnApi.setColumnWidth(id, maxW, false);
    });

  } catch(err) {}
}
"""
)


def _apply_column_layout(gb: GridOptionsBuilder, cols: list[str], article_col_name: str | None = None):
    """
    Set reasonable min/max defaults but keep resizable.
    IMPORTANT: also explicitly enforce the identifier (Art. Nr.) column.
    """
    for c in cols:
        nc = _normalize_colname(c)

        is_article = False
        if article_col_name and c == article_col_name:
            is_article = True
        else:
            # fallback detection if exact name differs
            if "artikelnummer" in nc or nc.startswith("art") or "sku" in nc or "article number" in nc:
                is_article = True

        if "beschreib" in nc or "description" in nc:
            gb.configure_column(c, minWidth=260, maxWidth=650, flex=3, wrapText=True, autoHeight=True)
        elif "lieferant" in nc or "vendor" in nc or "supplier" in nc:
            gb.configure_column(c, minWidth=180, maxWidth=360, flex=2, wrapText=True, autoHeight=True)
        elif is_article:
            # hard minimum so it can't collapse into nonsense
            gb.configure_column(c, minWidth=110, width=130, maxWidth=170, flex=0, wrapText=False)
        elif "lp" in nc or "lagerplatz" in nc:
            gb.configure_column(c, minWidth=120, width=150, maxWidth=200, flex=0, wrapText=False)
        else:
            gb.configure_column(c, minWidth=120, maxWidth=320, flex=1, wrapText=True, autoHeight=True)


# ---------------------------------------------------
# CONTROLS (top)
# ---------------------------------------------------
with controls:
    st.write(f"Rows loaded: {len(df):,}")

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

    PREFERRED_ORDER = ["Art. Nr.", "Beschreibung", "Neue LP", "Lieferant"]  # adjust to your headers
    res = reorder_columns(res, PREFERRED_ORDER)

    st.subheader("Results")

    gb = GridOptionsBuilder.from_dataframe(res)
    gb.configure_default_column(resizable=True, wrapText=True, autoHeight=True)
    gb.configure_selection(selection_mode="single", use_checkbox=False)

    _apply_column_layout(gb, list(res.columns), article_col_name=article_col)

    gb.configure_grid_options(
        onCellKeyDown=enter_select,
        onFirstDataRendered=first_data_rendered,
        suppressRowClickSelection=False,
        rowSelection="single",
        # helps keep navigation smooth
        suppressCellFocus=False,
    )

    grid = AgGrid(
        res,
        gridOptions=gb.build(),
        height=560,
        data_return_mode=DataReturnMode.FILTERED_AND_SORTED,
        update_mode=GridUpdateMode.SELECTION_CHANGED,
        allow_unsafe_jscode=True,
        fit_columns_on_grid_load=False,
        theme="streamlit", # <- dark-mode friendly (matches Streamlit theme)
        key=f"results_grid_{st.session_state.results_grid_key}",    
    )

    selected = grid.get("selected_rows", [])
    sel_df = selected if isinstance(selected, pd.DataFrame) else pd.DataFrame(selected)

    # Allow duplicates
    if not sel_df.empty:
    st.session_state.batch = pd.concat([st.session_state.batch, sel_df], ignore_index=True)
    st.session_state.results_grid_key += 1
    st.rerun()


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

        batch = reorder_columns(batch, PREFERRED_ORDER)
        st.session_state.batch = batch  # keep state consistent with new order

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

        _apply_column_layout(gb2, [c for c in batch_view.columns if c != "dup"], article_col_name=article_col)

        gb2.configure_grid_options(
            rowDragManaged=True,
            animateRows=True,
            getRowStyle=highlight,
            onFirstDataRendered=first_data_rendered,
            suppressCellFocus=False,
        )

        batch_grid = AgGrid(
            batch_view,
            gridOptions=gb2.build(),
            height=560,
            data_return_mode=DataReturnMode.FILTERED_AND_SORTED,
            update_mode=GridUpdateMode.MODEL_CHANGED | GridUpdateMode.SELECTION_CHANGED,
            allow_unsafe_jscode=True,
            fit_columns_on_grid_load=False,
            theme="streamlit",  # <- dark-mode friendly
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
