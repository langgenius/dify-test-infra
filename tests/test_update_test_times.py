import io
import json
import unittest
import zipfile
from unittest.mock import patch

import update_test_times as stats


def archive(data, name='durations-1.json'):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as bundle:
        bundle.writestr(name, json.dumps(data))
    return stream.getvalue()


class TimingTests(unittest.TestCase):
    def test_only_known_json_member_is_read(self):
        self.assertEqual(stats.read_observation(archive({'api/tests/test_a.py': 2}), 1), {'api/tests/test_a.py': 2})
        for name in ('../durations-1.json', 'script.py'):
            with self.assertRaises(ValueError):
                stats.read_observation(archive({'api/tests/test_a.py': 2}, name), 1)

    def test_invalid_observations_are_rejected(self):
        for value in (-1, float('nan'), float('inf'), True, '2'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                stats.read_observation(archive({'api/tests/test_a.py': value}), 1)
        for data in ([], {}, {'../file.py': 1}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                stats.read_observation(archive(data), 1)

    def test_average_prunes_deleted_files_and_handles_new_files(self):
        samples = [({}, {'a': 10, 'new': 2}), ({}, {'a': 20, 'deleted': 99})]
        self.assertEqual(stats.average_samples(samples), {'a': 15, 'new': 2})
        self.assertEqual(stats.average_samples([]), {})

    def test_missing_or_expired_shard_does_not_publish_partial_data(self):
        for artifacts in ([], [{'id': 1, 'name': 'api-unit-durations-1', 'expired': False}],
                          [{'id': 1, 'name': 'api-unit-durations-1', 'expired': True}]):
            with patch.object(stats, 'api', return_value={'artifacts': artifacts}), patch.object(stats.subprocess, 'check_output') as download:
                self.assertIsNone(stats.run_observation(123))
                download.assert_not_called()

    def test_logical_parts_are_summed_using_latest_artifacts(self):
        artifacts = [{'id': i, 'name': f'api-unit-durations-{s}', 'expired': False}
                     for i, s in ((1, 1), (2, 1), (3, 2))]
        with patch.object(stats, 'api', return_value={'artifacts': artifacts}), patch.object(
            stats.subprocess, 'check_output', side_effect=[archive({'api/test.py': 2}), archive({'api/test.py': 3}, 'durations-2.json')]
        ) as download:
            self.assertEqual(stats.run_observation(123), {'api/test.py': 5})
            self.assertIn('/artifacts/2/zip', download.call_args_list[0].args[0][-1])

    def test_only_merged_prs_with_complete_runs_are_sampled(self):
        prs = [{'number': 1, 'merged_at': None, 'head': {'sha': 'unmerged'}},
               {'number': 2, 'merged_at': '2026-09-20', 'head': {'sha': 'merged'}}]
        def fake_api(path):
            if path.startswith('pulls?'):
                return prs
            self.assertIn('head_sha=merged', path)
            self.assertIn('status=success', path)
            return {'workflow_runs': [{'id': 10, 'head_sha': 'merged'}, {'id': 9, 'head_sha': 'merged'}]}
        with patch.object(stats, 'api', side_effect=fake_api), patch.object(stats, 'run_observation', side_effect=[None, {'api/test.py': 3}]):
            samples = stats.recent_samples()
        self.assertEqual(len(samples), 1)
        self.assertEqual(samples[0][0]['pull_request'], 2)
        self.assertEqual(samples[0][0]['run_id'], 9)


if __name__ == '__main__':
    unittest.main()
