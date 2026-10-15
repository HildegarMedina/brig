"""Choose an installed agent before Docker starts or opens a session."""

import curses
import sys

from brig.components.agents import AGENTS, resolve_project_agent
from brig.errors import BrigError
from brig.i18n import tr


def choose_agent(project, requested=None, *, terminal=None):
    agents = project.configuration.selected_agents
    if requested is not None or len(agents) == 1:
        return resolve_project_agent(project.configuration, requested)

    def choose(ui):
        index = ui.choose(
            tr("Choose an agent for '{project}'").format(project=project.name),
            [AGENTS[agent].name for agent in agents],
        )
        return agents[index]

    if terminal is not None:
        return choose(terminal)
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise BrigError(
            tr(
                "This project has several agents. Specify --agent for run/shell or an agent name for brig agent."
            )
        )

    def pick(screen):
        from brig.ui.tui.terminal import Terminal

        return choose(Terminal(screen))

    from brig.ui.tui.terminal import tui_protocols

    with tui_protocols():
        return curses.wrapper(pick)
