from __future__ import annotations

import argparse
import subprocess
import sys
import tomllib
from enum import IntEnum
from pathlib import Path
from typing import Any, NoReturn, Optional
from urllib.parse import urlparse

from django.core.management.color import color_style


class ExitCode(IntEnum):
    SUCCESS = 0
    ERROR = 1


class ProjectConfig:
    """Read and cache project metadata from pyproject.toml"""

    pyproject_path: Path
    _config: Optional[dict[str, Any]]

    def __init__(self, pyproject_path: Path) -> None:
        self.pyproject_path = pyproject_path
        self._config = None

    @classmethod
    def from_base_dir(cls) -> "ProjectConfig":
        """Factory constructor using the project root directory"""
        base = Path(__file__).resolve().parent.parent
        return cls(base / "pyproject.toml")

    def load(self) -> dict[str, Any]:
        """Load TOML only once. Raises FileNotFoundError or tomllib.TOMLDecodeError."""
        if self._config is None:
            with open(self.pyproject_path, "rb") as f:
                self._config = tomllib.load(f)
        # mypy-friendly cast (we just loaded it or it was previously set)
        return self._config  # type: ignore[return-value]

    @property
    def repo_url(self) -> str:
        """Return repository URL from TOML (raises ValueError if missing)."""
        urls = self.load().get("project", {}).get("urls", {})
        # urls is expected to be mapping of str->str
        url = urls.get("repository")
        if not url:
            raise ValueError("No repository URL found in project.urls")
        return url

    def sanitize_repo_path(self) -> str:
        """Strip trailing slashes and `.git` suffix."""
        path = self.repo_url.rstrip("/")
        if path.endswith(".git"):
            path = path[:-4]
        return path

    def build_actions_url(self) -> str:
        """Convert repo URL into GitHub Actions page URL; raises ValueError if not GitHub."""
        parsed = urlparse(self.sanitize_repo_path())
        if "github.com" not in parsed.netloc:
            raise ValueError("Repository URL is not a GitHub URL")
        return f"https://{parsed.netloc}{parsed.path}/actions"

    def fetch_version(self) -> str:
        """Get version from `uv` CLI. Raises CalledProcessError or ValueError."""
        result: subprocess.CompletedProcess[str] = subprocess.run(
            ["uv", "version", "--short"],
            check=True,
            capture_output=True,
            text=True,
        )
        version = result.stdout.strip()
        if not version:
            raise ValueError("Version output was empty")
        return version


class GitPublisher:
    """Encapsulate git tagging and pushing"""

    config: ProjectConfig

    def __init__(self, config: ProjectConfig) -> None:
        self.config = config
        self.style = color_style()

    def tag(self, version: str, dry: bool) -> str:
        """Create git tag and return tag string (e.g. 'v1.2.3')."""
        tag = f"v{version}"
        cmd = ["git", "tag", "-a", tag, "-m", f"Release {version}"]

        if dry:
            print(self.style.WARNING(f"Would run: {' '.join(cmd)}"))
        else:
            subprocess.run(cmd, check=True, capture_output=True, text=True)

        return tag

    def push(self, dry: bool) -> None:
        """Push tags to origin."""
        cmd = ["git", "push", "origin", "--tags"]
        if dry:
            print(self.style.WARNING("Would run: git push origin --tags"))
        else:
            subprocess.run(cmd, check=True, capture_output=True, text=True)


def publish(dry_run: bool = False) -> ExitCode:
    style = color_style()

    if dry_run:
        print(style.NOTICE("DRY RUN MODE - no changes will be made\n"))

    try:
        cfg = ProjectConfig.from_base_dir()
        version = cfg.fetch_version()
        actions_url = cfg.build_actions_url()

        pub = GitPublisher(cfg)
        tag = pub.tag(version, dry_run)
        pub.push(dry_run)

    except FileNotFoundError as e:
        # e.filename can be None; guard for that
        filename = getattr(e, "filename", None)
        if filename:
            print(style.ERROR(f"File not found: {filename}"))
        else:
            print(style.ERROR("File not found"))
        return ExitCode.ERROR

    except subprocess.CalledProcessError as e:
        # e.cmd may be list[str] or None; format defensively
        cmd = " ".join(map(str, e.cmd)) if e.cmd else "<cmd>"
        print(style.ERROR(f"Command failed: {cmd}"))
        print(style.ERROR(f"Return code: {e.returncode}"))
        if getattr(e, "stdout", None):
            print(style.ERROR(f"stdout: {e.stdout}"))
        if getattr(e, "stderr", None):
            print(style.ERROR(f"stderr: {e.stderr}"))
        return ExitCode.ERROR

    except tomllib.TOMLDecodeError as e:
        print(style.ERROR(f"Failed to parse pyproject.toml: {str(e)}"))
        return ExitCode.ERROR

    except ValueError as e:
        print(style.ERROR(f"Configuration error: {str(e)}"))
        return ExitCode.ERROR

    except Exception as e:
        print(style.ERROR(f"Unexpected error: {str(e)}"))
        return ExitCode.ERROR

    else:
        if dry_run:
            print(style.SUCCESS(f"Tag {tag} would be pushed successfully."))
            print(style.SUCCESS("GitHub Actions workflow would trigger."))
        else:
            print(style.SUCCESS(f"Tag {tag} pushed successfully!"))
            print(style.NOTICE(f"Monitor workflow: {actions_url}"))

        return ExitCode.SUCCESS


def main() -> NoReturn:
    parser = argparse.ArgumentParser(
        description="Create and push git tag to trigger publishing workflow",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Example:\n  publish.py --dry-run",
    )

    parser.add_argument(
        "--dry",
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Preview commands without execution",
    )

    args = parser.parse_args()
    sys.exit(publish(args.dry_run))


if __name__ == "__main__":
    main()
