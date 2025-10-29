from typing import Dict, List, Any


def synthesize_api_code(original_chunks: Dict[str, Any], refactored_logic: Dict[str, str], endpoint_details: Dict[str, str]) -> str:
    api_code_parts = []
    
    api_imports = _generate_api_imports(original_chunks['imports'])
    api_code_parts.append(api_imports)
    api_code_parts.append('\n\n')
    
    api_code_parts.append('app = FastAPI()\n\n')
    
    if original_chunks['classes']:
        for class_name, class_code in original_chunks['classes'].items():
            api_code_parts.append(class_code)
            api_code_parts.append('\n\n')
    
    for func_name, func_code in refactored_logic.items():
        api_code_parts.append(func_code)
        api_code_parts.append('\n\n')
    
    if 'endpoint_code' in endpoint_details:
        api_code_parts.append(endpoint_details['endpoint_code'])
        api_code_parts.append('\n\n')
    
    uvicorn_block = '''if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
'''
    api_code_parts.append(uvicorn_block)
    
    return ''.join(api_code_parts)


def _generate_api_imports(original_imports: List[str]) -> str:
    filtered_imports = []
    
    skip_modules = {'argparse', 'sys'}
    
    for imp in original_imports:
        should_skip = False
        for skip_mod in skip_modules:
            if f'import {skip_mod}' in imp or f'from {skip_mod}' in imp:
                should_skip = True
                break
        
        if not should_skip:
            filtered_imports.append(imp)
    
    api_specific_imports = [
        'from fastapi import FastAPI, File, Form, UploadFile, HTTPException',
        'from typing import Optional',
        'import io'
    ]
    
    all_imports = api_specific_imports + filtered_imports
    
    return '\n'.join(all_imports)


def clean_function_code(function_code: str) -> str:
    lines = function_code.split('\n')
    cleaned_lines = []
    
    for line in lines:
        if 'print(' in line and 'sys.stderr' not in line:
            continue
        if 'sys.exit' in line:
            continue
        if line.strip().startswith('#'):
            continue
        
        cleaned_lines.append(line)
    
    return '\n'.join(cleaned_lines)