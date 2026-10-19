import unittest
from calc import add, div


class T(unittest.TestCase):
    def test_add(self):
        self.assertEqual(add(2, 3), 5)

    def test_div(self):
        self.assertEqual(div(6, 3), 2)

    def test_zero(self):
        self.assertRaises(ZeroDivisionError, div, 1, 0)
