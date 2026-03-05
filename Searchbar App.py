import io
import re
import pandas as pd
import streamlit as st
import contextlib

st.set_page_config(page_title="Quick Finder", page_icon="🧀", layout="wide")

# ---- i18n: language toggle + translations -----------------------------------
with st.sidebar:
    lang_de = st.toggle("Deutsch", value=False)

LANG = "de" if lang_de else "en"

T = {
    "title": {
        "en": "🧀 HICKERTZ Nissels Article Search",
        "de": "🧀 HICKERTZ Nissels-Artikel-Suche",
    },
    "caption": {
        "en": "Search your existing Excel/CSV and get just the fields you need.",
        "de": "Durchsuche deine vorhandene Excel/CSV und zeige nur die benötigten Felder an.",
    },
    "data_source": {"en": "Data Source", "de": "Datenquelle"},
    "upload_label": {"en": "Upload your Excel or CSV file", "de": "Excel- oder CSV-Datei hochladen"},
    "choose_sheet": {"en": "Choose Excel sheet", "de": "Excel-Arbeitsblatt auswählen"},
    "loaded_counts": {
        "en": "**Loaded rows:** {rows:,} — **Columns:** {cols}",
        "de": "**Geladene Zeilen:** {rows:,} — **Spalten:** {cols}",
    },
    "search_terms": {"en": "Search terms (use quotes for phrases)", "de": "Suchbegriffe (für Phrasen Anführungszeichen nutzen)"},
    "search_placeholder": {"en": 'e.g., "gouda young" 12345 acme', "de": 'z. B. „gouda jung“ 12345 acme'},
    "columns_to_search": {"en": "Columns to search (default: all)", "de": "Zu durchsuchende Spalten (Standard: alle)"},
    "match_terms_using": {"en": "Match terms using", "de": "Suchlogik"},
    "any_term": {"en": "Any term", "de": "Mindestens ein Begriff"},
    "all_terms": {"en": "All terms", "de": "Alle Begriffe"},
    "starts_with": {"en": "Starts with", "de": "Beginnt mit"},
    "exact_match": {"en": "Exact match", "de": "Exakte Übereinstimmung"},
    "case_sensitive": {"en": "Case sensitive", "de": "Groß-/Kleinschreibung beachten"},
    "output_columns": {"en": "Output columns (add or remove as needed)", "de": "Ausgabespalten (nach Bedarf anpassen)"},
    "output_help": {
        "en": "By default shows Article Number, Description, Main Vendor, and Article Type if found.",
        "de": "Standardmäßig werden Artikelnummer, Beschreibung, Hauptlieferant und Artikeltyp angezeigt (falls vorhanden).",
    },
    "results": {"en": "Results", "de": "Ergebnisse"},
    "results_caption": {"en": "Showing only selected output columns.", "de": "Es werden nur die ausgewählten Ausgabespalten angezeigt."},
    "matches": {"en": "**Matches:** {n:,}", "de": "**Treffer:** {n:,}"},
    "download_btn": {"en": "Download results as CSV", "de": "Ergebnisse als CSV herunterladen"},
    "tips": {"en": "Tips", "de": "Tipps"},
    "tips_md": {
        "en": "- Put phrases in quotes: \"gouda young\"\n- Toggle **Any/All** to require all terms.\n- Use **Starts with** for prefixes (e.g., vendor codes).\n- Use **Exact match** for precise SKU/IDs.\n- Add more columns via **Output columns**.",
        "de": "- Phrasen in Anführungszeichen setzen: „gouda jung“\n- **Mindestens ein/Alle** umschalten, um alle Begriffe zu verlangen.\n- **Beginnt mit** für Präfixe (z. B. Lieferantencodes).\n- **Exakte Übereinstimmung** für genaue SKU/IDs.\n- Weitere Spalten über **Ausgabespalten** hinzufügen.",
    },
    "need_upload": {"en": "Upload a CSV or Excel file to begin.", "de": "Zum Starten CSV- oder Excel-Datei hochladen."},
    "sheet_list_error": {"en": "Could not list Excel sheets: {e}", "de": "Excel-Blätter konnten nicht geladen werden: {e}"},
    "read_error": {"en": "{e}", "de": "{e}"},
    # New UI strings
    "batch_title": {"en": "Batch add for ERP", "de": "Sammelliste für ERP"},
    "batch_caption": {
        "en": "Use ↑/↓ + Enter to add multiple items. Then copy/paste into your ERP.",
        "de": "Mit ↑/↓ + Enter mehrere Einträge hinzufügen. Dann ins ERP kopieren/einfügen.",
    },
    "id_column": {"en": "ID column to copy", "de": "ID-Spalte zum Kopieren"},
    "label_column": {"en": "Label column (for display)", "de": "Label-Spalte (Anzeige)"},
    "add_btn": {"en": "Add selected", "de": "Auswahl hinzufügen"},
    "selected_list": {"en": "Selected list", "de": "Ausgewählte Liste"},
    "copy_format": {"en": "Copy format", "de": "Kopierformat"},
    "ids_only": {"en": "IDs only", "de": "Nur IDs"},
    "labels_only": {"en": "Labels only", "de": "Nur Labels"},
    "tsv": {"en": "ID + Label (TSV)", "de": "ID + Label (TSV)"},
    "copy_box": {"en": "Copy/paste into ERP", "de": "Ins ERP kopieren/einfügen"},
    "clear_list": {"en": "Clear list", "de": "Liste leeren"},
}

