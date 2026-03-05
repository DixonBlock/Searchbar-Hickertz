import io
import re
import pandas as pd
import streamlit as st
from pathlib import Path
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, DataReturnMode, JsCode

st.set_page_config(page_title="Quick Finder", page_icon="🧀", layout="wide")

# ---------------------------------------------------
# SESSION STATE
# ---------------------------------------------------

if "batch" not in st.session_state:
    st.session_state.batch = pd.DataFrame()

# ---------------------------------------------------
# LOADERS
# ---------------------------------------------------

@st.cache_data(show_spinner=False)
def load_default():

    from pathlib import Path

    default_path = Path("default_data.csv")

    if not default_path.exists():
        return None

    encodings = ["utf-8", "utf-8-sig", "cp1252", "latin-1"]

    for enc in encodings:
        try:
            df = pd.read_csv(
                default_path,
                encoding=enc,
                sep=None,          # auto-detect delimiter
                engine="python",   # tolerant parser
                dtype=str
            )

            if df.shape[1] > 1:
                return df

        except Exception:
            continue

    raise RuntimeError("Default dataset could not be parsed. Try exporting as CSV UTF-8.")


@st.cache_data(show_spinner=False)
def load_default():

    default_path=Path("default_data.csv")

    if default_path.exists():
        return pd.read_csv(default_path,dtype=str)

    return None


# ---------------------------------------------------
# SEARCH
# ---------------------------------------------------

def search_df(df,query,cols):

    if not query:
        return df

    terms=re.findall(r'"([^"]+)"|(\S+)',query)
    terms=[t[0] or t[1] for t in terms]

    mask=pd.Series(False,index=df.index)

    for term in terms:

        matches=pd.Series(False,index=df.index)

        for c in cols:
            matches|=df[c].astype(str).str.contains(term,case=False,na=False)

        mask|=matches

    return df[mask]


# ---------------------------------------------------
# DATA SOURCE
# ---------------------------------------------------

st.sidebar.header("Data Source")

uploaded=st.sidebar.file_uploader("Upload CSV or Excel",type=["csv","xlsx","xls"])

sheet=None

if uploaded and uploaded.name.endswith(("xlsx","xls")):
    sheet=st.sidebar.text_input("Excel sheet name")

if uploaded:

    df=load_file(uploaded.getvalue(),uploaded.name,sheet)

else:

    df=load_default()

    if df is None:
        st.warning("Upload a file or include default_data.csv")
        st.stop()

df=df.astype(str)

# ---------------------------------------------------
# AUTO DETECT ARTICLE COLUMN
# ---------------------------------------------------

possible_article_cols=[
    "Art. Nr.",
    "Art Nr",
    "Artikelnummer",
    "Article Number",
    "SKU"
]

article_col=None

for col in df.columns:

    if col in possible_article_cols:
        article_col=col
        break

if article_col is None:
    article_col=df.columns[0]


# ---------------------------------------------------
# UI
# ---------------------------------------------------

st.title("🧀 Hickertz Quick Finder")

left,right=st.columns([2,3])

# ---------------------------------------------------
# SEARCH PANEL
# ---------------------------------------------------

with left:

    st.write(f"Rows loaded: {len(df):,}")

    # moved above search input
    cols=st.multiselect(
        "Columns to search",
        options=df.columns,
        default=df.columns
    )

    search_query=st.text_input("Search")

    res=search_df(df,search_query,cols)

    st.subheader("Results")

    enter_select=JsCode("""
    function(e){
        if(e.event.key==='Enter'){
            const api=e.api;
            const focused=api.getFocusedCell();
            if(!focused) return;
            const node=api.getDisplayedRowAtIndex(focused.rowIndex);
            node.setSelected(true,true);
            e.event.preventDefault();
        }
    }
    """)

    autosize=JsCode("""
    function(e){
        const cols=[]
        e.columnApi.getAllColumns().forEach(c=>cols.push(c))
        e.columnApi.autoSizeColumns(cols,false)
    }
    """)

    gb=GridOptionsBuilder.from_dataframe(res)

    gb.configure_default_column(
        resizable=True,
        wrapText=True,
        autoHeight=True
    )

    gb.configure_selection(
        selection_mode="single",
        use_checkbox=False
    )

    gb.configure_grid_options(
        onCellKeyDown=enter_select
    )

    grid=AgGrid(
        res,
        gridOptions=gb.build(),
        height=500,
        data_return_mode=DataReturnMode.FILTERED_AND_SORTED,
        update_mode=GridUpdateMode.SELECTION_CHANGED,
        allow_unsafe_jscode=True,
        fit_columns_on_grid_load=False
    )

    selected=grid["selected_rows"]

    if isinstance(selected,pd.DataFrame):
        sel_df=selected
    else:
        sel_df=pd.DataFrame(selected)

    if not sel_df.empty:

        st.session_state.batch=pd.concat(
            [st.session_state.batch,sel_df],
            ignore_index=True
        )

# ---------------------------------------------------
# BATCH PANEL
# ---------------------------------------------------

with right:

    st.subheader("Batch List")

    batch=st.session_state.batch

    if batch.empty:

        st.info("No items added")

    else:

        if article_col in batch.columns:
            dup_mask=batch[article_col].duplicated(keep=False)
        else:
            dup_mask=pd.Series(False,index=batch.index)

        batch_view=batch.copy()
        batch_view["dup"]=dup_mask

        highlight=JsCode("""
        function(params){
            if(params.data.dup===true){
                return {backgroundColor:'#007672',color:'white'}
            }
            return {}
        }
        """)

        gb2=GridOptionsBuilder.from_dataframe(batch_view)

        gb2.configure_default_column(
            resizable=True,
            wrapText=True,
            autoHeight=True
        )

        gb2.configure_column("dup",hide=True)

        first_col=batch.columns[0]
        gb2.configure_column(first_col,rowDrag=True)

        gb2.configure_selection("multiple",use_checkbox=True)

        gb2.configure_grid_options(
            rowDragManaged=True,
            animateRows=True,
            getRowStyle=highlight
        )

        batch_grid=AgGrid(
            batch_view,
            gridOptions=gb2.build(),
            height=500,
            data_return_mode=DataReturnMode.FILTERED_AND_SORTED,
            update_mode=GridUpdateMode.MODEL_CHANGED | GridUpdateMode.SELECTION_CHANGED,
            allow_unsafe_jscode=True,
            fit_columns_on_grid_load=False
        )

        new_data=batch_grid["data"]

        if isinstance(new_data,pd.DataFrame):

            if "dup" in new_data.columns:
                new_data=new_data.drop(columns=["dup"])

            st.session_state.batch=new_data

        selected=batch_grid["selected_rows"]

        if isinstance(selected,pd.DataFrame):
            del_df=selected
        else:
            del_df=pd.DataFrame(selected)

        c1,c2=st.columns(2)

        with c1:

            if st.button("Delete Selected"):

                if not del_df.empty:

                    cur=st.session_state.batch

                    for _,row in del_df.iterrows():

                        idx=cur[(cur==row).all(axis=1)].index

                        if len(idx)>0:
                            cur=cur.drop(idx[0])

                    st.session_state.batch=cur.reset_index(drop=True)
                    st.rerun()

        with c2:

            if st.button("Clear Batch"):

                st.session_state.batch=pd.DataFrame()
                st.rerun()

        st.write("Rows:",len(st.session_state.batch))

        csv=st.session_state.batch.to_csv(index=False).encode("utf-8")

        st.download_button(
            "Download CSV for Excel",
            data=csv,
            file_name="batch_export.csv"
        )
