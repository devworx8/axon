"""
Axon database compatibility facade.

The repository implementations now live in `axon_data/`. Import `db` only when
you need the stable legacy surface used across the current codebase.
"""

from axon_data import *  # noqa: F401,F403
