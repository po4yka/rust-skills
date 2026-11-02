import unittest

from report import average_cents, split_amount, summarize


class SplitAmount(unittest.TestCase):
    def test_even_split(self):
        self.assertEqual(split_amount(900, 3), [300, 300, 300])

    def test_extra_cents_go_first(self):
        self.assertEqual(split_amount(100, 3), [34, 33, 33])

    def test_parts_must_be_positive(self):
        with self.assertRaises(ValueError):
            split_amount(100, 0)


class AverageCents(unittest.TestCase):
    def test_whole_mean(self):
        self.assertEqual(average_cents([100, 200, 300]), 200)

    def test_empty_is_an_error(self):
        with self.assertRaises(ValueError):
            average_cents([])


class Summarize(unittest.TestCase):
    def test_totals_by_name(self):
        lines = ["ann,100", "bob,250", "ann,50"]
        self.assertEqual(summarize(lines), "ann    150\nbob    250")


if __name__ == "__main__":
    unittest.main()
