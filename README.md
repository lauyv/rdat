# rdat

自动生成并发布适用于 Clash、Surge、Quantumult X、sing-box 和 V2Ray GeoSite 的域名规则。

## 规则

生成以下三个标签：

- `reject`：合并 `category-ads-all`、所有列表中带 `@ads` 属性的规则及手动补充
- `loc-!cn`：合并 `geolocation-!cn`、所有列表中带 `@!cn` 属性的规则及手动补充
- `loc-cn`：合并 `geolocation-cn`、`category-public-tracker`、所有列表中带 `@cn` 属性的规则及手动补充

`@cn`、`@!cn` 和 `@ads` 按完整属性名分别匹配，合并后去重。带有多个匹配属性的规则会进入对应的多个集合。

`@cn` 不保证服务器位于境内。

客户端应按 `reject` → `loc-cn` → `loc-!cn` 的顺序匹配，让广告拦截优先于直连，并处理可能存在的域名覆盖重叠。

Quantumult X 产物分别使用 `reject`、`direct` 和 `proxy` 策略。

## 发布

GitHub Actions 每天构建一次，并在 `main` 更新时自动构建。产物发布到 `rel` 分支；该分支每次发布都会重建，只保留最新结果。

| 路径             | 格式                                              |
| ---------------- | ------------------------------------------------- |
| `<tag>.yaml`     | Clash Rule Provider                               |
| `<tag>.list`     | Surge Domain Set                                  |
| `<tag>.quanx`    | Quantumult X Filter                               |
| `<tag>.srs`      | sing-box Binary Rule Set                          |
| `geosite.dat`    | V2Ray GeoSite，包含 `reject`、`loc-!cn`、`loc-cn` |
| `geosite-cn.dat` | V2Ray GeoSite，包含 `loc-cn`                      |
| `ext/*.quanx`    | Quantumult X 重写规则                             |
| `ext/*.sgmodule` | Surge 模块                                        |

下载地址格式：

```text
https://github.com/lauyv/rdat/raw/rel/<文件路径>
```

例如：

```text
https://github.com/lauyv/rdat/raw/rel/loc-cn.srs
https://github.com/lauyv/rdat/raw/rel/ext/bili.quanx
https://github.com/lauyv/rdat/raw/rel/ext/bili.sgmodule
```

## 项目结构

```text
.
├── main.py                    # 规则生成器
├── source/                    # 手工维护的重写规则和模块
├── js/                        # JS 脚本
├── example/                   # 客户端配置示例
├── tests/                     # 规则解析测试
├── .github/workflows/build.yml
├── pyproject.toml
└── uv.lock
```

## 本地构建

需要 Python 3.12、[uv](https://docs.astral.sh/uv/) 和
[sing-box](https://sing-box.sagernet.org/)。

```bash
uv sync
uv run python main.py
```

构建产物位于 `dist/`。

## 致谢

感谢以下项目提供规则数据：

- [fmz200/wool_scripts](https://github.com/fmz200/wool_scripts)
- [v2fly/domain-list-community](https://github.com/v2fly/domain-list-community)
