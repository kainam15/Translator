import json
import unittest
from urllib.parse import parse_qs

from translator_lite.client import build_request_body, parse_response


class GoogleTranslateClientTests(unittest.TestCase):
    def test_build_request_body_matches_mkewbc_shape(self) -> None:
        form = parse_qs(build_request_body("Hello", "auto", "zh-TW").decode())
        batch = json.loads(form["f.req"][0])

        self.assertEqual(batch[0][0][0], "MkEWBc")
        self.assertEqual(
            json.loads(batch[0][0][1]),
            [["Hello", "auto", "zh-TW", True], [None]],
        )

    def test_parse_live_response_shape(self) -> None:
        payload = [
            [None, None, "en"],
            [
                [
                    [
                        None,
                        None,
                        None,
                        None,
                        None,
                        [
                            ["你好，", None, None, None, None, None, "Hello, ", 1],
                            ["世界！", None, None, None, None, None, "world!", 1],
                        ],
                    ]
                ],
                "zh-CN",
            ],
            "en",
        ]
        outer = [["wrb.fr", "MkEWBc", json.dumps(payload), None, None, None, "generic"]]
        response = ")]}'\n\n" + json.dumps(outer)

        result = parse_response(response, "zh-CN")

        self.assertEqual(result.text, "你好，世界！")
        self.assertEqual(result.detected_source_language, "en")
        self.assertEqual(result.target_language, "zh-CN")


if __name__ == "__main__":
    unittest.main()
