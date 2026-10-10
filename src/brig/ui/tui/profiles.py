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
            f"{item.category} · {item.label}"
            + (
                " · also installs Node.js (required)"
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
                f"Fetching {component.label} versions from {source_label(component)}…"
            )
            try:
                versions = list(
                    live.compatible_versions(name, runtimes)
                    if component.runtime and runtimes is not None
                    else live.versions(name)
                )
                break
            except BrigError as error:
                self.ui.notice("Version source unavailable", [str(error)], error=True)
                if (
                    self.ui.choose(
                        "Try fetching versions again?",
                        ["Retry", "Cancel profile"],
                        default=1,
                    )
                    == 1
                ):
                    raise Cancelled from None
        if not versions:
            runtime = COMPONENTS[component.runtime]
            raise IncompatibleSelection(
                f"No verified {component.label} version supports {runtime.label} {runtimes[component.runtime]}. Choose a different runtime version or deselect this tool."
            )
        if name in defaults and defaults[name] not in versions:
            self.ui.notice(
                "Choose an available version",
                [
                    f"Previously selected {component.label} {defaults[name]} is unavailable or incompatible with the selected runtime.",
                    "Select a compatible published version. Existing versions remain unchanged.",
                ],
            )
        default = (
            versions.index(defaults[name])
            if defaults.get(name) in versions
            else versions.index(live.preferred_version(name, versions))
        )
        index = self.ui.choose(
            f"{component.label} version · {source_label(component)}",
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
            f"{component.label} requires {runtime.label}",
            [
                f"Brig installs {component.label} through npm.",
                f"{runtime.label} will also be installed because it is required.",
                "Your project can keep using Python or PHP.",
                f"Choose the {runtime.label} version next.",
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
        title = "Edit profile" if editing else "Create profile"
        live = self.app.catalog_factory()
        if not editing:
            name = self.ui.input(
                f"{title} · 1/6 · name (kebab-case)",
                required_message="Profile name is required. Enter a name to continue.",
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
                "Inherited configuration",
                [
                    *configuration_lines(inherited),
                    "Only additional components are selectable.",
                ],
            )
        defaults = local_defaults(self.app, existing)
        runtime_defaults = defaults.runtimes if defaults else {}
        tool_defaults = defaults.tools if defaults else {}
        while True:
            runtimes = {
                **pinned_runtimes,
                **self._select_versions(
                    f"{title} · 2/6 · runtimes",
                    {
                        n: item
                        for n, item in RUNTIMES.items()
                        if n not in pinned_runtimes
                    },
                    runtime_defaults,
                    live,
                    required_message=None
                    if inherited
                    else "Select a runtime with Space to continue.",
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
                        f"{title} · 3/6 · tools · compatible versions only",
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
                    "Choose a compatible runtime and tools", [str(error)], error=True
                )
        services = {
            **pinned_services,
            **self._select_versions(
                f"{title} · 4/6 · databases and caches",
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
            f"{title} · 6/6 · review",
            [
                f"Name       {name}",
                *configuration_lines(version),
                "",
                "Existing projects keep their current version.",
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
            "Profile saved",
            [
                f"{profile.name} · version {profile.latest.number}",
                f"YAML: {profile_path(self.data_directory, profile.name, profile.latest.number)}",
            ],
        )

    def delete_profile(self, name: str) -> None:
        profile = self.app.profile_for_deletion(name)
        if not self.ui.confirm(
            f"Delete profile '{profile.name}'",
            [
                f"Name       {profile.name}",
                f"Versions   {len(profile.versions)}",
                "All versions and their YAML files will be deleted.",
            ],
            action="Delete profile",
        ):
            return
        message = self.app.delete_profile(profile.name)
        self.ui.notice("Profile deleted", [message])

    def profiles(self) -> None:
        selected = 0
        while True:
            try:
                profiles = self.app.state.profiles
                records = list_rows(self.app, "profile") + ["+ Create profile"]
                index = choose_list(
                    self.ui, "Profiles", records, min(selected, len(records) - 1)
                )
                selected = index
                if index == len(profiles):
                    self.profile_wizard()
                else:
                    name = profiles[index].name
                    action = self.ui.choose(
                        name, ["View latest version", "Edit profile", "Delete profile"]
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
                self.ui.notice("Could not complete action", [str(error)], error=True)

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
                f"{title} · 5/6 · agents",
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
                else "Select at least one agent with Space to continue.",
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
                    f"{title} · default agent",
                    [AGENTS[name].name for name in agents],
                    default=default,
                )
            ]
        return agents, agent
