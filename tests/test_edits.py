from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/usr/share/audio-swop'))
from edits import AudioSection, arrange_sections, split_section


class AudioSectionTests(unittest.TestCase):
    def test_split_translates_video_time_to_source_time(self):
        section = AudioSection(10, 30, 20)
        self.assertEqual(split_section(section, 26, shift=1),
                         [AudioSection(10, 15, 20), AudioSection(15, 30, 25)])
        for position in (20, 21, 41, 42):
            with self.assertRaises(ValueError):
                split_section(section, position, shift=1)

    def test_overlap_and_negative_position_trim_instead_of_mixing(self):
        arranged = arrange_sections([AudioSection(0, 10, -2), AudioSection(10, None, 7)], 20, 0)
        self.assertEqual(arranged, [AudioSection(2, 9, 0), AudioSection(10, 20, 7)])

    def test_invalid_edits_cannot_render(self):
        for sections in ([], [AudioSection(2, 1, 0)], [AudioSection(20, None, 0)],
                         [AudioSection(position=float('nan'))], [AudioSection(position=-30)]):
            with self.subTest(sections=sections), self.assertRaises(ValueError):
                arrange_sections(sections, 20, 0)

    def test_sections_can_be_reordered_and_gaps_are_preserved(self):
        self.assertEqual(arrange_sections([AudioSection(0, 2, 8), AudioSection(5, 7, 1)], 10, 0.5),
                         [AudioSection(5, 7, 1.5), AudioSection(0, 2, 8.5)])
