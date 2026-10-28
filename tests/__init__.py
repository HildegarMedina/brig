"""Brig's unit and interface behavior tests."""

import os

# Interface assertions use English regardless of the developer's locale or
# BRIG_LANG. Translation tests override this baseline with isolated environments.
os.environ["BRIG_LANG"] = "en"
