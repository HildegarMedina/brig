"""Streaming secret filtering, including matches split across network chunks."""


class Redactor:
    def __init__(self, secrets: list[str]):
        self.secrets = tuple(
            sorted(
                set(value.encode() for value in secrets if value), key=len, reverse=True
            )
        )
        self.pending = b""

    def __call__(self, chunk: bytes) -> bytes:
        text = self.pending + chunk
        self.pending = b""
        output = bytearray()
        position = 0
        while position < len(text):
            remaining = len(text) - position
            # A complete short token may also be the start of a longer one.
            # Wait for another chunk before choosing which token to replace.
            if chunk and any(
                remaining < len(secret) and secret.startswith(text[position:])
                for secret in self.secrets
            ):
                self.pending = text[position:]
                break
            match = next(
                (
                    secret
                    for secret in self.secrets
                    if text.startswith(secret, position)
                ),
                None,
            )
            if match is not None:
                output.extend(b"[brig-redacted]")
                position += len(match)
            else:
                output.append(text[position])
                position += 1
        return bytes(output)
