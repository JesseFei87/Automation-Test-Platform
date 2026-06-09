import unittest

from solve_math_captcha import (
    choose_expression,
    normalize_candidate,
    solve_expression_text,
)


class SolveMathCaptchaTests(unittest.TestCase):
    def test_normalize_candidate_keeps_math_symbols(self) -> None:
        self.assertEqual(normalize_candidate(" 4+2=? "), "4+2=?")

    def test_choose_expression_prefers_valid_math_text(self) -> None:
        self.assertEqual(choose_expression(["Q", "4+2=?", ""]), "4+2=?")

    def test_solve_expression_text_returns_answer(self) -> None:
        self.assertEqual(solve_expression_text("4+2=?"), "6")


if __name__ == "__main__":
    unittest.main()
