#!/usr/bin/env bash
#
# git 一键提交脚本
#
# 用法:
#   ./git_commit.sh                # 使用默认提交信息 "default commit"
#   ./git_commit.sh "修复沙箱路径"  # 使用自定义提交信息
#
set -euo pipefail

# 始终在脚本所在目录执行，避免从别处调用时提交错仓库
cd "$(dirname "$0")"

COMMIT_MSG="${1:-default commit}"

# 不是 git 仓库就先初始化
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "当前目录不是 git 仓库，正在初始化..."
    git init
fi

git add -A

# 没有变更就不提交，避免报错
if git diff --cached --quiet 2>/dev/null; then
    echo "没有需要提交的变更。"
    exit 0
fi

git commit -m "$COMMIT_MSG"
echo "✅ 已提交: $COMMIT_MSG"

# 如果配置了远程且当前分支有上游，就顺带推送
if git remote get-url origin >/dev/null 2>&1; then
    branch="$(git rev-parse --abbrev-ref HEAD)"
    if git rev-parse --abbrev-ref --symbolic-full-name "@{u}" >/dev/null 2>&1; then
        git push
        echo "✅ 已推送到远程 ($branch)"
    else
        echo "ℹ️  远程 origin 已配置但当前分支无上游，如需推送请运行: git push -u origin $branch"
    fi
else
    echo "ℹ️  未配置远程仓库，仅本地提交。"
fi
