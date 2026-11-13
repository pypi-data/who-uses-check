import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from public_api import find_packages, public_names  # noqa: E402


def make(tree):
    root = Path(tempfile.mkdtemp())
    for rel, text in tree.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text))
    return root


class PublicNames(unittest.TestCase):
    def test_rules(self):
        root = make({
            "pkg/__init__.py": """
                from .models import User
                from ._impl import Engine
                from os import path
                VERSION = "1"
                _private = 1
                try:
                    from .fast import speedup
                except ImportError:
                    speedup = None
            """,
            "pkg/models.py": """
                from ._base import Base
                class User(Base):
                    name = ""
                    def save(self): ...
                    def _hidden(self): ...
                def helper(): ...
            """,
            "pkg/_base.py": """
                class Base:
                    def delete(self): ...
            """,
            "pkg/_impl.py": """
                class Engine:
                    def run(self): ...
            """,
            "pkg/fast.py": "def speedup(): ...\n",
            "pkg/limited.py": """
                __all__ = ["kept"]
                def kept(): ...
                def not_exported(): ...
            """,
            "pkg/tests/test_x.py": "def test_a(): ...\n",
            "setup.py": "",
        })
        names = public_names(root)
        for n in ["pkg", "pkg.User", "pkg.User.save", "pkg.User.delete", "pkg.User.name", "pkg.VERSION",
                  "pkg.Engine", "pkg.Engine.run", "pkg.speedup", "pkg.models.User.delete", "pkg.models.helper",
                  "pkg.limited.kept", "pkg.fast.speedup"]:
            self.assertIn(n, names)
        for n in ["pkg._private", "pkg.path", "pkg.User._hidden", "pkg._base", "pkg._base.Base",
                  "pkg.limited.not_exported", "pkg.tests", "pkg.tests.test_x.test_a"]:
            self.assertNotIn(n, names)
        self.assertEqual(find_packages(root), ["pkg"])

    def test_removal(self):
        before = make({"lib.py": "def old(): ...\ndef same(): ...\nclass C:\n    def m(self): ...\n"})
        after = make({"lib.py": "def new(): ...\ndef same(): ...\n"})
        self.assertEqual(public_names(before) - public_names(after), {"lib.old", "lib.C", "lib.C.m"})

    def test_syntax_error_is_skipped(self):
        root = make({"pkg/__init__.py": "def ok(): ...\n", "pkg/broken.py": "def (:\n"})
        self.assertIn("pkg.ok", public_names(root))


if __name__ == "__main__":
    unittest.main()
