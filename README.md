# 804-Hacks

## Publish the dashboard with GitHub Pages

This repository is a static website. It uses plain HTML, CSS, and JavaScript, so GitHub Pages can serve it directly from the repository root; no build command, package installation, or server-side runtime is required.

### 1. Push the site to GitHub

Commit and push the website files to the repository's `main` branch. The live dashboard starts at `index.html`; its navigation links to `impact.html`, `backtest.html`, `calculator.html`, and `methodology.html`. Keep `data.js` and the JSON files beside the root HTML pages because the dashboard loads them using relative paths.

### 2. Enable Pages

1. Open the repository on GitHub.
2. Select **Settings**, then **Pages** in the **Code and automation** section.
3. Under **Build and deployment**, choose **Deploy from a branch**.
4. Select branch **main** and folder **/(root)**, then select **Save**.
5. Wait for the Pages deployment to finish. Its status and URL appear on the Pages settings screen and in the repository's **Actions** tab.

### 3. Open the site

For this repository, GitHub Pages will normally publish at:

`https://divitgangrade-lab.github.io/804-Hacks/`

Open that URL in any browser. The other pages use relative links and should work under the repository subpath as well. The first deployment can take a few minutes; reload the Pages settings screen if the URL is not available immediately.

### Updating the site

Push later changes to `main`; GitHub Pages republishes the root directory automatically. Check the latest Pages deployment in **Actions** if a change does not appear. If the page returns a 404, verify that Pages is enabled for `main` and `/(root)`, that `index.html` is at the repository root, and that the deployment workflow completed successfully.

### Browser and data notes

- The dashboard can use the Open-Meteo forecast API when a browser has network access; its saved project data is available as a fallback.
- Device telemetry uses the browser's Web Serial API. That feature requires a supported browser and a secure context; the `https://` GitHub Pages site qualifies, while `file://` does not.
- The `804-Hackathon/dashboard/` folder is a second copy of dashboard pages and is not the Pages entry point when publishing from `/(root)`.