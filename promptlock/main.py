"""CLI entry point — registers all commands (v0.2)."""

import click
from rich.console import Console

from promptlock.commands.init_cmd import init
from promptlock.commands.save import save
from promptlock.commands.log_cmd import log
from promptlock.commands.diff import diff
from promptlock.commands.rollback import rollback
from promptlock.commands.tag import tag
from promptlock.commands.status import status
from promptlock.commands.login import login
from promptlock.commands.logout import logout
from promptlock.commands.push import push
from promptlock.commands.pull import pull

console = Console()

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}


@click.group(context_settings=CONTEXT_SETTINGS)
@click.version_option(package_name="promptlock")
def cli():
    """promptlock — version control for prompts.

    \b
    Local (no account needed):
      promptlock init
      promptlock save prompts/my-prompt.txt -m "Initial version"
      promptlock log prompts/my-prompt.txt
      promptlock diff prompts/my-prompt.txt v1 v2
      promptlock rollback prompts/my-prompt.txt v1

    \b
    Cloud registry (v0.2+):
      promptlock login
      promptlock push prompts/my-prompt.txt
      promptlock pull prompts/my-prompt.txt
    """


# Local commands (v0.1)
cli.add_command(init)
cli.add_command(save)
cli.add_command(log)
cli.add_command(diff)
cli.add_command(rollback)
cli.add_command(tag)
cli.add_command(status)

# Cloud registry commands (v0.2)
cli.add_command(login)
cli.add_command(logout)
cli.add_command(push)
cli.add_command(pull)
