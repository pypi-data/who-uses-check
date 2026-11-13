"""Collect the public names of a Python package from its source, with ast.

A public name is a dotted path that other code can import or reach by attribute, written the
way py-code.org records uses: `pkg`, `pkg.sub`, `pkg.sub.func`, `pkg.Class`, `pkg.Class.method`.

Rules:
- Modules and packages whose own name starts with "_" are private, and so is everything in them.
- In a module with a literal __all__, the public names are the ones it lists.
- Otherwise every top-level def, class, assignment and in-package import whose name does not
  start with "_" is public. Statements under if/try/with at the top level count too.
- Methods and class attributes of a public class are public unless they start with "_", including
  the ones it inherits from other classes in the package.
- A class re-exported under another path (`from .models import User` in pkg/__init__.py) gets
  its members under that path as well.
"""
import ast
from pathlib import Path

SKIP_DIRS = {"tests", "test", "testing", "docs", "doc", "examples", "example", "benchmarks", "build", "dist",
             "venv", ".venv", "env", "site-packages", "node_modules", "__pycache__"}
SKIP_FILES = {"setup.py", "conftest.py", "noxfile.py", "fabfile.py", "manage.py"}


def find_packages(root: Path):
    """Top-level import packages and modules under a source root."""
    out = []
    for p in sorted(root.iterdir()):
        if p.name.startswith((".", "_")) or p.name in SKIP_DIRS:
            continue
        if p.is_dir() and (p / "__init__.py").exists():
            out.append(p.name)
        elif p.is_file() and p.suffix == ".py" and p.name not in SKIP_FILES:
            out.append(p.stem)
    return out


def module_files(root: Path, package: str):
    """(dotted module name, path, is_private) for every module of a package. Private modules are
    read too, because public classes can inherit from or re-export classes defined in them."""
    single = root / f"{package}.py"
    if single.is_file():
        yield package, single, False
        return
    for path in sorted((root / package).rglob("*.py")):
        parts = list(path.relative_to(root).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        if any(x in SKIP_DIRS for x in parts[1:]) or path.name in SKIP_FILES:
            continue
        yield ".".join(parts), path, any(x.startswith("_") for x in parts[1:])


def _top_statements(body):
    for node in body:
        if isinstance(node, ast.If):
            yield from _top_statements(node.body)
            yield from _top_statements(node.orelse)
        elif isinstance(node, ast.Try) or type(node).__name__ == "TryStar":
            yield from _top_statements(node.body)
            for h in node.handlers:
                yield from _top_statements(h.body)
            yield from _top_statements(node.orelse)
            yield from _top_statements(node.finalbody)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            yield from _top_statements(node.body)
        else:
            yield node


def _targets(node):
    if isinstance(node, ast.Assign):
        targets = node.targets
    elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
        targets = [node.target]
    elif type(node).__name__ == "TypeAlias":
        targets = [node.name]
    else:
        return []
    names = []
    for t in targets:
        for n in ast.walk(t):
            if isinstance(n, ast.Name):
                names.append(n.id)
    return names


def _literal_all(tree):
    for node in _top_statements(tree.body):
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and "__all__" in _targets(node) and node.value is not None:
            try:
                value = ast.literal_eval(node.value)
            except ValueError:
                return None
            if isinstance(value, (list, tuple)) and all(isinstance(x, str) for x in value):
                return list(value)
    return None


def _resolve(module, is_package, node):
    """Absolute module of an ImportFrom, or None for a plain `import x`."""
    if node.level == 0:
        return node.module
    base = module.split(".")
    if not is_package:
        base = base[:-1]
    base = base[: len(base) - (node.level - 1)] if node.level > 1 else base
    return ".".join(base + ([node.module] if node.module else []))


def public_names(root, packages=None):
    """Set of public dotted names for the given top-level packages (auto-detected if None)."""
    root = Path(root)
    packages = packages or find_packages(root)
    names, classes, aliases, bases = set(), {}, {}, {}
    for package in packages:
        for module, path, private in module_files(root, package):
            try:
                tree = ast.parse(path.read_bytes(), filename=str(path))
            except (SyntaxError, ValueError):
                continue
            is_package = path.name == "__init__.py"
            if not private:
                names.add(module)
            declared = _literal_all(tree)
            defined, local = {}, {}  # local: name in this module -> full dotted path, for base classes
            for node in _top_statements(tree.body):
                if isinstance(node, ast.Import):
                    for a in node.names:
                        if a.asname:
                            local[a.asname] = a.name
                        else:
                            local[a.name.split(".")[0]] = a.name.split(".")[0]
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    defined[node.name] = None
                elif isinstance(node, ast.ClassDef):
                    members = set()
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                            members.add(item.name)
                        else:
                            members.update(_targets(item))
                    classes[f"{module}.{node.name}"] = {m for m in members if not m.startswith("_")}
                    bases[f"{module}.{node.name}"] = (node.bases, local)
                    local[node.name] = f"{module}.{node.name}"
                    defined[node.name] = None
                elif isinstance(node, ast.ImportFrom):
                    source = _resolve(module, is_package, node)
                    if not source or source.split(".")[0] != package:
                        continue  # only re-exports from the package itself are part of its API
                    for a in node.names:
                        if a.name != "*":
                            defined[a.asname or a.name] = f"{source}.{a.name}"
                            local[a.asname or a.name] = f"{source}.{a.name}"
                else:
                    for t in _targets(node):
                        defined[t] = None
            exported = declared if declared is not None else [n for n in defined if not n.startswith("_")]
            for n in exported:
                full = f"{module}.{n}"
                if not private:
                    names.add(full)
                if defined.get(n):
                    aliases[full] = defined[n]
    def canonical(path, seen=()):
        while path in aliases and path not in seen:
            seen = seen + (path,)
            path = aliases[path]
        return path

    def dotted(expr, local):
        parts = []
        while isinstance(expr, ast.Attribute):
            parts.append(expr.attr)
            expr = expr.value
        if not isinstance(expr, ast.Name) or expr.id not in local:
            return None
        return ".".join([local[expr.id]] + parts[::-1])

    done = {}

    def all_members(cls, stack=()):
        if cls in done:
            return done[cls]
        out = set(classes.get(cls, ()))
        exprs, local = bases.get(cls, ((), {}))
        for e in exprs:
            base = dotted(e, local)
            base = base and canonical(base)
            if base in classes and base not in stack:
                out |= all_members(base, stack + (cls,))
        done[cls] = out
        return out

    for cls in list(classes):
        classes[cls] = all_members(cls)
    # Give re-exported classes their members under every public path (follows alias chains).
    for alias in aliases:
        if alias not in names:
            continue  # an alias inside a private module
        for m in classes.get(canonical(alias), ()):
            names.add(f"{alias}.{m}")
    for cls, members in classes.items():
        if cls in names:
            names.update(f"{cls}.{m}" for m in members)
    return names
