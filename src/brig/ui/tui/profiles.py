"""Interactive profile selection, versions and deletion."""

from pathlib import Path

from brig.application import Application
from brig.components.agents import AGENTS
from brig.components.catalog import (
    COMPONENTS,
    RUNTIMES,
    SERVICES,
    TOOLS,
    Component,
    VersionCatalog,
)
from brig.components.providers import source_label
from brig.errors import BrigError, Cancelled, IncompatibleSelection
from brig.i18n import tr
from brig.models import ProfileVersion
from brig.persistence.profile_yaml import profile_path
from brig.profile_inheritance import resolve_base
from brig.ui.listings import list_rows
from brig.ui.presentation import configuration_lines
from brig.ui.tui.browser import choose_list
from brig.ui.tui.profile_inheritance import choose_parent, local_defaults
from brig.ui.tui.terminal import Terminal


class ProfileViews:
    def __init__(self, app: Application, terminal: Terminal, data_directory: Path):
        self.app = app
        self.ui = terminal
        self.data_directory = data_directory

    def _select_versions(
        self,
        title: str,
        catalog: dict[str, Component],
        defaults: dict[str, str],
        live: VersionCatalog,
        *,
        required_message: str | None = None,
        runtimes: dict[str, str] | None = None,
    ) -> dict[str, str]:
        if not catalog:
            return {}
        options = {
            f"{tr(item.category)} · {item.label}"
            + (
                tr(" · also installs Node.js (required)")
                if name == "playwright"
                and runtimes is not None
                and "node" not in runtimes
                else ""
            ): name
            for name, item in catalog.items()
        }
        chosen = self.ui.multiple(
            title,
            list(options),
            {label for label, name in options.items() if name in defaults},
            required_message=required_message,
        )
        names = [options[label] for label in chosen]
        result = {}
        for name in names:
            if runtimes is not None:
                self._ensure_tool_runtime(name, runtimes, live)
            result[name] = self._select_version(name, defaults, live, runtimes)
        return result

    def _select_version(
        self,
        name: str,
        defaults: dict[str, str],
        live: VersionCatalog,
        runtimes: dict[str, str] | None = None,
    ) -> str:
        component = COMPONENTS[name]
        while True:
            self.ui.loading(
                tr("Fetching {value0} versions from {value1}…").format(
                    value0=component.label, value1=source_label(component)
                )
            )
            try:
                versions = list(
                    live.compatible_versions(name, runtimes)
                    if component.runtime and runtimes is not None
                    else live.versions(name)
                )
                break
            except BrigError as error:
                self.ui.notice(
                    tr("Version source unavailable"), [str(error)], error=True
                )
                if (
                    self.ui.choose(
                        tr("Try fetching versions again?"),
                        [tr("Retry"), tr("Cancel profile")],
                        default=1,
                    )
                    == 1
                ):
                    raise Cancelled from None
        if not versions:
            runtime = COMPONENTS[component.runtime]
            raise IncompatibleSelection(
                tr(
                    "No verified {value0} version supports {value1} {value2}. Choose a different runtime version or deselect this tool."
                ).format(
                    value0=component.label,
                    value1=runtime.label,
                    value2=runtimes[component.runtime],
                )
            )
        if name in defaults and defaults[name] not in versions:
            self.ui.notice(
                tr("Choose an available version"),
                [
                    tr(
                        "Previously selected {value0} {value1} is unavailable or incompatible with the selected runtime."
                    ).format(value0=component.label, value1=defaults[name]),
                    tr(
                        "Select a compatible published version. Existing versions remain unchanged."
                    ),
                ],
            )
        default = (
            versions.index(defaults[name])
            if defaults.get(name) in versions
            else versions.index(live.preferred_version(name, versions))
        )
        index = self.ui.choose(
            tr("{value0} version · {value1}").format(
                value0=component.label, value1=source_label(component)
            ),
            [live.label(name, version) for version in versions],
            default,
            searchable=True,
        )
        return versions[index]

    def _ensure_tool_runtime(
        self, name: str, runtimes: dict[str, str], live: VersionCatalog
    ) -> None:
        component = TOOLS[name]
        required = component.runtime
        if required is None or required in runtimes:
            return
        runtime = RUNTIMES[required]
        self.ui.notice(
            tr("{value0} requires {value1}").format(
                value0=component.label, value1=runtime.label
            ),
            [
                tr("Brig installs {value0} through npm.").format(
                    value0=component.label
                ),
                tr("{value0} will also be installed because it is required.").format(
                    value0=runtime.label
                ),
                tr("Your project can keep using Python or PHP."),
                tr("Choose the {value0} version next.").format(value0=runtime.label),
            ],
        )
        runtimes[required] = self._select_version(required, {}, live)

    def profile_wizard(
        self,
        name: str | None = None,
        *,
        base: str | None = None,
        base_version: int | None = None,
        update_base: bool = False,
    ) -> None:
        editing = name is not None
        existing = self.app.profile(name).latest if editing else None
        title = tr("Edit profile") if editing else tr("Create profile")
        live = self.app.catalog_factory()
        if not editing:
            name = self.ui.input(
                tr("{value0} · 1/6 · name (kebab-case)").format(value0=title),
                required_message=tr(
                    "Profile name is required. Enter a name to continue."
                ),
                validator=self.app.validate_profile_name,
            )
        parent = choose_parent(
            self.app,
            self.ui,
            existing,
            base=base,
            base_version=base_version,
            update_base=update_base,
        )
        inherited = resolve_base(self.app.state.profiles, parent) if parent else None
        pinned_runtimes = inherited.runtimes if inherited else {}
        pinned_tools = inherited.tools if inherited else {}
        pinned_services = inherited.services if inherited else {}
        if inherited:
            self.ui.notice(
                tr("Inherited configuration"),
                [
                    *configuration_lines(inherited),
                    tr("Only additional components are selectable."),
                ],
            )
        defaults = local_defaults(self.app, existing)
        runtime_defaults = defaults.runtimes if defaults else {}
        tool_defaults = defaults.tools if defaults else {}
        while True:
            runtimes = {
                **pinned_runtimes,
                **self._select_versions(
                    tr("{value0} · 2/6 · runtimes").format(value0=title),
                    {
                        n: item
                        for n, item in RUNTIMES.items()
                        if n not in pinned_runtimes
                    },
                    runtime_defaults,
                    live,
                    required_message=None
                    if inherited
                    else tr("Select a runtime with Space to continue."),
                ),
            }
            runtime_defaults = runtimes
            available_tools = {
                n: t
                for n, t in TOOLS.items()
                if n not in pinned_tools
                and (t.runtime in runtimes or n == "playwright")
            }
            try:
                tools = {
                    **pinned_tools,
                    **self._select_versions(
                        tr("{value0} · 3/6 · tools · compatible versions only").format(
                            value0=title
                        ),
                        available_tools,
                        {
                            n: v
                            for n, v in tool_defaults.items()
                            if n in available_tools
                        },
                        live,
                        runtimes=runtimes,
                    ),
                }
                break
            except IncompatibleSelection as error:
                self.ui.notice(
                    tr("Choose a compatible runtime and tools"),
                    [str(error)],
                    error=True,
                )
        services = {
            **pinned_services,
            **self._select_versions(
                tr("{value0} · 4/6 · databases and caches").format(value0=title),
                {n: item for n, item in SERVICES.items() if n not in pinned_services},
                defaults.services if defaults else {},
                live,
            ),
        }
        agents, agent = self._select_agents(title, defaults, inherited)
        version = ProfileVersion(
            existing.number + 1 if existing else 1,
            runtimes,
            tools,
            services,
            agent,
            agents,
            parent,
        )
        if not self.ui.confirm(
            tr("{value0} · 6/6 · review").format(value0=title),
            [
                tr("Name       {value0}").format(value0=name),
                *configuration_lines(version),
                "",
                tr("Existing projects keep their current version."),
            ],
        ):
            return
        profile = self.app.save_profile(
            name,
            runtimes,
            tools,
            services,
            agent,
            agents=agents,
            editing=editing,
            catalog=live,
            base=parent.profile if parent else None,
            base_version=parent.version if parent else None,
        )
        self.ui.notice(
            tr("Profile saved"),
            [
                tr("{value0} · version {value1}").format(
                    value0=profile.name, value1=profile.latest.number
                ),
                tr("YAML: {value0}").format(
                    value0=profile_path(
                        self.data_directory, profile.name, profile.latest.number
                    )
                ),
            ],
        )

    def delete_profile(self, name: str) -> None:
        profile = self.app.profile_for_deletion(name)
        if not self.ui.confirm(
            tr("Delete profile '{value0}'").format(value0=profile.name),
            [
                tr("Name       {value0}").format(value0=profile.name),
                tr("Versions   {value0}").format(value0=len(profile.versions)),
                tr("All versions and their YAML files will be deleted."),
            ],
            action="Delete profile",
        ):
            return
        message = self.app.delete_profile(profile.name)
        self.ui.notice(tr("Profile deleted"), [message])

    def profiles(self) -> None:
        selected = 0
        while True:
            try:
                profiles = self.app.state.profiles
                records = list_rows(self.app, "profile") + [tr("+ Create profile")]
                index = choose_list(
                    self.ui, tr("Profiles"), records, min(selected, len(records) - 1)
                )
                selected = index
                if index == len(profiles):
                    self.profile_wizard()
                else:
                    name = profiles[index].name
                    action = self.ui.choose(
                        name,
                        [
                            tr("View latest version"),
                            tr("Edit profile"),
                            tr("Delete profile"),
                        ],
                    )
                    if action == 0:
                        self.ui.notice(
                            name, configuration_lines(self.app.profile(name).latest)
                        )
                    elif action == 1:
                        self.profile_wizard(name)
                    else:
                        self.delete_profile(name)
            except Cancelled:
                return
            except BrigError as error:
                self.ui.notice(
                    tr("Could not complete action"), [str(error)], error=True
                )

    def _select_agents(
        self,
        title: str,
        existing: ProfileVersion | None,
        inherited: ProfileVersion | None = None,
    ) -> tuple[list[str], str]:
        available_agents = {
            name: integration
            for name, integration in AGENTS.items()
            if integration.available
            and (inherited is None or name not in inherited.selected_agents)
        }
        agent_options = {
            f"{name} · {integration.name}": name
            for name, integration in available_agents.items()
        }
        selected_options = (
            self.ui.multiple(
                tr("{value0} · 5/6 · agents").format(value0=title),
                list(agent_options),
                {
                    option
                    for option, agent in agent_options.items()
                    if agent
                    in (
                        existing.selected_agents
                        if existing
                        else []
                        if inherited
                        else ["claude"]
                    )
                },
                required_message=None
                if inherited
                else tr("Select at least one agent with Space to continue."),
            )
            if agent_options
            else []
        )
        agents = (inherited.selected_agents if inherited else []) + [
            agent_options[option] for option in selected_options
        ]
        agent = agents[0]
        if len(agents) > 1:
            reference = existing or inherited
            default = (
                agents.index(reference.agent)
                if reference and reference.agent in agents
                else 0
            )
            agent = agents[
                self.ui.choose(
                    tr("{value0} · default agent").format(value0=title),
                    [AGENTS[name].name for name in agents],
                    default=default,
                )
            ]
        return agents, agent
