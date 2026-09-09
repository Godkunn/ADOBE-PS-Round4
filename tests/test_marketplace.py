"""
Adversarial Stress Test Suite for Marketplace Manifest and agentskills.io SKILL.md Specifications.
Covers Milestone 1 verification for the brand-ai-readiness-audit package.
"""

import os
import re
import json
import unittest
import yaml

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MARKETPLACE_PATH = os.path.join(PROJECT_ROOT, "marketplace.json")
SKILLS_DIR = os.path.join(PROJECT_ROOT, "skills")
README_PATH = os.path.join(PROJECT_ROOT, "README.md")
PROJECT_MD_PATH = os.path.join(PROJECT_ROOT, "PROJECT.md")
TEST_INFRA_PATH = os.path.join(PROJECT_ROOT, "TEST_INFRA.md")

EXPECTED_SKILL_NAMES = {
    "audit-orchestrator",
    "crawl-render-audit",
    "structured-data-audit",
    "freshness-corroboration",
    "engagement-bounce-audit"
}

REQUIRED_SECTIONS = [
    "## When to use",
    "## Inputs",
    "## Procedure",
    "## Output"
]


class StrictJSONDecoder:
    """Helper to detect duplicate keys in JSON objects."""
    @staticmethod
    def parse_no_duplicates(json_str):
        def dict_raise_on_duplicates(ordered_pairs):
            d = {}
            for k, v in ordered_pairs:
                if k in d:
                    raise ValueError(f"Duplicate key detected in JSON: '{k}'")
                d[k] = v
            return d
        return json.loads(json_str, object_pairs_hook=dict_raise_on_duplicates)


