import ast
from typing import Dict, List, Any


class CLIScriptVisitor(ast.NodeVisitor):
    def __init__(self, source_code: str):
        self.source_code = source_code
        self.source_lines = source_code.splitlines()
        self.imports = []
        self.classes = {}
        self.functions = {}
        self.main_logic = []
        self.in_main_block = False

    def visit_Import(self, node: ast.Import):
        if not self.in_main_block:
            import_str = self._get_source(node)
            if import_str:
                self.imports.append(import_str)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        if not self.in_main_block:
            import_str = self._get_source(node)
            if import_str:
                self.imports.append(import_str)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef):
        if not self.in_main_block:
            class_code = self._get_source(node)
            if class_code:
                self.classes[node.name] = class_code
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef):
        if not self.in_main_block:
            func_code = self._get_source(node)
            if func_code:
                self.functions[node.name] = func_code
        self.generic_visit(node)

    def visit_If(self, node: ast.If):
        if self._is_main_block(node):
            self.in_main_block = True
            for item in node.body:
                chunk = self._get_source(item)
                if chunk:
                    self.main_logic.append(chunk)
            self.in_main_block = False
        else:
            self.generic_visit(node)

    def _is_main_block(self, node: ast.If) -> bool:
        if isinstance(node.test, ast.Compare):
            if isinstance(node.test.left, ast.Name) and node.test.left.id == '__name__':
                if len(node.test.ops) > 0 and isinstance(node.test.ops[0], ast.Eq):
                    if len(node.test.comparators) > 0:
                        comp = node.test.comparators[0]
                        if isinstance(comp, ast.Constant) and comp.value == '__main__':
                            return True
        return False

    def _get_source(self, node: ast.AST) -> str:
        try:
            return ast.get_source_segment(self.source_code, node)
        except:
            try:
                if hasattr(node, 'lineno') and hasattr(node, 'end_lineno'):
                    start_line = node.lineno - 1
                    end_line = node.end_lineno
                    if start_line >= 0 and end_line <= len(self.source_lines):
                        return '\n'.join(self.source_lines[start_line:end_line])
            except:
                pass
        return ''


def parse_script(filepath: str) -> Dict[str, Any]:
    with open(filepath, 'r', encoding='utf-8') as f:
        source_code = f.read()
    
    tree = ast.parse(source_code)
    visitor = CLIScriptVisitor(source_code)
    visitor.visit(tree)
    
    chunks = {
        'imports': visitor.imports,
        'classes': visitor.classes,
        'functions': visitor.functions,
        'main_logic': visitor.main_logic
    }
    
    return chunks