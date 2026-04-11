from __future__ import annotations

import importlib
import os
import unittest
from unittest.mock import patch

import model_router


class ModelRouterLocalGateTests(unittest.TestCase):
    def _reload_model_router(self):
        return importlib.reload(model_router)

    def test_local_models_enabled_by_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AXON_LOCAL_MODELS", None)
            module = self._reload_model_router()
            self.assertTrue(module.LOCAL_MODELS_ENABLED)
            self.assertTrue(module.local_model_cards())

        self._reload_model_router()

    def test_local_models_can_be_explicitly_disabled(self):
        with patch.dict(os.environ, {"AXON_LOCAL_MODELS": "0"}, clear=False):
            module = self._reload_model_router()
            self.assertFalse(module.LOCAL_MODELS_ENABLED)
            self.assertEqual(module.local_model_cards(), [])

        self._reload_model_router()


if __name__ == "__main__":
    unittest.main()
