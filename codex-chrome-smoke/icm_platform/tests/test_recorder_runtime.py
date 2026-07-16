import unittest

from icm_platform.recorder_runtime import CERTIFICATE_FAILURE_MESSAGE, RECORDER_INIT_SCRIPT, classify_runtime_failure


class RecorderRuntimeTests(unittest.TestCase):
    def test_certificate_failure_requires_trusted_certificate(self) -> None:
        message = classify_runtime_failure(RuntimeError("Page.goto: net::ERR_CERT_AUTHORITY_INVALID"))

        self.assertEqual(message, CERTIFICATE_FAILURE_MESSAGE)
        self.assertIn("企业根 CA", message)

    def test_click_target_is_normalized_and_anchored_to_the_interactive_parent(self) -> None:
        self.assertIn("node instanceof Element", RECORDER_INIT_SCRIPT)
        self.assertIn("[data-testid],[data-test],button,a[href],input,select,textarea,[role],[aria-label],[contenteditable=true]", RECORDER_INIT_SCRIPT)
        self.assertIn("const node = interactiveTarget(event.target);", RECORDER_INIT_SCRIPT)
        self.assertNotIn("candidates(event.target)", RECORDER_INIT_SCRIPT)


if __name__ == "__main__":
    unittest.main()
