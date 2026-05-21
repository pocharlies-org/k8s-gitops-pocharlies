# k8s-gitops-pocharlies

ArgoCD app-of-apps orchestrator — gestiona todos los repos del cluster k3s con prefijo k8s-*-pocharlies

## Cluster
- **Master**: x86 ubuntu (192.168.50.142), k3s v1.32.5
- **Workers**: nvidia-dgx (dgx1 ARM64), gx10-ec3d (dgx2 ARM64), sauvage (WireGuard edge)

## GitOps
Gestionado por ArgoCD desde [k8s-gitops-pocharlies](https://github.com/pocharlies/k8s-gitops-pocharlies).
