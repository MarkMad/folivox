"""Folivox — local audiobook maker (book file → chaptered m4b) powered by CosyVoice 3."""

__version__ = "0.1.0.dev0"

import os as _os

# Windows without Developer Mode cannot symlink: the hub cache still works, only the warning is noise.
_os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
