# AI Optimization and Model-Safety Guide

This guide documents ReceiptAI's token, image, context, and model-routing
controls. The default rollout preserves the existing production model IDs and
answer behavior.

## Production defaults

| Workload | Default model | Behavior in this release |
| --- | --- | --- |
| Receipt vision scan | `claude-sonnet-4-5-20250929` | Unchanged |
| Agent planner | `claude-haiku-4-5-20251001` | Unchanged |
| Normal Agent synthesis | `claude-sonnet-4-5-20250929` | Unchanged |
| Complex tool-driven Agent fallback | `claude-opus-4-5-20251101` | Unchanged |

The optimization release does not silently move production traffic to a newer
model. New models must pass the receipt and Agent regression datasets before
an environment variable is changed.

## Enabled safe optimizations

### Exact vision-token budgeting

Claude counts one visual token for each 28x28 image patch after native resizing.
ReceiptAI now uses that patch calculation rather than the previous approximate
pixel formula.

`MAX_SCAN_IMAGE_TOKENS=1568` is an application-level ceiling. It remains in
force even when a future high-resolution model supports a larger visual budget.
This prevents a model upgrade from unexpectedly increasing image usage from
the standard tier to the high-resolution tier.

Receipt photos are still:

1. EXIF-corrected.
2. Auto-cropped to the paper region when confidence is sufficient.
3. Resized within both the edge and visual-token budgets.
4. JPEG encoded for lower transfer size.

JPEG quality primarily affects bytes. Cropping and dimensions are the controls
that reduce visual tokens.

### Prompt caching

`CLAUDE_PROMPT_CACHING_ENABLED=true` marks only stable content:

- the receipt extraction contract, before customer-specific image blocks;
- the Agent system contract and tool definitions;
- the general-advice system contract.

Caching does not change the selected model or reasoning instructions. Cache
reads, cache writes, normal input, and output tokens are recorded separately.

### Agent context budget

The tool-driven fallback retains the newest conversation turns within:

```env
AGENT_HISTORY_MAX_MESSAGES=10
AGENT_HISTORY_MAX_CHARS=16000
AGENT_HISTORY_MESSAGE_MAX_CHARS=4000
```

These defaults retain the previous ten-turn behavior while preventing one
abnormally large message from dominating every later request.

## Guarded optimizations

These features are implemented but disabled by default because they can affect
model output. Enable them only in a staging environment first.

The ready-to-copy staging profile is `backend/staging.env.example`. All four
optimization controls are enabled there. Staging is validated with the same
fail-closed secret, HTTPS, and CORS rules as production.

Run the profile gate and then the live synthetic-receipt evaluation:

```powershell
cd backend
Get-Content staging.env.example | ForEach-Object {
  if ($_ -match '^([^#][^=]+)=(.*)$') {
    [Environment]::SetEnvironmentVariable($matches[1], $matches[2], 'Process')
  }
}
python evaluate_ai_staging.py --offline
python evaluate_ai_staging.py
```

Replace all `your_*` values in the Railway staging environment before the live
run. The live evaluator uses a generated receipt containing no customer data.
It verifies extraction, total accuracy, confidence, cascade activation, and
token accounting. A failure blocks production promotion.

### Structured receipt output

```env
CLAUDE_STRUCTURED_OUTPUTS_ENABLED=false
```

When enabled, receipt extraction uses a JSON schema. This reduces malformed
JSON and type errors, but constrained decoding can change how a model handles
unusual receipts. Test photographed, damaged, multi-page, invoice, and vendor
price-list fixtures before production rollout.

### Strict Agent tools

```env
CLAUDE_STRICT_TOOLS_ENABLED=false
```

When enabled, Agent tool arguments must match their schemas. This can eliminate
bad tool inputs, but a schema that is too narrow can reject a previously
accepted request.

### Haiku-first scan cascade

```env
CLAUDE_SCAN_CASCADE_ENABLED=false
CLAUDE_SCAN_FAST_MODEL=claude-haiku-4-5-20251001
CLAUDE_SCAN_CASCADE_MIN_CONFIDENCE=0.82
```

When enabled:

1. The fast model scans first.
2. A model error or confidence below the threshold triggers the existing
   `CLAUDE_SCAN_MODEL`.
3. Token usage from both attempts is recorded.

This can reduce cost for clean receipts but can increase total usage when many
receipts require fallback. Enable it only after measuring the fast-model pass
rate and field accuracy.

## Model upgrade policy

Never change a production model because it is merely newer. Compare candidates
using the same frozen dataset and the actual token-counting endpoint.

Required receipt metrics:

- document acceptance/rejection accuracy;
- item row recall and price accuracy;
- totals, dates, stores, identifiers, discounts, and quantity semantics;
- visual input tokens, output tokens, latency, and fallback rate.

Required Agent metrics:

- intent accuracy;
- evidence precision and purchase-occasion counts;
- unsupported-claim rate;
- answer usefulness;
- input/output/cache tokens and latency.

A candidate should deploy only when it meets the existing quality floor and
improves the intended cost or latency target.

## Product images

Generated product images are intentionally not part of the receipt evidence
path. A synthetic package can look convincing while being the wrong brand,
size, or product.

For item thumbnails, prefer:

```text
barcode / normalized item
  -> licensed product catalog or retailer source
  -> verify brand and size
  -> cache the source URL and thumbnail
  -> category icon when no reliable match exists
```

This requires a catalog provider and licensing decision. Until that is selected,
ReceiptAI should not generate a new image whenever a user opens an item.

## Background batch processing

Batch APIs are appropriate for asynchronous reprocessing, evaluation, and
backfills. They are not used for live scans or chat because users need an
immediate response. Add a batch job only when there is a concrete offline
workload and an idempotent result-import path.

## Verification

Run the optimization tests:

```powershell
cd backend
python -m pytest test_ai_optimization.py test_receipt_autocrop.py -q
```

Run the production regression suite:

```powershell
python -m pytest -q --ignore=test_claude.py --ignore=test_websearch.py
python verify_release.py --offline
```

`test_claude.py` and `test_websearch.py` are live-provider scripts and are
excluded from offline CI.