def _(key: str, **fmt) -> str:
    """Translate helper with safe English fallback."""
    with contextlib.suppress(Exception):
        txt = T.get(key, {}).get(LANG) or T.get(key, {}).get("en")
        if txt and fmt:
            return txt.format(**fmt)
        return txt or key
    return key
# -----------------------------------------------------------------------------


st.title(_("title"))
st.caption(_("caption"))

# -----------------------------
# Helpers
# -----------------------------
@st.cache_data(show_spinner=False)
def load_file(file_bytes: bytes, filename: str, sheet_name=None):
    """Load CSV or Excel from bytes. Returns a DataFrame."""
    name_lower = (filename or "").lower()
    if name_lower.endswith((".xlsx", ".xls")):
        try:
            target_sheet = 0 if sheet_name in (None, "", "None") else sheet_name
            return pd.read_excel(io.BytesIO(file_bytes), sheet_name=target_sheet, dtype=str)
        except Exception as e:
            raise RuntimeError(f"Failed to read Excel file: {e}")
    else:
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
    return re.sub(r"[^a-z0-9]+", " ", str(col).strip().lower()).strip()

def best_default_output_cols(cols):
    """Pick default output columns based on common names, else first four."""
    wanted = [
        ["article number", "articlenumber", "article no", "artikelnummer", "item number", "sku", "id"],
        ["description", "desc", "item description", "bezeichnung", "artikeltext"],
        ["main vendor", "vendor", "supplier", "lieferant"],
        ["article type", "type", "category", "kategorie", "warengruppe"],
    ]
    norm_index = {normalize_col(c): c for c in cols}
    picked = []
    for aliases in wanted:
        for alias in aliases:
            if alias in norm_index and norm_index[alias] not in picked:
                picked.append(norm_index[alias])
                break
    return picked[:4] if picked else cols[:4]

def guess_best_id_col(cols):
    """Try to pick the best ID column automatically."""
    candidates = [
        ["article number", "artikelnummer", "item number", "sku", "id", "artikel nr", "artikel-nr"],
    ]
    norm_index = {normalize_col(c): c for c in cols}
    for group in candidates:
        for alias in group:
            if alias in norm_index:
                return norm_index[alias]
    return cols[0] if cols else None

def guess_best_label_col(cols):
    """Try to pick best human-friendly label column automatically."""
    candidates = [
        ["description", "bezeichnung", "artikeltext", "desc", "item description", "name"],
    ]
    norm_index = {normalize_col(c): c for c in cols}
    for group in candidates:
        for alias in group:
            if alias in norm_index:
                return norm_index[alias]
    return cols[1] if len(cols) > 1 else (cols[0] if cols else None)

