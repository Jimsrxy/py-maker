"""Show or change the Configuration."""
import typer

from py_maker.config.settings import Settings
from py_maker.helpers import header, show_table

app = typer.Typer(no_args_is_help=True)


@app.command()
def show() -> None:
    """Show the current settings from the Configuration file."""
    header()
    settings = Settings()
    show_table(settings.get_attrs())


@app.command()
def change() -> None:
    """Change the current configuration."""
    header()
    settings = Settings()
    settings.change_settings()


@app.command()
def token() -> None:
    """Change the current configuration."""
    header()
    settings = Settings()
    settings.change_token()


@app.command(name="edit")
def edit_config() -> None:
    """Open the Configuration file in the default editor."""
    header()
    settings = Settings()
    settings.edit_config()
