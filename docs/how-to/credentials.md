# Protect agent provider credentials

Sign in from the host, using an agent selected in the project's saved profile:

```bash
brig auth login codex --project my-api
brig auth login claude --project my-api
brig auth login opencode --project my-api
```

Brig starts a trusted, temporary native login helper without the project workspace.
Codex uses device authentication, Claude uses its native login, and OpenCode
selects OpenAI login. Follow the provider's instructions in your browser. This
requires a terminal and an account that supports the selected authentication flow.

To use an API key instead, run:

```bash
brig auth set-key codex --project my-api
brig auth set-key claude --project my-api
brig auth set-key opencode --project my-api --provider openrouter
```

The prompt hides your input. Automation can provide a key on standard input using
`--stdin`; never put the key directly in a command argument or commit it to files.
Codex supports OpenAI and Claude supports Anthropic. OpenCode supports API keys
for `openai`, `anthropic`, `google`, `openrouter`, `groq`, `mistral`, and `xai`.
Azure, AWS, Copilot, custom endpoints, and other provider authentication schemes
are not supported by the protected proxy.

After saving authentication, Brig recreates that project's proxy and agent.
Open the agent normally:

```bash
brig agent codex --project my-api
```

Logins are reused across projects for the same agent, host user, and Brig data
directory. Settings and conversation state remain private to each project.
Restart other running projects when switching between API-key and OAuth modes.
Supported OpenAI and Anthropic OAuth tokens refresh in the proxy near expiry;
a revoked or invalid login may require signing in again from the host.

## What the agent can access

The real credential store is mounted only in its separate credential proxy and
trusted authentication helper. The agent receives inert login placeholders and
public CA certificates. The proxy inserts the real credential into approved
HTTPS inference requests, verifies upstream certificates, rejects credentialed
redirects, and filters known credentials from returned streams. Its CA private
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
brig agent codex --project my-api
```

Existing login stores and nested conversation-directory volumes retain their
names. Agent runtime homes now use `brig-ID-AGENT-runtime-home`; older development
and agent home volumes are retained but not automatically copied, because they
may contain cached credentials. Keep them for selective recovery of local state.
Historical conversations may also contain secrets previously pasted or exposed;
this change does not erase those copies. See [agent isolation](agent-isolation.md).
