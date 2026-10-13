"""Command-line tools installed in every development image for agents."""

# Debian package and the commands it provides. Agents rarely try tools they
# do not know about, so their instructions list these commands.
AGENT_TOOLS = {
    "bind9-dnsutils": ("dig",),
    "diffutils": ("diff",),
    "fd-find": ("fd",),
    "file": ("file",),
    "iproute2": ("ss",),
    "less": ("less",),
    "lsof": ("lsof",),
    "make": ("make",),
    "netcat-openbsd": ("nc",),
    "patch": ("patch",),
    "procps": ("ps", "top"),
    "shellcheck": ("shellcheck",),
    "sqlite3": ("sqlite3",),
    "tree": ("tree",),
    "wget": ("wget",),
    "xz-utils": ("xz",),
    "zip": ("zip",),
}
