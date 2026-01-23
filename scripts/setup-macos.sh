#!/usr/bin/env bash
# macOS 开发环境设置脚本
# 用法: ./scripts/setup-macos.sh
set -euo pipefail

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

info() { echo -e "${GREEN}[INFO]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# 检查是否在 macOS 上运行
if [[ "$(uname)" != "Darwin" ]]; then
    error "此脚本仅适用于 macOS"
    exit 1
fi

# 切换到项目根目录
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
info "项目目录: $repo_root"

# 1. 检查/安装 Homebrew
if ! command -v brew &>/dev/null; then
    info "安装 Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

    # 添加到 PATH (Apple Silicon)
    if [[ -f /opt/homebrew/bin/brew ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    fi
else
    info "Homebrew 已安装"
fi

# 2. 安装 Python 3.13
if ! command -v python3.13 &>/dev/null; then
    info "安装 Python 3.13..."
    brew install python@3.13
else
    info "Python 3.13 已安装: $(python3.13 --version)"
fi

# 3. 安装 uv (快速 Python 包管理器)
if ! command -v uv &>/dev/null; then
    info "安装 uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # 添加到当前 shell
    export PATH="$HOME/.local/bin:$PATH"
else
    info "uv 已安装: $(uv --version)"
fi

# 4. 安装 PortAudio (sounddevice 依赖)
if ! brew list portaudio &>/dev/null; then
    info "安装 PortAudio (音频录制依赖)..."
    brew install portaudio
else
    info "PortAudio 已安装"
fi

# 5. 同步项目依赖
info "安装项目依赖..."
uv sync --frozen

# 6. 生成 icon.icns (如果不存在)
if [[ -f icon.png ]] && [[ ! -f icon.icns ]]; then
    info "生成 icon.icns..."

    # 安装 ImageMagick (可选，用于更好的图标质量)
    if ! command -v magick &>/dev/null; then
        warn "ImageMagick 未安装，使用 sips 生成图标 (质量略低)"
        warn "可运行 'brew install imagemagick' 获得更好的图标质量"
    fi

    mkdir -p icon.iconset

    for size in 16 32 64 128 256 512 1024; do
        inner=$((size * 80 / 100))
        if command -v magick &>/dev/null; then
            magick icon.png -resize ${inner}x${inner} -gravity center -background none -extent ${size}x${size} /tmp/icon_${size}.png
        else
            sips -z $size $size icon.png --out /tmp/icon_${size}.png 2>/dev/null
        fi
    done

    cp /tmp/icon_16.png icon.iconset/icon_16x16.png
    cp /tmp/icon_32.png icon.iconset/icon_16x16@2x.png
    cp /tmp/icon_32.png icon.iconset/icon_32x32.png
    cp /tmp/icon_64.png icon.iconset/icon_32x32@2x.png
    cp /tmp/icon_128.png icon.iconset/icon_128x128.png
    cp /tmp/icon_256.png icon.iconset/icon_128x128@2x.png
    cp /tmp/icon_256.png icon.iconset/icon_256x256.png
    cp /tmp/icon_512.png icon.iconset/icon_256x256@2x.png
    cp /tmp/icon_512.png icon.iconset/icon_512x512.png
    cp /tmp/icon_1024.png icon.iconset/icon_512x512@2x.png

    iconutil -c icns icon.iconset -o icon.icns
    rm -rf icon.iconset /tmp/icon_*.png
    info "icon.icns 已生成"
fi

# 7. 提示辅助功能权限
echo ""
info "===================== 设置完成 ====================="
echo ""
echo "运行应用:"
echo "  uv run python asr_pyqt6_app.py"
echo ""
echo "构建 .app bundle:"
echo "  uv sync --frozen --extra build"
echo "  JT_ONEFILE=0 JT_ICON=icon.icns uv run pyinstaller just_talk.spec"
echo ""
warn "首次运行需要授予以下权限:"
echo "  1. 麦克风权限 - 系统会自动弹窗请求"
echo "  2. 辅助功能权限 (全局快捷键) - 需要手动添加:"
echo "     系统设置 → 隐私与安全性 → 辅助功能"
echo "     添加 Terminal.app 或 iTerm.app (取决于你使用的终端)"
echo ""
echo "如果快捷键不工作，请检查辅助功能权限设置。"
echo ""
