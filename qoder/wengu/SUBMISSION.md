# 提交材料对照（Qoder 赛题）

> 本文件把「赛题要求的提交物」逐条对应到本仓库里的位置，方便评审与提交平台填写。
> **标 ✅ 的已经完成；标 ⬜ 的是只有你能做的一步（需要你的 Qoder 账号与 GitHub 权限）。**

| 赛题要求 | 对应内容 | 状态 |
| --- | --- | --- |
| 项目网站网址（Qoder Sites，公开可访问） | https://wengu-review-coach-8pp3v4ytw4k.qoder.zone （`website/` 是站点源码） | ✅ 已发布（公开） |
| 代码仓库 | https://github.com/gegedda/powercontext-fork/tree/qoder/wengu/qoder/wengu | ✅ 已推送 `qoder/wengu` 分支 |
| 运行说明 | `README.md` 第 4 节（Linux/Windows 两条路径、依赖、启动命令、配置项） | ✅ |
| 验证样例 | `docs/verification-sample.md`（6 步 + 预期输出）；`records/` 是对应的真实产物 | ✅ |
| Qoder 开发记录 | `docs/qoder-development-record.md`（每阶段的需求描述、关键问题、验证）；需补 Qoder 对话截图与账号 UID | ⬜ 需补截图 + UID |
| 技术结合有效 | seekdb：`records/tech.json` + `records/ask.json` 的召回明细；PowerContext：`create_artifact / replace_artifact` 事件与 revision 递增 | ✅ |
| 使用效果材料（鼓励） | 暂无真实外部用户数据；有 3 位同学试用后的反馈可补在此处（不要编造） | ⬜ 可选 |

## 提交平台需要填的三项

1. **项目网站网址**：https://wengu-review-coach-8pp3v4ytw4k.qoder.zone （已公开，无痕窗口可打开）。
2. **代码仓库地址**：https://github.com/gegedda/powercontext-fork/tree/qoder/wengu/qoder/wengu
3. **Qoder 账号 UID**：Qoder CN 使用阿里云账号体系，账号 UID 即**阿里云账号 UID**（16 位数字），
   可在阿里云控制台右上角头像 →「账号」→「基本信息」查看；Qoder Desktop 左下角头像 →「设置」→
   「个人资料」（Profile）也会显示当前登录账号信息。**只在提交平台表单里填写，不要写进本仓库或公开站点。**

## 建议的提交前自检

```bash
# 1) 站点：无痕窗口打开，图片能显示、链接能点开
# 2) 仓库：从干净 clone 按 README 第 4 节跑一遍
cd qoder/wengu
pip install -e ".[seekdb]"
./scripts/verify.sh          # 需要 Linux；Windows 用 pip install -e . 后逐条执行
# 3) 记录：确认 records/ 里的文件是本次提交对应的输出
```

## 引用与来源

- 示例语料是对公开论文/教材内容的**阅读笔记**（LSM-Tree 1996、ARIES 1992、Raft 2014、HNSW 2018、
  OceanBase TPC-C PVLDB 2022 等），不是原文转载。
- 依赖的上游项目：OceanBase seekdb（Apache-2.0）、PowerContext（Apache-2.0）、
  bge-small-zh-v1.5（MIT）、FastAPI、pypdf、NumPy。
