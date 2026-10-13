"""Agent identities, private homes, and root-only project initialization."""

import shlex

from brig.components.agents import AGENTS, INSTRUCTIONS_FILE
from brig.docker.services import agent_instructions


def agent_uid(agent, host_uid):
    return host_uid + 10000 + sorted(AGENTS).index(agent)


def agent_home(agent):
    return f"/opt/brig-agent-home/{agent}"


def agent_config(agent):
    directory = AGENTS[agent].config_directory
    return (
        agent_home(agent) + directory.removeprefix("/home/brig") if directory else None
    )


def agent_environment(agent):
    from brig.docker.auth_proxy import proxy_environment

    values = proxy_environment(agent) | {
        "HOME": agent_home(agent),
        "BRIG_AGENT": agent,
        "COMPOSER_HOME": f"{agent_home(agent)}/.config/composer",
        "COMPOSER_CACHE_DIR": f"{agent_home(agent)}/.cache/composer",
    }
    integration = AGENTS[agent]
    if integration.config_environment:
        values[integration.config_environment] = agent_config(agent)
    if agent == "opencode":
        values.update(
            XDG_DATA_HOME=f"{agent_home(agent)}/.local/share",
            XDG_STATE_HOME=f"{agent_home(agent)}/.local/state",
            OPENCODE_CONFIG_DIR=f"{agent_config(agent)}/config",
            OPENCODE_DB=f"{agent_home(agent)}/.local/state/opencode/brig.db",
        )
    return values


def java_proxy_lines(agent, maven=False):
    """Point the JVM, which ignores HTTPS_PROXY and SSL_CERT_FILE, at the proxy.

    Files live under root-owned /run/brig so an agent cannot plant links there.
    """
    from brig.docker.auth_proxy import proxy_environment

    environment = proxy_environment(agent)
    host = f"credential_{agent}"
    bypass = environment["NO_PROXY"].replace(",", "|")
    store = f"/run/brig/java/{agent}.truststore"
    options = " ".join(
        [
            f"-Djavax.net.ssl.trustStore={store}",
            "-Djavax.net.ssl.trustStorePassword=changeit",
            *[
                f"-D{scheme}.{key}={value}"
                for scheme in ("http", "https")
                for key, value in (("proxyHost", host), ("proxyPort", "8080"))
            ],
            f"-Dhttp.nonProxyHosts={bypass}",
        ]
    )
    exports = f"export JAVA_TOOL_OPTIONS={shlex.quote(options)}\\n"
    lines = [
        "mkdir -p /run/brig/java",
        # The proxy's bundle ends with its own CA, after the public roots.
        'awk \'/BEGIN CERTIFICATE/ { block = "" } { block = block $0 "\\n" } END { printf "%s", block }\' '
        f"{environment['SSL_CERT_FILE']} > /run/brig/java/{agent}.pem",
        f"rm -f {store}",
        f"cp \"$(find -L /opt/java/openjdk -path '*/lib/security/cacerts' | head -n 1)\" {store}",
        f"keytool -importcert -noprompt -alias brig-proxy -storepass changeit -keystore {store} -file /run/brig/java/{agent}.pem >/dev/null",
        f"chmod 644 {store}",
    ]
    if maven:
        settings = f"/run/brig/java/{agent}-maven-settings.xml"
        proxies = "".join(
            f"<proxy><id>brig-{scheme}</id><active>true</active>"
            f"<protocol>{scheme}</protocol><host>{host}</host><port>8080</port>"
            f"<nonProxyHosts>{bypass}</nonProxyHosts></proxy>"
            for scheme in ("http", "https")
        )
        # Maven reads proxies only from settings; this global file leaves the
        # agent's own ~/.m2/settings.xml in charge of everything else.
        lines += [
            f"printf '%s\\n' {shlex.quote(f'<settings><proxies>{proxies}</proxies></settings>')} > {settings}",
            f"chmod 644 {settings}",
        ]
        exports += (
            f"export MAVEN_ARGS={shlex.quote(f'--global-settings {settings}')}\\n"
        )
    return lines, exports


