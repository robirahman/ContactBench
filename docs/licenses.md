# Source and license inventory

| Asset | Source | License | Notes |
|---|---|---|---|
| Code (`contact_bench/`, `tests/`, `configs/`) | ContactBench authors | **To be chosen by the researcher** | `pyproject.toml` deliberately leaves the license unset |
| `lexicons/mechanics_fixture.txt` | The ten-word example from spec §6.6 | CC0-1.0 | Fixture only |
| `lexicons/dev_fixture.txt` | Hand-written list of 747 common English words | CC0-1.0 | Development fixture, not a production lexicon |
| `lexicons/enable.txt` | ENABLE word list (via github.com/dolph/dictionary `enable1.txt`, upstream SHA-256 `3f161302…`), filtered to 3–20 letters: 172,608 words | Public domain | Candidate production lexicon for the closed-book and lookup-tool conditions |
| Production lexicon | Researcher-selected | Check before redistributing | Use `contact-bench build-lexicon`. If the source cannot be redistributed, publish the recipe and its hash instead |
| Generated transcripts | Model outputs from live runs | Check provider terms | Declare in `docs/dataset_card.md` before release |
| Website assets (`contact_bench/site/static/`) | ContactBench authors | Same as code | No third-party scripts, fonts or CDNs |
| Python dependencies | See `requirements.lock` | Their respective licenses | pydantic, PyYAML, openai, anthropic, google-genai, pytest, hypothesis |
