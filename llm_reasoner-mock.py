from typing import List


def get_endpoint_signature_prompt(main_logic_chunks: List[str]) -> str:
    main_logic_text = '\n'.join(main_logic_chunks)
    
    prompt = f"""Anda adalah ahli refactoring API. Berikut adalah logika argparse dari skrip CLI:

{main_logic_text}

Tugas Anda: Rancang signature fungsi endpoint FastAPI yang ideal. Asumsikan argumen file adalah unggahan file (UploadFile). Gunakan Form untuk parameter lainnya.

Hasilkan signature dalam format:
async def endpoint_name(param1: Type = Form(...), param2: Type = Form(...), file: UploadFile = File(...)) -> dict:
"""
    
    return prompt


def get_logic_refactor_prompt(endpoint_signature: str, function_name: str, business_logic_chunk: str) -> str:
    prompt = f"""Bagus. Signature endpoint Anda adalah:
{endpoint_signature}

Sekarang, berikut adalah fungsi logika bisnis inti ({function_name}):

{business_logic_chunk}

Tugas Anda: Tulis ulang (refactor) seluruh isi fungsi ini agar:
1. Sesuai dengan signature endpoint baru
2. Membaca data dari file.read() (bytes), bukan filepath (gunakan io.StringIO atau io.BytesIO jika perlu)
3. Mengembalikan (return) hasil sebagai dictionary Python, bukan print
4. Mengganti print ke stderr atau sys.exit dengan raise HTTPException dari FastAPI

Hasilkan kode fungsi lengkap yang telah direfaktor.
"""
    
    return prompt


def mock_llm_response(prompt: str) -> str:
    if "Rancang signature fungsi endpoint" in prompt:
        return """async def analyze_data_endpoint(file: UploadFile = File(...), threshold: int = Form(10)) -> dict:"""
    
    elif "Tulis ulang (refactor) seluruh isi fungsi" in prompt:
        return """async def analyze_data_logic(file: UploadFile, threshold: int) -> dict:
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
        raise HTTPException(status_code=400, detail=f"Error processing file: {str(e)}")"""
    
    else:
        return """def placeholder_function():
    return {"status": "generated"}"""


def generate_endpoint_code(signature: str, logic_code: str) -> str:
    endpoint_decorator = '@app.post("/analyze/")'
    
    full_endpoint = f"""{endpoint_decorator}
{signature}
    {logic_code.strip()}
"""
    
    return full_endpoint