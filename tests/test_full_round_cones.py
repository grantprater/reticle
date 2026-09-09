import sys
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'prototypes'))
from full_round_entities import RoundReader


class FullRoundCones(unittest.TestCase):
    def test_stale_sample_clears_both_masks(self):
        reader = RoundReader.__new__(RoundReader)
        reader.cone_mask = np.ones((4,4), bool)
        reader.lit_mask = reader.cone_mask.copy()
        reader.freeze = []
        with patch('full_round_entities.stalls.stalled_at', return_value=True):
            row = reader.read(None, 100)
        self.assertEqual(row['source_state'], 'stale')
        self.assertIsNone(reader.cone_mask)
        self.assertIsNone(reader.lit_mask)

    def test_no_light_has_no_residual_fraction(self):
        reader = RoundReader.__new__(RoundReader)
        reader.floor = reader.passable = np.ones((4,4), bool)
        reader.light = type('Light', (), {'known': reader.floor})()
        row = reader.cone_checks([],np.zeros((4,4),bool),[],np.zeros((4,4),bool))
        self.assertIsNone(row['residual_frac'])
        self.assertIsNone(row['aggregate']['lit_share'])


if __name__ == '__main__':
    unittest.main()