def search_df(df, query, search_cols, mode="any", case=False, startswith=False, exact=False):
    """Search the DataFrame for one or more terms across given columns."""
    if not query:
        return df

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

    mask = pd.Series(True if mode == "all" else False, index=df.index)
    for term in terms:
        col_matches = pd.Series(False, index=df.index)
        for c in search_cols:
            s = df[c].astype(str)
            col_matches = col_matches | make_matcher(s, term)
        if mode == "all":
            mask = mask & col_matches
        else:
            mask = mask | col_matches

    return df[mask]


# -----------------------------
# Sidebar: Data source
# -----------------------------
with st.sidebar:
    st.header(_("data_source"))
    up = st.file_uploader(_("upload_label"), type=["csv", "xlsx", "xls"])
    sheet = None

    if up and up.name.lower().endswith((".xlsx", ".xls")):
        sheet = st.text_input("Excel sheet name (optional)", value="")
        sheet = sheet or None

    if up:
        try:
            df = load_file(up.getvalue(), up.name, sheet_name=sheet)
        except Exception as e:
            st.error(_("sheet_list_error", e=e))
            st.stop()
    else:
        st.info(_("need_upload"))
        st.stop()

all_columns = list(df.columns)
st.write(_("loaded_counts", rows=len(df), cols=len(df.columns)))

# -----------------------------
# Search controls
# -----------------------------
search_query = st.text_input(_("search_terms"), placeholder=_("search_placeholder"))
with st.expander(_("columns_to_search"), expanded=False):
    col_choice = st.multiselect("", options=all_columns, default=all_columns, label_visibility="collapsed")

options = [_("any_term"), _("all_terms")]
mode = st.radio(_("match_terms_using"), options=options, horizontal=True, index=1)
mode_key = "all" if mode == _("all_terms") else "any"

c1, c2, c3 = st.columns(3)
with c1:
    startswith = st.checkbox(_("starts_with"), value=False)
with c2:
    exact = st.checkbox(_("exact_match"), value=False)
with c3:
    case = st.checkbox(_("case_sensitive"), value=False)

# -----------------------------
# Output columns
# -----------------------------
default_out = best_default_output_cols(all_columns)
with st.expander(_("output_columns"), expanded=False):
    out_cols = st.multiselect(
        "", options=all_columns, default=default_out, help=_("output_help"), label_visibility="collapsed"
    )

# -----------------------------
# Do the search
# -----------------------------
res = search_df(df, search_query.strip(), col_choice, mode=mode_key, case=case, startswith=startswith, exact=exact)

out_cols = [c for c in out_cols if c in res.columns]
if not out_cols:
    out_cols = default_out[:]

res_view = res[out_cols].copy()

# Summary + download placed next to title
c_title, c_count, c_dl = st.columns([2, 1, 1])
with c_title:
    st.subheader(_("results"))
with c_count:
    st.write(_("matches", n=len(res_view)))
with c_dl:
    csv = res_view.to_csv(index=False).encode("utf-8")
    st.download_button(_("download_btn"), data=csv, file_name="quick_finder_results.csv", mime="text/csv")

st.caption(_("results_caption"))
st.dataframe(res_view, width="stretch", hide_index=True)

st.write(_("matches", n=len(res_view)))

# =============================================================================
# NEW: Batch add (keyboard navigation + Enter)
# =============================================================================

# session state for batch list
if "batch_selected_ids" not in st.session_state:
    st.session_state.batch_selected_ids = []
if "batch_selected_labels" not in st.session_state:
    st.session_state.batch_selected_labels = []

st.markdown("---")
st.markdown(f"### { _('batch_title') }")
st.caption(_("batch_caption"))

# Choose ID + label columns (defaults try to guess)
default_id_col = guess_best_id_col(out_cols) or (out_cols[0] if out_cols else None)
default_label_col = guess_best_label_col(out_cols) or (out_cols[0] if out_cols else None)

left, right = st.columns([1.15, 0.85], gap="large")

