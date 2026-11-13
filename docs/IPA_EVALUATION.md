# IPA 评估 — 未签名包 + 用户自签

> 用户 2026-11-14 确认：IPA 签名由用户自签就行。
> 状态：**评估中，未验证**。PWA 是第一版先行的 iPhone 入口，
> IPA 不阻塞网关与网页聊天。

## 结论（先行判断，以 CI 实际构建为准）

- 交付物：未签名 IPA（Flutter 在 macOS runner 上 `flutter build ipa
  --no-codesign` 生成 .app → 打包 .ipa）。
- 我方不提供签名证书或 Apple Developer 账号。
- 第一版形态（用户 2026-11-14 定 Flutter 路线）：**Flutter 客户端**
  （与 Windows/macOS 共用一套代码）；此前“WKWebView 壳首选”的
  决定已被 Flutter 路线取代。

## 构建方案（待 CI 验证）

- 本地 Linux 开发机无 Xcode，本地编不出真 IPA。
- 方案：GitHub Actions macOS runner 上 `flutter build ipa
  --no-codesign` 生成未签名 .app，再以 `Payload/<App>.app` 结构
  zip 打包为 .ipa；同一工作流的 Windows runner 出 EXE、macOS
  runner 出 DMG。
- 待验证项：runner 上的 Flutter/Dart 与 Xcode 版本、无签名编译
  是否一次通过、产物 .ipa 的大小与结构、安装前用户自签是否成功。

## 用户自签安装（待实际验证，以用户已有侧载方式为准）

以下方式按用户实际装成功的为准填写；未验证的标注“未验证”：

| 方式 | 步骤（待验证后补全） | 状态 |
|---|---|---|
| AltStore | 待验证后补全 | 未验证 |
| SideStore | 待验证后补全 | 未验证 |
| ESign | 待验证后补全 | 未验证 |
| Xcode 个人账号自签 | 待验证后补全 | 未验证 |

## 分发：GitHub Releases

- 未签名 IPA 随版本发布到 GitHub Releases；更新时用户去 GitHub
  下新版 IPA，自己重新签名安装。
- 版本号与服务端版本信息接口（`GET /api/v1/app/version`）一致；不一致
  时以服务端信息为准并明确提示。

## 明确不承诺

- 未在 CI 上编出来之前，不声称 IPA 可用。
- 未在用户设备上自签装成功之前，不声称安装流程可行。
- 绝不拿假包、空壳 .ipa 或改名的 zip 冒充可安装的 IPA。
