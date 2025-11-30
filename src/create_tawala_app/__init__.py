import argparse
import keyword
import re
import shutil
import sys
import tomllib
from enum import IntEnum, StrEnum
from pathlib import Path
from typing import NoReturn, Optional

from rich import print


class ExitCode(IntEnum):
    SUCCESS = 0
    ERROR = 1
    KEYBOARD_INTERRUPT = 3


class ColorCode(StrEnum):
    """Rich markup styles for different message types."""

    SUCCESS = "bold green"
    ERROR = "bold red"
    WARNING = "bold yellow"
    INFO = "cyan"  # Changed from NOTICE - less bold, cleaner
    HIGHLIGHT = "bold cyan"  # For important values like paths
    PROMPT = "yellow"  # For user prompts
    DIM = "dim"  # For less important info


def cprint(message: str, style: ColorCode = ColorCode.INFO, end: str = "\n") -> None:
    """Colored print message using rich Console writing to stdout.

    Args:
        message: The message to print
        style: The color style to use (default: INFO)
        end: String appended after the message (default: newline)
    """
    print(f"[{style.value}]{message}[/]", end=end)


def cprint_mixed(message: str, end: str = "\n") -> None:
    """Print message that already contains rich markup tags.

    Use this when you need multiple colors in one message.
    Example: cprint_mixed(f"Created project [bold cyan]'{name}'[/] at [dim]{path}[/]")
    """
    print(message, end=end)


class ProjectNameValidator:
    """Validates and provides error messages for project names."""

    @staticmethod
    def is_valid(name: str) -> bool:
        """
        Check if a name is a valid Tawala app project name.

        Rules:
        - Must contain only letters, numbers, and underscores
        - Must start with a letter or underscore
        - Must end with a letter or number (not underscore or hyphen)
        - Cannot be a Python keyword
        - Must not be empty
        """
        if not name or keyword.iskeyword(name):
            return False

        pattern = r"^[a-zA-Z_][a-zA-Z0-9_]*[a-zA-Z0-9]$|^[a-zA-Z]$"
        return bool(re.match(pattern, name))

    @staticmethod
    def get_error_message(name: str) -> str:
        """Get a descriptive error message for an invalid package name."""
        if not name:
            return "Project name cannot be empty."

        if keyword.iskeyword(name):
            return f"'{name}' is a Python keyword and cannot be used as a project name."

        if not re.match(r"^[a-zA-Z_]", name):
            return f"'{name}' must start with a letter or underscore."

        if not re.match(r"[a-zA-Z0-9]$", name):
            return (
                f"'{name}' must end with a letter or number (not underscore or hyphen)."
            )

        if not re.match(r"^[a-zA-Z0-9_]+$", name):
            return f"'{name}' can only contain letters, numbers, and underscores. No hyphens or special characters."

        return f"'{name}' is not a valid Python package name."


