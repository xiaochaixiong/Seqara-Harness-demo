# 参与贡献

1. Fork 仓库，从 `main` 建立功能分支。
2. 按 README 安装开发环境；使用虚构公司、示例院校和合成表格复现问题。
3. 修改行为时增加或更新对应测试，运行 `scripts/test.ps1`。
4. 每次完成一项修改创建 Git commit；提交 PR 时描述问题、变更与验证结果。

不要提交 `.venv`、`node_modules`、用户 AppData、日志、API 配置、客户资料或来源不明素材。新增依赖需更新版本清单和第三方许可说明。涉及原生与 Agent 共用业务模块时，检查 `native/` 与 `backend/` 是否需要同步修改。

请在 PR 中说明 Windows、Python、Node.js 版本及是否依赖 Word/WPS。除非明确验证，不要宣称支持其他操作系统或任意 Office 文件无损转换。
