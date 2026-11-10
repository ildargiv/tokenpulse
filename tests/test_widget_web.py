# -*- coding: utf-8 -*-
"""Helpers of the Linux web widget.

Importing widget_web must not need GTK (CI has no display), and the address/size
helpers are what decides which page and which window the widget opens.
Run:  python3 -m unittest discover -s tests -v"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import widget_web  # noqa: E402


class WidgetWebTests(unittest.TestCase):
    def test_import_needs_no_gtk(self):
        self.assertTrue(callable(widget_web.page_url))
        self.assertTrue(widget_web.BOOT_JS.lstrip().startswith("(function"))

    def test_page_url(self):
        self.assertEqual(widget_web.page_url("127.0.0.1:8787"),
                         "http://127.0.0.1:8787/?skin=pulse")
        self.assertEqual(widget_web.page_url("http://192.168.31.30:8787", "cockpit", True),
                         "http://192.168.31.30:8787/?mini=1&skin=cockpit")
        self.assertEqual(widget_web.page_url("http://192.168.31.30:8787/", "auto"),
                         "http://192.168.31.30:8787/")

    def test_parse_wh(self):
        self.assertEqual(widget_web.parse_wh("520x900", (380, 850)), (520, 900))
        self.assertEqual(widget_web.parse_wh("", (380, 850)), (380, 850))
        self.assertEqual(widget_web.parse_wh("wide", (380, 850)), (380, 850))

    def test_agent_port(self):
        self.assertEqual(widget_web.agent_port("http://192.168.31.30:8787"), 8787)
        self.assertEqual(widget_web.agent_port("http://host:1234/path"), 1234)
        self.assertEqual(widget_web.agent_port("127.0.0.1"), 8787)

    def test_agent_alive_is_quiet_when_nothing_listens(self):
        self.assertFalse(widget_web.agent_alive("http://127.0.0.1:9"))


if __name__ == "__main__":
    unittest.main()
