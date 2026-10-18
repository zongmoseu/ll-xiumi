# 维护与发布

本仓库同时交付通用排版skill和秀米浏览器插件。Python脚本负责提取、素材配置、渲染与打包；语义分组由AI完成。插件接收xiumi-bridge/v3，上传图片后写入正文，不自动发布。

## 本地检查

```sh
python -m pip install -r skills/wechat-brand-layout/requirements.txt
python -m unittest discover -s tests -v
node --check plugins/ll-xiumi-importer/popup.js
node --check plugins/ll-xiumi-importer/page-runtime.js
python scripts/package_workflow.py
```

Node仅用于可选开发语法检查，不是使用插件所需的服务。测试临时生成图片与Word，不读取个人稿件；覆盖首次建档、品牌隔离、复制素材持久化、原文守恒、独立图片和Word编号兼容。

`dist/`中输出完整工作流、单独skill和插件三个ZIP及SHA256校验文件。完整包保留`skills/`、`plugins/`层级；插件单包的manifest.json位于ZIP根目录。脚本采用文件白名单与扩展名过滤，不打包profile、用户素材或工作目录。

## 版本

`VERSION`是工作流发布版本。插件的`manifest.json`版本独立维护，在变更浏览器插件时同步弹窗和错误诊断版本。发布对应Git tag及三个安装包，README下载入口指向最新Release。

## 数据与边界

品牌数据默认位于用户的`CODEX_HOME/data/wechat-brand-layout`，不位于skill目录。更新代码不能覆盖该数据；不要提交用户素材、稿件、Cookie或导入数据包。插件的浏览器本地存储键保留历史命名以兼容已有安装，界面品牌为ll。

`page-runtime.js`来源与许可见插件NOTICE.md及UPSTREAM-LICENSE，修改时保留。真实秀米服务端及编辑器可能变化；本地、模拟和真实账号结果要分别记录，不将脚本测试通过当作所有账号导入成功。