def bootstrap_script(agents, services=(), runtimes=(), tools=()):
    lines = [
        "#!/bin/sh",
        "set -eu",
        "umask 002",
        "mkdir -p /run/brig; rm -f /run/brig/ready",
        "iptables -w -n -L BRIG_AGENTS >/dev/null 2>&1 || iptables -w -N BRIG_AGENTS",
        "iptables -w -F BRIG_AGENTS",
        "iptables -w -C OUTPUT -j BRIG_AGENTS 2>/dev/null || iptables -w -I OUTPUT 1 -j BRIG_AGENTS",
        # New files inherit the shared host group; existing code stays owned by
        # its original owner. Private homes remain outside this shared tree.
        'setfacl -R -P -m "g:$(id -g brig):rwX" /workspace',
        'find /workspace -type d -exec setfacl -m "d:g:$(id -g brig):rwx" {} +',
    ]
    instructions = agent_instructions(services)
    for agent in sorted(agents):
        home, config = agent_home(agent), agent_config(agent)
        lines += [
            f"actor_uid=$(id -u brig-agent-{agent})",
            f"chmod 700 {home}",
        ]
        for other in sorted(set(agents) - {agent}):
            lines += [
                f"addresses=$(getent ahostsv4 credential_{other} | awk '{{print $1}}' | sort -u)",
                'test -n "$addresses"',
                "for address in $addresses; do",
                '    iptables -w -A BRIG_AGENTS -m owner --uid-owner "$actor_uid" -d "$address" -j REJECT',
                "done",
            ]
        if config:
            filename = ".credentials.json" if agent == "claude" else "auth.json"
            lines += [
                f'test "$(realpath -m {config})" = {config}',
                f"mkdir -p {config}",
                f"chmod 700 {config}",
                f"cp --remove-destination /opt/brig-auth/{agent}/auth.json {config}/{filename}",
                f'chown "$actor_uid:$(id -g brig)" {config}/{filename}',
                f"chmod 600 {config}/{filename}",
            ]
        exports = (
            "\\n".join(
                f"export {key}={shlex.quote(value)}"
                for key, value in agent_environment(agent).items()
            )
            + "\\numask 002\\n"
        )
        lines += [
            f"rm -f {home}/.brig-environment.sh",
            f"printf '%b' {shlex.quote(exports)} > {home}/.brig-environment.sh",
        ]
        if config:
            lines.append(
                f"cat /opt/brig-auth/{agent}/environment.sh >> {home}/.brig-environment.sh"
            )
        if config and "java" in runtimes:
            java_lines, java_exports = java_proxy_lines(agent, "maven" in tools)
            lines += java_lines + [
                f"printf '%b' {shlex.quote(java_exports)} >> {home}/.brig-environment.sh"
            ]
        lines += [
            f"rm -f {home}/{INSTRUCTIONS_FILE}",
            f"printf '%s' {shlex.quote(instructions)} > {home}/{INSTRUCTIONS_FILE}",
            f'chown -Rh "$actor_uid:$(id -g brig)" {home}',
            f'chown "$actor_uid:$(id -g brig)" {home}/.brig-environment.sh',
            f"chmod 600 {home}/.brig-environment.sh",
            f"chmod 600 {home}/{INSTRUCTIONS_FILE}",
        ]
        if config and agent == "claude":
            # The proxy holds the login, so skip Claude's interactive login step.
            # Runs as the agent so root never follows a link it planted.
            script = (
                f"f={config}/.claude.json; "
                'test -s "$f" || echo \'{}\' > "$f"; '
                'jq \'.hasCompletedOnboarding = true\' "$f" > "$f.brig" && '
                'mv "$f.brig" "$f" && chmod 600 "$f"'
            )
            lines.append(
                'setpriv --reuid "$actor_uid" --regid "$(id -g brig)" --clear-groups '
                f"sh -c {shlex.quote(script)} || true"
            )
    lines += [
        "touch /run/brig/ready",
        "exec setpriv --reuid brig --regid brig --init-groups --bounding-set=-all --no-new-privs sleep infinity",
    ]
    return "\n".join(lines) + "\n"
