# 安装与首次使用

## 下载

打开 [最新发布](https://github.com/zongmoseu/ll-xiumi/releases/latest)。第一次使用，下载 `ll-xiumi-workflow-v版本号.zip`：它同时包含 skill、插件和本文档。已有其中一部分，也可单独下载 `wechat-brand-layout-v版本号.zip` 或 `ll-xiumi-importer-v版本号.zip`。

## 安装 AI skill

将解压后的 **整个** `skills/wechat-brand-layout` 文件夹放到 AI 助手的技能目录，不要只复制 `SKILL.md`。在使用默认目录的 Codex 中，是：

- Windows：`C:\Users\你的用户名\.codex\skills\wechat-brand-layout`
- macOS / Linux：`~/.codex/skills/wechat-brand-layout`

如果设置了 `CODEX_HOME`，使用该目录下的 `skills`。让助手刷新技能列表或开启新会话后，使用名称 `wechat-brand-layout` 调用。其他支持技能的助手请使用其技能安装方式，并确保能读取本机文件、执行 Python 脚本。

Python 需要 3.10+。可以让 AI 检查并安装依赖；人工安装的命令是：

```sh
python -m pip install -r /你的路径/wechat-brand-layout/requirements.txt
```

本项目不提供 AI 模型或账号，需要使用你自己的 AI 助手。

## 安装浏览器插件

1. 解压插件，并放到一个以后不会随手删除的位置。
2. Edge 打开 `edge://extensions/`；Chrome 打开 `chrome://extensions/`。
3. 打开「开发者模式」，点击「加载已解压的扩展」。
4. 选择 **直接包含 manifest.json** 的 `ll-xiumi-importer` 文件夹。不要选择 ZIP 或整个工作流根目录。
5. 在浏览器扩展菜单中找到「ll帮你喂给xiumi」，可将它固定到工具栏。

已安装旧版本时，可将新版文件覆盖到原来加载的插件目录，再在扩展管理页点击重新加载。无需为了改名重复安装一份。

## 第一次：建立品牌配置

把稿件发给 AI，并说：

```text
用 wechat-brand-layout 为我的公众号排版。
账号名称是……，这些是我常用的素材和参考推送。
请先建立品牌配置，再处理这篇 Word。
```

可以提供：封面或封面模板、Logo、正文开头、尾图/账号名片、分隔元素、一两篇喜欢的历史推送。用文件夹、ZIP 或单独文件均可；无需全部齐备。AI 会检查素材用途并保存配置，必要时询问容易混淆的素材。二维码归属不明确时不要直接启用。

没有素材可以明确说“先用基础样式”。已有配置时，下一篇只需要说明账号并提供稿件；换账号则另建配置。

## 每次：预览、修改、导入

AI 应交付 `preview.html` 和 **article.xiumi.json**。浏览预览，直接说需要调整的位置，例如：

> 这两张照片左右排，中间留 8px；每张照片仍然独立。

在秀米新建空白图文，打开插件，选择最新 JSON，点击「导入正文与图片」。上传过程中保持页面和插件打开，不切换稿件。完成后核对标题摘要、配图、图注、署名，保存、重新打开，再使用插件的核验按钮。

JSON 已带图片文件内容，通常不需要再逐张选择原图。Word 中已经拼好的照片，AI 可在边界清楚时按要求拆分；模糊、重叠或缺少完整边界的情况需要原片，不能恢复原图本来就没有的信息。

## 常见问题

**插件里选不到 Word？** Word 交给 AI，插件只接收 AI 导出的 `.xiumi.json`。

**名字还显示旧的？** 在扩展管理页对已安装的插件点击重新加载，重新打开弹窗。

**提示没有登录？** 先在同一个浏览器里登录秀米并打开图文编辑页，再重试。

**有图片上传失败？** 下载插件提供的错误说明交给 AI；它包含失败阶段和图片序号。不要靠手工修改图片后缀解决格式问题。

**复制 skill 后没有我以前的品牌？** 品牌素材在本机数据目录，与 skill 代码分开存储。迁移时复制整个 `wechat-brand-layout/profiles/` 数据目录，避免丢失其素材子目录。
