# Static leaderboard website

The leaderboard is a static site built from one or more **sanitized public exports**
(`contact-bench export RUN_ID --public`). It needs no API keys, no paid inference and no
backend. Visitors can only read precomputed JSON/CSV; nothing on the site can start a
benchmark run.

## Build

```bash
contact-bench build-site exports/RUN_ID [exports/OTHER_RUN ...] --out site_build
```

or from Python:

```python
from contact_bench.site.build import build_site
build_site([Path("exports/RUN_ID")], Path("site_build"))
```

The builder:

- validates each export (`manifest.json` must carry `schema_version`, `protocol_version`,
  `condition_key` and `run_id`; unknown files such as private task manifests are refused);
- copies each export to `site_build/data/<condition_key>__<run_id>/`. Each export stays a
  separate entry. Exports are never pooled, even when two runs share a condition key;
- writes `site_build/data/index.json` listing every entry with its condition fields;
- copies `index.html`, `assets/app.js` and `assets/style.css`;
- scans the whole output for credential-like strings and removes the build if any are found.

Synthetic or offline runs (`fixture_data: true`) display a conspicuous FIXTURE / DEMO banner.

## Security notes

- Model-generated text (clues, words, model ids) is inserted only with `textContent`.
  `app.js` never uses `innerHTML`, `outerHTML`, `insertAdjacentHTML` or `document.write`.
  A Content-Security-Policy meta tag blocks inline and third-party scripts.
- The site loads no CDN or other external resources.
- Private run material (task manifests with seeds, raw request logs, credentials) is not part
  of a public export and cannot be added to the site build.

## Local preview

`fetch()` needs an HTTP server, so opening `index.html` from disk will not work:

```bash
python -m http.server 8000 -d site_build
# open http://localhost:8000/
```

## Deployment (researcher action)

Deploying, buying a domain and publishing results are researcher decisions. Before you
deploy, confirm that the export's release policy (secrets, omniscient audit, transcripts)
has been approved. `site_build/` is a plain directory of static files, so any conventional
static host works:

- **GitHub Pages:** push `site_build/` to a `gh-pages` branch, or publish it with the
  `actions/upload-pages-artifact` and `actions/deploy-pages` workflow. Add an empty
  `.nojekyll` file.
- **Netlify / Cloudflare Pages:** set the publish directory to `site_build` and leave the
  build command empty, or upload the built folder.
- **Amazon S3 + CloudFront:** `aws s3 sync site_build/ s3://BUCKET/ --delete`, then enable
  static website hosting or put CloudFront in front of the bucket.

Keep earlier released snapshots under versioned paths or tags instead of overwriting them.
