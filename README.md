AST-LLM CLI-to-API Migrator adalah kerangka kerja yang secara otomatis mengonversi skrip CLI Python (berbasis argparse) menjadi layanan web FastAPI yang modern dan production-ready.
Fitur Utama

✅ Analisis Kode Berbasis AST - Parsing struktural yang akurat
✅ Smart Chunking Semantik - Pengelompokan logis komponen kode
✅ Transformasi CLI ke API - Konversi argumen argparse ke parameter FastAPI
✅ Adaptasi Logika Bisnis - Refactoring otomatis fungsi inti
✅ Error Handling Modern - Konversi sys.exit() ke HTTPException

# Quick Start
```
python main_cli.py --input <path_to_cli_script.py> --output <output_api_file.py>
```

# Advanced Usage
```
python .\main.py --input .\io_files\input\data_analyzer.py --output .\io_files\output\data_analyzer_api.py --use-llm --provider custom --custom-endpoint "http://localhost:8017/v1/generate" --api-key "your_api_key_here"
```