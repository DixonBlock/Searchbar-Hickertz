import io
import re
import pandas as pd
import streamlit as st

from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, DataReturnMode, JsCode

st.set_page_config(page_title="Quick Finder", page_icon="🧀", layout="wide")

# =============================
# Session state
# =============================
if "batch" not in st.session_state:
    st.session_state.batch = pd.DataFrame()

if "last_added_key" not in st.session_state:
    st.session_state.last_added_key = None

if "focus_results" not in st.session_state:
    st.session_state.focus_results = False

# =============================
# Helpers: load
# =============================
@st.cache_data(show_spinner=False)
def load_file(file_bytes: bytes, filename: str, sheet_name=None):
    name_lower = (filename or "").lower()

    if name_lower.endswith((".xlsx", ".xls")):
        target_sheet = 0 if not sheet_name else sheet_name
        return pd.read_excel(io.BytesIO(file_bytes), sheet_name=target_sheet, dtype=str)

    encodings = ["utf-8", "utf-8-sig", "cp1252", "latin-1"]
    for enc in encodings:
        try:
            df = pd.read_csv(io.BytesIO(file_bytes), encoding=enc, sep=None, engine="python", dtype=str)
            if df.shape[1] > 1:
                return df
        except Exception:
            continue

    raise RuntimeError("Failed to read CSV. Try exporting as UTF-8 or Excel.")

# =============================
# Helpers: search
# =============================
def search_df(df: pd.DataFrame, query: str, search_cols: list[str]) -> pd.DataFrame:
    if not query:
        return df

    terms = re.findall(r'"([^"]+)"|(\S+)', query)
    terms = [t[0] or t[1] for t in terms if (t[0] or t[1])]
    if not terms:
        return df

    mask = pd.Series(False, index=df.index)
    for term in terms:
        col_matches = pd.Series(False, index=df.index)
        for c in search_cols:
            col_matches |= df[c].astype(str).str.contains(re.escape(term), case=False, na=False)
        mask |= col_matches

    return df[mask]

# =============================
# UI
# =============================
st.title("🧀 HICKERTZ Nissels Article Search")
st.caption("Search your existing Excel/CSV and quickly build a batch list on the right.")

# Sidebar: upload
with st.sidebar:
    st.header("Data Source")
    up = st.file_uploader("Upload your Excel or CSV file", type=["csv", "xlsx", "xls"])
    sheet = None

    if up and up.name.lower().endswith((".xlsx", ".xls")):
        sheet = st.text_input("Excel sheet name (optional)", value="").strip() or None

    if not up:
        st.info("Upload a CSV or Excel file to begin.")
        st.stop()

    try:
        df = load_file(up.getvalue(), up.name, sheet_name=sheet)
    except Exception as e:
        st.error(f"Failed to load file: {e}")
        st.stop()

# Make everything strings (safe for search / grid)
df = df.copy()
for c in df.columns:
    df[c] = df[c].astype(str)

all_columns = list(df.columns)

# ===== Search input (Enter should focus the results grid) =====
def _on_search_change():
    st.session_state.focus_results = True

# Give batch panel more room
left, right = st.columns([2, 3], gap="large")

