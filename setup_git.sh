#!/usr/bin/env bash
# 可复用的 git 初始化脚本：安装 git 并写入全局配置。
#
# 设计为子进程执行（bash setup_git.sh），无需 source：脚本内所有效果都通过
# ~/.gitconfig 落盘持久化，不依赖变量作用域。
#
# 读取的环境变量（主脚本需 export 后再调用本脚本，否则子进程看不到）：
#   GIT_USERNAME  git 用户名（commit 署名 + 认证用户名）
#   GIT_EMAIL     commit 邮箱
#   GIT_TOKEN     访问 github / 内网 codehub 的 token
#
# 两项运行时环境变量无法在此持久化，由主脚本负责 export 给最终运行 git 的服务进程：
#   1. GIT_TERMINAL_PROMPT=0            —— 认证失败直接报错而非交互等待，避免 agent 的 bash 卡死
#   2. GIT_USERNAME / GIT_TOKEN         —— credential helper 在 git 运行时才读取它们
set -euo pipefail

# git 已存在则跳过安装，避免每次启动都跑 yum
if ! command -v git >/dev/null 2>&1; then
    yum install -y git
fi

if [ -n "${GIT_USERNAME:-}" ]; then
    git config --global user.name "$GIT_USERNAME"
fi
if [ -n "${GIT_EMAIL:-}" ]; then
    git config --global user.email "$GIT_EMAIL"
fi

# credential helper 从环境变量现读 token：clone/fetch/push 全部透明认证，
# token 不进命令行、不落 ~/.gitconfig
if [ -n "${GIT_TOKEN:-}" ]; then
    git config --global credential.helper '!f() { echo "username=${GIT_USERNAME}"; echo "password=${GIT_TOKEN}"; }; f'
else
    echo "[setup_git.sh] WARN: GIT_TOKEN 未设置，git 拉取私有仓库将失败" >&2
fi

# 内网 codehub 多为自签证书
git config --global http.sslVerify false
