# Cipher Skill catalog

每个目录是一个可审核的 Skill 包，入口文件固定为 `skill.yaml`。`source: github` 只表示上游项目来源，不会在运行时执行远程代码；管理员必须先同步、扫描、验证签名并发布，用户才能安装。

新增 GitHub Skill 时请保留：

- `sourceUrl`、`license` 和固定的 `upstream.release` 或 `upstream.commit`
- 明确的权限清单、输入 schema 和执行限制
- 一个 Cipher 适配器（对应 `app/skill_engine.py`），避免把上游仓库内容直接当作可执行插件

这样目录可以扩展到检测工程、漏洞管理、数字取证和云安全等工作流，而不绑定 CAPE Case。
