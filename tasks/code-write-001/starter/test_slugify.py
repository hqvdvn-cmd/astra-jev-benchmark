import unittest

from slugify import slugify


class SlugifyTests(unittest.TestCase):
    def test_words_and_symbols(self):
        self.assertEqual(slugify("  Hello,   Astra + Jev!  "), "hello-astra-jev")

    def test_unicode_letters_are_kept(self):
        self.assertEqual(slugify("Привет, Мир"), "привет-мир")


if __name__ == "__main__":
    unittest.main()
