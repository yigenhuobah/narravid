# 内网部署示例（单用户）

`docker-compose.example.yml` + `Caddyfile.example`：narravid 仅容器网暴露，Caddy 提供 Basic Auth。

```bash
# 生成密码哈希
docker run --rm caddy:2 caddy hash-password --plaintext 'your-password'
# 编辑 Caddyfile.example 后：
docker compose -f deploy/docker-compose.example.yml up -d --build
```

打开 `http://<host>:8080`。不要把 5000 端口直接映射到局域网。
