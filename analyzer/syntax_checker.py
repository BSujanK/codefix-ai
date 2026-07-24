import ast

def check_syntax(code: str) -> list[dict]:
    try:
        ast.parse(code)
    except SyntaxError as exc:
        return [{"type": "SyntaxError", "line": exc.lineno or "-", "message": exc.msg}]
    except Exception as exc:
        return [{"type": "ParseError", "line": "-", "message": str(exc)}]
    return []
