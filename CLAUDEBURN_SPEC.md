# ClaudeBurn — Implementation Spec

## What this is

A native macOS menu bar app that tracks Claude usage across all local surfaces (Claude Code CLI, VSCode, Claude Desktop), calculates burn rate over time, and recommends model switching to optimise 5-hour session and 7-day weekly limits.

---

## Approaches Considered and Red-Teamed

### 1. Token-based tracking (REJECTED)

**Approach**: Parse JSONL logs for exact token counts per message, map tokens to quota consumption.

**Why rejected**:
- JSONL output token counts are broken — streaming writes partial `usage` objects. Showed 8 tokens/message average when real responses are 1000+. Same bug as ccusage issue #705.
- Subagent/Task tokens are invisible in JSONL — ccusage issue #313. When Claude Code spawns subagents, their usage doesn't appear in logs.
- Quota formula is a black box — Anthropic doesn't document how tokens map to quota%. Different models, token types (input/output/cache), and operations are weighted differently. Unknown weights = can't convert.
- Would produce false confidence — users of ccusage and Claude-Code-Usage-Monitor report being told they have 74% remaining when actually at 100%. Same outcome here.

### 2. Existing tools (REJECTED)

**Why rejected after exhaustive review of 14+ tools**:
- **ccusage** (10.8K stars): Output tokens undercounted by 99%+. Subagents invisible. Can spawn infinite processes (300% CPU, 3GB RAM). No optimisation advice.
- **Claude-Code-Usage-Monitor** (6.6K stars): Shows credits remaining when limit is hit. HN criticism: "vibe-coded." No optimisation advice.
- **Usage4Claude** (181 stars): Requires full session key (account-level access). Spoofs Chrome headers to bypass Cloudflare. Not Apple notarised. Auth breaks every few versions. Zero Reddit/HN/Twitter presence. No optimisation advice.
- **ccburn** (13 stars): npm postinstall downloads unsigned binary without checksum verification. No optimisation advice. Was installed and removed during evaluation.
- **No tool provides optimisation recommendations.** All are display-only.

### 3. Time-based burn rate (AGREED APPROACH)

**Approach**: Correlate active usage time (from reliable timestamps) with quota% changes (from OAuth API). Derive burn rate per hour. Project forward.

**Why this works**:
- Timestamps are 100% reliable — no undercounting, no subagent blindness.
- Message rate is stable: ~240-280 msg/h regardless of model (validated across 34 sessions, 13 days of data).
- Self-correcting: if Anthropic changes quota formula, observed burn rate automatically recalibrates within a few data points. No model of internals to break.
- Validated on user's actual data: 48.6h active Code time this week, 79% quota used = ~1.5% per active Opus hour. Projections are actionable.

**What survives red-team**:
- Time != burn (variance exists). Mitigation: show ranges, not point estimates.
- Model switching changes rate. Mitigation: track separate burn rates per model.
- Rolling 5h window means old usage ages out. Mitigation: model the decay, don't extrapolate linearly.
- Sonnet cost multiplier is estimated (~5x cheaper). Mitigation: the model learns the actual ratio from observed data over time.

### 4. Python (rumps) vs Swift (SWIFT CHOSEN)

**Why Swift**:
- Native macOS integration (Keychain, FileManager, notifications, proper app signing).
- Clean distribution as .app — no PyInstaller SSL cert issues, no unsigned binaries.
- Xcode 26.3 has Claude Agent SDK built in — can build the entire app using Claude in Xcode.
- User's Python work is concentrated in the Research Workbench; this is a separate tool that benefits from being native.
- Long-term: Swift/SwiftUI is Apple's own stack, stable across macOS updates.

---

## Agreed Architecture

### Data Sources

| Source | Location | What it provides | How to read |
|--------|----------|-----------------|-------------|
| Claude Code JSONL | `~/.claude/projects/*/*.jsonl` | Timestamps, model per message, session IDs | FileManager + JSONSerialization, watch with DispatchSource |
| Claude Desktop agent sessions | `~/Library/Application Support/Claude/local-agent-mode-sessions/**/*.json` | Session model, timestamps (created/lastActive) | FileManager + JSONSerialization |
| Claude Desktop logs | `~/Library/Logs/Claude/claude.ai-web.log` | `rate_limit_event` timestamps | String scanning (optional, lower priority) |
| OAuth usage API | `https://api.anthropic.com/api/oauth/usage` | Session %, weekly %, reset timers, Opus/Sonnet split | URLSession, OAuth token from Keychain |
| Claude Code stats cache | `~/.claude/stats-cache.json` | Daily message counts, session counts | FileManager + JSONSerialization |

### Data NOT available (known gaps)

- Claude Desktop chat token counts — not logged locally. Inferred by: `desktop_burn = total_quota_delta - code_burn_delta`
- Per-surface quota breakdown — Anthropic's API returns one shared pool number.
- Exact Sonnet-to-Opus cost ratio — learned empirically over time.

### Core Algorithm

