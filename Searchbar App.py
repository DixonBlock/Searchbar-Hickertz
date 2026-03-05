import io
import re
import pandas as pd
import streamlit as st
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, DataReturnMode, JsCode

st.set_page_config(page_title="Quick Finder", page_icon="🧀", layout="wide")

# -----------------------------
# Session state
# -----------------------------
if "batch" not in st.session_state:
    st.session_state.batch = pd.DataFrame()

# -----------------------------
# File loader
# -----------------------------
@st.cache_data(show_spinner=False)
def load_file(file_bytes, filename, sheet=None):

    if filename.lower().endswith(("xlsx","xls")):
        target = 0 if not sheet else sheet
        return pd.read_excel(io.BytesIO(file_bytes), sheet_name=target, dtype=str)

    encodings = ["utf-8","utf-8-sig","cp1252","latin-1"]

    for enc in encodings:
        try:
            df = pd.read_csv(io.BytesIO(file_bytes), encoding=enc, sep=None, engine="python", dtype=str)
            if df.shape[1] > 1:
                return df
        except:
            continue

    raise RuntimeError("Unable to read file")

# -----------------------------
# Search
# -----------------------------
def search_df(df, query, cols):

    if not query:
        return df

    terms = re.findall(r'"([^"]+)"|(\S+)', query)
    terms = [t[0] or t[1] for t in terms]

    mask = pd.Series(False, index=df.index)

    for term in terms:

        matches = pd.Series(False, index=df.index)

        for c in cols:
            matches |= df[c].astype(str).str.contains(term, case=False, na=False)

        mask |= matches

    return df[mask]


# -----------------------------
# UI
# -----------------------------
st.title("🧀 Hickertz Quick Finder")

with st.sidebar:

    st.header("Data Source")

    up = st.file_uploader("Upload CSV or Excel", type=["csv","xlsx","xls"])

    sheet = None

    if up and up.name.endswith(("xlsx","xls")):
        sheet = st.text_input("Excel sheet name")

    if not up:
        st.stop()

    df = load_file(up.getvalue(), up.name, sheet)

df = df.astype(str)

# -----------------------------
# Search controls
# -----------------------------
search_query = st.text_input("Search")

cols = st.multiselect(
    "Columns to search",
    options=df.columns,
    default=df.columns
)

res = search_df(df, search_query, cols)

# -----------------------------
# Layout
# -----------------------------
left, right = st.columns([2,3])

# =============================
# RESULTS GRID
# =============================
with left:

    st.subheader("Results")

    enter_select = JsCode("""
        function(e){
            if(e.event.key === 'Enter'){
                const api = e.api;
                const focused = api.getFocusedCell();
                if(!focused) return;

                const node = api.getDisplayedRowAtIndex(focused.rowIndex);
                node.setSelected(true,true);
                e.event.preventDefault();
            }
        }
    """)

    auto_size = JsCode("""
        function(e){
            const allCols=[];
            e.columnApi.getAllColumns().forEach(col=>allCols.push(col));
            e.columnApi.autoSizeColumns(allCols,false);
        }
    """)

    gb = GridOptionsBuilder.from_dataframe(res)

    gb.configure_default_column(
        resizable=True,
        wrapText=True,
        autoHeight=True,
        minWidth=70
    )

    gb.configure_selection(
        selection_mode="single",
        use_checkbox=False
    )

    gb.configure_grid_options(
        onCellKeyDown=enter_select
    )

    grid = AgGrid(
        res,
        gridOptions=gb.build(),
        height=500,
        data_return_mode=DataReturnMode.FILTERED_AND_SORTED,
        update_mode=GridUpdateMode.SELECTION_CHANGED,
        allow_unsafe_jscode=True,
        fit_columns_on_grid_load=False
    )

    selected = grid["selected_rows"]

    if isinstance(selected, pd.DataFrame):
        sel_df = selected
    else:
        sel_df = pd.DataFrame(selected)

    if not sel_df.empty:

        # allow duplicates
        st.session_state.batch = pd.concat(
            [st.session_state.batch, sel_df],
            ignore_index=True
        )

# =============================
# BATCH GRID
# =============================
with right:

    st.subheader("Batch List")

    batch = st.session_state.batch

    if batch.empty:
        st.info("No items added yet")

    else:

        dup_mask = batch["Art. Nr."].duplicated(keep=False)

        batch_view = batch.copy()
        batch_view["dup"] = dup_mask

        highlight = JsCode("""
            function(params){
                if(params.data.dup === true){
                    return {backgroundColor:'#007672',color:'white'};
                }
                return {};
            }
        """)

        gb2 = GridOptionsBuilder.from_dataframe(batch_view)

        gb2.configure_default_column(
            resizable=True,
            wrapText=True,
            autoHeight=True
        )

        gb2.configure_column("dup", hide=True)

        # drag reorder
        first_col = batch.columns[0]
        gb2.configure_column(first_col, rowDrag=True)

        gb2.configure_selection("multiple", use_checkbox=True)

        gb2.configure_grid_options(
            rowDragManaged=True,
            animateRows=True,
            getRowStyle=highlight
        )

        batch_grid = AgGrid(
            batch_view,
            gridOptions=gb2.build(),
            height=500,
            data_return_mode=DataReturnMode.FILTERED_AND_SORTED,
            update_mode=GridUpdateMode.MODEL_CHANGED | GridUpdateMode.SELECTION_CHANGED,
            allow_unsafe_jscode=True,
            fit_columns_on_grid_load=False
        )

        # reorder persistence
        new_data = batch_grid["data"]

        if isinstance(new_data, pd.DataFrame):

            if "dup" in new_data.columns:
                new_data = new_data.drop(columns=["dup"])

            st.session_state.batch = new_data

        selected_rows = batch_grid["selected_rows"]

        if isinstance(selected_rows, pd.DataFrame):
            del_df = selected_rows
        else:
            del_df = pd.DataFrame(selected_rows)

        c1,c2 = st.columns(2)

        with c1:
            if st.button("Delete Selected"):

                if not del_df.empty:

                    current = st.session_state.batch

                    for _,row in del_df.iterrows():
                        idx = current[(current == row).all(axis=1)].index
                        if len(idx)>0:
                            current = current.drop(idx[0])

                    st.session_state.batch = current.reset_index(drop=True)
                    st.rerun()

        with c2:
            if st.button("Clear Batch"):
                st.session_state.batch = pd.DataFrame()
                st.rerun()

        st.write("Rows:",len(st.session_state.batch))

        csv = st.session_state.batch.to_csv(index=False).encode("utf-8")

        st.download_button(
            "Download CSV for Excel",
            data=csv,
            file_name="batch_export.csv"
        )
