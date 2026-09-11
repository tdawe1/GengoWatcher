#!/usr/bin/env bash
# translate-gengo.sh — fan-out Gengo-style translation to grok, opencode, codex, claude
# Usage: translate-gengo.sh [-o OUTDIR] [-t SECONDS] [--only a,b,c] [--skip-review] <file|text...> | <stdin>
# Never fails hard if a model is missing/unsubscribed — it records SKIP and continues.
set -u
set -o pipefail

OUTDIR="./gengo-output"
TIMEOUT=300
ONLY="grok,opencode,codex,claude"
SKIP_REVIEW=0
INPUT_ARGS=()

usage() {
  cat <<'USAGE'
Usage: translate-gengo.sh [OPTIONS] <input-file | text...> | <stdin>

  Translate a file (if path exists) or raw text via grok, opencode, codex, claude
  per Gengo Style Guide, then run a review pass, then collate.
  With no arguments and piped stdin, the piped text is translated.

Options:
  -o, --out-dir DIR     Output base dir (default: ./gengo-output)
  -t, --timeout SECS    Per-model per-phase timeout (default: 300)
  --only LIST           Comma list subset of grok,opencode,codex,claude
  --skip-review         Skip second (review) pass, keep translation only
  -h, --help            Show this help
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -o|--out-dir) OUTDIR="$2"; shift 2;;
    -t|--timeout) TIMEOUT="$2"; shift 2;;
    --only) ONLY="$2"; shift 2;;
    --skip-review) SKIP_REVIEW=1; shift;;
    -h|--help) usage; exit 0;;
    --) shift; while [[ $# -gt 0 ]]; do INPUT_ARGS+=("$1"); shift; done; break;;
    -*) echo "Unknown option: $1" >&2; usage >&2; exit 2;;
    *) INPUT_ARGS+=("$1"); shift;;
  esac
done

