import io
import re
import pandas as pd
import streamlit as st
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, DataReturnMode

st.set_page_config(page_title="Quick Finder", page_icon="🧀", layout="wide")

# -----------------------------
# SESSION STATE
# -----------------------------

if "batch" not in st.session_state:
    st.session_state.batch = pd.DataFrame()

# -----------------------------
# LOAD FILE
# -----------------------------

@st.cache_data(show_spinner=False)
def load_file(file_bytes: bytes, filename: str, sheet_name=None):
    name_lower = (filename or "").lower()

    if name_lower.endswith((".xlsx", ".xls")):
        target_sheet = 0 if not sheet_name else sheet_name
        return pd.read_excel(io.BytesIO(file_bytes), sheet_name=target_sheet, dtype=str)

    encodings = ["utf-8","utf-8-sig","cp1252","latin-1"]

    for enc in encodings:
        try:
            df = pd.read_csv(io.BytesIO(file_bytes), encoding=enc, sep=None, engine="python", dtype=str)
            if df.shape[1] > 1:
                return df
        except:
            continue

    raise RuntimeError("Could not read file.")

# -----------------------------
# SEARCH
# -----------------------------

def search_df(df, query, cols):

    if not query:
        return df

    terms = re.findall(r'"([^"]+)"|(\S+)', query)
    terms = [t[0] or t[1] for t in terms]

    mask = pd.Series(False, index=df.index)

    for term in terms:
        col_matches = pd.Series(False, index=df.index)

        for c in cols:
            col_matches |= df[c].astype(str).str.contains(term, case=False, na=False)

        mask |= col_matches

    return df[mask]


# -----------------------------
# SIDEBAR
# -----------------------------

with st.sidebar:

    st.header("Data Source")

    up = st.file_uploader("Upload CSV or Excel", type=["csv","xlsx","xls"])

    sheet = None

    if up and up.name.endswith(("xlsx","xls")):
        sheet = st.text_input("Excel sheet name (optional)")

    if up:
        df = load_file(up.getvalue(), up.name, sheet)

    else:
        st.stop()

# -----------------------------
# SEARCH UI
# -----------------------------

st.title("🧀 Hickertz Quick Finder")

query = st.text_input("Search")

search_cols = st.multiselect(
    "Columns to search",
    options=df.columns,
    default=df.columns
)

res = search_df(df, query, search_cols)

# -----------------------------
# LAYOUT
# -----------------------------

left, right = st.columns([3,1])

# =============================
# RESULTS GRID
# =============================

with left:

    st.subheader("Results")

    gb = GridOptionsBuilder.from_dataframe(res)

    gb.configure_selection(
        selection_mode="single",
        use_checkbox=False
    )

    gb.configure_grid_options(
        enableCellTextSelection=True
    )

    grid = AgGrid(
        res,
        gridOptions=gb.build(),
        height=400,
        data_return_mode=DataReturnMode.FILTERED_AND_SORTED,
        update_mode=GridUpdateMode.SELECTION_CHANGED,
        allow_unsafe_jscode=True
    )

    selected = grid["selected_rows"]

    if selected:

        row = pd.DataFrame(selected)

        st.session_state.batch = pd.concat(
            [st.session_state.batch, row],
            ignore_index=True
        )

# =============================
# BATCH PANEL
# =============================

with right:

    st.subheader("Batch List")

    batch = st.session_state.batch

    if not batch.empty:

        dupes = batch["Art. Nr."].duplicated(keep=False)

        def highlight(row):
            if dupes[row.name]:
                return ['background-color:#007672;color:white']*len(row)
            return ['']*len(row)

        styled = batch.style.apply(highlight, axis=1)

        st.dataframe(styled, height=400)

        st.write("Items:", len(batch))

        col1, col2 = st.columns(2)

        with col1:

            if st.button("Delete Selected"):

                gb2 = GridOptionsBuilder.from_dataframe(batch)

                gb2.configure_selection("single")

                grid2 = AgGrid(
                    batch,
                    gridOptions=gb2.build(),
                    height=200
                )

                sel = grid2["selected_rows"]

                if sel:

                    idx = batch.index[batch["Art. Nr."] == sel[0]["Art. Nr."]][0]

                    st.session_state.batch = batch.drop(idx)

                    st.experimental_rerun()

        with col2:

            if st.button("Clear"):

                st.session_state.batch = pd.DataFrame()

                st.experimental_rerun()

        csv = batch.to_csv(index=False).encode("utf-8")

        st.download_button(
            "Download Excel CSV",
            data=csv,
            file_name="batch_export.csv"
        )

    else:

        st.info("No items added yet.")
