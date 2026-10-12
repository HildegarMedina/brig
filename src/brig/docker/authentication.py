"""Host-invoked authentication helpers never mount a project workspace."""

import json

from brig.components.agents import AGENTS
from brig.errors import BrigError
from brig.i18n import tr


def authenticate(engine, project, agent, *, provider=None, key=None):
    directory, image, _ = engine.workspace.plan(project, engine.uid, engine.gid)
    mount = f"type=volume,source={engine.agent_volume_name(agent)},target="
    command = [
        "docker",
        "run",
        "--rm",
        "--user",
        f"{engine.uid}:{engine.gid}",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
    ]
    if key is None:
        command.extend(
            [
                "-it",
                "--mount",
                mount + AGENTS[agent].config_directory,
                image,
            ]
        )
        native = (
            [agent, "login", "--device-auth"]
            if agent == "codex"
            else [agent, "auth", "login"]
        )
        if agent == "opencode":
            # Capture v2 exports inside protected storage; legacy CLI keeps auth.json.
            native = [
                "/bin/sh",
                "-ec",
                "umask 077; if [ -s /home/brig/.local/share/opencode/brig-export.json ]; then opencode auth import < /home/brig/.local/share/opencode/brig-export.json >/dev/null 2>&1; fi; opencode auth login openai; if opencode auth export > /home/brig/.local/share/opencode/.brig-export.tmp; then mv /home/brig/.local/share/opencode/.brig-export.tmp /home/brig/.local/share/opencode/brig-export.json; else rm -f /home/brig/.local/share/opencode/.brig-export.tmp; fi",
            ]
        command.extend(native)
        options = {}
    else:
        command.extend(
            [
                "-i",
                "--network",
                "none",
                "--mount",
                mount + "/secrets",
                f"{image}-credential-proxy",
                "python",
                "-c",
                "import json,sys; from pathlib import Path; from brig.auth_proxy.maintenance import set_api_key; data=json.load(sys.stdin); set_api_key(Path('/secrets'), data['provider'], data['key'])",
            ]
        )
        options = {
            "input": json.dumps({"provider": provider, "key": key}),
            "text": True,
            "capture_output": True,
        }
    run_helper(engine, command, options)
    if key is None:
        run_helper(
            engine,
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--user",
                f"{engine.uid}:{engine.gid}",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges:true",
                "--mount",
                mount + "/secrets",
                f"{image}-credential-proxy",
                "python",
                "-c",
                f"from pathlib import Path; from brig.auth_proxy.maintenance import clear_override; clear_override(Path('/secrets'), {agent!r})",
            ],
            {"capture_output": True, "text": True},
        )
    engine.client.run(
        [
            *engine._compose(project, directory),
            "up",
            "--detach",
            "--no-build",
            "--no-deps",
            "--force-recreate",
            "--wait",
            f"credential_{agent}",
            "dev",
        ],
        capture=False,
    )
    return tr(
        "Authentication saved for {agent}. Other running projects may need restarting."
    ).format(agent=agent)


def run_helper(engine, command, options):
    try:
        result = engine.client.runner(command, check=False, **options)
    except OSError as error:
        raise BrigError(tr("Cannot authenticate agent from the host.")) from error
    if result.returncode:
        raise BrigError(
            tr(
                "Agent authentication failed. Existing credentials were preserved where possible."
            )
        )
