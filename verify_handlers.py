#!/usr/bin/env python3
"""Validación estática de handlers declarados en main.py.

No importa Pyrogram ni ejecuta handlers: parsea AST para poder validar el
registro incluso en entornos de desarrollo sin dependencias instaladas.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MAIN_FILE = ROOT / "main.py"
HANDLERS_DIR = ROOT / "handlers"


def _parse(path: Path) -> ast.Module:
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError) as error:
        raise RuntimeError(f"No se pudo analizar {path.relative_to(ROOT)}: {error}") from error


def _main_handler_names(tree: ast.Module) -> list[str]:
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "handlers":
            names.extend(alias.name for alias in node.names)
    return names


def _register_calls(tree: ast.Module) -> dict[str, list[ast.Call]]:
    calls: dict[str, list[ast.Call]] = {}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "register"
            and isinstance(node.func.value, ast.Name)
        ):
            calls.setdefault(node.func.value.id, []).append(node)
    return calls


def _register_function(tree: ast.Module) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "register":
            return node
    return None


def _check_call(function, call: ast.Call) -> list[str]:
    positional = [*function.args.posonlyargs, *function.args.args]
    names = [arg.arg for arg in positional]
    defaults_count = len(function.args.defaults)
    required = set(names[: len(names) - defaults_count if defaults_count else len(names)])
    required.update(
        arg.arg
        for arg, default in zip(function.args.kwonlyargs, function.args.kw_defaults)
        if default is None
    )
    provided = set(names[: len(call.args)])
    keyword_names = {keyword.arg for keyword in call.keywords if keyword.arg is not None}
    provided.update(keyword_names)
    valid_names = set(names) | {arg.arg for arg in function.args.kwonlyargs}

    errors = []
    missing = sorted(required - provided)
    unknown = sorted(keyword_names - valid_names)
    if missing:
        errors.append(f"faltan argumentos requeridos: {', '.join(missing)}")
    if unknown:
        errors.append(f"keywords desconocidos: {', '.join(unknown)}")
    if any(isinstance(argument, ast.Starred) for argument in call.args):
        errors.append("usa argumentos posicionales expandidos; verificación manual requerida")
    return errors


def main() -> int:
    errors: list[str] = []
    main_tree = _parse(MAIN_FILE)
    handler_names = _main_handler_names(main_tree)
    calls = _register_calls(main_tree)

    if len(handler_names) != len(set(handler_names)):
        errors.append("main.py importa handlers duplicados")

    for name in handler_names:
        module_path = HANDLERS_DIR / f"{name}.py"
        if not module_path.is_file():
            errors.append(f"{name}: no existe {module_path.relative_to(ROOT)}")
            continue
        tree = _parse(module_path)
        function = _register_function(tree)
        if function is None:
            errors.append(f"{name}: no define register() a nivel de módulo")
            continue

        registrations = calls.get(name, [])
        if len(registrations) != 1:
            errors.append(f"{name}: se esperaba una llamada register() desde main.py; encontradas {len(registrations)}")
            continue
        call_errors = _check_call(function, registrations[0])
        if call_errors:
            errors.extend(f"{name}: {error}" for error in call_errors)

    unimported_calls = sorted(set(calls) - set(handler_names))
    if unimported_calls:
        errors.append(f"main.py registra handlers que no importó: {', '.join(unimported_calls)}")

    if errors:
        print("Falló la validación de handlers:")
        for error in errors:
            print(f"- {error}")
        return 1

    print(f"OK: {len(handler_names)} handlers importados y registrados una vez; firmas requeridas satisfechas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
