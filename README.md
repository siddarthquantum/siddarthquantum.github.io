# Sichakra — Tech & Engineering Hub

[![Website](https://img.shields.io/badge/live-sichakra.in-0A66C2)](https://sichakra.in)

Source for **[sichakra.in](https://sichakra.in)**, the personal engineering site of **Siddarth Kumar** — notes and projects on AI agents, test automation and cybersecurity.

## What's here

| Path | What it is |
|---|---|
| [`qa-agent/`](qa-agent/) | **Sichakra QA Agent** — an AI agent that explores an Android app, writes manual test cases, runs them after human approval and produces screenshot evidence. Built with Google ADK, a custom MCP server over Appium (UiAutomator2) and Gemini. Includes evals, tests, Docker setup and a secret scanner. [Live demo report](https://sichakra.in/qa-agent/) |
| [`interview/mobile-automation/`](interview/mobile-automation/) | Interview prep guide for mobile test automation with Appium |
| [`java-collections/`](java-collections/) | Day-by-day notes on the Java Collections Framework |
| [`_posts/`](_posts/) | Blog posts |
| `hanuman-chalisa/` | Personal page |
| [`index.html`](index.html) | Home page |

Related code: [**quantum-polyglot-lab**](https://github.com/siddarthquantum/quantum-polyglot-lab) — mathematics, algorithms, cryptography and quantum computing in Python, Java, C and Rust.

## Running locally

The site is plain static HTML (no build step; `.nojekyll` disables Jekyll):

```bash
python3 -m http.server 8000
# open http://localhost:8000
```

The QA agent has its own setup instructions in [`qa-agent/README.md`](qa-agent/README.md).

## Deployment

Pushed to `main` → served by GitHub Pages at the custom domain in [`CNAME`](CNAME).

## Contact

[GitHub @siddarthquantum](https://github.com/siddarthquantum) · siddarth12118@gmail.com
