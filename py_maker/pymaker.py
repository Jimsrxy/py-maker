"""Class to encapsulate the application."""
from __future__ import annotations

import importlib.resources as pkg_resources
import os
import re
import shutil
import subprocess  # nosec
import sys
from pathlib import Path, PurePath
from typing import TYPE_CHECKING, Dict

from git.exc import GitError
from git.repo import Repo
from jinja2 import Environment, FileSystemLoader
from rich import print  # pylint: disable=W0622

from py_maker import template
from py_maker.config.settings import Settings
from py_maker.constants import MKDOCS_CONFIG, ExitErrors, license_names
from py_maker.helpers import (
    exists_on_pypi,
    get_current_year,
    get_file_list,
    get_title,
    header,
    sanitize,
)
from py_maker.prompt import Confirm, Prompt
from py_maker.schema import ProjectValues

if TYPE_CHECKING:
    from importlib.resources.abc import Traversable


class PyMaker:
    """PyMaker class."""

    def __init__(self, location: str, options: Dict[str, bool]) -> None:
        """Initialize the PyMaker class."""
        self.choices: ProjectValues = ProjectValues()
        self.location: str = location
        self.options: Dict[str, bool] = options

        header()

        self.settings = Settings()

        if len(Path(self.location).parts) > 1:
            print(
                "[red]  -> Error: Location must be a single directory name, "
                "and is relative to the current directory.\n"
            )
            sys.exit(ExitErrors.LOCATION_ERROR)

    def confirm_values(self) -> bool:
        """Confirm the values entered by the user."""
        print(
            "\n[green][bold]Creating a New Python app with the below "
            "settings :\n"
        )

        padding: int = max(len(key) for key, _ in self.choices) + 3

        for key, value in self.choices:
            print(f"{get_title(key).rjust(padding)} : [green]{value}")

        return Confirm.ask("\nIs this correct?", default=True)

    # ------------------------------------------------------------------------ #
    #                   create the project skeleton folders.                   #
    # ------------------------------------------------------------------------ #
    def create_folders(self) -> None:
        """Create the root folder for the project."""
        try:
            print("--> Creating project folder ... ", end="")
            if self.location != ".":
                self.choices.project_dir.mkdir()
            print("[green]Done[/green]")
        except FileExistsError:
            print(
                f"\n[red]  -> Error: Directory '{self.choices.project_dir}' "
                "already exists.\n"
            )
            sys.exit(ExitErrors.DIRECTORY_EXISTS)
        except PermissionError:
            print(
                "\n[red]  -> Error: Permission denied creating directory "
                f"'{self.choices.project_dir}'\n"
            )
            sys.exit(ExitErrors.PERMISSION_DENIED)

    # ------------------------------------------------------------------------ #
    #             Copy the template files to the project directory.            #
    # ------------------------------------------------------------------------ #
    def copy_files(self, template_dir: Traversable, file_list: list[str]):
        """Copy the template files to the project directory.

        Expand the jinja templates before copying.
        """
        jinja_env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            autoescape=True,
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True,
        )
        for file in file_list:
            with pkg_resources.as_file(template_dir / file) as src:
                if src.is_dir():
                    Path(self.choices.project_dir / file).mkdir()
                elif src.suffix == ".jinja":
                    jinja_template = jinja_env.get_template(str(file))
                    dst = self.choices.project_dir / Path(file).with_suffix("")
                    dst.write_text(
                        jinja_template.render(
                            self.choices.model_dump(),
                            slug=self.choices.project_dir.name,
                            options=self.options,
                        )
                    )
                else:
                    dst = self.choices.project_dir / file
                    dst.write_text(src.read_text(encoding="UTF-8"))

    def generate_template(self) -> None:
        """Copy the template files to the project directory.

        Any file that has the '.jinja' extension will be passed though the
        template engine before copying. The extension will also be removed.

        ie:
        'README.md.jinja' is copied as 'README.md' after template substitution.
        """
        try:
            # ---------------- copy the default template files --------------- #
            template_dir = pkg_resources.files(template)
            if self.settings.use_default_template:
                file_list = get_file_list(template_dir)
                self.copy_files(template_dir, file_list)

            # --------- copy the custom template files if they exist --------- #
            custom_template_dir = Path(self.settings.template_folder)
            if custom_template_dir.exists():
                file_list = get_file_list(custom_template_dir)
                self.copy_files(custom_template_dir, file_list)  # type: ignore

            # ---------------- generate the license file next. ------------- #
            if self.choices.license != "None":
                license_env = Environment(
                    loader=FileSystemLoader(str(template_dir / "../licenses")),
                    autoescape=True,
                    keep_trailing_newline=True,
                )
                license_template = license_env.get_template(
                    f"{self.choices.license}.jinja"
                )
                dst = self.choices.project_dir / "LICENSE.txt"
                dst.write_text(
                    license_template.render(
                        author=self.choices.author, year=get_current_year()
                    )
                )

            # ---------- rename or delete the 'app' dir if required ---------- #
            if self.choices.package_name != "-":
                Path(self.choices.project_dir / "app").rename(
                    self.choices.project_dir / self.choices.package_name
                )
            else:
                # move the main.py into the root project folder and delete app
                Path(self.choices.project_dir / "app" / "main.py").rename(
                    Path(self.choices.project_dir / "main.py")
                )
                shutil.rmtree(self.choices.project_dir / "app")

            # ----------- remove the 'test' folder if not required ----------- #
            if not self.options["test"]:
                shutil.rmtree(self.choices.project_dir / "tests")
        except OSError as exc:
            print(f"\n[red]  -> {exc}")
            sys.exit(ExitErrors.OS_ERROR)

    # ------------------------------------------------------------------------ #
    #                create the git repository for the project.                #
    # ------------------------------------------------------------------------ #
    def create_git_repo(self) -> None:
        """Create a Git repository for the project and add the first commit."""
        if not self.options["git"]:
            return
        try:
            print("\n--> Creating Git repository ... ", end="")
            repo = Repo.init(self.choices.project_dir)
            repo.index.add(repo.untracked_files)
            repo.index.commit("Initial Commit")
            print("[green]Done[/green]")
        except GitError as exc:
            print("Error: ", exc)
            sys.exit(ExitErrors.GIT_ERROR)

    # ------------------------------------------------------------------------ #
    #                       display post-process messages                      #
    # ------------------------------------------------------------------------ #
    def post_process(self) -> None:
        """Display steps to be carried out after the project is created.

        Currently just prints messages on what to do next.
        """
        output = f"""
--> [green]Project created successfully.[/green]

[bold]Next steps:[/bold]

    1) Change to the project directory:
    2) Install the dependencies if not done (creates a virtual environment):
        'poetry install'
    3) Activate the virtual environment:
        'poetry shell'
    4) Run the application:
        '{self.location}'
    5) Code!

See the [bold][green]README.md[/green][/bold] file for more information.
        """
        print(output)

    def get_sanitized_package_name(self, pk_name: str) -> str:
        """Return a sanitized package name from user input."""
        while True:
            name = Prompt.ask(
                "Package Name? (Use '-' for standalone script)",
                default=pk_name
                if pk_name != "."
                else sanitize(self.choices.project_dir.name),
            )
            # a single '-' is ok as it means a standalone script.
            if name == "-":
                self.choices.standalone = True
                break

            # note: not happy with this nested if/else, but it works for now.
            # will fix during the next refactor.
            if not re.search(r"[- .]", name):
                if exists_on_pypi(name):
                    print(
                        "\n[red]Warning: Package name already exists on PyPI."
                    )
                    confirm = Confirm.ask(
                        "Do you want to use it anyway?", default=False
                    )
                    if confirm:
                        print(
                            "\n[red]Warning: Using an existing package name "
                            "will mean it [b]cannot be uploaded to PyPI.\n"
                        )
                        break
                else:
                    break
            else:
                print(
                    "\n[red]Error: Package name cannot contain dashes, dots or "
                    "spaces. Please use Underscores if required.\n"
                )
        return name

    # ------------------------------------------------------------------------ #
    #             The main application loop is on the .run() method.           #
    # ------------------------------------------------------------------------ #
    def run(self) -> None:
        """Entry point for the application."""
        self.choices.project_dir = Path.cwd() / self.location

        # ensure that the chosen location is empty.
        if (
            self.choices.project_dir.exists()
            and len(os.listdir(self.choices.project_dir)) > 0
        ):
            print(
                "\n[red]Error: The chosen folder is not empty. "
                "Please specify a different location.[/red]\n"
            )
            sys.exit(ExitErrors.FOLDER_NOT_EMPTY)

        print(
            "[green]Creating a new project at[/green] "
            f"{self.choices.project_dir}\n"
        )

        if self.options["accept_defaults"]:
            self.choices.name = get_title(
                PurePath(self.choices.project_dir).name
            )
            self.choices.package_name = sanitize(self.choices.project_dir.name)
            self.choices.description = ""
            self.choices.author = self.settings.author_name
            self.choices.email = self.settings.author_email
            self.choices.license = self.settings.default_license
            self.choices.standalone = False
        else:
            self.choices.name = Prompt.ask(
                "Name of the Application?",
                default=get_title(PurePath(self.choices.project_dir).name),
            )
            pk_name = sanitize(self.location)
            self.choices.package_name = self.get_sanitized_package_name(pk_name)

            # if this is not a standalone script, ask for more details, useful
            # for PypI uploads.
            if not self.choices.standalone:
                self.choices.homepage = Prompt.ask("Homepage URL?", default="")

                self.choices.repository = Prompt.ask(
                    "Repository URL?",
                    default=(
                        "https://github.com/your_user_name/"
                        f"{self.choices.package_name}"
                    ),
                )

            self.choices.description = Prompt.ask(
                "Description of the Application?",
            )
            self.choices.author = Prompt.ask(
                "Author Name?", default=self.settings.author_name
            )

            self.choices.email = Prompt.ask(
                "Author Email?", default=self.settings.author_email
            )
            self.choices.license = Prompt.ask(
                "Application License?",
                choices=license_names,
                default=self.settings.default_license,
            )

            if self.choices.package_name == "-":
                self.choices.standalone = True

            if not self.confirm_values():
                # User chose not to continue
                print("\n[red]Aborting![/red]")
                sys.exit(ExitErrors.USER_ABORT)

            print()

        self.create_folders()
        self.generate_template()

        # run poetry install if required
        if self.options["accept_defaults"] or Confirm.ask(
            "\nShould I Run 'poetry install' now?", default=True
        ):
            os.chdir(self.choices.project_dir)
            subprocess.run(["poetry", "install"], check=True)  # nosec

            if self.options["docs"]:
                print("\n--> Creating MkDocs project")
                subprocess.run(  # nosec
                    ["poetry", "run", "mkdocs", "new", "."], check=True
                )
                # now copy the custom mkdocs.yml file
                (self.choices.project_dir / "mkdocs.yml").write_text(
                    MKDOCS_CONFIG.format(name=self.choices.name)
                )

            if Confirm.ask(
                "\nDo you want to install and update the [bold]"
                "pre-commit[/bold] hooks?",
                default=True,
            ):
                subprocess.run(
                    ["poetry", "run", "pre-commit", "install"], check=True
                )  # nosec
                subprocess.run(
                    ["poetry", "run", "pre-commit", "autoupdate"], check=True
                )  # nosec

        self.create_git_repo()
        self.post_process()
