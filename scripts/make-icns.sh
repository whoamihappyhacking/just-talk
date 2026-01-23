#!/usr/bin/env bash
# 从 icon.png 生成 macOS 的 icon.icns 文件
# 需要 ImageMagick (convert) 和 iconutil (macOS) 或 png2icns (Linux)
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

src_icon="icon.png"
if [ ! -f "$src_icon" ]; then
    echo "Error: $src_icon not found" >&2
    exit 1
fi

# 检查是否有 ImageMagick
if ! command -v convert &>/dev/null; then
    echo "Error: ImageMagick (convert) is required" >&2
    exit 1
fi

# 创建临时目录
iconset_dir="$(mktemp -d)/icon.iconset"
mkdir -p "$iconset_dir"

# 生成各种尺寸的图标
sizes=(16 32 64 128 256 512 1024)
for size in "${sizes[@]}"; do
    convert "$src_icon" -resize "${size}x${size}" "$iconset_dir/icon_${size}x${size}.png"
    # @2x 版本
    size2=$((size * 2))
    if [ $size2 -le 2048 ]; then
        convert "$src_icon" -resize "${size2}x${size2}" "$iconset_dir/icon_${size}x${size}@2x.png"
    fi
done

# 在 macOS 上使用 iconutil
if command -v iconutil &>/dev/null; then
    iconutil -c icns -o icon.icns "$iconset_dir"
    echo "Generated icon.icns using iconutil"
# 在 Linux 上使用 png2icns
elif command -v png2icns &>/dev/null; then
    png2icns icon.icns "$iconset_dir"/icon_*.png
    echo "Generated icon.icns using png2icns"
else
    echo "Warning: Neither iconutil nor png2icns found" >&2
    echo "On macOS: iconutil is built-in" >&2
    echo "On Linux: install libicns (provides png2icns)" >&2
    echo "Icon files are in: $iconset_dir" >&2
    exit 1
fi

# 清理
rm -rf "$(dirname "$iconset_dir")"
echo "icon.icns created successfully"
