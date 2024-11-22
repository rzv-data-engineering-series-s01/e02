import sys
from pathlib import Path
import unittest
from unittest.mock import patch, mock_open
import tempfile
import shutil
import json

# Add scripts directory to Python path
scripts_dir = str(Path(__file__).parent.parent / "scripts")
if scripts_dir not in sys.path:
    sys.path.append(scripts_dir)

from scan_dependencies import DependencyScanner, Dependency


class TestDependencyScanner(unittest.TestCase):
    def setUp(self):
        # Create temporary directory structure
        self.test_dir = Path(tempfile.mkdtemp())
        self.kimball_dir = self.test_dir / "deployer" / "patch" / "DWH" / "kimball"
        self.kimball_dir.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def _create_file(self, path: Path, content: str):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def test_dependency_searching(self):
        """Test searching of direct dependencies"""
        # Create function definition
        self._create_file(
            self.kimball_dir / "r_3.000001_f_test_func.sql",
            """
            CREATE OR REPLACE FUNCTION DWH.KIMBALL.test_func(...)
            RETURNS VARCHAR AS $$
            BEGIN
                RETURN 'test';
            END;
            $$
            """,
        )

        # Create file using the function
        source_dir = self.test_dir / "replicator" / "source"
        source_dir.mkdir(parents=True, exist_ok=True)
        self._create_file(
            source_dir / "test_view.sql",
            """
            SELECT ${ENV_PREFIX}DWH.KIMBALL.test_func(...) as col
            FROM some_table;
            """,
        )

        scanner = DependencyScanner(str(self.test_dir))
        raw_deps, _ = scanner.scan_dependencies()

        self.assertIn("test_func", raw_deps)
        self.assertEqual(
            Path(raw_deps["test_func"]["used_in"]["files"][0]).as_posix(),
            "replicator/source/test_view.sql",
        )

    def test_function_to_function_dependency(self):
        """Test detection of function-to-function dependencies"""
        # Create two functions where one calls another
        self._create_file(
            self.kimball_dir / "r_3.000001_f_base_func.sql",
            """
            CREATE OR REPLACE FUNCTION DWH.KIMBALL.base_func(...)
            RETURNS VARCHAR AS $$
            BEGIN
                RETURN 'test';
            END;
            $$
            """,
        )

        self._create_file(
            self.kimball_dir / "r_3.000002_f_caller_func.sql",
            """
            CREATE OR REPLACE FUNCTION DWH.KIMBALL.caller_func(...)
            RETURNS VARCHAR AS $$
            BEGIN
                RETURN ${ENV_PREFIX}DWH.KIMBALL.base_func(...);
            END;
            $$
            """,
        )

        scanner = DependencyScanner(str(self.test_dir))
        raw_deps, _ = scanner.scan_dependencies()

        self.assertIn("base_func", raw_deps)
        self.assertEqual(raw_deps["base_func"]["used_in"]["functions"], ["caller_func"])

    def test_transitive_dependency_flattening(self):
        """Test flattening of transitive dependencies chains"""
        # Create function chain: base_func <- middle_func <- end_view
        self._create_file(
            self.kimball_dir / "r_3.000001_f_base_func.sql",
            """
            CREATE OR REPLACE FUNCTION DWH.KIMBALL.base_func(...)
            RETURNS VARCHAR AS $$
            BEGIN
                RETURN 'test';
            END;
            $$
            """,
        )

        self._create_file(
            self.kimball_dir / "r_3.000002_f_middle_func.sql",
            """
            CREATE OR REPLACE FUNCTION DWH.KIMBALL.middle_func(...)
            RETURNS VARCHAR AS $$
            BEGIN
                RETURN ${ENV_PREFIX}DWH.KIMBALL.base_func(...);
            END;
            $$
            """,
        )

        source_dir = self.test_dir / "replicator" / "source"
        source_dir.mkdir(parents=True, exist_ok=True)

        self._create_file(
            source_dir / "end_view.sql",
            """
            CREATE VIEW end_view AS
            SELECT ${ENV_PREFIX}DWH.KIMBALL.middle_func(...) as col
            FROM some_table;
            """,
        )

        scanner = DependencyScanner(str(self.test_dir))
        raw_deps, flat_deps = scanner.scan_dependencies()

        # Check raw dependencies
        self.assertIn("base_func", raw_deps)
        self.assertIn("middle_func", raw_deps)
        self.assertEqual(len(raw_deps["base_func"]["used_in"]["files"]), 0)
        self.assertEqual(raw_deps["base_func"]["used_in"]["functions"], ["middle_func"])
        self.assertIn(
            "end_view.sql", Path(raw_deps["middle_func"]["used_in"]["files"][0]).name
        )

        # Check flattened dependencies - both functions should show end_view.sql as dependent
        self.assertIn("base_func", flat_deps)
        self.assertIn("middle_func", flat_deps)
        for func in ["base_func", "middle_func"]:
            self.assertEqual(len(flat_deps[func]["used_in"]["files"]), 1)
            self.assertIn(
                "end_view.sql", Path(flat_deps[func]["used_in"]["files"][0]).name
            )


if __name__ == "__main__":
    unittest.main()
