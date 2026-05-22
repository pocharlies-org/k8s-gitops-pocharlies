# translations-app migration - 2026-05-22

## Completed

- Built the current Sauvage runtime source commit
  `659327b38a590026e4f6c066b7f9b64e6c701c56`.
- Pushed image to Harbor:
  `harbor.e-dani.com/homelab/shopify-translation-app@sha256:58b61fbf535765078af4d068f5f7aedb2819d09d62a18c4a510e9adb8246077c`.
- Created GitOps repo:
  `https://github.com/pocharlies/k8s-shopify-translations-pocharlies`.
- Added ArgoCD app `shopify-translations`.
- Migrated `synapse` DB from Docker `shared-postgres` to k8s
  `databases/postgres-shared`.
- Expanded `postgres-shared` PVCs after restore pressure:
  data `20Gi -> 80Gi`, WAL `5Gi -> 20Gi`.
- Restored Synapse translation row counts:
  - `translation_plan`: `3102`
  - `translation_locale`: `61982`
  - `translation_unit`: `821736`
- Recreated target `webui` role with login/BYPASSRLS and read grants.
- Wrote `secret/skirmshop/translations` in Vault for ESO.
- Created RabbitMQ k8s vhost `/synapse` and durable topic exchange `events`.

## Validation

- `shopify-translations`: `Synced/Healthy`.
- `postgres-shared`: `Synced/Healthy`.
- `k8s-infra`: `Synced/Healthy`.
- `translations-app` Deployment rolled out in namespace `skirmshop`.
- Direct Traefik Edge smoke:
  `https://127.0.0.1:7443/translations/` with host
  `skirmshop.e-dani.com` returns `302`.
- No non-running pods after deployment.

## Not Cut Over Yet

Docker `translations-app` is still running because the public NGINX block on
Sauvage still proxies `/translations/` to `http://127.0.0.1:3458`.

Attempted NGINX edit was blocked by root-owned config and sudo requiring a
password. Do not stop the Docker container until this block is changed to:

```nginx
location ^~ /translations/ {
    proxy_pass https://127.0.0.1:7443;
    proxy_ssl_verify off;
    proxy_ssl_server_name on;
    proxy_ssl_name $host;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection 'upgrade';
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Prefix /translations;
    proxy_cache_bypass $http_upgrade;
    proxy_connect_timeout 300s;
    proxy_send_timeout 300s;
    proxy_read_timeout 300s;
}
```

Then run:

```bash
nginx -t && systemctl reload nginx
curl -sk -H "Host: skirmshop.e-dani.com" -o /dev/null -w "%{http_code}\n" https://127.0.0.1:7443/translations/
curl -sk -o /dev/null -w "%{http_code}\n" https://skirmshop.e-dani.com/translations/
docker update --restart=no translations-app
docker stop translations-app
```

Rollback:

```bash
docker start translations-app
```
