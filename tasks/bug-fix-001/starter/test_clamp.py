import unittest

from clamp import clamp


class ClampTests(unittest.TestCase):
    def test_below_inside_and_above(self):
        self.assertEqual(clamp(-2, 0, 10), 0)
        self.assertEqual(clamp(5, 0, 10), 5)
        self.assertEqual(clamp(12, 0, 10), 10)

    def test_rejects_reversed_bounds(self):
        with self.assertRaises(ValueError):
            clamp(5, 10, 0)


if __name__ == "__main__":
    unittest.main()
