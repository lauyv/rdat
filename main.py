import json
import logging
import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from urllib.request import urlopen

import yaml

# ═══════════════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════════════

BLOCK_DOMAIN = (
    # 农业银行代理检测，非广告
    "msmp.abchina.com.cn",
)

BLOCK_DOMAIN_SUFFIX = (
    # 广告联盟
    "tencent-ssp.66mobi.com",
    "statics.adanxing.com",
    "addnewer.com",
    "domob.cn",
    "adsmind.gdtimg.com",
    "qzs.gdtimg.com",
    "gridsum.com",
    "gridsumdissector.com",
    "adx.halomobi.com",
    "in-neo.com",
    "promotion-partner.kuaishou.com",
    "bridgeads.massx.com",
    "miaozhen.com",
    "mix-mind.com",
    "mazu.m.qq.com",
    "shenshiads.com",
    "huichuan-mc.sm.cn",
    "tunion-api.m.taobao.com",
    "api.touch-moblie.com",
    "fapi.xdrun.com",
    # pcdn
    "ahdohpiechei.com",
    "mountaintoys.cn",
    "nexusedgeio.com",
    "szbdyd.com",
)


BLOCK_DOMAIN_REGEX = (
    # pcdn
    r"^.*302.*\.bilivideo\.com$",
    r"^.*pcdn.*\.biliapi\.net$",
    r"^.*tracker.*\.biliapi\.net$",
)

DIRECT_DOMAIN = ("api.github.com",)

DIRECT_DOMAIN_SUFFIX = (
    "cn",
    "local",
    "steamserver.net",
    "steamcontent.com",
    "msftconnecttest.com",
    "msftncsi.com",
    "hotmail.com",
    "baozimh.com",
    "baozicdn.com",
)

PROXY_DOMAIN: tuple[str, ...] = ()
PROXY_DOMAIN_SUFFIX: tuple[str, ...] = ()

# ═══════════════════════════════════════════════════════════════════════════════
# Logging
# ═══════════════════════════════════════════════════════════════════════════════

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# Upstream
# ═══════════════════════════════════════════════════════════════════════════════

DomainResult = tuple[
    list[str],  # domain
    list[str],  # domain_suffix
    list[str],  # domain_keyword
    list[str],  # domain_regex
]

GeoSiteRules = dict[str, DomainResult]

GEOSITE_TAGS = (
    "reject",
    "loc-!cn",
    "loc-cn",
)


def parse_dlc_plain(url: str, tags: tuple[str, ...]) -> GeoSiteRules:
    """Extract flattened tags and supplement them with matching global attributes."""
    log.info("Downloading %s", url)
    with urlopen(url) as response:
        lists = yaml.safe_load(response).get("lists", [])

    remaining = set(tags)
    result: GeoSiteRules = {}
    attribute_targets = {
        attribute: tag
        for attribute, tag in (
            ("cn", "geolocation-cn"),
            ("!cn", "geolocation-!cn"),
            ("ads", "category-ads-all"),
        )
        if tag in tags
    }
    attribute_rules: GeoSiteRules = {
        attribute: ([], [], [], []) for attribute in attribute_targets
    }
    rule_indexes = {"full": 0, "domain": 1, "keyword": 2, "regexp": 3}
    for item in lists:
        tag = item.get("name")
        selected = tag in remaining
        if not selected and not attribute_targets:
            continue

        values: DomainResult = ([], [], [], [])
        for raw_rule in item.get("rules", []):
            # Upstream serializes attributes as :@attr1,@attr2.
            rule, _, attributes = raw_rule.partition(":@")
            matching_attributes = attribute_targets.keys() & set(attributes.split(",@"))
            if not selected and not matching_attributes:
                continue
            rule_type, separator, value = rule.partition(":")
            if not separator or rule_type not in rule_indexes:
                raise ValueError(f"Unsupported DLC rule: {raw_rule!r}")
            index = rule_indexes[rule_type]
            if selected:
                values[index].append(value)
            for attribute in matching_attributes:
                attribute_rules[attribute][index].append(value)

        if selected:
            result[tag] = values
            remaining.remove(tag)
        if not remaining and not attribute_targets:
            break

    if remaining:
        raise ValueError(f"Missing DLC tags: {', '.join(sorted(remaining))}")
    for attribute, target in attribute_targets.items():
        for destination, additions in zip(result[target], attribute_rules[attribute]):
            destination[:] = dict.fromkeys(destination + additions)
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Release — generate output files for all supported proxy platforms
# ═══════════════════════════════════════════════════════════════════════════════


