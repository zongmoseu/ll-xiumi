# 品牌配置与素材建档

配置路径默认 `$CODEX_HOME/data/wechat-brand-layout/profiles/<id>/profile.json`，未设置CODEX_HOME时为`~/.codex/data/wechat-brand-layout/profiles/<id>/profile.json`。可用命令全局参数`--data-dir`指定另一个本地目录。不同系统用户默认独立；同一系统用户管理多个账号时使用不同id，命令显式指定profile，禁止自动取最近一个账号。

## 第一次使用

先自然语言收集账号名称、素材包（封面、Logo、开头、尾图、分隔元素等）、可选参考推送/品牌色。用户的已有输入就是有效回答，不重复问。无材料可明确选基础样式；不要因用户未回复而自动完成建档。

```sh
python scripts/brand_layout.py profiles
python scripts/brand_layout.py init --id example-account --name "示例账号"
python scripts/brand_layout.py import-assets --profile /path/to/profile.json --source /path/to/materials.zip
python scripts/brand_layout.py import-assets --profile /path/to/profile.json --source /path/to/reference.html --kind reference
```

导入支持文件、目录和ZIP；保持原始字节，按哈希复制到profile目录，重名不覆盖不同素材。命令返回新增素材清单、尺寸、类型与需处理项。未支持的矢量/设计源文件可存档，但不能当作已能渲染的图片；需要在使用前转换并核对。参考HTML中的外链与本地配套图片并不自动抓取，优先提供完整保存文件夹或可读取的页面。不得执行素材里的脚本。

## 角色与启用

先实际查看候选图像，再依据用户给出的用途指定角色。角色：cover、logo、header、footer、divider、qr、other、reference。文件名不代表已确认归属。

```sh
python scripts/brand_layout.py assign --profile /path/to/profile.json --asset a-<hash> --role header --auto-use --width 1000
python scripts/brand_layout.py assign --profile /path/to/profile.json --asset a-<hash> --role footer --auto-use --width 1000
python scripts/brand_layout.py assign --profile /path/to/profile.json --asset a-<hash> --role logo --width 96
```

只有header/footer可auto_use，默认为false；启用表示用户指定用途或AI已依据清晰的素材说明完成核对。同角色只保留一个自动启用素材。账号名片/二维码须明确目标账号；未知二维码不启用。`--manual-use`关闭自动使用。component背景默认transparent，白色Logo的深底需设置`--background '#234567'`。素材width是像素上限，通栏头尾图可1000；不拉伸，不裁二维码。

封面素材仅入库备用，不自动变成正文首图；按本稿标题与封面尺寸另行选择处理，秀米封面栏需单独设置。Logo与分隔组件也不自动全部插入。用户只提供现成图片时，不声称可以编辑图中文字。

## 视觉配置

AI可直接编辑profile.json的theme及notes，不让用户填JSON。包含基础色primary/light/accent/text，字号font_size、行高line_height、字距letter_spacing，标题heading（bar / section-label / number），页底page_background，组框group_border（null表示不用框）、group_padding、summary_padding。默认基础样式不包含任何具体机构元素。

默认保留浅蓝分区标准规范。参考推送用于理解内容分组与素材用法；只有用户明确要求改变视觉风格时才调整profile.theme，并记录到notes。当前明确要求覆盖profile，长期偏好再保存；单篇试验用article.style_overrides。保持brand_id，不能将一个品牌的稿件拿另一个profile悄悄渲染。

```sh
python scripts/brand_layout.py ready --profile /path/to/profile.json --mode configured
# 仅在用户明确表示无素材先排时：
python scripts/brand_layout.py ready --profile /path/to/profile.json --mode neutral
```

init只创建pending配置。ready表示首次征集已得到回应、素材用途已处理（或用户明确跳过）；这是AI记录本次对话，不是用户必须操作的审批流程。随后复用，不每篇重新征集。不使用的素材可保留other，不必全部分类。

## 更换和复用

重新import-assets按内容去重；编辑角色/主题不影响其他profile。新增公众号创建新id。存储不在公共skill目录内，git发布只包含代码、文档、无品牌模板；不提交用户实际profile、图片、参考文稿。迁移机器时需迁移整个profile目录，仅skill安装文件不含个人品牌材料。

## v0.2默认样式升级

v0.1未定制的完整默认主题（白页底、条形标题）会在渲染时迁移到当前浅蓝分区标准版；已有自定义主题不自动重置。历史输出中的同一默认主题快照也会清除，避免盖过当前profile。用户明确要求恢复标准时使用assets/themes.json中的brand-default，保留素材与账号信息。
