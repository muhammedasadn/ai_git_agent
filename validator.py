"""
validator.py
============
Pre-commit validation module.

Before the agent commits code, this module:
1. Detects what kind of project we're in (CMake, Python, Node.js, etc.)
2. Runs the appropriate build or test command
3. Returns pass/fail with output

This prevents committing broken code — just like a real CI pipeline,
but running locally before the commit even happens.
"""

import subprocess
import os
from enum import Enum
from typing import Optional


# ─────────────────────────────────────────────
# Project Type Detection
# ─────────────────────────────────────────────

class ProjectType(Enum):
    CMAKE = "cmake"
    PYTHON = "python"
    NODE = "node"
    RUST = "rust"
    MAKEFILE = "makefile"
    UNKNOWN = "unknown"


def detect_project_type(path: str) -> ProjectType:
    """
    Detect the type of project in the given directory.
    Checks for signature files like CMakeLists.txt, setup.py, package.json, etc.
    """
    checks = [
        (ProjectType.CMAKE, ["CMakeLists.txt"]),
        (ProjectType.PYTHON, ["setup.py", "pyproject.toml", "requirements.txt", "setup.cfg"]),
        (ProjectType.NODE, ["package.json"]),
        (ProjectType.RUST, ["Cargo.toml"]),
        (ProjectType.MAKEFILE, ["Makefile", "GNUmakefile"]),
    ]

    for project_type, signatures in checks:
        for sig in signatures:
            if os.path.exists(os.path.join(path, sig)):
                return project_type

    # Check if there are Python files even without a setup.py
    for f in os.listdir(path):
        if f.endswith(".py"):
            return ProjectType.PYTHON

    return ProjectType.UNKNOWN


# ─────────────────────────────────────────────
# Validation Result
# ─────────────────────────────────────────────

class ValidationResult:
    """Holds the result of a validation run."""

    def __init__(self, passed: bool, project_type: str, command: str,
                 output: str = "", error: str = "", skipped: bool = False):
        self.passed = passed
        self.project_type = project_type
        self.command = command
        self.output = output
        self.error = error
        self.skipped = skipped

    def __str__(self):
        if self.skipped:
            return f"[SKIPPED] No validation configured for {self.project_type}"
        status = "PASSED ✓" if self.passed else "FAILED ✗"
        return f"[{status}] {self.project_type} — `{self.command}`"

    def summary(self) -> str:
        """Return a short summary string."""
        if self.skipped:
            return f"Skipped (unknown project type: {self.project_type})"
        if self.passed:
            return f"Build/tests passed ({self.project_type})"
        lines = (self.error or self.output).strip().splitlines()
        snippet = "\n".join(lines[-10:]) if lines else "No output"
        return f"Build/tests FAILED:\n{snippet}"


# ─────────────────────────────────────────────
# Command Runner
# ─────────────────────────────────────────────

