# 项目网站（Qoder Sites 发布源）

这个目录是作品的静态展示站，发布方式：在 Qoder 中通过 **Sites** 创建站点并指向本目录
（或把 `index.html` 与 `assets/` 上传到站点根目录），可见范围选「任何人都可访问」。

## 内容

- `index.html`：单文件站点（内联样式，无外部依赖、无 CDN、无统计脚本）
- `assets/`：五张真实运行截图（文库 / 带出处提问 / 今日复习 / 它记住了什么 / 技术证据）

## 发布前要改的两处

1. `index.html` 末尾的 `REPO_URL`：换成真实的代码仓库地址（建议直接指向 `qoder/wengu` 目录）。
2. 如果站点部署在子路径（例如 `https://xxx.com/wengu/`），把 `<a href="assets/...">` 与
   `<img src="assets/...">` 改成相对路径即可（当前已是相对路径，直接用即可）。

## 截图来源

五张截图全部来自本次 Linux 实测（openEuler 24.03 + seekdb 嵌入式 + PowerContext 1.4.1 + bge-small-zh），
不是设计稿，也没有后期合成。数据与 `records/` 里的记录对应。