INPUT_STDIN=0
STDIN_TMP=""
if [[ ${#INPUT_ARGS[@]} -eq 0 ]]; then
  if [[ ! -t 0 ]]; then
    # Piped stdin (e.g. from bin/gengo, which keeps customer text out of
    # argv) counts as a single text input. Captured to a temp file so the
    # bytes survive verbatim: command substitution would strip trailing
    # newlines, and the text must bypass -f path detection below (piped
    # text matching an existing path, e.g. "README.md", is literal text).
    STDIN_TMP="$(mktemp)"
    trap 'rm -f "${STDIN_TMP:-}"' EXIT
    cat > "$STDIN_TMP"
    [[ -s "$STDIN_TMP" ]] || { echo "Empty stdin." >&2; exit 2; }
    INPUT_STDIN=1
  else
    usage >&2; exit 2
  fi
fi

# ---------- notifications ----------
notify() {
  local title="$1"; local body="${2:-}"; local urgency="${3:-normal}"
  echo "[notify] $title — $body"
  if command -v notify-send >/dev/null 2>&1; then
    notify-send -u "$urgency" "$title" "$body" 2>/dev/null || true
  fi
  printf '\a' || true
  if command -v paplay >/dev/null 2>&1; then
    for snd in /usr/share/sounds/freedesktop/stereo/complete.oga \
               /usr/share/sounds/freedesktop/stereo/message.oga; do
      if [[ -f "$snd" ]]; then paplay "$snd" 2>/dev/null || true; break; fi
    done
  fi
}

# ---------- input detection ----------
INPUT_MODE="text"
INPUT_DESC=""
ORIG_BASENAME="input.txt"
CONTENT_FILE=""
if [[ "$INPUT_STDIN" -eq 1 ]]; then
  INPUT_MODE="text"
  INPUT_DESC="text: <stdin>"
elif [[ ${#INPUT_ARGS[@]} -eq 1 && -f "${INPUT_ARGS[0]}" ]]; then
  INPUT_MODE="file"
  SRC_FILE="${INPUT_ARGS[0]}"
  ORIG_BASENAME="$(basename "$SRC_FILE")"
  INPUT_DESC="file: $SRC_FILE"
else
  INPUT_DESC="text: ${INPUT_ARGS[*]:0:80}"
fi

RUN_TS="$(date +%Y%m%d-%H%M%S)"
RUN_DIR="$OUTDIR/$RUN_TS-gengo"
PROMPT_DIR="$RUN_DIR/prompts"
mkdir -p "$RUN_DIR" "$PROMPT_DIR"

if [[ "$INPUT_MODE" == "file" ]]; then
  cp -- "$SRC_FILE" "$RUN_DIR/original.$ORIG_BASENAME" 2>/dev/null || cp -- "$SRC_FILE" "$RUN_DIR/original.txt"
  cp -- "$SRC_FILE" "$RUN_DIR/original.txt" 2>/dev/null || true
  CONTENT_FILE="$RUN_DIR/original.txt"
elif [[ "$INPUT_STDIN" -eq 1 ]]; then
  cp -- "$STDIN_TMP" "$RUN_DIR/original.txt"
  rm -f "$STDIN_TMP"
  CONTENT_FILE="$RUN_DIR/original.txt"
else
  printf "%s" "${INPUT_ARGS[*]}" > "$RUN_DIR/original.txt"
  CONTENT_FILE="$RUN_DIR/original.txt"
fi

SOURCE_CONTENT="$(cat "$CONTENT_FILE")"
if [[ "$INPUT_MODE" == "file" ]]; then
  KIND_PHRASE="the file below (return the completed translated file content, same formatting/line breaks/paragraphs as the original)"
else
  KIND_PHRASE="the text below (return the completed translation, same formatting/line breaks as the original)"
fi

# ---------- prompts ----------
cat > "$PROMPT_DIR/translate.instructions.txt" <<'INSTR'
You are a professional Japanese-to-English translator following the Gengo.com Style Guide (American English).
MUST follow:
- American spelling (Gengo default).
- Numbers 0-9 spelled out; larger than 9 numeric; comma as thousands separator (3,000); over one million shortened ($3.5 billion). If numbers both smaller and larger than 9 are in the SAME sentence, use numeric for all.
- Dates as Month Dayth, Year with ordinal suffix and comma after day (June 7th, 2010). Time 12-hour (3:00 p.m.).
- Oxford/serial comma (bananas, apples, and oranges).
- Headlines: capitalize only first letter, except proper nouns.
- Double quotation marks (" ") for quotes; single only for quotes-within-quotes. Periods/commas inside closing quotes; colons/semicolons outside.
- Avoid contractions in formal writing (cannot not can't; Street not St.; It is not it's).
- Avoid hyphenating nouns (eye shadow, breakdown); hyphen only to clarify meaning (man-eating shark).
- Triple brackets [[[example]]] are DO-NOT-TRANSLATE: copy EXACTLY including brackets, never translate inside, never drop brackets.
- Preserve structure: same paragraph breaks/line breaks as source. Do not turn a list into a paragraph or vice versa. Use appropriate English punctuation, do not copy Japanese punctuation blindly.
- En dash (-) for ranges (Ages 18-21), em dash (—) for abrupt break.
- Accurately reflect meaning and style (formal/informal) of source.
INSTR

{
  cat "$PROMPT_DIR/translate.instructions.txt"
  echo ""
  echo "Task: Translate $KIND_PHRASE to English per above. Return ONLY the translation, no explanations, no notes."
  echo "---SOURCE START---"
  cat "$CONTENT_FILE"
  echo ""
  echo "---SOURCE END---"
} > "$PROMPT_DIR/translate.prompt.txt"

build_review_prompt() {
  local translation_file="$1"; local out_prompt="$2"
  {
    echo "You are a professional editor. Review the translation for naturalness whilst still ensuring Gengo.com Style Guide compliance (American spelling, numbers 0-9 spelled out unless mixed with larger numbers in same sentence, dates Month Dayth, Year, Oxford comma, headline capitalize only first letter, double quotes with periods inside, no contractions in formal text, triple brackets [[[x]]] preserved exactly, paragraph/line breaks match original, en dash for ranges)."
    echo ""
    echo "Original source (Japanese):"
    echo "---SOURCE START---"
    cat "$CONTENT_FILE"
    echo ""
    echo "---SOURCE END---"
    echo ""
    echo "Current translation to review:"
    echo "---TRANSLATION START---"
    cat "$translation_file"
    echo ""
    echo "---TRANSLATION END---"
    echo ""
    echo "Task: Return ONLY the revised final translation (same formatting/line breaks as original), no explanations. If already perfect, return it unchanged."
  } > "$out_prompt"
}

# ---------- helpers ----------
is_auth_or_quota_failure() {
  local f="$1"
  grep -qiE "not logged in|not signed in|please run .*login|failed to authenticate|oauth .*expired|invalid.*api.?key|no api key|api key.*missing|payment required|status 402|usage balance exhausted|usage limit|upgrade to plus|quota|credit.*exhaust|subscription.*not active|no .*subscription|billing|unauthorized| 401 | 403 |forbidden|access denied|CMPUnknownError|error.*auth" "$f" 2>/dev/null
}

have_tool() { command -v "$1" >/dev/null 2>&1; }

# Each runner: args = prompt_file out_file err_file ; stdout -> out_file
run_grok() {
  local pf="$1" out="$2" err="$3"
  timeout "$TIMEOUT" grok --prompt-file "$pf" --output-format plain >"$out" 2>"$err"
  return $?
}
run_opencode() {
  local pf="$1" out="$2" err="$3"
  # Prompt via stdin (argv would strip trailing newlines, risk ARG_MAX,
  # and leak prompt in ps). Isolate cwd so the build agent cannot
  # read/edit the caller's repo; allow model pinning via OPENCODE_MODEL.
  # Deny-all tool policy: prompts embed customer-controlled source text,
  # so the model must not reach shell, files, web, or MCP tools.
  local workdir="$RUN_DIR/opencode-workdir"
  local denycfg="$workdir/opencode.json"
  mkdir -p "$workdir"
  if [[ ! -f "$denycfg" ]]; then
    cat > "$denycfg" <<'JSON'
{
  "$schema": "https://opencode.ai/config.json",
  "permission": {
    "*": "deny",
    "question": "deny",
    "doom_loop": "deny",
    "external_directory": "deny"
  }
}
JSON
  fi
  if [[ -n "${OPENCODE_MODEL:-}" ]]; then
    OPENCODE_CONFIG="$denycfg" timeout "$TIMEOUT" opencode run -m "$OPENCODE_MODEL" --dir "$workdir" <"$pf" >"$out" 2>"$err"
  else
    OPENCODE_CONFIG="$denycfg" timeout "$TIMEOUT" opencode run --dir "$workdir" <"$pf" >"$out" 2>"$err"
  fi
  return $?
}
run_codex() {
  local pf="$1" out="$2" err="$3"
  local lastmsg="${out}.lastmsg.txt"
  timeout "$TIMEOUT" codex exec --skip-git-repo-check --sandbox read-only --color never -o "$lastmsg" - <"$pf" >"$out" 2>"$err"
  local rc=$?
  # prefer clean last-message file if produced
  if [[ -s "$lastmsg" ]]; then
    cp -- "$lastmsg" "${out}.clean"
    # prepend log for debugging but keep clean copy authoritative
  fi
  return $rc
}
run_claude() {
  local pf="$1" out="$2" err="$3"
  local rc
  timeout "$TIMEOUT" claude -p "$(cat "$pf")" --output-format text --max-turns 10 >"$out" 2>"$err"
  rc=$?
  return $rc
}

run_one_model() {
  local model="$1" runner="$2"
  local t_out="$RUN_DIR/${model}.translation.txt"
  local t_err="$RUN_DIR/${model}.translation.err.log"
  local r_out="$RUN_DIR/${model}.review.txt"
  local r_err="$RUN_DIR/${model}.review.err.log"
  local final="$RUN_DIR/${model}.final.txt"
  local status="$RUN_DIR/${model}.status"
  local rc

  echo "=== [$model] translate phase ==="
  if ! have_tool "$model" && [[ "$model" != "codex" || true ]]; then
    # claude binary is `claude`, codex `codex`, grok `grok`, opencode `opencode`
    : # fallthrough to actual check below (binary name == model for all four)
  fi
  if ! have_tool "$model"; then
    echo "SKIPPED: '$model' not installed (no binary on PATH)" | tee "$t_out" > "$status"
    echo "SKIPPED not-installed" > "$final"
    printf "SKIPPED (not installed)\n" >> "$status"
    notify "[$model] skipped" "not installed" low
    return 0
  fi

  set +e
  "$runner" "$PROMPT_DIR/translate.prompt.txt" "$t_out" "$t_err"
  rc=$?
  set +e

  # timeout?
  if [[ $rc -eq 124 ]]; then
    echo "SKIPPED/TIMEOUT after ${TIMEOUT}s in translate phase (see ${model}.translation.err.log)" > "$status"
    echo "TIMEOUT after ${TIMEOUT}s" > "$t_out.tmp" && cat "$t_out" >> "$t_out.tmp" 2>/dev/null; mv "$t_out.tmp" "$t_out" 2>/dev/null || true
    cp -- "$t_out" "$final" 2>/dev/null || true
    notify "[$model] timeout" "translate phase hit ${TIMEOUT}s" critical
    return 0
  fi

  # auth/quota/subscription failure? stderr is authoritative: translated
  # stdout may itself mention words like "quota" or "billing". Stdout is
  # only consulted when the phase exited non-zero (no usable translation).
  cat "$t_err" > "$RUN_DIR/.${model}.combined.tmp" 2>/dev/null || true
  if [[ $rc -ne 0 ]]; then
    cat "$t_out" >> "$RUN_DIR/.${model}.combined.tmp" 2>/dev/null || true
  fi
  if is_auth_or_quota_failure "$RUN_DIR/.${model}.combined.tmp"; then
    {
      echo "SKIPPED (no active subscription / auth / quota)."
      echo "Exit code: $rc"
      echo "--- captured output (truncated) ---"
      head -c 2000 "$RUN_DIR/.${model}.combined.tmp"
    } > "$status"
    # keep raw output for inspection but mark final as skipped
    cp -- "$t_out" "$RUN_DIR/${model}.translation.raw.txt" 2>/dev/null || true
    {
      echo "SKIPPED: $model has no active subscription, is not authenticated, or quota exhausted."
      echo "See $model.status and $model.translation.err.log for details."
    } > "$final"
    notify "[$model] skipped" "no sub / auth / quota" low
    rm -f "$RUN_DIR/.${model}.combined.tmp"
    return 0
  fi
  rm -f "$RUN_DIR/.${model}.combined.tmp"

  # codex: prefer clean last-message file
  if [[ "$model" == "codex" && -s "${t_out}.lastmsg.txt" ]]; then
    cp -- "${t_out}.lastmsg.txt" "$t_out.clean" 2>/dev/null || true
    # if stdout was mostly logs, replace translation with clean message
    if [[ "$(wc -c < "$t_out.clean" 2>/dev/null || echo 0)" -gt 10 ]]; then
      cp -- "$t_out.clean" "$t_out"
    fi
  fi

  if [[ ! -s "$t_out" ]]; then
    echo "FAILED translate phase: empty output (exit $rc). See err log." > "$status"
    echo "[no output; exit $rc]" > "$final"
    notify "[$model] failed" "empty output" critical
    return 0
  fi
  echo "OK translate (exit $rc, $(wc -c <"$t_out") bytes)" > "$status"
  notify "[$model] translated" "$(wc -c <"$t_out") bytes" normal

  if [[ "$SKIP_REVIEW" -eq 1 ]]; then
    cp -- "$t_out" "$final"
    cp -- "$t_out" "$r_out"
    echo "review skipped by flag" >> "$status"
    return 0
  fi

  # ---- review phase ----
  echo "=== [$model] review phase ==="
  build_review_prompt "$t_out" "$PROMPT_DIR/review.${model}.prompt.txt"
  set +e
  "$runner" "$PROMPT_DIR/review.${model}.prompt.txt" "$r_out" "$r_err"
  rc=$?
  set +e
  if [[ $rc -eq 124 ]]; then
    echo "review TIMEOUT after ${TIMEOUT}s; falling back to translation as final" >> "$status"
    cp -- "$t_out" "$final"
    notify "[$model] review timeout" "kept translation as final" critical
    return 0
  fi
  cat "$r_err" > "$RUN_DIR/.${model}.combined2.tmp" 2>/dev/null || true
  if [[ $rc -ne 0 ]]; then
    cat "$r_out" >> "$RUN_DIR/.${model}.combined2.tmp" 2>/dev/null || true
  fi
  if is_auth_or_quota_failure "$RUN_DIR/.${model}.combined2.tmp"; then
    echo "review SKIPPED (auth/quota mid-run); falling back to translation as final" >> "$status"
    cp -- "$t_out" "$final"
    notify "[$model] review skipped" "auth/quota, kept translation" low
    rm -f "$RUN_DIR/.${model}.combined2.tmp"
    return 0
  fi
  rm -f "$RUN_DIR/.${model}.combined2.tmp"

  if [[ "$model" == "codex" && -s "${r_out}.lastmsg.txt" ]]; then
    cp -- "${r_out}.lastmsg.txt" "$r_out.clean" 2>/dev/null || true
    if [[ "$(wc -c < "$r_out.clean" 2>/dev/null || echo 0)" -gt 10 ]]; then
      cp -- "$r_out.clean" "$r_out"
    fi
  fi

  if [[ -s "$r_out" ]]; then
    cp -- "$r_out" "$final"
    echo "OK review (exit $rc)" >> "$status"
    notify "[$model] reviewed" "final ready" normal
  else
    cp -- "$t_out" "$final"
    echo "review empty; kept translation as final" >> "$status"
    notify "[$model] review empty" "kept translation" critical
  fi
  return 0
}

# ---------- main fan-out ----------
notify "Gengo translate started" "$INPUT_DESC → $RUN_DIR" normal

IFS=',' read -ra WANT <<< "$ONLY"
for m in "${WANT[@]}"; do
  m="$(echo "$m" | xargs)" # trim
  case "$m" in
    grok) run_one_model "grok" run_grok;;
    opencode) run_one_model "opencode" run_opencode;;
    codex) run_one_model "codex" run_codex;;
    claude) run_one_model "claude" run_claude;;
    *) echo "Unknown model in --only: $m" >&2;;
  esac
done

# ---------- collate ----------
COMBINED="$RUN_DIR/COMBINED.md"
{
  echo "# Gengo translation comparison"
  echo ""
  echo "- Input: $INPUT_DESC"
  echo "- Mode: $INPUT_MODE"
  echo "- Date (UTC): $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "- Run dir: $RUN_DIR"
  echo ""
  echo "## Original"
  echo '```'
  cat "$CONTENT_FILE"
  echo '```'
  echo ""
  for m in grok opencode codex claude; do
    echo "---"
    echo ""
    echo "## $m"
    echo ""
    if [[ -f "$RUN_DIR/${m}.status" ]]; then
      echo "**Status:** $(cat "$RUN_DIR/${m}.status" | head -n 3 | tr '\n' ' ')"
      echo ""
    fi
    echo "### Translation (phase 1)"
    echo '```'
    cat "$RUN_DIR/${m}.translation.txt" 2>/dev/null || echo "(no file — model not in --only or not run)"
    echo '```'
    echo ""
    if [[ "$SKIP_REVIEW" -eq 0 ]]; then
      echo "### Reviewed final (phase 2)"
      echo '```'
      cat "$RUN_DIR/${m}.final.txt" 2>/dev/null || echo "(no final)"
      echo '```'
      echo ""
    fi
  done
  echo "---"
  echo "_Per-file outputs in $RUN_DIR : *.translation.txt, *.review.txt, *.final.txt, *.status_"
} > "$COMBINED"

# summary
{
  echo "run_dir=$RUN_DIR"
  echo "input_mode=$INPUT_MODE"
  for m in grok opencode codex claude; do
    if [[ -f "$RUN_DIR/${m}.status" ]]; then
      echo "$m: $(head -n 1 "$RUN_DIR/${m}.status")"
    else
      echo "$m: not run"
    fi
  done
} | tee "$RUN_DIR/summary.txt"

notify "Gengo translate done" "Collated: $COMBINED" critical
echo ""
echo "Done. Outputs in: $RUN_DIR"
echo "Collated file: $COMBINED"
ls -lh "$RUN_DIR"
