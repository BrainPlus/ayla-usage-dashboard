import unittest
from unittest.mock import patch

import matomo


class GetSessionsDeliveredTests(unittest.TestCase):
    def test_counts_only_real_deliver_visits_over_twenty_minutes(self):
        visits = [
            {
                "userId": "short-user",
                "visitDuration": 20 * 60,
                "actionDetails": [
                    {
                        "dimension10": "false",
                        "dimension14": "bundle-short",
                        "dimension5": "session-short",
                    }
                ],
            },
            {
                "userId": "real-user",
                "visitDuration": (20 * 60) + 1,
                "actionDetails": [
                    {
                        "dimension10": "false",
                        "dimension14": "bundle-real",
                        "dimension5": "session-real",
                    }
                ],
            },
            {
                "userId": "mixed-user",
                "visitDuration": 45 * 60,
                "actionDetails": [
                    {
                        "dimension10": "true",
                        "dimension14": "bundle-mixed",
                        "dimension5": "session-mixed",
                    },
                    {
                        "dimension10": "false",
                        "dimension14": "bundle-mixed",
                        "dimension5": "session-mixed",
                    },
                ],
            },
        ]

        with patch.object(matomo, "matomo_get", return_value=visits):
            result = matomo.get_sessions_delivered("2026-05-01,2026-05-31")

        self.assertEqual(
            result.to_dict("records"),
            [
                {
                    "bundle_id": "bundle-real",
                    "session_id": "session-real",
                    "user_id": "real-user",
                },
                {
                    "bundle_id": "bundle-mixed",
                    "session_id": "session-mixed",
                    "user_id": "mixed-user",
                },
            ],
        )


if __name__ == "__main__":
    unittest.main()