with left:
    st.write(f"**Loaded rows:** {len(df):,} — **Columns:** {len(df.columns)}")

    search_query = st.text_input(
        "Search terms (use quotes for phrases)",
        placeholder='e.g., "gouda young" 12345 acme',
        on_change=_on_search_change,
        key="search_query",
    )

    with st.expander("Columns to search (default: all)", expanded=False):
        col_choice = st.multiselect(
            "",
            options=all_columns,
            default=all_columns,
            label_visibility="collapsed",
        )

    res = search_df(df, (search_query or "").strip(), col_choice)

    st.subheader("Results")
    st.caption("Keyboard flow: Enter in search → table focuses → ↑↓ to row → Enter adds to batch.")

    # =============================
    # Results grid (Enter selects focused row)
    # =============================

    enter_select_js = JsCode(
        """
        function(e) {
          try {
            const key = e.event && e.event.key;
            if (key !== 'Enter') return;

            const api = e.api;
            const focused = api.getFocusedCell();
            if (!focused) return;

            const rowNode = api.getDisplayedRowAtIndex(focused.rowIndex);
            if (rowNode) {
              // select focused row, clear other selection
              rowNode.setSelected(true, true);
              if (e.event.preventDefault) e.event.preventDefault();
              if (e.event.stopPropagation) e.event.stopPropagation();
            }
          } catch(err) {}
        }
        """
    )

    focus_and_autosize_js = JsCode(
        """
        function(e) {
          try {
            // autosize columns to content (so results grid stays compact)
            const allCols = [];
            e.columnApi.getAllColumns().forEach(col => allCols.push(col));
            e.columnApi.autoSizeColumns(allCols, false);

            // focus first cell for arrow navigation
            const api = e.api;
            const firstRow = api.getDisplayedRowAtIndex(0);
            if (firstRow) {
              const firstCol = e.columnApi.getAllColumns()[0].getColId();
              api.setFocusedCell(firstRow.rowIndex, firstCol);
            }
          } catch(err) {}
        }
        """
    )

    gb = GridOptionsBuilder.from_dataframe(res)
    gb.configure_default_column(
        sortable=True,
        filter=True,
        resizable=True,
        wrapText=False,
        autoHeight=False,
        minWidth=60,
    )

    # single select, no checkbox
    gb.configure_selection(selection_mode="single", use_checkbox=False)

    gb.configure_grid_options(
        suppressRowClickSelection=False,
        rowSelection="single",
        ensureDomOrder=True,
        onCellKeyDown=enter_select_js,   # <-- Enter adds
    )

    grid_options = gb.build()

    # If we want focus after search, attach onFirstDataRendered
    if st.session_state.focus_results:
        grid_options["onFirstDataRendered"] = focus_and_autosize_js
    else:
        # still autosize even without focus flag (keeps results compact)
        grid_options["onFirstDataRendered"] = focus_and_autosize_js

    grid = AgGrid(
        res,
        gridOptions=grid_options,
        height=520,
        data_return_mode=DataReturnMode.FILTERED_AND_SORTED,
        update_mode=GridUpdateMode.SELECTION_CHANGED,
        allow_unsafe_jscode=True,
        # IMPORTANT: don't force-fit columns (we autosize instead)
        fit_columns_on_grid_load=False,
        key="results_grid",
    )

    st.session_state.focus_results = False

    selected_rows = grid.get("selected_rows", [])

    # st-aggrid can return list[dict] OR DataFrame depending on versions
    if isinstance(selected_rows, pd.DataFrame):
        has_selection = not selected_rows.empty
        sel_df = selected_rows if has_selection else None
    else:
        has_selection = bool(selected_rows) and len(selected_rows) > 0
        sel_df = pd.DataFrame(selected_rows) if has_selection else None

    # Add selection to batch (only once per selection change)
    if has_selection and sel_df is not None and not sel_df.empty:
        # Stable selection key: prefer Art. Nr.
        if "Art. Nr." in sel_df.columns:
            selection_key = f"ArtNr:{sel_df.loc[0, 'Art. Nr.']}"
        else:
            selection_key = f"Row:{hash(tuple(sel_df.iloc[0].astype(str).tolist()))}"

        if selection_key != st.session_state.last_added_key:
            st.session_state.last_added_key = selection_key

            # Ensure batch has ALL columns
            if st.session_state.batch.empty:
                st.session_state.batch = sel_df.reindex(columns=all_columns).copy()
            else:
                tmp = sel_df.reindex(columns=all_columns).copy()
                st.session_state.batch = pd.concat(
                    [st.session_state.batch, tmp],
                    ignore_index=True
                )