def _run_command(cmd: str, cwd: str, timeout: int = 120) -> tuple[int, str, str]:
    """Run a shell command and return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return 1, "", f"Command timed out after {timeout}s: {cmd}"
    except Exception as e:
        return 1, "", str(e)


# ─────────────────────────────────────────────
# Project-Specific Validators
# ─────────────────────────────────────────────

def _validate_cmake(path: str, build_dir: str) -> ValidationResult:
    """
    Validate a CMake project.
    1. Create build directory if needed
    2. Run cmake ..
    3. Run cmake --build .
    """
    full_build_dir = os.path.join(path, build_dir)

    # Step 1: Create build dir
    os.makedirs(full_build_dir, exist_ok=True)

    # Step 2: Configure
    code, out, err = _run_command("cmake ..", full_build_dir)
    if code != 0:
        return ValidationResult(
            passed=False,
            project_type="cmake",
            command="cmake ..",
            output=out,
            error=err
        )

    # Step 3: Build
    code, out, err = _run_command("cmake --build . --parallel", full_build_dir)
    return ValidationResult(
        passed=(code == 0),
        project_type="cmake",
        command="cmake --build .",
        output=out,
        error=err
    )


def _validate_python(path: str, test_command: str) -> ValidationResult:
    """
    Validate a Python project.
    Tries to run tests if a test runner is available.
    Falls back to syntax checking with py_compile.
    """
    # Try the configured test command
    code, out, err = _run_command(test_command, path, timeout=60)

    if code == 0:
        return ValidationResult(
            passed=True,
            project_type="python",
            command=test_command,
            output=out,
            error=err
        )

    # If pytest not found, fall back to syntax check
    if "not found" in err.lower() or "no module named pytest" in err.lower():
        # Syntax-check all Python files
        py_files = _find_python_files(path)
        if py_files:
            files_str = " ".join(f'"{f}"' for f in py_files[:20])
            syntax_cmd = f"python -m py_compile {files_str}"
            code2, out2, err2 = _run_command(syntax_cmd, path)
            return ValidationResult(
                passed=(code2 == 0),
                project_type="python",
                command="py_compile (syntax check)",
                output=out2,
                error=err2
            )

    return ValidationResult(
        passed=(code == 0),
        project_type="python",
        command=test_command,
        output=out,
        error=err
    )


def _validate_node(path: str) -> ValidationResult:
    """
    Validate a Node.js project.
    Runs `npm test` or `npm run build` if defined in package.json.
    """
    import json

    pkg_path = os.path.join(path, "package.json")
    try:
        with open(pkg_path) as f:
            pkg = json.load(f)
    except Exception:
        pkg = {}

    scripts = pkg.get("scripts", {})

    # Try test first, then build
    if "test" in scripts:
        cmd = "npm test -- --passWithNoTests 2>/dev/null || npm test"
        code, out, err = _run_command(cmd, path, timeout=90)
    elif "build" in scripts:
        cmd = "npm run build"
        code, out, err = _run_command(cmd, path, timeout=90)
    else:
        return ValidationResult(
            passed=True,
            project_type="node",
            command="(no test/build script found)",
            skipped=True
        )

    return ValidationResult(
        passed=(code == 0),
        project_type="node",
        command=cmd,
        output=out,
        error=err
    )


def _validate_rust(path: str) -> ValidationResult:
    """Run `cargo check` for Rust projects (faster than full build)."""
    code, out, err = _run_command("cargo check", path, timeout=120)
    return ValidationResult(
        passed=(code == 0),
        project_type="rust",
        command="cargo check",
        output=out,
        error=err
    )


def _validate_makefile(path: str) -> ValidationResult:
    """Run `make` for Makefile projects."""
    code, out, err = _run_command("make", path, timeout=120)
    return ValidationResult(
        passed=(code == 0),
        project_type="makefile",
        command="make",
        output=out,
        error=err
    )


def _find_python_files(path: str, max_depth: int = 3) -> list[str]:
    """Find Python files in the project (limited depth)."""
    py_files = []
    for root, dirs, files in os.walk(path):
        # Limit depth
        depth = root[len(path):].count(os.sep)
        if depth >= max_depth:
            dirs.clear()
            continue
        # Skip common non-source dirs
        dirs[:] = [d for d in dirs if d not in {
            ".git", "__pycache__", "venv", "env", ".env",
            "node_modules", "build", "dist", ".tox"
        }]
        for f in files:
            if f.endswith(".py"):
                py_files.append(os.path.join(root, f))
    return py_files


# ─────────────────────────────────────────────
# Public Interface
# ─────────────────────────────────────────────

class Validator:
    """
    Main validator class used by the agent.

    Usage:
        validator = Validator(config)
        result = validator.run(repo_path)
        if not result.passed:
            print("Build failed!")
    """

    def __init__(self, config: dict):
        val_config = config.get("validation", {})
        self.enabled = val_config.get("enabled", True)
        self.fail_on_error = val_config.get("fail_on_error", True)
        self.cmake_build_dir = val_config.get("cmake_build_dir", "build")
        self.python_test_command = val_config.get("python_test_command", "python -m pytest --tb=short -q")

    def run(self, path: str, project_type: Optional[ProjectType] = None) -> ValidationResult:
        """
        Run validation for the project at the given path.
        Auto-detects project type if not specified.
        """
        if not self.enabled:
            return ValidationResult(
                passed=True,
                project_type="disabled",
                command="(validation disabled in config)",
                skipped=True
            )

        if project_type is None:
            project_type = detect_project_type(path)

        if project_type == ProjectType.CMAKE:
            return _validate_cmake(path, self.cmake_build_dir)
        elif project_type == ProjectType.PYTHON:
            return _validate_python(path, self.python_test_command)
        elif project_type == ProjectType.NODE:
            return _validate_node(path)
        elif project_type == ProjectType.RUST:
            return _validate_rust(path)
        elif project_type == ProjectType.MAKEFILE:
            return _validate_makefile(path)
        else:
            return ValidationResult(
                passed=True,
                project_type="unknown",
                command="(no validator for this project type)",
                skipped=True
            )

    def detect(self, path: str) -> ProjectType:
        """Public method to detect project type."""
        return detect_project_type(path)