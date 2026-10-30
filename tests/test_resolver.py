import base64
import json
import unittest

from shortx_resolver import (
    decode_safelink_redirect, key_of, safe_url,
    choose_control, is_intermediary,
)


class ResolverTests(unittest.TestCase):
    def test_decode_metadata(self):
        obj = {
            "second_safelink_url": "",
            "safelink": "https://shortxlinks.com/8ciL1",
        }
        token = base64.b64encode(json.dumps(obj).encode()).decode()
        url = "https://mtc1.thedayspring.in?safelink_redirect=" + token
        self.assertEqual(decode_safelink_redirect(url), obj)

    def test_invalid_encoded_data(self):
        self.assertEqual(
            decode_safelink_redirect(
                "https://example.com?safelink_redirect=%25"), {})

    def test_changing_ad_token_ignored(self):
        first = "https://shortxlinks.com/8ciL1?foo=123"
        second = "https://shortxlinks.com/8ciL1?foo=456"
        self.assertEqual(key_of(first), key_of(second))

    def test_url_safety(self):
        self.assertFalse(safe_url("javascript:alert(1)"))
        self.assertFalse(safe_url("https://name:password@example.com"))
        self.assertTrue(safe_url("https://shortxlinks.com/8ciL1"))

    def test_intermediaries(self):
        self.assertTrue(is_intermediary(
            "https://mtc1.rbprompt.in/?adlinkfly=8ciL1"))
        self.assertFalse(is_intermediary("https://example.org/download"))

    def test_ignore_generic_ad(self):
        controls = [{
            "visible": True, "id": "ad", "text": "Continue",
            "href": "https://ads.example.org", "cls": "", "onclick": ""
        }]
        self.assertIsNone(choose_control(controls))

    def test_priority_wp_safelink(self):
        controls = [
            {"visible": True, "id": "ad", "text": "Verify Your Loan",
             "href": "", "cls": "", "onclick": ""},
            {"visible": True, "id": "wpsafelinkhuman",
             "text": "I'm not robot", "href": "", "cls": "",
             "onclick": ""}
        ]
        self.assertEqual(choose_control(controls)["index"], 1)


if __name__ == "__main__":
    unittest.main()
