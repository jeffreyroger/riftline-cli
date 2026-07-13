"""
Resolution layer: turns raw call names + a file's import cheat-sheet into
fully-qualified, cross-file references -- resolved with confidence, or
explicitly flagged unresolved. Never guesses.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .parser import ParsedFile


def module_name_for_file(root: Path, path: Path) -> str:
    """repo_root/mini_pkg/core.py -> 'mini_pkg.core'"""
    rel = path.relative_to(root).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def resolve_relative_module(current_module: str, level: int, module: str | None) -> str:
    """Resolve a relative import target to an absolute dotted module name.

    current_module: dotted module doing the importing, e.g. "mini_pkg.main"
    level: number of leading dots (1 = same package, 2 = parent package, ...)
    module: text after the dots, may be None (e.g. "from . import x")
    """
    parts = current_module.split(".")
    base = parts[: len(parts) - level] if level > 0 else parts[:-1]
    if module:
        base = base + module.split(".")
    return ".".join(base)


@dataclass(frozen=True)
class ResolvedCall:
    caller: str        # fully-qualified caller, e.g. "mini_pkg.main.foo"
    callee: str         # fully-qualified callee, or "unknown:<name>" if unresolved
    confidence: str      # "resolved" | "unresolved"


def resolve_calls_for_file(
    parsed: ParsedFile,
    current_module: str,
    all_symbols: dict[str, set[str]],   # module_name -> set of symbols it defines
) -> list[ResolvedCall]:
    """Chain this file's import table with every other file's own symbol
    table to turn each raw call name into a real graph edge."""
    results: list[ResolvedCall] = []
    for fn in parsed.functions:
        caller_fqn = f"{current_module}.{fn.name}"
        for raw_name in fn.calls:
            callee, confidence = _resolve_one(raw_name, parsed, current_module, all_symbols)
            results.append(ResolvedCall(caller=caller_fqn, callee=callee, confidence=confidence))
    return results


def _resolve_one(
    raw_name: str,
    parsed: ParsedFile,
    current_module: str,
    all_symbols: dict[str, set[str]],
) -> tuple[str, str]:
    # Case 1: name refers to something imported from elsewhere.
    binding = parsed.imports.get(raw_name)
    if binding is not None:
        if binding.is_relative:
            target_module = resolve_relative_module(current_module, binding.level, binding.module)
        else:
            target_module = binding.module or raw_name

        target_symbol = binding.imported_name or raw_name
        target_symbols = all_symbols.get(target_module)
        if target_symbols is not None and target_symbol in target_symbols:
            return f"{target_module}.{target_symbol}", "resolved"
        # imported, but we can't verify the destination actually defines it
        # (file not part of this scan, third-party package, or genuinely missing)
        return f"unknown:{raw_name}", "unresolved"

    # Case 2: name is defined right here in the same file.
    if raw_name in parsed.symbols:
        return f"{current_module}.{raw_name}", "resolved"

    # Case 3: genuinely unknown -- third-party call, builtin, typo, or a
    # name defined somewhere we haven't parsed. Flag it, never guess.
    return f"unknown:{raw_name}", "unresolved"
