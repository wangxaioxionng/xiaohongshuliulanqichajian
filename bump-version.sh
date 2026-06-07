#!/bin/bash
# ============================================================
# 小红书一键收录扩展 · 一键发版脚本
# 用法：./bump-version.sh [patch|minor|major] [--force]
#
# 功能：
#   1. 自动 bump extension/manifest.json 版本号
#   2. 交互式收集本次更新内容
#   3. 自动在 CHANGELOG.md 顶部插入新版本条目
#   4. 自动打包 zip 到 dist/
#   5. 提示后续同步 changelog 到服务端的指引
#
# 安全规则：
#   - 默认不会覆盖已存在的发布目录或 zip（按 CLAUDE.md "不删文件" 底线）
#   - 如目标已存在 → 报错退出，提示用户手动处理或加 --force
#   - 加 --force 时会先把旧目录/zip 移到 dist/.trash/<timestamp>/ 而不是真删
# ============================================================

set -e  # 任何命令失败立即停

# ---------- 参数标志 ----------
FORCE_OVERWRITE=0
for arg in "$@"; do
    if [ "$arg" = "--force" ]; then
        FORCE_OVERWRITE=1
    fi
done

# ---------- 颜色定义 ----------
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'  # 还原默认颜色

# ---------- 路径定义 ----------
PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
MANIFEST="$PROJECT_ROOT/extension/manifest.json"
CHANGELOG="$PROJECT_ROOT/CHANGELOG.md"
DIST_DIR="$PROJECT_ROOT/dist"
OLD_RELEASE_DIR="$DIST_DIR/小红书一键收录-v4.0.0"
README_SOURCE="$OLD_RELEASE_DIR/📖 使用说明（先看这里）.md"

# ---------- 工具函数 ----------
log_info() {
    echo -e "${BLUE}[信息]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[成功]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[警告]${NC} $1"
}

log_error() {
    echo -e "${RED}[错误]${NC} $1"
}

# ---------- 第 1 步：校验参数 ----------
BUMP_TYPE=""
for arg in "$@"; do
    case "$arg" in
        patch|minor|major) BUMP_TYPE="$arg" ;;
        --force) ;;  # 已在上面处理
        *) log_error "未知参数：$arg"; exit 1 ;;
    esac
done

if [ -z "$BUMP_TYPE" ]; then
    log_error "用法：$0 [patch|minor|major] [--force]"
    echo "  patch：补丁版本（如 4.1.0 → 4.1.1，仅 bug 修复）"
    echo "  minor：次要版本（如 4.1.0 → 4.2.0，新增功能向下兼容）"
    echo "  major：主要版本（如 4.1.0 → 5.0.0，破坏性变更）"
    echo "  --force：当目标已存在时，把旧版本移到 dist/.trash/ 而非直接退出"
    exit 1
fi

# ---------- 第 2 步：读取当前版本号 ----------
if [ ! -f "$MANIFEST" ]; then
    log_error "找不到 manifest.json：$MANIFEST"
    exit 1
fi

CURRENT_VERSION=$(grep '"version"' "$MANIFEST" | sed -E 's/.*"version": *"([^"]+)".*/\1/')
if [ -z "$CURRENT_VERSION" ]; then
    log_error "无法从 manifest.json 解析当前版本号"
    exit 1
fi

log_info "当前版本：$CURRENT_VERSION"

# ---------- 第 3 步：计算新版本号 ----------
IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT_VERSION"

case "$BUMP_TYPE" in
    patch)
        PATCH=$((PATCH + 1))
        ;;
    minor)
        MINOR=$((MINOR + 1))
        PATCH=0
        ;;
    major)
        MAJOR=$((MAJOR + 1))
        MINOR=0
        PATCH=0
        ;;
esac

NEW_VERSION="$MAJOR.$MINOR.$PATCH"
log_success "新版本：$NEW_VERSION"
echo ""

