# 第三方依赖与分发

Seqara 自有集成代码使用 Apache-2.0。第三方库、插件和系统软件分别受各自许可约束。根目录 LICENSE 不替代其许可。

| 组件 | 用途 | 来源 / 许可说明 |
| --- | --- | --- |
| DeepSeek Harness | 智能会话与插件运行时 | `@deepseek-ai/dsh` 0.1.5-rc.1；包元数据声明 MIT；[上游](https://github.com/deepseek-ai/deepseek-harness) |
| PySide6 / Qt | 原生界面与 WebEngine | LGPL/GPL/商业许可选项及模块级条款；检查安装包内许可；[Qt 许可](https://www.qt.io/licensing/) |
| Node.js | JavaScript 运行时 | 自身及内含组件的许可见 Node 安装目录 LICENSE；二进制打包时一并复制 |
| Python 依赖 | 表格、Word、PDF、网络与打包 | 版本见 requirements.txt 和 requirements-dev.txt；具体许可见各 distribution 的许可证文件 |
| npm 依赖 | Harness 及传递依赖 | 固定解析见 runtime/package-lock.json；安装包保留各自 LICENSE/NOTICE |
| Windows 字体 | 系统界面文字 | 使用操作系统字体，不分发系统字体文件 |
| Word / WPS | 可选转换与打印 | 用户独立安装和授权；本仓库不附带 |

`docs/dependency-inventory.json` 记录此版安装环境的依赖名称、版本与声明许可，供复核使用。它不是完整法律意见，也不替代逐包许可证文本。重新发布安装包前，应保留依赖许可证和必要通知，满足相关源码提供及替换库等要求；不能仅携带项目根目录 LICENSE。

原内部版的 PPT 编译引擎、第三方 PPT 知识包、真实案例、摄影模板均未包含在此仓库。

品牌图形与展示名称用于标识此项目；Apache-2.0 不授予商标权。品牌字标使用转曲图形，来源说明见 [品牌资产](assets/brand/README.md)。
