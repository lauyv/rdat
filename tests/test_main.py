import os
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import yaml

from main import (
    BLOCK_DOMAIN,
    BLOCK_DOMAIN_REGEX,
    BLOCK_DOMAIN_SUFFIX,
    _run,
    clean_domains,
    parse_dlc_plain,
    parse_gfwlist_text,
    release,
    release_quanx_file,
)


class ParseDLCTests(unittest.TestCase):
    def test_collects_ads_and_keeps_shared_cn_rules_in_both_lists(self):
        ad_rules = [
            "full:shared.example:@cn,@ads",
            "domain:ads.example:@ads,@other",
            "keyword:advertising:@ads",
            r"regexp:^ads[0-9]+\.example$:@ads",
        ]
        source = {
            "lists": [
                {"name": "category-ads-all", "rules": ["domain:base.example"]},
                {"name": "geolocation-cn", "rules": []},
                {
                    "name": "vendor",
                    "rules": ad_rules
                    + [
                        "full:negated.example:@!ads",
                        "full:similar.example:@ads2",
                        "full:untagged.example",
                    ],
                },
                {"name": "duplicate", "rules": ad_rules},
            ]
        }
        for tags in (("category-ads-all",), ("category-ads-all", "geolocation-cn")):
            with (
                self.subTest(tags=tags),
                patch(
                    "main.urlopen",
                    return_value=BytesIO(yaml.safe_dump(source).encode()),
                ),
            ):
                rules = parse_dlc_plain("fixture", tags)
            self.assertEqual(
                rules["category-ads-all"],
                (
                    ["shared.example"],
                    ["base.example", "ads.example"],
                    ["advertising"],
                    [r"^ads[0-9]+\.example$"],
                ),
            )
            if "geolocation-cn" in tags:
                self.assertEqual(
                    rules["geolocation-cn"], (["shared.example"], [], [], [])
                )

    def test_collects_cn_from_all_lists_and_deduplicates_each_rule_type(self):
        apple = "full:init-p01st.push.apple.com:@cn"
        source = {
            "lists": [
                {"name": "geolocation-cn", "rules": ["domain:base.cn", apple]},
                {"name": "geolocation-!cn", "rules": ["domain:apple.com"]},
                {
                    "name": "apple",
                    "rules": [
                        apple,
                        "full:extra.example:@ads,@cn",
                        "domain:cdn.example:@cn,@other",
                        "keyword:china-service:@cn",
                        r"regexp:^cn[0-9]+\.example$:@cn",
                        "full:foreign.example:@!cn",
                        "full:similar.example:@cn2",
                        "full:untagged.example",
                    ],
                },
                {
                    "name": "duplicate",
                    "rules": [
                        apple,
                        "keyword:china-service:@cn",
                        r"regexp:^cn[0-9]+\.example$:@cn",
                    ],
                },
            ]
        }
        with patch(
            "main.urlopen", return_value=BytesIO(yaml.safe_dump(source).encode())
        ):
            rules = parse_dlc_plain("fixture", ("geolocation-cn", "geolocation-!cn"))
        self.assertEqual(
            rules["geolocation-cn"],
            (
                ["init-p01st.push.apple.com", "extra.example"],
                ["base.cn", "cdn.example"],
                ["china-service"],
                [r"^cn[0-9]+\.example$"],
            ),
        )
        self.assertEqual(rules["geolocation-!cn"], ([], ["apple.com"], [], []))

    def test_missing_cn_list_is_still_an_error(self):
        source = b'lists:\n- name: apple\n  rules: ["full:example.com:@cn"]\n'
        with (
            patch("main.urlopen", return_value=BytesIO(source)),
            self.assertRaisesRegex(ValueError, "Missing DLC tags: geolocation-cn"),
        ):
            parse_dlc_plain("fixture", ("geolocation-cn",))


class RunTests(unittest.TestCase):
    def test_run_merges_manual_suffixes_and_uses_reject_policy(self) -> None:
        upstream = {
            "category-ads-all": (["ads.example"], ["upstream.example"], [], []),
            "geolocation-!cn": ([], ["foreign.example"], [], []),
            "geolocation-cn": ([], ["local.example"], [], []),
        }
        gfwlist = {tag: ([], [], [], []) for tag in ("gfw", "gfw-skip")}
        with (
            patch("main.parse_dlc_plain", return_value=upstream) as parse_dlc,
            patch("main.release", side_effect=lambda *args, **kwargs: args[:4]) as release,
            patch("main.parse_gfwlist", return_value=gfwlist),
            patch("main.release_geosite_files"),
        ):
            _run()

        self.assertEqual(
            parse_dlc.call_args.args[1],
            ("category-ads-all", "geolocation-!cn", "geolocation-cn"),
        )
        args, kwargs = release.call_args_list[0]
        self.assertEqual(args[0], ["ads.example", *BLOCK_DOMAIN])
        self.assertEqual(args[1], ["upstream.example", *BLOCK_DOMAIN_SUFFIX])
        self.assertEqual(args[3], list(BLOCK_DOMAIN_REGEX))
        self.assertEqual(args[4], "reject")
        self.assertEqual(kwargs, {"quanx_policy": "reject"})


