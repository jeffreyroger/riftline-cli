"""
Resolution layer: turns raw call names + a file's import cheat-sheet into
fully-qualified, cross-file references -- resolved with confidence, or
explicitly flagged unresolved. Never guesses.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .parser import ParsedFile


def module_name_for_file(root: Path, path: Path) -> str:
    """repo_root/mini_pkg/core.py -> 'mini_pkg.core'"""
    rel = path.relative_to(root).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def resolve_relative_module(
    current_module: str, level: int, module: str | None, is_package: bool = False
) -> str:
    """Resolve a relative import target to an absolute dotted module name.

    current_module: dotted module doing the importing, e.g. "mini_pkg.main"
    level: number of leading dots (1 = same package, 2 = parent package, ...)
    module: text after the dots, may be None (e.g. "from . import x")
    is_package: True if current_module represents an __init__.py package module.
    """
    parts = current_module.split(".")
    # For a package module (__init__.py), current_module is already the package.
    # So level=1 stays in current_module, level=2 goes up one level, etc.
    # For a normal module, level=1 goes up to the parent.
    up_count = level - 1 if is_package else level
    base = parts[: len(parts) - up_count] if up_count > 0 else parts
    if module:
        base = base + module.split(".")
    return ".".join(base)


@dataclass(frozen=True)
class ResolvedCall:
    caller: str        # fully-qualified caller, e.g. "mini_pkg.main.foo"
    callee: str         # fully-qualified callee, or "unknown:<name>" if unresolved
    confidence: str      # "resolved" | "unresolved"
    reason: str | None = None


def resolve_calls_for_file(
    parsed: ParsedFile,
    current_module: str,
    all_symbols: dict[str, set[str]],   # module_name -> set of symbols it defines
    class_method_table: dict[str, ClassMethods] | None = None,
    all_parsed: "dict[str, ParsedFile] | None" = None,
) -> list[ResolvedCall]:
    """Chain this file's import table with every other file's own symbol
    table to turn each raw call name into a real graph edge.

    all_parsed: the full module->ParsedFile mapping for the whole scan,
    used to follow re-export chains in __init__.py files.  When None
    (e.g. in isolated unit tests), re-export resolution is skipped and
    behavior is identical to before Phase C.
    """
    results: list[ResolvedCall] = []
    if class_method_table is None:
        class_method_table = build_class_method_table(parsed)

    for fn in parsed.functions:
        caller_fqn = f"{current_module}.{fn.name}"

        # 1. Resolve bare name calls
        for raw_name in fn.calls:
            callee, confidence = _resolve_one(raw_name, parsed, current_module, all_symbols, all_parsed)
            results.append(ResolvedCall(caller=caller_fqn, callee=callee, confidence=confidence))

        # 2. Resolve attribute/method calls
        for attr_call in fn.attribute_calls:
            resolved = False
            if attr_call.base == "self" and attr_call.enclosing_class is not None:
                fq_class = f"{current_module}.{attr_call.enclosing_class}"
                resolved_callee = _find_method_in_hierarchy(fq_class, attr_call.attr, class_method_table)
                if resolved_callee is not None:
                    results.append(ResolvedCall(
                        caller=caller_fqn,
                        callee=resolved_callee,
                        confidence="resolved",
                        reason=None
                    ))
                    resolved = True

            if not resolved:
                if attr_call.base != "self":
                    reason = "dynamic attribute target, not statically resolvable"
                else:
                    reason = "method not defined on class X or its base classes"
                callee = f"unknown:{attr_call.base}.{attr_call.attr} ({reason})"
                results.append(ResolvedCall(
                    caller=caller_fqn,
                    callee=callee,
                    confidence="unresolved",
                    reason=reason
                ))

    return results


def _resolve_one(
    raw_name: str,
    parsed: ParsedFile,
    current_module: str,
    all_symbols: dict[str, set[str]],
    all_parsed: "dict[str, ParsedFile] | None" = None,
) -> tuple[str, str]:
    # Case 1: name refers to something imported from elsewhere.
    binding = parsed.imports.get(raw_name)
    if binding is not None:
        if binding.is_relative:
            is_pkg = (parsed.path.name == "__init__.py")
            target_module = resolve_relative_module(
                current_module, binding.level, binding.module, is_package=is_pkg
            )
        else:
            target_module = binding.module or raw_name

        target_symbol = binding.imported_name or raw_name
        target_symbols = all_symbols.get(target_module)
        if target_symbols is not None and target_symbol in target_symbols:
            return f"{target_module}.{target_symbol}", "resolved"

        # Direct symbol look-up failed.  Before giving up, check whether
        # the target module's __init__.py re-exports target_symbol from a
        # deeper submodule (e.g. ``from mypkg import Foo`` where Foo is
        # re-exported by mypkg/__init__.py via ``from .sub import Foo``).
        if all_parsed is not None:
            result = _resolve_through_reexports(
                target_module, target_symbol, all_parsed, all_symbols
            )
            if result is not None:
                return result

        # imported, but we can't verify the destination actually defines it
        # (file not part of this scan, third-party package, or genuinely missing)
        return f"unknown:{raw_name}", "unresolved"

    # Case 2: name is defined right here in the same file.
    if raw_name in parsed.symbols:
        return f"{current_module}.{raw_name}", "resolved"

    # Case 3: genuinely unknown -- third-party call, builtin, typo, or a
    # name defined somewhere we haven't parsed. Flag it, never guess.
    return f"unknown:{raw_name}", "unresolved"


def _resolve_through_reexports(
    target_module: str,
    target_symbol: str,
    all_parsed: "dict[str, ParsedFile]",
    all_symbols: dict[str, set[str]],
    visited: set[str] | None = None,
) -> tuple[str, str] | None:
    """Follow re-export chains in __init__.py files to find the true defining module.

    When a caller imports a name from a package (e.g. ``from mypkg import Foo``)
    and Foo is not defined in mypkg itself but is re-exported from a submodule
    via ``mypkg/__init__.py``, this function follows that chain to the actual
    defining module and returns a resolved FQN.

    Returns ``(fqn, "resolved")`` if the chain resolves fully, or ``None`` if it
    cannot be followed (module not scanned, star import encountered, cycle
    detected, or chain broken at any hop).  Callers treat ``None`` as "keep the
    existing unresolved result" -- never guess.
    """
    if visited is None:
        visited = set()

    # Cycle guard: prevent infinite loops on pathological circular re-exports.
    visit_key = f"{target_module}:{target_symbol}"
    if visit_key in visited:
        return None  # cycle detected; leave the edge unresolved
    visited.add(visit_key)

    parsed = all_parsed.get(target_module)
    if parsed is None:
        return None  # module not part of this scan; cannot follow chain

    # Search the re-export table of target_module (populated only for __init__.py).
    for reexport in parsed.reexports:
        if reexport.local_name != target_symbol:
            continue
        if reexport.is_star:
            # Star imports cannot be resolved statically -- never guess.
            return None

        # Compute the absolute origin module from the relative import.
        # Since this re-export entry was declared in target_module's __init__.py,
        # target_module is a package.
        origin_module = resolve_relative_module(
            target_module, reexport.level, reexport.origin_module, is_package=True
        )
        origin_name = reexport.origin_name

        # Base case: origin_module directly defines origin_name.
        origin_symbols = all_symbols.get(origin_module)
        if origin_symbols is not None and origin_name in origin_symbols:
            return f"{origin_module}.{origin_name}", "resolved"

        # Recursive case: origin_module may itself re-export origin_name
        # (e.g. a subpackage __init__.py re-exporting from a deeper submodule).
        # Passes 'visited' so cycles across multiple hops are also caught.
        result = _resolve_through_reexports(
            origin_module, origin_name, all_parsed, all_symbols, visited
        )
        if result is not None:
            return result

        # This re-export entry exists but its chain is broken at this hop.
        # Do not try further re-export entries for the same symbol -- there
        # should only ever be one, and trying others would be guessing.
        return None

    # No re-export entry for target_symbol in target_module.
    return None


@dataclass
class ClassMethods:
    methods: set[str] = field(default_factory=set)
    bases: list[str] = field(default_factory=list)


def _resolve_base_fqn(base_name: str, parsed: ParsedFile, current_module: str) -> str:
    """Resolve a base class name used in a file to its fully-qualified name."""
    if "." in base_name:
        first_part = base_name.split(".")[0]
        binding = parsed.imports.get(first_part)
        if binding is not None:
            if binding.is_relative:
                is_pkg = (parsed.path.name == "__init__.py")
                target_module = resolve_relative_module(
                    current_module, binding.level, binding.module, is_package=is_pkg
                )
            else:
                target_module = binding.module or first_part
            remainder = base_name.split(".", 1)[1]
            return f"{target_module}.{remainder}"
        return base_name

    if base_name in parsed.symbols:
        return f"{current_module}.{base_name}"

    binding = parsed.imports.get(base_name)
    if binding is not None:
        if binding.is_relative:
            is_pkg = (parsed.path.name == "__init__.py")
            target_module = resolve_relative_module(
                current_module, binding.level, binding.module, is_package=is_pkg
            )
        else:
            target_module = binding.module or base_name
        target_symbol = binding.imported_name or base_name
        return f"{target_module}.{target_symbol}"

    return base_name


def _find_method_in_hierarchy(
    fq_class: str,
    method_name: str,
    table: dict[str, ClassMethods],
    visited: set[str] | None = None,
) -> str | None:
    """Find a method in a class or its base classes, recursively."""
    if visited is None:
        visited = set()
    if fq_class in visited:
        return None
    visited.add(fq_class)

    class_info = table.get(fq_class)
    if not class_info:
        return None

    if method_name in class_info.methods:
        return f"{fq_class}.{method_name}"

    for base in class_info.bases:
        res = _find_method_in_hierarchy(base, method_name, table, visited)
        if res is not None:
            return res

    return None


def build_class_method_table(
    files: ParsedFile | Iterable[ParsedFile],
    root: Path | None = None,
) -> dict[str, ClassMethods]:
    """Build a table of classes, their methods, and their declared base classes.

    Returns a mapping from fully-qualified class name -> ClassMethods object.
    """
    if isinstance(files, ParsedFile):
        files = [files]

    table: dict[str, ClassMethods] = {}

    def get_module(path: Path) -> str:
        if root is not None:
            return module_name_for_file(root, path)
        # Fallback: find project root or packages
        current = path.parent
        detected_root = None
        while current and current.parent != current:
            if (current / "pyproject.toml").exists() or (current / "setup.py").exists():
                detected_root = current
                break
            current = current.parent
        if detected_root is not None:
            return module_name_for_file(detected_root, path)
        # package dir traversal fallback
        current = path.parent
        while current and (current / "__init__.py").exists():
            current = current.parent
        if current and current != path.parent:
            return module_name_for_file(current, path)
        return path.stem

    for f in files:
        module = get_module(f.path)
        # Register all classes in this file
        for cls in f.classes:
            fq_class = f"{module}.{cls.name}"
            resolved_bases = [_resolve_base_fqn(b, f, module) for b in cls.bases]
            if fq_class not in table:
                table[fq_class] = ClassMethods(methods=set(), bases=resolved_bases)
            else:
                for b in resolved_bases:
                    if b not in table[fq_class].bases:
                        table[fq_class].bases.append(b)

        # Register all methods directly defined on those classes
        for fn in f.functions:
            if "." in fn.name:
                parts = fn.name.rsplit(".", 1)
                class_name, method_name = parts[0], parts[1]
                fq_class = f"{module}.{class_name}"
                if fq_class in table:
                    table[fq_class].methods.add(method_name)

    return table