```
1. On launch + every 60 seconds:
   a. Poll OAuth API for current session% and weekly%
   b. Scan JSONL directories for new messages since last check
   c. Calculate active_hours since last snapshot (15min idle threshold)
   d. Store snapshot: (timestamp, session%, weekly%, active_hours, primary_model)

2. Burn rate calculation:
   burn_rate_per_hour = delta(quota%) / delta(active_hours)
   - Maintain separate rates for Opus-heavy vs Sonnet-heavy sessions
   - Use exponential moving average (recent sessions weighted higher)

3. Projection:
   hours_remaining = remaining_quota% / current_burn_rate
   - Show as range: optimistic (Sonnet rate) to pessimistic (Opus rate)
   - Compare against time_until_reset to determine if pacing is safe

4. Recommendation engine (deterministic rules, no LLM):
   if weekly% > (elapsed_fraction * 100) + 15:
       -> "Over-burning. Switch to Sonnet for routine work."
   if weekly% < (elapsed_fraction * 100) - 15:
       -> "Under-burning. Opus is fine."
   if session% > 80% and session_reset > 1h:
       -> "Session hot. Defer heavy work or switch to Sonnet."
   if weekly% > 90%:
       -> "Critical. Sonnet only until weekly reset."
   if day_of_week in user's_heavy_days and weekly% > 60%:
       -> "Your heaviest days are coming. Conserve now."

5. Model switching (user-triggered, never automatic):
   - User taps "Switch to Sonnet" or "Switch to Opus"
   - App writes to BOTH files atomically:
     a. ~/.claude/settings.json -> update "model" field
     b. ~/Library/Application Support/Code/User/settings.json -> update "claudeCode.selectedModel"
   - Confirm write succeeded
   - Note: affects new sessions only, not currently running ones
```

### File Write Safety

When writing settings files:
1. Read current file content
2. Parse as JSON, validate structure
3. Update only the model field, preserve everything else
4. Write to temp file in same directory
5. Atomic rename (temp -> target)
6. Keep one backup (.bak) of previous version
7. If any step fails, abort and notify user

### Files the app writes to

| File | Key | Values |
|------|-----|--------|
| `~/.claude/settings.json` | `"model"` | `"claude-sonnet-4-6"`, `"claude-opus-4-6"`, `"claude-haiku-4-5-20251001"` |
| `~/Library/Application Support/Code/User/settings.json` | `"claudeCode.selectedModel"` | Same values |

### Files the app reads (read-only)

| File/Directory | Purpose |
|----------------|---------|
| `~/.claude/projects/*/*.jsonl` | Claude Code message timestamps + models |
| `~/.claude/stats-cache.json` | Daily activity summaries |
| `~/Library/Application Support/Claude/local-agent-mode-sessions/**/*.json` | Desktop agent session metadata |
| `~/Library/Logs/Claude/*.log` | Desktop log timestamps (optional) |
| OAuth token from macOS Keychain (`Claude Code-credentials`) | API authentication |

---

## UI Spec

### Menu bar icon

- Shows current weekly% as text: `72%`
- Color coding: green (<60%), amber (60-85%), red (>85%)
- Updates every 60 seconds

### Menu dropdown (click the icon)

```
------------------------------------
 Weekly: 72% used | Resets Wed 9AM
 Session: 45% used | Resets in 3h 12m
------------------------------------
 Burn rate: 1.5%/h (Opus)
 Remaining: ~19h Opus / ~93h Sonnet
------------------------------------
 RECOMMENDATION:
 Over pace. Switch to Sonnet for
 routine work to cover remaining
 4.2 days.
------------------------------------
 [ Switch to Sonnet ]  [ Opus ]
------------------------------------
 Today: 3.2h active
 This week: 28.4h active
------------------------------------
 Pattern: Fri+Sat are your heaviest
 days (avg 11.6h combined)
------------------------------------
 Quit ClaudeBurn
------------------------------------
```

### Interaction model

- Click menu bar icon -> dropdown appears
- "Switch to Sonnet" / "Switch to Opus" buttons write to both settings files
- After switching, dropdown shows confirmation: "Switched to Sonnet. New sessions will use Sonnet."
- No auto-switching. Ever. The app recommends, the user decides.

---

## Project Structure

```
ClaudeBurn/
├── ClaudeBurn.xcodeproj/
├── ClaudeBurn/
│   ├── ClaudeBurnApp.swift          -- @main, MenuBarExtra setup
│   ├── Views/
│   │   ├── MenuBarView.swift        -- Dropdown UI
│   │   └── StatusItemView.swift     -- Menu bar icon/text
│   ├── Models/
│   │   ├── UsageSnapshot.swift      -- Data model for snapshots
│   │   ├── BurnRate.swift           -- Burn rate calculation
│   │   └── Recommendation.swift     -- Rule engine output
│   ├── Services/
│   │   ├── JSONLWatcher.swift       -- File watcher for JSONL dirs
│   │   ├── OAuthPoller.swift        -- OAuth API polling
│   │   ├── SettingsWriter.swift     -- Atomic JSON writes
│   │   ├── HistoryStore.swift       -- SQLite for historical snapshots
│   │   └── KeychainReader.swift     -- Read OAuth token
│   └── Utilities/
│       ├── TimeCalculator.swift     -- Active time from timestamps
│       └── Constants.swift          -- Idle threshold, API URLs, etc.
├── ClaudeBurnTests/
│   ├── BurnRateTests.swift
│   ├── RecommendationTests.swift
│   ├── TimeCalculatorTests.swift
│   └── SettingsWriterTests.swift
└── README.md
```

