"""Command-line tools installed in every development image for agents."""

# Debian package and the commands it provides. Agents rarely try tools they
# do not know about, so their instructions list these commands.
AGENT_TOOLS = {
    "bind9-dnsutils": ("dig",),
    "fd-find": ("fd",),
    "file": ("file",),
    "iproute2": ("ss",),
    "less": ("less",),
    "make": ("make",),
    "netcat-openbsd": ("nc",),
    "procps": ("ps", "top"),
    "shellcheck": ("shellcheck",),
    "sqlite3": ("sqlite3",),
    "tree": ("tree",),
}
