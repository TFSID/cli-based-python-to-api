import argparse
import sys
import os
from ast_parser import parse_script
from llm_reasoner import (
    call_llm_for_signature,
    call_llm_for_refactor,
    generate_endpoint_code
)
from code_synthesizer import synthesize_api_code
from llm_client import LLMClient, LLMProvider


def main():
    parser = argparse.ArgumentParser(
        description='AST-LLM CLI-to-API Migrator: Refactor CLI scripts to FastAPI services'
    )
    parser.add_argument(
        '--input',
        required=True,
        help='Path to input CLI Python script'
    )
    parser.add_argument(
        '--output',
        required=True,
        help='Path to output FastAPI Python script'
    )
    parser.add_argument(
        '--use-llm',
        action='store_true',
        help='Use real LLM API instead of mock responses'
    )
    parser.add_argument(
        '--provider',
        choices=['gemini', 'openai', 'anthropic', 'custom'],
        default='gemini',
        help='LLM provider to use (default: gemini)'
    )
    parser.add_argument(
        '--api-key',
        help='API key for LLM provider (or set via environment variable)'
    )
    parser.add_argument(
        '--model',
        help='Specific model name to use'
    )
    parser.add_argument(
        '--custom-endpoint',
        help='Custom LLM endpoint URL (for custom provider)'
    )
    
    args = parser.parse_args()
    
    llm_client = None
    if args.use_llm:
        print(f"[INFO] Using real LLM API: {args.provider}")
        try:
            provider_map = {
                'gemini': LLMProvider.GEMINI,
                'openai': LLMProvider.OPENAI,
                'anthropic': LLMProvider.ANTHROPIC,
                'custom': LLMProvider.CUSTOM
            }
            
            llm_client = LLMClient(
                provider=provider_map[args.provider],
                api_key=args.api_key,
                model_name=args.model,
                custom_endpoint=args.custom_endpoint
            )
        except Exception as e:
            print(f"[ERROR] Failed to initialize LLM client: {e}", file=sys.stderr)
            print("[INFO] Falling back to mock mode", file=sys.stderr)
            llm_client = None
    else:
        print("[INFO] Using mock LLM responses (use --use-llm for real API calls)")
    
    print(f"[1/5] Parsing input script: {args.input}")
    try:
        chunks = parse_script(args.input)
    except Exception as e:
        print(f"Error parsing script: {e}", file=sys.stderr)
        sys.exit(1)
    
    print(f"[2/5] Analyzing CLI structure...")
    print(f"  - Found {len(chunks['imports'])} imports")
    print(f"  - Found {len(chunks['classes'])} classes")
    print(f"  - Found {len(chunks['functions'])} functions")
    print(f"  - Found {len(chunks['main_logic'])} main logic blocks")
    
    print(f"[3/5] Generating endpoint signature via LLM reasoning...")
    try:
        endpoint_signature = call_llm_for_signature(
            chunks['main_logic'],
            llm_client=llm_client,
            use_mock=not args.use_llm
        )
        print(f"  - Generated signature: {endpoint_signature.strip()}")
    except Exception as e:
        print(f"[ERROR] Failed to generate signature: {e}", file=sys.stderr)
        sys.exit(1)
    
    print(f"[4/5] Refactoring business logic functions...")
    refactored_logic = {}
    
    for func_name, func_code in chunks['functions'].items():
        print(f"  - Processing function: {func_name}")
        try:
            refactored_code = call_llm_for_refactor(
                endpoint_signature,
                func_name,
                func_code,
                llm_client=llm_client,
                use_mock=not args.use_llm
            )
            refactored_logic[func_name] = refactored_code
        except Exception as e:
            print(f"[WARNING] Failed to refactor {func_name}: {e}", file=sys.stderr)
            refactored_logic[func_name] = func_code
    
    endpoint_code = generate_endpoint_code(
        endpoint_signature,
        list(refactored_logic.values())[0] if refactored_logic else "pass"
    )
    
    endpoint_details = {
        'endpoint_code': endpoint_code,
        'signature': endpoint_signature
    }
    
    print(f"[5/5] Synthesizing final FastAPI code...")
    api_code = synthesize_api_code(chunks, refactored_logic, endpoint_details)
    
    try:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(api_code)
        print(f"\n✓ Successfully generated FastAPI application: {args.output}")
        print(f"\nTo run the generated API:")
        print(f"  python {args.output}")
        print(f"  or")
        print(f"  uvicorn {args.output.replace('.py', '')}:app --reload")
    except Exception as e:
        print(f"Error writing output file: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