class TawalaProjectCreator:
    """Handles creation of Tawala app projects."""

    def __init__(self, args: argparse.Namespace) -> None:
        self.args: argparse.Namespace = args
        self.cwd: Path = Path.cwd()
        self.project_name: Optional[str] = args.name
        self.project_path: Path = self._calculate_project_path()
        self.templates_dir: Path = Path(__file__).resolve().parent / "templates"
        self.template_name: str = args.template
        self.template_path: Path = self.templates_dir / self.template_name

    def _calculate_project_path(self) -> Path:
        """Calculate initial project path based on provided name."""
        return (self.cwd / self.project_name) if self.project_name else self.cwd

    def create(self) -> ExitCode:
        """Main method to create the project."""
        try:
            cprint("Creating Tawala app project...", ColorCode.INFO)
            if self.args.dry:
                cprint("Dry run enabled. No changes will be made.", ColorCode.WARNING)

            self._resolve_project_path()
            self._validate_project_path_availability()
            self._validate_template()
            self._create_project_structure()

            if not self.args.dry:
                self._after_creation_setup()

        except KeyboardInterrupt:
            cprint("\nOperation cancelled by user.", ColorCode.WARNING)
            return ExitCode.KEYBOARD_INTERRUPT
        except FileNotFoundError as e:
            cprint(f"Error: {str(e)}", ColorCode.ERROR)
            return ExitCode.ERROR
        except Exception as e:
            cprint(f"Unexpected Error: {str(e)}", ColorCode.ERROR)
            return ExitCode.ERROR
        else:
            self._print_success_message()
            return ExitCode.SUCCESS

    def _print_success_message(self) -> None:
        """Print success message after project creation."""
        cprint(
            f"✓ Successfully created Tawala app '{self.project_name}' using '{self.template_name}' template!",
            ColorCode.SUCCESS,
        )
        cprint_mixed(f"[dim]Project location:[/] [bold cyan]{self.project_path}[/]")

    def _resolve_project_path(self) -> None:
        """Resolve and validate the project path."""
        while True:
            if self.project_name is None:
                if not self._handle_unnamed_project():
                    continue
                break
            else:
                if not self._handle_named_project():
                    continue
                break

    def _handle_unnamed_project(self) -> bool:
        """
        Handle project creation when no name is provided.
        Returns True if resolved successfully, False to retry.
        """
        if any(self.cwd.iterdir()):
            # Current directory not empty - must provide a name
            self.project_name = self._prompt_for_project_name(
                "Current directory is not empty. Please provide a project name."
            )
            if not self.project_name:
                return False

            if not self._validate_and_set_name(self.project_name):
                self.project_name = None
                return False

            self.project_path = self.cwd / self.project_name
        else:
            # Current directory is empty - use it
            self.project_name = self.cwd.name
            if not ProjectNameValidator.is_valid(self.project_name):
                cprint(
                    ProjectNameValidator.get_error_message(self.project_name),
                    ColorCode.ERROR,
                )
                cprint(
                    "Current directory name is not a valid Python package name. Please provide a project name.",
                    ColorCode.WARNING,
                )
                self.project_name = None
                return False

        return True

    def _handle_named_project(self) -> bool:
        """
        Handle project creation when a name is provided.
        Returns True if resolved successfully, False to retry.
        """
        # First validate the name
        if self.project_name and not ProjectNameValidator.is_valid(self.project_name):
            cprint(
                ProjectNameValidator.get_error_message(self.project_name),
                ColorCode.ERROR,
            )
            self.project_name = self._prompt_for_project_name(
                "Enter a valid project name"
            )
            if not self.project_name:
                self.project_name = None
                return False
            self.project_path = self.cwd / self.project_name
            return False

        # Check if path exists (special case for empty cwd)
        if self._should_use_existing_path():
            return True

        # Name is valid
        return True

    def _should_use_existing_path(self) -> bool:
        """Check if we should use an existing path (special case for empty cwd)."""
        return (
            self.project_path.exists()
            and self.project_path == self.cwd
            and not any(self.cwd.iterdir())
        )

    def _prompt_for_project_name(self, message: str) -> str:
        """Prompt user for a project name with a custom message."""
        cprint(message, ColorCode.PROMPT)
        return input("Enter project name: ").strip()

    def _validate_and_set_name(self, name: str) -> bool:
        """Validate a project name and print error if invalid."""
        if not ProjectNameValidator.is_valid(name):
            cprint(ProjectNameValidator.get_error_message(name), ColorCode.ERROR)
            return False
        return True

    def _validate_project_path_availability(self) -> None:
        """Validate that the project path doesn't already exist or prompt for new name."""
        while True:
            # Special case: using current directory and it's empty
            if self._should_use_existing_path():
                return

            # Check if path already exists
            if self.project_path.exists():
                self.project_name = self._prompt_for_project_name(
                    f"Directory '{self.project_path}' already exists. Please choose a different project name."
                )
                if not self.project_name:
                    # User entered empty name, start over
                    self.project_name = None
                    self._resolve_project_path()
                    continue

                # Validate the new name
                if not ProjectNameValidator.is_valid(self.project_name):
                    cprint(
                        ProjectNameValidator.get_error_message(self.project_name),
                        ColorCode.ERROR,
                    )
                    continue

                # Update path with new name
                self.project_path = self.cwd / self.project_name
                continue

            # Path doesn't exist, we're good
            return

    def _validate_template(self) -> None:
        """Validate that the template exists."""
        if not self.template_path.exists() or not self.template_path.is_dir():
            self._raise_template_not_found_error()

        cprint_mixed(f"Using template: [bold cyan]{self.template_name}[/]")

    def _raise_template_not_found_error(self) -> None:
        """Raise an error with available templates listed."""
        available_templates = self._get_available_templates()
        available_msg = (
            f" Available templates: {', '.join(available_templates)}"
            if available_templates
            else ""
        )
        raise FileNotFoundError(
            f"Template '{self.template_name}' not found in {self.templates_dir}.{available_msg}"
        )

    def _get_available_templates(self) -> list[str]:
        """Get list of available template names."""
        if not self.templates_dir.exists():
            return []
        return [d.name for d in self.templates_dir.iterdir() if d.is_dir()]

    def _create_project_structure(self) -> None:
        """Create the project structure from the template."""
        if self.args.dry:
            self._show_dry_run_output()
        else:
            self._copy_template_files()

    def _show_dry_run_output(self) -> None:
        """Show what would happen in a dry run."""
        if self.project_path != self.cwd:
            cprint_mixed(
                f"[dim]Would create directory:[/] [bold cyan]{self.project_path}[/]"
            )

        cprint_mixed(
            f"[dim]Would copy template files from:[/] [bold cyan]{self.template_path}[/]"
        )
        cprint_mixed(f"[dim]Would copy to:[/] [bold cyan]{self.project_path}[/]")

        self._show_template_files_preview()

    def _show_template_files_preview(self) -> None:
        """Show a preview of files that would be copied."""
        template_files = list(self.template_path.rglob("*"))
        if not template_files:
            return

        cprint(f"Files to copy ({len(template_files)} items):", ColorCode.INFO)
        preview_limit = 10

        for file in template_files[:preview_limit]:
            relative_path = file.relative_to(self.template_path)
            cprint(f"  - {relative_path}", ColorCode.DIM)

        if len(template_files) > preview_limit:
            cprint(
                f"  ... and {len(template_files) - preview_limit} more",
                ColorCode.DIM,
            )

    def _copy_template_files(self) -> None:
        """Copy template files to the project directory."""
        if self.project_path != self.cwd:
            cprint_mixed(f"Creating directory: [bold cyan]{self.project_path}[/]")
            self.project_path.mkdir(parents=True, exist_ok=False)

        cprint_mixed(f"Copying template files to [bold cyan]{self.project_path}[/]...")

        for item in self.template_path.iterdir():
            destination = self.project_path / item.name
            if item.is_dir():
                shutil.copytree(item, destination)
            else:
                shutil.copy2(item, destination)

    def _after_creation_setup(self) -> None:
        """Perform any after-creation setup tasks."""
        self._update_pyproject_toml()
        self._update_readme()

    def _update_pyproject_toml(self) -> None:
        """Update the project name in pyproject.toml."""
        pyproject_path = self.project_path / "pyproject.toml"

        if not pyproject_path.exists():
            raise FileNotFoundError(
                f"pyproject.toml not found in project directory: {self.project_path}"
            )

        old_name = self._get_old_project_name(pyproject_path)
        self._replace_project_name_in_file(pyproject_path, old_name)

    def _get_old_project_name(self, pyproject_path: Path) -> str:
        """Extract the old project name from pyproject.toml."""
        with open(pyproject_path, "rb") as f:
            pyproject_data = tomllib.load(f)

        if "project" not in pyproject_data or "name" not in pyproject_data["project"]:
            raise KeyError("project.name not found in pyproject.toml")

        return pyproject_data["project"]["name"]

    def _replace_project_name_in_file(
        self, pyproject_path: Path, old_name: str
    ) -> None:
        """Replace the project name in pyproject.toml while preserving formatting."""
        content = pyproject_path.read_text(encoding="utf-8")

        pattern = rf'(name\s*=\s*["\']){re.escape(old_name)}(["\'])'
        updated_content = re.sub(
            pattern, rf"\g<1>{self.project_name}\g<2>", content, count=1
        )

        if updated_content == content:
            raise ValueError(
                f"Could not update project name in pyproject.toml. Pattern not found for: {old_name}"
            )

        pyproject_path.write_text(updated_content, encoding="utf-8")

    def _update_readme(self) -> None:
        """Update README.md with project name and Tawala CLI attribution."""
        readme_path = self.project_path / "README.md"

        if not readme_path.exists():
            raise FileNotFoundError(
                f"README.md not found in project directory: {self.project_path}"
            )

        readme_content = self._generate_readme_content()
        readme_path.write_text(readme_content, encoding="utf-8")

    def _generate_readme_content(self) -> str:
        """Generate README.md content."""
        return f"# {self.project_name}\n\nCreated with Tawala CLI\n"


def parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments for Tawala app creation."""
    parser = argparse.ArgumentParser(
        description="Initialize / create a new Tawala app."
    )

    parser.add_argument(
        "name",
        nargs="?",
        type=str,
        default=None,
        help=(
            "The name of the Tawala app project to create. "
            "Defaults to the current directory name if not provided. If directory is not empty, it will prompt for name. "
            "If name is provided, a new directory with that name will be created in the current directory. "
            "Scaffolding will occur inside the chosen directory."
        ),
    )

    parser.add_argument(
        "-t",
        "--template",
        dest="template",
        type=str,
        default="vercel",
        help="The project template to use. Defaults to the 'vercel' template if not specified.",
    )

    parser.add_argument(
        "--dry-run",
        "--dry",
        dest="dry",
        action="store_true",
        help="Simulate the project creation without making any changes to the file system.",
    )

    return parser.parse_args()


def main() -> NoReturn:
    """Main entry point for the CLI application."""
    args: argparse.Namespace = parse_arguments()
    exit_code: ExitCode = TawalaProjectCreator(args).create()
    sys.exit(int(exit_code))


if __name__ == "__main__":
    main()