with left:
    # Let user choose which columns define ERP copy & display label
    id_col = st.selectbox(
        _("id_column"),
        options=out_cols if out_cols else all_columns,
        index=(out_cols if out_cols else all_columns).index(default_id_col) if default_id_col in (out_cols if out_cols else all_columns) else 0,
    )

    label_col = st.selectbox(
        _("label_column"),
        options=out_cols if out_cols else all_columns,
        index=(out_cols if out_cols else all_columns).index(default_label_col) if default_label_col in (out_cols if out_cols else all_columns) else 0,
    )

    # Build options from current filtered results (res_view aligns with out_cols)
    # Use res (full) so you can pick columns even if not in out_cols
    if len(res) == 0:
        st.info("No results to add.")
    else:
        # To keep the UI fast, cap the picker options shown
        MAX_PICK = 2000
        pick_df = res[[id_col, label_col]].copy() if (id_col in res.columns and label_col in res.columns) else res[out_cols].copy()

        pick_df[id_col] = pick_df[id_col].astype(str).fillna("")
        pick_df[label_col] = pick_df[label_col].astype(str).fillna("")

        # Drop empty IDs + de-duplicate by ID
        pick_df = pick_df[pick_df[id_col].str.strip() != ""]
        pick_df = pick_df.drop_duplicates(subset=[id_col], keep="first")

        if len(pick_df) > MAX_PICK:
            pick_df = pick_df.head(MAX_PICK)
            st.warning(f"Showing first {MAX_PICK:,} unique IDs for picking (to keep it fast). Narrow your search to reduce results.")

        # Create mapping ID -> label
        id_to_label = dict(zip(pick_df[id_col].tolist(), pick_df[label_col].tolist()))

        # Picker options are IDs; display uses format_func (arrow keys work, typing filters)
        with st.form("batch_add_form", clear_on_submit=False):
            pick_id = st.selectbox(
                "Result picker (↑/↓ then Enter)",
                options=list(id_to_label.keys()),
                format_func=lambda x: f"{x} — {id_to_label.get(x,'')}".strip(" —"),
            )
            add_now = st.form_submit_button(_("add_btn"))

        if add_now and pick_id:
            if pick_id not in st.session_state.batch_selected_ids:
                st.session_state.batch_selected_ids.append(pick_id)
                st.session_state.batch_selected_labels.append(id_to_label.get(pick_id, ""))
                st.success(f"Added: {pick_id} — {id_to_label.get(pick_id,'')}")
            else:
                st.info("Already in list.")

with right:
    st.markdown(f"#### { _('selected_list') }")

    if not st.session_state.batch_selected_ids:
        st.info("Nothing selected yet.")
    else:
        # show list with remove buttons
        for i, (pid, plabel) in enumerate(zip(st.session_state.batch_selected_ids, st.session_state.batch_selected_labels), start=1):
            r1, r2 = st.columns([0.85, 0.15])
            with r1:
                st.write(f"{i}. {pid} — {plabel}".strip(" —"))
            with r2:
                if st.button("✖", key=f"rm_{pid}_{i}"):
                    # remove by index (safe with duplicates, though we prevent duplicates)
                    idx = i - 1
                    st.session_state.batch_selected_ids.pop(idx)
                    st.session_state.batch_selected_labels.pop(idx)
                    st.rerun()

        st.divider()

        fmt = st.radio(
            _("copy_format"),
            options=[_("ids_only"), _("labels_only"), _("tsv")],
            horizontal=True,
            key="batch_copy_fmt",
        )

        ids_only = "\n".join(st.session_state.batch_selected_ids)
        labels_only = "\n".join(st.session_state.batch_selected_labels)
        tsv = "\n".join([f"{a}\t{b}" for a, b in zip(st.session_state.batch_selected_ids, st.session_state.batch_selected_labels)])

        if fmt == _("ids_only"):
            payload = ids_only
        elif fmt == _("labels_only"):
            payload = labels_only
        else:
            payload = tsv

        st.text_area(_("copy_box"), value=payload, height=180)

        if st.button(_("clear_list")):
            st.session_state.batch_selected_ids = []
            st.session_state.batch_selected_labels = []
            st.rerun()

# -----------------------------
# Tips
# -----------------------------
st.markdown("---")
with st.expander(_("tips")):
    st.markdown(_("tips_md"))