class TestMarketplaceManifest(unittest.TestCase):
    """Adversarial validation tests for marketplace.json manifest."""

    def setUp(self):
        self.assertTrue(os.path.exists(MARKETPLACE_PATH), "marketplace.json does not exist at project root")
        with open(MARKETPLACE_PATH, "r", encoding="utf-8") as f:
            self.raw_content = f.read()

    def test_strict_json_parsing_and_no_bom(self):
        """Verify marketplace.json parses with strict JSON parser and has no UTF-8 BOM."""
        self.assertFalse(self.raw_content.startswith("\ufeff"), "marketplace.json must not have UTF-8 BOM")
        try:
            self.data = StrictJSONDecoder.parse_no_duplicates(self.raw_content)
        except Exception as e:
            self.fail(f"marketplace.json failed strict JSON parse with duplicate key check: {e}")

    def test_required_root_fields(self):
        """Verify all mandatory root metadata fields exist with correct types."""
        data = StrictJSONDecoder.parse_no_duplicates(self.raw_content)
        expected_fields = {
            "name": str,
            "version": str,
            "description": str,
            "license": str,
            "author": str,
            "entrypoint": str,
            "skills": list
        }
        for field, expected_type in expected_fields.items():
            self.assertIn(field, data, f"Missing required root field '{field}' in marketplace.json")
            self.assertIsInstance(data[field], expected_type, f"Field '{field}' must be of type {expected_type.__name__}")
            if expected_type == str:
                self.assertTrue(data[field].strip(), f"Field '{field}' must not be empty")

        self.assertEqual(data["name"], "brand-ai-readiness-audit")
        self.assertEqual(data["license"], "Apache-2.0")
        self.assertEqual(data["entrypoint"], "skills/audit-orchestrator")
        self.assertRegex(data["version"], r"^\d+\.\d+\.\d+$", f"Invalid semantic version: {data['version']}")

    def test_skills_array_exact_count(self):
        """Verify skills array contains exactly 5 skills."""
        data = StrictJSONDecoder.parse_no_duplicates(self.raw_content)
        skills = data.get("skills", [])
        self.assertEqual(len(skills), 5, f"marketplace.json must define exactly 5 skills, found {len(skills)}")

    def test_no_duplicate_skill_names_or_paths(self):
        """Verify there are zero duplicate skill names or relative paths in marketplace.json."""
        data = StrictJSONDecoder.parse_no_duplicates(self.raw_content)
        skills = data.get("skills", [])
        names = [s.get("name") for s in skills]
        paths = [s.get("path") for s in skills]

        self.assertEqual(len(names), len(set(names)), f"Duplicate skill names found: {names}")
        self.assertEqual(len(paths), len(set(paths)), f"Duplicate skill paths found: {paths}")
        self.assertEqual(set(names), EXPECTED_SKILL_NAMES, f"Skill names do not match expected set: {set(names)} vs {EXPECTED_SKILL_NAMES}")

    def test_single_entrypoint_invariant(self):
        """Verify that exactly one skill has entrypoint: true and that skill is audit-orchestrator."""
        data = StrictJSONDecoder.parse_no_duplicates(self.raw_content)
        skills = data.get("skills", [])
        entrypoint_skills = [s for s in skills if s.get("entrypoint") is True]

        self.assertEqual(len(entrypoint_skills), 1,
                         f"Exactly one skill must have entrypoint: true, found {len(entrypoint_skills)}: {entrypoint_skills}")
        self.assertEqual(entrypoint_skills[0]["name"], "audit-orchestrator",
                         f"Entrypoint skill must be 'audit-orchestrator', found '{entrypoint_skills[0]['name']}'")

        non_entrypoints = [s for s in skills if s.get("name") != "audit-orchestrator"]
        for s in non_entrypoints:
            self.assertFalse(s.get("entrypoint", False),
                             f"Skill '{s.get('name')}' must have entrypoint: false, but got {s.get('entrypoint')}")

    def test_skill_structure_and_types(self):
        """Verify each skill dictionary contains required fields and valid relative paths."""
        data = StrictJSONDecoder.parse_no_duplicates(self.raw_content)
        skills = data.get("skills", [])
        for s in skills:
            self.assertIn("name", s)
            self.assertIn("path", s)
            self.assertIn("entrypoint", s)
            self.assertIn("description", s)

            self.assertIsInstance(s["name"], str)
            self.assertIsInstance(s["path"], str)
            self.assertIsInstance(s["entrypoint"], bool)
            self.assertIsInstance(s["description"], str)

            self.assertTrue(s["name"].strip())
            self.assertTrue(s["description"].strip())

            # Path safety checks
            path = s["path"]
            self.assertFalse(path.startswith("/"), f"Path '{path}' must be relative, not absolute")
            self.assertFalse(path.startswith("\\"), f"Path '{path}' must not use backslashes")
            self.assertFalse(".." in path, f"Path '{path}' must not contain directory traversal")
            self.assertTrue(path.startswith("skills/"), f"Path '{path}' must start with 'skills/'")

    def test_filesystem_directory_and_skill_md_existence(self):
        """Verify all referenced paths exist as physical directories containing SKILL.md."""
        data = StrictJSONDecoder.parse_no_duplicates(self.raw_content)
        skills = data.get("skills", [])
        for s in skills:
            rel_path = s["path"]
            abs_path = os.path.join(PROJECT_ROOT, rel_path)
            self.assertTrue(os.path.isdir(abs_path), f"Referenced skill directory does not exist: {abs_path}")

            skill_md = os.path.join(abs_path, "SKILL.md")
            self.assertTrue(os.path.isfile(skill_md), f"Missing SKILL.md in directory: {abs_path}")

    def test_no_orphan_skill_directories(self):
        """
        Verify there are no orphan skill directories in skills/ that are not
        declared in marketplace.json.

        The 'shared' directory is intentionally excluded: it is a Python utility
        library (utils.py) used internally by all skill scripts and is not itself
        an agentskills.io skill (no SKILL.md, not a marketplace entry point).
        """
        #: Directories in skills/ that are known utility packages, not skills.
        UTILITY_DIRS = {"shared"}

        data = StrictJSONDecoder.parse_no_duplicates(self.raw_content)
        declared_names = {s["name"] for s in data.get("skills", [])}

        actual_skill_dirs = {
            d
            for d in os.listdir(SKILLS_DIR)
            if (
                os.path.isdir(os.path.join(SKILLS_DIR, d))
                and not d.startswith(".")
                and not d.startswith("__")
                and d not in UTILITY_DIRS
            )
        }
        self.assertEqual(
            actual_skill_dirs,
            declared_names,
            f"Mismatch between actual skill directories {actual_skill_dirs} "
            f"and manifest {declared_names}",
        )



