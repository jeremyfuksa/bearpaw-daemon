import os
import sys
import tempfile
import unittest

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
)

from bearpaw.config import load_config


class LoadConfigTests(unittest.TestCase):
    def test_loads_utf8_yaml(self) -> None:
        # Regression: load_config previously opened YAML with encoding="ascii",
        # so a non-ASCII byte (here in a comment) would raise.
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "c.yaml")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("# 22°C ambient — narrowband voice\napi:\n  port: 9000\n")
            config = load_config(path)
            self.assertEqual(config.api.port, 9000)


if __name__ == "__main__":
    unittest.main()
