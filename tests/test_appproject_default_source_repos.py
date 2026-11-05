"""DGX-825: el AppProject `default` lleva sourceRepos cerrado y toda Application
del kustomization raíz lee de un repo permitido.

Si alguien añade una Application con un repoURL nuevo sin pasarlo por
infra/appproject-default.yaml, ArgoCD la deja en `repository not allowed` en
producción; este test lo falla aquí, en el PR."""
import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _documents(path: pathlib.Path) -> list[dict]:
    return [d for d in yaml.safe_load_all(path.read_text()) if d]


def _project_source_repos() -> list[str]:
    for doc in _documents(ROOT / "infra" / "appproject-default.yaml"):
        if doc.get("kind") == "AppProject":
            return doc["spec"]["sourceRepos"]
    raise AssertionError("no hay AppProject en infra/appproject-default.yaml")


def _application_repo_urls() -> list[tuple[str, str]]:
    """(nombre Application, repoURL) de todo lo que declara el kustomization raíz."""
    kustomization = yaml.safe_load((ROOT / "kustomization.yaml").read_text())
    out: list[tuple[str, str]] = []
    for rel in kustomization["resources"]:
        path = ROOT / rel
        if not path.is_file():
            continue
        for doc in _documents(path):
            if doc.get("kind") != "Application":
                continue
            spec = doc.get("spec", {}) or {}
            srcs = ([spec.get("source")] if spec.get("source") else []) + list(
                spec.get("sources") or [])
            for s in srcs:
                if s and s.get("repoURL"):
                    out.append((doc["metadata"]["name"], s["repoURL"]))
    return out


def _permitted(repo_url: str, source_repos: list[str]) -> bool:
    for pattern in source_repos:
        if pattern == "*":
            return True
        # path.Match (Go), que es lo que usa ArgoCD: `*` no cruza `/`. Aquí solo
        # hay un patrón con `*`, el de la org, y sus repos van a un nivel.
        if "*" in pattern:
            prefix, _, suffix = pattern.partition("*")
            if suffix:
                continue
            if repo_url.startswith(prefix) and "/" not in repo_url[len(prefix):]:
                return True
        elif repo_url == pattern:
            return True
    return False


class AppProjectDefaultSourceRepos(unittest.TestCase):
    def test_source_repos_is_closed(self) -> None:
        source_repos = _project_source_repos()
        self.assertNotIn("*", source_repos,
                         "sourceRepos abierto: cualquier SA con patch de "
                         "Applications puede apuntar una app a un repo propio "
                         "(cluster-admin de facto, DGX-825)")

    def test_every_application_reads_a_permitted_repo(self) -> None:
        source_repos = _project_source_repos()
        urls = _application_repo_urls()
        self.assertGreater(len(urls), 50, "el scan de Applications no encuentra las apps")
        for name, url in urls:
            self.assertTrue(
                _permitted(url, source_repos),
                f"Application {name}: repoURL {url} no está en "
                f"infra/appproject-default.yaml (añádelo antes de desplegar)",
            )


if __name__ == "__main__":
    unittest.main()