class TestSkillSpecifications(unittest.TestCase):
    """Adversarial validation tests for agentskills.io SKILL.md files."""

    def get_skill_files(self):
        files = {}
        for skill_name in EXPECTED_SKILL_NAMES:
            path = os.path.join(SKILLS_DIR, skill_name, "SKILL.md")
            self.assertTrue(os.path.exists(path), f"File {path} does not exist")
            with open(path, "r", encoding="utf-8") as f:
                files[skill_name] = (path, f.read())
        return files

    def test_yaml_frontmatter_integrity(self):
        """Verify YAML frontmatter starts with --- and parses cleanly with safe YAML parser."""
        skill_files = self.get_skill_files()
        for skill_name, (path, content) in skill_files.items():
            self.assertTrue(content.startswith("---"), f"{path} must start with YAML delimiter '---'")
            parts = content.split("---", 2)
            self.assertGreaterEqual(len(parts), 3, f"{path} does not contain properly closed YAML frontmatter")

            yaml_text = parts[1].strip()
            try:
                fm = yaml.safe_load(yaml_text)
            except Exception as e:
                self.fail(f"Failed to parse YAML frontmatter in {path}: {e}")

            self.assertIsInstance(fm, dict, f"YAML frontmatter in {path} must be a dictionary")
            self.assertIn("name", fm, f"Missing 'name' in {path}")
            self.assertEqual(fm["name"], skill_name, f"Frontmatter 'name' {fm['name']} does not match directory {skill_name}")
            self.assertIn("description", fm, f"Missing 'description' in {path}")
            self.assertTrue(isinstance(fm["description"], str) and fm["description"].strip(), f"Empty description in {path}")
            self.assertIn("license", fm, f"Missing 'license' in {path}")
            self.assertEqual(fm["license"], "Apache-2.0", f"License in {path} must be 'Apache-2.0'")

            # Validate metadata block
            self.assertIn("metadata", fm, f"Missing 'metadata' block in {path}")
            metadata = fm["metadata"]
            self.assertIsInstance(metadata, dict, f"'metadata' in {path} must be a dict")
            self.assertIn("version", metadata, f"Missing metadata.version in {path}")
            self.assertIn("author", metadata, f"Missing metadata.author in {path}")
            self.assertIn("category", metadata, f"Missing metadata.category in {path}")
            self.assertIn("tags", metadata, f"Missing metadata.tags in {path}")
            self.assertIsInstance(metadata["tags"], list, f"metadata.tags in {path} must be a list")
            self.assertGreater(len(metadata["tags"]), 0, f"metadata.tags in {path} must not be empty")

    def test_required_markdown_sections(self):
        """Verify all 4 mandatory agentskills.io sections exist in exact format."""
        skill_files = self.get_skill_files()
        for skill_name, (path, content) in skill_files.items():
            parts = content.split("---", 2)
            markdown_body = parts[2].strip()

            # Must contain H1
            h1_matches = re.findall(r"^#\s+(.+)$", markdown_body, re.MULTILINE)
            self.assertGreaterEqual(len(h1_matches), 1, f"Missing H1 heading in {path}")

            # Must contain all 4 required H2 sections
            for sec in REQUIRED_SECTIONS:
                self.assertIn(sec, markdown_body, f"Missing required section '{sec}' in {path}")

            # Check section order
            indices = [markdown_body.find(sec) for sec in REQUIRED_SECTIONS]
            self.assertEqual(indices, sorted(indices), f"Required sections in {path} are not in standard order")

    def test_embedded_json_examples_parse_valid(self):
        """Extract and validate all JSON output code blocks in SKILL.md files."""
        skill_files = self.get_skill_files()
        for skill_name, (path, content) in skill_files.items():
            json_blocks = re.findall(r"```json\s*([\s\S]*?)\s*```", content)
            self.assertGreater(len(json_blocks), 0, f"No JSON output example found in {path}")
            for idx, block in enumerate(json_blocks):
                try:
                    parsed = json.loads(block)
                except Exception as e:
                    self.fail(f"Invalid JSON block #{idx+1} in {path}:\n{block}\nError: {e}")

                if skill_name == "audit-orchestrator":
                    # Check orchestrator report schema
                    self.assertIn("site", parsed)
                    self.assertIn("audited_at", parsed)
                    self.assertIn("summary", parsed)
                    self.assertIn("findings", parsed)
                    self.assertIsInstance(parsed["findings"], list)
                    self.assertIsInstance(parsed["summary"], dict)
                    for k in ["total_findings", "critical", "high", "medium"]:
                        self.assertIn(k, parsed["summary"])
                    for finding in parsed["findings"]:
                        self.assertIn("id", finding)
                        self.assertIn("title", finding)
                        self.assertIn("severity", finding)
                        self.assertIn("evidence", finding)
                        self.assertIn("suggested_action", finding)
                        self.assertIn("summary", finding["suggested_action"])
                        self.assertIn("priority", finding["suggested_action"])
                        self.assertIn(finding["severity"], ["critical", "high", "medium"])
                        self.assertIn(finding["suggested_action"]["priority"], ["high", "medium", "low"])


