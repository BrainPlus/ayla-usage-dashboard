# exporter.py — Excel Export Functions

Builds an in-memory `.xlsx` workbook from the final merged DataFrames and returns raw bytes for Streamlit's `st.download_button`. No file is written to disk.

---

### build_excel_report(user_detail, org_summary, monthly_ratings, region, date_range_30, date_range_90, org_filter_name=None)

**Purpose:** Assembles a five-sheet Excel workbook and returns it as bytes ready for download.

**Parameters:**
- `user_detail` *(DataFrame)* — output of `merger.build_user_detail`; written to the "User Detail" sheet
- `org_summary` *(DataFrame)* — output of `merger.build_org_summary`; written to the "Organisation Summary" sheet
- `monthly_ratings` *(DataFrame)* — output of `database.get_monthly_star_ratings`; written to the "Monthly Ratings" sheet
- `region` *(str)* — `"uk"` or `"eu"`; recorded in the Methodology sheet
- `date_range_30` *(str)* — `"YYYY-MM-DD,YYYY-MM-DD"`; recorded in the Methodology sheet
- `date_range_90` *(str)* — `"YYYY-MM-DD,YYYY-MM-DD"`; recorded in the Methodology sheet
- `org_filter_name` *(str or None, default None)* — when set, an "Organisation filter" row is inserted in the Methodology sheet showing the filtered organisation name

**Returns:** `bytes` — the raw content of the `.xlsx` file.

**Notes:** Uses `pandas.ExcelWriter` with the `openpyxl` engine writing to a `BytesIO` buffer. `buffer.getvalue()` is called after the `with` block closes the writer, which is important because openpyxl does not flush all content until `__exit__` runs. Sheet order is fixed: Organisation Summary → User Detail → Monthly Ratings → Activity Usage → Methodology. All sheets have auto-sized columns via `_autosize_columns`.

---

### build_methodology_df(region, date_range_30, date_range_90, org_filter_name=None)

**Purpose:** Builds a two-column DataFrame describing every metric in the report, used as the Methodology sheet.

**Parameters:**
- `region` *(str)* — inserted as the value for the "Region" row
- `date_range_30` *(str)* — inserted as the value for the "30-day window" row
- `date_range_90` *(str)* — inserted as the value for the "90-day window" row
- `org_filter_name` *(str or None, default None)* — when set, an "Organisation filter" row is inserted after the "Region" row

**Returns:** DataFrame with columns `Field` and `Description`, with one row per metric.

**Notes:** Content is hardcoded. Rows cover: Region, 30-day window, 90-day window, data sources, Logins, Active users, Avg session time, Sessions delivered, Last login date, Groups avg rating, Therapists avg rating, Activities completed.

---

### _autosize_columns(worksheet, df, max_width=50) *(private)*

**Purpose:** Sets each column's width in an openpyxl worksheet to fit its content, capped at a maximum.

**Parameters:**
- `worksheet` — an openpyxl `Worksheet` object (from `writer.sheets[sheet_name]`)
- `df` *(DataFrame)* — the DataFrame written to the sheet; used to measure content lengths
- `max_width` *(int, default 50)* — maximum column width in characters

**Returns:** None (mutates the worksheet in place).

**Notes:** Samples up to the first 1000 rows to keep performance acceptable on large DataFrames. Final width is `min(max(header_length, max_data_length) + 2, max_width)` — the `+2` adds a small padding margin. Column letters are resolved via `worksheet.cell(row=1, column=i).column_letter` rather than importing `openpyxl.utils.get_column_letter`.