def release(
    domain: list[str],
    domain_suffix: list[str],
    domain_keyword: list[str],
    domain_regex: list[str],
    tag: str,
    *,
    quanx_policy: str = "direct",
) -> DomainResult:
    """Generate output files (Surge, Clash, QuanX, sing-box) for *tag*."""
    log.info("Releasing tag: %s", tag)
    domain, domain_suffix = clean_domains(domain, domain_suffix)

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [
            pool.submit(release_surge_file, tag, domain, domain_suffix),
            pool.submit(release_clash_file, tag, domain, domain_suffix),
            pool.submit(
                release_quanx_file,
                tag,
                domain,
                domain_suffix,
                domain_keyword,
                quanx_policy,
            ),
            pool.submit(
                release_singbox_file,
                tag,
                domain,
                domain_suffix,
                domain_regex,
                domain_keyword,
            ),
        ]
        for future in futures:
            future.result()

    return domain, domain_suffix, domain_keyword, domain_regex


def release_surge_file(tag: str, domain: list[str], domain_suffix: list[str]) -> None:
    filename = f"dist/{tag}.list"
    with open(filename, "w") as f:
        f.writelines(value + "\n" for value in domain)
        f.writelines("." + value + "\n" for value in domain_suffix)


def release_clash_file(tag: str, domain: list[str], domain_suffix: list[str]) -> None:
    filename = f"dist/{tag}.yaml"
    with open(filename, "w") as f:
        yaml.dump(
            {"payload": domain + ["." + value for value in domain_suffix]},
            f,
            default_flow_style=False,
            allow_unicode=True,
        )


def release_quanx_file(
    tag: str,
    domain: list[str],
    domain_suffix: list[str],
    domain_keyword: list[str],
    policy: str = "direct",
) -> None:
    filename = f"dist/{tag}.quanx"
    with open(filename, "w", buffering=65536) as f:
        f.writelines(f"host, {value}, {policy}\n" for value in domain)
        f.writelines(f"host-suffix, {value}, {policy}\n" for value in domain_suffix)
        f.writelines(f"host-keyword, {value}, {policy}\n" for value in domain_keyword)