class TestDocumentationCrossConsistency(unittest.TestCase):
    """Verify consistency across README.md, PROJECT.md, TEST_INFRA.md, and manifest."""

    def test_root_docs_exist_and_populated(self):
        """Verify root documentation files exist and exceed minimum content threshold."""
        for path in [README_PATH, PROJECT_MD_PATH, TEST_INFRA_PATH]:
            self.assertTrue(os.path.exists(path), f"Missing documentation file: {path}")
            size = os.path.getsize(path)
            self.assertGreater(size, 1000, f"Documentation file {path} is suspiciously small ({size} bytes)")

    def test_readme_contains_all_skills_and_cli(self):
        """Verify README.md documents all 5 skills and standard CLI patterns."""
        with open(README_PATH, "r", encoding="utf-8") as f:
            readme = f.read()

        for skill_name in EXPECTED_SKILL_NAMES:
            self.assertIn(skill_name, readme, f"Skill '{skill_name}' not mentioned in README.md")

        self.assertIn("--url", readme, "README.md missing --url CLI documentation")
        self.assertIn("run_audit.py", readme, "README.md missing run_audit.py reference")
        self.assertIn("requirements.txt", readme, "README.md missing requirements.txt reference")
        self.assertIn("Apache-2.0", readme, "README.md missing license specification")

    def test_readme_json_example_valid(self):
        """Verify all JSON code blocks in README.md parse as valid JSON."""
        with open(README_PATH, "r", encoding="utf-8") as f:
            readme = f.read()

        json_blocks = re.findall(r"```json\s*([\s\S]*?)\s*```", readme)
        self.assertGreater(len(json_blocks), 0, "No JSON example found in README.md")
        for idx, block in enumerate(json_blocks):
            try:
                parsed = json.loads(block)
            except Exception as e:
                self.fail(f"Invalid JSON block #{idx+1} in README.md: {e}")
            if "skills" in parsed or "name" in parsed:
                self.assertIn("name", parsed)
                self.assertIn("skills", parsed)
            else:
                self.assertIn("site", parsed)
                self.assertIn("findings", parsed)

    def test_project_md_consistency(self):
        """Verify PROJECT.md contracts align with marketplace.json."""
        with open(PROJECT_MD_PATH, "r", encoding="utf-8") as f:
            content = f.read()

        for skill_name in EXPECTED_SKILL_NAMES:
            self.assertIn(skill_name, content, f"Skill '{skill_name}' not mentioned in PROJECT.md")


if __name__ == "__main__":
    unittest.main()
