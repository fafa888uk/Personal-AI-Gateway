# 服务器环境检测（只读，2026-11-14 05:53 CST）

目标：Spark 面板服务器 EC2 i-09a6adfe864e75794，公网 3.12.156.80。
SSH 已打通：`ssh -i /home/hatch/.ssh/id_ed25519 ubuntu@3.12.156.80`
（必须显式 `-i`，本机 ssh 默认找 `/root/.ssh`）。直连验证成功，
hostname `ip-172-31-18-252`，up 4 天 8 小时，load 0.06。

## 实测结果

- OS：Ubuntu 24.04.5 LTS
- CPU/内存：2 vCPU（m7i-flex.large），7.6 GiB 内存，6.5 GiB 可用
- 磁盘：58G 总，47G 可用（20% 已用）
- Docker：29.1.3；Docker Compose：2.40.3
- nginx：master 进程在跑（root），worker 为 www-data
- 监听端口（`ss -tlnp`）：
  - `0.0.0.0:80`、`0.0.0.0:443` — nginx（DY Control 已占用，网关不得盲目绑定）
  - `0.0.0.0:22` — SSH
  - `0.0.0.0:24443`、`0.0.0.0:24444` — 3x-ui 相关
  - 仅本机：`127.0.0.1:8787`、`8788`（douyin）、`7890`、`9090`、
    `8388`、`18080`、`2053`、`39839`
  - 空闲提示：8000（网关 API 预留）、8443 等未被占用，部署时复核

## 部署前必须解决的事项（阶段 H 门禁的一部分）

1. **ubuntu 用户无权直接访问 docker.sock**：`docker ps` 返回
   `permission denied while trying to connect to the docker API at
   unix:///var/run/docker.sock`。部署前须确认以下其一（只读核查，
   不自行改权限）：`sudo -n docker ps` 是否可用，或 ubuntu 是否在
   docker 组（`id ubuntu`）。权限调整须经主聊天确认。
2. **80/443 已被 nginx 占用**：网关不得直接绑定 80/443；部署方案须
   与现有 nginx 共存（反代新域名 `ai.fafa888.uk` 到网关本机端口，
   或 Caddy 协调），不得破坏 dy.fafa888.uk。
3. **备份先行**：部署前先备份现有服务数据与配置，再动网关部署。

## 容器现状（主聊天 05:53 核实）

7 个容器全 Up：dy-portal-web/scheduler healthy，douyin-web、
login-desktop、douyin-scheduler、mihomo、dy-family-network-xui-1。
部署网关时必须与它们共存、不得干扰。