with right:
    st.subheader("Batch List")
    st.caption("Duplicates allowed (highlighted #007672). Drag to reorder. Select rows and delete.")

    batch = st.session_state.batch

    if batch.empty:
        st.info("No items added yet.")
    else:
        # Duplicate highlighting for Art. Nr.
        if "Art. Nr." in batch.columns:
            dup_mask = batch["Art. Nr."].duplicated(keep=False)
        else:
            dup_mask = pd.Series(False, index=batch.index)

        # JS row style for duplicates
        dup_style_js = JsCode(
            """
            function(params) {
              try {
                if (params.data && params.data.__is_dup === true) {
                  return { 'backgroundColor': '#007672', 'color': 'white' };
                }
                return {};
              } catch(e) { return {}; }
            };
            """
        )

        batch_view = batch.copy()
        batch_view["__is_dup"] = dup_mask.values

        gb2 = GridOptionsBuilder.from_dataframe(batch_view)

        # Let batch columns be wider/readable
        gb2.configure_default_column(
            sortable=True,
            filter=True,
            resizable=True,
            minWidth=120,
            wrapText=True,
            autoHeight=False,
        )

        gb2.configure_column("__is_dup", hide=True)

        # Enable drag on first visible column
        first_visible_col = None
        for c in all_columns:
            if c in batch_view.columns:
                first_visible_col = c
                break
        if first_visible_col:
            gb2.configure_column(first_visible_col, rowDrag=True)

        # Selection for deletion
        gb2.configure_selection(selection_mode="multiple", use_checkbox=True)

        gb2.configure_grid_options(
            rowDragManaged=True,
            animateRows=True,
            getRowStyle=dup_style_js,
            suppressHorizontalScroll=False,
        )

        batch_grid = AgGrid(
            batch_view[all_columns + ["__is_dup"]],
            gridOptions=gb2.build(),
            height=520,
            data_return_mode=DataReturnMode.FILTERED_AND_SORTED,
            update_mode=GridUpdateMode.MODEL_CHANGED | GridUpdateMode.SELECTION_CHANGED,
            allow_unsafe_jscode=True,
            # IMPORTANT: do NOT fit-to-grid, so description columns can stay wide
            fit_columns_on_grid_load=False,
            key="batch_grid",
        )

        # Persist reordered data after drag
        new_batch_df = batch_grid.get("data", None)
        if isinstance(new_batch_df, pd.DataFrame) and not new_batch_df.empty:
            if "__is_dup" in new_batch_df.columns:
                new_batch_df = new_batch_df.drop(columns=["__is_dup"])
            st.session_state.batch = new_batch_df.reindex(columns=all_columns).copy()

        # Delete selected rows
        sel_batch = batch_grid.get("selected_rows", [])
        if isinstance(sel_batch, pd.DataFrame):
            sel_batch_df = sel_batch
        else:
            sel_batch_df = pd.DataFrame(sel_batch) if sel_batch else pd.DataFrame()

        c_del, c_clear = st.columns(2)
        with c_del:
            if st.button("Delete selected rows", type="secondary", use_container_width=True):
                if sel_batch_df.empty:
                    st.warning("No rows selected.")
                else:
                    cur = st.session_state.batch.copy()

                    # Remove ONE occurrence per exact row match (duplicates allowed)
                    sigs = []
                    for _, r in sel_batch_df.iterrows():
                        sigs.append(tuple(str(r.get(col, "")) for col in all_columns))

                    keep_rows = []
                    for _, r in cur.iterrows():
                        sig = tuple(str(r.get(col, "")) for col in all_columns)
                        if sig in sigs:
                            sigs.remove(sig)
                        else:
                            keep_rows.append(r)

                    st.session_state.batch = pd.DataFrame(keep_rows, columns=all_columns)
                    st.rerun()

        with c_clear:
            if st.button("Clear batch", type="secondary", use_container_width=True):
                st.session_state.batch = pd.DataFrame()
                st.session_state.last_added_key = None
                st.rerun()

        # Excel-friendly export
        st.markdown("---")
        st.write(f"**Rows in batch:** {len(st.session_state.batch):,}")

        csv_bytes = st.session_state.batch.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Download batch as CSV (Excel)",
            data=csv_bytes,
            file_name="batch_export.csv",
            mime="text/csv",
            use_container_width=True
        )
