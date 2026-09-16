# 有序 Seqara 品牌资产

`seqara-app-icon.svg` 是桌面应用图标：石墨黑圆角底、柔白层叠 LOGO，不含品牌文字或 DSH 标识。通过 `scripts/build-app-icon.py` 从 `seqara-mark.svg` 构建；该图形由用户最初提供的 LOGO 提取为三个独立轮廓，统一输出 EXE 使用的 ICO 和窗口／任务栏使用的 ICO、PNG。ICO 包含 16–256 像素共 11 个尺寸。

`seqara-signature-day.svg` 与 `seqara-signature-night.svg` 是软件内横排字标。
保留既有层叠图形，中文基于 Noto Sans SC Medium，英文基于 Geist Medium；字形已转曲，运行时不依赖用户安装品牌字体。

SVG 母版保留日夜色值。软件品牌区通过共享 `sidebar.css` 显示为浅色主题下的墨黑、深色主题下的柔白，DSH 角标使用中性灰底；该规则同时覆盖已有离线缓存。主操作沿用共享设计变量中的中性色。

品牌文字的可访问名称为“有序 Seqara”。应用正文保持真实文本，使用 Segoe UI / Microsoft YaHei 字体栈。系统字体文件不随仓库分发。
