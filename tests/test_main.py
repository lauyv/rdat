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
    release,
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
        self.assertEqual(rules["geolocation-!cn"], (["foreign.example"], ["apple.com"], [], []))

    def test_collects_negated_cn_with_exact_attributes_and_all_rule_types(self):
        additions = [
            "full:foreign.example:@ads,@!cn",
            "domain:foreign.example:@!cn",
            "keyword:foreign-service:@!cn",
            r"regexp:^foreign[0-9]+\.example$:@!cn",
        ]
        source = {"lists": [
            {"name": "vendor", "rules": additions + [
                "full:similar.example:@!cn2", "full:local.example:@cn",
                "full:untagged.example",
            ]},
            {"name": "geolocation-!cn", "rules": [additions[0]]},
            {"name": "duplicate", "rules": additions},
        ]}
        with patch("main.urlopen", return_value=BytesIO(yaml.safe_dump(source).encode())):
            rules = parse_dlc_plain("fixture", ("geolocation-!cn",))
        self.assertEqual(rules["geolocation-!cn"], (
            ["foreign.example"], ["foreign.example"], ["foreign-service"],
            [r"^foreign[0-9]+\.example$"],
        ))

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
            "category-public-tracker": (
                ["tracker.example"], ["trackers.example"], ["tracker-keyword"],
                [r"^tracker[0-9]+\.example$"],
            ),
        }
        with (
            patch("main.parse_dlc_plain", return_value=upstream) as parse_dlc,
            patch("main.release", side_effect=lambda *args, **kwargs: args[:4]) as release,
            patch("main.release_geosite_files"),
        ):
            _run()

        self.assertEqual(
            parse_dlc.call_args.args[1],
            ("category-ads-all", "geolocation-!cn", "geolocation-cn", "category-public-tracker"),
        )
        args, kwargs = release.call_args_list[0]
        self.assertEqual(args[0], ["ads.example", *BLOCK_DOMAIN])
        self.assertEqual(args[1], ["upstream.example", *BLOCK_DOMAIN_SUFFIX])
        self.assertEqual(args[3], list(BLOCK_DOMAIN_REGEX))
        self.assertEqual(args[4], "reject")
        self.assertEqual(kwargs, {"quanx_policy": "reject"})
        self.assertEqual(release.call_args_list[1].args[4], "loc-!cn")
        self.assertEqual(release.call_args_list[1].kwargs, {"quanx_policy": "proxy"})
        direct_args = release.call_args_list[2].args
        self.assertEqual(direct_args[4], "loc-cn")
        self.assertEqual(release.call_args_list[2].kwargs, {"quanx_policy": "direct"})
        for values, additions in zip(direct_args[:4], upstream["category-public-tracker"]):
            for value in additions:
                self.assertIn(value, values)
        self.assertEqual(len(release.call_args_list), 3)



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


if __name__ == "__main__":
    unittest.main()
