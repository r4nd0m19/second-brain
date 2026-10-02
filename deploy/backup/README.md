# 本地备份与恢复（T031 · 本地部分）

> 备份形态与理由见 `specs/001-core-qa/research.md` R8：**数据库 → 客户端加密 dump**；
> **原文件 → 增量明文镜像**（与源同信任域，加密不增防护；远程阶段以密文上云）。
>
> **远程异地同步**：待服务器阶段与同厂对象存储一起配——db 密文原样上传；文件镜像届时以加密方式上传。

## 组成

| 文件 | 作用 |
|------|------|
| `backup.sh` | 数据库（pg_dump -Fc → gpg AES-256 加密）+ 原文件增量镜像（rsync，删除同步生效 FR-011）→ `server/data/backups/`；自动清理 14 天前的旧 db 备份 |
| `restore.sh` | 恢复数据库/原文件；`restore.sh drill` 一键完整演练（**先自动做一次新鲜备份**，再恢复对照：行数/内容指纹/文件 sha256 全量一致） |
| `~/.config/second-brain/backup.key` | 数据库备份的加密密钥文件（仅本机 root 可读） |

## 初始化（新机器/换机时）

```bash
# 1) 生成密钥（32 字节随机）
mkdir -p ~/.config/second-brain && chmod 700 ~/.config/second-brain
openssl rand -base64 32 | tr -d '\n' > ~/.config/second-brain/backup.key
chmod 600 ~/.config/second-brain/backup.key
cat ~/.config/second-brain/backup.key   # ← 抄进密码管理器！丢了加密备份无法恢复
```

## 日常操作

```bash
# 手动跑一次备份
deploy/backup/backup.sh

# 恢复演练（建议每月一次；SC-008 验收项）
deploy/backup/restore.sh drill

# 灾难恢复：把最近备份恢复回正式库（会覆盖！）
deploy/backup/restore.sh db "$(ls -1t server/data/backups/db/*.gpg | head -1)" secondbrain

# 只取回原文件到某目录（从镜像同步）
deploy/backup/restore.sh files /tmp/取回
```

## 定时（cron 两条）

安装（本机/服务器各执行一次；**cron 尚未在本机安装，待确认后执行**）：

```bash
( crontab -l 2>/dev/null | grep -v "deploy/backup/backup.sh" ; \
  echo "17 3 * * * SECOND_BRAIN_BACKUP_STALE_ONLY=1 /root/code/second-brain/deploy/backup/backup.sh >> /root/code/second-brain/server/data/backups/backup.log 2>&1" ; \
  echo "@reboot sleep 90 && SECOND_BRAIN_BACKUP_STALE_ONLY=1 /root/code/second-brain/deploy/backup/backup.sh >> /root/code/second-brain/server/data/backups/backup.log 2>&1" ) | crontab -
```

| 条目 | 作用 |
|------|------|
| `17 3 * * *` | 每日常规（机器在线时） |
| `@reboot` | 开机补跑（WSL/笔记本不常在线：启动后若 20 小时内没备份过则补一次） |

`STALE_ONLY=1` = 距上次备份不足 20 小时则跳过（两条互不重复）；手动执行永远真的跑一次。
脚本自带文件锁，手动/定时/多会话并发触发时只会执行一个。
查看日志：`tail -f server/data/backups/backup.log`

## ⚠️ 两条硬规则

1. **密钥文件丢失 = 数据库备份全部作废**（零知识加密，无找回；原文件镜像不受影响）。
   密码管理器里必须有一份，理想情况下再手写一份放安全的地方。
2. 恢复演练要**定期做**（每月一次）：备份的价值只有在"能恢复"时才存在。
