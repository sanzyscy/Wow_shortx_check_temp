import unittest

from mediafire_probe import (
    SHARE_URL, choose_candidate, direct_apk_url, safe_mediafire_share
)


class MediaFireProbeTests(unittest.TestCase):
    def test_share_url(self):
        self.assertTrue(safe_mediafire_share(SHARE_URL))

    def test_unrelated_share_denied(self):
        self.assertFalse(safe_mediafire_share(
            "https://www.mediafire.com/file/OTHERID/file.apk/file"))

    def test_valid_direct_apk(self):
        self.assertTrue(direct_apk_url(
            "https://download1847.mediafire.com/token/file/Sonic+TV_1.0.1.apk"))

    def test_no_ad_host(self):
        self.assertFalse(direct_apk_url(
            "https://download1847.mediafire.com.evil.org/a.apk"))

    def test_no_non_apk(self):
        self.assertFalse(direct_apk_url(
            "https://download1847.mediafire.com/token/page.html"))

    def test_official_download_button(self):
        url = "https://download1847.mediafire.com/token/file/Sonic+TV_1.0.1.apk"
        self.assertEqual(choose_candidate([
            {"id": "fake", "href": "https://ads.example.com/file.apk",
             "class": "", "parent_id": ""},
            {"id": "downloadButton", "href": url,
             "class": "input popsok", "parent_id": "download_link"}
        ]), url)

    def test_fake_download_button_not_accepted(self):
        self.assertIsNone(choose_candidate([
            {"id": "downloadButton", "href": "https://evil.example.com/file.apk",
             "class": "", "parent_id": ""}
        ]))


if __name__ == "__main__":
    unittest.main()