# ---------- 第 4 步：交互式收集更新内容 ----------
echo -e "${BLUE}=== 收集本次更新内容 ===${NC}"
echo ""

# 标题
read -p "请输入本次更新标题（一行）：" UPDATE_TITLE
if [ -z "$UPDATE_TITLE" ]; then
    log_error "更新标题不能为空"
    exit 1
fi

# 类型
echo ""
echo "请选择类型：1=新增 2=修复 3=变更 4=移除"
read -p "输入数字（1-4）：" TYPE_NUM

case "$TYPE_NUM" in
    1) TYPE_LABEL="新增" ;;
    2) TYPE_LABEL="修复" ;;
    3) TYPE_LABEL="变更" ;;
    4) TYPE_LABEL="移除" ;;
    *)
        log_error "无效的类型，必须是 1-4"
        exit 1
        ;;
esac

# 详情（多行）
echo ""
echo "请输入详情（多行，单独一行写 END 结束）："
DETAIL_LINES=""
while IFS= read -r line; do
    if [ "$line" = "END" ]; then
        break
    fi
    DETAIL_LINES+="- $line"$'\n'
done

if [ -z "$DETAIL_LINES" ]; then
    log_warn "详情为空，将只写标题"
    DETAIL_LINES="- $UPDATE_TITLE"$'\n'
fi

# ---------- 第 5 步：改 manifest.json ----------
log_info "更新 manifest.json 版本号..."
# 用 sed 替换（macOS 和 Linux 兼容写法）
if [[ "$OSTYPE" == "darwin"* ]]; then
    sed -i '' "s/\"version\": *\"$CURRENT_VERSION\"/\"version\": \"$NEW_VERSION\"/" "$MANIFEST"
else
    sed -i "s/\"version\": *\"$CURRENT_VERSION\"/\"version\": \"$NEW_VERSION\"/" "$MANIFEST"
fi
log_success "manifest.json 已 bump → $NEW_VERSION"

# ---------- 第 6 步：在 CHANGELOG.md 顶部插入新条目 ----------
log_info "更新 CHANGELOG.md..."

TODAY=$(date +%Y-%m-%d)
NEW_ENTRY="## [$NEW_VERSION] - $TODAY

### $TYPE_LABEL
$DETAIL_LINES"

# 临时文件
TMP_CHANGELOG=$(mktemp)

# 读取原 CHANGELOG，找到第一个 "## [" 的位置，在前面插入新条目
# 如果还没有任何版本条目，就追加到文件末尾
if grep -q '^## \[' "$CHANGELOG"; then
    # 找到第一个 "## [" 的行号
    FIRST_VERSION_LINE=$(grep -n '^## \[' "$CHANGELOG" | head -1 | cut -d: -f1)
    # 头部内容（第一个版本条目之前）
    head -n $((FIRST_VERSION_LINE - 1)) "$CHANGELOG" > "$TMP_CHANGELOG"
    # 插入新条目
    echo "$NEW_ENTRY" >> "$TMP_CHANGELOG"
    # 旧条目
    tail -n +$FIRST_VERSION_LINE "$CHANGELOG" >> "$TMP_CHANGELOG"
else
    # 没有任何版本条目，直接追加
    cat "$CHANGELOG" > "$TMP_CHANGELOG"
    echo "" >> "$TMP_CHANGELOG"
    echo "$NEW_ENTRY" >> "$TMP_CHANGELOG"
fi

mv "$TMP_CHANGELOG" "$CHANGELOG"
log_success "CHANGELOG.md 已添加新条目"

# ---------- 第 7 步：打包 zip ----------
echo ""
log_info "开始打包 zip..."

NEW_RELEASE_DIR="$DIST_DIR/小红书一键收录-v$NEW_VERSION"
NEW_ZIP="$DIST_DIR/小红书一键收录-v$NEW_VERSION.zip"

