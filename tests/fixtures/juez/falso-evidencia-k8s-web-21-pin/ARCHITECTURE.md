# ARCHITECTURE.md — k8s-web-pocharlies

> `www.e-dani.com`: web corporativa de *e-dani · AI Solutions* (MORENOIBAÑEZ S.L.). Sitio **Astro estático** (es `/` + en `/en/`) servido por nginx.
> Mismo patrón que `k8s-blog-pocharlies`. Escrito por `architect` (SC-1426).

## 1. Clientes y versiones

| cliente | repositorio / ruta | versión desplegada | cómo se despliega |
|---|---|---|---|
| Web `www.e-dani.com` (+ redirección del apex, `k8s/apex-redirect.yaml`) | `src/`, `astro.config.mjs`, `k8s/` | imagen `harbor.e-dani.com/homelab/web-edani:<sha>` pinneada por `newTag` en `k8s/kustomization.yaml` (ver ese fichero, sin sha aquí) | ArgoCD app `web` |

Una sola web bilingüe; sin apps.

## 2. Dependencias, en ambos sentidos

- **Depende de** — Harbor (push desde CI), `traefik-edge` (IngressRoute `k8s/ingressroute.yaml`), Cloudflare/DNS público.
- **Dependen de él** — nadie técnico; enlaces de política de privacidad de las apps iOS (`legal/apps-privacidad`, `soporte`) apuntan a esta web
  (**cambiar esas URLs rompe las fichas de App Store**).
- **ArgoCD** `web`: repo `pocharlies-org/k8s-web-pocharlies`, path `k8s`, tronco **`main`**, sync automático.

## 3. Stack

| pieza | versión | para qué | no se usa en su lugar |
|---|---|---|---|
| Astro (^7.3.5, `output: static`, i18n es/en, sitemap) | `package.json` / lock | sitio | Next/WordPress |
| `astro:assets` (`<Picture>`, AVIF/WebP) sobre `sharp` (en el lock) | — | imágenes de la home y del portfolio, con `widths` y `sizes` explícitos | pipeline de imágenes propio, `image.layout` (emite `style=""`, que la CSP bloquea) |
| zod (`src/content.config.ts`) | — | esquemas de colecciones (soluciones, casos, legal) | frontmatter sin validar |
| nginx:alpine (`images/web.Dockerfile`) | — | servir estático | — |
| Kustomize | — | `k8s/` | Helm |

## 4. Componentes compartidos

| concepto | pieza canónica | ruta | quién la usa |
|---|---|---|---|
| Tabla de rutas por idioma (hreflang, selector) | `src/i18n/routes.ts` | ídem | todas las páginas |
| Plantillas de página compartidas es/en | `src/components/pages/` | ídem | ambos idiomas |
| Layout base | `src/layouts/Base.astro` | ídem | todas |
| Imagen + alt de solución, caso y hero | `src/i18n/images.ts` (clave `sol-`/`caso-` + `fileOf(id)`; valida `src/assets/home/alt.json` con zod y rompe la build si falta imagen o alt) | `src/assets/home/` | `Home.astro`, `Portfolio.astro` vía `Card.astro` |
| Tema (auto/claro/oscuro) y clase `js` | `public/theme-init.js` (síncrono, el primero del `<head>`) + botón en `Base.astro` | ídem | todas |
| Scripts de página | `src/scripts/` (`menu`, `header`, `reveal`, `hero`, `hero-net`) | ídem | `Base.astro` y `Home.astro` |
| Red de nodos del hero | `src/lib/net.ts` | ídem | `Net.astro` (SVG) y `hero-net.ts` (canvas) |

## 5. Cómo se construye aquí

Contenido en `src/content/{soluciones,casos,legal}/{es,en}/` con esquema zod; textos de UI en `src/i18n/{es,en}.json` (los de `chrome.ts` deben
moverse allí). Una plantilla por tipo de página, compartida entre idiomas: **no duplicar páginas por idioma**.

## 6. Tests y validaciones

```sh
npm ci && npm run build && npm run check   # build: el esquema zod y images.ts fallan si falta un campo, imagen o alt
```
`npm run check` es `node scripts/check-dist.mjs` (solo `node:fs`, lee `dist/`): URLs-contrato congeladas (con el NIF), enlaces de la home
al índice de soluciones, al portfolio y a las 6 legales del pie, hreflang, sitemaps y robots, CSP (ni `<style>` ni `<script>` en línea ni
`style=""`), cero terceros, `theme-init.js` antes de las hojas de estilo, imágenes de la home (`width`/`height`/`alt`, lazy salvo el hero,
`<picture>` avif+webp, recuento N), `IntersectionObserver` y `prefers-reduced-motion`. Quitar o renombrar una URL de su lista es una
decisión explícita en el diff. Sin tests unitarios.

## 7. CI/CD y despliegue

- `build.yml` (build-and-push de la imagen a Harbor en push a `main`; en `pull_request` solo construye, y ahí corre `check-dist` porque
  `images/web.Dockerfile` lo ejecuta tras `npm run build`); como en el blog, ArgoCD sigue el `newTag` fijado: tras el build hay que
  subir `newTag` al sha (segundo commit).
- **Validación en producción**:
  `curl -sI https://www.e-dani.com/ | head -1` (200), `curl -sI https://www.e-dani.com/en/ | head -1`, `curl -sI https://e-dani.com/ | grep -i location`
  (redirige a www) y `kubectl -n argocd get app web -o jsonpath='{.status.sync.status} {.status.health.status}'`.

## 8. Decisiones y trampas

- El CI construye pero no despliega: olvidar el bump de `newTag` deja la web sin cambios con ArgoCD en verde.
- Astro ≥6 no lee `src/content/config.ts`: el esquema vive en `src/content.config.ts`.
- `theme-init.js` va externo y sin `defer` porque la CSP no admite scripts en línea y con `defer` el tema parpadea; es lo único de `public/`
  que no pasa por Astro. La clase `js` la pone él y solo él (`menu.ts` ya no): el reveal y el botón de tema parten ocultos bajo `html.js`.
- Los tokens de color son `light-dark(claro, oscuro)` en una sola tabla (`global.css`; `[data-theme]` fuerza `color-scheme`): un script no puede leer `--accent`
  (devuelve el texto `light-dark(…)`), lee `getComputedStyle(el).color` de un elemento con `color: var(--accent)`.
- El enlace estirado de la tarjeta (`.more::after`) vive solo en `.cd` y `.mini` (`position: relative`); sobre un `.more` fuera de ellos cubriría la página.
- La red del hero anima como máximo 5 s y se congela (WCAG 2.2.2); con `prefers-reduced-motion` solo se pinta el último cuadro.
- `.company/specs/SC-1333`, `SC-1337` documentan el rediseño anterior; INFRA-396 el de la home actual.

Última verificación contra el código: 2026-10-10 · INFRA-806
