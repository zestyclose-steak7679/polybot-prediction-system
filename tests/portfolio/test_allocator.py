import unittest
from portfolio.allocator import allocate

class TestAllocator(unittest.TestCase):
    def test_allocate_empty_signals(self):
        """Test that passing an empty list of signals to allocate safely returns []"""
        result = allocate([], 1000.0)
        self.assertEqual(result, [])

if __name__ == '__main__':
    unittest.main()