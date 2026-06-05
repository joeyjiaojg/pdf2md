# pdf2md — AGENTS.md

Convert PDF to Markdown using [MinerU](https://github.com/opendatalab/MinerU), with optional LLM post-processing.

## Project State

- **Zero code yet** — only test PDF `000537_2026_年报.pdf` in workspace root
- **No `pyproject.toml`**, **no git repo** — project not initialized
- Python 3.11.2 available via `/home/joeyjiaojg/venv/bin/python3`; `uv` available at `/home/joeyjiaojg/.local/bin/uv`

## Architecture Target

- **CLI entrypoint**: `pdf2md` command (installed via `pip install -e .` or `uv pip install -e .`)
- **Core parsing**: MinerU (`magic-pdf`, or `mineru` CLI for v3.x+)
- **LLM integration**: invoke LLM at configurable stages (pre-processing PDF, post-processing markdown, table repair, formula cleanup). Use opencode cloud model (`deepseek-v4-flash-free`) or local models (ollama, llamacpp).
- **Output**: Markdown files with formatting preserved (tables → HTML, formulas → LaTeX)

## MinerU Key Facts

| Aspect | Detail |
|--------|--------|
| Package | `pip install "mineru[core]"` (v3.x+) or `magic-pdf` (v1.x legacy) |
| Python | 3.10–3.13 required |
| RAM | 16GB minimum (32GB+ recommended) |
| GPU | Required for hybrid/vlm backends (10GB+ VRAM); CPU-only works for `pipeline` backend |
| Backends | `pipeline` (CPU-compatible, accuracy 82+), `hybrid-auto-engine` (default v3.x, accuracy 90+), `vlm-auto-engine` |
| CLI (v3.x) | `mineru -p <input> -o <output> -b hybrid-auto-engine` |
| CLI (v1.x) | `magic-pdf -p <input> -o <output> -m auto` |
| Models | Auto-downloaded on first run; source configurable via `MINERU_MODEL_SOURCE=modelscope\|huggingface\|local` |
| Config | `~/.mineru/mineru.json` (auto-generated) — supports `llm-aided-config` for title hierarchy |
| License | AGPL-3.0 |

## Setup

```bash
# Create venv with Python 3.10-3.13
uv venv --python 3.11 .venv && source .venv/bin/activate

# Install MinerU with core + optional VLM acceleration
uv pip install "mineru[core]"

# Or minimal install (lightweight client mode)
uv pip install mineru
```

## Test PDF

`000537_2026_年报.pdf` — Chinese annual report, 2.2MB. Good test case for:
- Chinese text recognition
- Table extraction (financial tables)
- Multi-column layout handling
- Formula/inline formatting

## CLI Tool Expectations

1. **Accept input**: file path or directory (glob patterns)
2. **Select backend**: default `hybrid-auto-engine`, fallback to `pipeline` on CPU-only
3. **LLM hooks**: pluggable callbacks at stages like post-table, post-formula, or full markdown polish
4. **Output**: `{input_name}.md` in specified output dir
5. **Batch mode**: process multiple PDFs with parallel workers
6. **Config**: TOML or JSON config for LLM endpoints, backends, per-stage toggles

## LLM Integration

- **OpenCode cloud model**: default, requires `OPENCODE_API_KEY`
- **Local ollama**: auto-detected at `http://localhost:11434`
- **Local llamacpp**: auto-detected at `http://localhost:8081`
- Call LLM for: OCR error correction, table normalization, formula LaTeX cleanup, heading hierarchy improvement
- Do NOT call LLM for pure text extraction — MinerU handles that natively

## Common Pitfalls

1. **Python version**: must be 3.10–3.13. The repo's system Python is 3.11.2 — correct.
2. **GPU memory**: hybrid backend needs ~10GB VRAM. On CPU-only systems, use `pipeline` backend.
3. **First run**: models auto-download (~10GB for hybrid). Use `MINERU_MODEL_SOURCE=modelscope` in China for faster downloads.
4. **Config file**: `mineru.json` is auto-generated at `~/.mineru/mineru.json` on first `mineru` command. Edit this to enable LLM-aided parsing.
5. **Memory for long PDFs**: MinerU v3.x uses sliding windows + streaming writes to disk — handles long docs without OOM.
6. **Table output**: tables are rendered as HTML in Markdown, not native Markdown tables.
7. **License notice**: MinerU is AGPL-3.0. If distributing the CLI, the entire project must be AGPL-3.0.
8. **No git repo yet**: `git init` and first commit before significant work.
