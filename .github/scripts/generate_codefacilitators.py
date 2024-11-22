from pathlib import Path
import json
import re
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)

def generate_codefacilitators():
    scripts_dir = Path(__file__).parent
    root = scripts_dir.parent.parent
    
    with open(scripts_dir / "flattened_dependencies.json") as f:
        deps = json.load(f)

    logging.info("Parsing MARTOWNERS patterns") 
    mart_patterns = {}
    with open(root / ".github/MARTOWNERS") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                pattern, *teams = line.split()
                mart_patterns[pattern] = teams

    def match_pattern(path, pattern):
        pattern = pattern.replace("/", "\/").replace("*", "[^\/]*")
        return bool(re.match(f"^{pattern}$", path))

    func_teams = {}
    for func, data in deps.items():
        teams = set()
        for dep_file in data["used_in"]["files"]:
            for pattern, pattern_teams in mart_patterns.items():
                if match_pattern(dep_file, pattern):
                    teams.update(pattern_teams)
        
        if teams:
            func_teams[func] = data["path"], list(teams)
            logging.info(f"Mapped {func} -> {teams}")

    output_file = root / ".github/CODEFACILITATORS"
    logging.info(f"Writing to {output_file}")
    with open(output_file, "w") as f:
        f.write("# Auto-generated from dependencies\n\n")
        for _, (path, teams) in sorted(func_teams.items()):
            f.write(f"{path} {' '.join(sorted(teams))}\n")

if __name__ == "__main__":
    generate_codefacilitators()
