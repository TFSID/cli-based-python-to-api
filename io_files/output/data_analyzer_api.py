from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from typing import Optional
import io
import pandas as pd
import numpy as np
from collections import Counter
from typing import Dict, List, Optional, Tuple, Any, Union
from enum import Enum
import xlsxwriter
import logging
from pathlib import Path

app = FastAPI()

class ChartType(Enum):
    """Tipe bagan yang didukung."""
    PIE = "pie"
    BAR = "bar"
    COLUMN = "column"
    LINE = "line"
    SCATTER = "scatter"
    AREA = "area"

class ChartConfig:
    """Konfigurasi untuk satu bagan."""
    
    def __init__(
        self,
        chart_type: ChartType,
        title: str,
        data: pd.DataFrame,
        x_column: str = None,
        y_column: str = None,
        x_label: str = None,
        y_label: str = None,
        color: str = "#3498DB",
        position: str = "B2",
        scale_x: float = 1.2,
        scale_y: float = 1.2,
        show_legend: bool = True,
        show_data_labels: bool = False,
        sort_data: bool = False,
        sort_ascending: bool = False,
        top_n: int = None
    ):
        self.chart_type = chart_type
        self.title = title
        self.data = data
        # REVIEW: Logika default kolom disederhanakan agar lebih aman jika DataFrame kosong.
        self.x_column = x_column or (data.columns[0] if not data.empty else None)
        self.y_column = y_column or (data.columns[1] if len(data.columns) > 1 else (data.columns[0] if not data.empty else None))
        self.x_label = x_label
        self.y_label = y_label
        self.color = color
        self.position = position
        self.scale_x = scale_x
        self.scale_y = scale_y
        self.show_legend = show_legend
        self.show_data_labels = show_data_labels
        self.sort_data = sort_data
        self.sort_ascending = sort_ascending
        self.top_n = top_n

