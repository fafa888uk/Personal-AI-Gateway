# DNS — ai.fafa888.uk

域名由用户指定：**ai.fafa888.uk**

## 记录（已创建，2026-11-14 08:52，主聊天验证：A → 3.12.156.80，仅 DNS）

| 类型 | 主机记录 | 值 | TTL | 备注 |
|---|---|---|---|---|
| A | `ai` | `3.12.156.80` | 600（或默认） | 指向 Spark 面板服务器 |

- 完整域名：`ai.fafa888.uk`
- 目标服务器：EC2 i-09a6adfe864e75794，公网 3.12.156.80，us-east-2
- Caddy 配置（`infra/Caddyfile`）按此域名承接 HTTPS；域名在
  `.env` 中以 `GATEWAY_DOMAIN=ai.fafa888.uk` 配置，可改。
- 验证方法（记录生效后）：`curl -s -o /dev/null -w "%{http_code}\n"
  https://ai.fafa888.uk/api/health` 应返回 200；浏览器打开
  `https://ai.fafa888.uk` 应显示登录页。
- 注意：该服务器 443 端口已有 DY Control 的 nginx 在用；网关不得
  盲目绑定 80/443，部署时须与现有 Caddy/nginx 共存方案核对
  （见部署文档），不得破坏 dy.fafa888.uk。
