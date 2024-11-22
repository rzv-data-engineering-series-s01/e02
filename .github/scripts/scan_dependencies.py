import os
import re
from pathlib import Path
import json
from typing import Dict, List, Set, Tuple
from dataclasses import dataclass, asdict
import logging
from tqdm import tqdm


@dataclass
class Dependency:
    type: str
    path: str
    used_in_files: Set[str]
    used_in_functions: Set[str]

    def to_dict(self):
        return {
            "type": self.type,
            "path": Path(self.path).as_posix(),
            "used_in": {
                "files": sorted([Path(p).as_posix() for p in self.used_in_files]),
                "functions": sorted(list(self.used_in_functions)),
            },
        }


class DependencyScanner:
    def __init__(self, root_dir: str):
        self.root_dir = Path(root_dir)
        self.function_pattern = re.compile(
            r"r_\d+\.\d+(?:\.\d+)?_f_([a-z_]+)\.sql", re.IGNORECASE
        )
        self.function_call_pattern = re.compile(
            r"KIMBALL\.([A-Za-z_]+)\s*\(", re.IGNORECASE
        )
        self.dependencies: Dict[str, Dependency] = {}

        # Configure logging
        logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

    def scan_functions(self) -> Dict[str, str]:
        """Scan for function definitions and return {function_name: file_path}"""
        functions_dir = self.root_dir / "deployer" / "patch" / "DWH" / "kimball"
        functions = {}

        if not functions_dir.exists():
            logging.warning(f"Functions directory not found: {functions_dir}")
            return functions

        logging.debug(f"Scanning for functions in: {functions_dir}")  # Debug print

        for file in functions_dir.glob("*.sql"):
            logging.info(f"Found SQL file: {file.name}")  # Debug print
            match = self.function_pattern.match(file.name)
            if match:
                function_name = match.group(1).lower()
                functions[function_name] = str(
                    file.relative_to(self.root_dir).as_posix()
                )
                logging.info(f"Matched function: {function_name}")  # Debug print
            else:
                logging.info(f"No match for file: {file.name}")  # Debug print

        logging.debug(f"Found functions: {functions}")  # Debug print
        return functions

    def scan_sql_files(self) -> List[Path]:
        """Return all SQL files in specified directories"""
        search_dirs = [
            "replicator/source",
            "deployer/patch",
            "superset/datasets/kimball",
            "superset_objects/datasets",
        ]

        logging.info("Scanning directories:")
        sql_files = []
        for dir_path in search_dirs:
            full_path = self.root_dir / dir_path
            if full_path.exists():
                files_count = len(list(full_path.rglob("*.sql")))
                logging.info(f"  - {dir_path}: {files_count} files")
                sql_files.extend(full_path.rglob("*.sql"))
            else:
                logging.warning(f"  - {dir_path}: directory not found")

        return sql_files

    def scan_dependencies(self) -> Tuple[Dict, Dict]:
        """
        Scan for dependencies and return two dictionaries:
        1. Raw dependencies including function-to-function
        2. Flattened dependencies with only file dependencies
        """
        logging.info("Starting function scanning...")
        functions = self.scan_functions()
        logging.info(f"Found {len(functions)} functions")

        logging.info("Starting SQL files scanning...")
        sql_files = self.scan_sql_files()
        total_files = len(list(sql_files))
        logging.info(f"Found {total_files} SQL files to process")

        # Initialize dependencies
        for func_name, func_path in functions.items():
            self.dependencies[func_name] = Dependency(
                type="function",
                path=func_path,
                used_in_files=set(),
                used_in_functions=set(),
            )

        # Function name to path mapping for quicker lookups
        function_paths = {
            Path(fpath).as_posix(): fname for fname, fpath in functions.items()
        }

        # Scan for usage with progress bar
        for sql_file in tqdm(sql_files, desc="Processing SQL files"):
            relative_path = Path(sql_file).relative_to(self.root_dir).as_posix()
            logging.debug(f"Checking {sql_file} in path: {relative_path}")
            try:
                content = sql_file.read_text(encoding="utf-8")

                # Find all function calls in this file
                calls = self.function_call_pattern.finditer(content.lower())
                for match in calls:
                    func_name = match.group(1).lower()
                    if func_name in self.dependencies:
                        # Skip if this is the function's own definition file
                        if relative_path == functions.get(func_name):
                            continue

                        # Check if this file is another function's definition
                        calling_function_name = function_paths.get(relative_path)

                        if calling_function_name:
                            # This is a function-to-function dependency
                            self.dependencies[func_name].used_in_functions.add(
                                calling_function_name
                            )
                            logging.info(
                                f"Added a dep to func: {calling_function_name}"
                            )
                        else:
                            # This is a file using the function
                            self.dependencies[func_name].used_in_files.add(
                                relative_path
                            )
                            logging.info(f"Added a dep to file: {relative_path}")

            except Exception as e:
                logging.error(f"Error processing file {relative_path}: {str(e)}")

        logging.info("Creating dependency dictionaries...")
        raw_deps = {name: dep.to_dict() for name, dep in self.dependencies.items()}

        logging.info("Flattening dependencies...")
        flat_deps = self._flatten_dependencies()

        logging.info("Dependency scanning completed")
        return raw_deps, flat_deps

    def _flatten_dependencies(self) -> Dict:
        """Flatten function-to-function dependencies by propagating files upward through the dependency chain"""
        flattened = {}

        def get_all_dependent_files(func_name: str, processed: set = None) -> set:
            """
            Recursively get all files that depend on this function,
            including files that depend on functions that use this function
            """
            if processed is None:
                processed = set()

            if func_name in processed:
                return set()

            processed.add(func_name)

            # Get direct file dependencies
            all_files = set(
                Path(p).as_posix() for p in self.dependencies[func_name].used_in_files
            )

            # Get indirect dependencies through other functions
            for dependent_func in self.dependencies[func_name].used_in_functions:
                if dependent_func not in processed:
                    # Add files that directly use the dependent function
                    all_files.update(
                        Path(p).as_posix()
                        for p in self.dependencies[dependent_func].used_in_files
                    )
                    # Recursively get files that depend on the dependent function
                    all_files.update(get_all_dependent_files(dependent_func, processed))

            return all_files

        # Process each function
        for func_name, dep in self.dependencies.items():
            flattened[func_name] = {
                "type": "function",
                "path": Path(dep.path).as_posix(),
                "used_in": {"files": sorted(list(get_all_dependent_files(func_name)))},
            }

        return flattened

    def save_results(
        self, output_dir: str, raw_deps: Dict = None, flat_deps: Dict = None
    ):
        """Save both raw and flattened dependencies to JSON files"""
        if raw_deps is None or flat_deps is None:
            raw_deps, flat_deps = self.scan_dependencies()

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        with open(output_path / "raw_dependencies.json", "w") as f:
            json.dump(raw_deps, f, indent=2)

        with open(output_path / "flattened_dependencies.json", "w") as f:
            json.dump(flat_deps, f, indent=2)

if __name__ == "__main__":
    scanner = DependencyScanner(".")
    raw_deps, flat_deps = scanner.scan_dependencies()
    
    output_dir = Path(__file__).parent
    scanner.save_results(output_dir, raw_deps, flat_deps)
