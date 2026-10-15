# Protect agent provider credentials

`brig run` offers authentication when the selected agent has no credentials.
You can also sign in explicitly from the host, using any agent selected in the project's saved profile:

```bash
brig auth login codex --project my-api
brig auth login claude --project my-api
brig auth login opencode --project my-api
```

Brig starts a trusted, temporary native login helper without the project workspace.
Codex uses device authentication and Claude uses its native login. OpenCode opens
its native provider selector instead of forcing OpenAI. Choose a supported
provider, such as OpenCode Go, and follow its login or API-key prompt. This
requires a terminal and an account that supports the selected authentication flow.
OpenCode Go uses your Go API key; it does not require an OpenAI account.

For Go, you can also save the key directly through Brig's hidden prompt:

```bash
brig auth set-key opencode --project my-api --provider opencode-go
```

See the [OpenCode CLI authentication guide](https://opencode.ai/docs/cli/#login)
and [OpenCode Go guide](https://opencode.ai/docs/go/). After updating Brig, rerun
`./scripts/install.sh` from the checkout, then retry `brig auth login opencode`.
Brig prepares the updated credential proxy as needed; leave other active chats
before changing authentication.

To use an API key instead, run:

```bash
brig auth set-key codex --project my-api
brig auth set-key claude --project my-api
brig auth set-key opencode --project my-api --provider openrouter
```

The prompt hides your input. Automation can provide a key on standard input using
`--stdin`; never put the key directly in a command argument or commit it to files.
Codex supports OpenAI and Claude supports Anthropic. OpenCode supports API keys
for `openai`, `anthropic`, `google`, `openrouter`, `groq`, `mistral`, `xai`,
`opencode` (OpenCode Console / Zen), and `opencode-go` (OpenCode Go).
Go and Console credentials are selected independently by the inference URL.
Supported native login records are accepted for those same provider IDs.
Azure, AWS, Copilot, custom endpoints, and other provider authentication schemes
are not supported by the protected proxy.

Leave active chats before changing authentication. After saving authentication, Brig recreates that project's proxy and work container.
Open the agent normally:

```bash
brig run my-api --agent codex
```

Logins are reused across projects for the same agent, host user, and Brig data
directory. Settings and conversation state remain private to each project.
Restart other running projects when switching between API-key and OAuth modes.
For OpenCode, successful native login clears managed overrides only for providers
whose native credentials changed; unrelated provider keys remain intact. Legacy
OpenCode versions keep `auth.json`; versions that advertise auth import/export
use the protected export file. Failed login/export does not restart the agent
container or discard the previous export.
Supported OpenAI and Anthropic OAuth tokens refresh in the proxy near expiry;
a revoked or invalid login may require signing in again from the host.

## What the agent can access

The real credential store is mounted only in its separate credential proxy and
trusted authentication helper. The agent receives inert login placeholders and
public CA certificates. Codex's public login view also retains the non-secret
account and user identifiers needed for workspace discovery and Codex `/usage`.
Usage analytics requires a ChatGPT login; API-key authentication does not provide
a ChatGPT account identity. The proxy inserts the real
credential into approved HTTPS model requests and read-only Codex account/config
bootstrap, profile statistics, and usage analytics requests (including the
read-only POST queries for personal and workspace per-chat usage), verifies
upstream certificates, rejects credentialed redirects, and filters known credentials from returned streams. Its CA private
key is never mounted in the agent. Native login inside the agent cannot update
the protected login; use `brig auth` from the host.

The agent can still make authorized model requests and consume your account's
quota. It can modify or delete shared project files, read workspace secrets and
project database passwords, and access the internet. The proxy does not impose
spending limits or protect tokens you paste into chats or source files. Docker
administrators on the host can access the protected volumes.

## Upgrade existing projects

Update Brig, exit open chats, then recreate the environment:

```bash
brig down --project my-api
brig run my-api --agent codex
```

Existing login stores and nested conversation-directory volumes retain their
names. Project work containers reuse `brig-ID-AGENT-runtime-home`; older development
and legacy agent home volumes are retained but not automatically copied, because they
may contain cached credentials. Keep them for selective recovery of local state.
Historical conversations may also contain secrets previously pasted or exposed;
this change does not erase those copies. See [agent isolation](agent-isolation.md).

If a credential container exits during startup, inspect its log with
`docker logs brig-ID-credential-codex` (replace `ID` and the agent name).
`No module named brig.auth_proxy` indicates an older image whose proxy sources
are unreadable by its unprivileged user. Update Brig and run the project again;
the corrected Dockerfile triggers an image rebuild automatically.
