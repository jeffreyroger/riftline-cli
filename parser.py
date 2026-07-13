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


@dataclass(frozen=True)
class AttributeCall:
    """An attribute/method call, e.g. self.foo() or obj.bar()."""

    base: str                    # base expression, e.g. "self" or "obj"
    attr: str                    # attribute name being called, e.g. "foo"
    enclosing_class: str | None  # class where call occurs, e.g. "Widget" or None
    enclosing_method: str | None # method where call occurs, e.g. "render" or None


@dataclass
class FunctionInfo:
    """One function or method definition found in a file."""

    name: str                                  # e.g. "foo" or "Widget.render"
    lineno: int
    end_lineno: int
    calls: list[str] = field(default_factory=list)  # raw callee names found in the body
    attribute_calls: list[AttributeCall] = field(default_factory=list)


@dataclass(frozen=True)
class ClassInfo:
    """Information about a class definition, including its bases."""

    name: str                  # e.g. "Widget" or "Outer.Inner"
    bases: list[str]           # declared base class names, e.g. ["Animal"]


@dataclass
class ParsedFile:
    path: Path
    imports: dict[str, ImportBinding]   # local_name -> binding
    symbols: set[str]                   # names defined at top level (functions, classes)
    functions: list[FunctionInfo]       # every function/method + its raw calls
    classes: list[ClassInfo] = field(default_factory=list)


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


def _callee_attribute(call: ast.Call) -> tuple[str, str] | None:
    """If call is an attribute call (e.g. self.foo()), return (base, attr).
    Otherwise return None.
    """
    if isinstance(call.func, ast.Attribute):
        base = ast.unparse(call.func.value)
        return base, call.func.attr
    return None


def extract_functions(tree: ast.Module) -> list[FunctionInfo]:
    functions: list[FunctionInfo] = []

    # Map each Call node to its innermost enclosing (class, method) context.
    # If not inside a class, both are None.
    context_map: dict[ast.Call, tuple[str | None, str | None]] = {}

    def visit(node, current_class: str | None, current_method: str | None):
        if isinstance(node, ast.ClassDef):
            new_class = f"{current_class}.{node.name}" if current_class else node.name
            for child in node.body:
                visit(child, new_class, None)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            new_method = f"{current_method}.{node.name}" if current_method else node.name
            for decorator in node.decorator_list:
                visit(decorator, current_class, current_method)
            for default in node.args.defaults + node.args.kw_defaults:
                if default is not None:
                    visit(default, current_class, current_method)
            if node.returns is not None:
                visit(node.returns, current_class, current_method)
            for child in node.body:
                visit(child, current_class, new_method)
        else:
            if isinstance(node, ast.Call):
                if current_class:
                    context_map[node] = (current_class, current_method)
                else:
                    context_map[node] = (None, None)
            for child in ast.iter_child_nodes(node):
                visit(child, current_class, current_method)

    for node in tree.body:
        visit(node, None, None)

    def walk_body(node, prefix: str = ""):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualname = f"{prefix}{child.name}"
                calls = []
                attribute_calls = []
                for sub in ast.walk(child):
                    if isinstance(sub, ast.Call):
                        name = _callee_name(sub)
                        if name:
                            calls.append(name)
                        attr_info = _callee_attribute(sub)
                        if attr_info:
                            base, attr = attr_info
                            enc_class, enc_method = context_map.get(sub, (None, None))
                            attribute_calls.append(
                                AttributeCall(
                                    base=base,
                                    attr=attr,
                                    enclosing_class=enc_class,
                                    enclosing_method=enc_method,
                                )
                            )
                functions.append(
                    FunctionInfo(
                        name=qualname,
                        lineno=child.lineno,
                        end_lineno=getattr(child, "end_lineno", child.lineno),
                        calls=calls,
                        attribute_calls=attribute_calls,
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


def extract_classes(tree: ast.Module) -> list[ClassInfo]:
    classes: list[ClassInfo] = []

    def walk_body(node, prefix: str = ""):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                qualname = f"{prefix}{child.name}"
                bases = [ast.unparse(b) for b in child.bases]
                classes.append(ClassInfo(name=qualname, bases=bases))
                walk_body(child, prefix=f"{qualname}.")
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Functions can contain nested classes, walk them too
                walk_body(child, prefix=f"{prefix}{child.name}.")

    walk_body(tree)
    return classes


def parse(path: Path) -> ParsedFile:
    tree = parse_file(path)
    return ParsedFile(
        path=path,
        imports=extract_imports(tree),
        symbols=extract_symbols(tree),
        functions=extract_functions(tree),
        classes=extract_classes(tree),
    )