# 安全规则：默认不直接删除已存在的发布产物
# 如目标已存在 → 报错退出 / 加 --force 则移到 dist/.trash/<ts>/ 而非真删
if [ -d "$NEW_RELEASE_DIR" ] || [ -f "$NEW_ZIP" ]; then
    if [ "$FORCE_OVERWRITE" -eq 0 ]; then
        log_error "目标已存在，按安全规则不会自动删除："
        [ -d "$NEW_RELEASE_DIR" ] && echo "  - 目录：$NEW_RELEASE_DIR"
        [ -f "$NEW_ZIP" ] && echo "  - zip：$NEW_ZIP"
        echo ""
        echo "处理方式（选一）："
        echo "  1. 手动检查后自己删除：rm -rf \"$NEW_RELEASE_DIR\" \"$NEW_ZIP\""
        echo "  2. 重跑脚本加 --force：$0 $BUMP_TYPE --force"
        echo "     （--force 会把旧产物移到 dist/.trash/<ts>/ 保留，而非真删）"
        exit 1
    fi
    # --force 模式：移到回收站而不是删
    TRASH_DIR="$DIST_DIR/.trash/$(date +%Y%m%d_%H%M%S)"
    log_warn "目标已存在，--force 模式，移到回收站：$TRASH_DIR"
    mkdir -p "$TRASH_DIR"
    [ -d "$NEW_RELEASE_DIR" ] && mv "$NEW_RELEASE_DIR" "$TRASH_DIR/"
    [ -f "$NEW_ZIP" ] && mv "$NEW_ZIP" "$TRASH_DIR/"
    log_info "旧产物保留在：$TRASH_DIR（30 天后可手动清理）"
fi

# 建新目录
mkdir -p "$NEW_RELEASE_DIR"

# 复制 extension/ 到新目录（排除敏感文件）
log_info "复制 extension/ 文件（排除 secrets）..."
rsync -a \
    --exclude='secrets.js' \
    --exclude='secrets.js.example' \
    --exclude='.serena' \
    --exclude='.spec-workflow' \
    --exclude='.DS_Store' \
    "$PROJECT_ROOT/extension/" "$NEW_RELEASE_DIR/extension/"

# 复制使用说明
if [ -f "$README_SOURCE" ]; then
    cp "$README_SOURCE" "$NEW_RELEASE_DIR/"
    log_info "已复制使用说明到新版本目录"
else
    log_warn "找不到使用说明文件：$README_SOURCE（跳过）"
fi

# 打 zip
# 注意：cd 到 dist/ 再 zip，确保包内首层是「小红书一键收录-vX.Y.Z/」而非「dist/小红书一键收录-vX.Y.Z/」
log_info "正在打 zip..."
cd "$DIST_DIR"
zip -r "$NEW_ZIP" "小红书一键收录-v$NEW_VERSION/" > /dev/null
cd "$PROJECT_ROOT"
ZIP_SIZE=$(du -h "$NEW_ZIP" | cut -f1)
log_success "zip 打包完成：$NEW_ZIP（$ZIP_SIZE）"

# ---------- 第 8 步：输出后续指引 ----------
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  发版完成 v$NEW_VERSION${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "${BLUE}产出：${NC}"
echo "  新版本号：$NEW_VERSION"
echo "  压缩包：  $NEW_ZIP（$ZIP_SIZE）"
echo "  解压目录：$NEW_RELEASE_DIR/"
echo ""
echo -e "${YELLOW}⚠️  请记得调 \`POST /api/admin/changelog\` 同步 changelog 到服务端${NC}"
echo -e "${YELLOW}   （脚本未自动调用，因为需要 admin token）${NC}"
echo ""
echo -e "${BLUE}下一步：${NC}"
echo "  1. 把 $NEW_ZIP 发给团队成员"
echo "  2. 用 admin token 调 POST /api/admin/changelog 同步更新日志"
echo "  3. 在 CLAUDE.md 同步"当前发布版"字段"
echo ""
