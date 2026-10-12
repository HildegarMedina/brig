"""mitmdump entry point, loaded only inside a trusted proxy container."""

import os
from pathlib import Path

from brig.auth_proxy.credentials import CredentialStore
from brig.auth_proxy.injector import CredentialInjector

addons = [
    CredentialInjector(
        CredentialStore(Path("/secrets"), os.environ["BRIG_AUTH_AGENT"]),
        Path("/public/ready"),
    )
]
