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

async def analyze_data_logic(file: UploadFile, threshold: int) -> dict:
    try:
        contents = await file.read()
        from io import StringIO
        import pandas as pd
        
        df = pd.read_csv(StringIO(contents.decode('utf-8')))
        
        result = df[df['value'] > threshold].to_dict(orient='records')
        
        return {
            "status": "success",
            "data": result,
            "count": len(result)
        }
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Error processing file: {str(e)}")

async def analyze_data_logic(file: UploadFile, threshold: int) -> dict:
    try:
        contents = await file.read()
        from io import StringIO
        import pandas as pd
        
        df = pd.read_csv(StringIO(contents.decode('utf-8')))
        
        result = df[df['value'] > threshold].to_dict(orient='records')
        
        return {
            "status": "success",
            "data": result,
            "count": len(result)
        }
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Error processing file: {str(e)}")

async def analyze_data_logic(file: UploadFile, threshold: int) -> dict:
    try:
        contents = await file.read()
        from io import StringIO
        import pandas as pd
        
        df = pd.read_csv(StringIO(contents.decode('utf-8')))
        
        result = df[df['value'] > threshold].to_dict(orient='records')
        
        return {
            "status": "success",
            "data": result,
            "count": len(result)
        }
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Error processing file: {str(e)}")

async def analyze_data_logic(file: UploadFile, threshold: int) -> dict:
    try:
        contents = await file.read()
        from io import StringIO
        import pandas as pd
        
        df = pd.read_csv(StringIO(contents.decode('utf-8')))
        
        result = df[df['value'] > threshold].to_dict(orient='records')
        
        return {
            "status": "success",
            "data": result,
            "count": len(result)
        }
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Error processing file: {str(e)}")

async def analyze_data_logic(file: UploadFile, threshold: int) -> dict:
    try:
        contents = await file.read()
        from io import StringIO
        import pandas as pd
        
        df = pd.read_csv(StringIO(contents.decode('utf-8')))
        
        result = df[df['value'] > threshold].to_dict(orient='records')
        
        return {
            "status": "success",
            "data": result,
            "count": len(result)
        }
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Error processing file: {str(e)}")

async def analyze_data_logic(file: UploadFile, threshold: int) -> dict:
    try:
        contents = await file.read()
        from io import StringIO
        import pandas as pd
        
        df = pd.read_csv(StringIO(contents.decode('utf-8')))
        
        result = df[df['value'] > threshold].to_dict(orient='records')
        
        return {
            "status": "success",
            "data": result,
            "count": len(result)
        }
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Error processing file: {str(e)}")

async def analyze_data_logic(file: UploadFile, threshold: int) -> dict:
    try:
        contents = await file.read()
        from io import StringIO
        import pandas as pd
        
        df = pd.read_csv(StringIO(contents.decode('utf-8')))
        
        result = df[df['value'] > threshold].to_dict(orient='records')
        
        return {
            "status": "success",
            "data": result,
            "count": len(result)
        }
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Error processing file: {str(e)}")

async def analyze_data_logic(file: UploadFile, threshold: int) -> dict:
    try:
        contents = await file.read()
        from io import StringIO
        import pandas as pd
        
        df = pd.read_csv(StringIO(contents.decode('utf-8')))
        
        result = df[df['value'] > threshold].to_dict(orient='records')
        
        return {
            "status": "success",
            "data": result,
            "count": len(result)
        }
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Error processing file: {str(e)}")

async def analyze_data_logic(file: UploadFile, threshold: int) -> dict:
    try:
        contents = await file.read()
        from io import StringIO
        import pandas as pd
        
        df = pd.read_csv(StringIO(contents.decode('utf-8')))
        
        result = df[df['value'] > threshold].to_dict(orient='records')
        
        return {
            "status": "success",
            "data": result,
            "count": len(result)
        }
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Error processing file: {str(e)}")

async def analyze_data_logic(file: UploadFile, threshold: int) -> dict:
    try:
        contents = await file.read()
        from io import StringIO
        import pandas as pd
        
        df = pd.read_csv(StringIO(contents.decode('utf-8')))
        
        result = df[df['value'] > threshold].to_dict(orient='records')
        
        return {
            "status": "success",
            "data": result,
            "count": len(result)
        }
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Error processing file: {str(e)}")

async def analyze_data_logic(file: UploadFile, threshold: int) -> dict:
    try:
        contents = await file.read()
        from io import StringIO
        import pandas as pd
        
        df = pd.read_csv(StringIO(contents.decode('utf-8')))
        
        result = df[df['value'] > threshold].to_dict(orient='records')
        
        return {
            "status": "success",
            "data": result,
            "count": len(result)
        }
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Error processing file: {str(e)}")

async def analyze_data_logic(file: UploadFile, threshold: int) -> dict:
    try:
        contents = await file.read()
        from io import StringIO
        import pandas as pd
        
        df = pd.read_csv(StringIO(contents.decode('utf-8')))
        
        result = df[df['value'] > threshold].to_dict(orient='records')
        
        return {
            "status": "success",
            "data": result,
            "count": len(result)
        }
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Error processing file: {str(e)}")

async def analyze_data_logic(file: UploadFile, threshold: int) -> dict:
    try:
        contents = await file.read()
        from io import StringIO
        import pandas as pd
        
        df = pd.read_csv(StringIO(contents.decode('utf-8')))
        
        result = df[df['value'] > threshold].to_dict(orient='records')
        
        return {
            "status": "success",
            "data": result,
            "count": len(result)
        }
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Error processing file: {str(e)}")

async def analyze_data_logic(file: UploadFile, threshold: int) -> dict:
    try:
        contents = await file.read()
        from io import StringIO
        import pandas as pd
        
        df = pd.read_csv(StringIO(contents.decode('utf-8')))
        
        result = df[df['value'] > threshold].to_dict(orient='records')
        
        return {
            "status": "success",
            "data": result,
            "count": len(result)
        }
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Error processing file: {str(e)}")

@app.post("/analyze/")
async def analyze_data_endpoint(file: UploadFile = File(...), threshold: int = Form(10)) -> dict:
    async def analyze_data_logic(file: UploadFile, threshold: int) -> dict:
    try:
        contents = await file.read()
        from io import StringIO
        import pandas as pd
        
        df = pd.read_csv(StringIO(contents.decode('utf-8')))
        
        result = df[df['value'] > threshold].to_dict(orient='records')
        
        return {
            "status": "success",
            "data": result,
            "count": len(result)
        }
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Error processing file: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