def release_singbox_file(
    tag: str,
    domain: list[str],
    domain_suffix: list[str],
    domain_regex: list[str],
    domain_keyword: list[str],
) -> None:
    filename = f"tmp/{tag}.json"
    rule = {
        key: values
        for key, values in (
            ("domain", domain),
            ("domain_suffix", domain_suffix),
            ("domain_regex", domain_regex),
            ("domain_keyword", domain_keyword),
        )
        if values
    }

    with open(filename, "w") as f:
        json.dump({"version": 2, "rules": [rule]}, f, separators=(",", ":"))

    output = f"dist/{tag}.srs"
    log.info("Compiling sing-box file: %s", filename)
    subprocess.run(
        ["sing-box", "rule-set", "compile", "--output", output, filename],
        check=True,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# V2Ray GeoSite output
# ══════════════════════════════════════════════════════════════════════════════


def _protobuf_varint(value: int) -> bytes:
    """Encode a non-negative integer using the protobuf varint format."""
    encoded = bytearray()
    while value > 0x7F:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _protobuf_field(field_number: int, wire_type: int, value: bytes) -> bytes:
    key = _protobuf_varint((field_number << 3) | wire_type)
    if wire_type == 2:
        return key + _protobuf_varint(len(value)) + value
    return key + value


def _encode_geosite_domain(domain_type: int, value: str) -> bytes:
    # v2ray routercommon.Domain: type = 1, value = 2.
    return _protobuf_field(1, 0, _protobuf_varint(domain_type)) + _protobuf_field(
        2, 2, value.encode()
    )


def _encode_geosite(tag: str, rules: DomainResult) -> bytes:
    # v2ray routercommon.GeoSite: country_code = 1, domain = 2.
    domain, domain_suffix, domain_keyword, domain_regex = rules
    fields = [_protobuf_field(1, 2, tag.upper().encode())]
    typed_rules = (
        (3, domain),  # Full
        (2, domain_suffix),  # RootDomain
        (0, domain_keyword),  # Plain
        (1, domain_regex),  # Regex
    )
    for domain_type, values in typed_rules:
        for value in dict.fromkeys(values):
            encoded = _encode_geosite_domain(domain_type, value)
            fields.append(_protobuf_field(2, 2, encoded))
    return b"".join(fields)


def write_geosite_file(filename: str, rules_by_tag: GeoSiteRules) -> None:
    """Write a V2Ray-compatible GeoSiteList protobuf file."""
    # routercommon.GeoSiteList has one repeated GeoSite field named entry (1).
    with open(filename, "wb") as f:
        f.writelines(
            _protobuf_field(1, 2, _encode_geosite(tag, rules_by_tag[tag]))
            for tag in sorted(rules_by_tag)
        )
    log.info("Wrote GeoSite file: %s (%d tags)", filename, len(rules_by_tag))


def release_geosite_files(rules_by_tag: GeoSiteRules) -> None:
    """Generate the general and CN-only GeoSite databases."""
    complete_rules = {tag: rules_by_tag[tag] for tag in GEOSITE_TAGS}
    write_geosite_file("dist/geosite.dat", complete_rules)
    write_geosite_file("dist/geosite-cn.dat", {"loc-cn": rules_by_tag["loc-cn"]})


# ═══════════════════════════════════════════════════════════════════════════════
# Utilities
# ═══════════════════════════════════════════════════════════════════════════════


def clean_domains(
    domain: list[str], domain_suffix: list[str]
) -> tuple[list[str], list[str]]:
    """Remove domains whose parent is already covered by a domain suffix."""
    log.info(
        "Cleaning domains: %d domains, %d suffixes", len(domain), len(domain_suffix)
    )

    unique_suffixes = dict.fromkeys(domain_suffix)

    def covered(value: str) -> bool:
        while (dot := value.find(".")) >= 0:
            value = value[dot + 1 :]
            if value in unique_suffixes:
                return True
        return False

    return (
        [
            value
            for value in dict.fromkeys(domain)
            if value not in unique_suffixes and not covered(value)
        ],
        [value for value in unique_suffixes if not covered(value)],
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════


def main() -> None:
    shutil.rmtree("dist", ignore_errors=True)
    os.makedirs("dist")
    os.makedirs("tmp", exist_ok=True)

    try:
        _run()
    finally:
        shutil.rmtree("tmp", ignore_errors=True)


def _run() -> None:
    rule_tags = (
        ("geolocation-!cn", "loc-!cn", PROXY_DOMAIN, PROXY_DOMAIN_SUFFIX),
        ("geolocation-cn", "loc-cn", DIRECT_DOMAIN, DIRECT_DOMAIN_SUFFIX),
    )
    upstream_rules = parse_dlc_plain(
        "https://github.com/v2fly/domain-list-community/releases/latest/download/dlc.dat_plain.yml",
        (
            "category-ads-all",
            *(rule[0] for rule in rule_tags),
            "category-public-tracker",
        ),
    )

    tracker_rules = upstream_rules["category-public-tracker"]
    for destination, additions in zip(upstream_rules["geolocation-cn"], tracker_rules):
        destination.extend(additions)

    geosite_rules: GeoSiteRules = {}
    reject_rules = upstream_rules["category-ads-all"]
    reject_rules[0].extend(BLOCK_DOMAIN)
    reject_rules[1].extend(BLOCK_DOMAIN_SUFFIX)
    reject_rules[3].extend(BLOCK_DOMAIN_REGEX)
    geosite_rules["reject"] = release(*reject_rules, "reject", quanx_policy="reject")
    for upstream_tag, output_tag, extra_domains, extra_suffixes in rule_tags:
        domain, domain_suffix, domain_keyword, domain_regex = upstream_rules[
            upstream_tag
        ]
        domain.extend(extra_domains)
        domain_suffix.extend(extra_suffixes)
        geosite_rules[output_tag] = release(
            domain, domain_suffix, domain_keyword, domain_regex, output_tag,
            quanx_policy="proxy" if output_tag == "loc-!cn" else "direct",
        )

    release_geosite_files(geosite_rules)


if __name__ == "__main__":
    main()