~12 Swift source files + 4 test files.

---

## Xcode Project Configuration

- **App Sandbox**: OFF (needs access to ~/.claude/, ~/Library/)
- **Info.plist**: `Application is agent (UIElement) = YES` (menu bar only, no dock icon)
- **Signing**: Self-signed for personal use (no Apple Developer Program needed)
- **Minimum deployment**: macOS 14+ (for MenuBarExtra SwiftUI API)
- **Frameworks**: Foundation, SwiftUI, Security (Keychain), SQLite3

---

## Build Phases

### Phase 1: Core data pipeline (Session 1)
- KeychainReader: read OAuth token
- OAuthPoller: fetch session% and weekly% every 60s
- MenuBarExtra showing live quota%
- Result: working menu bar widget showing real quota numbers

### Phase 2: JSONL parsing + burn rate (Session 2)
- JSONLWatcher: scan ~/.claude/projects/ for timestamps + models
- TimeCalculator: compute active hours (15min idle threshold)
- BurnRate: calculate %/hour from OAuth snapshots + active time
- HistoryStore: SQLite for snapshot persistence
- Result: burn rate and projections displayed in dropdown

### Phase 3: Recommendations + model switching (Session 3)
- Recommendation engine: deterministic rules
- SettingsWriter: atomic writes to both JSON files
- Switch buttons in UI
- Weekly pattern analysis (day-of-week burn profiles)
- Result: full working app

### Phase 4: Polish (Session 4, optional)
- Desktop agent session parsing (bonus data source)
- Historical trend view (optional)
- Launch-at-login toggle
- Sparkle or manual update mechanism

---

## Key Decisions

1. **No LLM calls from the app** — all logic is deterministic math. Zero ongoing Claude usage cost.
2. **No auto-switching** — app recommends, user decides. Prevents quality degradation from surprise model changes.
3. **Two-file atomic write** — settings.json + VSCode settings updated together for true global model control.
4. **Time-based, not token-based** — immune to JSONL accuracy issues and Anthropic formula changes.
5. **Empirical burn rates** — self-calibrating from observed data, no hardcoded assumptions about token costs.
6. **60-second poll interval** — balances freshness vs. API load. OAuth endpoint is lightweight.
7. **SQLite for history** — enables week-over-week pattern comparison without complexity.
8. **macOS 14+ minimum** — enables MenuBarExtra (SwiftUI native menu bar API). Reasonable for a developer tool.

---

## User's Current Baseline Data (from analysis session)

For calibrating initial estimates:

- **Burn rate (all-Opus)**: ~1.5% weekly quota per active hour
- **Message rate**: ~240-280 msg/h (stable across models)
- **Active hours/day average**: 5.3h
- **Weekly pattern**: Mon 2.7h, Tue 6.3h, Wed 7.1h, Thu 6.1h, Fri 14.3h, Sat 9.0h, Sun 0.2h
- **Model mix this week**: 99%+ Opus
- **Subscription**: Max 20x plan (default = Opus)
- **Weekly reset**: Wednesday 9 AM
- **Total Claude Code data**: 248 JSONL files, 19,104 assistant messages, 13 days

---

## OAuth API Details

**Endpoint**: `https://api.anthropic.com/api/oauth/usage`

**Auth**: Bearer token from macOS Keychain (`Claude Code-credentials` service name)

**Response** (expected fields based on existing tools):
- Session utilization %
- Weekly utilization %
- Session reset timestamp
- Weekly reset timestamp
- Opus vs Sonnet breakdown

**Keychain access** (Swift):
```swift
let query: [String: Any] = [
    kSecClass as String: kSecClassGenericPassword,
    kSecAttrService as String: "Claude Code-credentials",
    kSecReturnData as String: true,
    kSecMatchLimit as String: kSecMatchLimitOne
]
var item: CFTypeRef?
SecItemCopyMatching(query as CFDictionary, &item)
```

---

## Risk Register

| Risk | Mitigation |
|------|-----------|
| OAuth API changes/breaks | Graceful degradation — show JSONL-only data, hide quota% |
| Keychain access denied | Clear error message, link to System Settings > Privacy |
| settings.json corruption | Atomic writes + .bak backup + JSON validation before write |
| Race condition with Claude Code writing settings.json | Read-modify-write with file coordination (NSFileCoordinator) |
| Inaccurate burn rate early on (few data points) | Show "calibrating..." for first 2 hours, use wider ranges |
| Anthropic changes quota formula | Self-correcting — burn rate recalibrates from new observations |
| User runs heavy subagent task, burn spikes | Show "rate spiking" alert when burn rate > 2x average |
