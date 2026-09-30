#!/usr/bin/env python3
"""Generate the complete NSS driver option inventory from repository sources.

Profile values are explicit selections, not the result of make defconfig.
"""

import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "package/kernel/qca-nss-drv/Config.in"
PROFILE = ROOT / "configs/redmi-ax3000-nss-wifi.config"
OUTPUT = ROOT / "docs/nss"


def main():
    profile = PROFILE.read_text()
    source = CONFIG.read_text()
    features = []
    for match in re.finditer(r"(?m)^config (NSS_DRV_\w+)\n([\s\S]*?)(?=^config |^endmenu|\Z)", source):
        symbol, block = match.groups()
        selected = re.search(r"(?m)^CONFIG_" + symbol + r"=(.*)$", profile)
        disabled = re.search(r"(?m)^# CONFIG_" + symbol + r" is not set$", profile)
        prompt = re.search(r'(?m)^\s*prompt "([^"]+)"', block)
        features.append({
            "symbol": symbol,
            "prompt": prompt.group(1) if prompt else "",
            "defaults": re.findall(r"(?m)^\s*default (.+)$", block),
            "depends_on": re.findall(r"(?m)^\s*depends on (.+)$", block),
            "selects": re.findall(r"(?m)^\s*select (.+)$", block),
            "profile_value": selected.group(1) if selected else "n" if disabled else None,
            "source_line": source[:match.start()].count("\n") + 1,
        })
    if len(features) != 44:
        raise SystemExit(f"NSS option count changed ({len(features)}); review the capability documentation")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    inventory = {
        "definition": "package/kernel/qca-nss-drv/Config.in",
        "profile": "configs/redmi-ax3000-nss-wifi.config",
        "interpretation": "profile_value is an explicit fragment selection; null is unspecified, not a resolved build result",
        "features": features,
    }
    (OUTPUT / "features.json").write_text(json.dumps(inventory, indent=2) + "\n")
    lines = [
        "# NSS 驱动完整配置项清单", "",
        "由 `scripts/nss/update-feature-inventory.py` 从仓库 `Config.in` 和配置片段生成，共 44 项。", "",
        "“未指定”表示配置片段没有显式选择。它不等于最终 `.config` 为 `n`；Kconfig 的依赖、select、其他软件包及 Makefile 会影响实际构建。端到端功能状态见 [开发交接说明](README.md)。", "",
        "| 配置项（省略 `NSS_DRV_`） | 配置片段 | Kconfig 默认 | 依赖 |", "|---|---|---|---|",
    ]
    for feature in features:
        name = feature["symbol"].removeprefix("NSS_DRV_")
        state = {"y": "显式启用", "n": "显式关闭", None: "未指定"}.get(feature["profile_value"], feature["profile_value"])
        default = "; ".join(feature["defaults"]) or "无"
        dependencies = "; ".join(feature["depends_on"]) or "无平台限制"
        lines.append(f"| `{name}` | {state} | `{default}` | `{dependencies}` |")
    lines += ["", "固定驱动源码还包含 IPv4、ETH_RX、动态接口、N2H 等基础组件，不全部对应独立 NSS_DRV 配置项。", ""]
    (OUTPUT / "feature-options.md").write_text("\n".join(lines))
    print(f"Generated {len(features)} NSS driver feature definitions")


if __name__ == "__main__":
    main()
