"""
Parsing layer: walks a Python file's AST and extracts
  - import bindings (the file's "cheat sheet" of local name -> real origin)
  - top-level symbols the file defines (functions, classes)
  - every function/method + the raw names it calls

NOTE ON TREE-SITTER: the original plan used tree-sitter for multi-language
support. This sandbox has no network access to install it, so V1 here uses
Python's built-in `ast` module instead -- which is actually a better fit for
a Python-only V1 (real semantic node types, no manual grammar-node-name
matching). Swapping in tree-sitter later only touches this file; every
downstream module (resolver.py, graph.py) depends only on the dataclasses
defined here, not on how they were produced.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ImportBinding:
    """One row of a file's cheat sheet: what a local name actually refers to."""

    local_name: str            # the name used inside this file, e.g. "h"
    module: str | None         # module it comes from, e.g. "utils" (None for "from . import x")
    imported_name: str | None  # specific symbol imported, e.g. "helper" (None for bare "import os")
    level: int                 # leading dots for relative imports (0 = absolute)

    @property
    def is_relative(self) -> bool:
        return self.level > 0


@dataclass
class FunctionInfo:
    """One function or method definition found in a file."""

    name: str                                  # e.g. "foo" or "Widget.render"
    lineno: int
    end_lineno: int
    calls: list[str] = field(default_factory=list)  # raw callee names found in the body


@dataclass
class ParsedFile:
    path: Path
    imports: dict[str, ImportBinding]   # local_name -> binding
    symbols: set[str]                   # names defined at top level (functions, classes)
    functions: list[FunctionInfo]       # every function/method + its raw calls


def parse_file(path: Path) -> ast.Module:
    source = path.read_text(encoding="utf-8")
    return ast.parse(source, filename=str(path))


def extract_imports(tree: ast.Module) -> dict[str, ImportBinding]:
    bindings: dict[str, ImportBinding] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".")[0]
                bindings[local] = ImportBinding(
                    local_name=local, module=alias.name, imported_name=None, level=0
                )
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                local = alias.asname or alias.name
                bindings[local] = ImportBinding(
                    local_name=local,
                    module=node.module,
                    imported_name=alias.name,
                    level=node.level,
                )
    return bindings


def _callee_name(call: ast.Call) -> str | None:
    """Raw text of what's being called. Bare names only for V1
    (`foo(x)` -> "foo"); attribute calls (`h.process(x)`) return None and
    are left unresolved -- verifying an attribute exists on an imported
    symbol needs type inference, out of scope for V1 (see SRS limitations).
    """
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    return None


def extract_functions(tree: ast.Module) -> list[FunctionInfo]:
    functions: list[FunctionInfo] = []

    def walk_body(node, prefix: str = ""):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualname = f"{prefix}{child.name}"
                calls = []
                for sub in ast.walk(child):
                    if isinstance(sub, ast.Call):
                        name = _callee_name(sub)
                        if name:
                            calls.append(name)
                functions.append(
                    FunctionInfo(
                        name=qualname,
                        lineno=child.lineno,
                        end_lineno=getattr(child, "end_lineno", child.lineno),
                        calls=calls,
                    )
                )
                walk_body(child, prefix=f"{qualname}.")
            elif isinstance(child, ast.ClassDef):
                walk_body(child, prefix=f"{prefix}{child.name}.")

    walk_body(tree)
    return functions


def extract_symbols(tree: ast.Module) -> set[str]:
    """Top-level names this file defines -- what a bare `import module` or
    `from module import name` could actually resolve to."""
    symbols: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.add(node.name)
    return symbols


def parse(path: Path) -> ParsedFile:
    tree = parse_file(path)
    return ParsedFile(
        path=path,
        imports=extract_imports(tree),
        symbols=extract_symbols(tree),
        functions=extract_functions(tree),
    )