class CleanDomainsTests(unittest.TestCase):
    def test_removes_exact_domains_and_child_suffixes_covered_by_a_suffix(self) -> None:
        self.assertEqual(
            clean_domains(
                ["example.com", "ads.example.com", "other.example", "other.example"],
                ["example.com", "ads.example.com", "example.com"],
            ),
            (["other.example"], ["example.com"]),
        )


class ReleaseTests(unittest.TestCase):
    def test_reject_output_preserves_order_within_each_rule_type(self) -> None:
        previous_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            os.chdir(directory)
            try:
                Path("dist").mkdir()
                with patch("main.release_singbox_file"):
                    rules = release(
                        ["z.example", "a.example"],
                        ["m.example", "b.example"],
                        ["zz", "aa", "c.example", "b.example"],
                        ["^z", "^a"],
                        "reject",
                        quanx_policy="reject",
                    )
                surge = Path("dist/reject.list").read_text().splitlines()
                clash = yaml.safe_load(Path("dist/reject.yaml").read_text())["payload"]
                quanx = Path("dist/reject.quanx").read_text().splitlines()
            finally:
                os.chdir(previous_cwd)

        self.assertEqual(
            rules,
            (["z.example", "a.example"], ["m.example", "b.example"], ["zz", "aa", "c.example", "b.example"], ["^z", "^a"]),
        )
        self.assertEqual(
            surge,
            ["z.example", "a.example", ".m.example", ".b.example"],
        )
        self.assertEqual(clash, surge)
        self.assertEqual(
            quanx,
            [
                "host, z.example, reject",
                "host, a.example, reject",
                "host-suffix, m.example, reject",
                "host-suffix, b.example, reject",
                "host-keyword, zz, reject",
                "host-keyword, aa, reject",
                "host-keyword, c.example, reject",
                "host-keyword, b.example, reject",
            ],
        )


class ParseGFWListTests(unittest.TestCase):
    def test_converts_current_autoproxy_rule_forms(self) -> None:
        source = r"""[AutoProxy 0.2.9]
! metadata
||example.com
||cdn*.assets.example/path
|https://exact.example/a/path
|http://*.wild.example/
plain.example
/^https?:\/\/[^\/]+blogspot\.(.*)/
@@||direct.example
@@/^https?:\/\/(?=.*?(2x3|ni5|j5o))[a-z0-9.-]+\.xn--ngstr-lra8j\.com$
"""

        rules = parse_gfwlist_text(source.encode())
        domain, domain_suffix, domain_keyword, domain_regex = rules["gfw"]

        self.assertEqual(domain, ["exact.example", "plain.example"])
        self.assertEqual(
            domain_suffix, ["example.com", "assets.example", "wild.example"]
        )
        self.assertEqual(domain_keyword, [])
        self.assertEqual(domain_regex, [r"[^\/]+blogspot\.(.*)"])
        self.assertEqual(rules["gfw-skip"][1], ["direct.example"])
        self.assertEqual(
            rules["gfw-skip"][3],
            [r"^[a-z0-9.-]*(?:2x3|ni5|j5o)[a-z0-9.-]*\.xn--ngstr-lra8j\.com$"],
        )

    def test_rejects_non_gfwlist_data(self) -> None:
        with self.assertRaisesRegex(ValueError, "header"):
            parse_gfwlist_text(b"not a gfwlist")

    def test_gfw_quanx_rules_use_proxy_policy(self) -> None:
        previous_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            os.chdir(directory)
            try:
                Path("dist").mkdir()
                release_quanx_file(
                    "gfw", ["exact.example"], ["suffix.example"], [], "proxy"
                )
                output = Path("dist/gfw.quanx").read_text()
            finally:
                os.chdir(previous_cwd)

        self.assertEqual(
            output,
            "host, exact.example, proxy\nhost-suffix, suffix.example, proxy\n",
        )


if __name__ == "__main__":
    unittest.main()