class DataVisualizer:
    """
    Kelas visualisasi data serbaguna untuk membuat dasbor Excel.
    """
    
    def __init__(self):
        """Inisialisasi visualizer."""
        self.charts: List[ChartConfig] = []
    
    @staticmethod
    def prepare_categorical_data(
        df: pd.DataFrame, column: str, top_n: int = None, min_count: int = 1
    ) -> pd.DataFrame:
        """Mempersiapkan data kategorikal dengan menghitung frekuensi."""
        counts = df[column].astype(str).value_counts()
        counts = counts[counts >= min_count]
        if top_n:
            counts = counts.head(top_n)
        result = counts.reset_index()
        result.columns = ['Category', 'Count']
        return result
    
    @staticmethod
    def prepare_numeric_distribution(
        df: pd.DataFrame, column: str, bins: int = 10, round_to: int = 1
    ) -> pd.DataFrame:
        """Mempersiapkan distribusi data numerik (histogram)."""
        df_col = pd.to_numeric(df[column], errors='coerce').dropna()
        if df_col.empty:
            return pd.DataFrame({'Value': [], 'Count': []})
        if round_to is not None:
            values = df_col.round(round_to).value_counts().sort_index()
            result = values.reset_index()
            result.columns = ['Value', 'Count']
        else:
            values, bin_edges = np.histogram(df_col, bins=bins)
            bin_labels = [f"[{bin_edges[i]:.1f}-{bin_edges[i+1]:.1f}]" for i in range(len(bin_edges)-1)]
            result = pd.DataFrame({'Value': bin_labels, 'Count': values})
        return result
    
    @staticmethod
    def prepare_top_items(
        df: pd.DataFrame, text_column: str, delimiter: str = ',', top_n: int = None
    ) -> pd.DataFrame:
        """Mengekstrak dan menghitung item dari kolom teks yang dipisahkan delimiter."""
        items = []
        for text in df[text_column].dropna():
            if isinstance(text, str):
                items.extend([item.strip() for item in text.split(delimiter) if item.strip()])
        counts = Counter(items)
        top_items = pd.DataFrame(counts.most_common(top_n), columns=['Item', 'Count'])
        return top_items

    @staticmethod
    def prepare_aggregated_data(
        df: pd.DataFrame, group_by: str, agg_column: str, agg_func: str = 'sum', top_n: int = None
    ) -> pd.DataFrame:
        """Mengagregasi data berdasarkan kelompok."""
        if agg_func in ['sum', 'mean', 'median']:
            df[agg_column] = pd.to_numeric(df[agg_column], errors='coerce')
        result = df.groupby(group_by)[agg_column].agg(agg_func).reset_index()
        result.columns = ['Group', 'Value']
        if top_n:
            result = result.head(top_n)
        return result

    def add_chart(self, chart_config: ChartConfig) -> None:
        """Menambahkan konfigurasi bagan ke dasbor."""
        self.charts.append(chart_config)
    
    def _create_chart(
        self, workbook: xlsxwriter.Workbook, config: ChartConfig, data_sheet_name: str, start_row: int
    ) -> xlsxwriter.chart.Chart:
        """Membuat objek bagan xlsxwriter dari konfigurasi."""
        chart_type_str = config.chart_type.value if isinstance(config.chart_type, ChartType) else config.chart_type
        chart = workbook.add_chart({'type': chart_type_str})
        num_rows = len(config.data)

        if num_rows == 0:
            return workbook.add_chart({'type': 'column'})

        cat_range = f"='{data_sheet_name}'!$A${start_row + 2}:$A${start_row + num_rows + 1}"
        val_range = f"='{data_sheet_name}'!$B${start_row + 2}:$B${start_row + num_rows + 1}"
        name_ref = f"='{data_sheet_name}'!$B${start_row + 1}"

        series_config = {'name': name_ref, 'categories': cat_range, 'values': val_range, 'fill': {'color': config.color}}
        
        if chart_type_str == 'pie' and config.show_data_labels:
            series_config['data_labels'] = {'percentage': True, 'leader_lines': True}
            del series_config['fill']
        elif config.show_data_labels:
            series_config['data_labels'] = {'value': True}

        chart.add_series(series_config)
        chart.set_title({'name': config.title})
        if config.x_label: chart.set_x_axis({'name': config.x_label})
        if config.y_label: chart.set_y_axis({'name': config.y_label, 'reverse': (chart_type_str == 'bar')})
        if not config.show_legend: chart.set_legend({'position': 'none'})
        chart.set_style(10)
        return chart
    
    def create_dashboard(
        self, output_path: str, dashboard_name: str, dashboard_title: str = None, summary: str = None
    ) -> bool:
        """Membuat file Excel dengan dasbor berisi semua bagan yang dikonfigurasi."""
        if not self.charts:
            logger.warning("Tidak ada bagan yang dikonfigurasi.")
            return False
        
        try:
            with xlsxwriter.Workbook(output_path) as workbook:
                dashboard_sheet = workbook.add_worksheet(dashboard_name)
                data_sheet = workbook.add_worksheet("Chart_Data_Source")
                data_sheet.hide()

                current_row = 0
                chart_position_index = 0
                
                # REVIEW: Offset baris dibuat lebih dinamis untuk mengakomodasi judul dan ringkasan.
                row_offset = 2
                if dashboard_title:
                    title_format = workbook.add_format({'bold': True, 'font_size': 16, 'align': 'center', 'valign': 'vcenter', 'fg_color': '#2C3E50', 'font_color': 'white'})
                    dashboard_sheet.merge_range('B1:S1', dashboard_title, title_format)
                    row_offset += 1
                
                if summary:
                    summary_format = workbook.add_format({'bold': True, 'font_size': 11, 'text_wrap': True})
                    dashboard_sheet.write_string(f'B{row_offset}', "Ringkasan Analisis AI:", summary_format)
                    dashboard_sheet.write_string(f'B{row_offset+1}', summary, workbook.add_format({'text_wrap': True}))
                    row_offset += 5

                for config in self.charts:
                    # REVIEW: Pengecekan kolom yang diperlukan dilakukan sebelum akses untuk mencegah error.
                    if config.x_column not in config.data.columns or config.y_column not in config.data.columns:
                        logger.warning(f"Melewati bagan '{config.title}' karena kolom yang diperlukan ('{config.x_column}', '{config.y_column}') tidak ada.")
                        continue
                        
                    df_viz_data = config.data[[config.x_column, config.y_column]].copy()
                    if df_viz_data.empty: continue
                    
                    data_sheet.write_row(current_row, 0, df_viz_data.columns, workbook.add_format({'bold': True}))
                    for r, row_data in enumerate(df_viz_data.itertuples(index=False), 1):
                        data_sheet.write_row(current_row + r, 0, row_data)

                    chart = self._create_chart(workbook, config, "Chart_Data_Source", current_row)
                    
                    chart_row = row_offset + (chart_position_index // 2) * 18
                    chart_col = 'B' if chart_position_index % 2 == 0 else 'K'
                    dashboard_sheet.insert_chart(f'{chart_col}{chart_row}', chart, {'x_scale': config.scale_x, 'y_scale': config.scale_y})
                    
                    chart_position_index += 1
                    current_row += len(df_viz_data) + 3
                
                dashboard_sheet.set_column('A:A', 2)
                dashboard_sheet.set_column('B:Z', 12)
            
            logger.result(f"Dasbor '{dashboard_name}' berhasil dibuat: {Path(output_path).name}")
            return True
        except Exception as e:
            logger.error(f"Error FATAL saat membuat dasbor: {e}", exc_info=True)
            return False

    def auto_analyze_dataframe(
        self, df: pd.DataFrame, max_charts: int = 6, max_unique_for_categorical: int = 50
    ) -> List[ChartConfig]:
        """
        Menganalisis DataFrame secara otomatis dan menyarankan konfigurasi bagan (DEPRECATED).
        Hanya berfungsi sebagai fallback jika analisis AI gagal.
        """
        suggestions = []
        for column in df.columns:
            if len(suggestions) >= max_charts: break
            if df[column].isnull().sum() / len(df) > 0.5: continue
            
            if pd.api.types.is_numeric_dtype(df[column]):
                data = self.prepare_numeric_distribution(df, column)
                if not data.empty:
                    suggestions.append(ChartConfig(
                        chart_type=ChartType.COLUMN, title=f"Distribusi: {column}", data=data,
                        x_column='Value', y_column='Count', x_label=column, y_label='Frekuensi'
                    ))
            elif df[column].nunique() <= max_unique_for_categorical:
                data = self.prepare_categorical_data(df, column, top_n=10)
                if not data.empty:
                    chart_type = ChartType.PIE if len(data) <= 5 else ChartType.BAR
                    suggestions.append(ChartConfig(
                        chart_type=chart_type, title=f"Distribusi: {column}", data=data,
                        x_column='Category', y_column='Count', show_data_labels=(chart_type == ChartType.PIE)
                    ))
        logger.info(f"Analisis otomatis (Fallback) menyarankan {len(suggestions)} bagan.")
        return suggestions

class VEMDataVisualizer(DataVisualizer):
    """
    Kelas khusus untuk membuat dasbor Laporan Manajemen Kerentanan & Paparan (VEM).
    """
    def __init__(self, df_input: pd.DataFrame):
        super().__init__()
        self.df = df_input
        self._prepare_charts()

    def _prepare_charts(self):
        """Mempersiapkan semua konfigurasi bagan spesifik untuk dasbor VEM."""
        # BAGAN 1: Distribusi Severity (Pie)
        self.add_chart(ChartConfig(
            chart_type=ChartType.PIE, title='Distribusi Tingkat Keparahan Kerentanan',
            data=self.prepare_categorical_data(self.df, 'Severity'),
            x_column='Category', y_column='Count', show_data_labels=True
        ))
        
        # BAGAN 2: Top 10 Servers (Bar)
        self.add_chart(ChartConfig(
            chart_type=ChartType.BAR, title='10 Server Teratas yang Paling Terpengaruh',
            data=self.prepare_top_items(self.df, 'Affected_Servers', top_n=10),
            x_column='Item', y_column='Count', y_label='Nama Server', x_label='Jumlah Kerentanan',
            color='#E74C3C', show_legend=False, scale_x=1.5, scale_y=1.5, sort_data=True, sort_ascending=True
        ))

        # BAGAN 3: CVSS Distribution (Column)
        self.add_chart(ChartConfig(
            chart_type=ChartType.COLUMN, title='Distribusi Skor CVSS Maksimal',
            data=self.prepare_numeric_distribution(self.df, 'Max_CVSS_Score', round_to=1),
            x_column='Value', y_column='Count', x_label='Skor CVSS (0-10)', y_label='Jumlah CVE',
            color='#3498DB', show_legend=False
        ))

        # BAGAN 4: Top CVEs by Asset Count (Bar)
        df_temp = self.df.copy()
        df_temp['Asset_Count'] = df_temp['Affected_Servers'].apply(lambda x: len([s for s in str(x).split(',') if s.strip()]) if pd.notna(x) else 0)
        top_cve_asset_data = df_temp[['CVE_ID', 'Asset_Count']].sort_values('Asset_Count', ascending=False).head(15)
        self.add_chart(ChartConfig(
            chart_type=ChartType.BAR, title='15 CVE Teratas berdasarkan Jumlah Aset',
            data=top_cve_asset_data, x_column='CVE_ID', y_column='Asset_Count',
            y_label='CVE ID', x_label='Jumlah Aset Terpengaruh', color='#F39C12',
            show_legend=False, scale_x=1.5, scale_y=1.5, sort_data=True, sort_ascending=True
        ))

        # BAGAN 5 & 6 (Ringkasan)
        all_servers_data = self.prepare_top_items(self.df, 'Affected_Servers', top_n=None)
        all_cve_asset_data = df_temp[['CVE_ID', 'Asset_Count']].sort_values('Asset_Count', ascending=False)
        self.add_chart(ChartConfig(
            chart_type=ChartType.BAR, title='Ringkasan Semua Server berdasarkan Jumlah Kerentanan',
            data=all_servers_data, x_column='Item', y_column='Count', y_label='Nama Server', x_label='Jumlah Kerentanan',
            color='#1ABC9C', show_legend=False, scale_x=1.5, scale_y=2.0, sort_data=True, sort_ascending=True
        ))
        self.add_chart(ChartConfig(
            chart_type=ChartType.BAR, title='Ringkasan Semua CVE berdasarkan Jumlah Aset',
            data=all_cve_asset_data, x_column='CVE_ID', y_column='Asset_Count',
            y_label='CVE ID', x_label='Jumlah Aset Terpengaruh', color='#9B59B6',
            show_legend=False, scale_x=1.5, scale_y=2.0, sort_data=True, sort_ascending=True
        ))

    def create_vem_dashboard(self, output_path: str) -> int:
        """Membuat file dasbor VEM Excel."""
        # REVIEW: Menambahkan judul utama ke dasbor VEM untuk konteks yang lebih baik.
        success = self.create_dashboard(output_path, 'Vulnerability_Dashboard', 'Vulnerability & Exposure Management Dashboard')
        return len(self.charts) if success else 0

```python
import pandas as pd
from fastapi import Form, UploadFile, File, HTTPException
from typing import Literal, Optional
import io
import logging

# It's generally good practice to configure logging globally at application startup.
# However, for a self-contained function that takes `log_level` as a parameter,
# configuring a dedicated logger within the function, while preventing duplicate
# handlers, is a pragmatic approach for demonstration purposes.

async def endpoint_name(
    user: str = Form(...),
    password: str = Form(...),
    port: int = Form(8080),
    host: str = Form("localhost"),
    debug: bool = Form(False),
    dry_run: bool = Form(False),
    config_file: str | None = Form(None),
    verbose: int = Form(0),
    log_level: Literal['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] = Form('INFO'),
    timeout: float = Form(30.0),
    file: UploadFile = File(...)
) -> dict:
    
    # Configure logger for this specific endpoint call
    logger = logging.getLogger(__name__)
    
    # Set the logging level dynamically based on the input parameter
    numeric_level = getattr(logging, log_level.upper(), None)
    if not isinstance(numeric_level, int):
        raise HTTPException(status_code=400, detail=f"Invalid log level specified: {log_level}. Must be one of DEBUG, INFO, WARNING, ERROR, CRITICAL.")
    
    # Ensure no duplicate handlers are added if the function is called multiple times
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        # Prevent propagation to the root logger to avoid duplicate messages if a root handler exists
        logger.propagate = False 
        
    logger.setLevel(numeric_level)

    if debug:
        logger.debug(f"Request received: user={user}, host={host}:{port}, debug={debug}, dry_run={dry_run}")
        logger.debug(f"Config: config_file={config_file}, verbose={verbose}, log_level={log_level}, timeout={timeout}")
        logger.debug(f"File details: filename={file.filename}, content_type={file.content_type}, size={file.size} bytes")

    df: Optional[pd.DataFrame] = None
    try:
        # Check if the uploaded file has a filename (basic validation)
        if not file.filename:
            logger.error("No filename provided for the uploaded file.")
            raise HTTPException(status_code=400, detail="No file uploaded or filename is empty.")
            
        # Read the file contents as bytes
        contents = await file.read()
        
        # If the file is truly empty (0 bytes)
        if not contents:
            logger.warning(f"Uploaded file '{file.filename}' is empty.")
            raise HTTPException(status_code=400, detail=f"File '{file.filename}' is empty. Please upload a file with content.")

        # Determine file type based on extension for reading with pandas
        file_extension = file.filename.split('.')[-1].lower()
        
        if file_extension == 'csv':
            # Decode bytes to string for io.StringIO and pandas.read_csv
            sio = io.StringIO(contents.decode('utf-8'))
            df = pd.read_csv(sio)
            logger.info(f"Successfully read CSV file '{file.filename}'. Shape: {df.shape}")
        elif file_extension in ['xls', 'xlsx']:
            # Use io.BytesIO directly for pandas.read_excel
            bio = io.BytesIO(contents)
            df = pd.read_excel(bio)
            logger.info(f"Successfully read Excel file '{file.filename}'. Shape: {df.shape}")
        else:
            logger.error(f"Unsupported file type '{file_extension}' for file '{file.filename}'.")
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type: {file_extension}. Please upload a CSV or Excel file."
            )

        # Check if DataFrame is empty after parsing (e.g., CSV with only headers, or corrupted data)
        if df.empty:
            logger.warning(f"Uploaded file '{file.filename}' resulted in an empty DataFrame after parsing.")
            # An empty DataFrame likely means no meaningful data for chart generation, so raise an error.
            raise HTTPException(status_code=422, detail=f"The uploaded file '{file.filename}' contains no valid data after parsing, resulting in an empty dataset.")

    except UnicodeDecodeError as e:
        logger.error(f"UnicodeDecodeError while reading file '{file.filename}': {e}", exc_info=True)
        raise HTTPException(status_code=422, detail=f"Could not decode file content. Please ensure '{file.filename}' is a valid UTF-8 CSV file: {e}")
    except pd.errors.EmptyDataError as e:
        logger.error(f"Pandas EmptyDataError while reading file '{file.filename}': {e}", exc_info=True)
        raise HTTPException(status_code=422, detail=f"The uploaded file '{file.filename}' is empty or contains no parsable data: {e}")
    except pd.errors.ParserError as e:
        logger.error(f"Pandas ParserError while reading file '{file.filename}': {e}", exc_info=True)
        raise HTTPException(status_code=422, detail=f"Could not parse file content from '{file.filename}'. Please check the file format and integrity: {e}")
    except Exception as e:
        logger.critical(f"An unexpected critical error occurred during file processing for '{file.filename}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An unexpected internal server error occurred while processing the file: {e}")

    # --- Simulate the _prepare_charts() logic ---
    # The original __init__ called self._prepare_charts().
    # In this refactored endpoint, we'll simulate this step.
    # If dry_run is true, we skip the actual "chart preparation".
    
    chart_preparation_details = {}
    if dry_run:
        logger.info("Dry run enabled. Skipping actual chart preparation logic.")
        chart_preparation_details = {
            "status": "Dry run: Chart preparation skipped.",
            "message": "Data was successfully parsed but chart generation was not performed due to dry_run mode."
        }
    else:
        logger.info(f"Initiating chart preparation for data from '{file.filename}'...")
        # This is where the core business logic from _prepare_charts() would be implemented.
        # Example: Call another function, a service, or an instance method.
        # e.g., chart_output = YourChartService.generate_charts(df, config_file=config_file, verbose=verbose)
        
        # For this exercise, we return some placeholder information.
        chart_preparation_details = {
            "status": "Charts preparation initiated.",
            "message": "Data has been processed and chart generation is underway or ready.",
            "rows_processed": len(df),
            "columns_processed": len(df.columns),
            "first_n_rows_preview": df.head(5).to_dict(orient='records'), # Provide a preview
            # In a real scenario, this might include URLs to generated charts, a job ID, etc.
            "chart_links": [], 
            "generation_config_used": {
                "config_file": config_file,
                "verbose_level": verbose
            }
        }
        logger.info("Chart preparation simulation complete.")

    # Return the results as a Python dictionary
    return {
        "status": "success",
        "message": f"File '{file.filename}' processed successfully.",
        "request_metadata": {
            "user": user,
            "host": host,
            "port": port,
            "debug_mode": debug,
            "dry_run_mode": dry_run,
            "log_level_set": log_level,
            "timeout_seconds": timeout
        },
        "file_uploaded_details": {
            "filename": file.filename,
            "content_type": file.content_type,
            "size_bytes": file.size
        },
        "data_summary": {
            "rows": len(df),
            "columns": len(df.columns),
            "is_empty_after_parse": df.empty,
            "column_names": df.columns.tolist()
        },
        "chart_preparation_output": chart_preparation_details
    }
```

```python
import pandas as pd
import io
from fastapi import Form, File, UploadFile, HTTPException
from typing import Literal, Optional

async def endpoint_name(
    user: str = Form(...),
    password: str = Form(...),
    port: int = Form(8080),
    host: str = Form("localhost"),
    debug: bool = Form(False),
    dry_run: bool = Form(False),
    config_file: str | None = Form(None),
    verbose: int = Form(0),
    log_level: Literal['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] = Form('INFO'),
    timeout: float = Form(30.0),
    file: UploadFile = File(...),
    column: str = Form(..., description="Nama kolom kategorikal untuk diproses."),
    top_n: Optional[int] = Form(None, ge=1, description="Jumlah kategori teratas yang akan dipertahankan. Jika None, semua kategori dipertahankan."),
    min_count: int = Form(1, ge=1, description="Jumlah minimum kemunculan kategori agar disertakan."),
) -> dict:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Tidak ada file yang diunggah.")

    try:
        contents = await file.read()
        file_like_object = io.BytesIO(contents)

        try:
            # Assume CSV for tabular data. Add more handlers for other formats if needed.
            df = pd.read_csv(file_like_object)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Gagal membaca file sebagai CSV: {e}. Pastikan file adalah CSV yang valid.")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Terjadi kesalahan saat memproses file: {e}")

    if column not in df.columns:
        raise HTTPException(status_code=400, detail=f"Kolom '{column}' tidak ditemukan dalam data yang diunggah. Kolom yang tersedia: {list(df.columns)}")

    try:
        counts = df[column].astype(str).value_counts()
        counts = counts[counts >= min_count]
        if top_n is not None:
            counts = counts.head(top_n)
        result_df = counts.reset_index()
        result_df.columns = ['Category', 'Count']
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Terjadi kesalahan saat menerapkan logika bisnis pada kolom '{column}': {e}")

    return result_df.to_dict(orient='records')
```

```python
from fastapi import Form, UploadFile, File, HTTPException
import pandas as pd
import numpy as np
import io
from typing import Literal, Optional

async def endpoint_name(
    user: str = Form(...),
    password: str = Form(...),
    port: int = Form(8080),
    host: str = Form("localhost"),
    debug: bool = Form(False),
    dry_run: bool = Form(False),
    config_file: str | None = Form(None),
    verbose: int = Form(0),
    log_level: Literal['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] = Form('INFO'),
    timeout: float = Form(30.0),
    column: str = Form(...),
    bins: int = Form(10),
    round_to: Optional[int] = Form(1),
    file: UploadFile = File(...)
) -> dict:
    contents = await file.read()

    df: pd.DataFrame
    try:
        if file.filename and (file.filename.endswith('.csv') or file.filename.endswith('.txt')):
            df = pd.read_csv(io.StringIO(contents.decode('utf-8')))
        elif file.filename and (file.filename.endswith('.xlsx') or file.filename.endswith('.xls')):
            df = pd.read_excel(io.BytesIO(contents))
        else:
            raise HTTPException(
                status_code=400,
                detail="Unsupported file type. Please upload a CSV, TXT, XLS, or XLSX file."
            )
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=400,
            detail="Could not decode file contents. Ensure it's a valid UTF-8 CSV/TXT file."
        )
    except pd.errors.EmptyDataError:
        raise HTTPException(
            status_code=400,
            detail="Uploaded file is empty or contains no data."
        )
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Error reading file: {e}"
        )

    if column not in df.columns:
        raise HTTPException(
            status_code=400,
            detail=f"Column '{column}' not found in the uploaded data. Available columns: {list(df.columns)}"
        )

    df_col = pd.to_numeric(df[column], errors='coerce').dropna()

    if df_col.empty:
        raise HTTPException(
            status_code=400,
            detail=f"Column '{column}' contains no numeric data after cleaning (e.g., all values are non-numeric or NaN)."
        )

    result_df: pd.DataFrame
    if round_to is not None:
        values = df_col.round(round_to).value_counts().sort_index()
        result_df = values.reset_index()
        result_df.columns = ['Value', 'Count']
    else:
        if not isinstance(bins, int) or bins <= 0:
            raise HTTPException(
                status_code=400,
                detail="Parameter 'bins' must be a positive integer when 'round_to' is not specified."
            )
        try:
            values, bin_edges = np.histogram(df_col, bins=bins)
            bin_labels = [f"[{bin_edges[i]:.2f}-{bin_edges[i+1]:.2f}]" for i in range(len(bin_edges)-1)]
            result_df = pd.DataFrame({'Value': bin_labels, 'Count': values})
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Error creating histogram: {e}. Check 'bins' parameter and data range."
            )

    return {"distribution": result_df.to_dict(orient='records')}
```

```python
import pandas as pd
from collections import Counter
import io
from typing import Literal
from fastapi import Form, File, UploadFile, HTTPException, status

async def endpoint_name(
    user: str = Form(...),
    password: str = Form(...),
    port: int = Form(8080),
    host: str = Form("localhost"),
    debug: bool = Form(False),
    dry_run: bool = Form(False),
    config_file: str | None = Form(None),
    verbose: int = Form(0),
    log_level: Literal['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] = Form('INFO'),
    timeout: float = Form(30.0),
    file: UploadFile = File(...),
    text_column: str = Form(...),
    delimiter: str = Form(','),
    top_n: int | None = Form(None)
) -> dict:
    if not file:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No file uploaded."
        )

    try:
        contents = await file.read()
        if not contents:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file is empty."
            )
        
        # Attempt to decode as UTF-8; adjust if other encodings are expected
        s_io = io.StringIO(contents.decode('utf-8'))
        df = pd.read_csv(s_io)
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not decode file contents with UTF-8. Please ensure it's a valid text file."
        )
    except pd.errors.EmptyDataError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File is empty or contains no data."
        )
    except pd.errors.ParserError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not parse file as CSV. Check file format and delimiter."
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing uploaded file: {e}"
        )

    if text_column not in df.columns:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Text column '{text_column}' not found in the uploaded data. Available columns: {list(df.columns)}"
        )

    items = []
    for text in df[text_column].dropna():
        if isinstance(text, str):
            items.extend([item.strip() for item in text.split(delimiter) if item.strip()])
    
    if not items:
        return {
            "message": "No processable items found in the specified text column.",
            "top_items": [],
            "metadata": {
                "uploaded_filename": file.filename,
                "text_column_used": text_column,
                "delimiter_used": delimiter,
                "top_n_requested": top_n,
                "total_unique_items": 0
            }
        }

    counts = Counter(items)
    top_items_df = pd.DataFrame(counts.most_common(top_n), columns=['Item', 'Count'])

    return {
        "message": "Top items successfully extracted and counted.",
        "top_items": top_items_df.to_dict(orient='records'),
        "metadata": {
            "uploaded_filename": file.filename,
            "text_column_used": text_column,
            "delimiter_used": delimiter,
            "top_n_requested": top_n,
            "total_unique_items": len(counts)
        }
    }
```

```python
import pandas as pd
from fastapi import Form, File, UploadFile, HTTPException
from typing import Literal, Optional
import io

async def endpoint_name(
    user: str = Form(...),
    password: str = Form(...),
    port: int = Form(8080),
    host: str = Form("localhost"),
    debug: bool = Form(False),
    dry_run: bool = Form(False),
    config_file: str | None = Form(None),
    verbose: int = Form(0),
    log_level: Literal['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] = Form('INFO'),
    timeout: float = Form(30.0),
    file: UploadFile = File(...),
    # Tambahan parameter untuk logika agregasi
    group_by: str = Form(...),
    agg_column: str = Form(...),
    agg_func: Literal['sum', 'mean', 'median', 'min', 'max', 'count'] = Form('sum'),
    top_n: int | None = Form(None)
) -> dict:
    """
    Endpoint untuk mengunggah file CSV dan melakukan agregasi data.
    """
    # 1. Membaca data dari file.read() (bytes)
    try:
        contents = await file.read()
        # Asumsi file adalah CSV dan dapat didekode sebagai UTF-8
        s_io = io.StringIO(contents.decode('utf-8'))
        df = pd.read_csv(s_io)
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Gagal mendekode konten file sebagai UTF-8. Pastikan file adalah file teks (misalnya, CSV) yang valid.")
    except pd.errors.EmptyDataError:
        raise HTTPException(status_code=400, detail="File yang diunggah kosong atau tidak berisi data.")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Terjadi kesalahan saat membaca atau mengurai file: {e}")

    # Validasi keberadaan kolom
    if group_by not in df.columns:
        raise HTTPException(status_code=400, detail=f"Kolom 'group_by' ('{group_by}') tidak ditemukan dalam data yang diunggah.")
    if agg_column not in df.columns:
        raise HTTPException(status_code=400, detail=f"Kolom 'agg_column' ('{agg_column}') tidak ditemukan dalam data yang diunggah.")

    # 2. Mengimplementasikan logika bisnis inti (prepare_aggregated_data)
    # Konversi kolom agregasi ke numerik jika fungsi agregasi memerlukannya
    if agg_func in ['sum', 'mean', 'median']:
        df[agg_column] = pd.to_numeric(df[agg_column], errors='coerce')
        # Jika semua nilai di kolom agregasi menjadi NaN, mungkin tidak ada data numerik
        if df[agg_column].isnull().all():
             raise HTTPException(status_code=400, detail=f"Kolom agregasi '{agg_column}' hanya berisi nilai non-numerik setelah konversi. Tidak dapat melakukan operasi '{agg_func}'.")

    try:
        # Melakukan agregasi
        result_df = df.groupby(group_by)[agg_column].agg(agg_func).reset_index()
        result_df.columns = ['Group', 'Value'] # Mengganti nama kolom sesuai logika asli

        # Menerapkan top_n jika ada
        if top_n is not None and top_n > 0:
            result_df = result_df.head(top_n)

    except KeyError as e:
        raise HTTPException(status_code=400, detail=f"Kesalahan kolom selama agregasi: {e}. Pastikan kolom '{group_by}' dan '{agg_column}' ada.")
    except Exception as e:
        # Menangkap error pandas lainnya selama agregasi
        raise HTTPException(status_code=500, detail=f"Terjadi kesalahan selama agregasi data: {e}")

    # 3. Mengembalikan hasil sebagai dictionary Python
    # Mengonversi DataFrame ke list of dictionaries (orient='records' adalah format umum untuk API)
    return {"status": "success", "data": result_df.to_dict(orient='records')}
```

```python
import json
from typing import Literal, Optional, List
from fastapi import Form, UploadFile, File, HTTPException
from pydantic import BaseModel, ValidationError

# --- Asumsi: Definisi ChartConfig dan penyimpanan charts_storage tersedia di scope global/modul ---
# Dalam aplikasi nyata, ChartConfig akan menjadi model Pydantic yang terdefinisi dengan baik,
# dan charts_storage akan digantikan dengan interaksi database atau manajemen state yang lebih canggih.

# Contoh sederhana ChartConfig untuk tujuan demonstrasi:
class ChartConfig(BaseModel):
    id: str
    title: str
    data_source: str
    chart_type: Literal['bar', 'line', 'pie', 'scatter']
    description: Optional[str] = None

# Penyimpanan dalam memori (untuk simulasi self.charts)
charts_storage: List[ChartConfig] = []
# --- Akhir asumsi ---

async def endpoint_name(user: str = Form(...), password: str = Form(...), port: int = Form(8080), host: str = Form("localhost"), debug: bool = Form(False), dry_run: bool = Form(False), config_file: str | None = Form(None), verbose: int = Form(0), log_level: Literal['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] = Form('INFO'), timeout: float = Form(30.0), file: UploadFile = File(...)) -> dict:
    """
    Memproses file konfigurasi bagan yang diunggah, memvalidasinya, dan menambahkannya ke penyimpanan.
    """
    try:
        # 1. Membaca data dari file.read() (bytes)
        content = await file.read()

        if not content:
            raise HTTPException(status_code=400, detail="File yang diunggah kosong.")

        # Dekode konten dan parse sebagai JSON
        # Mengasumsikan file berisi data JSON yang merepresentasikan ChartConfig
        try:
            chart_data = json.loads(content.decode('utf-8'))
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=400, detail=f"Format JSON tidak valid dalam file: {e}")
        except UnicodeDecodeError:
            raise HTTPException(status_code=400, detail="Tidak dapat mendekode konten file sebagai UTF-8. Pastikan ini adalah teks yang valid.")

        # Validasi dan parse data ke dalam model Pydantic ChartConfig
        try:
            chart_config = ChartConfig(**chart_data)
        except ValidationError as e:
            raise HTTPException(status_code=422, detail=f"Data ChartConfig tidak valid: {e.errors()}")

        # 2. Implementasi logika bisnis inti (add_chart)
        # Logika asli: self.charts.append(chart_config)
        # Kami mensimulasikan ini dengan menambahkan ke daftar global/tingkat modul bernama charts_storage.
        # Parameter 'dry_run' dapat digunakan untuk mencegah modifikasi sebenarnya.
        if dry_run:
            return {
                "status": "success",
                "message": "Konfigurasi bagan divalidasi berhasil (dry run). Tidak ada perubahan yang dilakukan.",
                "chart_id": chart_config.id,
                "chart_config": chart_config.dict() # Mengembalikan konfigurasi yang diparse untuk konfirmasi
            }

        # Mensimulasikan penambahan konfigurasi bagan ke penyimpanan
        # Dalam aplikasi nyata, ini akan melibatkan penyisipan ke database,
        # berinteraksi dengan layer layanan, dll.
        charts_storage.append(chart_config)

        # 3. Mengembalikan (return) hasil sebagai dictionary Python
        return {
            "status": "success",
            "message": f"Bagan '{chart_config.title}' (ID: {chart_config.id}) berhasil ditambahkan.",
            "chart_id": chart_config.id,
            "chart_config": chart_config.dict() # Sertakan konfigurasi yang ditambahkan dalam respons
        }

    except HTTPException:
        # Mengangkat kembali HTTPException yang sudah dibuat
        raise
    except Exception as e:
        # 4. Mengganti print ke stderr atau sys.exit dengan raise HTTPException dari FastAPI
        # Menangkap error tak terduga lainnya dan mengembalikan 500 generik
        raise HTTPException(status_code=500, detail=f"Terjadi kesalahan tak terduga: {str(e)}")
```

```python
import io
import json
import base64
import pandas as pd
import xlsxwriter
from fastapi import Form, UploadFile, File, HTTPException
from typing import Literal, Optional
from pydantic import BaseModel
from enum import Enum

async def endpoint_name(
    user: str = Form(...),
    password: str = Form(...),
    port: int = Form(8080),
    host: str = Form("localhost"),
    debug: bool = Form(False),
    dry_run: bool = Form(False),
    config_file: str | None = Form(None),
    verbose: int = Form(0),
    log_level: Literal['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] = Form('INFO'),
    timeout: float = Form(30.0),
    file: UploadFile = File(...)
) -> dict:
    # Define ChartType and ChartConfig as they are integral to the chart logic
    class ChartType(str, Enum):
        COLUMN = 'column'
        BAR = 'bar'
        LINE = 'line'
        PIE = 'pie'
        AREA = 'area'

    class ChartConfig(BaseModel):
        chart_type: ChartType = ChartType.COLUMN
        title: str = "Generated Chart"
        x_label: str | None = None
        y_label: str | None = None
        color: str = "#5B9BD5" # Default blue
        show_data_labels: bool = False
        show_legend: bool = True

    # 1. Parse ChartConfig from config_file (JSON string) or use defaults
    chart_config = ChartConfig() # Default config
    if config_file:
        try:
            config_data = json.loads(config_file)
            chart_config = ChartConfig(**config_data)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON format for config_file. Must be a valid JSON string.")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Error parsing config_file: {e}")

    # 2. Read and parse data from UploadFile
    try:
        contents = await file.read()
        if not contents:
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")

        # Attempt to decode as UTF-8. If it fails, could be binary or other encoding.
        try:
            data_string = contents.decode('utf-8')
        except UnicodeDecodeError:
            raise HTTPException(status_code=400, detail="Could not decode file content as UTF-8. Please ensure it's a valid text file (e.g., CSV, TSV).")

        data_io = io.StringIO(data_string)
        
        # Use pandas to infer format (CSV, TSV, etc.). pd.read_csv is robust.
        df = pd.read_csv(data_io) 

        if df.empty:
            raise HTTPException(status_code=400, detail="Input file contains no data rows after headers.")
        if df.shape[1] < 2:
            raise HTTPException(status_code=400, detail="Input file must have at least two columns: categories and values.")

        # Assume first column for categories, second for values
        categories = df.iloc[:, 0].tolist()
        values = df.iloc[:, 1].tolist()

        num_rows = len(categories)
        if num_rows == 0:
             raise HTTPException(status_code=400, detail="No valid data found for charting after parsing.")

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error reading or parsing input file: {e}. Ensure file is a valid CSV/TSV format.")

    # 3. Create an in-memory Excel workbook
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {'in_memory': True})
    data_sheet_name = "ChartData"
    worksheet = workbook.add_worksheet(data_sheet_name)

    # 4. Write data to the worksheet
    # Headers are at row 0, data starts at row 1.
    category_header = df.columns[0] if not str(df.columns[0]).isdigit() else "Category" # Use actual column name or default
    value_header = df.columns[1] if not str(df.columns[1]).isdigit() else (chart_config.title or "Value") # Use actual column name or chart title/default

    worksheet.write(0, 0, category_header)
    worksheet.write(0, 1, value_header)

    for i, (cat, val) in enumerate(zip(categories, values)):
        worksheet.write(i + 1, 0, cat)
        worksheet.write(i + 1, 1, val)

    # 5. Adapt the _create_chart logic to create and configure the chart
    chart_type_str = chart_config.chart_type.value
    chart = workbook.add_chart({'type': chart_type_str})

    # Xlsxwriter ranges are 1-indexed.
    # Data starts from row 1 (after headers at row 0).
    # Categories: A2 to A(num_rows+1)
    # Values: B2 to B(num_rows+1)
    # Series Name: B1 (header of value column)
    cat_range = f"='{data_sheet_name}'!$A$2:$A${num_rows + 1}"
    val_range = f"='{data_sheet_name}'!$B$2:$B${num_rows + 1}"
    name_ref = f"='{data_sheet_name}'!$B$1"

    series_config = {'name': name_ref, 'categories': cat_range, 'values': val_range}
    
    if chart_config.color:
        series_config['fill'] = {'color': chart_config.color}

    if chart_type_str == 'pie' and chart_config.show_data_labels:
        series_config['data_labels'] = {'percentage': True, 'leader_lines': True}
        if 'fill' in series_config: # Pie charts often don't use series fill color
            del series_config['fill']
    elif chart_config.show_data_labels:
        series_config['data_labels'] = {'value': True}

    chart.add_series(series_config)
    chart.set_title({'name': chart_config.title})
    if chart_config.x_label: chart.set_x_axis({'name': chart_config.x_label})
    if chart_config.y_label: chart.set_y_axis({'name': chart_config.y_label, 'reverse': (chart_type_str == 'bar')})
    if not chart_config.show_legend: chart.set_legend({'position': 'none'})
    chart.set_style(10)

    # 6. Insert the chart into the worksheet
    worksheet.insert_chart('D2', chart) # Insert chart at cell D2

    # 7. Close the workbook and retrieve bytes
    try:
        workbook.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error closing workbook: {e}")

    output.seek(0)
    excel_bytes = output.getvalue()

    # 8. Return the bytes as a base64 encoded string in a dictionary
    encoded_excel = base64.b64encode(excel_bytes).decode('utf-8')

    return {
        "message": "Chart generated successfully",
        "file_name": "generated_chart.xlsx",
        "file_content_b64": encoded_excel,
        "user": user,
        "debug_mode": debug,
        "log_level": log_level,
        "dry_run": dry_run,
        "port": port,
        "host": host,
        "timeout": timeout
    }
```

```python
import pandas as pd
import xlsxwriter
from fastapi import Form, File, UploadFile, HTTPException
from typing import Literal, Dict, Any, List, Optional
from io import BytesIO
import logging

# Configure a basic logger for demonstration purposes
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Custom logger class to support a 'result' method as seen in the original code
class CustomLogger(logging.Logger):
    def result(self, message, *args, **kwargs):
        self.info(f"[RESULT] {message}", *args, **kwargs)

logging.setLoggerClass(CustomLogger)
logger = logging.getLogger(__name__)

# --- Helper classes and functions (simulating the context of the original `self` object) ---

class ChartConfig:
    """A minimal class to hold chart configuration data."""
    def __init__(self, data: pd.DataFrame, x_column: str, y_column: str, title: str, scale_x: float = 1.0, scale_y: float = 1.0):
        self.data = data
        self.x_column = x_column
        self.y_column = y_column
        self.title = title
        self.scale_x = scale_x
        self.scale_y = scale_y

def _create_chart_helper(workbook: xlsxwriter.Workbook, config: ChartConfig, data_sheet_name: str, current_row_start_index: int) -> xlsxwriter.chart.Chart:
    """
    Helper function to create an xlsxwriter chart based on ChartConfig.
    This simulates the `_create_chart` method from the original class.
    """
    chart = workbook.add_chart({'type': 'column'}) # Default to column chart

    num_data_rows = len(config.data)
    
    # Get 0-based column indices for x and y data
    try:
        x_col_idx = config.data.columns.get_loc(config.x_column)
        y_col_idx = config.data.columns.get_loc(config.y_column)
    except KeyError as e:
        logger.error(f"Kolom yang diperlukan tidak ditemukan untuk bagan '{config.title}': {e}")
        raise ValueError(f"Kolom yang diperlukan tidak ditemukan untuk bagan: {e}")

    # xlsxwriter formulas use 1-based indexing for rows and columns.
    # `current_row_start_index` is the 0-based row where the header is written.
    # Data starts at `current_row_start_index + 1` in the `data_sheet`.
    data_start_row_excel_idx = current_row_start_index + 2 # Header (1) + first data row (1) = 2
    data_end_row_excel_idx = current_row_start_index + 1 + num_data_rows # Header row (1) + total data rows

    # Add a series to the chart
    chart.add_series({
        'name':       f"='{data_sheet_name}'!${xlsxwriter.utility.xl_col_to_name(y_col_idx)}${current_row_start_index + 1}", # Header of Y column
        'categories': f"='{data_sheet_name}'!${xlsxwriter.utility.xl_col_to_name(x_col_idx)}${data_start_row_excel_idx}:${xlsxwriter.utility.xl_col_to_name(x_col_idx)}${data_end_row_excel_idx}",
        'values':     f"='{data_sheet_name}'!${xlsxwriter.utility.xl_col_to_name(y_col_idx)}${data_start_row_excel_idx}:${xlsxwriter.utility.xl_col_to_name(y_col_idx)}${data_end_row_excel_idx}",
        'fill':       {'color': '#C6EFCE'},
        'border':     {'color': '#006100'},
    })

    chart.set_title({'name': config.title})
    chart.set_x_axis({'name': config.x_column})
    chart.set_y_axis({'name': config.y_column})
    chart.set_legend({'position': 'none'})
    
    return chart

# --- Refactored Endpoint Function ---

async def endpoint_name(
    user: str = Form(...),
    password: str = Form(...),
    port: int = Form(8080),
    host: str = Form("localhost"),
    debug: bool = Form(False),
    dry_run: bool = Form(False),
    config_file: str | None = Form(None), # This parameter is part of the signature but not used by the core logic provided.
    verbose: int = Form(0),
    log_level: Literal['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] = Form('INFO'),
    timeout: float = Form(30.0),
    file: UploadFile = File(...),
    # Parameters from the original create_dashboard function, now part of the endpoint
    dashboard_name: str = Form("AI Dashboard"),
    dashboard_title: Optional[str] = Form(None),
    summary: Optional[str] = Form(None),
) -> Dict[str, Any]:
    """
    Menerima file data dan parameter untuk membuat dasbor Excel dengan bagan.
    Mengembalikan status dan detail hasil dalam format dictionary.
    """
    
    # Konfigurasi logger berdasarkan input parameter
    logger.setLevel(log_level)
    if debug:
        logger.setLevel(logging.DEBUG)
    if verbose > 0:
        # Atur level log lebih tinggi untuk verbose
        logger.setLevel(logging.DEBUG if verbose > 1 else logging.INFO)

    if dry_run:
        logger.info("Permintaan dry run. Tidak ada dasbor yang akan dihasilkan.")
        return {"status": "dry_run_success", "message": "Dry run selesai dengan sukses, tidak ada dasbor yang dihasilkan."}

    # 1. Membaca data dari file yang diunggah (`file.read()`)
    file_content = await file.read()
    if not file_content:
        raise HTTPException(status_code=400, detail="File yang diunggah kosong.")

    df_raw: pd.DataFrame
    try:
        # Tentukan tipe file berdasarkan ekstensi dan baca menggunakan pandas
        file_extension = file.filename.split('.')[-1].lower() if file.filename else ''
        data_io = BytesIO(file_content)

        if file_extension in ['xls', 'xlsx']:
            df_raw = pd.read_excel(data_io)
        elif file_extension == 'csv':
            df_raw = pd.read_csv(data_io)
        else:
            raise HTTPException(status_code=400, detail=f"Tipe file tidak didukung: .{file_extension}. Mohon unggah file Excel (.xls, .xlsx) atau CSV (.csv).")
            
    except Exception as e:
        logger.error(f"Kesalahan saat membaca file yang diunggah '{file.filename}': {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"Gagal membaca file '{file.filename}': {e}. Pastikan itu adalah file Excel atau CSV yang valid.")

    if df_raw.empty:
        raise HTTPException(status_code=400, detail="File data yang diunggah kosong atau tidak berisi data yang dapat dibaca.")

    # 2. Mensimulasikan `self.charts` (konfigurasi bagan)
    # Karena tidak ada logika yang disediakan untuk membuat ChartConfig dari `df_raw`,
    # kita akan membuat satu konfigurasi bagan sederhana secara otomatis untuk demonstrasi.
    charts: List[ChartConfig] = []
    
    if len(df_raw.columns) < 2:
        raise HTTPException(status_code=400, detail="Data yang diunggah memiliki kolom yang tidak mencukupi (kurang dari 2) untuk membuat bagan secara otomatis.")

    # Mencoba membuat satu bagan: menggunakan kolom non-numerik pertama sebagai x, dan numerik pertama sebagai y.
    # Jika tidak ada kolom non-numerik, gunakan dua kolom numerik pertama.
    x_col_candidate: Optional[str] = None
    for col in df_raw.columns:
        if not pd.api.types.is_numeric_dtype(df_raw[col]):
            x_col_candidate = col
            break
    
    numeric_cols = df_raw.select_dtypes(include=['number']).columns.tolist()

    if x_col_candidate and numeric_cols:
        # Bagan: Kolom non-numerik pertama vs Kolom numerik pertama
        charts.append(ChartConfig(
            data=df_raw,
            x_column=x_col_candidate,
            y_column=numeric_cols[0],
            title=f"Bagan: {numeric_cols[0]} berdasarkan {x_col_candidate}",
            scale_x=1.5, scale_y=1.5
        ))
    elif len(numeric_cols) >= 2:
        # Bagan: Kolom numerik pertama vs Kolom numerik kedua (jika tidak ada non-numerik)
        charts.append(ChartConfig(
            data=df_raw,
            x_column=numeric_cols[0],
            y_column=numeric_cols[1],
            title=f"Bagan: {numeric_cols[1]} berdasarkan {numeric_cols[0]}",
            scale_x=1.5, scale_y=1.5
        ))
    else:
        raise HTTPException(status_code=400, detail="Tidak dapat menentukan kolom yang sesuai untuk pembuatan bagan secara otomatis. Pastikan Anda memiliki setidaknya dua kolom, salah satunya numerik, atau dua kolom numerik.")

    if not charts:
        raise HTTPException(status_code=400, detail="Tidak ada konfigurasi bagan yang valid yang dapat diturunkan dari data yang diunggah.")

    # Gunakan BytesIO untuk menulis workbook Excel ke dalam memori
    output_buffer = BytesIO()
        
    try:
        with xlsxwriter.Workbook(output_buffer, {'in_memory': True}) as workbook:
            dashboard_sheet = workbook.add_worksheet(dashboard_name)
            data_sheet = workbook.add_worksheet("Chart_Data_Source")
            data_sheet.hide() # Sembunyikan lembar data sumber

            current_row_for_data_source = 0
            chart_position_index = 0
            
            # Kelola offset baris secara dinamis untuk judul dan ringkasan
            row_offset = 2
            if dashboard_title:
                title_format = workbook.add_format({'bold': True, 'font_size': 16, 'align': 'center', 'valign': 'vcenter', 'fg_color': '#2C3E50', 'font_color': 'white'})
                dashboard_sheet.merge_range('B1:S1', dashboard_title, title_format)
                row_offset += 1 # Pindah ke baris berikutnya setelah judul
            
            if summary:
                summary_format = workbook.add_format({'bold': True, 'font_size': 11, 'text_wrap': True})
                dashboard_sheet.write_string(f'B{row_offset}', "Ringkasan Analisis AI:", summary_format)
                dashboard_sheet.write_string(f'B{row_offset+1}', summary, workbook.add_format({'text_wrap': True}))
                row_offset += 5 # Tambahkan spasi untuk ringkasan dan antara ringkasan dengan bagan

            for config in charts:
                # Pengecekan kolom yang diperlukan dilakukan sebelum akses untuk mencegah error.
                if config.x_column not in config.data.columns or config.y_column not in config.data.columns:
                    logger.warning(f"Melewati bagan '{config.title}' karena kolom yang diperlukan ('{config.x_column}', '{config.y_column}') tidak ada.")
                    continue
                    
                df_viz_data = config.data[[config.x_column, config.y_column]].copy()
                df_viz_data.dropna(subset=[config.x_column, config.y_column], inplace=True) # Hapus baris dengan NaN di kolom bagan
                
                if df_viz_data.empty: 
                    logger.warning(f"Melewati bagan '{config.title}' karena data kosong setelah pemrosesan.")
                    continue
                
                # Tulis header ke lembar data sumber
                data_sheet.write_row(current_row_for_data_source, 0, df_viz_data.columns, workbook.add_format({'bold': True}))
                # Tulis data ke lembar data sumber
                for r, row_data in enumerate(df_viz_data.itertuples(index=False), 1):
                    data_sheet.write_row(current_row_for_data_source + r, 0, row_data)

                # Buat bagan menggunakan helper function
                chart = _create_chart_helper(workbook, config, "Chart_Data_Source", current_row_for_data_source)
                
                # Tempatkan bagan di lembar dasbor
                chart_row = row_offset + (chart_position_index // 2) * 18 # Tinggi kira-kira 18 baris per bagan
                chart_col = 'B' if chart_position_index % 2 == 0 else 'K' # Dua bagan per baris (kolom B dan K)
                dashboard_sheet.insert_chart(f'{chart_col}{chart_row}', chart, {'x_scale': config.scale_x, 'y_scale': config.scale_y})
                
                chart_position_index += 1
                current_row_for_data_source += len(df_viz_data) + 3 # Tambahkan untuk header data + spasi untuk data bagan berikutnya
            
            dashboard_sheet.set_column('A:A', 2) # Kolom A lebih sempit untuk estetika
            dashboard_sheet.set_column('B:Z', 12) # Lebar default untuk kolom data
        
        # Setelah workbook ditutup, ambil byte dari buffer
        output_buffer.seek(0)
        excel_bytes = output_buffer.getvalue()

        logger.result(f"Dasbor '{dashboard_name}' berhasil dibuat.")
        
        # 3. Mengembalikan hasil sebagai dictionary Python
        return {
            "status": "success",
            "message": f"Dasbor '{dashboard_name}' berhasil dihasilkan.",
            "dashboard_name": dashboard_name,
            "file_size_bytes": len(excel_bytes),
            "file_content_available": True # Dalam aplikasi nyata, ini mungkin FileResponse atau link unduhan
        }
    except HTTPException:
        # Pastikan HTTPException yang mungkin diangkat oleh helper tetap diteruskan
        raise
    except Exception as e:
        logger.error(f"Kesalahan FATAL saat membuat dasbor: {e}", exc_info=True)
        # 4. Mengganti print ke stderr/sys.exit dengan raise HTTPException dari FastAPI
        raise HTTPException(status_code=500, detail=f"Gagal menghasilkan dasbor: {e}")
```

```python
import io
import pandas as pd
from fastapi import Form, UploadFile, HTTPException, File
from typing import List, Dict, Any, Optional, Literal
from enum import Enum
from pydantic import BaseModel
import logging

# Konfigurasi logger dasar (ganti dengan setup logging aplikasi Anda yang sebenarnya)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
# Tambahkan handler jika belum ada, untuk mencegah duplikasi jika kode ini dijalankan berulang
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)


# --- Helper Enums dan Model yang diperlukan ---
class ChartType(str, Enum):
    COLUMN = "COLUMN"
    PIE = "PIE"
    BAR = "BAR"

class ChartConfig(BaseModel):
    chart_type: ChartType
    title: str
    data: List[Dict[str, Any]] # Data akan dikonversi ke list of dicts
    x_column: Optional[str] = None
    y_column: Optional[str] = None
    x_label: Optional[str] = None
    y_label: Optional[str] = None
    show_data_labels: Optional[bool] = False

# --- Fungsi bantu untuk persiapan data (menggantikan metode 'self.' dari fungsi asli) ---
def prepare_numeric_distribution_data(df: pd.DataFrame, column: str) -> pd.DataFrame:
    """
    Mempersiapkan data untuk bagan distribusi numerik.
    Menggunakan binning untuk data kontinu atau value counts untuk diskrit.
    """
    if pd.api.types.is_numeric_dtype(df[column]):
        # Jika banyak nilai unik (kemungkinan kontinu), lakukan binning
        if df[column].nunique() > 50 and len(df[column].dropna()) > 1: # Ambag batas untuk binning vs value_counts
            # Buat histogram sederhana dengan 10 bin
            # Menggunakan value_counts pada data yang sudah di-bin
            bins = pd.cut(df[column].dropna(), bins=10, include_lowest=True, right=True)
            counts = bins.value_counts().sort_index()
            # Konversi IntervalIndex ke string agar lebih mudah diserialkan ke JSON
            data = pd.DataFrame({
                'Value': [str(interval) for interval in counts.index],
                'Count': counts.values
            })
        else: # Numerik diskrit atau jumlah unik sedikit, hitung nilai unik
            data = df[column].value_counts().reset_index()
            data.columns = ['Value', 'Count']
        return data.dropna()
    return pd.DataFrame()


def prepare_categorical_data(df: pd.DataFrame, column: str, top_n: int = 10) -> pd.DataFrame:
    """
    Mempersiapkan data untuk bagan distribusi kategorikal.
    """
    data = df[column].value_counts().nlargest(top_n).reset_index()
    data.columns = ['Category', 'Count']
    return data.dropna()


async def endpoint_name(
    user: str = Form(...),
    password: str = Form(...),
    port: int = Form(8080),
    host: str = Form("localhost"),
    debug: bool = Form(False),
    dry_run: bool = Form(False),
    config_file: str | None = Form(None),
    verbose: int = Form(0),
    log_level: Literal['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] = Form('INFO'),
    timeout: float = Form(30.0),
    file: UploadFile = File(...),
    max_charts: int = Form(6), # Ditambahkan dari parameter fungsi asli
    max_unique_for_categorical: int = Form(50) # Ditambahkan dari parameter fungsi asli
) -> dict:
    
    # 1. Membaca data dari file.read() (bytes)
    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="File yang diunggah kosong.")

    # Menentukan tipe file dari content_type atau nama file
    file_extension = file.filename.split('.')[-1].lower() if file.filename else ''
    df: pd.DataFrame

    try:
        if file_extension == 'csv' or file.content_type == 'text/csv':
            df = pd.read_csv(io.StringIO(contents.decode('utf-8')))
        elif file_extension in ['xls', 'xlsx'] or file.content_type in ['application/vnd.ms-excel', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet']:
            df = pd.read_excel(io.BytesIO(contents))
        else:
            # Mencoba sebagai CSV jika content type generik atau tidak diketahui
            try:
                df = pd.read_csv(io.StringIO(contents.decode('utf-8')))
            except pd.errors.ParserError:
                 raise HTTPException(status_code=400, detail=f"Tipe file '{file.content_type}' atau '{file_extension}' tidak didukung. Coba CSV atau Excel.")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Tidak dapat mendekode isi file sebagai UTF-8. Pastikan ini adalah file teks yang valid seperti CSV.")
    except pd.errors.EmptyDataError:
        raise HTTPException(status_code=400, detail="File kosong atau tidak berisi data.")
    except Exception as e:
        logger.error(f"Error saat membaca file yang diunggah: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Gagal memproses file: {e}")

    if df.empty:
        raise HTTPException(status_code=400, detail="Data yang diproses kosong. Pastikan file berisi data yang valid.")

    suggestions: List[ChartConfig] = []
    
    # 2. Logika Bisnis Inti (adaptasi dari auto_analyze_dataframe)
    for column in df.columns:
        if len(suggestions) >= max_charts:
            break
        
        # Lewati kolom dengan persentase null yang tinggi (> 50%)
        if df[column].isnull().sum() / len(df) > 0.5:
            continue
        
        if pd.api.types.is_numeric_dtype(df[column]):
            data_df = prepare_numeric_distribution_data(df, column)
            if not data_df.empty:
                suggestions.append(ChartConfig(
                    chart_type=ChartType.COLUMN,
                    title=f"Distribusi: {column}",
                    data=data_df.to_dict(orient='records'), # Konversi DataFrame ke list of dicts
                    x_column='Value',
                    y_column='Count',
                    x_label=column,
                    y_label='Frekuensi'
                ))
        # Periksa apakah kolom cocok untuk analisis kategorikal
        elif df[column].nunique() <= max_unique_for_categorical:
            data_df = prepare_categorical_data(df, column, top_n=10) # top_n hardcoded sesuai fungsi asli
            if not data_df.empty:
                chart_type = ChartType.PIE if len(data_df) <= 5 else ChartType.BAR
                suggestions.append(ChartConfig(
                    chart_type=chart_type,
                    title=f"Distribusi: {column}",
                    data=data_df.to_dict(orient='records'), # Konversi DataFrame ke list of dicts
                    x_column='Category',
                    y_column='Count',
                    show_data_labels=(chart_type == ChartType.PIE)
                ))
                
    logger.info(f"Analisis otomatis (Fallback) menyarankan {len(suggestions)} bagan.")
    
    # 3. Mengembalikan hasil sebagai dictionary Python
    # Konversi list dari ChartConfig Pydantic models ke list of dicts
    return {"suggestions": [s.dict() for s in suggestions]}
```

```python
import pandas as pd
import io
from fastapi import Form, File, UploadFile, HTTPException, status
from typing import Literal, Optional, List, Dict, Any

# Helper functions for data preparation
def _prepare_categorical_data_helper(df: pd.DataFrame, column_name: str) -> List[Dict[str, Any]]:
    """Generates categorical data distribution (counts) for a given column."""
    if column_name not in df.columns:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Missing required column: '{column_name}' for chart data preparation.")
    
    # Filter out NaN values before counting
    counts = df[column_name].dropna().value_counts().reset_index()
    counts.columns = ['Category', 'Count']
    return counts.to_dict(orient='records')

def _prepare_top_items_helper(df: pd.DataFrame, column_name: str, top_n: Optional[int] = None) -> List[Dict[str, Any]]:
    """Prepares data for top items, especially useful for comma-separated lists within a column."""
    if column_name not in df.columns:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Missing required column: '{column_name}' for chart data preparation.")
    
    # Extract and flatten items from potentially comma-separated strings
    # Ensure items are treated as strings and filter out empty strings after splitting
    items_series = df[column_name].dropna().astype(str).apply(
        lambda x: [s.strip() for s in x.split(',') if s.strip()]
    )
    flat_items = [item for sublist in items_series if isinstance(sublist, list) for item in sublist]
    
    if not flat_items: # Handle case where no valid items are extracted
        return []

    counts = pd.Series(flat_items).value_counts().reset_index()
    counts.columns = ['Item', 'Count']
    
    if top_n is not None:
        counts = counts.head(top_n)
    
    return counts.to_dict(orient='records')

def _prepare_numeric_distribution_helper(df: pd.DataFrame, column_name: str, round_to: int = 0) -> List[Dict[str, Any]]:
    """Prepares numerical data distribution, optionally rounding values."""
    if column_name not in df.columns:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Missing required column: '{column_name}' for chart data preparation.")
    
    # Convert column to numeric, coercing errors to NaN, then drop NaNs
    numeric_series = pd.to_numeric(df[column_name], errors='coerce').dropna()
    
    if numeric_series.empty: # If no valid numeric data remains
        return []

    # Round values and count their occurrences, then sort by value
    distribution = numeric_series.round(round_to).value_counts().sort_index().reset_index()
    distribution.columns = ['Value', 'Count']
    return distribution.to_dict(orient='records')

async def endpoint_name(
    user: str = Form(...),
    password: str = Form(...),
    port: int = Form(8080),
    host: str = Form("localhost"),
    debug: bool = Form(False),
    dry_run: bool = Form(False),
    config_file: str | None = Form(None),
    verbose: int = Form(0),
    log_level: Literal['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] = Form('INFO'),
    timeout: float = Form(30.0),
    file: UploadFile = File(...)
) -> dict:
    
    # 1. Load data from the uploaded file
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No file uploaded.")

    try:
        content = await file.read()
        if not content:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty.")
            
        df_content = io.StringIO(content.decode('utf-8'))
        df = pd.read_csv(df_content)
    except UnicodeDecodeError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Could not decode file content. Please ensure it's a UTF-8 encoded CSV.")
    except pd.errors.EmptyDataError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty or malformed.")
    except pd.errors.ParserError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Could not parse file content as CSV. Please ensure it's a valid CSV.")
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"An unexpected error occurred while processing the file: {e}")

    # 2. Validate essential columns required for all charts
    core_required_cols = ['Severity', 'Affected_Servers', 'Max_CVSS_Score', 'CVE_ID']
    for col in core_required_cols:
        if col not in df.columns:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Missing core required column: '{col}' in the uploaded data. Please check your CSV header.")

    charts_output: List[Dict[str, Any]] = []

    # Helper function to append chart configurations to the output list
    def add_chart_config(chart_config: Dict[str, Any]):
        charts_output.append(chart_config)

    # BAGAN 1: Distribusi Severity (Pie)
    add_chart_config({
        'chart_type': 'PIE',
        'title': 'Distribusi Tingkat Keparahan Kerentanan',
        'data': _prepare_categorical_data_helper(df, 'Severity'),
        'x_column': 'Category',
        'y_column': 'Count',
        'show_data_labels': True
    })
    
    # BAGAN 2: Top 10 Servers (Bar)
    add_chart_config({
        'chart_type': 'BAR',
        'title': '10 Server Teratas yang Paling Terpengaruh',
        'data': _prepare_top_items_helper(df, 'Affected_Servers', top_n=10),
        'x_column': 'Item',
        'y_column': 'Count',
        'y_label': 'Nama Server',
        'x_label': 'Jumlah Kerentanan',
        'color': '#E74C3C',
        'show_legend': False,
        'scale_x': 1.5,
        'scale_y': 1.5,
        'sort_data': True,
        'sort_ascending': True
    })

    # BAGAN 3: CVSS Distribution (Column)
    add_chart_config({
        'chart_type': 'COLUMN',
        'title': 'Distribusi Skor CVSS Maksimal',
        'data': _prepare_numeric_distribution_helper(df, 'Max_CVSS_Score', round_to=1),
        'x_column': 'Value',
        'y_column': 'Count',
        'x_label': 'Skor CVSS (0-10)',
        'y_label': 'Jumlah CVE',
        'color': '#3498DB',
        'show_legend': False
    })

    # BAGAN 4: Top 15 CVEs by Asset Count (Bar)
    # Create a temporary DataFrame for asset count calculation to avoid modifying the original df
    df_temp = df.copy()
    
    # Calculate 'Asset_Count' based on the number of affected servers listed
    df_temp['Asset_Count'] = df_temp['Affected_Servers'].apply(
        lambda x: len([s for s in str(x).split(',') if s.strip()]) if pd.notna(x) else 0
    )
    
    # Select top 15 CVEs by Asset_Count
    top_cve_asset_data = df_temp[['CVE_ID', 'Asset_Count']].sort_values('Asset_Count', ascending=False).head(15)
    
    add_chart_config({
        'chart_type': 'BAR',
        'title': '15 CVE Teratas berdasarkan Jumlah Aset',
        'data': top_cve_asset_data.to_dict(orient='records'),
        'x_column': 'CVE_ID',
        'y_column': 'Asset_Count',
        'y_label': 'CVE ID',
        'x_label': 'Jumlah Aset Terpengaruh',
        'color': '#F39C12',
        'show_legend': False,
        'scale_x': 1.5,
        'scale_y': 1.5,
        'sort_data': True,
        'sort_ascending': True
    })

    # BAGAN 5: Ringkasan Semua Server berdasarkan Jumlah Kerentanan (Bar)
    all_servers_data = _prepare_top_items_helper(df, 'Affected_Servers', top_n=None)
    add_chart_config({
        'chart_type': 'BAR',
        'title': 'Ringkasan Semua Server berdasarkan Jumlah Kerentanan',
        'data': all_servers_data,
        'x_column': 'Item',
        'y_column': 'Count',
        'y_label': 'Nama Server',
        'x_label': 'Jumlah Kerentanan',
        'color': '#1ABC9C',
        'show_legend': False,
        'scale_x': 1.5,
        'scale_y': 2.0,
        'sort_data': True,
        'sort_ascending': True
    })
    
    # BAGAN 6: Ringkasan Semua CVE berdasarkan Jumlah Aset (Bar)
    # Reuse df_temp which already has 'Asset_Count' calculated
    all_cve_asset_data = df_temp[['CVE_ID', 'Asset_Count']].sort_values('Asset_Count', ascending=False).to_dict(orient='records')
    add_chart_config({
        'chart_type': 'BAR',
        'title': 'Ringkasan Semua CVE berdasarkan Jumlah Aset',
        'data': all_cve_asset_data,
        'x_column': 'CVE_ID',
        'y_column': 'Asset_Count',
        'y_label': 'CVE ID',
        'x_label': 'Jumlah Aset Terpengaruh',
        'color': '#9B59B6',
        'show_legend': False,
        'scale_x': 1.5,
        'scale_y': 2.0,
        'sort_data': True,
        'sort_ascending': True
    })

    return {"charts": charts_output}
```

```python
import io
import tempfile
import os
import logging
from typing import Literal, Optional

from fastapi import Form, File, UploadFile, HTTPException, status

# Konfigurasi logging dasar.
# Dalam aplikasi nyata, logging akan dikonfigurasi secara global
# dan lebih kuat (misalnya, menambahkan handler ke stderr, dll.).
logger = logging.getLogger(__name__)
# Atur level default, dapat ditimpa oleh parameter fungsi
logger.setLevel(logging.INFO)
# Untuk memastikan log terlihat jika belum ada konfigurasi handler
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

# --- MULAI DARI KONTEKS/PLACEHOLDER YANG DIPERLUKAN UNTUK REFACTORING ---
# Ini adalah kelas placeholder/mock untuk mensimulasikan konteks 'self' asli dan metodenya.
# Dalam aplikasi Anda yang sebenarnya, ini akan menjadi kelas logika bisnis Anda yang sudah ada.
class DashboardCreator:
    def __init__(self, input_data: bytes):
        self.input_data = input_data
        self.charts = [] # Untuk mensimulasikan len(self.charts)

    def create_dashboard(self, output_path: Optional[str], dashboard_name: str, main_title: str) -> bool:
        """
        Mensimulasikan pembuatan file dashboard Excel.
        Dalam skenario nyata, ini akan menguraikan input_data,
        menghasilkan grafik, dan menulis file Excel ke output_path.
        """
        try:
            # Mensimulasikan pemrosesan input_data
            # Mengasumsikan input_data adalah teks (misalnya, CSV) untuk simulasi jumlah grafik sederhana
            try:
                decoded_data = self.input_data.decode('utf-8')
                lines = decoded_data.splitlines()
            except UnicodeDecodeError:
                # Jika tidak dapat didekode sebagai UTF-8, perlakukan sebagai data biner mentah, perkirakan barisnya
                lines = [f"Binary data chunk {i}" for i in range(len(self.input_data) // 1000 + 1)]

            # Mensimulasikan pembuatan grafik berdasarkan volume data
            num_charts_simulated = max(1, len(lines) // 5)
            self.charts = [{'id': i, 'type': 'simulated_chart'} for i in range(num_charts_simulated)]
            logger.debug(f"Simulasi {num_charts_simulated} grafik berdasarkan data masukan.")

            if output_path:
                # Mensimulasikan penulisan file Excel ke jalur yang ditentukan
                # Dalam skenario nyata, Anda akan menggunakan pustaka seperti openpyxl di sini.
                with open(output_path, 'wb') as f:
                    f.write(b'Simulated Excel Dashboard Content created from input data.')
                logger.info(f"Simulasi file dashboard ditulis ke: {output_path}")
            else:
                logger.info("Mode dry run atau jalur keluaran tidak ditentukan: tidak ada file dashboard yang ditulis.")

            logger.debug(f"Pembuatan dashboard '{dashboard_name}' ('{main_title}') disimulasikan berhasil.")
            return True
        except Exception as e:
            logger.error(f"Gagal mensimulasikan pembuatan dashboard: {e}", exc_info=True)
            return False
# --- AKHIR DARI KONTEKS/PLACEHOLDER YANG DIPERLUKAN UNTUK REFACTORING ---

async def endpoint_name(
    user: str = Form(...),
    password: str = Form(...),
    port: int = Form(8080),
    host: str = Form("localhost"),
    debug: bool = Form(False),
    dry_run: bool = Form(False),
    config_file: str | None = Form(None),
    verbose: int = Form(0),
    log_level: Literal['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] = Form('INFO'),
    timeout: float = Form(30.0),
    file: UploadFile = File(...)
) -> dict:
    # --- Konfigurasi Logging (cakupan untuk fungsi ini) ---
    # Sesuaikan level logger berdasarkan parameter masukan untuk permintaan spesifik ini.
    # Catatan: Memodifikasi level logger global secara langsung dapat menyebabkan kondisi balapan
    # di lingkungan konkurensi tinggi jika beberapa permintaan memodifikasinya secara bersamaan.
    # Untuk solusi yang kuat, pertimbangkan konteks logging yang cakupannya per permintaan
    # (misalnya, melalui contextvars) atau meneruskan log_level secara eksplisit ke fungsi internal.
    numeric_level = getattr(logging, log_level.upper(), None)
    if not isinstance(numeric_level, int):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid log_level: {log_level}")

    # Prioritaskan flag debug dan verbose untuk verbositas yang lebih tinggi
    effective_log_level = numeric_level
    if debug or verbose > 0: # Jika debug atau verbose aktif, pastikan setidaknya level DEBUG
        effective_log_level = min(effective_log_level, logging.DEBUG) # Pilih level yang lebih verbose

    logger.setLevel(effective_log_level) # Terapkan level yang dihitung

    logger.debug(f"Permintaan diterima: user='{user}', host='{host}', port='{port}', debug={debug}, dry_run={dry_run}, config_file='{config_file}', verbose={verbose}, log_level='{log_level}', timeout={timeout}")
    logger.debug(f"Level logger diatur ke: {logging.getLevelName(logger.level)}")

    # --- Autentikasi ---
    # Contoh: Ganti dengan logika autentikasi yang sebenarnya (misalnya, pencarian database, validasi token)
    if user != "admin" or password != "secure_password":
        logger.warning(f"Autentikasi gagal untuk user: {user}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Kredensial tidak valid. Harap berikan nama pengguna dan kata sandi yang valid."
        )
    logger.debug(f"Autentikasi berhasil untuk user: {user}")

    # --- Baca Konten File yang Diunggah ---
    contents = None
    try:
        contents = await file.read()
        if not contents:
            logger.error(f"File yang diunggah '{file.filename}' kosong.")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File yang diunggah kosong. Harap berikan file dengan konten."
            )
        logger.info(f"Berhasil membaca {len(contents)} byte dari file yang diunggah '{file.filename}'.")
    except Exception as e:
        logger.exception(f"Kesalahan membaca file yang diunggah '{file.filename}': {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Gagal membaca file yang diunggah '{file.filename}': {e}"
        )

    # --- Logika Pembuatan Dashboard ---
    # Instansiasi DashboardCreator dengan konten file yang diunggah
    creator = DashboardCreator(input_data=contents)

    output_filepath_for_creation = None
    return_output_path_info = "N/A (dry run)"

    # Tentukan apakah file fisik harus dibuat dan jalurnya
    if not dry_run:
        temp_file_descriptor = None
        try:
            # Buat file sementara untuk menyimpan dashboard yang dihasilkan.
            # tempfile.mkstemp mengembalikan deskriptor file tingkat rendah (fd) dan jalurnya.
            # Kita menutup fd segera karena DashboardCreator akan membukanya berdasarkan jalur.
            temp_file_descriptor, path = tempfile.mkstemp(suffix=".xlsx", prefix="vem_dashboard_", dir=tempfile.gettempdir())
            os.close(temp_file_descriptor) # Tutup deskriptor file
            output_filepath_for_creation = path
            return_output_path_info = path # Jalur ini akan disertakan dalam respons
            logger.debug(f"Jalur keluaran sementara dihasilkan untuk dashboard: {output_filepath_for_creation}")
        except Exception as e:
            logger.exception(f"Kesalahan membuat jalur file keluaran sementara: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Tidak dapat menyiapkan lokasi keluaran: {e}"
            )
    else:
        logger.info("Mode dry run aktif: Tidak ada file dashboard fisik yang akan ditulis.")

    # Panggil logika pembuatan dashboard inti dari instance DashboardCreator
    success = creator.create_dashboard(
        output_filepath_for_creation,
        'Vulnerability_Dashboard',
        'Vulnerability & Exposure Management Dashboard'
    )

    num_charts = len(creator.charts) if success else 0

    # --- Penanganan Kesalahan & Respons ---
    if not success:
        # Jika pembuatan dashboard gagal dan file sementara dicoba, coba bersihkan.
        if output_filepath_for_creation and os.path.exists(output_filepath_for_creation):
            try:
                os.remove(output_filepath_for_creation)
                logger.debug(f"Membersihkan file sementara setelah pembuatan gagal: {output_filepath_for_creation}")
            except Exception as e:
                logger.error(f"Gagal membersihkan file sementara '{output_filepath_for_creation}': {e}")

        logger.error("Gagal membuat dashboard VEM.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Gagal membuat dashboard VEM. Harap periksa log untuk detail lebih lanjut."
        )

    # Siapkan respons keberhasilan
    response_message = "Dashboard VEM berhasil dibuat."
    if dry_run:
        response_message = "Simulasi pembuatan Dashboard VEM berhasil (dry run)."
    elif debug: # Secara opsional tambahkan detail lebih lanjut jika debug aktif
        response_message += f" File dashboard disimpan di {output_filepath_for_creation}"

    return {
        "status": "success",
        "message": response_message,
        "charts_created": num_charts,
        "output_file_location": return_output_path_info,
        "dashboard_name": "Vulnerability & Exposure Management Dashboard",
        "filename_received": file.filename,
        "file_size_bytes": len(contents)
    }
```

```python
import io
import pandas as pd
from fastapi import Form, File, UploadFile, HTTPException
from typing import Literal, Optional
import logging
import tempfile
import os

# --- Catatan Penting ---
# Kelas VEMDataVisualizer dan konfigurasi logger tidak termasuk dalam output akhir sesuai instruksi.
# Namun, Anda harus memastikan keduanya tersedia dan terimport di lingkungan Anda.
# Contoh placeholder untuk VEMDataVisualizer (asumsi yang sangat minimal):
# class VEMDataVisualizer:
#     def __init__(self, df: pd.DataFrame):
#         self.df = df
#         self.simulated_chart_count = 1 if not df.empty else 0
#     def create_vem_dashboard(self, output_path: str) -> int:
#         try:
#             with pd.ExcelWriter(output_path, engine='xlsxwriter') as writer:
#                 self.df.to_excel(writer, sheet_name='Dashboard Data', index=False)
#             return self.simulated_chart_count
#         except Exception:
#             return 0

# Konfigurasi logger (asumsi logger dengan nama __name__ digunakan):
# logger = logging.getLogger(__name__)
# logger.setLevel(logging.INFO) # Level default, akan diatur ulang oleh parameter endpoint
# --- Akhir Catatan ---

# Pastikan VEMDataVisualizer dan logger telah didefinisikan atau diimpor
# Misalnya:
# from .your_module import VEMDataVisualizer
# logger = logging.getLogger(__name__)

async def endpoint_name(user: str = Form(...), password: str = Form(...), port: int = Form(8080), host: str = Form("localhost"), debug: bool = Form(False), dry_run: bool = Form(False), config_file: str | None = Form(None), verbose: int = Form(0), log_level: Literal['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] = Form('INFO'), timeout: float = Form(30.0), file: UploadFile = File(...)) -> dict:
    """
    Memproses file input Excel yang diunggah untuk membuat dasbor visualisasi VEM.
    Mengembalikan status pemrosesan dan jumlah dasbor yang berhasil dibuat.
    """
    # Atur level logger berdasarkan parameter endpoint
    if debug:
        logger.setLevel(logging.DEBUG)
    elif verbose > 0:
        logger.setLevel(logging.DEBUG if verbose >= 1 else logging.INFO)
    else:
        level = getattr(logging, log_level.upper(), logging.INFO)
        logger.setLevel(level)

    logger.info("Memulai visualisasi Dasbor VEM (Phase 4) melalui endpoint...")
    logger.debug(f"User: {user}, Host: {host}:{port}, Debug: {debug}, Dry Run: {dry_run}, Config File: {config_file}, Verbose: {verbose}, Log Level: {log_level}, Timeout: {timeout}")

    if dry_run:
        logger.info("Mode 'dry_run' aktif. Tidak ada pemrosesan file yang akan dilakukan.")
        return {"status": "success", "message": "Dry run selesai. Tidak ada pemrosesan yang dilakukan."}

    df_input: pd.DataFrame
    try:
        contents = await file.read()
        if not contents:
            logger.error("File input kosong.")
            raise HTTPException(status_code=400, detail="File input kosong.")
        
        # Asumsi file input adalah Excel (.xlsx, .xls) berdasarkan konteks `output_excel_path`
        # dari fungsi asli dan penggunaan `pd.DataFrame`.
        df_input = pd.read_excel(io.BytesIO(contents))
        logger.debug(f"File Excel berhasil dibaca. {len(df_input)} baris dan {len(df_input.columns)} kolom ditemukan.")
    except Exception as e:
        logger.error(f"Gagal membaca atau menguraikan file Excel: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"Gagal membaca atau menguraikan file Excel. Pastikan format file benar dan tidak rusak: {e}")

    if df_input.empty:
        logger.error("DataFrame input kosong setelah diuraikan dari file.")
        raise HTTPException(status_code=400, detail="DataFrame input kosong setelah diuraikan dari file. Pastikan file berisi data yang valid.")

    # Inisialisasi visualizer dengan DataFrame input
    vem_visualizer = VEMDataVisualizer(df_input)
    
    # Membuat file sementara untuk output Excel
    # File ini akan dihapus setelah proses selesai, karena endpoint hanya mengembalikan status,
    # bukan file itu sendiri.
    temp_output_file_path: Optional[str] = None
    charts_created_count: int = 0

    try:
        # Buat file sementara dan dapatkan namanya.
        # Penting untuk menutup file setelah mendapatkan namanya agar
        # `create_vem_dashboard` dapat membukanya kembali untuk menulis.
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as temp_file:
            temp_output_file_path = temp_file.name
        
        logger.debug(f"Output Excel sementara akan disimpan di: {temp_output_file_path}")
        charts_created_count = vem_visualizer.create_vem_dashboard(temp_output_file_path)

        if charts_created_count > 0:
            logger.info(f"Berhasil membuat {charts_created_count} dasbor VEM.")
            return {
                "status": "success",
                "charts_created": charts_created_count,
                "message": f"Berhasil membuat {charts_created_count} dasbor VEM."
                # Jika file output perlu dikembalikan ke pengguna, tipe pengembalian endpoint
                # perlu diubah menjadi StreamingResponse atau FileResponse, bukan dict.
            }
        else:
            logger.warning("Tidak ada dasbor VEM yang dibuat, meskipun input DataFrame tidak kosong.")
            return {
                "status": "warning",
                "charts_created": 0,
                "message": "Tidak ada dasbor VEM yang dibuat. Mungkin ada masalah dengan data atau logika visualizer."
            }
    except Exception as e:
        logger.error(f"Terjadi kesalahan internal saat membuat dasbor VEM: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Terjadi kesalahan internal saat membuat dasbor VEM: {e}")
    finally:
        # Membersihkan file sementara yang dibuat
        if temp_output_file_path and os.path.exists(temp_output_file_path):
            try:
                os.remove(temp_output_file_path)
                logger.debug(f"File sementara dihapus: {temp_output_file_path}")
            except OSError as e:
                logger.error(f"Gagal menghapus file sementara '{temp_output_file_path}': {e}")
```

```python
import pandas as pd
import io
import os
import uuid
import tempfile
from fastapi import Form, UploadFile, File, HTTPException
from typing import Literal, Dict, Any, List

# Asumsi kelas DataVisualizer didefinisikan di tempat lain dan dapat diakses.
# Contoh struktur DataVisualizer (tidak termasuk dalam output final):
# class DataVisualizer:
#     def __init__(self):
#         self.charts = []
#     def auto_analyze_dataframe(self, df: pd.DataFrame) -> List[Dict[str, Any]]:
#         # Logika analisis otomatis DataFrame
#         configs = []
#         for col in df.columns:
#             # Contoh sederhana: jika numerik, sarankan histogram
#             if pd.api.types.is_numeric_dtype(df[col]):
#                 configs.append({"chart_type": "histogram", "column": col, "title": f"Histogram of {col}"})
#             elif pd.api.types.is_object_dtype(df[col]) or pd.api.types.is_categorical_dtype(df[col]):
#                 configs.append({"chart_type": "bar_chart", "column": col, "title": f"Bar Chart of {col}"})
#             else:
#                 configs.append({"chart_type": "table", "column": col, "title": f"Table of {col}"})
#         return configs
#     def add_chart(self, config: Dict[str, Any]):
#         self.charts.append(config)
#     def create_dashboard(self, output_path: str, dashboard_name: str = 'Dashboard') -> bool:
#         # Logika untuk membuat file dashboard HTML
#         try:
#             with open(output_path, 'w') as f:
#                 f.write(f"<html><head><title>{dashboard_name}</title></head><body>")
#                 f.write(f"<h1>{dashboard_name}</h1>")
#                 f.write(f"<p>Dashboard generated with {len(self.charts)} charts.</p>")
#                 for chart in self.charts:
#                     f.write(f"<div><h2>{chart.get('title', 'Chart')}</h2><p>Type: {chart.get('chart_type')}</p></div>")
#                 f.write(f"</body></html>")
#             return True
#         except Exception as e:
#             # Ganti print ke stderr atau sys.exit dengan raise HTTPException
#             raise IOError(f"Failed to write dashboard to {output_path}: {e}")


async def endpoint_name(user: str = Form(...), password: str = Form(...), port: int = Form(8080), host: str = Form("localhost"), debug: bool = Form(False), dry_run: bool = Form(False), config_file: str | None = Form(None), verbose: int = Form(0), log_level: Literal['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] = Form('INFO'), timeout: float = Form(30.0), file: UploadFile = File(...)) -> dict:
    
    # 2. Membaca data dari file.read() (bytes)
    contents = await file.read()
    
    df: pd.DataFrame
    try:
        # Menentukan tipe file berdasarkan ekstensi
        filename_lower = file.filename.lower()
        if filename_lower.endswith('.csv'):
            # Dekode bytes ke string untuk pemrosesan CSV
            df = pd.read_csv(io.StringIO(contents.decode('utf-8')))
        elif filename_lower.endswith(('.xls', '.xlsx')):
            # Lewati bytes secara langsung untuk pemrosesan Excel
            df = pd.read_excel(io.BytesIO(contents))
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type: {file.filename}. Only CSV and Excel are supported."
            )
    except UnicodeDecodeError:
        # 4. Mengganti print ke stderr atau sys.exit dengan raise HTTPException
        raise HTTPException(
            status_code=400,
            detail="Could not decode CSV file. Please ensure it is UTF-8 encoded."
        )
    except pd.errors.EmptyDataError:
        # 4. Mengganti print ke stderr atau sys.exit dengan raise HTTPException
        raise HTTPException(
            status_code=400,
            detail="The provided file is empty."
        )
    except Exception as e:
        # Menangkap kesalahan pembacaan pandas lainnya
        # 4. Mengganti print ke stderr atau sys.exit dengan raise HTTPException
        raise HTTPException(
            status_code=400,
            detail=f"Error reading file {file.filename}: {e}"
        )

    # Menghasilkan jalur output unik untuk dasbor.
    # Direktori sementara digunakan untuk menyimpan file HTML yang dihasilkan.
    # Dalam lingkungan produksi, file ini biasanya akan disajikan atau disimpan ke penyimpanan persisten.
    temp_dir = tempfile.mkdtemp()
    dashboard_filename = f"quick_dashboard_{uuid.uuid4().hex}.html"
    output_path = os.path.join(temp_dir, dashboard_filename)

    visualizer = DataVisualizer() # Instansiasi visualizer (diasumsikan didefinisikan secara global atau diimpor)

    try:
        # Sesuai dengan default create_quick_dashboard asli, auto_analyze diatur ke True.
        # Signature endpoint tidak menyediakan parameter untuk 'column_configs' atau 'auto_analyze',
        # jadi kami menerapkan logika analisis otomatis default dari fungsi asli.
        for config in visualizer.auto_analyze_dataframe(df):
            visualizer.add_chart(config)
        
        # Membuat dasbor. Fungsi asli mengembalikan boolean.
        # visualizer.create_dashboard diharapkan menulis ke output_path.
        dashboard_created_successfully = visualizer.create_dashboard(output_path, dashboard_name='Quick_Dashboard')

        if not dashboard_created_successfully:
            # Jika visualizer menunjukkan kegagalan dalam membuat dasbor
            # 4. Mengganti print ke stderr atau sys.exit dengan raise HTTPException
            raise HTTPException(
                status_code=500,
                detail="Failed to generate the quick dashboard due to an internal error."
            )

        # 3. Mengembalikan (return) hasil sebagai dictionary Python
        return {
            "status": "success",
            "message": "Quick dashboard generated successfully.",
            "dashboard_path": output_path, # Jalur tempat file HTML dasbor disimpan
            "filename_uploaded": file.filename,
            "user": user,
            "host": host,
            "port": port,
            "debug_mode": debug,
            "dry_run_mode": dry_run,
            "log_level": log_level,
            "verbose_level": verbose,
            "timeout_seconds": timeout,
            "config_file": config_file
        }
    except IOError as e:
        # Menangkap kesalahan khusus yang terkait dengan penulisan file oleh DataVisualizer.create_dashboard
        # 4. Mengganti print ke stderr atau sys.exit dengan raise HTTPException
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save dashboard file: {e}"
        )
    except Exception as e:
        # Menangkap kesalahan tak terduga lainnya selama proses pembuatan dasbor
        # 4. Mengganti print ke stderr atau sys.exit dengan raise HTTPException
        raise HTTPException(
            status_code=500,
            detail=f"An unexpected error occurred during dashboard generation: {e}"
        )
    finally:
        # Dalam aplikasi nyata, pertimbangkan cara menangani file dasbor sementara:
        # - Sajikan secara langsung.
        # - Pindahkan ke lokasi permanen.
        # - Jadwalkan untuk penghapusan setelah periode tertentu.
        # Untuk fungsi yang direfaktor ini, kami mengembalikan jalur, mengasumsikan pemanggil akan menanganinya.
        pass # Placeholder untuk logika pembersihan jika diperlukan nanti.
```

```python
import pandas as pd
import io
import json
import logging
import tempfile
from typing import Dict, Any, Literal, Optional
from fastapi import Form, UploadFile, File, HTTPException

# Asumsi: Kelas DataVisualizer, ChartType, dan ChartConfig didefinisikan di tempat lain
# dan dapat diimpor. Untuk tujuan refactoring ini, kami akan menyediakan definisi dummy
# yang cukup untuk membuat kode berjalan dan menunjukkan logika.
# Dalam aplikasi nyata, Anda akan memiliki implementasi lengkap ini.

# --- Dummy/Placeholder Definitions for External Dependencies ---
# Pastikan ini cocok dengan perilaku yang diharapkan oleh fungsi inti.

class ChartType:
    COLUMN: str = 'COLUMN'
    BAR: str = 'BAR'
    LINE: str = 'LINE'
    PIE: str = 'PIE'
    SCATTER: str = 'SCATTER'
    # Tambahkan tipe bagan lain yang relevan
    
    # Metode helper untuk membandingkan dengan string
    @staticmethod
    def is_type(chart_type_enum, chart_type_str: str) -> bool:
        return chart_type_enum == chart_type_str

class ChartConfig:
    def __init__(self, chart_type, title, data, x_column, y_column, x_label, y_label, sort_data, sort_ascending):
        self.chart_type = chart_type
        self.title = title
        self.data = data
        self.x_column = x_column
        self.y_column = y_column
        self.x_label = x_label
        self.y_label = y_label
        self.sort_data = sort_data
        self.sort_ascending = sort_ascending

class DataVisualizer:
    def __init__(self):
        self.charts = []

    def prepare_categorical_data(self, df: pd.DataFrame, column: str) -> pd.DataFrame:
        if column not in df.columns:
            logger.warning(f"Kolom kategorikal '{column}' tidak ditemukan di DataFrame.")
            return pd.DataFrame()
        # Contoh: Menghitung frekuensi kategori
        return df[column].value_counts().reset_index(name='Count').rename(columns={'index': 'Category'})

    def prepare_numeric_distribution(self, df: pd.DataFrame, column: str, round_to: int) -> pd.DataFrame:
        if column not in df.columns:
            logger.warning(f"Kolom numerik '{column}' tidak ditemukan di DataFrame.")
            return pd.DataFrame()
        if not pd.api.types.is_numeric_dtype(df[column]):
            logger.warning(f"Kolom '{column}' bukan tipe numerik untuk distribusi.")
            return pd.DataFrame()
        # Contoh: Membuat distribusi numerik menggunakan binning
        # Jumlah bins bisa disesuaikan atau dihitung secara otomatis
        bins = pd.cut(df[column], bins=20, include_lowest=True)
        return bins.value_counts().reset_index(name='Count').rename(columns={'index': 'Value'})

    def prepare_aggregated_data(self, df: pd.DataFrame, group_by: str, agg_column: str, agg_func: str) -> pd.DataFrame:
        if group_by not in df.columns:
            logger.warning(f"Kolom group_by '{group_by}' tidak ditemukan di DataFrame.")
            return pd.DataFrame()
        
        if agg_func == 'count':
            # Size() secara otomatis mengembalikan jumlah baris per grup
            result = df.groupby(group_by).size().reset_index(name='Value')
        else:
            if agg_column not in df.columns:
                logger.warning(f"Kolom agregasi '{agg_column}' tidak ditemukan di DataFrame.")
                return pd.DataFrame()
            if not pd.api.types.is_numeric_dtype(df[agg_column]):
                logger.warning(f"Kolom agregasi '{agg_column}' bukan tipe numerik.")
                return pd.DataFrame()
            
            valid_agg_funcs = ['sum', 'mean', 'median', 'min', 'max']
            if agg_func not in valid_agg_funcs:
                logger.warning(f"Fungsi agregasi '{agg_func}' tidak didukung. Menggunakan 'sum' sebagai default.")
                agg_func = 'sum'
            result = df.groupby(group_by)[agg_column].agg(agg_func).reset_index()
            result.columns = [group_by, 'Value'] # Kolom output standar 'Value'
        
        result.columns = ['Group', 'Value'] # Pastikan nama kolom konsisten
        return result

    def add_chart(self, config: ChartConfig):
        self.charts.append(config)

    def auto_analyze_dataframe(self, df: pd.DataFrame, max_charts: int) -> list[ChartConfig]:
        """Melakukan analisis otomatis untuk membuat bagan fallback."""
        fallback_configs = []
        
        # Cari kolom numerik pertama
        numeric_cols = df.select_dtypes(include=['number']).columns
        if len(numeric_cols) > 0 and len(fallback_configs) < max_charts:
            col = numeric_cols[0]
            data = self.prepare_numeric_distribution(df, col, 1)
            if not data.empty:
                fallback_configs.append(ChartConfig(
                    chart_type=ChartType.COLUMN, title=f'Distribusi {col} (Fallback)', data=data,
                    x_column='Value', y_column='Count', x_label='Nilai', y_label='Jumlah', sort_data=False, sort_ascending=True
                ))
        
        # Cari kolom kategorikal pertama
        categorical_cols = df.select_dtypes(include=['object', 'category', 'bool']).columns
        if len(categorical_cols) > 0 and len(fallback_configs) < max_charts:
            col = categorical_cols[0]
            data = self.prepare_categorical_data(df, col)
            if not data.empty:
                fallback_configs.append(ChartConfig(
                    chart_type=ChartType.BAR, title=f'Jumlah {col} (Fallback)', data=data,
                    x_column='Category', y_column='Count', x_label='Kategori', y_label='Jumlah', sort_data=True, sort_ascending=False
                ))
        return fallback_configs

    def create_dashboard(self, output_path: str, dashboard_name: str, dashboard_title: str, summary: Dict[str, Any]) -> bool:
        """
        Simulasi pembuatan dashboard Excel.
        Dalam implementasi nyata, ini akan menulis file Excel dengan bagan.
        """
        logger.info(f"Simulasi pembuatan dashboard '{dashboard_name}' di '{output_path}' dengan {len(self.charts)} bagan.")
        try:
            # Contoh simulasi penulisan file Excel kosong atau dengan data bagan dasar
            # Menggunakan pandas.ExcelWriter untuk menulis spesifikasi bagan ke sheet pertama
            # Di sini Anda akan mengintegrasikan library seperti openpyxl atau xlsxwriter
            # untuk menambahkan bagan sebenarnya ke lembar kerja.
            
            # Buat DataFrame dari konfigurasi bagan untuk menunjukkan apa yang akan ditulis
            chart_specs_df = pd.DataFrame([
                {
                    'Title': chart.title,
                    'Chart Type': chart.chart_type,
                    'X Column': chart.x_column,
                    'Y Column': chart.y_column,
                    'Data Head': chart.data.head(2).to_json(orient='records') if chart.data is not None else 'N/A'
                }
                for chart in self.charts
            ])
            
            with pd.ExcelWriter(output_path, engine='xlsxwriter') as writer:
                # Tulis ringkasan data
                summary_df = pd.DataFrame([summary])
                summary_df.to_excel(writer, sheet_name='Summary', index=False)

                # Tulis spesifikasi bagan
                chart_specs_df.to_excel(writer, sheet_name='Chart Specs', index=False)

                # TODO: Di sini, Anda akan menambahkan logika untuk benar-benar membuat
                # bagan di lembar kerja Excel menggunakan `writer` objek.
                # Misalnya, `workbook = writer.book`, `worksheet = writer.sheets['Chart Specs']`,
                # lalu gunakan `xlsxwriter` API untuk menambahkan bagan berdasarkan `self.charts`.

            logger.info(f"File Excel dashboard (simulasi) berhasil ditulis ke {output_path}")
            return True
        except Exception as e:
            logger.error(f"Gagal mensimulasikan pembuatan dashboard Excel: {e}", exc_info=True)
            return False

# --- Konfigurasi Logger ---
logger = logging.getLogger(__name__)
# Pastikan logger hanya menambahkan handler sekali
if not logger.handlers:
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

# --- Fungsi Endpoint yang Direfaktor ---

async def endpoint_name(
    user: str = Form(...),
    password: str = Form(...),
    port: int = Form(8080),
    host: str = Form("localhost"),
    debug: bool = Form(False),
    dry_run: bool = Form(False),
    config_file: str | None = Form(None),
    verbose: int = Form(0),
    log_level: Literal['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] = Form('INFO'),
    timeout: float = Form(30.0),
    file: UploadFile = File(..., description="File input (Excel atau CSV) untuk analisis."),
    gemini_analysis_json: str = Form(..., description="JSON string yang berisi hasil analisis Gemini, termasuk 'suggested_viz_specs' dan 'data_summary'."),
    min_charts: int = Form(10, description="Jumlah minimum bagan yang ditargetkan untuk dibuat."),
    output_filename: str = Form("adaptive_dashboard.xlsx", description="Nama file untuk dashboard Excel yang dihasilkan. (Disimpan di sisi server)."),
) -> dict:
    
    # Konfigurasi logging berdasarkan parameter input
    logger.setLevel(getattr(logging, log_level))
    if debug:
        logger.setLevel(logging.DEBUG)
    elif verbose > 0:
        logger.setLevel(logging.DEBUG if verbose >= 2 else logging.INFO)

    logger.info(f"Memulai endpoint Dasbor Adaptif untuk user: {user} dengan log_level: {logger.level}")

    # 1. Membaca data dari UploadFile
    df_input: pd.DataFrame
    try:
        file_content = await file.read()
        
        # Tentukan tipe file dan baca data
        if file.filename.endswith(('.xls', '.xlsx')):
            df_input = pd.read_excel(io.BytesIO(file_content))
            logger.info(f"Berhasil membaca file Excel: {file.filename}")
        elif file.filename.endswith('.csv'):
            # Asumsi UTF-8, bisa ditambahkan deteksi encoding jika perlu
            df_input = pd.read_csv(io.StringIO(file_content.decode('utf-8')))
            logger.info(f"Berhasil membaca file CSV: {file.filename}")
        else:
            logger.error(f"Tipe file tidak didukung: {file.filename}. Hanya Excel atau CSV yang diizinkan.")
            raise HTTPException(status_code=400, detail="Tipe file tidak didukung. Harap unggah file Excel (.xls, .xlsx) atau CSV (.csv).")
    except Exception as e:
        logger.error(f"Gagal membaca file input '{file.filename}': {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"Gagal membaca file input: {e}")

    if df_input.empty:
        logger.warning("DataFrame input kosong setelah dibaca.")
        raise HTTPException(status_code=400, detail="File input kosong atau tidak dapat diurai menjadi DataFrame.")

    # 2. Menguraikan gemini_analysis_json
    gemini_analysis_result: Dict[str, Any]
    try:
        gemini_analysis_result = json.loads(gemini_analysis_json)
        logger.debug(f"Gemini analysis result parsed: {gemini_analysis_result.keys()}")
    except json.JSONDecodeError as e:
        logger.error(f"JSON yang tidak valid untuk hasil analisis Gemini: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"JSON tidak valid untuk hasil analisis Gemini: {e}")
    except TypeError as e:
        logger.error(f"Tipe data tidak sesuai untuk hasil analisis Gemini: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"Tipe data tidak sesuai untuk hasil analisis Gemini: {e}")
    
    # 3. Menyiapkan jalur output file sementara
    # Menggunakan direktori sementara agar file tidak mengotori sistem setelah permintaan
    with tempfile.TemporaryDirectory() as tmpdir:
        output_excel_path = f"{tmpdir}/{output_filename}"
        logger.info(f"Target pembuatan dashboard: {output_excel_path}")

        logger.info(f"Memulai visualisasi Dasbor Adaptif (Target: {min_charts} Bagan)...")
        
        visualizer = DataVisualizer()
        viz_specs = gemini_analysis_result.get('suggested_viz_specs', [])
        summary = gemini_analysis_result.get('data_summary')

        if not viz_specs or not isinstance(viz_specs, list):
            logger.warning("Spesifikasi visualisasi dari Gemini tidak ditemukan atau tidak valid. Menggunakan Fallback.")
            fallback_charts = visualizer.auto_analyze_dataframe(df_input, max_charts=min_charts)
            for config in fallback_charts:
                visualizer.add_chart(config)
            if not visualizer.charts:
                logger.warning("Tidak ada bagan yang dihasilkan dari spesifikasi Gemini atau fallback.")

        else:
            for spec in viz_specs:
                if len(visualizer.charts) >= min_charts and min_charts > 0:
                    logger.info(f"Telah mencapai jumlah bagan minimum yang ditargetkan ({min_charts}). Menghentikan pembuatan bagan dari spesifikasi Gemini.")
                    break # Hentikan jika sudah mencapai target min_charts

                try:
                    prep_func = spec.get('prep_function', 'none').lower()
                    
                    # Validasi dan konversi tipe bagan
                    chart_type_str = spec.get('chart_type', 'COLUMN').upper()
                    if not hasattr(ChartType, chart_type_str):
                        logger.warning(f"Tipe bagan tidak valid '{chart_type_str}' ditemukan dalam spesifikasi. Melewati bagan ini.")
                        continue
                    chart_type = getattr(ChartType, chart_type_str)

                    x_col, y_col = spec.get('x_column'), spec.get('y_column')
                    data_to_viz, x_col_final, y_col_final = None, x_col, y_col

                    if prep_func == 'categorical':
                        if not x_col or x_col not in df_input.columns:
                            logger.warning(f"Kolom kategorikal '{x_col}' tidak ditemukan di DataFrame input. Melewati bagan.")
                            continue
                        data_to_viz = visualizer.prepare_categorical_data(df_input, x_col)
                        x_col_final, y_col_final = 'Category', 'Count'
                    elif prep_func == 'numeric':
                        if not x_col or x_col not in df_input.columns:
                            logger.warning(f"Kolom numerik '{x_col}' tidak ditemukan di DataFrame input. Melewati bagan.")
                            continue
                        data_to_viz = visualizer.prepare_numeric_distribution(df_input, x_col, round_to=1)
                        x_col_final, y_col_final = 'Value', 'Count'
                    elif prep_func == 'aggregated':
                        group_col = spec.get('group_by_column')
                        agg_type = spec.get('aggregation_type', 'count').lower()

                        if not group_col or group_col not in df_input.columns:
                            logger.warning(f"Kolom group-by '{group_col}' tidak ditemukan di DataFrame input. Melewati bagan.")
                            continue
                        if agg_type != 'count' and (not y_col or y_col not in df_input.columns):
                             logger.warning(f"Kolom agregasi '{y_col}' tidak ditemukan untuk agregasi '{agg_type}'. Melewati bagan.")
                             continue
                        
                        # Pastikan kolom agregasi numerik jika bukan 'count'
                        if agg_type != 'count' and not pd.api.types.is_numeric_dtype(df_input[y_col]):
                            logger.warning(f"Kolom agregasi '{y_col}' bukan tipe numerik. Melewati bagan.")
                            continue

                        if agg_type == 'count':
                            data_to_viz = df_input.groupby(group_col).size().reset_index(name='Count')
                            data_to_viz.columns = ['Group', 'Value']
                        else:
                            data_to_viz = visualizer.prepare_aggregated_data(
                                df_input, group_by=group_col, agg_column=y_col, agg_func=agg_type
                            )
                        x_col_final, y_col_final = 'Group', 'Value'
                    elif prep_func == 'none':
                        if not x_col or not y_col or x_col not in df_input.columns or y_col not in df_input.columns:
                            logger.warning(f"Kolom yang diperlukan '{x_col}' atau '{y_col}' tidak ditemukan untuk prep_func 'none'. Melewati bagan.")
                            continue
                        data_to_viz = df_input[[x_col, y_col]].copy()
                    else:
                        logger.warning(f"prep_function yang tidak dikenal '{prep_func}'. Melewati bagan.")
                        continue
                    
                    if data_to_viz is None or data_to_viz.empty:
                        logger.warning(f"Data yang disiapkan untuk bagan '{spec.get('title', 'Untitled')}' kosong. Melewati bagan.")
                        continue
                    
                    visualizer.add_chart(ChartConfig(
                        chart_type=chart_type, title=spec.get('title'), data=data_to_viz,
                        x_column=x_col_final, y_column=y_col_final,
                        x_label=spec.get('x_column_label', x_col_final), 
                        y_label=spec.get('y_column_label', y_col_final),
                        sort_data=(chart_type == ChartType.BAR or chart_type == ChartType.COLUMN), # Hanya BAR/COLUMN yang disortir secara default
                        sort_ascending=(chart_type == ChartType.BAR) # BAR biasanya menurun, COLUMN menaik
                    ))
                    logger.debug(f"Bagan '{spec.get('title', 'Untitled')}' berhasil ditambahkan. Total: {len(visualizer.charts)}")
                except KeyError as e:
                    logger.error(f"Kunci yang diharapkan hilang dalam spesifikasi bagan: {e}. Melewati bagan ini.", exc_info=True)
                    continue # Lanjutkan ke spesifikasi berikutnya
                except Exception as e:
                    logger.error(f"Kesalahan tak terduga saat memproses spesifikasi bagan Gemini: {e}. Melewati bagan ini.", exc_info=True)
                    continue

        generated_chart_count = len(visualizer.charts)
        
        if dry_run:
            logger.info(f"Mode dry_run aktif. Tidak membuat file dashboard. Menghasilkan {generated_chart_count} bagan secara virtual.")
            return {
                "status": "dry_run_success",
                "message": f"Simulasi pembuatan dashboard berhasil. {generated_chart_count} bagan akan dibuat.",
                "chart_count": generated_chart_count,
                "output_filename": output_filename,
                "note": "Ini adalah hasil dry run; tidak ada file yang benar-benar dibuat."
            }

        # Jika tidak ada bagan yang dihasilkan tetapi min_charts > 0, ini adalah kegagalan
        if generated_chart_count == 0 and min_charts > 0:
            logger.error("Tidak ada bagan yang dapat dihasilkan, bahkan dengan fallback, meskipun target minimum ditentukan.")
            raise HTTPException(status_code=500, detail="Gagal menghasilkan bagan apa pun dari data dan spesifikasi yang disediakan.")

        success = visualizer.create_dashboard(
            output_excel_path, 
            'Gemini_Adaptive_Dashboard', 
            'AI-Driven Adaptive Dashboard', 
            summary
        )
        
        if success:
            logger.info(f"Dashboard berhasil dibuat dengan {generated_chart_count} bagan di {output_excel_path}")
            return {
                "status": "success",
                "message": "Dashboard berhasil dibuat.",
                "chart_count": generated_chart_count,
                "output_filename": output_filename,
                "output_filepath_on_server": output_excel_path, # Untuk referensi internal/debug
            }
        else:
            logger.error(f"Gagal membuat dasbor. {generated_chart_count} bagan disiapkan.")
            raise HTTPException(status_code=500, detail=f"Gagal membuat dasbor Excel. {generated_chart_count} bagan disiapkan tetapi tidak dapat ditulis ke {output_excel_path}.")

```

@app.post("/analyze/")
async def endpoint_name(user: str = Form(...), password: str = Form(...), port: int = Form(8080), host: str = Form("localhost"), debug: bool = Form(False), dry_run: bool = Form(False), config_file: str | None = Form(None), verbose: int = Form(0), log_level: Literal['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] = Form('INFO'), timeout: float = Form(30.0), file: UploadFile = File(...)) -> dict:
    ```python
import pandas as pd
from fastapi import Form, UploadFile, File, HTTPException
from typing import Literal, Optional
import io
import logging

# It's generally good practice to configure logging globally at application startup.
# However, for a self-contained function that takes `log_level` as a parameter,
# configuring a dedicated logger within the function, while preventing duplicate
# handlers, is a pragmatic approach for demonstration purposes.

async def endpoint_name(
    user: str = Form(...),
    password: str = Form(...),
    port: int = Form(8080),
    host: str = Form("localhost"),
    debug: bool = Form(False),
    dry_run: bool = Form(False),
    config_file: str | None = Form(None),
    verbose: int = Form(0),
    log_level: Literal['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] = Form('INFO'),
    timeout: float = Form(30.0),
    file: UploadFile = File(...)
) -> dict:
    
    # Configure logger for this specific endpoint call
    logger = logging.getLogger(__name__)
    
    # Set the logging level dynamically based on the input parameter
    numeric_level = getattr(logging, log_level.upper(), None)
    if not isinstance(numeric_level, int):
        raise HTTPException(status_code=400, detail=f"Invalid log level specified: {log_level}. Must be one of DEBUG, INFO, WARNING, ERROR, CRITICAL.")
    
    # Ensure no duplicate handlers are added if the function is called multiple times
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        # Prevent propagation to the root logger to avoid duplicate messages if a root handler exists
        logger.propagate = False 
        
    logger.setLevel(numeric_level)

    if debug:
        logger.debug(f"Request received: user={user}, host={host}:{port}, debug={debug}, dry_run={dry_run}")
        logger.debug(f"Config: config_file={config_file}, verbose={verbose}, log_level={log_level}, timeout={timeout}")
        logger.debug(f"File details: filename={file.filename}, content_type={file.content_type}, size={file.size} bytes")

    df: Optional[pd.DataFrame] = None
    try:
        # Check if the uploaded file has a filename (basic validation)
        if not file.filename:
            logger.error("No filename provided for the uploaded file.")
            raise HTTPException(status_code=400, detail="No file uploaded or filename is empty.")
            
        # Read the file contents as bytes
        contents = await file.read()
        
        # If the file is truly empty (0 bytes)
        if not contents:
            logger.warning(f"Uploaded file '{file.filename}' is empty.")
            raise HTTPException(status_code=400, detail=f"File '{file.filename}' is empty. Please upload a file with content.")

        # Determine file type based on extension for reading with pandas
        file_extension = file.filename.split('.')[-1].lower()
        
        if file_extension == 'csv':
            # Decode bytes to string for io.StringIO and pandas.read_csv
            sio = io.StringIO(contents.decode('utf-8'))
            df = pd.read_csv(sio)
            logger.info(f"Successfully read CSV file '{file.filename}'. Shape: {df.shape}")
        elif file_extension in ['xls', 'xlsx']:
            # Use io.BytesIO directly for pandas.read_excel
            bio = io.BytesIO(contents)
            df = pd.read_excel(bio)
            logger.info(f"Successfully read Excel file '{file.filename}'. Shape: {df.shape}")
        else:
            logger.error(f"Unsupported file type '{file_extension}' for file '{file.filename}'.")
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type: {file_extension}. Please upload a CSV or Excel file."
            )

        # Check if DataFrame is empty after parsing (e.g., CSV with only headers, or corrupted data)
        if df.empty:
            logger.warning(f"Uploaded file '{file.filename}' resulted in an empty DataFrame after parsing.")
            # An empty DataFrame likely means no meaningful data for chart generation, so raise an error.
            raise HTTPException(status_code=422, detail=f"The uploaded file '{file.filename}' contains no valid data after parsing, resulting in an empty dataset.")

    except UnicodeDecodeError as e:
        logger.error(f"UnicodeDecodeError while reading file '{file.filename}': {e}", exc_info=True)
        raise HTTPException(status_code=422, detail=f"Could not decode file content. Please ensure '{file.filename}' is a valid UTF-8 CSV file: {e}")
    except pd.errors.EmptyDataError as e:
        logger.error(f"Pandas EmptyDataError while reading file '{file.filename}': {e}", exc_info=True)
        raise HTTPException(status_code=422, detail=f"The uploaded file '{file.filename}' is empty or contains no parsable data: {e}")
    except pd.errors.ParserError as e:
        logger.error(f"Pandas ParserError while reading file '{file.filename}': {e}", exc_info=True)
        raise HTTPException(status_code=422, detail=f"Could not parse file content from '{file.filename}'. Please check the file format and integrity: {e}")
    except Exception as e:
        logger.critical(f"An unexpected critical error occurred during file processing for '{file.filename}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An unexpected internal server error occurred while processing the file: {e}")

    # --- Simulate the _prepare_charts() logic ---
    # The original __init__ called self._prepare_charts().
    # In this refactored endpoint, we'll simulate this step.
    # If dry_run is true, we skip the actual "chart preparation".
    
    chart_preparation_details = {}
    if dry_run:
        logger.info("Dry run enabled. Skipping actual chart preparation logic.")
        chart_preparation_details = {
            "status": "Dry run: Chart preparation skipped.",
            "message": "Data was successfully parsed but chart generation was not performed due to dry_run mode."
        }
    else:
        logger.info(f"Initiating chart preparation for data from '{file.filename}'...")
        # This is where the core business logic from _prepare_charts() would be implemented.
        # Example: Call another function, a service, or an instance method.
        # e.g., chart_output = YourChartService.generate_charts(df, config_file=config_file, verbose=verbose)
        
        # For this exercise, we return some placeholder information.
        chart_preparation_details = {
            "status": "Charts preparation initiated.",
            "message": "Data has been processed and chart generation is underway or ready.",
            "rows_processed": len(df),
            "columns_processed": len(df.columns),
            "first_n_rows_preview": df.head(5).to_dict(orient='records'), # Provide a preview
            # In a real scenario, this might include URLs to generated charts, a job ID, etc.
            "chart_links": [], 
            "generation_config_used": {
                "config_file": config_file,
                "verbose_level": verbose
            }
        }
        logger.info("Chart preparation simulation complete.")

    # Return the results as a Python dictionary
    return {
        "status": "success",
        "message": f"File '{file.filename}' processed successfully.",
        "request_metadata": {
            "user": user,
            "host": host,
            "port": port,
            "debug_mode": debug,
            "dry_run_mode": dry_run,
            "log_level_set": log_level,
            "timeout_seconds": timeout
        },
        "file_uploaded_details": {
            "filename": file.filename,
            "content_type": file.content_type,
            "size_bytes": file.size
        },
        "data_summary": {
            "rows": len(df),
            "columns": len(df.columns),
            "is_empty_after_parse": df.empty,
            "column_names": df.columns.tolist()
        },
        "chart_preparation_output": chart_preparation_details
    }
```


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
