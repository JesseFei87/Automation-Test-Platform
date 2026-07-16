from __future__ import annotations

import unittest

from icm_platform.generation_control import GenerationCancellationRegistry


class GenerationCancellationRegistryTests(unittest.TestCase):
    def test_stop_before_begin_blocks_persistence(self) -> None:
        registry = GenerationCancellationRegistry()
        registry.request_stop("generation-1")

        self.assertFalse(registry.begin("generation-1"))
        self.assertFalse(registry.claim_persistence("generation-1"))

    def test_stop_after_begin_blocks_persistence(self) -> None:
        registry = GenerationCancellationRegistry()

        self.assertTrue(registry.begin("generation-2"))
        self.assertTrue(registry.request_stop("generation-2"))

        self.assertFalse(registry.claim_persistence("generation-2"))

    def test_stop_is_rejected_after_persistence_is_claimed(self) -> None:
        registry = GenerationCancellationRegistry()
        registry.begin("generation-committed")

        self.assertTrue(registry.claim_persistence("generation-committed"))
        self.assertFalse(registry.request_stop("generation-committed"))

    def test_finish_releases_completed_generation(self) -> None:
        registry = GenerationCancellationRegistry()
        registry.begin("generation-3")
        registry.finish("generation-3")

        self.assertTrue(registry.begin("generation-3"))


if __name__ == "__main__":
    unittest.main()
