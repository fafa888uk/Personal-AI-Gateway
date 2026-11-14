# GitHub Actions 工作流（第二份指令）

> 状态：**已写好、待浏览器创建**。5 个工作流文件已在本地分支
> `feature/workflows` 写好并通过 YAML 校验；GitHub App「Meta Muse AI」
> 无 workflows 权限，`.github/workflows/` 文件**不能经 API 推送**，
> 须用浏览器网页编辑器创建（主聊天派浏览器任务）。在浏览器创建并
> 验证前，不得谎称工作流已上线。

## 仓库与分支

- 仓库：https://github.com/fafa920q-hue/Personal-AI-Gateway（公开）
- 分支：`main` 稳定、`develop` 开发整合、`feature/*` 新功能、
  `v1.0.0` 等 Git Tag 正式发布。PR 先跑 CI，CI 通过才允许合并。

## 五个工作流

### 1. `.github/workflows/ci.yml`

代码检查、Flutter analyze、Flutter test、后端 pytest、Web 构建、
依赖安全检查。PR 与 main/develop push 触发。

### 2. `.github/workflows/build-ios.yml`

- GitHub 托管 macOS Runner；安装固定版本 Flutter、Xcode 所需依赖。
- 编译 iOS Release；禁用 Apple Code Signing（`flutter build ipa
  --no-codesign`）。
- 把 Runner.app 放入 Payload 目录打包成 .ipa；检查 IPA 内部目录
  及二进制文件完整性。
- 上传未签名 IPA 到 Actions Artifacts；版本发布时上传 GitHub Releases。
- 命名示例：`PersonalAI-1.0.0-ios-unsigned.ipa`。
- 不要求自动签名，不上传任何 Apple 证书。iOS 应用暂不依赖
  App Groups、Push Notifications 等不必要的特殊 Entitlements。
- 注意：生成 IPA 后，应检查所选签名工具能否成功签名、安装和启动，
  不得把打包成功直接当成设备安装成功。

### 3. `.github/workflows/build-windows.yml`

- Windows Runner 构建 Flutter Windows Release；运行时及依赖一同打包。
- 用 Inno Setup 等成熟方案制作完整安装程序；输出 .exe。
- 上传 Artifacts 和正式 Release。

### 4. `.github/workflows/build-macos.yml`

- macOS Runner 编译 Flutter macOS 客户端；生成 .app；制作 .dmg。
- 上传 Artifacts 和正式 Release。
- 未进行 Apple 签名和公证时，在发布说明中明确提示 macOS 安全验证限制。

### 5. `.github/workflows/deploy-server.yml`

- 构建后端和网页镜像；通过 GHCR 发布。
- 只有测试通过并满足部署审批规则时才允许更新正式服务器。
- 通过安全部署凭证连接新服务器；备份数据库并验证镜像；更新
  Docker Compose 服务；执行健康检查；失败自动恢复上一可用版本。
- 不得删除持久化数据；不得将 OpenAI 官方 API Key 写入 GitHub
  构建日志、镜像或源码。

## 发布机制

- 推送版本标签后自动构建所有客户端；构建成功后上传 GitHub Release。
- 发布说明包含版本号、更新内容和兼容性；每个安装包包含 SHA-256 校验值。
- 单个平台构建失败不能伪装为所有平台发布成功；失败时保留日志供诊断。
- 未经实际安装测试的结果必须标记为“仅构建验证”。

## 在线更新

- 服务端版本服务接口 `GET /api/v1/app/version`（见
  `docs/ARCHITECTURE.md` §13.2）：返回各平台实际可用的版本信息
  （版本号、发布日期、下载地址、SHA-256、更新说明）。
- iOS：显示新版本号和更新内容，提供获取未签名 IPA 的入口，由用户
  自己签名并安装，不尝试绕过 iOS 安全机制静默安装。
- Windows：第一阶段支持检测更新、下载新版安装程序并提示安装；后续
  在验证签名和更新包完整性后再增加安全自动更新。
- macOS：第一阶段支持检测更新、下载 DMG；后续在满足签名及公证条件
  后完善自动更新。
- 网页：服务器发布新版后提供版本提示，静态资源使用版本化缓存策略，
  刷新页面加载新版，不丢失正在保存的聊天记录。
- 后端：Docker 镜像版本化，更新前备份数据库，自动健康检查，支持
  手动回滚和失败回滚，数据库迁移必须考虑向后兼容。
- 客户端不允许内置 GitHub PAT，通过服务端安全获取发布信息和受控下载地址。
