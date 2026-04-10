import unittest
from scoring.engine import estimate_edge

class TestScoringEngine(unittest.TestCase):
    def test_estimate_edge_yes(self):
        # 0.4 + 0.06 = 0.46. Edge = 0.06
        # 0.6 + 0.06 = 0.66. Edge = 0.06
        side, prob, edge = estimate_edge(0.4, 1.0)
        self.assertEqual(side, "YES")
        self.assertEqual(prob, 0.46)
        self.assertEqual(edge, 0.06)

    def test_estimate_edge_no(self):
        # 0.6 + 0.06 = 0.66. Edge = 0.06
        # 0.4 + 0.06 = 0.46. Edge = 0.06
        # floating point logic usually favors one slightly. In engine, float calculation of
        # (1-0.6) + 0.06 - (1-0.6) vs 0.6 + 0.06 - 0.6
        side, prob, edge = estimate_edge(0.6, 1.0)
        self.assertEqual(side, "NO")
        self.assertEqual(prob, 0.46)
        self.assertEqual(edge, 0.06)

    def test_estimate_edge_zero_score(self):
        side, prob, edge = estimate_edge(0.4, 0.0)
        self.assertEqual(side, "YES")
        self.assertEqual(prob, 0.4)
        self.assertEqual(edge, 0.0)

    def test_estimate_edge_half_price(self):
        side, prob, edge = estimate_edge(0.5, 0.5)
        self.assertEqual(side, "YES")
        self.assertEqual(prob, 0.53)
        self.assertEqual(edge, 0.03)

if __name__ == '__main__':
    unittest.main()
