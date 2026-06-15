#!/usr/bin/env bash
# 一键双推：把当前分支推到 GitHub(origin) 和 Gitee(gitee)。
# 用法：
#   ./scripts/push-all.sh              # 推到 origin + gitee
#   ./scripts/push-all.sh origin       # 只推 origin
#   ./scripts/push-all.sh gitee main   # 指定分支（否则用当前分支）
# gitee 是 SSH remote 时自动带上 ~/.ssh/id_ed25519（避免多 key 干扰）。
set -uo pipefail

# 解析参数：最后一个若已是分支名则用之，否则取当前分支
BR=""
REMOTES=()
for a in "$@"; do
  REMOTES+=("$a")
done
if [ ${#REMOTES[@]} -gt 0 ]; then
  last="${REMOTES[-1]}"
  if git show-ref --verify --quiet "refs/heads/$last" 2>/dev/null; then
    BR="$last"; unset 'REMOTES[-1]'; REMOTES=("${REMOTES[@]}")
  fi
fi
[ -z "$BR" ] && BR="$(git rev-parse --abbrev-ref HEAD)"
[ ${#REMOTES[@]} -eq 0 ] && REMOTES=(origin gitee)

# gitee SSH 用指定 key；HTTPS remote 会忽略此项，无副作用
mkdir -p "$HOME/.ssh"
export GIT_SSH_COMMAND="${GIT_SSH_COMMAND:-ssh -i $HOME/.ssh/id_ed25519 -o IdentitiesOnly=yes -o ConnectTimeout=20}"

rc=0
for r in "${REMOTES[@]}"; do
  url="$(git remote get-url "$r" 2>/dev/null)" || { echo "✗ $r: 无此 remote"; rc=1; continue; }
  echo "→ push $BR → $r  ($url)"
  if out="$(git push "$r" "$BR" 2>&1)"; then
    echo "  ✓ ok"
    [ -n "$out" ] && printf '%s\n' "$out" | sed 's/^/    /'
  else
    echo "  ✗ FAILED"
    [ -n "$out" ] && printf '%s\n' "$out" | sed 's/^/    /'
    rc=1
  fi
done

echo ""
[ "$rc" -eq 0 ] && echo "全部推送成功 ✓" || echo "有 remote 推送失败 ✗（见上）"
exit $rc
