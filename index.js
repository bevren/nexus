const { createRequire } = require('node:module');
require = createRequire(__filename); 

const readline = require("readline");
const fs = require("fs/promises");
const fsSync = require("fs");
const path = require("path");
const os = require("os");
const { execFile } = require("child_process");
const { randomUUID } = require("crypto");

let OpenAI = null;
try {
  const openaiModule = require("openai");
  OpenAI = openaiModule.default || openaiModule;
} catch {
  OpenAI = null;
}

const PROMPT_PREFIX = "› ";
const CONTINUATION_PREFIX = "  ";
const PLACEHOLDER = "Explain this codebase";
const PLACEHOLDER_COLOR = "\u001b[90m";
const RESET_COLOR = "\u001b[0m";
const BLUE_COLOR = "\u001b[94m";
const TOKEN_COLOR = "\u001b[94m";
const GREEN_COLOR = "\u001b[92m";
const RED_COLOR = "\u001b[91m";
const CODE_BLOCK_BG_COLOR = "\u001b[48;5;236m";
const CODE_BLOCK_FG_COLOR = "\u001b[38;5;252m";
const CODE_BLOCK_KEYWORD_COLOR = "\u001b[38;5;81m";
const CODE_BLOCK_STRING_COLOR = "\u001b[38;5;151m";
const CODE_BLOCK_NUMBER_COLOR = "\u001b[38;5;222m";
const CODE_BLOCK_COMMENT_COLOR = "\u001b[38;5;244m";
const CODE_BLOCK_BUILTIN_COLOR = "\u001b[38;5;117m";
const DIFF_ADD_BG_COLOR = "\u001b[48;5;22m\u001b[38;5;231m";
const DIFF_REMOVE_BG_COLOR = "\u001b[48;5;52m\u001b[38;5;231m";
const MARKDOWN_HEADER_COLOR = "\u001b[96m";
const MARKDOWN_LIST_MARKER_COLOR = "\u001b[96m";
const MARKDOWN_QUOTE_COLOR = "\u001b[90m";
const MARKDOWN_BOLD_COLOR = "\u001b[97m";
const MARKDOWN_LINK_TEXT_COLOR = "\u001b[94m";
const MARKDOWN_LINK_URL_COLOR = "\u001b[90m";
const MARKDOWN_INLINE_CODE_FG = "\u001b[38;5;222m";
const BOTTOM_PADDING = 0;
const INPUT_BOTTOM_PADDING_NO_MENU = 1;
const CHAT_INPUT_GAP = 0;
const CHAT_INPUT_GAP_NO_STATUS = 2;
const MESSAGE_SPACING_ROWS = 2;
const STATUS_BAR_ROWS = 1;
const STATUS_CHAT_GAP = 1;
const STATUS_INPUT_GAP = 2;
const MENU_INPUT_GAP = 1;
const MAIN_FOOTER_GAP = 1;
const CHAT_LEFT_PADDING = "";
const COMMAND_MENU_MAX_ITEMS = 7;
const MODEL_LIST_MAX_ITEMS = 12;
const MAX_PASTE_CHARS = 8000;
const PASTE_BURST_WINDOW_MS = 180;
const PASTE_BURST_CHAR_THRESHOLD = 220;
const PASTE_BURST_NEWLINE_THRESHOLD = 4;
const PASTE_BURST_MIN_CHARS_WITH_NEWLINES = 80;
const PASTE_BURST_EVENT_THRESHOLD = 3;
const PASTE_BURST_MIN_CHARS_RAPID_MULTILINE = 24;
const PASTE_BURST_BLOCK_MS = 250;
const TOOL_EXEC_TIMEOUT_MS = 300000;
const TOOL_EXEC_MAX_STEPS = 120000;
const TOOL_RESULT_TRUNCATE_WRAP_COLS = 120;
const TOOL_RESULT_TRUNCATE_MAX_LINES = 14;
const TOOL_RESULT_TRUNCATE_HEAD_LINES = 2;
const TOOL_RESULT_TRUNCATE_TAIL_LINES = 2;
// Context compaction (Codex-style local path): when accumulated history is
// near the model's context window, summarize old turns into a single
// "compaction summary" user message and keep only the most recent user-role
// messages, so long sessions survive instead of hitting the provider ceiling.
const COMPACTION_DEFAULT_FRACTION = 0.9; // hard ceiling: min(user, window * 90%)
const COMPACTION_RECENT_USER_TOKENS = 20000; // keep this many recent user tokens
const COMPACTION_SUMMARY_PREFIX = "_summary"; // marker prefix for summaries
const COMPACTION_DEFAULT_CUSTOM_INSTRUCTION =
  "Summarize this coding session as a structured handoff for another AI engineer. " +
  "Include: current task, files modified (with brief description of each change), " +
  "decisions made and their rationale, blockers encountered, and clear next steps. " +
  "Use bullet lists. Be concise but complete.";
const MAX_REASONING_DISPLAY_CHARS = 4000;
const MAX_INPUT_HISTORY_ITEMS = 500;
const DEFAULT_LLM_REQUEST_TIMEOUT_MS = 120000;
const MIN_LLM_REQUEST_TIMEOUT_MS = 10000;
const MAX_LLM_REQUEST_TIMEOUT_MS = 600000;
const THINKING_ANIMATION_INTERVAL_MS = 320;
const SHINE_ANIMATION_INTERVAL_MS = 66;
const ANSWER_REVEAL_MS = 500;
const ANSWER_REVEAL_TICK_MS = 33;
const THINKING_FRAMES = ["Thinking   ", "Thinking.  ", "Thinking.. ", "Thinking..."];
const SPINNER_FRAMES = ["\u280b", "\u2819", "\u2839", "\u2838", "\u283c", "\u2834", "\u2826", "\u2827", "\u2807", "\u280f"];
const APPEND_COMPOSER_FIXED_ROWS = 8;
const MOUSE_KEYPRESS_SUPPRESS_MS = 650;
const MOUSE_SELECTION_REENABLE_MS = 5000;
const PASTED_CONTENT_TOKEN_RE = /^\[Pasted Content \d+ chars\]$/i;
const PASTED_CONTENT_INLINE_TOKEN_RE = /\[Pasted Content \d+ chars\]/gi;
const IMAGE_INLINE_TOKEN_RE = /\[Image #\d+\]/gi;
const IMAGE_EXT_RE = /\.(png|jpe?g|gif|webp|bmp|svg|ico|tiff?|avif|heic|heif)(\?.*)?$/i;
const HIDE_CURSOR = "\u001b[?25l";
const SHOW_CURSOR = "\u001b[?25h";
const BRACKETED_PASTE_START = "\u001b[200~";
const BRACKETED_PASTE_END = "\u001b[201~";
const ENABLE_BRACKETED_PASTE = "\u001b[?2004h";
const DISABLE_BRACKETED_PASTE = "\u001b[?2004l";
const ENABLE_MOUSE_TRACKING = "\u001b[?1000h\u001b[?1006h";
const DISABLE_MOUSE_TRACKING = "\u001b[?1000l\u001b[?1006l";
const ENTER_ALT_SCREEN = "\u001b[?1049h";
const EXIT_ALT_SCREEN = "\u001b[?1049l";
const APP_MOUSE_TRACKING_ENABLED = process.env.TUI_ENABLE_MOUSE !== "0";
const APPEND_CHAT_TO_SCROLLBACK = false;
const OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1";
const WORKSPACE_ROOT = path.resolve(process.cwd());
const HOME_DIR = os.homedir();
const NEXUS_DIR = path.join(HOME_DIR, ".nexus");
const SESSIONS_DIR = path.join(NEXUS_DIR, "sessions");
const NEXUS_CONFIG_FILE = path.join(NEXUS_DIR, "config.json");
const NEXUS_PROVIDERS_FILE = path.join(NEXUS_DIR, "providers.json");
const NEXUS_MEMORY_FILE = path.join(NEXUS_DIR, "memory.jsonl");
const DEFAULT_PROVIDERS = [
  {
    name: "Open Router",
    base_url: "https://openrouter.ai/api/v1",
    api_key: "",
    model: "",
  },
];
const FALLBACK_MODELS = [
  "gpt-5",
  "gpt-5-mini",
  "gpt-5-nano",
  "gpt-4.1",
  "gpt-4.1-mini",
  "gpt-4o",
  "gpt-4o-mini",
  "o3",
  "o3-mini",
  "o4-mini",
];
const COMMANDS = [
  { name: "/providers", description: "manage provider list and credentials" },
  { name: "/set", description: "set runtime values: /set model <name> | /set thinking <on|off>" },
  { name: "/resume", description: "show session list and resume selected chat" },
  { name: "/clear", description: "clear chat window and delete current session history file" },
  { name: "/clear-memory", description: "clear all saved memory and memory keywords" },
  { name: "/permissions", description: "choose what Codex is allowed to do" },
  {
    name: "/sandbox-add-read-dir",
    description: "let sandbox read a directory: /sandbox-add-read-dir <absolute_path>",
  },
  { name: "/experimental", description: "toggle experimental features" },
  { name: "/skills", description: "use skills to improve how Codex performs specific tasks" },
  { name: "/review", description: "review my current changes and find issues" },
  { name: "/rename", description: "rename the current thread" },
  { name: "/new", description: "start a new chat with a new uid" },
  { name: "/mcp", description: "show MCP server status and available tools (/mcp reload to restart servers)" },
  { name: "/compact", description: "manually compact context: /compact [optional instruction]" },
];
const FALLBACK_TOOL_DESCRIPTIONS = {
  insert_memory:
    "insert_memory(memory: str, keyword: str|list[str]) -> dict: Save persistent memory with one or more keywords. Preference statements (like/dislike/prefer/love/hate) are auto-upserted by topic to prevent conflicting duplicates.",
  retrieve_memory:
    "retrieve_memory(query: str = '', use_regex: bool = False, case_sensitive: bool = False, regex_flags: str = '', keywords: str|list[str]|None = None, max_results: int = 20) -> list[dict]: Retrieve memories by string/regex and/or keyword filters.",
  memory_keywords:
    "memory_keywords() -> list[dict]: List all inserted memory keywords with usage counts.",
  remove_memory:
    "remove_memory(id: str) -> dict: Remove one memory record by id.",
  update_memory:
    "update_memory(id: str, memory: str|None = None, keyword: str|list[str]|None = None) -> dict: Update one memory record by id (memory text and/or keywords).",
  exclude_history_messages:
    "exclude_history_messages(latest_n: int = 0, role: str = '', query: str = '', use_regex: bool = False, case_sensitive: bool = False, regex_flags: str = '', max_matches: int = 200, include_system: bool = False) -> dict: Exclude matching existing chat messages from future LLM requests.",
  create_plan:
    "create_plan(entries: str|list[str]) -> dict: Create a new workspace to-do plan and return the full plan.",
  update_plan:
    "update_plan(completed: int|str|list[int|str]|None = None, new_entries: str|list[str]|None = None) -> dict: Mark plan entries completed and/or add new plan entries, then return updated entries and current plan.",
  get_current_plan:
    "get_current_plan() -> dict: Get current workspace plan with [ ]/[✓] style formatted output.",
  get_current_working_directory:
    "get_current_working_directory() -> str: Return absolute workspace path.",
  get_file_list:
    "get_file_list(path: str = '.') -> list[str]: List files/directories under a workspace path.",
  get_file_content:
    "get_file_content(path: str, start_line: int = -1, end_line: int = -1) -> str: Read full or partial file content by 1-based line range.",
  find_files:
    "find_files(query: str, path: str = '.', max_results: int = 200) -> list[str]: Find files by name/path substring.",
  list_directory:
    "list_directory(path: str = '.', include_hidden: bool = False, max_results: int = 500) -> list[dict]: List direct children of a directory.",
  make_directory:
    "make_directory(path: str, parents: bool = True, exist_ok: bool = True) -> dict: Create directory in workspace.",
  delete_path:
    "delete_path(path: str, recursive: bool = False) -> dict: Delete file/directory in workspace.",
  move_path:
    "move_path(src: str, dst: str, overwrite: bool = False) -> dict: Move or rename path in workspace.",
  copy_path:
    "copy_path(src: str, dst: str, overwrite: bool = False, recursive: bool = False) -> dict: Copy file/directory in workspace.",
  path_exists:
    "path_exists(path: str) -> dict: Return existence/type info for a workspace path.",
  find_in_file:
    "find_in_file(path: str, query: str, use_regex: bool = False, case_sensitive: bool = False, regex_flags: str = '', max_results: int = 200) -> list[dict]: Find matches in one file (literal or regex) with line/column locations.",
  write_file:
    "write_file(path: str, content: str) -> dict: Write text file (create/overwrite) in workspace.",
  replace_in_file:
    "replace_in_file(path: str, old: str, new: str, count: int = -1, use_regex: bool = False, regex_flags: str = '') -> dict: Replace text in a file (literal or regex).",
  run_shell:
    "run_shell(command: str, timeout: int|float = 10) -> dict: Run shell command with timeout seconds.",
  get_git_status:
    "get_git_status() -> dict: Return git status summary.",
  get_git_diff:
    "get_git_diff(path: str = '', staged: bool = False, context_lines: int = 3, max_chars: int = 60000) -> dict: Return git diff text.",
  get_git_log:
    "get_git_log(max_count: int = 20) -> dict: Return recent git commits.",
  get_file_info: "async get_file_info(path: str) -> dict: Return file metadata inside workspace.",
  read_file_summary: "async read_file_summary(path: str) -> dict: Return summary/preview for large files.",
};

let input = "";
let inputCursorIndex = 0;
let submittedInputHistory = [];
let submittedInputHistoryIndex = -1;
let submittedInputHistoryDraft = "";
const messages = [];
let lastFrameTop = null;
let lastFrameHeight = 0;
let lastChatAreaHeight = null;
let chatScrollOffset = 0;
let lastMenuTop = null;
let lastMenuHeight = 0;
let lastFooterTop = null;
let lastMenuRenderedLines = [];
let lastStatusTop = null;
let lastStatusHeight = 0;
let lastStatusVisible = false;
let hasInitializedScreen = false;
let forceFullClearOnNextRender = false;
let dirty = true;
let flushTimer = null;
const IDLE_FLUSH_MS = 160;
const FAST_KEY_GAP_MS = 10;
let cleanedUp = false;
let lastInputEventAt = 0;
let burstMode = false;
let commandMenuDismissed = false;
let commandMenuSelected = 0;
let commandMenuScroll = 0;
let activeBuffer = "main";
let selectedModel = "";
let reasoningEnabledByModel = {};
let modelSearch = "";
let modelSelected = 0;
let modelScroll = 0;
let availableModels = FALLBACK_MODELS.map((id) => ({
  id,
  inputModalities: ["text"],
  outputModalities: ["text"],
  contextLength: 0,
}));
let isModelsLoading = false;
let loadedModelsProviderKey = "";
let modelsLoadError = "";
let lastModelRenderedRows = [];
let lastModelRenderedCols = 0;
let lastModelRenderedHeight = 0;
let sessionFiles = [];
let sessionsSelected = 0;
let sessionsScroll = 0;
let isSessionsLoading = false;
let sessionsLoadError = "";
let lastSessionsRenderedRows = [];
let lastSessionsRenderedCols = 0;
let lastSessionsRenderedHeight = 0;
let providers = [];
let selectedProviderName = DEFAULT_PROVIDERS[0].name;
let nexusConfig = {};
let providersSelected = 0;
let providersScroll = 0;
let isProvidersLoading = false;
let providersLoadError = "";
let lastProvidersRenderedRows = [];
let lastProvidersRenderedCols = 0;
let lastProvidersRenderedHeight = 0;
let providerEditorMode = "";
let providerEditorIndex = -1;
let providerEditorFieldIndex = 0;
let providerEditorDraft = { name: "", base_url: "", api_key: "", model: "" };
let lastProviderEditorRenderedRows = [];
let lastProviderEditorRenderedCols = 0;
let lastProviderEditorRenderedHeight = 0;
let commandBufferQuery = "";
let lastCommandRenderedRows = [];
let lastCommandRenderedCols = 0;
let lastCommandRenderedHeight = 0;
let burstWindowStartAt = 0;
let burstWindowChars = 0;
let burstWindowNewlines = 0;
let burstWindowEvents = 0;
let burstWindowContent = "";
let burstSnapshotInput = "";
let burstSnapshotCursor = 0;
let suppressIncomingUntil = 0;
let pendingPastedPayloads = [];
let activeBlockedPastePayloadIndex = -1;
let isBracketedPasteActive = false;
let bracketedPasteBuffer = "";
let suppressKeypressUntil = 0;
let suppressMouseNoiseUntil = 0;
let ignoreNextProvidersEscape = false;
let bracketedPasteModeEnabled = false;
let mouseTrackingEnabled = false;
let mouseSelectionMode = false;
let mouseSelectionTimer = null;
let mouseSelectionStartedAt = 0;
let mouseSequenceRemainder = "";
let pasteParserBuffer = "";
let imagePasteCounter = 0;
const imageTokenPayloads = new Map();
let openRouterClient = null;
let openRouterClientKey = "";
let assistantRequestChain = Promise.resolve();
let pendingAssistantRequests = 0;
let chatGeneration = 0;
let toolDescriptions = { ...FALLBACK_TOOL_DESCRIPTIONS };
let systemPromptText = "";
let skillsCatalog = [];
let systemPromptLoadPromise = null;
let mcpBridgeServer = null;
let mcpBridgePort = 0;
let mcpServers = [];
let mcpDescriptions = {};
let mcpBridgeReadyResolve = null;
let mcpBridgeReadyPromise = null;
let mcpBridgeState = "";
let mcpBridgeError = "";
let mcpStartupActive = false;
let mcpStartupHasConfig = false;
let answerRevealTimer = null;
let answerRevealSettlePending = false;
let forceChatRefreshFlag = false;
let thinkingAnimationTimer = null;
let thinkingFrameIndex = 0;
let shineFrameIndex = 0;
let shineAnimationTimer = null;
let spinnerFrameIndex = 0;
let spinnerAnimationTimer = null;
let thinkingStartedAt = 0;
let activeToolRun = null; // { label, startedAt, done, ok }
let stopRequested = false;
let pendingAssistantMessageIndex = -1;
let contextLeftPercentByModel = {};
let currentSessionUid = createSessionUid();
let sessionFilePath = getSessionFilePath(currentSessionUid);
let sessionInitPromise = null;
let sessionWriteChain = Promise.resolve();
let sessionPersistenceInitialized = false;
let printedMessageCount = 0;
let lastRenderedChatRole = null;
let lastRenderableMessageCount = -1;
let altScreenActive = false;
let forceTranscriptReplay = true;
let appendReservedBottomRows = 0;
let cachedChatLines = null;
let lastEntryVisualStartIndex = -1;
let cachedChatLinesCols = 0;
let cachedChatLinesLen = -1;
let cachedChatLinesLastRef = null;
let cachedChatLinesSpacing = -1;

function createSessionUid() {
  if (typeof randomUUID === "function") {
    return randomUUID();
  }

  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

function getSessionFilePath(uid) {
  return path.join(SESSIONS_DIR, `session-${uid}.jsonl`);
}

function normalizeReasoningConfigMap(raw) {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return {};
  }

  const normalized = {};
  for (const [key, value] of Object.entries(raw)) {
    if (typeof key === "string" && key.trim().length > 0 && typeof value === "boolean") {
      normalized[key.trim()] = value;
    }
  }
  return normalized;
}

function getSessionReasoningConfig() {
  return normalizeReasoningConfigMap(reasoningEnabledByModel);
}

function isAssistantNoContentFallbackMessage(content) {
  if (typeof content !== "string") {
    return false;
  }
  const normalized = content.trim();
  return (
    normalized === "Provider returned no assistant content." ||
    normalized === "Provider returned no assistant content. Try /set thinking off for this model."
  );
}

function hasSuccessfulAssistantMessage() {
  return messages.some((entry) => {
    if (!entry || entry.role !== "assistant" || entry.ephemeral === true) {
      return false;
    }
    const content = typeof entry.content === "string" ? entry.content.trim() : "";
    if (!content) {
      return false;
    }
    return !isAssistantNoContentFallbackMessage(content);
  });
}

function hasUserMessage() {
  return messages.some((entry) => entry && entry.role === "user");
}

function shouldPersistSessionHistory() {
  return hasUserMessage() && hasSuccessfulAssistantMessage();
}

function getReasoningEnabledForModel(modelId = selectedModel) {
  const key = typeof modelId === "string" ? modelId.trim() : "";
  if (!key) {
    return true;
  }
  if (Object.prototype.hasOwnProperty.call(reasoningEnabledByModel, key)) {
    return Boolean(reasoningEnabledByModel[key]);
  }
  return true;
}

function setReasoningEnabledForModel(modelId, enabled) {
  const key = typeof modelId === "string" ? modelId.trim() : "";
  if (!key) {
    return;
  }
  reasoningEnabledByModel[key] = Boolean(enabled);
}

function normalizeModelLookupKey(value) {
  return typeof value === "string" ? value.trim().toLowerCase() : "";
}

function getModelEntryForContext(modelId = selectedModel) {
  const key = typeof modelId === "string" ? modelId.trim() : "";
  if (!key) {
    return null;
  }

  const exact = availableModels.find((item) => item?.id === key);
  if (exact) {
    return exact;
  }

  const keyLower = normalizeModelLookupKey(key);
  const byCase = availableModels.find((item) => normalizeModelLookupKey(item?.id) === keyLower);
  if (byCase) {
    return byCase;
  }

  // Match alias forms like "owner/model" vs "model".
  const keyTail = keyLower.includes("/") ? keyLower.split("/").pop() : keyLower;
  if (keyTail) {
    const byTail = availableModels.find((item) => {
      const idLower = normalizeModelLookupKey(item?.id);
      if (!idLower) {
        return false;
      }
      const idTail = idLower.includes("/") ? idLower.split("/").pop() : idLower;
      return idTail === keyTail;
    });
    if (byTail) {
      return byTail;
    }
  }

  // Common provider suffix mismatch fallback (":free", ":thinking", etc.).
  const byPrefix = availableModels.find((item) => {
    const idLower = normalizeModelLookupKey(item?.id);
    return idLower && (idLower.startsWith(`${keyLower}:`) || keyLower.startsWith(`${idLower}:`));
  });
  if (byPrefix) {
    return byPrefix;
  }

  // If provider exposes only one loaded model, use it as the active context source.
  if (availableModels.length === 1) {
    return availableModels[0];
  }

  return null;
}

function getModelContextLength(modelId = selectedModel) {
  // Optional per-session window override beats everything: providers often
  // omit context_length from /models, and a 128k fallback is wrong for
  // models with e.g. a 1M window.
  const override = Number(nexusConfig?.model_context_window_override);
  if (Number.isFinite(override) && override > 0) {
    return Math.floor(override);
  }
  const model = getModelEntryForContext(modelId);
  const raw = Number(model?.contextLength || 0);
  if (!Number.isFinite(raw) || raw <= 0) {
    return 0;
  }
  return Math.floor(raw);
}

function getContextLeftPercent(modelId = selectedModel) {
  const key = typeof modelId === "string" ? modelId.trim() : "";
  if (!key) {
    return 100;
  }

  const raw = Number(contextLeftPercentByModel[key]);
  if (Number.isFinite(raw)) {
    return Math.max(0, Math.min(100, raw));
  }

  // No live usage data yet (e.g. resumed a session before the first new
  // completion). Estimate from the current messages using the same
  // chars-per-token heuristic as compaction, so the footer shows a
  // meaningful percentage instead of a stale 100%.
  // Fall back to a sane 128k estimate when the model does not advertise a
  // context length (same default compaction uses), so a resumed session
  // never gets stuck showing a meaningless 100%.
  const contextLength = getModelContextLength(modelId);
  const windowLength = Number.isFinite(contextLength) && contextLength > 0 ? contextLength : 128000;
  const estimatedTokens = messages.length > 0 ? estimateMessagesInChatTokens(messages) : 0;
  if (estimatedTokens > 0) {
    const percentLeft = ((windowLength - estimatedTokens) / windowLength) * 100;
    return Math.max(0, Math.min(100, Math.round(percentLeft)));
  }
  return 100;
}

function setContextLeftPercent(modelId, percent) {
  const key = typeof modelId === "string" ? modelId.trim() : "";
  if (!key) {
    return;
  }
  const raw = Number(percent);
  if (!Number.isFinite(raw)) {
    return;
  }
  contextLeftPercentByModel[key] = Math.max(0, Math.min(100, raw));
}

function updateContextBudgetFromCompletion(completion, modelId = selectedModel) {
  const responseModelId =
    typeof completion?.model === "string" && completion.model.trim().length > 0
      ? completion.model.trim()
      : "";

  let contextLength = getModelContextLength(responseModelId || modelId);
  if (contextLength <= 0 && responseModelId && responseModelId !== modelId) {
    contextLength = getModelContextLength(modelId);
  }
  if (contextLength <= 0) {
    // Model does not advertise a context window; fall back to a sane 128k
    // default so the footer keeps tracking progress after each completion.
    contextLength = 128000;
  }

  const usage = completion?.usage && typeof completion.usage === "object" ? completion.usage : null;
  const timings =
    completion?.timings && typeof completion.timings === "object" ? completion.timings : null;

  const usagePromptTokens = Number(usage?.prompt_tokens);
  const usageTotalTokens = Number(usage?.total_tokens);
  const timingsCacheN = Number(timings?.cache_n);
  const timingsPromptN = Number(timings?.prompt_n);
  const timingsPredictedN = Number(timings?.predicted_n);
  const timingsContextTokens =
    (Number.isFinite(timingsCacheN) && timingsCacheN > 0 ? timingsCacheN : 0) +
    (Number.isFinite(timingsPromptN) && timingsPromptN > 0 ? timingsPromptN : 0) +
    (Number.isFinite(timingsPredictedN) && timingsPredictedN > 0 ? timingsPredictedN : 0);

  const usedTokens =
    timingsContextTokens > 0
      ? timingsContextTokens
      : Number.isFinite(usageTotalTokens) && usageTotalTokens > 0
        ? usageTotalTokens
        : Number.isFinite(usagePromptTokens) && usagePromptTokens > 0
          ? usagePromptTokens
          : 0;
  if (usedTokens <= 0) {
    return;
  }

  const percentLeft = ((contextLength - usedTokens) / contextLength) * 100;
  setContextLeftPercent(modelId, percentLeft);
  if (responseModelId && responseModelId !== modelId) {
    setContextLeftPercent(responseModelId, percentLeft);
  }
  ensureSystemMessageAtTop(modelId);
}

function normalizeReasoningDetails(value) {
  if (typeof value === "string") {
    const cleaned = value.trim();
    return cleaned.length > 0 ? [{ type: "reasoning.text", text: cleaned, format: "unknown" }] : null;
  }
  if (!Array.isArray(value)) {
    return null;
  }
  const cleaned = [];
  for (const item of value) {
    if (typeof item === "string") {
      cleaned.push({ type: "reasoning.text", text: item, format: "unknown" });
    } else if (item && typeof item === "object") {
      cleaned.push(item);
    }
  }
  return cleaned.length > 0 ? cleaned : null;
}

function extractReasoningDisplayText(reasoningDetails) {
  const details = normalizeReasoningDetails(reasoningDetails);
  if (!details) {
    return "";
  }

  const chunks = [];
  for (const detail of details) {
    const type = typeof detail?.type === "string" ? detail.type : "";
    if (type === "reasoning.summary") {
      const summary = detail?.summary;
      if (typeof summary === "string" && summary.trim().length > 0) {
        chunks.push(summary.trim());
        continue;
      }
      if (Array.isArray(summary)) {
        const parts = summary
          .map((item) => {
            if (typeof item === "string") {
              return item;
            }
            if (typeof item?.text === "string") {
              return item.text;
            }
            return "";
          })
          .filter((part) => part.trim().length > 0);
        if (parts.length > 0) {
          chunks.push(parts.join("\n"));
          continue;
        }
      }
    }

    if (type === "reasoning.text" && typeof detail?.text === "string" && detail.text.trim().length > 0) {
      chunks.push(detail.text.trim());
      continue;
    }

    if (type === "reasoning.encrypted") {
      chunks.push("[encrypted reasoning]");
      continue;
    }

    if (typeof detail?.text === "string" && detail.text.trim().length > 0) {
      chunks.push(detail.text.trim());
      continue;
    }
    if (typeof detail?.summary === "string" && detail.summary.trim().length > 0) {
      chunks.push(detail.summary.trim());
    }
  }

  const joined = chunks.join("\n\n").trim();
  if (!joined) {
    return "";
  }

  if (joined.length > MAX_REASONING_DISPLAY_CHARS) {
    return `${joined.slice(0, MAX_REASONING_DISPLAY_CHARS)}\n...`;
  }
  return joined;
}

function execFileAsync(file, args, options = {}) {
  return new Promise((resolve, reject) => {
    execFile(file, args, options, (error, stdout, stderr) => {
      if (error) {
        error.stdout = stdout;
        error.stderr = stderr;
        reject(error);
        return;
      }
      resolve({ stdout, stderr });
    });
  });
}

function getBundledPythonExe() {
  // Prefer the tools.exe that sits NEXT TO this executable (works when sea.exe
  // is launched from any cwd via PATH). __dirname resolves to the exe's folder
  // in SEA, process.execPath is the definitive path.
  const candidates = [
    path.join(path.dirname(process.execPath), "tools.exe"),
    path.join(__dirname, "tools.exe"),
    path.join(process.cwd(), "tools.exe"),
  ];
  for (const candidate of candidates) {
    try {
      if (fsSync.existsSync(candidate)) {
        return candidate;
      }
    } catch {
      // continue
    }
  }
  return "";
}

async function runPythonCommand(args, options = {}) {
  const mergedOptions = { cwd: process.cwd(), windowsHide: true, ...options };
  const bundledExe = getBundledPythonExe();

  // Prefer a self-contained tools.exe bundled next to this app.
  if (bundledExe) {
    const normalized = args.map((arg) =>
      typeof arg === "string" && path.basename(arg) === "tools.py" ? arg : arg
    );
    return await execFileAsync(bundledExe, normalized, mergedOptions);
  }

  try {
    return await execFileAsync("python", args, mergedOptions);
  } catch (error) {
    if (error?.code !== "ENOENT") {
      throw error;
    }
  }

  return execFileAsync("py", ["-3", ...args], mergedOptions);
}

function buildSystemPromptFromDescriptions(descriptions, runtime = {}) {
  const entries = Object.entries(descriptions || {});
  const lines = entries
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([name, description]) => `- ${name}: ${description}`);
  const modelLabel =
    typeof runtime?.modelId === "string" && runtime.modelId.trim().length > 0
      ? runtime.modelId.trim()
      : "no model";
  const rawContextLeft = Number(runtime?.contextLeftPercent);
  const safeContextLeft = Number.isFinite(rawContextLeft)
    ? Math.max(0, Math.min(100, Math.round(rawContextLeft)))
    : 100;

  return [
    "Your name is Nexus developed by duxx.",
    "You are a terminal coding assistant. You can spawn agents and orchestrate them.",
    "",
    "RUNTIME CONTEXT STATUS (MUST FOLLOW):",
    `- Current model: ${modelLabel}`,
    "- Use context effectively: avoid unnecessary repetition, avoid re-reading unchanged large files, and prefer targeted edits/tool calls.",
    "",
    "TOOL USAGE FORMAT (MANDATORY):",
    "- If tool use is needed, output exactly one fenced ```execute code block.",
    "- Only ```execute blocks are executed by the app.",
    "- Never use ```python blocks for executable tool calls (those are treated as plain text/demo).",
    "- Do not output JSON like {\"tool\": \"...\", \"arguments\": {...}}.",
    "- Do not output tool_call payloads, XML, YAML, or pseudo function-call objects.",
    "- Call helper functions directly in Python code.",
    "- For tool-use replies, include no prose before or after the execute block.",
    "",
    "FILE EDIT STRATEGY (MANDATORY):",
    "- For existing files, prefer incremental edits with replace_in_file instead of rewriting the full file.",
    "- Keep edits minimal and targeted to the smallest relevant block.",
    "- Use write_file only for new files, or when the user explicitly asks for a full rewrite.",
    "- Before replacing, read context only if needed (missing or stale).",
    "- If the relevant code is already present in recent conversation/tool output, do not call read tools again.",
    "",
    "VALID TOOL-USE RESPONSE EXAMPLE 1:",
    "```execute",
    "cwd = get_current_working_directory()",
    "print(cwd)",
    "print(get_file_list(\".\"))",
    "```",
    "",
    "VALID TOOL-USE RESPONSE EXAMPLE 2:",
    "```execute",
    "path = \"index.js\"",
    "file_info = await get_file_info(path)",
    "if file_info[\"size\"] < 10000:",
    "    print(get_file_content(path))",
    "else:",
    "    print(await read_file_summary(path))",
    "```",
    "",
    "VALID TOOL-USE RESPONSE EXAMPLE 3:",
    "```execute",
    "matches = find_in_file(",
    "    path=\"index.js\",",
    "    query=\"buildSystemPromptFromDescriptions\",",
    "    use_regex=False,",
    "    max_results=5,",
    ")",
    "print(matches)",
    "```",
    "",
    "VALID FILE-EDIT RESPONSE EXAMPLE:",
    "```execute",
    "snippet = get_file_content(\"index.js\", start_line=120, end_line=170)",
    "old = \"const RETRY_COUNT = 2\"",
    "new = \"const RETRY_COUNT = 3\"",
    "print(replace_in_file(\"index.js\", old, new, count=1))",
    "```",
    "",
    "VALID PLAN TOOL RESPONSE EXAMPLE 1:",
    "```execute",
    "print(create_plan([",
    "    \"Inspect repository structure\",",
    "    \"Implement initial CLI\",",
    "    \"Add tests for critical flows\",",
    "]))",
    "print(get_current_plan())",
    "```",
    "",
    "VALID PLAN TOOL RESPONSE EXAMPLE 2:",
    "```execute",
    "print(update_plan(completed=[1, \"Implement initial CLI\"]))",
    "print(get_current_plan())",
    "```",
    "",
    "VALID PLAN TOOL RESPONSE EXAMPLE 3:",
    "```execute",
    "print(update_plan(new_entries=[",
    "    \"Add CI workflow\",",
    "    \"Write migration notes\",",
    "]))",
    "print(get_current_plan())",
    "```",
    "",
    "INVALID RESPONSE EXAMPLE (NEVER DO THIS):",
    "{\"tool\": \"get_file_list\", \"arguments\": {\"path\": \".\"}}",
    "",
    "RECURSIVE SUBAGENTS (MANDATORY):",
    "- You can delegate independent workloads to child agents in parallel:",
    "  h = rlm_spawn('Do X')",
    "  result = rlm_spawn('Do X', timeout=120)['result']   # poll instead, see below",
    "- rlm_spawn returns immediately with an admission handle {id, status, prompt}.",
    "- Poll with list_subagents() until status == 'done', then read result from the entry.",
    "- Or import the runtime directly in an execute block:",
    "  import harness",
    "  h = harness.rlm('Do X')       # spawn; returns handle",
    "  result = harness.rlm('Do X').join(timeout=120)   # or await h",
    "  print(harness.rlm.list_subagents())",
    "  print(harness.rlm.delete_subagent(h))",
    "- Use subagents when work is parallel/independent (research chunks, separate file reviews, batch tasks).",
    "- Avoid spawning subagents for trivial one-liner lookups; do those inline.",
    "- rlm(...) uses the active provider/model from ~/.nexus/providers.json.",
    "",
    "CONTINUAL HARNESS (MANDATORY):",
    "- Persistent state lives in ~/.nexus/harness.json and survives across sessions.",
    "- harness_overview() -> list current memories, skills, subagent templates, prompt notes, refinements.",
    "- harness_memory(key, content) / harness_memory(key, delete=True): durable facts about the user or project.",
    "- harness_prompt_note(name, content) / (name, delete=True): reusable instructions or style guidance.",
    "- harness_subagent(name, prompt, model, system) / (name, ..., delete=True): save reusable subagent templates, then rlm_spawn(..., template=name).",
    "- harness_skill(name, description, body) / (name, delete=True): create a real SKILL.md in ~/.nexus/skills (surfaces via list_skills).",
    "- record_refinement(summary, evidence): persist a reusable pattern with supporting evidence.",
    "- refine_reflection(): auto-synthesize a refinement from recent subagent results and prompt notes.",
    "- Use the harness for durable cross-session knowledge. Never store secrets or credentials there.",
    "- Keep refinements small and evidence-backed. Do not write the same refinement repeatedly.",
    "",
    "SKILL DEPENDENCIES (OPTIONAL):",
    "- A skill folder may contain requirements.txt declaring Python packages.",
    "- get_skill() auto-installs them into a shared venv at ~/.nexus/skills-venv (never system Python).",
    "- Install is non-blocking: get_skill returns immediately with deps.status = 'installing'; call get_skill again later to see 'satisfied' or the error.",
    "- Run skill scripts with skill_python_path() (the venv interpreter) via run_shell.",
    "- If install fails (offline/bad package), deps.error explains why; fall back to stdlib or document the limitation.",
    "- Disable auto-install by setting skills_auto_install_deps=false in ~/.nexus/config.json.",
    "",
    "SKILLS (OPTIONAL EXTENSIONS):",
    "- Skills are packaged instructions you can load when the task matches.",
    "- Call list_skills() to see available skills, then get_skill(name) to load the instructions.",
    "- Load a skill only when it is relevant to the current task; otherwise ignore.",
    "- Available skills:",
    ...(skillsCatalog.length > 0
      ? skillsCatalog.map((s) => `  - ${s.name}${s.description ? ": " + s.description : ""}`)
      : ["  (none)"]),
    "",
    "Predefined Python helper functions available in the execution environment:",
    ...(lines.length > 0 ? lines : ["- (none)"]),
    "",
    "MCP TOOLS (Model Context Protocol servers, optional):",
    "- MCP servers are separate processes exposing extra capabilities as tools.",
    "- Call them from within an execute block using: mcp_call(server, tool, args) -> dict",
    "- List available servers/tools with: mcp_list() -> dict",
    ...(Object.keys(mcpDescriptions).length > 0
      ? Object.entries(mcpDescriptions)
          .sort((a, b) => a[0].localeCompare(b[0]))
          .map(([toolKey, desc]) => `- ${toolKey}: ${desc}`)
      : ["- (no MCP servers/tools available)"]),
    "",
    "If no tool use is needed, reply in normal plain text.",
  ].join("\n");
}

async function loadToolDescriptionsFromPython() {
  try {
    const { stdout } = await runPythonCommand(["tools.py", "--describe-json"], {
      timeout: 3000,
      maxBuffer: 256 * 1024,
    });
    const parsed = JSON.parse(String(stdout || "{}"));
    if (!parsed || typeof parsed !== "object") {
      return { ...FALLBACK_TOOL_DESCRIPTIONS };
    }

    const cleaned = {};
    for (const [name, description] of Object.entries(parsed)) {
      if (typeof name === "string" && typeof description === "string") {
        cleaned[name] = description;
      }
    }

    if (Object.keys(cleaned).length === 0) {
      return { ...FALLBACK_TOOL_DESCRIPTIONS };
    }

    return cleaned;
  } catch {
    return { ...FALLBACK_TOOL_DESCRIPTIONS };
  }
}

async function loadSkillsCatalog() {
  try {
    const { stdout } = await runPythonCommand(["tools.py", "--list-skills-json"], {
      timeout: 3000,
      maxBuffer: 128 * 1024,
    });
    const parsed = JSON.parse(String(stdout || "{}"));
    const skills = Array.isArray(parsed?.skills) ? parsed.skills : [];
    skillsCatalog = skills
      .filter((item) => item && typeof item.name === "string" && item.name.trim().length > 0)
      .map((item) => ({
        name: item.name.trim(),
        description: typeof item.description === "string" ? item.description.trim() : "",
      }));
  } catch {
    skillsCatalog = [];
  }
}

// ---------------------------------------------------------------------------
// MCP (Model Context Protocol) client support
//
// Launches configured MCP stdio servers at startup, exposes their tools to
// the LLM via the system prompt, and bridges tool calls from the Python
// execution environment (tools.py) through a localhost HTTP endpoint.
// ---------------------------------------------------------------------------

const MCP_CONFIG_PATH = path.join(os.homedir(), ".nexus", "mcp_config.json");

// mcpBridgeServer, mcpBridgePort, mcpServers, mcpDescriptions, mcpBridgeReady*
// and mcpBridgeState/Error are declared at the top of the file.

function getMcpConfigPath() {
  return MCP_CONFIG_PATH;
}

function loadMcpConfig() {
  try {
    if (!fsSync.existsSync(MCP_CONFIG_PATH)) {
      return { mcpServers: {} };
    }
    const raw = JSON.parse(fsSync.readFileSync(MCP_CONFIG_PATH, "utf8"));
    const servers = raw?.mcpServers && typeof raw.mcpServers === "object" ? raw.mcpServers : {};
    return { mcpServers: servers };
  } catch (error) {
    mcpBridgeError = `Failed to parse ${MCP_CONFIG_PATH}: ${error?.message || error}`;
    return { mcpServers: {} };
  }
}

function mcpMessageFrame(message) {
  const body = JSON.stringify(message);
  return `Content-Length: ${Buffer.byteLength(body, "utf8")}\r\n\r\n${body}`;
}

function mcpParseFrame(buffer) {
  const headerEnd = buffer.indexOf("\r\n\r\n");
  if (headerEnd === -1) {
    return null;
  }
  const header = buffer.slice(0, headerEnd).toString("utf8");
  const match = /Content-Length:\s*(\d+)/i.exec(header);
  if (!match) {
    return null;
  }
  const length = Number(match[1]);
  const bodyStart = headerEnd + 4;
  if (buffer.length < bodyStart + length) {
    return null;
  }
  const body = buffer.slice(bodyStart, bodyStart + length).toString("utf8");
  let parsed = null;
  try {
    parsed = JSON.parse(body);
  } catch {
    parsed = null;
  }
  return { message: parsed, consumed: bodyStart + length };
}

// Node's execFile buffers stdout; MCP needs streaming, so use spawn:
const { spawn } = require("node:child_process");

class McpStdioClientReal {
  constructor(name, config) {
    this.name = name;
    this.config = config;
    this.child = null;
    this.buffer = Buffer.alloc(0);
    this.requestId = 0;
    this.pending = new Map();
    this.initialized = false;
    this.stderrTail = "";
    this.toolsCache = null;
    this.toolsCacheError = "";
    this.closed = false;
  }

  async start() {
    const command = typeof this.config?.command === "string" ? this.config.command : "";
    if (!command.trim()) {
      throw new Error(`MCP server ${this.name}: missing "command"`);
    }
    const args = Array.isArray(this.config?.args) ? this.config.args.map(String) : [];
    const env = { ...process.env };
    const configEnv = this.config?.env && typeof this.config.env === "object" ? this.config.env : {};
    for (const [k, v] of Object.entries(configEnv)) {
      if (typeof v === "string") {
        env[k] = v;
      }
    }

    this.child = spawn(command, args, {
      env,
      cwd: this.config?.cwd || process.cwd(),
      windowsHide: true,
      stdio: ["pipe", "pipe", "pipe"],
    });
    this.child.stdout.on("data", (chunk) => this._onData(chunk));
    this.child.stderr.on("data", (chunk) => {
      this.stderrTail = (this.stderrTail + String(chunk)).slice(-4000);
    });
    this.child.on("error", (error) => {
      if (!this.closed) {
        this.stderrTail = (this.stderrTail + `\nspawn error: ${error?.message || error}`).slice(-4000);
      }
    });
    this.child.on("exit", (code, signal) => {
      if (!this.closed) {
        this.stderrTail = (this.stderrTail + `\nexited code=${code} signal=${signal}`).slice(-4000);
      }
    });

    await this._request("initialize", {
      protocolVersion: "2025-03-26",
      capabilities: {},
      clientInfo: { name: "nexus-tui", version: "1.0.0" },
    });

    this._send({ jsonrpc: "2.0", method: "notifications/initialized" });
    this.initialized = true;
  }

  _send(obj) {
    if (!this.child || !this.child.stdin || this.child.stdin.destroyed) {
      throw new Error(`MCP server ${this.name}: stdin closed`);
    }
    this.child.stdin.write(mcpMessageFrame(obj));
  }

  _onData(chunk) {
    this.buffer = Buffer.concat([this.buffer, chunk]);
    for (;;) {
      const parsed = mcpParseFrame(this.buffer);
      if (!parsed) {
        break;
      }
      this.buffer = this.buffer.slice(parsed.consumed);
      const msg = parsed.message;
      if (!msg) {
        continue;
      }
      if (msg.id !== undefined && msg.id !== null && this.pending.has(String(msg.id))) {
        const { resolve, reject } = this.pending.get(String(msg.id));
        this.pending.delete(String(msg.id));
        if (msg.error) {
          reject(new Error(msg.error.message || JSON.stringify(msg.error)));
        } else {
          resolve(msg.result);
        }
        continue;
      }
      if (msg.method === "notifications/message") {
        const level = msg.params?.level || "info";
        if (level === "error" || level === "warning") {
          this.stderrTail = (this.stderrTail + `\n[server message] ${msg.params?.message || ""}`).slice(-4000);
        }
      }
    }
  }

  _request(method, params = {}) {
    if (this.child && !this.child.stdin?.destroyed && this.child.exitCode !== null) {
      return Promise.reject(new Error(`MCP server ${this.name}: process exited`));
    }
    const id = ++this.requestId;
    const payload = { jsonrpc: "2.0", id, method, params };
    return new Promise((resolve, reject) => {
      this.pending.set(String(id), { resolve, reject });
      try {
        this._send(payload);
      } catch (error) {
        this.pending.delete(String(id));
        reject(error);
      }
      // Safety timeout: 30s for long-running tools.
      setTimeout(() => {
        if (this.pending.has(String(id))) {
          this.pending.delete(String(id));
          reject(new Error(`MCP server ${this.name}: request timed out (${method})`));
        }
      }, 30000);
    });
  }

  async listTools() {
    if (this.toolsCache) {
      return this.toolsCache;
    }
    try {
      const result = await this._request("tools/list", {});
      const tools = Array.isArray(result?.tools) ? result.tools : [];
      this.toolsCache = tools
        .filter((t) => t && typeof t.name === "string" && t.name.trim().length > 0)
        .map((t) => ({
          name: t.name.trim(),
          description: typeof t.description === "string" ? t.description : "",
          inputSchema: t.inputSchema && typeof t.inputSchema === "object" ? t.inputSchema : {},
        }));
      this.toolsCacheError = "";
      return this.toolsCache;
    } catch (error) {
      this.toolsCacheError = error?.message || String(error);
      throw error;
    }
  }

  async callTool(name, args = {}) {
    return this._request("tools/call", {
      name,
      arguments: args && typeof args === "object" ? args : {},
    });
  }

  async close() {
    this.closed = true;
    for (const { reject } of this.pending.values()) {
      reject(new Error(`MCP server ${this.name}: closed`));
    }
    this.pending.clear();
    if (this.child) {
      try {
        this.child.stdin.end();
      } catch {
        // ignore
      }
      const child = this.child;
      this.child = null;
      await new Promise((resolve) => {
        const timer = setTimeout(() => {
          try {
            child.kill();
          } catch {
            // ignore
          }
          resolve();
        }, 1500);
        child.once("exit", () => {
          clearTimeout(timer);
          resolve();
        });
        if (child.exitCode !== null) {
          clearTimeout(timer);
          resolve();
        }
      });
    }
  }
}

async function startMcpServers() {
  const config = loadMcpConfig();
  const entries = Object.entries(config.mcpServers || {});
  const running = [];

  for (const [name, serverConfig] of entries) {
    const client = new McpStdioClientReal(name, serverConfig);
    try {
      await client.start();
      const tools = await client.listTools();
      running.push({ name, client, tools });
    } catch (error) {
      running.push({
        name,
        client,
        tools: [],
        error: error?.message || String(error),
      });
    }
  }
  mcpServers = running.map((entry) => ({
    name: entry.name,
    client: entry.client,
    tools: entry.tools || [],
    error: entry.error || "",
    command: String(config.mcpServers?.[entry.name]?.command || ""),
  }));
}

async function startMcpBridgeServer() {
  mcpBridgeState = "starting";
  mcpBridgeError = "";
  const http = require("node:http");
  const server = http.createServer(async (req, res) => {
    if (req.method !== "POST") {
      res.writeHead(405).end();
      return;
    }
    let body = "";
    req.on("data", (chunk) => {
      body += chunk;
      if (body.length > 1024 * 1024) {
        req.destroy();
      }
    });
    req.on("end", async () => {
      let parsed = null;
      try {
        parsed = JSON.parse(body || "{}");
      } catch {
        parsed = null;
      }
      const reply = await handleMcpBridgeRequest(parsed);
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify(reply));
    });
  });
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      mcpBridgePort = typeof address === "object" && address ? address.port : 0;
      resolve();
    });
  });
  mcpBridgeServer = server;
  mcpBridgeState = "running";

  // Publish the bridge endpoint so the Python execution environment can find it.
  try {
    fsSync.writeFileSync(
      path.join(os.homedir(), ".nexus", "mcp_bridge.json"),
      JSON.stringify({ port: mcpBridgePort, pid: process.pid }),
      "utf8"
    );
  } catch {
    // non-fatal: python helpers will report the missing file clearly
  }
}

async function handleMcpBridgeRequest(parsed) {
  if (!parsed || typeof parsed !== "object") {
    return { ok: false, error: "bad request" };
  }

  const serverName = typeof parsed.server === "string" ? parsed.server : "";
  const toolName = typeof parsed.tool === "string" ? parsed.tool : "";
  const argumentsObj = parsed.arguments && typeof parsed.arguments === "object" ? parsed.arguments : {};

  if (parsed.method === "list") {
    const result = {};
    for (const entry of mcpServers) {
      result[entry.name] = {
        status: entry.error ? "error" : entry.client ? "running" : "stopped",
        error: entry.error || "",
        tools: entry.tools.map((t) => t.name),
      };
    }
    return { ok: true, servers: result };
  }

  if (!serverName) {
    return { ok: false, error: "missing server" };
  }
  const serverEntry = mcpServers.find((entry) => entry.name === serverName);
  if (!serverEntry) {
    return { ok: false, error: `unknown MCP server "${serverName}"` };
  }
  if (!serverEntry.client) {
    return { ok: false, error: serverEntry.error || `MCP server "${serverName}" not running` };
  }

  try {
    const result = await serverEntry.client.callTool(toolName, argumentsObj);
    if (result?.isError) {
      const text = extractMcpResultText(result);
      return { ok: false, isError: true, result: result, text: text };
    }
    return { ok: true, result: result, text: extractMcpResultText(result) };
  } catch (error) {
    return { ok: false, error: error?.message || String(error) };
  }
}

function extractMcpResultText(result) {
  if (result && typeof result === "object" && Array.isArray(result.content)) {
    const parts = [];
    for (const item of result.content) {
      if (item && typeof item.text === "string") {
        parts.push(item.text);
      }
    }
    return parts.join("\n");
  }
  try {
    return JSON.stringify(result);
  } catch {
    return String(result);
  }
}

function buildMcpDescriptionLine(toolName, tool, serverName) {
  const schema = tool.inputSchema || {};
  const props = schema.properties && typeof schema.properties === "object" ? Object.keys(schema.properties) : [];
  const params = props.length > 0 ? props.join(", ") : "...";
  const required = Array.isArray(schema.required) ? schema.required : [];
  const requiredMark = required.length > 0 ? ` (required: ${required.join(", ")})` : "";
  const schemaHint = JSON.stringify(schema).slice(0, 240);
  return `mcp_call(server="${serverName}", tool="${tool.name}", args={${params}}) -> dict: MCP tool "${toolName}" from server "${serverName}".${tool.description ? ` ${tool.description}` : ""}${requiredMark} Accepts JSON args matching the inputSchema. Schema: ${schemaHint}`;
}

async function refreshMcpDescriptions() {
  mcpDescriptions = {};
  for (const entry of mcpServers) {
    if (!entry.client || entry.error) {
      continue;
    }
    for (const tool of entry.tools) {
      mcpDescriptions[`mcp:[${entry.name}] ${tool.name}`] = buildMcpDescriptionLine(
        `${entry.name}_${tool.name}`,
        tool,
        entry.name
      );
    }
  }
}

async function stopMcpServers() {
  for (const entry of mcpServers) {
    if (entry.client) {
      try {
        await entry.client.close();
      } catch {
        // ignore
      }
    }
  }
  mcpServers = [];
}

async function initMcp() {
  try {
    await startMcpServers();
  } catch (error) {
    mcpBridgeError = error?.message || String(error);
  }
  try {
    await refreshMcpDescriptions();
  } catch (error) {
    mcpBridgeError = (mcpBridgeError ? mcpBridgeError + "; " : "") + (error?.message || String(error));
  }
  try {
    await startMcpBridgeServer();
  } catch (error) {
    mcpBridgeState = "error";
    mcpBridgeError = (mcpBridgeError ? mcpBridgeError + "; " : "") + (error?.message || String(error));
  }
  // Refresh the system message so freshly-discovered MCP tools show up for
  // the current chat (and any new one).
  if (systemPromptText) {
    try {
      systemPromptText = buildSystemPromptFromDescriptions(toolDescriptions, {
        modelId: selectedModel,
        contextLeftPercent: getContextLeftPercent(selectedModel),
      });
      ensureSystemMessageAtTop();
    } catch {
      // non-fatal: keep the previous prompt if a rebuild fails
    }
  }

  if (mcpBridgeReadyResolve) {
    mcpBridgeReadyResolve();
    mcpBridgeReadyResolve = null;
  }
}

async function ensureMcpBridgeReady() {
  if (mcpBridgeState === "running" || mcpBridgeState === "error") {
    return;
  }
  if (!mcpBridgeReadyPromise) {
    mcpBridgeReadyPromise = new Promise((resolve) => {
      mcpBridgeReadyResolve = resolve;
    });
  }
  await mcpBridgeReadyPromise;
}

// Snippet entry point for the system prompt: mcpCallFromBridge used by python helpers
function getMcpBridgePort() {
  return mcpBridgePort;
}

function getMcpStatusText() {
  if (mcpServers.length === 0) {
    return "no MCP servers configured";
  }
  const parts = [];
  for (const entry of mcpServers) {
    const status = entry.error ? `error (${entry.error})` : entry.client ? `running (${entry.tools.length} tools)` : "stopped";
    parts.push(`${entry.name}: ${status}`);
  }
  return parts.join("; ");
}

async function ensureSystemPromptReady(forceReload = false) {
  if (systemPromptText && !forceReload) {
    return;
  }

  if (!forceReload && systemPromptLoadPromise) {
    await systemPromptLoadPromise;
    return;
  }

  systemPromptLoadPromise = (async () => {
    toolDescriptions = await loadToolDescriptionsFromPython();
    systemPromptText = buildSystemPromptFromDescriptions(toolDescriptions, {
      modelId: selectedModel,
      contextLeftPercent: getContextLeftPercent(selectedModel),
    });
  })();

  await systemPromptLoadPromise;
}

function ensureSystemMessageAtTop(modelId = selectedModel) {
  const runtimeModelId = typeof modelId === "string" ? modelId : selectedModel;
  systemPromptText = buildSystemPromptFromDescriptions(toolDescriptions, {
    modelId: runtimeModelId,
    contextLeftPercent: getContextLeftPercent(runtimeModelId),
  });

  if (messages.length === 0) {
    messages.push({ role: "system", content: systemPromptText, hidden: true });
    return;
  }

  if (messages[0]?.role !== "system") {
    messages.unshift({ role: "system", content: systemPromptText, hidden: true });
    return;
  }

  messages[0] = { ...messages[0], role: "system", content: systemPromptText, hidden: true };
}

function resetMessagesToSystemPrompt() {
  messages.length = 0;
  printedMessageCount = 0;
  lastRenderedChatRole = null;
  forceTranscriptReplay = true;
  ensureSystemMessageAtTop();
  syncImagePasteCounter();
  scrollChatToBottom();
}

async function rewriteSessionWithCurrentMessages() {
  if (!shouldPersistSessionHistory()) {
    sessionPersistenceInitialized = false;
    return false;
  }

  await ensureSessionFileReady();
  const lines = messages
    .filter((entry) => {
      if (entry?.ephemeral === true) {
        return false;
      }
      const role = typeof entry?.role === "string" ? entry.role : "";
      return (
        role === "system" ||
        role === "user" ||
        role === "assistant" ||
        role === "tool" ||
        role === "error"
      );
    })
    .map((entry) => {
      const payload = {
        role: entry.role,
        content:
          typeof entry.content === "string"
            ? entry.content.replace(/\r\n/g, "\n").replace(/\r/g, "\n")
            : String(entry.content ?? ""),
      };
      if (typeof selectedModel === "string" && selectedModel.trim().length > 0) {
        payload.sessionModel = selectedModel.trim();
      }
      payload.sessionWorkspace = WORKSPACE_ROOT;
      payload.sessionReasoningByModel = getSessionReasoningConfig();
      payload.excludeFromRequest = entry?.excludeFromRequest === true;
      if (Array.isArray(entry?.reasoningDetails) && entry.reasoningDetails.length > 0) {
        payload.reasoning_details = entry.reasoningDetails;
      }
      if (typeof entry?.name === "string") {
        payload.name = entry.name;
      }
      if (typeof entry?.toolCallId === "string") {
        payload.toolCallId = entry.toolCallId;
      }
      if (typeof entry?.toolInput === "string") {
        payload.toolInput = entry.toolInput;
      }
      if (typeof entry?.toolCode === "string") {
        payload.toolCode = entry.toolCode;
      }
      if (typeof entry?.toolOk === "boolean") {
        payload.toolOk = entry.toolOk;
      }
      if (entry?.hidden === true) {
        payload.hidden = true;
      }
      return JSON.stringify(payload);
    })
    .join("\n");

  try {
    await fs.writeFile(sessionFilePath, lines.length > 0 ? `${lines}\n` : "", "utf8");
    sessionPersistenceInitialized = lines.length > 0;
    return true;
  } catch {
    return false;
  }
}

function cleanupTerminal(options = {}) {
  const clearScreen = options?.clearScreen === true;
  if (cleanedUp) {
    return;
  }

  cleanedUp = true;
  if (flushTimer) {
    clearTimeout(flushTimer);
    flushTimer = null;
  }
  if (thinkingAnimationTimer) {
    clearInterval(thinkingAnimationTimer);
    thinkingAnimationTimer = null;
  }
  if (shineAnimationTimer) {
    clearInterval(shineAnimationTimer);
    shineAnimationTimer = null;
  }
  if (spinnerAnimationTimer) {
    clearInterval(spinnerAnimationTimer);
    spinnerAnimationTimer = null;
  }
  if (answerRevealTimer) {
    clearInterval(answerRevealTimer);
    answerRevealTimer = null;
  }
  if (mcpBridgeServer) {
    try {
      mcpBridgeServer.close();
    } catch {
      // ignore
    }
    mcpBridgeServer = null;
  }
  clearMouseSelectionTimer();
  mouseSelectionMode = false;

  if (process.stdin.isTTY) {
    process.stdin.setRawMode(false);
  }

  if (bracketedPasteModeEnabled) {
    process.stdout.write(DISABLE_BRACKETED_PASTE);
    bracketedPasteModeEnabled = false;
  }

  if (mouseTrackingEnabled) {
    process.stdout.write(DISABLE_MOUSE_TRACKING);
    mouseTrackingEnabled = false;
  }

  if (altScreenActive) {
    process.stdout.write(EXIT_ALT_SCREEN);
    altScreenActive = false;
  }

  process.stdout.write("\u001b[r");
  if (clearScreen && process.stdout.isTTY) {
    // Clear visible content and scrollback, then place cursor at top-left.
    process.stdout.write("\u001b[2J\u001b[3J\u001b[H");
  }
  process.stdout.write(SHOW_CURSOR);
  if (APPEND_CHAT_TO_SCROLLBACK) {
    process.stdout.write("\r\n");
  }
}

function setMouseTrackingEnabled(enabled) {
  if (APPEND_CHAT_TO_SCROLLBACK) {
    if (mouseTrackingEnabled) {
      process.stdout.write(DISABLE_MOUSE_TRACKING);
      mouseTrackingEnabled = false;
    }
    mouseSequenceRemainder = "";
    return;
  }

  if (!process.stdout.isTTY) {
    mouseTrackingEnabled = false;
    mouseSequenceRemainder = "";
    return;
  }

  if (enabled) {
    if (!mouseTrackingEnabled) {
      process.stdout.write(ENABLE_MOUSE_TRACKING);
      mouseTrackingEnabled = true;
    }
    return;
  }

  if (mouseTrackingEnabled) {
    process.stdout.write(DISABLE_MOUSE_TRACKING);
    mouseTrackingEnabled = false;
  }
  mouseSequenceRemainder = "";
}

function clearMouseSelectionTimer() {
  if (!mouseSelectionTimer) {
    return;
  }
  clearTimeout(mouseSelectionTimer);
  mouseSelectionTimer = null;
}

function exitMouseSelectionMode() {
  if (!mouseSelectionMode) {
    return;
  }
  mouseSelectionMode = false;
  mouseSelectionStartedAt = 0;
  clearMouseSelectionTimer();
  if (APP_MOUSE_TRACKING_ENABLED && activeBuffer === "main") {
    setMouseTrackingEnabled(true);
  }
}

function enterMouseSelectionMode() {
  if (APPEND_CHAT_TO_SCROLLBACK || activeBuffer !== "main") {
    return;
  }

  mouseSelectionMode = true;
  mouseSelectionStartedAt = Date.now();
  clearMouseSelectionTimer();
  setMouseTrackingEnabled(false);
  mouseSelectionTimer = setTimeout(() => {
    mouseSelectionTimer = null;
    exitMouseSelectionMode();
  }, MOUSE_SELECTION_REENABLE_MS);
}

function enterAltScreenIfNeeded() {
  if (!process.stdout.isTTY || altScreenActive) {
    return;
  }

  process.stdout.write(ENTER_ALT_SCREEN);
  altScreenActive = true;
  hasInitializedScreen = false;
  forceFullClearOnNextRender = true;
}

function exitAltScreenIfNeeded() {
  if (!altScreenActive) {
    return;
  }

  process.stdout.write(EXIT_ALT_SCREEN);
  altScreenActive = false;
  hasInitializedScreen = false;
  forceFullClearOnNextRender = true;
}

function normalizeLlmRequestTimeoutMs(value) {
  const raw = Number(value);
  if (!Number.isFinite(raw)) {
    return DEFAULT_LLM_REQUEST_TIMEOUT_MS;
  }
  const rounded = Math.round(raw);
  return Math.max(MIN_LLM_REQUEST_TIMEOUT_MS, Math.min(MAX_LLM_REQUEST_TIMEOUT_MS, rounded));
}

function getLlmRequestTimeoutMs() {
  return normalizeLlmRequestTimeoutMs(nexusConfig?.llm_request_timeout_ms);
}

async function ensureNexusConfigFileReady() {
  const initialConfig = {
    version: 1,
    createdAt: new Date().toISOString(),
    provider: DEFAULT_PROVIDERS[0].name,
    llm_request_timeout_ms: DEFAULT_LLM_REQUEST_TIMEOUT_MS,
  };
  const content = `${JSON.stringify(initialConfig, null, 2)}\n`;
  try {
    await fs.writeFile(NEXUS_CONFIG_FILE, content, {
      encoding: "utf8",
      flag: "wx",
    });
  } catch (error) {
    if (error?.code !== "EEXIST") {
      throw error;
    }
  }
}

function resetLlmClient() {
  openRouterClient = null;
  openRouterClientKey = "";
}

function normalizeProviderModel(value) {
  const model = typeof value === "string" ? value.trim() : "";
  return model;
}

function getProviderByName(name) {
  const key = typeof name === "string" ? name.trim() : "";
  if (!key) {
    return null;
  }

  const found = providers.find((entry) => entry?.name === key);
  return found || null;
}

function getActiveProvider() {
  const providerFromState = getProviderByName(selectedProviderName);
  if (providerFromState) {
    return providerFromState;
  }

  if (providers.length > 0) {
    return providers[0];
  }

  return null;
}

function syncSelectedModelFromActiveProvider() {
  const activeProvider = getActiveProvider();
  if (!activeProvider) {
    return;
  }
  selectedModel = normalizeProviderModel(activeProvider.model);
}

async function saveNexusConfig() {
  await ensureSessionFileReady();
  let current = {};
  try {
    const raw = await fs.readFile(NEXUS_CONFIG_FILE, "utf8");
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      current = parsed;
    }
  } catch {
    current = {};
  }

  const next = {
    ...current,
    ...nexusConfig,
    provider: selectedProviderName || DEFAULT_PROVIDERS[0].name,
    llm_request_timeout_ms: normalizeLlmRequestTimeoutMs(
      nexusConfig?.llm_request_timeout_ms ?? current?.llm_request_timeout_ms
    ),
  };
  nexusConfig = next;
  await fs.writeFile(NEXUS_CONFIG_FILE, `${JSON.stringify(next, null, 2)}\n`, "utf8");
}

async function loadNexusConfig() {
  await ensureSessionFileReady();
  let parsed = {};
  try {
    const raw = await fs.readFile(NEXUS_CONFIG_FILE, "utf8");
    const data = JSON.parse(raw);
    if (data && typeof data === "object" && !Array.isArray(data)) {
      parsed = data;
    }
  } catch {
    parsed = {};
  }

  nexusConfig = {
    ...parsed,
    llm_request_timeout_ms: normalizeLlmRequestTimeoutMs(parsed?.llm_request_timeout_ms),
  };
  const providerName = typeof parsed.provider === "string" ? parsed.provider.trim() : "";
  if (providerName) {
    selectedProviderName = providerName;
  }
}

async function ensureSelectedProviderIsValid() {
  const existing = getProviderByName(selectedProviderName);
  if (existing) {
    syncSelectedModelFromActiveProvider();
    return;
  }

  if (providers.length > 0) {
    selectedProviderName = providers[0].name;
  } else {
    selectedProviderName = DEFAULT_PROVIDERS[0].name;
  }

  nexusConfig.provider = selectedProviderName;
  await saveNexusConfig().catch(() => {});
  resetLlmClient();
  syncSelectedModelFromActiveProvider();
}

async function selectProviderByIndex(index) {
  if (index < 0 || index >= providers.length) {
    return false;
  }

  const next = providers[index];
  const nextName = next?.name || "";
  if (!nextName) {
    return false;
  }

  selectedProviderName = nextName;
  nexusConfig.provider = nextName;
  await saveNexusConfig();
  resetLlmClient();
  syncSelectedModelFromActiveProvider();
  return true;
}

function normalizeProviderEntry(raw) {
  const name = typeof raw?.name === "string" ? raw.name : "";
  const base_url = typeof raw?.base_url === "string" ? raw.base_url : "";
  const api_key = typeof raw?.api_key === "string" ? raw.api_key : "";
  const model = normalizeProviderModel(raw?.model);
  return {
    name: name.trim(),
    base_url: base_url.trim(),
    api_key,
    model,
  };
}

function normalizeProvidersList(raw) {
  if (!Array.isArray(raw)) {
    return [];
  }

  return raw
    .map((entry) => normalizeProviderEntry(entry))
    .filter(
      (entry) =>
        entry.name.length > 0 ||
        entry.base_url.length > 0 ||
        entry.api_key.length > 0 ||
        entry.model.length > 0
    );
}

async function ensureProvidersFileReady() {
  const content = `${JSON.stringify(DEFAULT_PROVIDERS, null, 2)}\n`;
  try {
    await fs.writeFile(NEXUS_PROVIDERS_FILE, content, {
      encoding: "utf8",
      flag: "wx",
    });
  } catch (error) {
    if (error?.code !== "EEXIST") {
      throw error;
    }
  }
}

async function saveProvidersToFile() {
  await ensureSessionFileReady();
  const normalized = normalizeProvidersList(providers);
  providers = normalized;
  updateProvidersSelectionState();
  const content = `${JSON.stringify(normalized, null, 2)}\n`;
  await fs.writeFile(NEXUS_PROVIDERS_FILE, content, "utf8");
}

async function loadProvidersFromFile() {
  if (isProvidersLoading) {
    return;
  }

  isProvidersLoading = true;
  providersLoadError = "";
  if (activeBuffer === "providers") {
    markDirty();
    renderFrame(true);
  }

  try {
    await ensureSessionFileReady();
    const raw = await fs.readFile(NEXUS_PROVIDERS_FILE, "utf8");
    const parsed = JSON.parse(raw);
    providers = normalizeProvidersList(parsed);
    await ensureSelectedProviderIsValid();
    const selectedIndex = providers.findIndex((entry) => entry?.name === selectedProviderName);
    providersSelected = selectedIndex >= 0 ? selectedIndex : 0;
    updateProvidersSelectionState();
    syncSelectedModelFromActiveProvider();
  } catch (_error) {
    providersLoadError = "Could not load providers";
  } finally {
    isProvidersLoading = false;
    markDirty();
    renderFrame(true);
  }
}

function ensureSessionFileReady() {
  if (!sessionInitPromise) {
    sessionInitPromise = (async () => {
      await fs.mkdir(SESSIONS_DIR, { recursive: true });
      await ensureNexusConfigFileReady();
      await ensureProvidersFileReady();
    })();
  }

  return sessionInitPromise;
}

function appendHistoryEntry(role, content, extra = null) {
  if (!shouldPersistSessionHistory()) {
    return;
  }

  const normalizedContent =
    typeof content === "string"
      ? content.replace(/\r\n/g, "\n").replace(/\r/g, "\n")
      : String(content ?? "");
  const payload = { role, content: normalizedContent };
  if (typeof selectedModel === "string" && selectedModel.trim().length > 0) {
    payload.sessionModel = selectedModel.trim();
  }
  payload.sessionWorkspace = WORKSPACE_ROOT;
  payload.sessionReasoningByModel = getSessionReasoningConfig();
  payload.excludeFromRequest = false;
  if (extra && typeof extra === "object") {
    if (Array.isArray(extra.reasoningDetails) && extra.reasoningDetails.length > 0) {
      payload.reasoning_details = extra.reasoningDetails;
    }
    if (typeof extra.name === "string") {
      payload.name = extra.name;
    }
    if (typeof extra.toolCallId === "string") {
      payload.toolCallId = extra.toolCallId;
    }
    if (typeof extra.toolInput === "string") {
      payload.toolInput = extra.toolInput;
    }
    if (typeof extra.toolCode === "string") {
      payload.toolCode = extra.toolCode;
    }
    if (extra.hidden === true) {
      payload.hidden = true;
    }
    payload.excludeFromRequest = extra.excludeFromRequest === true;
    if (typeof extra.toolOk === "boolean") {
      payload.toolOk = extra.toolOk;
    }
  }
  const line = JSON.stringify(payload) + "\n";
  const targetGeneration = chatGeneration;
  const targetSessionPath = sessionFilePath;

  sessionWriteChain = sessionWriteChain
    .then(async () => {
      if (targetGeneration !== chatGeneration || targetSessionPath !== sessionFilePath) {
        return;
      }

      if (!shouldPersistSessionHistory()) {
        sessionPersistenceInitialized = false;
        return;
      }

      if (!sessionPersistenceInitialized) {
        await rewriteSessionWithCurrentMessages();
        return;
      }

      await ensureSessionFileReady();
      await fs.appendFile(targetSessionPath, line, "utf8");
    })
    .catch(() => {});
}

function getOpenRouterClient() {
  if (!OpenAI) {
    return null;
  }

  const activeProvider = getActiveProvider();
  const baseURL =
    (typeof activeProvider?.base_url === "string" && activeProvider.base_url.trim()) ||
    OPENROUTER_BASE_URL;
  const apiKey =
    (typeof activeProvider?.api_key === "string" && activeProvider.api_key.trim()) || "";
  if (!apiKey) {
    return null;
  }

  const clientKey = `${baseURL}|${apiKey}`;
  if (openRouterClient && openRouterClientKey === clientKey) {
    return openRouterClient;
  }

  const defaultHeaders = {};
  if (typeof baseURL === "string" && baseURL.toLowerCase().includes("openrouter.ai")) {
    if (process.env.OPENROUTER_HTTP_REFERER) {
      defaultHeaders["HTTP-Referer"] = process.env.OPENROUTER_HTTP_REFERER;
    }
    if (process.env.OPENROUTER_TITLE) {
      defaultHeaders["X-OpenRouter-Title"] = process.env.OPENROUTER_TITLE;
    }
  }

  openRouterClient = new OpenAI({
    baseURL,
    apiKey,
    ...(Object.keys(defaultHeaders).length > 0 ? { defaultHeaders } : {}),
  });
  openRouterClientKey = clientKey;

  return openRouterClient;
}

// Rough token estimate: ~4 chars per token is the common heuristic. Used only
// for compaction thresholds, not exact billing.
function estimateTokensForText(text) {
  const source = String(text ?? "");
  return Math.max(1, Math.ceil(source.length / 4));
}

function estimateMessageTokens(message) {
  const role = typeof message?.role === "string" ? message.role : "";
  const content = typeof message?.content === "string" ? message.content : "";
  let tokens = estimateTokensForText(content) + 4; // role + separators
  if (Array.isArray(message?.reasoning_details)) {
    for (const part of message.reasoning_details) {
      if (part && typeof part === "object") {
        tokens += estimateTokensForText(String(part?.text || ""));
      } else if (typeof part === "string") {
        tokens += estimateTokensForText(part);
      }
    }
  }
  return tokens;
}

function estimateRequestTokens(messagesForRequest) {
  return messagesForRequest.reduce((sum, message) => sum + estimateMessageTokens(message), 0);
}

function estimateMessagesInChatTokens(entries) {
  return entries.reduce((sum, entry) => sum + estimateMessageTokens(entry), 0);
}

function isCompactionSummaryEntry(entry) {
  return (
    entry?.role === "user" &&
    typeof entry?.content === "string" &&
    entry.content.startsWith(COMPACTION_SUMMARY_PREFIX)
  );
}

function getCompactionThreshold() {
  const configLimit = Number(nexusConfig?.model_auto_compact_token_limit);
  // Fall back to a sane default (128k) when the model's context length is
  // unknown, so a missing entry can never collapse the threshold to ~1 token
  // and force compaction on every single request.
  const rawWindow = getModelContextLength(selectedModel);
  const windowLength = Number.isFinite(rawWindow) && rawWindow > 0 ? rawWindow : 128000;
  const hardCap = Math.max(1, Math.floor(windowLength * COMPACTION_DEFAULT_FRACTION));
  if (Number.isFinite(configLimit) && configLimit > 0) {
    return Math.min(configLimit, hardCap);
  }
  return hardCap;
}

function getToolOutputTokenLimit() {
  const configLimit = Number(nexusConfig?.tool_output_token_limit);
  if (Number.isFinite(configLimit) && configLimit > 0) {
    return configLimit;
  }
  return 16000;
}

async function runCompaction(customInstruction = "") {
  // Codex local path: ask the model to summarize the conversation into a
  // single user-role "_summary" message, then keep only the most recent user
  // messages (default 20k tokens) below it. Older assistant/tool turns are
  // dropped from the in-memory messages array.
  const client = getOpenRouterClient();
  if (!client) {
    return { ok: false, error: "LLM provider is not configured." };
  }
  const resolvedModel = selectedModel;
  if (!resolvedModel || String(resolvedModel).trim().length === 0) {
    return { ok: false, error: "Model is not configured. Use /set model <name>." };
  }

  ensureSystemMessageAtTop(resolvedModel);
  const requestMessages = buildOpenRouterMessagesFromHistory(resolvedModel);
  if (requestMessages.length === 0) {
    return { ok: false, error: "Nothing to compact." };
  }

  const contextLength = getModelContextLength(resolvedModel);
  const maxSummaryChars = Math.max(2000, Math.floor(contextLength * 0.02));
  const instruction =
    typeof customInstruction === "string" && customInstruction.trim().length > 0
      ? customInstruction.trim()
      : COMPACTION_DEFAULT_CUSTOM_INSTRUCTION;

  const summaryPrompt = [
    `You are compacting a long coding session into a handoff summary for another AI engineer.`,
    ``,
    `INSTRUCTIONS:`,
    instruction,
    ``,
    `RULES:`,
    `- Write the summary in plain text (no markdown fences, no code blocks).`,
    `- Keep it under ${maxSummaryChars} characters.`,
    `- Do not mention this prompt.`,
    ``,
    `CONVERSATION TO COMPACT:`,
    ...requestMessages
      .filter((message) => message.role !== "system")
      .map((message) => {
        const roleLabel = message.role === "tool" || message.role === "tool_result" ? "tool" : message.role;
        const content = typeof message?.content === "string" ? message.content : "";
        if (Array.isArray(content)) {
          return `${roleLabel}: ${content.map((part) => (typeof part === "object" && typeof part?.text === "string" ? part.text : "")).join(" ")}`;
        }
        return `${roleLabel}: ${content}`;
      })
      .join(String.fromCharCode(10, 10))
      .slice(-Math.max(2000, Math.floor(contextLength * 0.6))),
  ].join(String.fromCharCode(10));

  let summaryText = "";
  try {
    const completion = await client.chat.completions.create({
      model: resolvedModel,
      messages: [...requestMessages.filter((message) => message.role === "system"), { role: "user", content: summaryPrompt }],
    });
    const content = completion?.choices?.[0]?.message?.content;
    summaryText = typeof content === "string" ? content.trim() : "";
  } catch (error) {
    return { ok: false, error: `Compaction failed: ${getOpenRouterErrorMessage(error)}` };
  }

  if (summaryText.length === 0) {
    return { ok: false, error: "Compaction failed: model returned an empty summary." };
  }

  // Replace the conversation with: system + [freshest summary] + the most
  // recent tail of the conversation that fits the recent-token budget.
  // Everything older (assistant replies, tool results, read file contents)
  // is dropped, matching Codex's local-path compaction tradeoff.
  const keptTail = [];
  const recentBudget = COMPACTION_RECENT_USER_TOKENS;
  let recentTokens = 0;
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const entry = messages[i];
    if (!entry || entry.ephemeral === true) {
      continue;
    }
    if (isCompactionSummaryEntry(entry)) {
      continue;
    }
    const tokens = estimateMessageTokens(entry);
    if (recentTokens + tokens > recentBudget) {
      break;
    }
    recentTokens += tokens;
    keptTail.unshift(entry);
  }

  const systemEntries = [];
  for (const entry of messages) {
    if (entry && entry.ephemeral !== true && entry.role === "system") {
      systemEntries.push(entry);
    }
  }

  messages.length = 0;
  messages.push(
    ...systemEntries,
    { role: "user", content: COMPACTION_SUMMARY_PREFIX + "\n" + summaryText },
    ...keptTail.filter((entry) => !isCompactionSummaryEntry(entry))
  );

  printedMessageCount = Math.min(printedMessageCount, messages.length);
  forceTranscriptReplay = true;
  await rewriteSessionWithCurrentMessages().catch(() => {});
  markDirty();
  renderFrame(true);
  return { ok: true, summary: summaryText, keptRecentUserMessages: keptTail.length };
}

async function maybeCompactBeforeTurn() {
  if (APPEND_CHAT_TO_SCROLLBACK) {
    return { ran: false };
  }
  const currentTokens = estimateMessagesInChatTokens(messages);
  const threshold = getCompactionThreshold();
  if (currentTokens <= threshold) {
    return { ran: false };
  }
  const result = await runCompaction();
  return { ran: true, result };
}

function buildOpenRouterMessagesFromHistory(modelId = selectedModel) {
  ensureSystemMessageAtTop(modelId);
  const includeReasoningDetails = getReasoningEnabledForModel(modelId);
  const buildUserMultimodalContent = (text) => {
    const source = String(text ?? "");
    if (!source.includes("[Image #")) {
      return source;
    }

    const parts = [];
    const re = /\[Image #(\d+)\]/g;
    let cursor = 0;
    let match = null;
    let hasImagePart = false;

    while ((match = re.exec(source)) !== null) {
      const tokenText = match[0];
      const tokenNumber = Number(match[1]);
      const before = source.slice(cursor, match.index);
      if (before.length > 0) {
        parts.push({ type: "text", text: before });
      }

      const imageUrl = imageTokenPayloads.get(tokenNumber);
      if (typeof imageUrl === "string" && imageUrl.length > 0) {
        hasImagePart = true;
        parts.push({
          type: "image_url",
          image_url: { url: imageUrl },
        });
      } else {
        parts.push({ type: "text", text: tokenText });
      }

      cursor = match.index + tokenText.length;
    }

    const tail = source.slice(cursor);
    if (tail.length > 0) {
      parts.push({ type: "text", text: tail });
    }

    return hasImagePart ? parts : source;
  };

  const requestMessages = [];
  for (const entry of messages) {
    if (entry && entry.ephemeral === true) {
      continue;
    }
    if (entry && entry.excludeFromRequest === true) {
      continue;
    }

    const role = typeof entry?.role === "string" ? entry.role : "";
    if (
      role !== "system" &&
      role !== "user" &&
      role !== "assistant" &&
      role !== "tool" &&
      role !== "tool_result"
    ) {
      continue;
    }

    const content = typeof entry?.content === "string" ? entry.content : "";
    if (!content.trim()) {
      continue;
    }

    if (role === "tool_result" || role === "tool") {
      const toolName =
        typeof entry?.name === "string" && entry.name.trim().length > 0
          ? entry.name.trim()
          : "code_execution";
      const toolContent = content.trim().length > 0 ? content : "(no output)";
      // Programmatic tool-calling flow uses plain text/code, not API-native tool_call objects.
      // Feed tool outcomes back as user context so the model reliably produces a final answer.
      requestMessages.push({
        role: "user",
        content: `[tool ${toolName} result]\n${toolContent}`,
      });
      continue;
    }

    if (role === "user") {
      requestMessages.push({ role, content: buildUserMultimodalContent(content) });
      continue;
    }

    if (role === "assistant") {
      const messagePayload = { role, content };
      const details = normalizeReasoningDetails(entry?.reasoningDetails);
      if (includeReasoningDetails && details) {
        messagePayload.reasoning_details = details;
      }
      requestMessages.push(messagePayload);
      continue;
    }

    requestMessages.push({ role, content });
  }

  return requestMessages;
}

function extractAssistantText(content) {
  if (typeof content === "string") {
    return content;
  }

  if (!Array.isArray(content)) {
    return "";
  }

  const lines = content
    .map((part) => {
      if (typeof part === "string") {
        return part;
      }
      if (typeof part?.text === "string") {
        return part.text;
      }
      if (typeof part?.content === "string") {
        return part.content;
      }
      return "";
    })
    .filter((part) => part.length > 0);

  return lines.join("\n");
}

function extractThinkBlocksFromText(text) {
  const source = typeof text === "string" ? text : String(text ?? "");
  if (!source.includes("<think")) {
    return { content: source, reasoningText: "" };
  }

  const reasoningChunks = [];
  const content = source.replace(/<think>([\s\S]*?)<\/think>/gi, (_match, inner) => {
    const chunk = String(inner ?? "").trim();
    if (chunk.length > 0) {
      reasoningChunks.push(chunk);
    }
    return "";
  });

  const cleanedContent = content
    .replace(/\n{3,}/g, "\n\n")
    .trim();
  const reasoningText = reasoningChunks.join("\n\n").trim();
  return { content: cleanedContent, reasoningText };
}

function extractAssistantPayloadFromCompletion(completion, options = {}) {
  const allowReasoningTextFallback = options?.allowReasoningTextFallback !== false;
  const choice = completion?.choices?.[0] || {};
  const message = choice?.message || {};
  let reasoningDetails =
    normalizeReasoningDetails(message?.reasoning_details) ||
    normalizeReasoningDetails(choice?.reasoning_details) ||
    normalizeReasoningDetails(completion?.reasoning_details) ||
    // OpenRouter returns thinking traces as message.reasoning: an array of
    // objects, each { type: "reasoning.text", text }, or part-array variants.
    normalizeReasoningDetails(message?.reasoning ? message.reasoning : null) ||
    normalizeReasoningDetails(choice?.reasoning ? choice.reasoning : null) ||
    normalizeReasoningDetails(completion?.reasoning ? completion.reasoning : null);

  const providerReasoningText =
    (typeof message?.reasoning_content === "string" && message.reasoning_content.trim()) ||
    (typeof choice?.reasoning_content === "string" && choice.reasoning_content.trim()) ||
    (typeof completion?.reasoning_content === "string" && completion.reasoning_content.trim()) ||
    "";
  if (!reasoningDetails && providerReasoningText) {
    reasoningDetails = [{ type: "reasoning.text", text: providerReasoningText, format: "unknown" }];
  }

  let text = extractAssistantText(message?.content);
  const thinkParsed = extractThinkBlocksFromText(text);
  if (thinkParsed.reasoningText) {
    const thinkDetails = [{ type: "reasoning.text", text: thinkParsed.reasoningText, format: "unknown" }];
    reasoningDetails = reasoningDetails ? [...reasoningDetails, ...thinkDetails] : thinkDetails;
    text = thinkParsed.content;
  }
  if (!text.trim() && typeof message?.refusal === "string" && message.refusal.trim().length > 0) {
    text = message.refusal.trim();
  }
  if (!text.trim() && typeof choice?.text === "string" && choice.text.trim().length > 0) {
    text = choice.text.trim();
  }
  if (allowReasoningTextFallback && !text.trim()) {
    const reasoningPreview = extractReasoningDisplayText(reasoningDetails);
    if (reasoningPreview.trim().length > 0) {
      text = reasoningPreview;
    }
  }

  return { text, reasoningDetails };
}

function appendAssistantMessage(text, options = {}) {
  const content = typeof text === "string" ? text : String(text ?? "");
  const reasoningDetails = normalizeReasoningDetails(options?.reasoningDetails);
  const excludeFromRequest = options?.excludeFromRequest === true;
  const persistHistory = options?.persistHistory !== false;
  const reveal = options?.reveal === true;
  const assistantEntry = { role: "assistant", content };
  if (reasoningDetails) {
    assistantEntry.reasoningDetails = reasoningDetails;
  }
  if (excludeFromRequest) {
    assistantEntry.excludeFromRequest = true;
  }
  messages.push(assistantEntry);
  if (reveal) {
    triggerAnswerReveal(assistantEntry);
  }
  const historyExtra = {};
  if (reasoningDetails) {
    historyExtra.reasoningDetails = reasoningDetails;
  }
  if (excludeFromRequest) {
    historyExtra.excludeFromRequest = true;
  }
  if (persistHistory) {
    appendHistoryEntry("assistant", content, Object.keys(historyExtra).length > 0 ? historyExtra : null);
  }
  syncImagePasteCounter();
  scrollChatToBottom();
  if (!APPEND_CHAT_TO_SCROLLBACK) {
    forceFullClearOnNextRender = true;
  }
  markDirty();
  renderFrame(true);
  scheduleViewportMainRefresh();
  if (APPEND_CHAT_TO_SCROLLBACK) {
    appendTranscriptNow();
    markDirty();
    renderFrame(false);
  }
}

function appendTuiErrorMessage(commandName, reason = "disabled while a task is in progress") {
  const content = `'${commandName}' is ${reason}.`;
  messages.push({ role: "error", content });
  appendHistoryEntry("error", content);
  scrollChatToBottom();
  if (!APPEND_CHAT_TO_SCROLLBACK) {
    forceFullClearOnNextRender = true;
  }
  markDirty();
  renderFrame(true);
  scheduleViewportMainRefresh();
  if (APPEND_CHAT_TO_SCROLLBACK) {
    appendTranscriptNow();
    markDirty();
    renderFrame(false);
  }
}

function hasActiveAnswerReveal() {
  for (const msg of messages) {
    if (msg && typeof msg.revealUntil === "number" && msg.revealUntil > Date.now()) {
      return true;
    }
  }
  return false;
}

function triggerAnswerReveal(entry) {
  if (!entry || entry.ephemeral === true || APPEND_CHAT_TO_SCROLLBACK) {
    return;
  }
  entry.revealUntil = Date.now() + ANSWER_REVEAL_MS;
  if (!answerRevealTimer) {
    answerRevealTimer = setInterval(() => {
      if (!hasActiveAnswerReveal()) {
        clearInterval(answerRevealTimer);
        answerRevealTimer = null;
        // Reveal finished: drop the cache (it may hold a mid-fade frame) and
        // run one final in-place repaint so the message resolves to normal
        // styling without a full clear/redraw.
        cachedChatLines = null;
        answerRevealSettlePending = true;
        forceChatRefreshFlag = true;
        markDirty();
        renderFrame(false);
        return;
      }
      // Repaint the chat block every tick so the fade advances, even though
      // no structural state changed.
      forceChatRefreshFlag = true;
      markDirty();
      renderFrame(false);
    }, ANSWER_REVEAL_TICK_MS);
  }
}

const ANSWER_REVEAL_FADE_FROM = 231; // bright white
const ANSWER_REVEAL_FADE_TO = 243;   // dim gray
const ANSWER_REVEAL_BULLET_FG = "\u001b[96m";

function applyAnswerRevealStyle(lineText, elapsed) {
  // Fade progress 0..1: bright white -> dim gray. Returns null once the fade
  // completes so callers fall back to the normal markdown/code styling.
  const plain = stripAnsiSgr(String(lineText ?? ""));
  if (elapsed >= 1) {
    return null;
  }
  const progress = Math.max(0, Math.min(1, elapsed));
  const colorIndex = Math.round(
    ANSWER_REVEAL_FADE_FROM + (ANSWER_REVEAL_FADE_TO - ANSWER_REVEAL_FADE_FROM) * progress
  );
  const color = `\u001b[38;5;${colorIndex}m`;
  let out = `${color}${plain}${RESET_COLOR}`;
  if (plain.startsWith("\u2022 ")) {
    out = `${ANSWER_REVEAL_BULLET_FG}\u2022${RESET_COLOR} ${color}${plain.slice(2)}${RESET_COLOR}`;
  }
  return out;
}

function createPendingAssistantMessage(generation) {
  if (generation !== chatGeneration) {
    return -1;
  }

  if (APPEND_CHAT_TO_SCROLLBACK) {
    return -1;
  }

  const index = messages.length;
  messages.push({ role: "assistant", content: "thinking...", ephemeral: true });
  pendingAssistantMessageIndex = index;
  scrollChatToBottom();
  forceFullClearOnNextRender = true;
  markDirty();
  renderFrame(true);
  return index;
}

function finalizePendingAssistantMessage(index, text, generation, options = {}) {
  if (generation !== chatGeneration) {
    return;
  }
  pendingAssistantMessageIndex = -1;

  const role = typeof options.role === "string" ? options.role : "assistant";
  const persistHistory =
    typeof options.persistHistory === "boolean"
      ? options.persistHistory
      : (role === "assistant" || role === "tool" || role === "tool_result" || role === "user");
  const rawContent = typeof text === "string" ? text : String(text ?? "");
  const content =
    role === "error" && !rawContent.trimStart().startsWith("■")
      ? `■ ${rawContent}`
      : rawContent;
  const reasoningDetails = role === "assistant" ? normalizeReasoningDetails(options?.reasoningDetails) : null;
  const nextEntry = { role, content };
  if (reasoningDetails) {
    nextEntry.reasoningDetails = reasoningDetails;
  }
  if (index >= 0 && index < messages.length && messages[index]?.role === "assistant") {
    messages[index] = nextEntry;
  } else {
    messages.push(nextEntry);
  }

  if (role === "assistant" && !rawContent.trimStart().startsWith("■")) {
    triggerAnswerReveal(nextEntry);
  }

  if (persistHistory) {
    appendHistoryEntry(role, content, reasoningDetails ? { reasoningDetails } : null);
  }
  syncImagePasteCounter();
  scrollChatToBottom();
  if (!APPEND_CHAT_TO_SCROLLBACK) {
    forceFullClearOnNextRender = true;
  }
  markDirty();
  renderFrame(true);
  scheduleViewportMainRefresh();
  if (APPEND_CHAT_TO_SCROLLBACK) {
    appendTranscriptNow();
    markDirty();
    renderFrame(false);
  }
}

function getOpenRouterErrorMessage(error) {
  if (!error) {
    return "Unknown error";
  }

  const nestedMessage =
    error?.error?.message ||
    error?.response?.data?.error?.message ||
    error?.cause?.message;
  if (typeof nestedMessage === "string" && nestedMessage.trim()) {
    return nestedMessage.trim();
  }

  if (typeof error?.message === "string" && error.message.trim()) {
    return error.message.trim();
  }

  if (typeof error === "string" && error.trim()) {
    return error.trim();
  }

  return "Unknown error";
}

function shouldRetryWithoutReasoning(error) {
  const msg = getOpenRouterErrorMessage(error).toLowerCase();
  if (!msg) {
    return false;
  }

  if (msg.includes("provider returned error")) {
    return true;
  }

  const mentionsReasoning = msg.includes("reasoning");
  const unsupportedHint =
    msg.includes("unsupported") ||
    msg.includes("not supported") ||
    msg.includes("invalid parameter") ||
    msg.includes("unknown parameter");
  return mentionsReasoning && unsupportedHint;
}

function stripReasoningDetailsFromMessages(messagesForRequest) {
  if (!Array.isArray(messagesForRequest)) {
    return [];
  }

  return messagesForRequest.map((msg) => {
    if (!msg || typeof msg !== "object") {
      return msg;
    }
    if (!Object.prototype.hasOwnProperty.call(msg, "reasoning_details")) {
      return msg;
    }
    const { reasoning_details: _ignored, ...rest } = msg;
    return rest;
  });
}

function parseToolArguments(rawArgs) {
  if (!rawArgs) {
    return {};
  }

  if (typeof rawArgs === "object") {
    return rawArgs;
  }

  if (typeof rawArgs !== "string") {
    return {};
  }

  try {
    const parsed = JSON.parse(rawArgs);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function extractAllPythonCodeBlocks(text) {
  if (typeof text !== "string" || text.length === 0) {
    return [];
  }

  const blocks = [];
  const re = /```execute\s*\n([\s\S]*?)```/gi;
  let match = null;
  while ((match = re.exec(text)) !== null) {
    const body = (match[1] || "").trim();
    if (!body) {
      continue;
    }
    blocks.push(body);
  }

  return blocks;
}

function getToolRunLabel(pythonCode) {
  const source = String(pythonCode ?? "");
  const firstLine = source.split("\n").find((ln) => ln.trim().length > 0) || "";
  const snippet = firstLine.trim().slice(0, 48);
  return snippet || "code execution";
}

function isPredefinedToolFunction(name) {
  return typeof name === "string" && Object.prototype.hasOwnProperty.call(toolDescriptions, name);
}

function buildExecutableCodeForToolCall(toolName, toolArgs) {
  if (toolName === "code_execution") {
    const code = typeof toolArgs?.code === "string" ? toolArgs.code : "";
    if (!code.trim()) {
      return { error: "Tool argument error: 'code' must be a non-empty string." };
    }
    return { code, executionName: toolName };
  }

  if (!isPredefinedToolFunction(toolName)) {
    return { error: `Unsupported tool: ${toolName || "(unknown)"}` };
  }

  const argsValue = toolArgs && typeof toolArgs === "object" ? toolArgs : {};
  const argsJson = JSON.stringify(argsValue);
  const generatedCode = [
    "import json",
    `__tool_name = ${JSON.stringify(toolName)}`,
    `__args = json.loads(${JSON.stringify(argsJson)})`,
    "__fn = globals().get(__tool_name)",
    "if __fn is None:",
    "    raise RuntimeError(f\"Unknown predefined tool function: {__tool_name}\")",
    "if isinstance(__args, dict):",
    "    __result = __fn(**__args)",
    "elif isinstance(__args, list):",
    "    __result = __fn(*__args)",
    "else:",
    "    __result = __fn(__args)",
    "print(__result)",
  ].join("\n");

  return { code: generatedCode, executionName: toolName };
}

async function executeCodeWithPythonTool(code) {
  const encodedCode = Buffer.from(String(code ?? ""), "utf8").toString("base64");
  const runner = `
import base64
import asyncio
import io
import json
import textwrap
import traceback
import ast
from contextlib import redirect_stdout
import sys
import tools

MAX_STEPS = ${TOOL_EXEC_MAX_STEPS}
_steps = 0

def tracer(frame, event, arg):
    global _steps
    if event == "call":
        if frame.f_code.co_filename == "<generated>":
            return tracer
        return None
    if event == "line":
        _steps += 1
        if _steps > MAX_STEPS:
            raise RuntimeError("Execution stopped: step limit exceeded")
    return tracer

code = base64.b64decode(sys.argv[1]).decode("utf-8")
scope = {}
if hasattr(tools, "FUNCTIONS") and isinstance(tools.FUNCTIONS, dict):
    scope.update(tools.FUNCTIONS)
if hasattr(tools, "get_functions"):
    maybe = tools.get_functions()
    if isinstance(maybe, dict):
        scope.update(maybe)
scope["__name__"] = "__main__"

def _compile_generated_async(user_code: str):
    parsed = ast.parse(user_code, mode="exec")
    body = list(parsed.body)
    if body and isinstance(body[-1], ast.Expr):
        body[-1] = ast.Assign(
            targets=[ast.Name(id="__codex_last_expr", ctx=ast.Store())],
            value=body[-1].value,
        )
        body.append(ast.Return(value=ast.Name(id="__codex_last_expr", ctx=ast.Load())))
    if not body:
        body = [ast.Pass()]

    func = ast.AsyncFunctionDef(
        name="__generated_main__",
        args=ast.arguments(
            posonlyargs=[],
            args=[],
            kwonlyargs=[],
            kw_defaults=[],
            defaults=[],
        ),
        body=body,
        decorator_list=[],
    )
    module = ast.Module(body=[func], type_ignores=[])
    ast.fix_missing_locations(module)
    return compile(module, "<generated>", "exec")

buf = io.StringIO()
result = {"ok": True, "output": "", "edit_events": [], "edit_summaries": [], "history_actions": []}
try:
    sys.settrace(tracer)
    compiled = _compile_generated_async(code)
    exec(compiled, scope, scope)
    with redirect_stdout(buf):
        returned = asyncio.run(scope["__generated_main__"]())
        if returned is not None:
            print(returned)
        if hasattr(tools, "drain_edit_events"):
            events = tools.drain_edit_events()
            if isinstance(events, list):
                result["edit_events"] = [event for event in events if isinstance(event, str) and event]
        if hasattr(tools, "drain_edit_summaries"):
            summaries = tools.drain_edit_summaries()
            if isinstance(summaries, list):
                result["edit_summaries"] = [item for item in summaries if isinstance(item, str) and item]
        if hasattr(tools, "drain_history_actions"):
            actions = tools.drain_history_actions()
            if isinstance(actions, list):
                result["history_actions"] = [item for item in actions if isinstance(item, dict)]
    sys.settrace(None)
    result["output"] = buf.getvalue()
except Exception as exc:
    sys.settrace(None)
    result["ok"] = False
    result["output"] = buf.getvalue()
    result["error"] = f"{exc.__class__.__name__}: {exc}"
    result["traceback"] = traceback.format_exc()

print(json.dumps(result))
`.trim();

  try {
    const { stdout } = await runPythonCommand(["-c", runner, encodedCode], {
      timeout: TOOL_EXEC_TIMEOUT_MS,
      maxBuffer: 2 * 1024 * 1024,
    });
    const parsed = JSON.parse(String(stdout || "{}"));
    return {
      ok: Boolean(parsed?.ok),
      output: typeof parsed?.output === "string" ? parsed.output : "",
      error: typeof parsed?.error === "string" ? parsed.error : "",
      traceback: typeof parsed?.traceback === "string" ? parsed.traceback : "",
      editEvents: Array.isArray(parsed?.edit_events)
        ? parsed.edit_events.filter((item) => typeof item === "string" && item.length > 0)
        : [],
      editSummaries: Array.isArray(parsed?.edit_summaries)
        ? parsed.edit_summaries.filter((item) => typeof item === "string" && item.length > 0)
        : [],
      historyActions: Array.isArray(parsed?.history_actions)
        ? parsed.history_actions.filter((item) => item && typeof item === "object")
        : [],
    };
  } catch (error) {
    if (error?.killed || error?.signal || error?.code === "ETIMEDOUT") {
      return {
        ok: false,
        output: "",
        error: `Tool execution timed out after ${Math.round(TOOL_EXEC_TIMEOUT_MS / 1000)}s`,
        traceback: "",
        editEvents: [],
        editSummaries: [],
        historyActions: [],
      };
    }

    return {
      ok: false,
      output: String(error?.stdout || ""),
      error: getOpenRouterErrorMessage(error),
      traceback: String(error?.stderr || ""),
      editEvents: [],
      editSummaries: [],
      historyActions: [],
    };
  }
}

function capToolHistoryText(text, limit) {
  const source = String(text ?? "");
  if (source.length === 0) {
    return source;
  }
  const maxChars = Math.max(500, Math.floor((Number(limit) || 16000) * 4));
  if (source.length <= maxChars) {
    return source;
  }
  const head = Math.floor(maxChars * 0.5);
  const tail = maxChars - head;
  return `${source.slice(0, head)}
... [tool result truncated: ${source.length} chars > ${maxChars}] ...
${source.slice(-tail)}`;
}

function buildToolResultPayload(result) {
  const output = typeof result?.output === "string" ? result.output.trimEnd() : "";
  const error = typeof result?.error === "string" ? result.error.trimEnd() : "";
  const traceback = typeof result?.traceback === "string" ? result.traceback.trimEnd() : "";
  const editEvents = Array.isArray(result?.editEvents)
    ? result.editEvents.filter((item) => typeof item === "string" && item.trim().length > 0)
    : [];
  const editSummaries = Array.isArray(result?.editSummaries)
    ? result.editSummaries.filter((item) => typeof item === "string" && item.trim().length > 0)
    : [];

  if (result?.ok) {
    const outputText = output.trim();
    const looksLikeEditResultDict =
      outputText.startsWith("{") &&
      outputText.endsWith("}") &&
      /["'](?:path|file|replacements|bytes_written|added_lines|removed_lines|changed)["']/.test(
        outputText
      );
    const displayParts = [];
    if (outputText.length > 0 && !(editEvents.length > 0 && looksLikeEditResultDict)) {
      displayParts.push(output);
    }
    if (editEvents.length > 0) {
      displayParts.push(editEvents.join("\n"));
    }
    const displayText = displayParts.length > 0 ? displayParts.join("\n") : "(no output)";

    const historyParts = [];
    if (output.trim().length > 0) {
      historyParts.push(output);
    }
    if (editSummaries.length > 0) {
      historyParts.push(editSummaries.join("\n"));
    }
    const joinedHistory = historyParts.length > 0 ? historyParts.join("\n") : "(no output)";
    const historyText = capToolHistoryText(joinedHistory, getToolOutputTokenLimit());
    return { displayText, historyText };
  }

  const displayParts = [];
  const historyParts = [];
  if (error) {
    displayParts.push(error);
    historyParts.push(error);
  }
  if (output.trim().length > 0) {
    displayParts.push(output);
    historyParts.push(output);
  }
  if (traceback.trim().length > 0) {
    displayParts.push(traceback);
    historyParts.push(traceback);
  }
  if (editEvents.length > 0) {
    displayParts.push(editEvents.join("\n"));
  }
  if (editSummaries.length > 0) {
    historyParts.push(editSummaries.join("\n"));
  }

  return {
    displayText: displayParts.length > 0 ? displayParts.join("\n") : "Tool execution failed.",
    historyText: capToolHistoryText(
      historyParts.length > 0 ? historyParts.join("\n") : "Tool execution failed.",
      getToolOutputTokenLimit()
    ),
  };
}

function applyHistoryActionsFromTool(actions, generation) {
  if (generation !== chatGeneration) {
    return { processedActions: 0, appliedCount: 0, changed: false, errorCount: 0 };
  }
  if (!Array.isArray(actions) || actions.length === 0) {
    return { processedActions: 0, appliedCount: 0, changed: false, errorCount: 0 };
  }

  let processedActions = 0;
  let appliedCount = 0;
  let changed = false;
  let errorCount = 0;

  for (const action of actions) {
    if (!action || typeof action !== "object") {
      continue;
    }
    if (action.type !== "exclude_history_messages") {
      continue;
    }
    processedActions += 1;

    const includeSystem = action.include_system === true;
    const maxMatches = Math.max(1, Math.min(5000, Number(action.max_matches) || 1));
    const latestN = Math.max(0, Number(action.latest_n) || 0);
    const roleRaw = typeof action.role === "string" ? action.role.trim().toLowerCase() : "";
    const roleFilter = roleRaw === "tool_result" ? "tool" : roleRaw;

    const query = typeof action.query === "string" ? action.query : "";
    const useRegex = action.use_regex === true && query.trim().length > 0;
    const caseSensitive = action.case_sensitive === true;
    const regexFlagsRaw = typeof action.regex_flags === "string" ? action.regex_flags : "";

    let regex = null;
    if (useRegex) {
      try {
        let flags = regexFlagsRaw.replace(/[^gimsuy]/g, "");
        flags = flags.replace(/g/g, "");
        if (!caseSensitive && !flags.includes("i")) {
          flags += "i";
        }
        regex = new RegExp(query, flags);
      } catch {
        errorCount += 1;
        continue;
      }
    }

    const scopeIndexes = [];
    for (let i = messages.length - 1; i >= 0; i -= 1) {
      const entry = messages[i];
      if (!entry || entry.ephemeral === true) {
        continue;
      }
      const entryRole = typeof entry.role === "string" ? entry.role : "";
      if (!includeSystem && entryRole === "system") {
        continue;
      }
      scopeIndexes.push(i);
      if (latestN > 0 && scopeIndexes.length >= latestN) {
        break;
      }
    }

    let actionApplied = 0;
    for (const idx of scopeIndexes) {
      if (actionApplied >= maxMatches) {
        break;
      }
      const entry = messages[idx];
      if (!entry || entry.ephemeral === true) {
        continue;
      }
      const entryRole = typeof entry.role === "string" ? entry.role : "";
      if (roleFilter && entryRole !== roleFilter) {
        continue;
      }

      const text = typeof entry.content === "string" ? entry.content : String(entry.content ?? "");
      let matchesQuery = true;
      if (query.trim().length > 0) {
        if (regex) {
          matchesQuery = regex.test(text);
        } else {
          const haystack = caseSensitive ? text : text.toLowerCase();
          const needle = caseSensitive ? query : query.toLowerCase();
          matchesQuery = haystack.includes(needle);
        }
      }
      if (!matchesQuery) {
        continue;
      }

      if (entry.excludeFromRequest === true) {
        continue;
      }
      entry.excludeFromRequest = true;
      appliedCount += 1;
      actionApplied += 1;
      changed = true;
    }
  }

  return { processedActions, appliedCount, changed, errorCount };
}

function getToolResultLinesForDisplay(text) {
  const normalized = String(text ?? "").replace(/\r\n/g, "\n").replace(/\r/g, "\n").trimEnd();
  if (!normalized) {
    return ["(no output)"];
  }

  const originalLines = normalized.split("\n");
  const hasUnifiedDiffMarkers =
    /(^|\n)---\s+a\//.test(normalized) &&
    /(^|\n)\+\+\+\s+b\//.test(normalized) &&
    /(^|\n)@@\s/.test(normalized);
  if (hasUnifiedDiffMarkers) {
    return originalLines;
  }

  const wrapCols = Math.max(20, TOOL_RESULT_TRUNCATE_WRAP_COLS);
  const wrappedLines = [];
  for (const line of originalLines) {
    if (line.length === 0) {
      wrappedLines.push("");
      continue;
    }

    for (let i = 0; i < line.length; i += wrapCols) {
      wrappedLines.push(line.slice(i, i + wrapCols));
    }
  }

  if (wrappedLines.length <= TOOL_RESULT_TRUNCATE_MAX_LINES) {
    return originalLines;
  }

  const headCount = Math.min(TOOL_RESULT_TRUNCATE_HEAD_LINES, wrappedLines.length);
  const tailCount = Math.min(
    TOOL_RESULT_TRUNCATE_TAIL_LINES,
    Math.max(0, wrappedLines.length - headCount)
  );
  const hiddenCount = Math.max(0, wrappedLines.length - headCount - tailCount);
  const preview = [];

  for (let i = 0; i < headCount; i += 1) {
    preview.push(`${i + 1}:${wrappedLines[i]}`);
  }

  preview.push(`... +${hiddenCount} lines`);

  for (let i = wrappedLines.length - tailCount; i < wrappedLines.length; i += 1) {
    preview.push(`${i + 1}:${wrappedLines[i]}`);
  }

  return preview;
}

function removePendingAssistantMessage(index, generation) {
  if (generation !== chatGeneration) {
    return false;
  }

  if (index < 0 || index >= messages.length) {
    return false;
  }

  if (messages[index]?.role !== "assistant" || messages[index]?.ephemeral !== true) {
    return false;
  }

  pendingAssistantMessageIndex = -1;
  messages.splice(index, 1);
  markDirty();
  renderFrame(true);
  return true;
}

function appendToolMessages(
  toolName,
  assistantToolInput,
  executedCode,
  resultText,
  historyResultText,
  toolCallId,
  toolOk,
  generation
) {
  if (generation !== chatGeneration) {
    return;
  }

  const normalizedToolName = toolName || "code_execution";
  const normalizedInput = String(assistantToolInput ?? "");
  const normalizedCode = String(executedCode ?? "");
  const normalizedResult = String(resultText ?? "");
  const normalizedHistoryResult = String(historyResultText ?? "");
  const safeResult = normalizedResult.trim().length > 0 ? normalizedResult : "(no output)";
  const safeHistoryResult =
    normalizedHistoryResult.trim().length > 0 ? normalizedHistoryResult : "(no output)";
  messages.push({
    role: "tool",
    name: normalizedToolName,
    toolCallId,
    toolInput: normalizedInput,
    toolCode: normalizedCode,
    toolOk: Boolean(toolOk),
    content: safeHistoryResult,
    uiContent: safeResult,
  });
  appendHistoryEntry("tool", safeHistoryResult, {
    name: normalizedToolName,
    toolCallId: typeof toolCallId === "string" ? toolCallId : "",
    toolInput: normalizedInput,
    toolCode: normalizedCode,
    toolOk: Boolean(toolOk),
  });
  scrollChatToBottom();
  if (!APPEND_CHAT_TO_SCROLLBACK) {
    forceFullClearOnNextRender = true;
  }
  markDirty();
  renderFrame(true);
  scheduleViewportMainRefresh();
  if (APPEND_CHAT_TO_SCROLLBACK) {
    appendTranscriptNow();
    markDirty();
    renderFrame(false);
  }
}

async function requestAssistantReply(modelId, pendingIndex, generation) {
  if (generation !== chatGeneration) {
    return;
  }

  await ensureSystemPromptReady();
  const resolvedModel = modelId || selectedModel;
  ensureSystemMessageAtTop(resolvedModel);

  // Pre-turn compaction (Codex-style): if accumulated history exceeds the
  // compaction threshold, summarize before sending the user's request into
  // the freshened window.
  if (!APPEND_CHAT_TO_SCROLLBACK) {
    const currentTokens = estimateMessagesInChatTokens(messages);
    if (currentTokens > getCompactionThreshold()) {
      try {
        await runCompaction();
      } catch {
        // non-fatal: proceed with an oversized request if compaction fails
      }
    }
  }

  const client = getOpenRouterClient();
  if (!client) {
    const message = OpenAI
      ? "LLM provider is not configured. Set Base URL and API key in /providers."
      : "OpenAI package is unavailable. Please reinstall dependencies.";
    finalizePendingAssistantMessage(pendingIndex, message, generation, {
      role: "error",
      persistHistory: true,
    });
    return;
  }

  if (!resolvedModel || String(resolvedModel).trim().length === 0) {
    finalizePendingAssistantMessage(
      pendingIndex,
      "Model is not configured. Use /set model <name>.",
      generation,
      { role: "error", persistHistory: true }
    );
    return;
  }
  const requestMessages = buildOpenRouterMessagesFromHistory(resolvedModel);
  if (requestMessages.length === 0) {
    finalizePendingAssistantMessage(pendingIndex, "(empty request)", generation, {
      role: "error",
      persistHistory: true,
    });
    return;
  }

  const requestWithTimeout = async (messagesForRequest, options = {}) => {
    const disableReasoning = options?.disableReasoning === true;
    const performRequest = async (msgs, includeReasoning) => {
      const payload = {
        model: resolvedModel,
        messages: msgs,
      };
      if (includeReasoning) {
        payload.reasoning = { enabled: true };
      }

      const requestPromise = client.chat.completions.create(payload);
      let timeoutId = null;
      const llmTimeoutMs = getLlmRequestTimeoutMs();
      const timeoutPromise = new Promise((_, reject) => {
        timeoutId = setTimeout(
          () => reject(new Error(`Request timed out after ${Math.round(llmTimeoutMs / 1000)}s`)),
          llmTimeoutMs
        );
      });
      try {
        return await Promise.race([requestPromise, timeoutPromise]);
      } finally {
        if (timeoutId) {
          clearTimeout(timeoutId);
        }
      }
    };

    const reasoningEnabled = !disableReasoning && getReasoningEnabledForModel(resolvedModel);
    try {
      return await performRequest(messagesForRequest, reasoningEnabled);
    } catch (error) {
      if (disableReasoning || !reasoningEnabled || !shouldRetryWithoutReasoning(error)) {
        throw error;
      }

      try {
        const retryMessages = stripReasoningDetailsFromMessages(messagesForRequest);
        const retryCompletion = await performRequest(retryMessages, false);
        setReasoningEnabledForModel(resolvedModel, false);
        appendAssistantMessage(
          "Auto-disabled thinking for this model (provider rejected the reasoning parameter). Run /set thinking on to re-enable.",
          { excludeFromRequest: true, persistHistory: false }
        );
        await rewriteSessionWithCurrentMessages().catch(() => {});
        markDirty();
        renderFrame(false);
        return retryCompletion;
      } catch {
        throw error;
      }
    }
  };

  let pendingResolved = false;
  try {
    let completion = await requestWithTimeout(requestMessages);
    if (generation !== chatGeneration) {
      return;
    }
    updateContextBudgetFromCompletion(completion, resolvedModel);

    const reasoningEnabledNow = getReasoningEnabledForModel(resolvedModel);
    let assistantPayload = extractAssistantPayloadFromCompletion(completion, {
      allowReasoningTextFallback: reasoningEnabledNow,
    });
    if (assistantPayload.text.trim().length === 0 && getReasoningEnabledForModel(resolvedModel)) {
      try {
        const retryMessages = stripReasoningDetailsFromMessages(requestMessages);
        const retryCompletion = await requestWithTimeout(retryMessages, { disableReasoning: true });
        const retryPayload = extractAssistantPayloadFromCompletion(retryCompletion, {
          allowReasoningTextFallback: false,
        });
        if (retryPayload.text.trim().length > 0) {
          completion = retryCompletion;
          updateContextBudgetFromCompletion(completion, resolvedModel);
          assistantPayload = retryPayload;
          setReasoningEnabledForModel(resolvedModel, false);
          appendAssistantMessage(
            "Auto-disabled thinking for this model (empty content with thinking on). Run /set thinking on to re-enable.",
            { excludeFromRequest: true, persistHistory: false }
          );
          await rewriteSessionWithCurrentMessages().catch(() => {});
          markDirty();
          renderFrame(false);
        }
      } catch {
        // Keep original payload and fall through to user-facing error text.
      }
    }

    const assistantContent = assistantPayload.text;
    const assistantReasoningDetails = reasoningEnabledNow ? assistantPayload.reasoningDetails : null;
    const emptyContentMessage = getReasoningEnabledForModel(resolvedModel)
      ? "Provider returned no assistant content. Try /set thinking off for this model."
      : "Provider returned no assistant content.";
    finalizePendingAssistantMessage(
      pendingIndex,
      assistantContent.trim().length > 0
        ? assistantContent
        : emptyContentMessage,
      generation,
      { reasoningDetails: assistantReasoningDetails }
    );
    pendingResolved = true;

    if (generation !== chatGeneration) {
      return;
    }

    let latestAssistantContent = assistantContent;
    for (;;) {
      if (stopRequested) {
        emitStopNotice();
        break;
      }
      const pythonBlocks = extractAllPythonCodeBlocks(latestAssistantContent);
      if (pythonBlocks.length === 0) {
        break;
      }

      for (const pythonCode of pythonBlocks) {
        if (stopRequested) {
          break;
        }
        activeToolRun = {
          label: getToolRunLabel(pythonCode),
          startedAt: Date.now(),
          done: false,
          ok: false,
        };
        const execResult = await executeCodeWithPythonTool(pythonCode);
        if (stopRequested) {
          // User pressed Esc while the process was running: per request,
          // let the running process finish, show its output, then stop.
          activeToolRun = { ...activeToolRun, done: true, ok: false, cancelled: true };
        } else if (activeToolRun) {
          activeToolRun.done = true;
          activeToolRun.ok = Boolean(execResult?.ok);
        }
        const toolResultPayload = buildToolResultPayload(execResult);
        const historyActionResult = applyHistoryActionsFromTool(execResult?.historyActions, generation);
        if (historyActionResult.changed) {
          await rewriteSessionWithCurrentMessages().catch(() => {});
          markDirty();
          renderFrame(false);
        }
        if (historyActionResult.processedActions > 0) {
          const actionSummary =
            historyActionResult.errorCount > 0
              ? `history exclude applied: ${historyActionResult.appliedCount} (errors: ${historyActionResult.errorCount})`
              : `history exclude applied: ${historyActionResult.appliedCount}`;
          toolResultPayload.displayText = `${toolResultPayload.displayText}\n${actionSummary}`.trim();
          toolResultPayload.historyText = `${toolResultPayload.historyText}\n${actionSummary}`.trim();
        }
        appendToolMessages(
          "code_execution",
          pythonCode,
          pythonCode,
          toolResultPayload.displayText,
          toolResultPayload.historyText,
          undefined,
          Boolean(execResult?.ok),
          generation
        );

        if (generation !== chatGeneration) {
          return;
        }

      }

      if (stopRequested) {
        activeToolRun = null;
        emitStopNotice();
        break;
      }

      // Mid-turn compaction: the tool chain may have grown the context past
      // the threshold; compact at the loop boundary before continuing.
      const midTurnTokens = estimateMessagesInChatTokens(messages);
      if (midTurnTokens > getCompactionThreshold()) {
        try {
          await runCompaction();
        } catch {
          // non-fatal
        }
      }

      const followUpMessages = buildOpenRouterMessagesFromHistory(resolvedModel);
      if (followUpMessages.length === 0) {
        activeToolRun = null;
        break;
      }

      activeToolRun = null;
      // Reset the thinking counter after code execution so the follow-up
      // thinking phase starts from 0s instead of carrying the old elapsed time.
      thinkingStartedAt = Date.now();
      let followUpCompletion = await requestWithTimeout(followUpMessages);
      if (generation !== chatGeneration) {
        return;
      }
      updateContextBudgetFromCompletion(followUpCompletion, resolvedModel);

      const followUpReasoningEnabled = getReasoningEnabledForModel(resolvedModel);
      let followUpPayload = extractAssistantPayloadFromCompletion(followUpCompletion, {
        allowReasoningTextFallback: followUpReasoningEnabled,
      });
      let followUpContent = followUpPayload.text;
      let followUpReasoningDetails = followUpReasoningEnabled ? followUpPayload.reasoningDetails : null;
      if (followUpContent.trim().length === 0 && followUpReasoningEnabled) {
        // Reasoning models sometimes return only reasoning_content with an
        // empty final answer on follow-ups after tool runs. Retry without
        // reasoning so the feedback loop keeps going instead of stalling
        // silently after code execution.
        try {
          const retryMessages = stripReasoningDetailsFromMessages(followUpMessages);
          const retryCompletion = await requestWithTimeout(retryMessages, { disableReasoning: true });
          const retryPayload = extractAssistantPayloadFromCompletion(retryCompletion, {
            allowReasoningTextFallback: false,
          });
          if (retryPayload.text.trim().length > 0) {
            followUpCompletion = retryCompletion;
            updateContextBudgetFromCompletion(followUpCompletion, resolvedModel);
            followUpContent = retryPayload.text;
            followUpReasoningDetails = null;
            setReasoningEnabledForModel(resolvedModel, false);
            appendAssistantMessage(
              "Auto-disabled thinking for this model (empty follow-up content with thinking on). Run /set thinking on to re-enable.",
              { excludeFromRequest: true, persistHistory: false }
            );
            await rewriteSessionWithCurrentMessages().catch(() => {});
            markDirty();
            renderFrame(false);
          }
        } catch {
          // Keep the original empty result; the notice below will explain.
        }
      }
      if (followUpContent.trim().length === 0) {
        appendAssistantMessage(
          getReasoningEnabledForModel(resolvedModel)
            ? "Provider returned no assistant content after the tool run. Try /set thinking off for this model."
            : "Provider returned no assistant content after the tool run.",
          { excludeFromRequest: true, persistHistory: false }
        );
        break;
      }

      appendAssistantMessage(followUpContent, { reasoningDetails: followUpReasoningDetails, reveal: true });
      latestAssistantContent = followUpContent;
    }
  } catch (error) {
    const message = getOpenRouterErrorMessage(error);
    finalizePendingAssistantMessage(
      pendingResolved ? -1 : pendingIndex,
      `LLM request failed: ${message}`,
      generation,
      { role: "error", persistHistory: true }
    );
  }
}

function queueAssistantReply(modelId) {
  const wasThinking = pendingAssistantRequests > 0;
  if (!wasThinking) {
    stopRequested = false;
  }
  pendingAssistantRequests += 1;
  if (!wasThinking) {
    thinkingStartedAt = Date.now();
  }
  updateThinkingAnimationState();
  const generation = chatGeneration;
  const pendingIndex = createPendingAssistantMessage(generation);
  assistantRequestChain = assistantRequestChain
    .then(() => requestAssistantReply(modelId, pendingIndex, generation))
    .catch((error) => {
      const message = getOpenRouterErrorMessage(error);
      finalizePendingAssistantMessage(
        pendingIndex,
        `LLM request failed: ${message}`,
        generation,
        { role: "error", persistHistory: true }
      );
    })
    .finally(() => {
      const hadPending = pendingAssistantRequests > 0;
      pendingAssistantRequests = Math.max(0, pendingAssistantRequests - 1);
      if (hadPending && pendingAssistantRequests === 0) {
        thinkingStartedAt = 0;
      }
      updateThinkingAnimationState();
      if (hadPending && pendingAssistantRequests === 0) {
        markDirty();
        renderFrame(false);
      }
    });
}

function shouldBlockPastedInput(text) {
  if (typeof text !== "string" || text.length === 0) {
    return false;
  }

  const normalized = text.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  if (normalized.length > MAX_PASTE_CHARS) {
    return true;
  }

  return PASTED_CONTENT_TOKEN_RE.test(normalized.trim());
}

function styleInlineTokens(text) {
  if (typeof text !== "string" || text.length === 0) {
    return text;
  }

  return text
    .replace(PASTED_CONTENT_INLINE_TOKEN_RE, (token) => `${TOKEN_COLOR}${token}${RESET_COLOR}`)
    .replace(IMAGE_INLINE_TOKEN_RE, (token) => `${TOKEN_COLOR}${token}${RESET_COLOR}`);
}

function isImageLikePathOrUrl(value) {
  if (!value || /\r|\n/.test(value)) {
    return false;
  }

  const normalized = value.trim().replace(/^['"]|['"]$/g, "");
  if (!normalized) {
    return false;
  }

  if (IMAGE_EXT_RE.test(normalized)) {
    return true;
  }

  return false;
}

function normalizeImagePayload(value) {
  if (typeof value !== "string") {
    return "";
  }

  const trimmed = value.trim();
  if (!trimmed) {
    return "";
  }

  if (/^data:image\/[a-z0-9.+-]+;base64,/i.test(trimmed)) {
    const [, prefix = "", data = ""] = trimmed.match(/^(data:image\/[a-z0-9.+-]+;base64,)([\s\S]*)$/i) || [];
    return `${prefix}${data.replace(/\s+/g, "")}`;
  }

  return trimmed;
}

function guessImageMimeFromBase64(compact) {
  const sample = String(compact || "");
  if (/^iVBORw0KGgo/.test(sample)) return "image/png";
  if (/^\/9j\//.test(sample)) return "image/jpeg";
  if (/^R0lGOD/.test(sample)) return "image/gif";
  if (/^UklGR/.test(sample)) return "image/webp";
  if (/^Qk0/.test(sample)) return "image/bmp";
  if (/^(PHN2Zy|PD94bWwg)/.test(sample)) return "image/svg+xml";
  return "image/png";
}

function extractImagePayloadFromText(text) {
  if (typeof text !== "string" || text.length === 0) {
    return "";
  }

  const normalized = text.replace(/\r\n/g, "\n").replace(/\r/g, "\n").trim();
  if (!normalized) {
    return "";
  }

  if (/^data:image\/[a-z0-9.+-]+;base64,[a-z0-9+/=\s]+$/i.test(normalized)) {
    return normalizeImagePayload(normalized);
  }

  const htmlSrcMatch = normalized.match(/<img\b[\s\S]*?\bsrc=["']([^"']+)["'][\s\S]*?>/i);
  if (htmlSrcMatch && isImageLikePathOrUrl(htmlSrcMatch[1])) {
    return normalizeImagePayload(htmlSrcMatch[1]);
  }

  const markdownMatch = normalized.match(/^!\[[^\]]*]\(([^)]+)\)$/);
  if (markdownMatch && isImageLikePathOrUrl(markdownMatch[1])) {
    return normalizeImagePayload(markdownMatch[1]);
  }

  if (isImageLikePathOrUrl(normalized)) {
    return normalizeImagePayload(normalized);
  }

  const compact = normalized.replace(/\s+/g, "");
  if (compact.length > 256 && /^[a-z0-9+/=]+$/i.test(compact)) {
    const mime = guessImageMimeFromBase64(compact);
    return `data:${mime};base64,${compact}`;
  }

  return "";
}

function looksLikeImagePaste(text) {
  if (typeof text !== "string" || text.length === 0) {
    return false;
  }

  return extractImagePayloadFromText(text).length > 0;
}

function insertAtCursor(text) {
  input = `${input.slice(0, inputCursorIndex)}${text}${input.slice(inputCursorIndex)}`;
  inputCursorIndex += text.length;
  updateCommandMenuState();
}

function insertPastePlaceholderFromText(text) {
  const normalized = String(text ?? "").replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  const tokenMatch = normalized.trim().match(/^\[Pasted Content (\d+) chars\]$/i);
  const charCount = tokenMatch ? Number(tokenMatch[1]) : normalized.length;
  return insertPastePlaceholderByCount(charCount, normalized);
}

function insertPastePlaceholderByCount(charCount, payload = null) {
  let payloadIndex = -1;
  if (typeof payload === "string" && payload.length > 0) {
    pendingPastedPayloads.push(payload);
    payloadIndex = pendingPastedPayloads.length - 1;
  }
  insertAtCursor(`[Pasted Content ${charCount} chars]`);
  return payloadIndex;
}

function insertImagePlaceholder(payload = "") {
  syncImagePasteCounter();
  imagePasteCounter += 1;
  const tokenNumber = imagePasteCounter;
  const normalizedPayload = normalizeImagePayload(payload);
  if (normalizedPayload) {
    imageTokenPayloads.set(tokenNumber, normalizedPayload);
  }
  insertAtCursor(`[Image #${tokenNumber}]`);
  return tokenNumber;
}

function getMaxImageTokenNumberFromText(text) {
  if (typeof text !== "string" || text.length === 0) {
    return 0;
  }

  const re = /\[Image #(\d+)\]/g;
  let max = 0;
  let match;
  while ((match = re.exec(text)) !== null) {
    const n = Number(match[1]);
    if (Number.isFinite(n) && n > max) {
      max = n;
    }
  }

  return max;
}

function collectImageTokenNumbersFromText(text, collector) {
  if (!(collector instanceof Set)) {
    return;
  }

  const re = /\[Image #(\d+)\]/g;
  let match;
  while ((match = re.exec(String(text ?? ""))) !== null) {
    const n = Number(match[1]);
    if (Number.isFinite(n) && n > 0) {
      collector.add(n);
    }
  }
}

function syncImagePasteCounter() {
  const presentTokens = new Set();
  let max = getMaxImageTokenNumberFromText(input);
  collectImageTokenNumbersFromText(input, presentTokens);
  for (const entry of messages) {
    const content = typeof entry?.content === "string" ? entry.content : "";
    const entryMax = getMaxImageTokenNumberFromText(content);
    collectImageTokenNumbersFromText(content, presentTokens);
    if (entryMax > max) {
      max = entryMax;
    }
  }

  for (const key of imageTokenPayloads.keys()) {
    if (!presentTokens.has(key)) {
      imageTokenPayloads.delete(key);
    }
  }

  imagePasteCounter = max;
}

function appendToActiveBlockedPastePayload(text) {
  if (activeBlockedPastePayloadIndex < 0) {
    return;
  }

  if (activeBlockedPastePayloadIndex >= pendingPastedPayloads.length) {
    activeBlockedPastePayloadIndex = -1;
    return;
  }

  pendingPastedPayloads[activeBlockedPastePayloadIndex] += text;
}

function resolvePastedPlaceholders(text) {
  const queue = [...pendingPastedPayloads];
  const resolved = text.replace(/\[Pasted Content \d+ chars\]/g, (token) => {
    if (queue.length === 0) {
      return token;
    }

    return queue.shift();
  });

  pendingPastedPayloads = [];
  activeBlockedPastePayloadIndex = -1;
  return resolved;
}

function hasClipboardImageWindows() {
  return new Promise((resolve) => {
    const args = [
      "-NoProfile",
      "-STA",
      "-Command",
      "$img = Get-Clipboard -Format Image -ErrorAction SilentlyContinue; if ($null -ne $img) { [Console]::Write('1') }",
    ];

    execFile(
      "powershell.exe",
      args,
      { windowsHide: true, timeout: 1500, maxBuffer: 8 * 1024 },
      (_error, stdout) => {
        resolve(String(stdout || "").trim() === "1");
      }
    );
  });
}

function getClipboardImageDataUrlWindows() {
  return new Promise((resolve) => {
    const script = [
      "$img = Get-Clipboard -Format Image -ErrorAction SilentlyContinue",
      "if ($null -eq $img) { return }",
      "$ms = New-Object System.IO.MemoryStream",
      "$img.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)",
      "$bytes = $ms.ToArray()",
      "$b64 = [Convert]::ToBase64String($bytes)",
      "[Console]::Write('data:image/png;base64,' + $b64)",
    ].join("; ");

    const args = ["-NoProfile", "-STA", "-Command", script];
    execFile(
      "powershell.exe",
      args,
      { windowsHide: true, timeout: 4000, maxBuffer: 40 * 1024 * 1024 },
      (_error, stdout) => {
        const dataUrl = normalizeImagePayload(String(stdout || ""));
        resolve(dataUrl);
      }
    );
  });
}

async function pasteImageFromClipboard() {
  if (process.platform !== "win32") {
    return false;
  }

  const hasImage = await hasClipboardImageWindows();
  if (!hasImage) {
    return false;
  }

  const dataUrl = await getClipboardImageDataUrlWindows();
  if (!dataUrl) {
    return false;
  }
  insertImagePlaceholder(dataUrl);
  return true;
}

function wrapLine(text, cols) {
  const width = Math.max(1, cols || 80);
  const result = [];

  for (let i = 0; i < text.length; i += width) {
    result.push(text.slice(i, i + width));
  }

  return result.length ? result : [""];
}

function wrapLineWithPrefixes(text, firstPrefix, continuationPrefix, cols) {
  const width = Math.max(1, cols || 80);
  const source = String(text ?? "");
  const result = [];
  let remaining = source;
  let first = true;

  if (remaining.length === 0) {
    return [
      {
        prefix: firstPrefix,
        body: "",
        fullText: firstPrefix,
      },
    ];
  }

  while (remaining.length > 0) {
    const prefix = first ? firstPrefix : continuationPrefix;
    const available = Math.max(1, width - prefix.length);
    const body = remaining.slice(0, available);
    result.push({
      prefix,
      body,
      fullText: `${prefix}${body}`,
    });
    remaining = remaining.slice(body.length);
    first = false;
  }

  return result;
}

function stripAnsiSgr(text) {
  return String(text ?? "").replace(/\u001b\[[0-9;]*m/g, "");
}

function isVisualBlankLine(line) {
  return stripAnsiSgr(line).trim().length === 0;
}

function inputStartsWithSlash() {
  return input.startsWith("/");
}

function getCommandQuery() {
  const firstLine = input.split("\n")[0] || "";
  if (!firstLine.startsWith("/")) {
    return "";
  }

  return firstLine.slice(1).trim().toLowerCase();
}

function getFilteredCommands() {
  const query = getCommandQuery();
  if (!query) {
    return COMMANDS;
  }

  return COMMANDS.filter(
    (command) =>
      command.name.toLowerCase().includes(query) ||
      command.description.toLowerCase().includes(query)
  );
}

function isCommandMenuVisible() {
  return activeBuffer === "command";
}

function isNoCommandsState() {
  return isCommandMenuVisible() && getFilteredCommandBufferCommands().length === 0;
}

function getSelectedCommand() {
  if (!isCommandMenuVisible()) {
    return null;
  }

  const commands = getFilteredCommandBufferCommands();
  if (commands.length === 0) {
    return null;
  }

  return commands[commandMenuSelected] ?? null;
}

function getFilteredCommandBufferCommands() {
  const query = commandBufferQuery.trim().toLowerCase();
  if (!query) {
    return COMMANDS;
  }

  return COMMANDS.filter(
    (command) =>
      command.name.toLowerCase().includes(query) ||
      command.description.toLowerCase().includes(query)
  );
}

function getCommandBufferVisibleCount() {
  const rows = process.stdout.rows || 24;
  return Math.max(1, rows - 4);
}

function updateCommandBufferSelectionState() {
  const commands = getFilteredCommandBufferCommands();
  if (commands.length === 0) {
    commandMenuSelected = 0;
    commandMenuScroll = 0;
    return;
  }

  if (commandMenuSelected >= commands.length) {
    commandMenuSelected = commands.length - 1;
  }

  if (commandMenuSelected < commandMenuScroll) {
    commandMenuScroll = commandMenuSelected;
  }

  const visibleCount = getCommandBufferVisibleCount();
  const maxScroll = Math.max(0, commands.length - visibleCount);
  if (commandMenuScroll > maxScroll) {
    commandMenuScroll = maxScroll;
  }
}

function getFilteredModels() {
  const query = modelSearch.trim().toLowerCase();
  if (!query) {
    return availableModels;
  }

  return availableModels.filter((model) => {
    const inModes = model.inputModalities.join(", ");
    const outModes = model.outputModalities.join(", ");
    return (
      model.id.toLowerCase().includes(query) ||
      inModes.toLowerCase().includes(query) ||
      outModes.toLowerCase().includes(query)
    );
  });
}

function getModelVisibleCount() {
  const rows = process.stdout.rows || 24;
  const maxByRows = Math.max(1, Math.floor((rows - 4) / 2));
  return Math.max(1, Math.min(MODEL_LIST_MAX_ITEMS, maxByRows));
}

function normalizeModalities(value) {
  const arr = Array.isArray(value) ? value : [];
  const cleaned = arr
    .filter((item) => typeof item === "string" && item.trim().length > 0)
    .map((item) => item.trim());

  if (cleaned.length === 0) {
    return ["text"];
  }

  return [...new Set(cleaned)];
}

function formatModelModalities(model) {
  const inputModes = model.inputModalities.join(", ");
  const outputModes = model.outputModalities.join(", ");
  return `  └in: ${inputModes} out: ${outputModes}`;
}

function normalizeWorkspacePathForCompare(workspacePath) {
  if (typeof workspacePath !== "string") {
    return "";
  }
  const trimmed = workspacePath.trim();
  if (trimmed.length === 0) {
    return "";
  }
  const normalized = path.resolve(trimmed).replace(/[\\/]+$/, "");
  return process.platform === "win32" ? normalized.toLowerCase() : normalized;
}

function normalizeWorkspacePath(workspacePath) {
  if (typeof workspacePath !== "string") {
    return "";
  }
  const trimmed = workspacePath.trim();
  if (trimmed.length === 0) {
    return "";
  }
  return path.resolve(trimmed);
}

function isCurrentWorkspace(workspacePath) {
  const key = normalizeWorkspacePathForCompare(workspacePath);
  if (!key) {
    return true;
  }
  return key === normalizeWorkspacePathForCompare(WORKSPACE_ROOT);
}

function formatWorkspacePathForFooter(workspacePath) {
  const normalizedWorkspace = normalizeWorkspacePath(workspacePath);
  if (!normalizedWorkspace) {
    return "";
  }

  const homePath = normalizeWorkspacePath(process.env.USERPROFILE || process.env.HOME || "");
  if (!homePath) {
    return normalizedWorkspace;
  }

  const workspaceKey = normalizeWorkspacePathForCompare(normalizedWorkspace);
  const homeKey = normalizeWorkspacePathForCompare(homePath);
  const separator = process.platform === "win32" ? "\\" : "/";
  if (workspaceKey === homeKey) {
    return "~";
  }

  if (workspaceKey.startsWith(`${homeKey}${separator}`)) {
    return `~${normalizedWorkspace.slice(homePath.replace(/[\\/]+$/, "").length)}`;
  }

  return normalizedWorkspace;
}

function getMainFooterText() {
  const modelLabel = selectedModel && selectedModel.trim().length > 0 ? selectedModel.trim() : "no model";
  const contextLeft = Math.round(getContextLeftPercent(selectedModel));
  const safeContextLeft = Math.max(0, Math.min(100, contextLeft));
  const thinkingState = getReasoningEnabledForModel(selectedModel) ? "thinking on" : "thinking off";
  let text = `Current model: ${modelLabel} | ${safeContextLeft}% context left | ${thinkingState} | ${formatWorkspacePathForFooter(WORKSPACE_ROOT)}`;
  const mouseManuallyOff = APP_MOUSE_TRACKING_ENABLED && !mouseTrackingEnabled && !mouseSelectionMode;
  if (mouseManuallyOff) {
    text += " | drag to select/copy · Alt+M mouse · PgUp/PgDn scroll";
  }
  return text;
}

function getSessionsVisibleCount() {
  const rows = process.stdout.rows || 24;
  return Math.max(1, Math.min(20, rows - 4));
}

function formatUpdatedTime(date) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(
    date.getHours()
  )}:${pad(date.getMinutes())}`;
}

function updateSessionsSelectionState() {
  if (sessionFiles.length === 0) {
    sessionsSelected = 0;
    sessionsScroll = 0;
    return;
  }

  if (sessionsSelected >= sessionFiles.length) {
    sessionsSelected = sessionFiles.length - 1;
  }

  if (sessionsSelected < sessionsScroll) {
    sessionsScroll = sessionsSelected;
  }

  const visibleCount = getSessionsVisibleCount();
  const maxScroll = Math.max(0, sessionFiles.length - visibleCount);
  if (sessionsScroll > maxScroll) {
    sessionsScroll = maxScroll;
  }
}

async function loadSessionFiles() {
  if (isSessionsLoading) {
    return;
  }

  isSessionsLoading = true;
  sessionsLoadError = "";
  if (activeBuffer === "sessions") {
    markDirty();
    renderFrame(true);
  }

  try {
    await ensureSessionFileReady();
    const names = await fs.readdir(SESSIONS_DIR);
    const files = [];

    for (const name of names) {
      const fullPath = path.join(SESSIONS_DIR, name);
      const stat = await fs.stat(fullPath);
      if (!stat.isFile()) {
        continue;
      }

      const sessionWorkspace = await readSessionWorkspaceFromFile(fullPath);
      if (sessionWorkspace && !isCurrentWorkspace(sessionWorkspace)) {
        continue;
      }

      files.push({
        name,
        fullPath,
        mtimeMs: stat.mtimeMs,
        updatedAt: stat.mtime,
        sessionWorkspace,
      });
    }

    files.sort((a, b) => b.mtimeMs - a.mtimeMs);
    sessionFiles = files;
    updateSessionsSelectionState();
  } catch (_error) {
    sessionsLoadError = "Could not load sessions";
  } finally {
    isSessionsLoading = false;
    markDirty();
    renderFrame(true);
  }
}

async function readSessionWorkspaceFromFile(filePath) {
  let raw = "";
  try {
    raw = await fs.readFile(filePath, "utf8");
  } catch {
    return "";
  }

  const lines = raw.split(/\r?\n/);
  for (let i = lines.length - 1; i >= 0; i -= 1) {
    const line = lines[i].trim();
    if (!line) {
      continue;
    }
    try {
      const parsed = JSON.parse(line);
      const normalized = normalizeWorkspacePath(parsed?.sessionWorkspace);
      if (normalized) {
        return normalized;
      }
    } catch {
      // Keep scanning older lines when malformed.
    }
  }

  return "";
}

function parseSessionHistory(raw) {
  const lines = String(raw ?? "")
    .split(/\r?\n/)
    .filter((line) => line.trim().length > 0);
  const loadedMessages = [];
  let pendingToolMessage = null;
  let sessionModel = "";
  let sessionWorkspace = "";
  let sessionReasoningByModel = {};

  const isSetFeedbackEntry = (entry) => {
    if (!entry || entry.role !== "assistant" || entry.excludeFromRequest !== true) {
      return false;
    }
    const text = typeof entry.content === "string" ? entry.content.trim() : "";
    return /^Set model to ".+"$/.test(text) || /^Set thinking (on|off)$/.test(text);
  };

  for (const line of lines) {
    try {
      const parsed = JSON.parse(line);
      if (typeof parsed?.content !== "string") {
        continue;
      }

      if (typeof parsed?.sessionModel === "string" && parsed.sessionModel.trim().length > 0) {
        sessionModel = parsed.sessionModel.trim();
      }
      if (
        typeof parsed?.sessionWorkspace === "string" &&
        parsed.sessionWorkspace.trim().length > 0
      ) {
        sessionWorkspace = normalizeWorkspacePath(parsed.sessionWorkspace);
      }
      if (parsed?.sessionReasoningByModel && typeof parsed.sessionReasoningByModel === "object") {
        sessionReasoningByModel = normalizeReasoningConfigMap(parsed.sessionReasoningByModel);
      }

      const role = typeof parsed?.role === "string" ? parsed.role : "assistant";
      const content = parsed.content.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
      const reasoningDetails = normalizeReasoningDetails(parsed?.reasoning_details);

      if (role === "tool") {
        const hasStructuredToolMeta =
          typeof parsed?.name === "string" ||
          typeof parsed?.toolCallId === "string" ||
          typeof parsed?.toolInput === "string" ||
          typeof parsed?.toolCode === "string";
        if (hasStructuredToolMeta) {
          if (pendingToolMessage) {
            loadedMessages.push({ role: "tool", content: pendingToolMessage });
            pendingToolMessage = null;
          }
          loadedMessages.push({
            role: "tool",
            content,
            ...(typeof parsed?.name === "string" ? { name: parsed.name } : {}),
            ...(typeof parsed?.toolCallId === "string" ? { toolCallId: parsed.toolCallId } : {}),
            ...(typeof parsed?.toolInput === "string" ? { toolInput: parsed.toolInput } : {}),
            ...(typeof parsed?.toolCode === "string" ? { toolCode: parsed.toolCode } : {}),
            ...(typeof parsed?.toolOk === "boolean" ? { toolOk: parsed.toolOk } : {}),
            ...(parsed?.hidden === true ? { hidden: true } : {}),
            ...(parsed?.excludeFromRequest === true ? { excludeFromRequest: true } : {}),
          });
          continue;
        }

        if (pendingToolMessage) {
          loadedMessages.push({ role: "tool", content: pendingToolMessage });
        }
        pendingToolMessage = content.trim().startsWith("\u2022 Ran ")
          ? content
          : `\u2022 Ran ${content}`;
        continue;
      }

      if (role === "tool_result") {
        if (pendingToolMessage) {
          const resultLines = content.split("\n");
          if (resultLines.length > 0) {
            const formatted = resultLines.map((text, index) =>
              index === 0 ? `\u2514 ${text}` : `  ${text}`
            );
            pendingToolMessage += `\n${formatted.join("\n")}`;
          }
          loadedMessages.push({ role: "tool", content: pendingToolMessage });
          pendingToolMessage = null;
        } else {
          loadedMessages.push({ role: "tool", content });
        }
        continue;
      }

      if (pendingToolMessage) {
        loadedMessages.push({ role: "tool", content: pendingToolMessage });
        pendingToolMessage = null;
      }

      const nextEntry = {
        role,
        content,
        ...(reasoningDetails ? { reasoningDetails } : {}),
        ...(parsed?.hidden === true ? { hidden: true } : {}),
        ...(parsed?.excludeFromRequest === true ? { excludeFromRequest: true } : {}),
      };

      const previousEntry = loadedMessages.length > 0 ? loadedMessages[loadedMessages.length - 1] : null;
      if (
        isSetFeedbackEntry(previousEntry) &&
        isSetFeedbackEntry(nextEntry) &&
        previousEntry.content === nextEntry.content
      ) {
        continue;
      }

      loadedMessages.push(nextEntry);
    } catch {
      // Ignore malformed JSONL lines and continue loading remaining history.
    }
  }

  if (pendingToolMessage) {
    loadedMessages.push({ role: "tool", content: pendingToolMessage });
  }

  return { loadedMessages, sessionModel, sessionWorkspace, sessionReasoningByModel };
}

async function loadSessionFileIntoChat(filePath, options = {}) {
  const bumpGeneration = options.bumpGeneration !== false;
  let raw = "";

  try {
    raw = await fs.readFile(filePath, "utf8");
  } catch (error) {
    if (error?.code !== "ENOENT") {
      return false;
    }
  }

  if (bumpGeneration) {
    chatGeneration += 1;
  }

  const parsedSession = parseSessionHistory(raw);
  const loadedMessages = Array.isArray(parsedSession?.loadedMessages)
    ? parsedSession.loadedMessages
    : [];
  const loadedSessionWorkspace = normalizeWorkspacePath(parsedSession?.sessionWorkspace);
  if (loadedSessionWorkspace && !isCurrentWorkspace(loadedSessionWorkspace)) {
    return false;
  }
  const loadedSessionReasoningByModel = normalizeReasoningConfigMap(
    parsedSession?.sessionReasoningByModel
  );
  reasoningEnabledByModel = loadedSessionReasoningByModel;
  messages.length = 0;
  printedMessageCount = 0;
  forceTranscriptReplay = true;
  messages.push(...loadedMessages);
  imageTokenPayloads.clear();
  ensureSystemMessageAtTop();
  syncImagePasteCounter();
  scrollChatToBottom();
  sessionPersistenceInitialized = raw.trim().length > 0 && shouldPersistSessionHistory();
  return true;
}

async function loadSelectedSessionIntoChat() {
  const selected = sessionFiles[sessionsSelected];
  if (!selected) {
    return;
  }

  await ensureSystemPromptReady();
  const uidMatch = selected.name.match(/^session-(.+)\.jsonl$/i);
  currentSessionUid = uidMatch ? uidMatch[1] : selected.name;
  sessionFilePath = selected.fullPath;
  sessionWriteChain = Promise.resolve();
  sessionPersistenceInitialized = false;
  await loadSessionFileIntoChat(selected.fullPath);
}

function resetComposerState() {
  input = "";
  inputCursorIndex = 0;
  resetSubmittedInputHistoryNavigation();
  pendingPastedPayloads = [];
  activeBlockedPastePayloadIndex = -1;
  imageTokenPayloads.clear();
  imagePasteCounter = 0;
  commandMenuDismissed = false;
  commandMenuSelected = 0;
  commandMenuScroll = 0;
  syncImagePasteCounter();
}

function refreshMainBufferAfterCommand() {
  cancelIdleFlush();
  burstMode = false;
  forceFullClearOnNextRender = true;
  markDirty();
  renderFrame(true);
}

async function startNewChat() {
  await ensureSystemPromptReady();
  chatGeneration += 1;
  currentSessionUid = createSessionUid();
  sessionFilePath = getSessionFilePath(currentSessionUid);
  sessionWriteChain = Promise.resolve();
  sessionPersistenceInitialized = false;
  resetMessagesToSystemPrompt();
  resetComposerState();
  await rewriteSessionWithCurrentMessages();
  refreshMainBufferAfterCommand();
}

async function clearCurrentChat() {
  await ensureSystemPromptReady();
  chatGeneration += 1;
  sessionWriteChain = Promise.resolve();
  sessionPersistenceInitialized = false;
  resetMessagesToSystemPrompt();
  resetComposerState();
  await fs.unlink(sessionFilePath).catch(() => {});
  await rewriteSessionWithCurrentMessages();
  refreshMainBufferAfterCommand();
}

async function clearAllMemory() {
  await ensureSessionFileReady();
  await fs.writeFile(NEXUS_MEMORY_FILE, "", "utf8");
  refreshMainBufferAfterCommand();
}

async function resumeCurrentChat() {
  await ensureSystemPromptReady();
  await loadSessionFileIntoChat(sessionFilePath);
  resetComposerState();
  refreshMainBufferAfterCommand();
}

function updateModelSelectionState() {
  const models = getFilteredModels();
  if (models.length === 0) {
    modelSelected = 0;
    modelScroll = 0;
    return;
  }

  if (modelSelected >= models.length) {
    modelSelected = models.length - 1;
  }

  if (modelSelected < modelScroll) {
    modelScroll = modelSelected;
  }

  const visibleCount = getModelVisibleCount();
  const maxScroll = Math.max(0, models.length - visibleCount);
  if (modelScroll > maxScroll) {
    modelScroll = maxScroll;
  }
}

function getProviderBaseUrl() {
  const activeProvider = getActiveProvider();
  return (
    (typeof activeProvider?.base_url === "string" && activeProvider.base_url.trim()) ||
    OPENROUTER_BASE_URL
  );
}

function getProviderApiKey() {
  const activeProvider = getActiveProvider();
  return (typeof activeProvider?.api_key === "string" && activeProvider.api_key.trim()) || "";
}

function getProviderModelsCacheKey() {
  const baseURL = getProviderBaseUrl().replace(/\/+$/, "");
  const apiKey = getProviderApiKey();
  return `${baseURL}|${apiKey}`;
}

function extractContextLengthFromModelItem(item) {
  const candidates = [
    item?.context_length,
    item?.contextLength,
    item?.context_window,
    item?.contextWindow,
    item?.max_context_length,
    item?.maxContextLength,
    item?.max_model_len,
    item?.max_seq_len,
    item?.max_position_embeddings,
    item?.n_ctx,
    item?.n_ctx_per_seq,
    item?.n_ctx_train,
    item?.architecture?.context_length,
    item?.architecture?.max_context_length,
    item?.details?.context_length,
    item?.details?.max_context_length,
    item?.details?.n_ctx,
    item?.model_info?.context_length,
    item?.model_info?.n_ctx,
    item?.limits?.context_length,
    item?.limits?.max_context_length,
    item?.meta?.context_length,
    item?.meta?.contextLength,
    item?.meta?.n_ctx,
    item?.meta?.n_ctx_train,
    item?.tokenizer_config?.model_max_length,
  ];
  for (const candidate of candidates) {
    const raw = Number(candidate);
    if (Number.isFinite(raw) && raw > 0) {
      return Math.floor(raw);
    }
  }
  return 0;
}

function normalizeModelsPayload(payload) {
  const source = Array.isArray(payload?.data)
    ? payload.data
    : Array.isArray(payload?.models)
      ? payload.models
      : Array.isArray(payload)
        ? payload
        : [];

  return source
    .map((item) => {
      const id =
        (typeof item?.id === "string" && item.id) ||
        (typeof item?.name === "string" && item.name) ||
        "";
      if (!id) {
        return null;
      }
      return {
        id,
        inputModalities: normalizeModalities(
          item?.architecture?.input_modalities ??
            item?.input_modalities ??
            item?.modalities?.input
        ),
        outputModalities: normalizeModalities(
          item?.architecture?.output_modalities ??
            item?.output_modalities ??
            item?.modalities?.output
        ),
        contextLength: extractContextLengthFromModelItem(item),
      };
    })
    .filter((item) => item && item.id);
}

async function loadModelsFromProvider(force = false) {
  if (isModelsLoading) {
    return;
  }

  const providerCacheKey = getProviderModelsCacheKey();
  if (!force && loadedModelsProviderKey === providerCacheKey && availableModels.length > 0) {
    return;
  }

  isModelsLoading = true;
  modelsLoadError = "";
  if (activeBuffer === "model") {
    markDirty();
    renderFrame(true);
  }

  try {
    if (typeof fetch !== "function") {
      throw new Error("fetch unavailable");
    }

    const normalizedBaseURL = getProviderBaseUrl().replace(/\/+$/, "");
    const apiKey = getProviderApiKey();
    const endpoints = [];
    endpoints.push(`${normalizedBaseURL}/models`);
    if (!/\/v1$/i.test(normalizedBaseURL)) {
      endpoints.push(`${normalizedBaseURL}/v1/models`);
    }

    let models = [];
    let lastErrorMessage = "";
    for (const endpoint of endpoints) {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 8000);
      try {
        const headers = { Accept: "application/json" };
        if (apiKey) {
          headers.Authorization = `Bearer ${apiKey}`;
        }
        const response = await fetch(endpoint, {
          headers,
          signal: controller.signal,
        });
        if (!response.ok) {
          lastErrorMessage = `HTTP ${response.status}`;
          continue;
        }
        const payload = await response.json();
        models = normalizeModelsPayload(payload);
        if (models.length > 0) {
          break;
        }
        lastErrorMessage = "No models returned";
      } catch (error) {
        lastErrorMessage = String(error?.message || "request failed");
      } finally {
        clearTimeout(timeout);
      }
    }

    if (!models.length) {
      throw new Error(lastErrorMessage || "No models returned");
    }

    const uniqueMap = new Map();
    for (const model of models) {
      if (!uniqueMap.has(model.id)) {
        uniqueMap.set(model.id, model);
      }
    }
    availableModels = [...uniqueMap.values()].sort((a, b) => a.id.localeCompare(b.id));
    loadedModelsProviderKey = providerCacheKey;

    updateModelSelectionState();
  } catch (_error) {
    modelsLoadError = "Could not load provider models";
  } finally {
    isModelsLoading = false;
    markDirty();
    renderFrame(true);
  }
}

async function runSlashCommand(commandName, commandArgs = "") {
  if (commandName === "/model") {
    openProvidersBuffer();
    return true;
  }

  if (commandName === "/thinking") {
    appendTuiErrorMessage("/thinking", "deprecated. Use '/set thinking <on|off>'");
    return true;
  }

  if (commandName === "/providers") {
    openProvidersBuffer();
    return true;
  }

  if (commandName === "/set") {
    const args = String(commandArgs ?? "").trim();
    const [keyToken = ""] = args.split(/\s+/);
    const settingKey = keyToken.toLowerCase();
    const settingValue = keyToken ? args.slice(keyToken.length).trim() : "";

    if (settingKey === "model") {
      if (!settingValue) {
        appendTuiErrorMessage("/set", "invalid usage. Use '/set model <name>'");
        return true;
      }

      const providerIndex = providers.findIndex((entry) => entry?.name === selectedProviderName);
      if (providerIndex < 0) {
        appendTuiErrorMessage("/set", "failed because no active provider is selected");
        return true;
      }

      const previousModel = normalizeProviderModel(providers[providerIndex]?.model);
      providers[providerIndex] = normalizeProviderEntry({
        ...providers[providerIndex],
        model: settingValue,
      });
      const nextModel = normalizeProviderModel(providers[providerIndex]?.model);
      await saveProvidersToFile();
      resetLlmClient();
      syncSelectedModelFromActiveProvider();
      if (previousModel !== nextModel) {
        await loadModelsFromProvider(true);
      }
      appendAssistantMessage(`Set model to "${selectedModel}"`, {
        excludeFromRequest: true,
        persistHistory: false,
      });
      await rewriteSessionWithCurrentMessages();
      refreshMainBufferAfterCommand();
      return true;
    }

    if (settingKey === "thinking") {
      if (!selectedModel || selectedModel.trim().length === 0) {
        appendTuiErrorMessage("/set", "failed because current model is not set");
        return true;
      }
      if (settingValue.trim().length === 0) {
        const stateText = getReasoningEnabledForModel(selectedModel) ? "on" : "off";
        appendAssistantMessage(`Thinking is currently ${stateText} for ${selectedModel.trim()}`, {
          excludeFromRequest: true,
          persistHistory: false,
        });
        await rewriteSessionWithCurrentMessages();
        refreshMainBufferAfterCommand();
        return true;
      }
      const normalizedValue = settingValue.toLowerCase();
      if (normalizedValue !== "on" && normalizedValue !== "off") {
        appendTuiErrorMessage("/set", "invalid usage. Use '/set thinking <on|off>'");
        return true;
      }

      setReasoningEnabledForModel(selectedModel, normalizedValue === "on");
      appendAssistantMessage(
        `Set thinking ${normalizedValue === "on" ? "on" : "off"}`,
        {
          excludeFromRequest: true,
          persistHistory: false,
        }
      );
      await rewriteSessionWithCurrentMessages();
      refreshMainBufferAfterCommand();
      return true;
    }

    appendTuiErrorMessage(
      "/set",
      "invalid usage. Use '/set model <name>' or '/set thinking <on|off>'"
    );
    return true;
  }

  if (commandName === "/resume") {
    if (pendingAssistantRequests > 0) {
      appendTuiErrorMessage("/resume");
      return true;
    }
    openSessionsBuffer();
    return true;
  }

  if (commandName === "/new") {
    if (pendingAssistantRequests > 0) {
      appendTuiErrorMessage("/new");
      return true;
    }
    await startNewChat();
    return true;
  }

  if (commandName === "/clear") {
    if (pendingAssistantRequests > 0) {
      appendTuiErrorMessage("/clear");
      return true;
    }
    await clearCurrentChat();
    return true;
  }

  if (commandName === "/clear-memory") {
    if (pendingAssistantRequests > 0) {
      appendTuiErrorMessage("/clear-memory");
      return true;
    }
    try {
      await clearAllMemory();
    } catch {
      appendTuiErrorMessage("/clear-memory", "failed");
    }
    return true;
  }

  if (commandName === "/skills") {
    if (pendingAssistantRequests > 0) {
      appendTuiErrorMessage("/skills");
      return true;
    }
    await loadSkillsCatalog();
    if (skillsCatalog.length === 0) {
      appendAssistantMessage("No skills available. Create a skill directory with a SKILL.md file (e.g. .nexus/skills/my-skill/SKILL.md).", {
        excludeFromRequest: true,
        persistHistory: false,
      });
    } else {
      const lines = skillsCatalog.map((s) => `- ${s.name}${s.description ? ": " + s.description : ""}`);
      appendAssistantMessage(`Available skills:\n${lines.join("\n")}\n\nLoad a skill with: get_skill("name")`, {
        excludeFromRequest: true,
        persistHistory: false,
      });
    }
    await rewriteSessionWithCurrentMessages();
    refreshMainBufferAfterCommand();
    return true;
  }

  if (commandName === "/mcp") {
    const args = String(commandArgs ?? "").trim();
    if (args.toLowerCase() === "reload") {
      try {
        await stopMcpServers();
      } catch {
        // ignore
      }
      mcpBridgeError = "";
      try {
        await startMcpServers();
        await refreshMcpDescriptions();
      } catch (error) {
        mcpBridgeError = error?.message || String(error);
      }
      if (systemPromptText) {
        systemPromptText = buildSystemPromptFromDescriptions(toolDescriptions, {
          modelId: selectedModel,
          contextLeftPercent: getContextLeftPercent(selectedModel),
        });
        ensureSystemMessageAtTop();
      }
      appendAssistantMessage(`MCP servers reloaded. ${getMcpStatusText()}`, {
        excludeFromRequest: true,
        persistHistory: false,
      });
      await rewriteSessionWithCurrentMessages();
      refreshMainBufferAfterCommand();
      return true;
    }

    let text = "";
    if (mcpServers.length === 0) {
      text = getMcpStatusText() || "No MCP servers configured. Add servers to ~/.nexus/mcp_config.json";
    } else {
      text = getMcpStatusText();
    }
    for (const entry of mcpServers) {
      if (!entry.tools || entry.tools.length === 0) {
        continue;
      }
      const toolNames = entry.tools.map((t) => t.name).join(", ");
      text += `\n  ${entry.name} tools: ${toolNames}`;
    }
    appendAssistantMessage(text, {
      excludeFromRequest: true,
      persistHistory: false,
    });
    await rewriteSessionWithCurrentMessages();
    refreshMainBufferAfterCommand();
    return true;
  }

  if (commandName === "/compact") {
    const instruction = String(commandArgs ?? "").trim();
    appendAssistantMessage(
      instruction
        ? `Compacting context with instruction: ${instruction}...`
        : "Compacting context...",
      { excludeFromRequest: true, persistHistory: false }
    );
    const compactResult = await runCompaction(instruction);
    if (!compactResult?.ok) {
      appendAssistantMessage(`Compaction failed: ${compactResult?.error || "unknown error"}`, {
        excludeFromRequest: true,
        persistHistory: false,
      });
    } else {
      appendAssistantMessage(
        `Compaction complete. Summary (${compactResult.summary.length} chars) plus the most recent context retained.`,
        { excludeFromRequest: true, persistHistory: false }
      );
    }
    await rewriteSessionWithCurrentMessages();
    refreshMainBufferAfterCommand();
    return true;
  }

  if (COMMANDS.some((command) => command.name === commandName)) {
    appendTuiErrorMessage(commandName, "not supported in this build");
    return true;
  }

  return false;
}

function openCommandBuffer(initialQuery = "") {
  input = "";
  inputCursorIndex = 0;
  pendingPastedPayloads = [];
  activeBlockedPastePayloadIndex = -1;
  isBracketedPasteActive = false;
  bracketedPasteBuffer = "";
  pasteParserBuffer = "";
  commandBufferQuery = String(initialQuery ?? "").trim();
  commandMenuDismissed = false;
  commandMenuSelected = 0;
  commandMenuScroll = 0;
  updateCommandBufferSelectionState();
  activeBuffer = "command";
  enterAltScreenIfNeeded();
  lastCommandRenderedRows = [];
  lastCommandRenderedCols = 0;
  lastCommandRenderedHeight = 0;
  forceFullClearOnNextRender = true;
  cancelIdleFlush();
  burstMode = false;
  markDirty();
  renderFrame(true);
}

function closeCommandBuffer(options = {}) {
  const restoreInput =
    typeof options.restoreInput === "string" ? options.restoreInput : "";
  exitAltScreenIfNeeded();
  activeBuffer = "main";
  commandBufferQuery = "";
  isBracketedPasteActive = false;
  bracketedPasteBuffer = "";
  pasteParserBuffer = "";
  lastCommandRenderedRows = [];
  lastCommandRenderedCols = 0;
  lastCommandRenderedHeight = 0;
  input = restoreInput;
  inputCursorIndex = input.length;
  commandMenuDismissed = false;
  commandMenuSelected = 0;
  commandMenuScroll = 0;
  forceFullClearOnNextRender = true;
  cancelIdleFlush();
  burstMode = false;
  markDirty();
  renderFrame(true);
}

function openModelBuffer() {
  commandBufferQuery = "";
  lastCommandRenderedRows = [];
  lastCommandRenderedCols = 0;
  lastCommandRenderedHeight = 0;
  input = "";
  inputCursorIndex = 0;
  pendingPastedPayloads = [];
  commandMenuDismissed = false;
  commandMenuSelected = 0;
  commandMenuScroll = 0;
  activeBuffer = "model";
  enterAltScreenIfNeeded();
  isBracketedPasteActive = false;
  bracketedPasteBuffer = "";
  pasteParserBuffer = "";
  modelSearch = "";
  modelSelected = 0;
  modelScroll = 0;
  lastModelRenderedRows = [];
  lastModelRenderedCols = 0;
  lastModelRenderedHeight = 0;
  forceFullClearOnNextRender = true;
  cancelIdleFlush();
  burstMode = false;
  markDirty();
  renderFrame(true);
}

function closeModelBuffer() {
  exitAltScreenIfNeeded();
  activeBuffer = "main";
  lastModelRenderedRows = [];
  lastModelRenderedCols = 0;
  lastModelRenderedHeight = 0;
  forceFullClearOnNextRender = true;
  cancelIdleFlush();
  burstMode = false;
  markDirty();
  renderFrame(true);
}

function openSessionsBuffer() {
  commandBufferQuery = "";
  lastCommandRenderedRows = [];
  lastCommandRenderedCols = 0;
  lastCommandRenderedHeight = 0;
  input = "";
  inputCursorIndex = 0;
  pendingPastedPayloads = [];
  commandMenuDismissed = false;
  commandMenuSelected = 0;
  commandMenuScroll = 0;
  activeBuffer = "sessions";
  enterAltScreenIfNeeded();
  isBracketedPasteActive = false;
  bracketedPasteBuffer = "";
  pasteParserBuffer = "";
  sessionsSelected = 0;
  sessionsScroll = 0;
  lastSessionsRenderedRows = [];
  lastSessionsRenderedCols = 0;
  lastSessionsRenderedHeight = 0;
  forceFullClearOnNextRender = true;
  cancelIdleFlush();
  burstMode = false;
  markDirty();
  renderFrame(true);
  loadSessionFiles();
}

function closeSessionsBuffer() {
  exitAltScreenIfNeeded();
  activeBuffer = "main";
  if (APPEND_CHAT_TO_SCROLLBACK) {
    appendTranscriptNow({ replay: true });
  }
  lastSessionsRenderedRows = [];
  lastSessionsRenderedCols = 0;
  lastSessionsRenderedHeight = 0;
  forceFullClearOnNextRender = true;
  cancelIdleFlush();
  burstMode = false;
  markDirty();
  renderFrame(true);
}

function getProvidersVisibleCount() {
  const rows = process.stdout.rows || 24;
  return Math.max(1, Math.min(20, rows - 4));
}

function updateProvidersSelectionState() {
  if (providers.length === 0) {
    providersSelected = 0;
    providersScroll = 0;
    return;
  }

  if (providersSelected >= providers.length) {
    providersSelected = providers.length - 1;
  }

  if (providersSelected < providersScroll) {
    providersScroll = providersSelected;
  }

  const visibleCount = getProvidersVisibleCount();
  const maxScroll = Math.max(0, providers.length - visibleCount);
  if (providersScroll > maxScroll) {
    providersScroll = maxScroll;
  }
}

function openProvidersBuffer() {
  commandBufferQuery = "";
  lastCommandRenderedRows = [];
  lastCommandRenderedCols = 0;
  lastCommandRenderedHeight = 0;
  input = "";
  inputCursorIndex = 0;
  pendingPastedPayloads = [];
  commandMenuDismissed = false;
  commandMenuSelected = 0;
  commandMenuScroll = 0;
  activeBuffer = "providers";
  enterAltScreenIfNeeded();
  isBracketedPasteActive = false;
  bracketedPasteBuffer = "";
  pasteParserBuffer = "";
  const currentIndex = providers.findIndex((entry) => entry?.name === selectedProviderName);
  providersSelected = currentIndex >= 0 ? currentIndex : 0;
  providersScroll = 0;
  lastProvidersRenderedRows = [];
  lastProvidersRenderedCols = 0;
  lastProvidersRenderedHeight = 0;
  forceFullClearOnNextRender = true;
  cancelIdleFlush();
  burstMode = false;
  markDirty();
  renderFrame(true);
  loadProvidersFromFile();
}

function closeProvidersBuffer() {
  exitAltScreenIfNeeded();
  activeBuffer = "main";
  lastProvidersRenderedRows = [];
  lastProvidersRenderedCols = 0;
  lastProvidersRenderedHeight = 0;
  forceFullClearOnNextRender = true;
  cancelIdleFlush();
  burstMode = false;
  markDirty();
  renderFrame(true);
}

function openProviderEditorBuffer(mode, index) {
  providerEditorMode = mode === "create" ? "create" : "edit";
  providerEditorIndex = index;
  providerEditorFieldIndex = 0;
  providerEditorDraft = normalizeProviderEntry(providers[index] || {});
  activeBuffer = "provider_editor";
  enterAltScreenIfNeeded();
  isBracketedPasteActive = false;
  bracketedPasteBuffer = "";
  pasteParserBuffer = "";
  lastProviderEditorRenderedRows = [];
  lastProviderEditorRenderedCols = 0;
  lastProviderEditorRenderedHeight = 0;
  forceFullClearOnNextRender = true;
  cancelIdleFlush();
  burstMode = false;
  markDirty();
  renderFrame(true);
}

function closeProviderEditorToProviders() {
  activeBuffer = "providers";
  providerEditorMode = "";
  providerEditorIndex = -1;
  providerEditorFieldIndex = 0;
  providerEditorDraft = { name: "", base_url: "", api_key: "", model: "" };
  lastProviderEditorRenderedRows = [];
  lastProviderEditorRenderedCols = 0;
  lastProviderEditorRenderedHeight = 0;
  forceFullClearOnNextRender = true;
  cancelIdleFlush();
  burstMode = false;
  markDirty();
  renderFrame(true);
}

async function createProviderAndOpenEditor() {
  const newProvider = normalizeProviderEntry({
    name: "New Provider",
    base_url: "",
    api_key: "",
    model: "",
  });
  providers.push(newProvider);
  providersSelected = providers.length - 1;
  updateProvidersSelectionState();
  await saveProvidersToFile();
  openProviderEditorBuffer("create", providersSelected);
}

async function saveProviderEditorChanges() {
  if (providerEditorIndex < 0 || providerEditorIndex >= providers.length) {
    closeProviderEditorToProviders();
    return;
  }

  const previous = normalizeProviderEntry(providers[providerEditorIndex]);
  const next = normalizeProviderEntry(providerEditorDraft);
  const wasSelectedProvider = selectedProviderName === previous.name;
  const modelChanged = previous.model !== next.model;
  if (!next.name) {
    next.name = previous.name || "Provider";
  }
  providers[providerEditorIndex] = next;
  await saveProvidersToFile();
  if (wasSelectedProvider) {
    selectedProviderName = next.name || previous.name;
    nexusConfig.provider = selectedProviderName;
    await saveNexusConfig().catch(() => {});
    resetLlmClient();
    syncSelectedModelFromActiveProvider();
    if (modelChanged) {
      await loadModelsFromProvider(true);
    }
  }
  providersSelected = Math.max(0, Math.min(providers.length - 1, providerEditorIndex));
  updateProvidersSelectionState();
  closeProviderEditorToProviders();
}

async function cancelProviderEditorChanges(options = {}) {
  const immediate = options?.immediate === true;
  const mode = providerEditorMode;
  const index = providerEditorIndex;

  if (immediate) {
    closeProviderEditorToProviders();
  }

  if (
    mode === "create" &&
    index >= 0 &&
    index < providers.length
  ) {
    providers.splice(index, 1);
    await saveProvidersToFile();
    providersSelected = Math.max(0, Math.min(providers.length - 1, index));
    updateProvidersSelectionState();
  }

  await ensureSelectedProviderIsValid();
  if (!immediate) {
    closeProviderEditorToProviders();
  }
}

function getProviderEditorFields() {
  return [
    { label: "Name", key: "name" },
    { label: "Base URL", key: "base_url" },
    { label: "Api Key", key: "api_key" },
    { label: "Model", key: "model" },
  ];
}

function getProviderEditorFieldKey() {
  const fields = getProviderEditorFields();
  const field = fields[providerEditorFieldIndex] || fields[0];
  return field.key;
}

function appendToProviderEditorField(text) {
  const key = getProviderEditorFieldKey();
  providerEditorDraft[key] = `${providerEditorDraft[key] || ""}${text}`;
}

function backspaceProviderEditorField() {
  const key = getProviderEditorFieldKey();
  const current = String(providerEditorDraft[key] || "");
  if (current.length === 0) {
    return;
  }
  providerEditorDraft[key] = current.slice(0, -1);
}

function updateCommandMenuState() {
  if (!inputStartsWithSlash()) {
    commandMenuDismissed = false;
    commandMenuSelected = 0;
    commandMenuScroll = 0;
    return;
  }

  if (commandMenuDismissed) {
    return;
  }

  const commands = getFilteredCommands();
  if (commands.length === 0) {
    commandMenuSelected = 0;
    commandMenuScroll = 0;
    return;
  }

  if (commandMenuSelected >= commands.length) {
    commandMenuSelected = commands.length - 1;
  }

  if (commandMenuSelected < commandMenuScroll) {
    commandMenuScroll = commandMenuSelected;
  }

  const maxScroll = Math.max(0, commands.length - COMMAND_MENU_MAX_ITEMS);
  if (commandMenuScroll > maxScroll) {
    commandMenuScroll = maxScroll;
  }
}

function getCommandMenuVisualLines(cols) {
  if (!isCommandMenuVisible()) {
    return [];
  }

  const commands = getFilteredCommands();
  const lines = [];

  if (commands.length === 0) {
    lines.push({ text: "  no commands", selected: false, muted: true });
    for (let i = 1; i < COMMAND_MENU_MAX_ITEMS; i += 1) {
      lines.push({ text: "", selected: false, muted: false });
    }

    return lines;
  }

  const end = commandMenuScroll + COMMAND_MENU_MAX_ITEMS;
  for (let i = commandMenuScroll; i < end; i += 1) {
    const command = commands[i];
    if (!command) {
      lines.push({ text: "", selected: false, muted: false });
      continue;
    }

    const selected = i === commandMenuSelected;
    const prefix = "  ";
    lines.push({ text: `${prefix}${command.name}  ${command.description}`, selected, muted: false });
  }

  return lines;
}

function buildInputVisualLines(cols) {
  if (!input) {
    return wrapLine(`${PROMPT_PREFIX}${PLACEHOLDER}`, cols);
  }

  const logicalLines = input.split("\n");
  const visualLines = [];

  for (let i = 0; i < logicalLines.length; i += 1) {
    const prefix = i === 0 ? PROMPT_PREFIX : CONTINUATION_PREFIX;
    const fullLine = `${prefix}${logicalLines[i]}`;
    visualLines.push(...wrapLine(fullLine, cols));
  }

  return visualLines;
}

const PYTHON_KEYWORDS = new Set([
  "False",
  "None",
  "True",
  "and",
  "as",
  "assert",
  "async",
  "await",
  "break",
  "class",
  "continue",
  "def",
  "del",
  "elif",
  "else",
  "except",
  "finally",
  "for",
  "from",
  "global",
  "if",
  "import",
  "in",
  "is",
  "lambda",
  "nonlocal",
  "not",
  "or",
  "pass",
  "raise",
  "return",
  "try",
  "while",
  "with",
  "yield",
]);

const PYTHON_BUILTINS = new Set([
  "abs",
  "all",
  "any",
  "dict",
  "enumerate",
  "float",
  "int",
  "len",
  "list",
  "map",
  "max",
  "min",
  "open",
  "print",
  "range",
  "set",
  "sorted",
  "str",
  "sum",
  "tuple",
  "zip",
]);

function annotateAssistantCodeBlocks(message) {
  const sourceLines = String(message ?? "").replace(/\r/g, "\n").split("\n");
  const annotated = [];
  let insidePythonBlock = false;

  for (const line of sourceLines) {
    const trimmed = line.trim();
    if (!insidePythonBlock && /^```(?:python|py|execute)\s*$/i.test(trimmed)) {
      insidePythonBlock = true;
      continue;
    }

    if (insidePythonBlock && /^```\s*$/.test(trimmed)) {
      insidePythonBlock = false;
      continue;
    }

    annotated.push({ text: line, python: insidePythonBlock, fence: false });
  }

  return annotated;
}

function stylePythonToken(token, color) {
  return `${color}${token}${CODE_BLOCK_FG_COLOR}`;
}

function styleMarkdownInline(text) {
  let changed = false;
  let styled = String(text ?? "");

  styled = styled.replace(/`([^`\n]+)`/g, (_match, code) => {
    changed = true;
    return `${CODE_BLOCK_BG_COLOR}${MARKDOWN_INLINE_CODE_FG}\`${code}\`${RESET_COLOR}`;
  });

  styled = styled.replace(/\*\*([^*\n]+)\*\*/g, (_match, value) => {
    changed = true;
    return `${MARKDOWN_BOLD_COLOR}**${value}**${RESET_COLOR}`;
  });

  styled = styled.replace(/\[([^\]\n]+)\]\(([^)\n]+)\)/g, (_match, label, url) => {
    changed = true;
    return `${MARKDOWN_LINK_TEXT_COLOR}[${label}]${RESET_COLOR}${MARKDOWN_LINK_URL_COLOR}(${url})${RESET_COLOR}`;
  });

  return { styled, changed };
}

function highlightMarkdownText(text, allowBlockMarkers) {
  const raw = String(text ?? "");
  if (raw.length === 0) {
    return null;
  }

  if (allowBlockMarkers && /^\s*(?:[-*_]\s*){3,}$/.test(raw)) {
    return `${PLACEHOLDER_COLOR}${raw}${RESET_COLOR}`;
  }

  if (allowBlockMarkers) {
    const headingMatch = raw.match(/^(\s*#{1,6}\s+)(.*)$/);
    if (headingMatch) {
      const inline = styleMarkdownInline(headingMatch[2]);
      return `${MARKDOWN_HEADER_COLOR}${headingMatch[1]}${inline.styled}${RESET_COLOR}`;
    }

    const quoteMatch = raw.match(/^(\s*>\s?)(.*)$/);
    if (quoteMatch) {
      const inline = styleMarkdownInline(quoteMatch[2]);
      return `${MARKDOWN_QUOTE_COLOR}${quoteMatch[1]}${RESET_COLOR}${inline.styled}`;
    }

    const listMatch = raw.match(/^(\s*)([-*+]|\d+\.)\s+(.*)$/);
    if (listMatch) {
      const inline = styleMarkdownInline(listMatch[3]);
      return `${listMatch[1]}${MARKDOWN_LIST_MARKER_COLOR}${listMatch[2]}${RESET_COLOR} ${inline.styled}`;
    }
  }

  const inline = styleMarkdownInline(raw);
  return inline.changed ? inline.styled : null;
}

function isRenderableChatEntry(entry) {
  if (!entry || entry.hidden === true || entry.ephemeral === true) {
    return false;
  }

  const role = typeof entry?.role === "string" ? entry.role : "";
  if (role === "system") {
    return false;
  }

  if (role !== "user" && role !== "assistant" && role !== "tool" && role !== "error") {
    return false;
  }

  const content = typeof entry?.content === "string" ? entry.content : "";
  return content.length > 0;
}

function detectToolStatusColorFromLines(lines) {
  const joined = lines.join(" ").toLowerCase();
  const failed = /(exit code:\s*[1-9]\d*|error|failed|exception|not found)/.test(joined);
  if (failed) {
    return RED_COLOR;
  }

  return GREEN_COLOR;
}

function extractEditSummaryFromToolOutput(text) {
  const lines = String(text ?? "")
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n")
    .split("\n");

  for (const line of lines) {
    const trimmed = line.trim();
    if (/^Edited\s+.+\s+\(\+\d+\s+-\d+\)$/.test(trimmed)) {
      return trimmed;
    }
  }

  return "";
}

function stripFirstMatchingLine(text, targetLine) {
  const target = String(targetLine ?? "").trim();
  if (!target) {
    return String(text ?? "");
  }

  const lines = String(text ?? "")
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n")
    .split("\n");
  const output = [];
  let removed = false;
  for (const line of lines) {
    if (!removed && line.trim() === target) {
      removed = true;
      continue;
    }
    output.push(line);
  }

  return output.join("\n");
}

function styleEditedToolHeaderLine(visibleText, toolColor) {
  const match = String(visibleText ?? "").match(/^(\S)\s+Edited\s+(.+?)\s+\(\+(\d+)\s+-(\d+)\)$/);
  if (!match) {
    return null;
  }

  const bullet = match[1];
  const filePath = match[2];
  const plusCount = match[3];
  const minusCount = match[4];
  const bulletColor = toolColor || GREEN_COLOR;
  const BOLD_WHITE = "\u001b[1m\u001b[97m";

  return `${bulletColor}${bullet}${RESET_COLOR} ${BOLD_WHITE}Edited${RESET_COLOR} ${filePath} (${GREEN_COLOR}+${plusCount}${RESET_COLOR} ${RED_COLOR}-${minusCount}${RESET_COLOR})`;
}

function isUnifiedDiffText(text) {
  const source = String(text ?? "");
  const lines = source.replace(/\r\n/g, "\n").split("\n").map((l) => l.trim());
  let sawTripleDash = false;
  let sawTriplePlus = false;
  for (const line of lines) {
    if (line.startsWith("diff --git ") || line.startsWith("index ")) {
      return true;
    }
    if (line.startsWith("--- ")) {
      sawTripleDash = true;
    } else if (line.startsWith("+++ ")) {
      sawTriplePlus = true;
    } else if (/^@@\s+-\d+,\d+\s+\+\d+,\d+\s+@@/.test(line)) {
      return true;
    }
    if (sawTripleDash && sawTriplePlus) {
      return true;
    }
  }
  return false;
}

function getDiffBackgroundColor(toolLineText) {
  const raw = String(toolLineText ?? "");
  if (!raw) {
    return null;
  }

  const normalized = raw.startsWith("\u2514 ") ? raw.slice(2) : raw.startsWith("  ") ? raw.slice(2) : raw;
  if (normalized.startsWith("+") && !normalized.startsWith("+++")) {
    return DIFF_ADD_BG_COLOR;
  }
  if (normalized.startsWith("-") && !normalized.startsWith("---")) {
    return DIFF_REMOVE_BG_COLOR;
  }
  return null;
}

function buildTranscriptLinesForEntry(entry, cols = process.stdout.columns || 80) {
  const role = typeof entry?.role === "string" ? entry.role : "assistant";
  const message =
    role === "tool" && typeof entry?.uiContent === "string"
      ? entry.uiContent
      : typeof entry?.content === "string"
        ? entry.content
        : "";
  const contentWidth = Math.max(1, Number(cols) || 80);
  let logicalLines = message.replace(/\r/g, "\n").split("\n");
  let logicalLineMeta = logicalLines.map((line) => ({ text: line, python: false, fence: false }));
  const hasStructuredToolMeta =
    role === "tool" &&
    (typeof entry?.toolInput === "string" ||
      typeof entry?.toolCode === "string" ||
      typeof entry?.name === "string" ||
      typeof entry?.toolCallId === "string");
  let structuredToolOk = null;
  if (hasStructuredToolMeta) {
    const toolName = typeof entry?.name === "string" && entry.name ? entry.name : "code_execution";
    const assistantInput =
      typeof entry?.toolInput === "string" && entry.toolInput.length > 0
        ? entry.toolInput
        : "(no args/code provided)";
    const executedCode = typeof entry?.toolCode === "string" && entry.toolCode.length > 0
      ? entry.toolCode
      : "";
    let resultSource = message;
    let toolHeader = `\u2022 Ran ${toolName}`;
    if (toolName === "code_execution") {
      const editSummary = extractEditSummaryFromToolOutput(message);
      if (editSummary) {
        toolHeader = `\u2022 ${editSummary}`;
        resultSource = stripFirstMatchingLine(message, editSummary);
      }
    }
    const resultLines = getToolResultLinesForDisplay(resultSource);
    const formattedResults = (resultLines.length > 0 ? resultLines : [""]).map((line, i) =>
      i === 0 ? `\u2514 ${line}` : `  ${line}`
    );
    const hasDistinctCode = executedCode.length > 0 && executedCode !== assistantInput;
    logicalLines = [toolHeader];
    if (toolName !== "code_execution") {
      const inputLines = assistantInput.replace(/\r/g, "\n").split("\n");
      const formattedInputLines = (inputLines.length > 0 ? inputLines : ["(no args/code provided)"]).map(
        (line) => `    ${line}`
      );
      logicalLines.push(...formattedInputLines);
      if (hasDistinctCode) {
        const codeLines = executedCode.replace(/\r/g, "\n").split("\n");
        const formattedCodeLines = (codeLines.length > 0 ? codeLines : ["(no executed code)"]).map(
          (line) => `    ${line}`
        );
        logicalLines.push(...formattedCodeLines);
      }
    }
    logicalLines.push(...formattedResults);
    logicalLineMeta = logicalLines.map((line) => ({ text: line, python: false, fence: false }));
    if (typeof entry?.toolOk === "boolean") {
      structuredToolOk = entry.toolOk;
    }
  }

  if (role === "assistant" && !hasStructuredToolMeta) {
    logicalLineMeta = annotateAssistantCodeBlocks(message);
    logicalLines = logicalLineMeta.map((item) => item.text);
  }

  const isToolCall =
    role === "tool" || (logicalLines.length > 0 && logicalLines[0].trim().startsWith("\u2022 Ran "));
  // Unified-diff detection for the whole tool payload; +/- lines only get
  // the diff background when the output genuinely contains a patch.
  const looksLikeDiff = isToolCall && isUnifiedDiffText(message);
  const isErrorMessage = role === "error";
  const toolColor = isToolCall
    ? (structuredToolOk === true
        ? GREEN_COLOR
        : structuredToolOk === false
          ? RED_COLOR
          : detectToolStatusColorFromLines(logicalLines))
    : null;
  const assistantPrefix = role === "assistant" ? "• " : "";
  const isMultilineUser = role === "user" && logicalLines.length > 1;
  const userPrefix = role === "user" ? PROMPT_PREFIX : "";
  const continuationPrefix = isMultilineUser
    ? ""
    : role === "user" || (role === "assistant" && !isToolCall)
      ? CONTINUATION_PREFIX
      : "";
  const output = [];

  for (let i = 0; i < logicalLines.length; i += 1) {
    const lineMeta = logicalLineMeta[i] || { text: logicalLines[i], python: false, fence: false };
    const body = logicalLines[i];
    const isToolLine = isToolCall;
    const firstPrefix = isToolLine
      ? ""
      : i === 0
        ? `${assistantPrefix}${userPrefix}`
        : continuationPrefix;
    const wrapped = wrapLineWithPrefixes(
      body,
      firstPrefix,
      isToolLine ? "" : continuationPrefix,
      contentWidth
    );

    for (let w = 0; w < wrapped.length; w += 1) {
      const wrappedLine = wrapped[w];
      const visibleText = wrappedLine.fullText;
      let line = visibleText;

      if (isErrorMessage) {
        line = `${RED_COLOR}${visibleText}${RESET_COLOR}`;
      } else if (isToolCall) {
        // Only color +/- lines as diff hunks when the whole output actually
        // looks like a unified diff; otherwise "- some text" from a tool
        // result would get a misleading red/red background.
        const diffBgColor =
          isToolCall && looksLikeDiff && !(i === 0 && w === 0)
            ? getDiffBackgroundColor(wrappedLine.body)
            : null;
        if (diffBgColor) {
          line = `${diffBgColor}${visibleText.padEnd(contentWidth, " ")}${RESET_COLOR}`;
        } else {
          const color = i === 0 && w === 0 ? toolColor : PLACEHOLDER_COLOR;
          const editedHeaderStyled =
            i === 0 && w === 0 ? styleEditedToolHeaderLine(visibleText, toolColor) : null;
          if (editedHeaderStyled) {
            line = editedHeaderStyled;
          } else if (color) {
            line = `${color}${visibleText}${RESET_COLOR}`;
          }
        }
      } else if (role === "assistant" && lineMeta.python) {
        line = highlightPythonCodeLine(visibleText.padEnd(contentWidth, " "), lineMeta.fence);
      } else if (role === "assistant") {
        const styledMarkdown = highlightMarkdownText(wrappedLine.body, w === 0);
        if (styledMarkdown) {
          line = `${wrappedLine.prefix}${styledMarkdown}`;
        } else if (i === 0 && w === 0) {
          line = `${PLACEHOLDER_COLOR}•${RESET_COLOR} ${wrappedLine.body}`;
        }
      }

      output.push(styleInlineTokens(line));
    }
  }

  if (role === "tool") {
    const divider = "\u2500".repeat(Math.max(3, contentWidth));
    output.push("");
    output.push(`${PLACEHOLDER_COLOR}${divider}${RESET_COLOR}`);
  }
  return output;
}

function getMainFrameTopForCurrentLayout(rows, cols) {
  const inputVisualLines = buildInputVisualLines(cols);
  const menuLines = getCommandMenuVisualLines(cols);
  const menuHeight = menuLines.length;
  const statusVisible = isAssistantThinking() || isMcpStartupStatusVisible();
  const statusRows = statusVisible ? STATUS_BAR_ROWS : 0;
  const statusChatGapRows = statusVisible ? STATUS_CHAT_GAP : 0;
  const statusInputGapRows = statusVisible ? STATUS_INPUT_GAP : 0;
  if (APPEND_CHAT_TO_SCROLLBACK) {
    const neededReservedRows = getAppendReservedBottomRowsFromLayout(
      inputVisualLines.length,
      menuHeight
    );
    const reservedTop = Math.max(0, rows - Math.min(rows, neededReservedRows));
    const appendChatGap = menuHeight > 0 ? 0 : CHAT_INPUT_GAP;
    return Math.min(
      rows - 1,
      reservedTop + appendChatGap + statusChatGapRows + statusRows + statusInputGapRows
    );
  }
  const footerVisible = !APPEND_CHAT_TO_SCROLLBACK && input.length === 0 && menuHeight === 0;
  const footerHeight = menuHeight > 0 ? 0 : 1;
  const activeBottomPadding = menuHeight > 0 ? BOTTOM_PADDING : INPUT_BOTTOM_PADDING_NO_MENU;
  const frameHeight = inputVisualLines.length;
  const footerBlockHeight = menuHeight > 0 ? 0 : MAIN_FOOTER_GAP + footerHeight;
  const menuBlockHeight = footerBlockHeight + (menuHeight > 0 ? MENU_INPUT_GAP + menuHeight : 0);
  return Math.max(
    0,
    rows -
      activeBottomPadding -
      menuBlockHeight -
      frameHeight -
      statusChatGapRows -
      statusRows -
      statusInputGapRows
  );
}

function getAppendReservedBottomRowsFromLayout(inputRowsCount, menuHeight, includeStatus = true) {
  const inputRows = Math.max(1, Number(inputRowsCount) || 1);
  const menuRows = Number(menuHeight) > 0 ? MENU_INPUT_GAP + Number(menuHeight) : 0;
  if (APPEND_CHAT_TO_SCROLLBACK) {
    return Math.max(APPEND_COMPOSER_FIXED_ROWS, inputRows + menuRows);
  }

  // In append mode keep the composer compact and avoid appending footer artifacts.
  const footerRows = Number(menuHeight) > 0 ? 0 : MAIN_FOOTER_GAP + 1;
  const chatGapRows = CHAT_INPUT_GAP;
  const statusVisible = includeStatus && isAssistantThinking();
  const statusRows = statusVisible ? STATUS_BAR_ROWS : 0;
  const statusChatGapRows = statusVisible ? STATUS_CHAT_GAP : 0;
  const statusInputGapRows = statusVisible ? STATUS_INPUT_GAP : 0;
  return Math.max(
    1,
    chatGapRows +
      statusChatGapRows +
      statusRows +
      statusInputGapRows +
      inputRows +
      menuRows +
      footerRows
  );
}

function getAppendReservedBottomRows(cols, includeStatus = true) {
  const inputRows = buildInputVisualLines(cols).length;
  const menuHeight = getCommandMenuVisualLines(cols).length;
  return getAppendReservedBottomRowsFromLayout(inputRows, menuHeight, includeStatus);
}

function isAssistantThinking() {
  return pendingAssistantRequests > 0;
}

function isMcpStartupStatusVisible() {
  return mcpStartupActive && mcpStartupHasConfig;
}

function cancelAndClearActiveToolRun() {
  activeToolRun = {
    label: activeToolRun?.label || "code execution",
    startedAt: activeToolRun?.startedAt || Date.now(),
    done: true,
    ok: false,
    cancelled: true,
  };
  markDirty();
  renderFrame(false);
  updateThinkingAnimationState();
}

function resetStopRequested() {
  stopRequested = false;
}

function handleStopRequest() {
  if (stopRequested) {
    return;
  }
  stopRequested = true;

  const toolRunning =
    activeToolRun && !activeToolRun.done && isAssistantThinking();

  if (toolRunning) {
    // A process is still running: wait for it to finish (per user request),
    // show its result, then emit the stop notice after it.
    activeToolRun = { ...activeToolRun, cancelPending: true };
    markDirty();
    renderFrame(false);
    return;
  }

  // Nothing is mid-process: write the stop notice immediately.
  const text = "■ Stopped by user (Esc pressed).";
  const idx = pendingAssistantMessageIndex;
  const candidate =
    idx >= 0 && idx < messages.length && messages[idx]?.role === "assistant"
      ? messages[idx]
      : null;
  if (candidate && candidate.ephemeral === true) {
    candidate.content = text;
    candidate.ephemeral = false;
    candidate.role = "assistant";
    pendingAssistantMessageIndex = -1;
  } else {
    messages.push({ role: "assistant", content: text });
  }
  appendHistoryEntry("assistant", text);
  cancelAndClearActiveToolRun();
  scrollChatToBottom();
  forceFullClearOnNextRender = true;
  markDirty();
  renderFrame(true);
}

function emitStopNotice() {
  const text = "■ Stopped by user (Esc pressed).";
  const idx = pendingAssistantMessageIndex;
  const candidate =
    idx >= 0 && idx < messages.length && messages[idx]?.role === "assistant"
      ? messages[idx]
      : null;
  if (candidate && candidate.ephemeral === true) {
    candidate.content = text;
    candidate.ephemeral = false;
    candidate.role = "assistant";
    pendingAssistantMessageIndex = -1;
  } else {
    messages.push({ role: "assistant", content: text });
  }
  appendHistoryEntry("assistant", text);
  cancelAndClearActiveToolRun();
  scrollChatToBottom();
  forceFullClearOnNextRender = true;
  markDirty();
  renderFrame(true);
}

function getViewportChatInputGapRows(statusVisible) {
  if (!statusVisible) {
    return CHAT_INPUT_GAP_NO_STATUS;
  }

  // Reserve the status bar block so chat content shifts upward while thinking.
  return CHAT_INPUT_GAP + STATUS_CHAT_GAP + STATUS_BAR_ROWS + STATUS_INPUT_GAP;
}

function getStatusBarText() {
  if (APPEND_CHAT_TO_SCROLLBACK) {
    return "";
  }

  if (isMcpStartupStatusVisible()) {
    const frame = SPINNER_FRAMES[spinnerFrameIndex % SPINNER_FRAMES.length];
    const text = "Starting MCP Servers...";
    return `${frame} ${applyShineEffect(text, shineFrameIndex, 8)}`;
  }

  if (!isAssistantThinking()) {
    activeToolRun = null;
    return "";
  }

  // Tool execution status takes priority over the generic thinking animation.
  if (activeToolRun) {
    const label = activeToolRun.label || "code execution";
    const elapsed = Math.floor((Date.now() - activeToolRun.startedAt) / 1000);
    const frame = SPINNER_FRAMES[spinnerFrameIndex % SPINNER_FRAMES.length];
    if (!activeToolRun.done) {
      return `${frame} ${SHINE_BRIGHT}Running:${SHINE_RESET} ${label} (${elapsed}s)`;
    }
    const mark = activeToolRun.ok ? "\u2713" : "\u2717";
    return `${mark} ${label} (${elapsed}s)`;
  }

  const elapsedSeconds =
    thinkingStartedAt > 0 ? Math.floor((Date.now() - thinkingStartedAt) / 1000) : 0;
  const symbol = thinkingFrameIndex % 2 === 0 ? "\u2022" : "\u25e6";
  const thinkingText = `${THINKING_FRAMES[thinkingFrameIndex % THINKING_FRAMES.length]} (${elapsedSeconds}s)`;
  return `${symbol} ${applyShineEffect(thinkingText, shineFrameIndex, 5)}`;
}

const SHINE_RESET = "\u001b[0m";
const SHINE_BRIGHT = "\u001b[1m\u001b[97m";
const SHINE_DIM = "\u001b[90m";

function applyShineEffect(text, frameIndex, windowWidth) {
  // Left-to-right sweeping bright highlight over dim text.
  if (!text) {
    return text;
  }
  const win = Math.max(1, windowWidth || 5);
  const total = Math.max(1, text.length);
  const cycle = total + win; // shine spawns off the left, exits off the right
  const phase = frameIndex % cycle;
  const start = phase - win;
  let out = "";
  for (let i = 0; i < text.length; i += 1) {
    const inWindow = i > start && i <= phase;
    out += inWindow ? `${SHINE_BRIGHT}${text[i]}${SHINE_RESET}` : `${SHINE_DIM}${text[i]}${SHINE_RESET}`;
  }
  // Add a dim reset so the status line doesn't leak styling into the rest of the frame.
  return `${out}${SHINE_RESET}`;
}

function updateThinkingAnimationState() {
  const shouldAnimate =
    activeBuffer === "main" &&
    (isAssistantThinking() || isMcpStartupStatusVisible());

  if (!shouldAnimate) {
    if (thinkingAnimationTimer) {
      clearInterval(thinkingAnimationTimer);
      thinkingAnimationTimer = null;
    }
    if (shineAnimationTimer) {
      clearInterval(shineAnimationTimer);
      shineAnimationTimer = null;
    }
    if (spinnerAnimationTimer) {
      clearInterval(spinnerAnimationTimer);
      spinnerAnimationTimer = null;
    }
    thinkingFrameIndex = 0;
    shineFrameIndex = 0;
    spinnerFrameIndex = 0;
    return;
  }

  if (!thinkingAnimationTimer) {
    thinkingAnimationTimer = setInterval(() => {
      if (activeBuffer !== "main" || !isAssistantThinking()) {
        updateThinkingAnimationState();
        markDirty();
        renderFrame(false);
        return;
      }

      thinkingFrameIndex = (thinkingFrameIndex + 1) % THINKING_FRAMES.length;
      markDirty();
      renderFrame(false);
    }, THINKING_ANIMATION_INTERVAL_MS);
  }

  // High-frequency shine: ~30fps smooth left-to-right sweep.
  if (!shineAnimationTimer) {
    shineAnimationTimer = setInterval(() => {
      if (activeBuffer !== "main" || !isAssistantThinking()) {
        updateThinkingAnimationState();
        markDirty();
        renderFrame(false);
        return;
      }

      shineFrameIndex += 1;
      markDirty();
      renderFrame(false);
    }, SHINE_ANIMATION_INTERVAL_MS);
  }

  // High-frequency spinner: ~60ms per frame -> smooth, complete 10-frame loop.
  if (!spinnerAnimationTimer) {
    spinnerAnimationTimer = setInterval(() => {
      if (activeBuffer !== "main" || !isAssistantThinking()) {
        updateThinkingAnimationState();
        markDirty();
        renderFrame(false);
        return;
      }

      spinnerFrameIndex = (spinnerFrameIndex + 1) % SPINNER_FRAMES.length;
      markDirty();
      renderFrame(false);
    }, 60);
  }
}

function ensureAppendReservedBottomRows(requiredRows, rows, cols = process.stdout.columns || 80) {
  if (!APPEND_CHAT_TO_SCROLLBACK) {
    return 0;
  }

  const viewportRows = Math.max(1, Number(rows) || process.stdout.rows || 24);
  const needed = Math.max(1, Math.min(viewportRows, Number(requiredRows) || 1));
  const current = Math.max(0, Math.min(viewportRows, Number(appendReservedBottomRows) || 0));
  if (current === 0) {
    appendReservedBottomRows = needed;
    return appendReservedBottomRows;
  }

  if (needed > current) {
    const delta = needed - current;
    readline.cursorTo(process.stdout, 0, Math.max(0, viewportRows - 1));
    process.stdout.write("\r\n".repeat(delta));
  } else if (needed < current) {
    const safeCols = Math.max(1, Number(cols) || process.stdout.columns || 80);
    const delta = current - needed;
    const newChatBottom = Math.max(0, viewportRows - needed);
    if (newChatBottom > 0 && delta > 0) {
      // Shift currently visible chat downward to match composer shrink.
      process.stdout.write(`\u001b[1;${newChatBottom}r`);
      readline.cursorTo(process.stdout, 0, 0);
      process.stdout.write(`\u001b[${delta}L`);
      process.stdout.write("\u001b[r");
    }
    // Fill only newly-exposed top rows from already printed transcript lines.
    paintAppendChatTopRows(viewportRows, safeCols, newChatBottom, delta, printedMessageCount);
  }

  appendReservedBottomRows = needed;
  return appendReservedBottomRows;
}

function flushAppendedChatMessages(options = {}) {
  if (!APPEND_CHAT_TO_SCROLLBACK || activeBuffer !== "main") {
    return false;
  }

  if (forceTranscriptReplay) {
    printedMessageCount = 0;
    lastRenderedChatRole = null;
    forceTranscriptReplay = false;
  }

  if (printedMessageCount > messages.length) {
    printedMessageCount = 0;
    lastRenderedChatRole = null;
  }

  if (printedMessageCount === messages.length) {
    return false;
  }

  const startCount = printedMessageCount;
  const pendingEntries = messages
    .slice(startCount)
    .filter((entry) => isRenderableChatEntry(entry));
  printedMessageCount = messages.length;
  if (pendingEntries.length === 0) {
    return false;
  }

  const cols = process.stdout.columns || 80;
  const outputLines = [];
  let previousRole = lastRenderedChatRole;
  for (const entry of pendingEntries) {
    const entryRole = typeof entry?.role === "string" ? entry.role : "";
    const entryLines = [...buildTranscriptLinesForEntry(entry, cols)];
    if (entryLines.length > 0) {
      const shouldInsertBoundaryGap = previousRole !== null;
      if (shouldInsertBoundaryGap && MESSAGE_SPACING_ROWS > 0) {
        for (let i = 0; i < MESSAGE_SPACING_ROWS; i += 1) {
          outputLines.push("");
        }
      }
      outputLines.push(...entryLines);
      previousRole = entryRole;
    }
  }
  lastRenderedChatRole = previousRole;

  const body = outputLines.join("\r\n");
  if (!body) {
    return false;
  }
  const rows = process.stdout.rows || 24;
  const reservedRows = Math.max(
    1,
    Math.min(rows, Number(options.reservedRows) || Number(appendReservedBottomRows) || 1)
  );
  const chatBottom = Math.max(1, rows - reservedRows);
  const shouldPrependNewline = startCount > 0;
  const targetRow = Math.max(0, chatBottom - 1);
  process.stdout.write(`\u001b[1;${chatBottom}r`);
  readline.cursorTo(process.stdout, 0, targetRow);
  if (shouldPrependNewline) {
    process.stdout.write("\r\n");
  }
  process.stdout.write(body);
  process.stdout.write("\u001b[r");
  return true;
}

function clearAppendReservedRows(cols, rows, reservedRows) {
  const clamped = Math.max(1, Math.min(rows, Number(reservedRows) || 1));
  const startRow = Math.max(0, rows - clamped);
  for (let y = startRow; y < rows; y += 1) {
    writeLine(y, "", cols);
  }
}

function appendTranscriptNow(options = {}) {
  if (!APPEND_CHAT_TO_SCROLLBACK || activeBuffer !== "main") {
    return false;
  }

  if (options.replay === true) {
    printedMessageCount = 0;
    forceTranscriptReplay = true;
  }

  const rows = process.stdout.rows || 24;
  const cols = process.stdout.columns || 80;
  // Do not bake transient status rows into transcript spacing.
  const requiredRows = getAppendReservedBottomRows(cols, false);
  const reservedRows = ensureAppendReservedBottomRows(requiredRows, rows, cols);
  clearAppendReservedRows(cols, rows, reservedRows);
  const wroteAppendedChat = flushAppendedChatMessages({
    reservedRows,
  });
  if (wroteAppendedChat) {
    lastFrameTop = null;
    lastFrameHeight = 0;
    lastChatAreaHeight = null;
    lastMenuTop = null;
    lastMenuHeight = 0;
    lastFooterTop = null;
    lastStatusTop = null;
    lastStatusHeight = 0;
    lastMenuRenderedLines = [];
  }

  return wroteAppendedChat;
}

function highlightPythonCodeLine(line, isFenceLine = false) {
  const raw = String(line ?? "");
  if (!raw.length) {
    return `${CODE_BLOCK_BG_COLOR}${RESET_COLOR}`;
  }

  if (isFenceLine) {
    return `${CODE_BLOCK_BG_COLOR}${CODE_BLOCK_COMMENT_COLOR}${raw}${RESET_COLOR}`;
  }

  const isIdentStart = (ch) => /[A-Za-z_]/.test(ch);
  const isIdentChar = (ch) => /[A-Za-z0-9_]/.test(ch);
  let i = 0;
  let out = "";

  while (i < raw.length) {
    const ch = raw[i];

    if (ch === "#") {
      out += `${CODE_BLOCK_COMMENT_COLOR}${raw.slice(i)}${CODE_BLOCK_FG_COLOR}`;
      break;
    }

    if (
      /[fFrRbBuU]/.test(ch) &&
      i + 1 < raw.length &&
      (raw[i + 1] === "\"" || raw[i + 1] === "'") &&
      (i === 0 || !isIdentChar(raw[i - 1]))
    ) {
      const quote = raw[i + 1];
      let j = i + 2;
      while (j < raw.length) {
        if (raw[j] === "\\" && j + 1 < raw.length) {
          j += 2;
          continue;
        }
        if (raw[j] === quote) {
          j += 1;
          break;
        }
        j += 1;
      }
      out += stylePythonToken(raw.slice(i, j), CODE_BLOCK_STRING_COLOR);
      i = j;
      continue;
    }

    if (ch === "\"" || ch === "'") {
      const quote = ch;
      let j = i + 1;
      while (j < raw.length) {
        if (raw[j] === "\\" && j + 1 < raw.length) {
          j += 2;
          continue;
        }
        if (raw[j] === quote) {
          j += 1;
          break;
        }
        j += 1;
      }
      out += stylePythonToken(raw.slice(i, j), CODE_BLOCK_STRING_COLOR);
      i = j;
      continue;
    }

    if (/[0-9]/.test(ch)) {
      let j = i + 1;
      while (j < raw.length && /[0-9._]/.test(raw[j])) {
        j += 1;
      }
      out += stylePythonToken(raw.slice(i, j), CODE_BLOCK_NUMBER_COLOR);
      i = j;
      continue;
    }

    if (isIdentStart(ch)) {
      let j = i + 1;
      while (j < raw.length && isIdentChar(raw[j])) {
        j += 1;
      }
      const token = raw.slice(i, j);
      if (PYTHON_KEYWORDS.has(token)) {
        out += stylePythonToken(token, CODE_BLOCK_KEYWORD_COLOR);
      } else if (PYTHON_BUILTINS.has(token)) {
        out += stylePythonToken(token, CODE_BLOCK_BUILTIN_COLOR);
      } else {
        out += token;
      }
      i = j;
      continue;
    }

    out += ch;
    i += 1;
  }

  return `${CODE_BLOCK_BG_COLOR}${CODE_BLOCK_FG_COLOR}${out}${RESET_COLOR}`;
}

function buildChatVisualLines(cols, sourceEntries = messages) {
  const revealActive = sourceEntries === messages && hasActiveAnswerReveal();
  let entryStartIndex = -1;
  if (sourceEntries === messages && !revealActive) {
    const lastRef = messages.length > 0 ? messages[messages.length - 1] : null;
    if (
      cachedChatLines &&
      cachedChatLinesCols === cols &&
      cachedChatLinesLen === messages.length &&
      cachedChatLinesLastRef === lastRef &&
      cachedChatLinesSpacing === MESSAGE_SPACING_ROWS
    ) {
      return cachedChatLines;
    }
  }

  const visualLines = [];
  const contentWidth = Math.max(1, cols - CHAT_LEFT_PADDING.length);
  let previousRole = null;

  for (const entry of sourceEntries) {
    if (!isRenderableChatEntry(entry)) {
      continue;
    }

    const role = typeof entry?.role === "string" ? entry.role : "";
    const entryLines = [...buildTranscriptLinesForEntry(entry, contentWidth)];
    const reasoningText = role === "assistant" ? extractReasoningDisplayText(entry?.reasoningDetails) : "";
    const reasoningLines = [];
    if (reasoningText) {
      const logical = reasoningText.split("\n");
      for (let reasoningIndex = 0; reasoningIndex < logical.length; reasoningIndex += 1) {
        const line = logical[reasoningIndex];
        const wrapped = wrapLineWithPrefixes(
          line,
          reasoningIndex === 0 ? "◦ " : "  ",
          "  ",
          contentWidth
        );
        for (const part of wrapped) {
          reasoningLines.push(`${PLACEHOLDER_COLOR}${part.fullText}${RESET_COLOR}`);
        }
      }
    }

    if (entryLines.length === 0 && reasoningLines.length === 0) {
      continue;
    }

    const shouldInsertBoundaryGap = previousRole !== null;
    if (shouldInsertBoundaryGap && MESSAGE_SPACING_ROWS > 0) {
      for (let i = 0; i < MESSAGE_SPACING_ROWS; i += 1) {
        visualLines.push({ text: "", styledText: "", color: null, assistantBulletMuted: false });
      }
    }

    entryStartIndex = visualLines.length;

    for (const styledLine of reasoningLines) {
      const plainLine = stripAnsiSgr(styledLine);
      visualLines.push({
        text: `${CHAT_LEFT_PADDING}${plainLine}`,
        styledText: `${CHAT_LEFT_PADDING}${styledLine}`,
        color: null,
        assistantBulletMuted: false,
      });
    }

    if (reasoningLines.length > 0 && entryLines.length > 0) {
      visualLines.push({ text: "", styledText: "", color: null, assistantBulletMuted: false });
    }

    let revealElapsed = null;
    if (
      role === "assistant" &&
      typeof entry?.revealUntil === "number" &&
      entry.revealUntil > Date.now()
    ) {
      const remaining = (entry.revealUntil - Date.now()) / ANSWER_REVEAL_MS;
      revealElapsed = Math.max(0, Math.min(1, 1 - remaining));
    }
    for (const styledLine of entryLines) {
      const plainLine = stripAnsiSgr(styledLine);
      let lineStyled = styledLine;
      if (revealElapsed !== null) {
        const revealStyled = applyAnswerRevealStyle(plainLine, revealElapsed);
        if (revealStyled) {
          lineStyled = revealStyled;
        }
      }
      visualLines.push({
        text: `${CHAT_LEFT_PADDING}${plainLine}`,
        styledText: `${CHAT_LEFT_PADDING}${lineStyled}`,
        color: null,
        assistantBulletMuted: false,
      });
    }

    previousRole = role;
  }

  lastEntryVisualStartIndex = entryStartIndex;

  if (sourceEntries === messages && !revealActive) {
    cachedChatLines = visualLines;
    cachedChatLinesCols = cols;
    cachedChatLinesLen = messages.length;
    cachedChatLinesLastRef = messages.length > 0 ? messages[messages.length - 1] : null;
    cachedChatLinesSpacing = MESSAGE_SPACING_ROWS;
  }

  return visualLines;
}

function paintAppendChatTopRows(
  rows,
  cols,
  chatBottom,
  topRows,
  maxMessageCount = messages.length
) {
  const viewportRows = Math.max(1, Number(rows) || process.stdout.rows || 24);
  const safeCols = Math.max(1, Number(cols) || process.stdout.columns || 80);
  const height = Math.max(0, Math.min(viewportRows, Number(chatBottom) || 0));
  if (height <= 0) {
    return;
  }
  const rowsToPaint = Math.max(0, Math.min(height, Number(topRows) || 0));
  if (rowsToPaint <= 0) {
    return;
  }

  const safeCount = Math.max(
    0,
    Math.min(messages.length, Number(maxMessageCount) || 0)
  );
  const sourceEntries = safeCount >= messages.length ? messages : messages.slice(0, safeCount);
  const allChatLines = buildChatVisualLines(safeCols, sourceEntries);
  const startIndex = Math.max(0, allChatLines.length - height);
  for (let row = 0; row < rowsToPaint; row += 1) {
    const line = allChatLines[startIndex + row];
    if (!line) {
      writeLine(row, "", safeCols);
      continue;
    }
    if (line.styledText) {
      writeStyledLine(row, line.text, line.styledText, safeCols);
    } else if (line.color === GREEN_COLOR) {
      writeColoredLine(row, line.text, safeCols, GREEN_COLOR);
    } else if (line.color === RED_COLOR) {
      writeColoredLine(row, line.text, safeCols, RED_COLOR);
    } else if (line.color === PLACEHOLDER_COLOR) {
      writeColoredLine(row, line.text, safeCols, PLACEHOLDER_COLOR);
    } else {
      writeLine(row, line.text, safeCols);
      if (line.assistantBulletMuted) {
        readline.cursorTo(process.stdout, CHAT_LEFT_PADDING.length, row);
        process.stdout.write(`${PLACEHOLDER_COLOR}\u2022${RESET_COLOR}`);
      }
    }
  }
}

function getChatViewportInfo(cols, rows) {
  if (APPEND_CHAT_TO_SCROLLBACK) {
    return { maxOffset: 0 };
  }

  updateCommandMenuState();
  const inputVisualLines = buildInputVisualLines(cols);
  const menuLines = getCommandMenuVisualLines(cols);
  const menuHeight = menuLines.length;
  const footerVisible = !APPEND_CHAT_TO_SCROLLBACK && input.length === 0 && menuHeight === 0;
  const footerHeight = menuHeight > 0 ? 0 : 1;
  const activeBottomPadding = menuHeight > 0 ? BOTTOM_PADDING : INPUT_BOTTOM_PADDING_NO_MENU;
  const frameHeight = inputVisualLines.length;
  const statusVisible = isAssistantThinking() || isMcpStartupStatusVisible();
  const chatInputGapRows = getViewportChatInputGapRows(statusVisible);
  const footerBlockHeight = menuHeight > 0 ? 0 : MAIN_FOOTER_GAP + footerHeight;
  const menuBlockHeight = footerBlockHeight + (menuHeight > 0 ? MENU_INPUT_GAP + menuHeight : 0);
  const frameTop = Math.max(0, rows - activeBottomPadding - menuBlockHeight - frameHeight);
  const chatAreaHeight = Math.max(0, frameTop - chatInputGapRows);
  const allChatLines = buildChatVisualLines(cols);
  const maxOffset = Math.max(0, allChatLines.length - chatAreaHeight);
  return { maxOffset };
}

function scrollChatBy(delta) {
  const cols = process.stdout.columns || 80;
  const rows = process.stdout.rows || 24;
  const { maxOffset } = getChatViewportInfo(cols, rows);
  const nextOffset = Math.max(0, Math.min(maxOffset, chatScrollOffset + delta));
  if (nextOffset === chatScrollOffset) {
    return false;
  }

  chatScrollOffset = nextOffset;
  return true;
}

function scrollChatToBottom() {
  if (chatScrollOffset === 0) {
    return false;
  }

  chatScrollOffset = 0;
  return true;
}

function scrollChatToTop() {
  const cols = process.stdout.columns || 80;
  const rows = process.stdout.rows || 24;
  const { maxOffset } = getChatViewportInfo(cols, rows);
  if (chatScrollOffset === maxOffset) {
    return false;
  }

  chatScrollOffset = maxOffset;
  return true;
}

function handleMouseEvent(buttonCode, action) {
  if (activeBuffer !== "main") {
    exitMouseSelectionMode();
    return;
  }

  const isWheel = (buttonCode & 64) !== 0;
  const buttonBase = buttonCode & 3;

  if (!isWheel) {
    const isLeftDown = action === "M" && buttonBase === 0;
    const isRelease = action === "m" || buttonBase === 3;
    if (isLeftDown) {
      enterMouseSelectionMode();
      return;
    }
    if (isRelease) {
      // Re-enable mouse tracking on release so wheel scrolling works again immediately.
      if (mouseSelectionMode) {
        exitMouseSelectionMode();
      }
      return;
    }
  }

  if (mouseSelectionMode) {
    return;
  }

  if (action !== "M") {
    return;
  }

  // Wheel events use bit 6 (64): 64=up, 65=down (+ modifier bits).
  if (!isWheel) {
    return;
  }

  const rows = process.stdout.rows || 24;
  const step = Math.max(1, Math.floor(rows / 6));
  const changed = (buttonCode & 1) === 1 ? scrollChatBy(-step) : scrollChatBy(step);
  if (!changed) {
    return;
  }

  cancelIdleFlush();
  burstMode = false;
  markDirty();
  renderFrame(true);
}

function looksLikeMouseSequenceFragment(text) {
  if (typeof text !== "string" || text.length === 0) {
    return false;
  }

  if (text.startsWith("\u001b[<")) {
    return true;
  }

  // Bare/fragmented SGR payloads that can leak through keypress parsing.
  // Require either explicit '<' marker or an m/M terminator to avoid swallowing normal text like '1;2;3'.
  if (
    (text.includes("<") || /[mM]/.test(text)) &&
    text.includes(";") &&
    /[mM]?$/.test(text)
  ) {
    return /^[\d;<>mM\[\]]+$/.test(text);
  }

  return false;
}

function stripMouseSequences(chunk) {
  if (typeof chunk !== "string" || chunk.length === 0) {
    return chunk;
  }

  let input = `${mouseSequenceRemainder}${chunk}`;
  mouseSequenceRemainder = "";
  let matchedMouse = false;
  let cleaned = input.replace(
    /\u001b\[<(\d+);(\d+);(\d+)([mM])/g,
    (_full, buttonStr, _x, _y, action) => {
      matchedMouse = true;
      const buttonCode = Number(buttonStr);
      if (Number.isFinite(buttonCode)) {
        handleMouseEvent(buttonCode, action);
      }
      return "";
    }
  );

  // Drop packed bare sequences too (some terminals/parsers can strip ESC[<).
  cleaned = cleaned.replace(/(?:<?\d+;\d+;\d+[mM])+/g, (full) => {
    matchedMouse = true;
    let local = full;
    const re = /<?(\d+);(\d+);(\d+)([mM])/g;
    let m = null;
    while ((m = re.exec(local)) !== null) {
      const buttonCode = Number(m[1]);
      const action = m[4];
      if (Number.isFinite(buttonCode)) {
        handleMouseEvent(buttonCode, action);
      }
    }
    return "";
  });

  // Preserve trailing partial fragment and consume it next chunk.
  const partial = cleaned.match(/(?:\u001b\[<|<?\d+;\d+;?\d*[mM]?)$/);
  if (partial && looksLikeMouseSequenceFragment(partial[0])) {
    mouseSequenceRemainder = partial[0];
    cleaned = cleaned.slice(0, -partial[0].length);
  }

  if (matchedMouse) {
    suppressMouseNoiseUntil = Date.now() + MOUSE_KEYPRESS_SUPPRESS_MS;
  }

  return cleaned;
}

function isStandaloneMouseSequence(text) {
  if (typeof text !== "string" || text.length === 0) {
    return false;
  }

  // Some terminals/key parsers can deliver mouse events without ESC[< prefix.
  // Accept repeated packed events in one chunk.
  return /^(?:(?:\u001b\[<|<)?\d+;\d+;\d+[mM])+$/.test(text);
}

function isMouseNoiseFragment(text) {
  if (typeof text !== "string" || text.length === 0) {
    return false;
  }

  if (isStandaloneMouseSequence(text) || looksLikeMouseSequenceFragment(text)) {
    return true;
  }

  // Partial packed chunks like "64;33;5M64;33;" should still be dropped.
  return (
    /^[\d;<>[\]mM]+$/.test(text) &&
    text.includes(";") &&
    (text.includes("<") || /[mM]/.test(text))
  );
}

function isMouseNoiseCharFragment(text) {
  if (typeof text !== "string" || text.length === 0) {
    return false;
  }

  return /^[\d;<>[\]mM]+$/.test(text);
}

function writeLine(y, text, cols) {
  readline.cursorTo(process.stdout, 0, y);
  const clipped = text.slice(0, cols);
  process.stdout.write(styleInlineTokens(clipped));

  if (clipped.length < cols) {
    process.stdout.write(" ".repeat(cols - clipped.length));
  }
}

function writeStyledLine(y, rawText, styledText, cols) {
  readline.cursorTo(process.stdout, 0, y);
  const clipped = String(rawText ?? "").slice(0, cols);
  process.stdout.write(String(styledText ?? ""));

  if (clipped.length < cols) {
    process.stdout.write(" ".repeat(cols - clipped.length));
  }
}

function writePlaceholderLine(y, rawText, cols) {
  const promptPart = rawText.startsWith(PROMPT_PREFIX)
    ? PROMPT_PREFIX
    : "";
  const placeholderPart = promptPart ? rawText.slice(PROMPT_PREFIX.length) : rawText;
  const styled = `${promptPart}${PLACEHOLDER_COLOR}${placeholderPart}${RESET_COLOR}`;
  readline.cursorTo(process.stdout, 0, y);
  process.stdout.write(styled);

  if (rawText.length < cols) {
    process.stdout.write(" ".repeat(cols - rawText.length));
  }
}

function writeColoredLine(y, rawText, cols, color) {
  readline.cursorTo(process.stdout, 0, y);
  process.stdout.write(`${color}${rawText}${RESET_COLOR}`);

  // Pad by VISIBLE width: ANSI escape codes are invisible but inflate
  // String.length, which would leave stale text on screen when the status
  // line shrinks (e.g. "Running: ..." -> "Thinking...").
  const visibleLength = stripAnsiSgr(rawText).length;
  if (visibleLength < cols) {
    process.stdout.write(" ".repeat(cols - visibleLength));
  }
}

function writeCenteredLine(y, rawText, cols, panelLeft, panelWidth) {
  readline.cursorTo(process.stdout, panelLeft, y);
  const clipped = rawText.slice(0, panelWidth);
  process.stdout.write(clipped);

  if (clipped.length < panelWidth) {
    process.stdout.write(" ".repeat(panelWidth - clipped.length));
  }
}

function writeCenteredColoredLine(y, rawText, cols, panelLeft, panelWidth, color) {
  readline.cursorTo(process.stdout, panelLeft, y);
  const clipped = rawText.slice(0, panelWidth);
  process.stdout.write(`${color}${clipped}${RESET_COLOR}`);

  if (clipped.length < panelWidth) {
    process.stdout.write(" ".repeat(panelWidth - clipped.length));
  }
}

function writeAlignCenterLine(y, rawText, cols) {
  const clipped = rawText.slice(0, cols);
  const startX = Math.max(0, Math.floor((cols - clipped.length) / 2));
  writeLine(y, "", cols);
  readline.cursorTo(process.stdout, startX, y);
  process.stdout.write(clipped);
}

function writeAlignCenterColoredLine(y, rawText, cols, color) {
  const clipped = rawText.slice(0, cols);
  const startX = Math.max(0, Math.floor((cols - clipped.length) / 2));
  writeLine(y, "", cols);
  readline.cursorTo(process.stdout, startX, y);
  process.stdout.write(`${color}${clipped}${RESET_COLOR}`);
}

function getInputCursorMetrics(cols) {
  if (!input) {
    return { x: PROMPT_PREFIX.length, row: 0 };
  }

  const logicalLines = input.split("\n");
  const beforeCursor = input.slice(0, inputCursorIndex);
  const beforeCursorLines = beforeCursor.split("\n");
  const currentLineIndex = beforeCursorLines.length - 1;
  const currentLineCursorCol = beforeCursorLines[currentLineIndex].length;
  let consumedRows = 0;

  for (let i = 0; i < currentLineIndex; i += 1) {
    const prefix = i === 0 ? PROMPT_PREFIX : CONTINUATION_PREFIX;
    consumedRows += wrapLine(`${prefix}${logicalLines[i]}`, cols).length;
  }

  const currentPrefix = currentLineIndex === 0 ? PROMPT_PREFIX : CONTINUATION_PREFIX;
  const currentLineRenderedUntilCursor = `${currentPrefix}${logicalLines[currentLineIndex].slice(
    0,
    currentLineCursorCol
  )}`;
  const wrappedCurrent = wrapLine(currentLineRenderedUntilCursor, cols);

  return {
    x: wrappedCurrent[wrappedCurrent.length - 1].length,
    row: consumedRows + wrappedCurrent.length - 1,
  };
}

function getCursorPosition(cols, startRow, inputViewportOffset = 0, cursorMetrics = null) {
  const metrics = cursorMetrics || getInputCursorMetrics(cols);
  const offset = Math.max(0, Number(inputViewportOffset) || 0);
  const maxY = Math.max(0, (process.stdout.rows || 24) - 1);
  const y = startRow + Math.max(0, metrics.row - offset);
  return {
    x: metrics.x,
    y: Math.max(0, Math.min(maxY, y)),
  };
}

function render() {
  if (!dirty) {
    return;
  }
  renderFrame(false);
}

function renderCommandBuffer() {
  process.stdout.write(HIDE_CURSOR);

  const rows = process.stdout.rows || 24;
  const cols = process.stdout.columns || 80;
  const visibleCount = getCommandBufferVisibleCount();
  updateCommandBufferSelectionState();
  const commands = getFilteredCommandBufferCommands();

  if (!hasInitializedScreen) {
    readline.cursorTo(process.stdout, 0, 0);
    readline.clearScreenDown(process.stdout);
    hasInitializedScreen = true;
  }

  if (forceFullClearOnNextRender) {
    readline.cursorTo(process.stdout, 0, 0);
    readline.clearScreenDown(process.stdout);
    forceFullClearOnNextRender = false;
    lastCommandRenderedRows = [];
    lastCommandRenderedCols = 0;
    lastCommandRenderedHeight = 0;
  }

  if (lastCommandRenderedCols !== cols || lastCommandRenderedHeight !== rows) {
    lastCommandRenderedRows = [];
    lastCommandRenderedCols = cols;
    lastCommandRenderedHeight = rows;
  }

  const frameRows = Array.from({ length: rows }, () => ({
    text: " ".repeat(cols),
    color: null,
  }));

  const setRow = (y, text, color = null) => {
    if (y < 0 || y >= rows) {
      return;
    }

    frameRows[y] = {
      text: String(text ?? "").slice(0, cols).padEnd(cols, " "),
      color,
    };
  };

  const promptText = commandBufferQuery ? `${PROMPT_PREFIX}/${commandBufferQuery}` : `${PROMPT_PREFIX}/`;
  setRow(0, promptText);
  setRow(1, "");

  if (commands.length === 0) {
    setRow(2, "  no commands", PLACEHOLDER_COLOR);
  } else {
    const end = Math.min(commands.length, commandMenuScroll + visibleCount);
    let row = 2;
    for (let i = commandMenuScroll; i < end; i += 1) {
      const command = commands[i];
      const selected = i === commandMenuSelected;
      const text = `  ${command.name}  ${command.description}`;
      setRow(row, text, selected ? BLUE_COLOR : null);
      row += 1;
    }
  }

  if (rows > 0) {
    setRow(rows - 1, "Enter: run  Esc: close", PLACEHOLDER_COLOR);
  }

  for (let y = 0; y < rows; y += 1) {
    const nextRow = frameRows[y];
    const prevRow = lastCommandRenderedRows[y];
    if (prevRow && prevRow.text === nextRow.text && prevRow.color === nextRow.color) {
      continue;
    }

    if (nextRow.color === BLUE_COLOR) {
      writeColoredLine(y, nextRow.text, cols, BLUE_COLOR);
    } else if (nextRow.color === PLACEHOLDER_COLOR) {
      writeColoredLine(y, nextRow.text, cols, PLACEHOLDER_COLOR);
    } else {
      writeLine(y, nextRow.text, cols);
    }
  }

  lastCommandRenderedRows = frameRows;
  const cursorX = Math.min(promptText.length, Math.max(0, cols - 1));
  readline.cursorTo(process.stdout, cursorX, 0);
  process.stdout.write(SHOW_CURSOR);
  dirty = false;
}

function renderModelBuffer() {
  process.stdout.write(HIDE_CURSOR);

  const rows = process.stdout.rows || 24;
  const cols = process.stdout.columns || 80;
  updateModelSelectionState();
  const models = getFilteredModels();
  const visibleCount = getModelVisibleCount();
  const listHeight = visibleCount * 2;
  const panelWidth = Math.min(Math.max(40, Math.floor(cols * 0.72)), cols);
  const blockHeight = listHeight + 2;
  const blockTop = Math.max(0, Math.floor((rows - blockHeight) / 2));
  const panelLeft = Math.max(0, Math.floor((cols - panelWidth) / 2));
  const searchInputRow = blockTop;
  const listTop = blockTop + 2;

  if (!hasInitializedScreen) {
    readline.cursorTo(process.stdout, 0, 0);
    readline.clearScreenDown(process.stdout);
    hasInitializedScreen = true;
  }

  if (forceFullClearOnNextRender) {
    readline.cursorTo(process.stdout, 0, 0);
    readline.clearScreenDown(process.stdout);
    forceFullClearOnNextRender = false;
    lastModelRenderedRows = [];
    lastModelRenderedCols = 0;
    lastModelRenderedHeight = 0;
  }

  if (lastModelRenderedCols !== cols || lastModelRenderedHeight !== rows) {
    lastModelRenderedRows = [];
    lastModelRenderedCols = cols;
    lastModelRenderedHeight = rows;
  }

  const frameRows = Array.from({ length: rows }, () => ({
    text: " ".repeat(cols),
    color: null,
  }));

  const setPanelRow = (y, content, color = null) => {
    if (y < 0 || y >= rows) {
      return;
    }

    const clipped = content.slice(0, panelWidth).padEnd(panelWidth, " ");
    const left = " ".repeat(panelLeft);
    const right = " ".repeat(Math.max(0, cols - panelLeft - panelWidth));
    frameRows[y] = { text: `${left}${clipped}${right}`.slice(0, cols), color };
  };

  if (modelSearch) {
    setPanelRow(searchInputRow, `> ${modelSearch}`);
  } else {
    setPanelRow(searchInputRow, "> search model", PLACEHOLDER_COLOR);
  }

  let lines = [];
  if (isModelsLoading && models.length === 0) {
    lines = [{ text: "  loading models...", selected: false, muted: true, kind: "status" }];
  } else if (modelsLoadError && models.length === 0) {
    lines = [{ text: `  ${modelsLoadError}`, selected: false, muted: true, kind: "status" }];
  } else if (models.length === 0) {
    lines = [{ text: "  no models", selected: false, muted: true, kind: "status" }];
  } else {
    const end = Math.min(models.length, modelScroll + visibleCount);
    for (let i = modelScroll; i < end; i += 1) {
      const model = models[i];
      const marker = i === modelSelected ? "●" : "○";
      lines.push({
        text: `  ${marker} ${model.id}`,
        selected: i === modelSelected,
        muted: false,
        kind: "model",
      });
      lines.push({
        text: formatModelModalities(model),
        selected: i === modelSelected,
        muted: true,
        kind: "modalities",
      });
    }
  }

  for (let i = 0; i < listHeight; i += 1) {
    const row = lines[i];
    const y = listTop + i;
    if (!row) {
      setPanelRow(y, "");
      continue;
    }

    if (row.kind === "modalities" || row.muted) {
      setPanelRow(y, row.text, PLACEHOLDER_COLOR);
    } else if (row.selected) {
      setPanelRow(y, row.text, BLUE_COLOR);
    } else {
      setPanelRow(y, row.text);
    }
  }

  const footer = getMainFooterText();
  const footerX = Math.max(0, cols - footer.length);
  if (rows > 0) {
    const footerLine =
      `${" ".repeat(footerX)}${footer}`.slice(0, cols).padEnd(cols, " ");
    frameRows[rows - 1] = { text: footerLine, color: null };
  }

  for (let y = 0; y < rows; y += 1) {
    const nextRow = frameRows[y];
    const prevRow = lastModelRenderedRows[y];
    if (prevRow && prevRow.text === nextRow.text && prevRow.color === nextRow.color) {
      continue;
    }

    if (nextRow.color === BLUE_COLOR) {
      writeColoredLine(y, nextRow.text, cols, BLUE_COLOR);
    } else if (nextRow.color === PLACEHOLDER_COLOR) {
      writeColoredLine(y, nextRow.text, cols, PLACEHOLDER_COLOR);
    } else {
      writeLine(y, nextRow.text, cols);
    }
  }

  lastModelRenderedRows = frameRows;

  const cursorX = Math.min(panelLeft + 2 + modelSearch.length, panelLeft + panelWidth - 1);
  readline.cursorTo(process.stdout, cursorX, searchInputRow);
  readline.cursorTo(process.stdout, cursorX, searchInputRow);
  process.stdout.write(SHOW_CURSOR);
  dirty = false;
}

function renderSessionsBuffer() {
  process.stdout.write(HIDE_CURSOR);

  const rows = process.stdout.rows || 24;
  const cols = process.stdout.columns || 80;
  const panelWidth = Math.min(Math.max(60, Math.floor(cols * 0.85)), cols);
  const panelLeft = Math.max(0, Math.floor((cols - panelWidth) / 2));
  const visibleCount = getSessionsVisibleCount();
  updateSessionsSelectionState();

  if (!hasInitializedScreen) {
    readline.cursorTo(process.stdout, 0, 0);
    readline.clearScreenDown(process.stdout);
    hasInitializedScreen = true;
  }

  if (forceFullClearOnNextRender) {
    readline.cursorTo(process.stdout, 0, 0);
    readline.clearScreenDown(process.stdout);
    forceFullClearOnNextRender = false;
    lastSessionsRenderedRows = [];
    lastSessionsRenderedCols = 0;
    lastSessionsRenderedHeight = 0;
  }

  if (lastSessionsRenderedCols !== cols || lastSessionsRenderedHeight !== rows) {
    lastSessionsRenderedRows = [];
    lastSessionsRenderedCols = cols;
    lastSessionsRenderedHeight = rows;
  }

  const frameRows = Array.from({ length: rows }, () => ({
    text: " ".repeat(cols),
    color: null,
  }));

  const setPanelRow = (y, content, color = null) => {
    if (y < 0 || y >= rows) {
      return;
    }

    const clipped = content.slice(0, panelWidth).padEnd(panelWidth, " ");
    const left = " ".repeat(panelLeft);
    const right = " ".repeat(Math.max(0, cols - panelLeft - panelWidth));
    frameRows[y] = { text: `${left}${clipped}${right}`.slice(0, cols), color };
  };

  setPanelRow(0, "Sessions (most recent first)");

  if (isSessionsLoading && sessionFiles.length === 0) {
    setPanelRow(2, "loading sessions...", PLACEHOLDER_COLOR);
  } else if (sessionsLoadError && sessionFiles.length === 0) {
    setPanelRow(2, sessionsLoadError, PLACEHOLDER_COLOR);
  } else if (sessionFiles.length === 0) {
    setPanelRow(2, "no session files", PLACEHOLDER_COLOR);
  } else {
    const end = Math.min(sessionFiles.length, sessionsScroll + visibleCount);
    for (let i = sessionsScroll; i < end; i += 1) {
      const row = 2 + (i - sessionsScroll);
      const entry = sessionFiles[i];
      const marker = i === sessionsSelected ? "●" : "○";
      const text = `  ${marker} ${entry.name}  updated: ${formatUpdatedTime(entry.updatedAt)}`;
      if (i === sessionsSelected) {
        setPanelRow(row, text, BLUE_COLOR);
      } else {
        setPanelRow(row, text);
      }
    }
  }

  setPanelRow(rows - 1, "Esc to return", PLACEHOLDER_COLOR);

  for (let y = 0; y < rows; y += 1) {
    const nextRow = frameRows[y];
    const prevRow = lastSessionsRenderedRows[y];
    if (prevRow && prevRow.text === nextRow.text && prevRow.color === nextRow.color) {
      continue;
    }

    if (nextRow.color === BLUE_COLOR) {
      writeColoredLine(y, nextRow.text, cols, BLUE_COLOR);
    } else if (nextRow.color === PLACEHOLDER_COLOR) {
      writeColoredLine(y, nextRow.text, cols, PLACEHOLDER_COLOR);
    } else {
      writeLine(y, nextRow.text, cols);
    }
  }

  lastSessionsRenderedRows = frameRows;

  dirty = false;
}

function renderProvidersBuffer() {
  process.stdout.write(HIDE_CURSOR);

  const rows = process.stdout.rows || 24;
  const cols = process.stdout.columns || 80;
  const panelWidth = Math.min(Math.max(60, Math.floor(cols * 0.85)), cols);
  const panelLeft = Math.max(0, Math.floor((cols - panelWidth) / 2));
  const visibleCount = getProvidersVisibleCount();
  updateProvidersSelectionState();

  if (!hasInitializedScreen) {
    readline.cursorTo(process.stdout, 0, 0);
    readline.clearScreenDown(process.stdout);
    hasInitializedScreen = true;
  }

  if (forceFullClearOnNextRender) {
    readline.cursorTo(process.stdout, 0, 0);
    readline.clearScreenDown(process.stdout);
    forceFullClearOnNextRender = false;
    lastProvidersRenderedRows = [];
    lastProvidersRenderedCols = 0;
    lastProvidersRenderedHeight = 0;
  }

  if (lastProvidersRenderedCols !== cols || lastProvidersRenderedHeight !== rows) {
    lastProvidersRenderedRows = [];
    lastProvidersRenderedCols = cols;
    lastProvidersRenderedHeight = rows;
  }

  const frameRows = Array.from({ length: rows }, () => ({
    text: " ".repeat(cols),
    color: null,
  }));

  const setPanelRow = (y, content, color = null) => {
    if (y < 0 || y >= rows) {
      return;
    }
    const clipped = content.slice(0, panelWidth).padEnd(panelWidth, " ");
    const left = " ".repeat(panelLeft);
    const right = " ".repeat(Math.max(0, cols - panelLeft - panelWidth));
    frameRows[y] = { text: `${left}${clipped}${right}`.slice(0, cols), color };
  };

  setPanelRow(0, "Providers");

  if (isProvidersLoading && providers.length === 0) {
    setPanelRow(2, "loading providers...", PLACEHOLDER_COLOR);
  } else if (providersLoadError && providers.length === 0) {
    setPanelRow(2, providersLoadError, PLACEHOLDER_COLOR);
  } else if (providers.length === 0) {
    setPanelRow(2, "no providers", PLACEHOLDER_COLOR);
  } else {
    const end = Math.min(providers.length, providersScroll + visibleCount);
    for (let i = providersScroll; i < end; i += 1) {
      const row = 2 + (i - providersScroll);
      const entry = providers[i];
      const marker = i === providersSelected ? "\u25cf" : "\u25cb";
      const name = entry.name || "(unnamed provider)";
      const model = normalizeProviderModel(entry?.model) || "no model";
      const text = `  ${marker} ${name}  model: ${model}`;
      const isActiveProvider = entry.name === selectedProviderName;
      if (isActiveProvider) {
        setPanelRow(row, text, GREEN_COLOR);
      } else if (i === providersSelected) {
        setPanelRow(row, text, BLUE_COLOR);
      } else {
        setPanelRow(row, text);
      }
    }
  }

  setPanelRow(rows - 1, "Enter: select  F1: new  F2: edit  Del: delete  Esc: return", PLACEHOLDER_COLOR);

  for (let y = 0; y < rows; y += 1) {
    const nextRow = frameRows[y];
    const prevRow = lastProvidersRenderedRows[y];
    if (prevRow && prevRow.text === nextRow.text && prevRow.color === nextRow.color) {
      continue;
    }

    if (nextRow.color === BLUE_COLOR) {
      writeColoredLine(y, nextRow.text, cols, BLUE_COLOR);
    } else if (nextRow.color === GREEN_COLOR) {
      writeColoredLine(y, nextRow.text, cols, GREEN_COLOR);
    } else if (nextRow.color === PLACEHOLDER_COLOR) {
      writeColoredLine(y, nextRow.text, cols, PLACEHOLDER_COLOR);
    } else {
      writeLine(y, nextRow.text, cols);
    }
  }

  lastProvidersRenderedRows = frameRows;
  dirty = false;
}

function renderProviderEditorBuffer() {
  process.stdout.write(HIDE_CURSOR);

  const rows = process.stdout.rows || 24;
  const cols = process.stdout.columns || 80;
  const panelWidth = Math.min(Math.max(60, Math.floor(cols * 0.85)), cols);
  const panelLeft = Math.max(0, Math.floor((cols - panelWidth) / 2));
  const fields = getProviderEditorFields();
  const blockHeight = fields.length + 6;
  const blockTop = Math.max(0, Math.floor((rows - blockHeight) / 2));

  if (!hasInitializedScreen) {
    readline.cursorTo(process.stdout, 0, 0);
    readline.clearScreenDown(process.stdout);
    hasInitializedScreen = true;
  }

  if (forceFullClearOnNextRender) {
    readline.cursorTo(process.stdout, 0, 0);
    readline.clearScreenDown(process.stdout);
    forceFullClearOnNextRender = false;
    lastProviderEditorRenderedRows = [];
    lastProviderEditorRenderedCols = 0;
    lastProviderEditorRenderedHeight = 0;
  }

  if (lastProviderEditorRenderedCols !== cols || lastProviderEditorRenderedHeight !== rows) {
    lastProviderEditorRenderedRows = [];
    lastProviderEditorRenderedCols = cols;
    lastProviderEditorRenderedHeight = rows;
  }

  const frameRows = Array.from({ length: rows }, () => ({
    text: " ".repeat(cols),
    color: null,
  }));

  const setPanelRow = (y, content, color = null) => {
    if (y < 0 || y >= rows) {
      return;
    }
    const clipped = content.slice(0, panelWidth).padEnd(panelWidth, " ");
    const left = " ".repeat(panelLeft);
    const right = " ".repeat(Math.max(0, cols - panelLeft - panelWidth));
    frameRows[y] = { text: `${left}${clipped}${right}`.slice(0, cols), color };
  };

  setPanelRow(blockTop, providerEditorMode === "create" ? "New Provider" : "Edit Provider");
  setPanelRow(blockTop + 1, "");

  for (let i = 0; i < fields.length; i += 1) {
    const field = fields[i];
    const selected = i === providerEditorFieldIndex;
    const value = String(providerEditorDraft[field.key] || "");
    const prefix = selected ? "> " : "  ";
    setPanelRow(blockTop + 2 + i, `${prefix}${field.label}: ${value}`, selected ? BLUE_COLOR : null);
  }

  setPanelRow(blockTop + blockHeight - 1, "F1: save  Esc: cancel", PLACEHOLDER_COLOR);

  for (let y = 0; y < rows; y += 1) {
    const nextRow = frameRows[y];
    const prevRow = lastProviderEditorRenderedRows[y];
    if (prevRow && prevRow.text === nextRow.text && prevRow.color === nextRow.color) {
      continue;
    }

    if (nextRow.color === BLUE_COLOR) {
      writeColoredLine(y, nextRow.text, cols, BLUE_COLOR);
    } else if (nextRow.color === PLACEHOLDER_COLOR) {
      writeColoredLine(y, nextRow.text, cols, PLACEHOLDER_COLOR);
    } else {
      writeLine(y, nextRow.text, cols);
    }
  }

  lastProviderEditorRenderedRows = frameRows;

  const activeField = fields[providerEditorFieldIndex] || fields[0];
  const cursorRow = blockTop + 2 + providerEditorFieldIndex;
  const cursorPrefix = `> ${activeField.label}: `;
  const cursorValue = String(providerEditorDraft[activeField.key] || "");
  const cursorX = Math.min(panelLeft + cursorPrefix.length + cursorValue.length, Math.max(0, cols - 1));
  readline.cursorTo(process.stdout, cursorX, Math.max(0, Math.min(rows - 1, cursorRow)));
  process.stdout.write(SHOW_CURSOR);
  dirty = false;
}

function renderFrame(forceChatRefresh = false) {
  if (forceChatRefreshFlag) {
    forceChatRefresh = true;
    forceChatRefreshFlag = false;
  }
  updateThinkingAnimationState();

  if (activeBuffer === "command") {
    renderCommandBuffer();
    return;
  }
  if (activeBuffer === "model") {
    renderModelBuffer();
    return;
  }
  if (activeBuffer === "sessions") {
    renderSessionsBuffer();
    return;
  }
  if (activeBuffer === "providers") {
    renderProvidersBuffer();
    return;
  }
  if (activeBuffer === "provider_editor") {
    renderProviderEditorBuffer();
    return;
  }

  if (!dirty && !forceChatRefresh) {
    return;
  }

  process.stdout.write(HIDE_CURSOR);

  const rows = process.stdout.rows || 24;
  const cols = process.stdout.columns || 80;
  updateCommandMenuState();
  const inputVisualLines = buildInputVisualLines(cols);
  const menuLines = getCommandMenuVisualLines(cols);
  const menuHeight = menuLines.length;
  const footerVisible = !APPEND_CHAT_TO_SCROLLBACK && input.length === 0 && menuHeight === 0;
  const footerHeight = menuHeight > 0 ? 0 : 1;
  const activeBottomPadding = menuHeight > 0 ? BOTTOM_PADDING : INPUT_BOTTOM_PADDING_NO_MENU;
  const frameHeight = inputVisualLines.length;
  const cursorMetrics = getInputCursorMetrics(cols);
  const statusText = getStatusBarText();
  const statusVisible = statusText.length > 0 || isMcpStartupStatusVisible();
  const statusRows = statusVisible ? STATUS_BAR_ROWS : 0;
  const statusChatGapRows = statusVisible ? STATUS_CHAT_GAP : 0;
  const statusInputGapRows = statusVisible ? STATUS_INPUT_GAP : 0;
  const chatInputGapRows = getViewportChatInputGapRows(statusVisible);
  const footerBlockHeight = menuHeight > 0 ? 0 : MAIN_FOOTER_GAP + footerHeight;
  const menuBlockHeight = footerBlockHeight + (menuHeight > 0 ? MENU_INPUT_GAP + menuHeight : 0);
  const neededReservedRows = getAppendReservedBottomRowsFromLayout(
    frameHeight,
    menuHeight
  );
  const allocationRows = neededReservedRows;

  if (!hasInitializedScreen && !APPEND_CHAT_TO_SCROLLBACK) {
    readline.cursorTo(process.stdout, 0, 0);
    readline.clearScreenDown(process.stdout);
    hasInitializedScreen = true;
  } else if (!hasInitializedScreen) {
    ensureAppendReservedBottomRows(allocationRows, rows, cols);
    hasInitializedScreen = true;
  } else if (APPEND_CHAT_TO_SCROLLBACK) {
    ensureAppendReservedBottomRows(allocationRows, rows, cols);
  }

  if (APPEND_CHAT_TO_SCROLLBACK && forceFullClearOnNextRender) {
    forceFullClearOnNextRender = false;
    lastFrameTop = null;
    lastFrameHeight = 0;
    lastChatAreaHeight = null;
    lastMenuTop = null;
    lastMenuHeight = 0;
    lastFooterTop = null;
    lastStatusTop = null;
    lastStatusHeight = 0;
    lastMenuRenderedLines = [];
  }

  let frameTop;
  if (APPEND_CHAT_TO_SCROLLBACK) {
    const reservedTop = Math.max(0, rows - Math.min(rows, neededReservedRows));
    const appendChatGap = menuHeight > 0 ? 0 : CHAT_INPUT_GAP;
    frameTop = Math.min(
      rows - 1,
      reservedTop + appendChatGap + statusChatGapRows + statusRows + statusInputGapRows
    );
  } else {
    // Keep composer fixed in viewport mode; status is painted as an overlay block.
    frameTop = Math.max(0, rows - activeBottomPadding - menuBlockHeight - frameHeight);
  }
  let inputViewportOffset = 0;
  let renderedFrameHeight = frameHeight;
  if (APPEND_CHAT_TO_SCROLLBACK) {
    const menuBlockRows = menuHeight > 0 ? MENU_INPUT_GAP + menuHeight : 0;
    const availableInputRows = Math.max(
      1,
      rows - frameTop - statusInputGapRows - statusRows - menuBlockRows
    );
    renderedFrameHeight = Math.min(frameHeight, availableInputRows);
    const maxOffset = Math.max(0, frameHeight - renderedFrameHeight);
    inputViewportOffset = Math.max(
      0,
      Math.min(maxOffset, cursorMetrics.row - renderedFrameHeight + 1)
    );
  }
  const statusTop = Math.max(0, frameTop - statusRows - statusInputGapRows);
  const statusBlockTop = statusVisible ? Math.max(0, statusTop - statusChatGapRows) : statusTop;
  const statusBlockHeight = statusVisible
    ? statusChatGapRows + statusRows + statusInputGapRows
    : 0;
  const footerTop = frameTop + renderedFrameHeight + MAIN_FOOTER_GAP;
  const menuTopBase = footerVisible ? (footerTop + 1) : (frameTop + renderedFrameHeight);
  const menuTop = menuTopBase + (menuHeight > 0 ? MENU_INPUT_GAP : 0);
  const chatAreaHeight = APPEND_CHAT_TO_SCROLLBACK
    ? 0
    : Math.max(0, frameTop - chatInputGapRows);
  const allChatLines = APPEND_CHAT_TO_SCROLLBACK ? [] : buildChatVisualLines(cols);
  const currentRenderableMessageCount = APPEND_CHAT_TO_SCROLLBACK
    ? 0
    : messages.filter((entry) => isRenderableChatEntry(entry)).length;
  const maxScrollOffset = APPEND_CHAT_TO_SCROLLBACK
    ? 0
    : Math.max(0, allChatLines.length - chatAreaHeight);
  if (chatScrollOffset > maxScrollOffset) {
    chatScrollOffset = maxScrollOffset;
  } else if (chatScrollOffset < 0) {
    chatScrollOffset = 0;
  }
  const chatEnd = Math.max(0, allChatLines.length - chatScrollOffset);
  const chatStart = Math.max(0, chatEnd - chatAreaHeight);
  const chatVisualLines = allChatLines.slice(chatStart, chatEnd);
  const menuLayoutChanged =
    lastMenuTop === null ||
    lastMenuTop !== menuTop ||
    lastMenuHeight !== menuHeight;
  const statusLayoutChanged =
    !APPEND_CHAT_TO_SCROLLBACK &&
    (lastStatusTop === null ||
      lastStatusTop !== statusBlockTop ||
      lastStatusHeight !== statusBlockHeight);
  const statusVisibilityChanged = APPEND_CHAT_TO_SCROLLBACK
    ? false
    : lastStatusVisible !== statusVisible;
  if (statusVisibilityChanged && !APPEND_CHAT_TO_SCROLLBACK) {
    // Cleanly redraw the whole screen when entering/leaving the thinking
    // state so stale status rows cannot overlap chat or input text.
    forceFullClearOnNextRender = true;
  }

  if (!APPEND_CHAT_TO_SCROLLBACK && forceFullClearOnNextRender) {
    readline.cursorTo(process.stdout, 0, 0);
    readline.clearScreenDown(process.stdout);
    forceFullClearOnNextRender = false;
    lastFrameTop = null;
    lastFrameHeight = 0;
    lastChatAreaHeight = null;
    lastMenuTop = null;
    lastMenuHeight = 0;
    lastFooterTop = null;
    lastStatusTop = null;
    lastStatusHeight = 0;
    lastMenuRenderedLines = [];
    lastRenderableMessageCount = -1;
  }

  const needsChatRefresh =
    !APPEND_CHAT_TO_SCROLLBACK &&
    (forceChatRefresh ||
      currentRenderableMessageCount !== lastRenderableMessageCount ||
      statusLayoutChanged ||
      lastChatAreaHeight === null ||
      chatAreaHeight !== lastChatAreaHeight ||
      menuLayoutChanged);

  const chatStartRow = Math.max(0, chatAreaHeight - chatVisualLines.length);
  const revealActiveNow =
    !APPEND_CHAT_TO_SCROLLBACK &&
    chatScrollOffset === 0 &&
    (hasActiveAnswerReveal() || answerRevealSettlePending) &&
    lastEntryVisualStartIndex >= 0;

  if (revealActiveNow) {
    // Repaint every visible chat row in place (no clear step): static rows
    // are rewritten with identical content (invisible), while the revealing
    // message gets the current fade color. This also self-heals any
    // full-screen clear that happened this frame (arrival or status-bar
    // collapse) so the rest of the chat never disappears mid-fade.
    for (let i = 0; i < chatVisualLines.length; i += 1) {
      const row = chatStartRow + i;
      const line = chatVisualLines[i];
      if (line.styledText) {
        writeStyledLine(row, line.text, line.styledText, cols);
      } else if (line.color === GREEN_COLOR) {
        writeColoredLine(row, line.text, cols, GREEN_COLOR);
      } else if (line.color === RED_COLOR) {
        writeColoredLine(row, line.text, cols, RED_COLOR);
      } else if (line.color === PLACEHOLDER_COLOR) {
        writeColoredLine(row, line.text, cols, PLACEHOLDER_COLOR);
      } else {
        writeLine(row, line.text, cols);
        if (line.assistantBulletMuted) {
          readline.cursorTo(process.stdout, CHAT_LEFT_PADDING.length, row);
          process.stdout.write(`${PLACEHOLDER_COLOR}\u2022${RESET_COLOR}`);
        }
      }
    }
    answerRevealSettlePending = false;
  } else if (needsChatRefresh) {
    const oldChatHeight = lastChatAreaHeight ?? 0;
    const chatClearHeight = Math.max(chatAreaHeight, oldChatHeight);
    for (let y = 0; y < chatClearHeight; y += 1) {
      writeLine(y, "", cols);
    }

    for (let i = 0; i < chatVisualLines.length; i += 1) {
      if (chatVisualLines[i].styledText) {
        writeStyledLine(
          chatStartRow + i,
          chatVisualLines[i].text,
          chatVisualLines[i].styledText,
          cols
        );
      } else if (chatVisualLines[i].color === GREEN_COLOR) {
        writeColoredLine(chatStartRow + i, chatVisualLines[i].text, cols, GREEN_COLOR);
      } else if (chatVisualLines[i].color === RED_COLOR) {
        writeColoredLine(chatStartRow + i, chatVisualLines[i].text, cols, RED_COLOR);
      } else if (chatVisualLines[i].color === PLACEHOLDER_COLOR) {
        writeColoredLine(chatStartRow + i, chatVisualLines[i].text, cols, PLACEHOLDER_COLOR);
      } else {
        writeLine(chatStartRow + i, chatVisualLines[i].text, cols);
        if (chatVisualLines[i].assistantBulletMuted) {
          readline.cursorTo(process.stdout, CHAT_LEFT_PADDING.length, chatStartRow + i);
          process.stdout.write(`${PLACEHOLDER_COLOR}\u2022${RESET_COLOR}`);
        }
      }
    }
  }

  const oldTop = lastFrameTop ?? frameTop;
  const oldBottom = oldTop + (lastFrameHeight ?? renderedFrameHeight);
  const oldFooterTopValue = lastFooterTop ?? (footerTop ?? frameTop);
  const oldFooterBottom = oldFooterTopValue + 1;
  const oldStatusTopValue = lastStatusTop ?? statusBlockTop;
  const oldStatusBottom = oldStatusTopValue + (lastStatusHeight || 0);
  const oldMenuTopValue = lastMenuTop ?? menuTop;
  const oldMenuBottom = oldMenuTopValue + (lastMenuHeight ?? menuHeight);
  const newBottom = frameTop + renderedFrameHeight;
  const newFooterBottom = (footerTop ?? oldFooterTopValue) + 1;
  const newStatusBottom = statusBlockTop + statusBlockHeight;
  const newMenuBottom = menuTop + menuHeight;
  const paintTop = Math.max(
    0,
    Math.min(
      Math.min(oldTop, frameTop),
      Math.min(oldMenuTopValue, menuTop),
      Math.min(oldFooterTopValue, footerTop ?? oldFooterTopValue),
      Math.min(oldStatusTopValue, statusTop)
    )
  );
  const paintBottom = Math.min(
    rows,
    Math.max(
      Math.max(oldBottom, newBottom),
      Math.max(oldMenuBottom, newMenuBottom),
      Math.max(oldFooterBottom, newFooterBottom),
      Math.max(oldStatusBottom, newStatusBottom)
    )
  );

  const rowMap = new Map();
  for (let i = 0; i < menuLines.length; i += 1) {
    rowMap.set(menuTop + i, {
      type: menuLines[i].selected ? "blue" : menuLines[i].muted ? "muted" : "plain",
      text: menuLines[i].text,
    });
  }

  if (APPEND_CHAT_TO_SCROLLBACK) {
    for (let i = 0; i < renderedFrameHeight; i += 1) {
      const lineIndex = inputViewportOffset + i;
      rowMap.set(frameTop + i, {
        type: !input ? "placeholder" : "plain",
        text: inputVisualLines[lineIndex] || "",
      });
    }
  } else {
    for (let i = 0; i < inputVisualLines.length; i += 1) {
      rowMap.set(frameTop + i, {
        type: !input ? "placeholder" : "plain",
        text: inputVisualLines[i],
      });
    }
  }

  if (statusVisible) {
    for (let i = 0; i < statusChatGapRows; i += 1) {
      rowMap.set(statusBlockTop + i, { type: "plain", text: "" });
    }
    for (let i = 0; i < statusRows; i += 1) {
      rowMap.set(statusTop + i, {
        type: "status",
        text: i === statusRows - 1 ? statusText : "",
      });
    }
    for (let i = 0; i < statusInputGapRows; i += 1) {
      rowMap.set(statusTop + statusRows + i, { type: "plain", text: "" });
    }
  }

  if (footerVisible && footerTop !== null) {
    rowMap.set(footerTop, {
      type: "footer",
      text: getMainFooterText(),
    });
  }

  const paintRow = (y) => {
    const row = rowMap.get(y);
    if (!row) {
      if (!APPEND_CHAT_TO_SCROLLBACK && y < chatAreaHeight) {
        // Chat rows are painted by the chat pass above. Avoid clearing them here.
        return;
      }
      writeLine(y, "", cols);
      return;
    }

    if (row.type === "blue") {
      writeColoredLine(y, row.text, cols, BLUE_COLOR);
    } else if (row.type === "muted") {
      writeColoredLine(y, row.text, cols, PLACEHOLDER_COLOR);
    } else if (row.type === "footer") {
      writeColoredLine(y, row.text, cols, PLACEHOLDER_COLOR);
    } else if (row.type === "status") {
      if (row.text) {
        writeColoredLine(y, row.text, cols, PLACEHOLDER_COLOR);
      } else {
        writeLine(y, "", cols);
      }
    } else if (row.type === "placeholder") {
      writePlaceholderLine(y, row.text, cols);
    } else {
      writeLine(y, row.text, cols);
    }
  };

  if (APPEND_CHAT_TO_SCROLLBACK) {
    const reservedRows = Math.max(1, Math.min(rows, neededReservedRows));
    const reservedTop = Math.max(0, rows - reservedRows);
    const appendPaintTop = reservedTop;
    for (let y = appendPaintTop; y < rows; y += 1) {
      paintRow(y);
    }
  } else {
    for (let y = paintTop; y < paintBottom; y += 1) {
      paintRow(y);
    }
  }

  const cursor = getCursorPosition(cols, frameTop, inputViewportOffset, cursorMetrics);
  readline.cursorTo(process.stdout, cursor.x, cursor.y);
  process.stdout.write(SHOW_CURSOR);

  lastFrameTop = frameTop;
  lastFrameHeight = renderedFrameHeight;
  lastChatAreaHeight = chatAreaHeight;
  if (!APPEND_CHAT_TO_SCROLLBACK) {
    lastRenderableMessageCount = currentRenderableMessageCount;
  }
  lastMenuTop = menuTop;
  lastMenuHeight = menuHeight;
  lastFooterTop = footerTop;
  lastStatusTop = statusBlockTop;
  lastStatusHeight = statusBlockHeight;
  lastStatusVisible = statusVisible;
  lastMenuRenderedLines = menuLines.map((line) => ({ ...line }));
  dirty = false;
}

function renderMenuOnly() {
  if (!isCommandMenuVisible()) {
    return;
  }
  if (APPEND_CHAT_TO_SCROLLBACK) {
    markDirty();
    renderFrame(true);
    return;
  }

  process.stdout.write(HIDE_CURSOR);

  const rows = process.stdout.rows || 24;
  const cols = process.stdout.columns || 80;
  updateCommandMenuState();
  const inputVisualLines = buildInputVisualLines(cols);
  const menuLines = getCommandMenuVisualLines(cols);
  const menuHeight = menuLines.length;
  const footerVisible = !APPEND_CHAT_TO_SCROLLBACK && input.length === 0 && menuHeight === 0;
  const footerHeight = menuHeight > 0 ? 0 : 1;
  const frameHeight = inputVisualLines.length;
  const activeBottomPadding = menuHeight > 0 ? BOTTOM_PADDING : INPUT_BOTTOM_PADDING_NO_MENU;
  const footerBlockHeight = menuHeight > 0 ? 0 : MAIN_FOOTER_GAP + footerHeight;
  const menuBlockHeight = footerBlockHeight + (menuHeight > 0 ? MENU_INPUT_GAP + menuHeight : 0);
  const frameTop = Math.max(0, rows - activeBottomPadding - menuBlockHeight - frameHeight);
  const footerTop = frameTop + frameHeight + MAIN_FOOTER_GAP;
  const menuTopBase = footerVisible ? (footerTop + 1) : (frameTop + frameHeight);
  const menuTop = menuTopBase + (menuHeight > 0 ? MENU_INPUT_GAP : 0);

  const oldTop = lastMenuTop ?? menuTop;
  const oldLines = lastMenuRenderedLines;
  const maxLines = Math.max(oldLines.length, menuLines.length);

  for (let i = 0; i < maxLines; i += 1) {
    const oldLine = oldLines[i];
    const newLine = menuLines[i];
    const targetRow = menuTop + i;
    const oldRow = oldTop + i;

    if (
      oldTop === menuTop &&
      oldLine &&
      newLine &&
      oldLine.text === newLine.text &&
      oldLine.selected === newLine.selected
    ) {
      continue;
    }

    if (oldRow !== targetRow && oldLine) {
      writeLine(oldRow, "", cols);
    }

    if (!newLine) {
      writeLine(targetRow, "", cols);
    } else if (newLine.selected) {
      writeColoredLine(targetRow, newLine.text, cols, BLUE_COLOR);
    } else if (newLine.muted) {
      writeColoredLine(targetRow, newLine.text, cols, PLACEHOLDER_COLOR);
    } else {
      writeLine(targetRow, newLine.text, cols);
    }
  }

  const cursor = getCursorPosition(cols, frameTop);
  readline.cursorTo(process.stdout, cursor.x, cursor.y);
  process.stdout.write(SHOW_CURSOR);

  lastMenuTop = menuTop;
  lastMenuHeight = menuHeight;
  lastMenuRenderedLines = menuLines.map((line) => ({ ...line }));
}

function markDirty() {
  dirty = true;
}

function cancelIdleFlush() {
  if (flushTimer) {
    clearTimeout(flushTimer);
    flushTimer = null;
  }
}

function scheduleIdleFlush() {
  markDirty();

  cancelIdleFlush();

  flushTimer = setTimeout(() => {
    flushTimer = null;
    render();
    burstMode = false;
  }, IDLE_FLUSH_MS);
}

function scheduleViewportMainRefresh() {
  if (APPEND_CHAT_TO_SCROLLBACK || activeBuffer !== "main") {
    return;
  }

  setTimeout(() => {
    if (cleanedUp || activeBuffer !== "main") {
      return;
    }
    markDirty();
    renderFrame(true);
  }, 0);
}

function scheduleAdaptiveRender() {
  const now = Date.now();
  const gap = now - lastInputEventAt;
  lastInputEventAt = now;

  if (gap > 0 && gap < FAST_KEY_GAP_MS) {
    burstMode = true;
  }

  if (burstMode) {
    scheduleIdleFlush();
    return;
  }

  cancelIdleFlush();
  markDirty();
  render();
}

function scheduleInputRender(menuWasVisible, noCommandsWasVisible) {
  const menuNowVisible = isCommandMenuVisible();
  const noCommandsNowVisible = isNoCommandsState();
  if (menuWasVisible !== menuNowVisible) {
    // Incremental clearing can leave stale rows in some terminals on layout shift.
    // Do a one-time full clear whenever menu visibility toggles.
    if (!APPEND_CHAT_TO_SCROLLBACK) {
      forceFullClearOnNextRender = true;
    }

    cancelIdleFlush();
    burstMode = false;
    markDirty();
    renderFrame(true);
    return;
  }

  if (noCommandsWasVisible !== noCommandsNowVisible) {
    cancelIdleFlush();
    burstMode = false;
    markDirty();
    render();
    return;
  }

  scheduleAdaptiveRender();
}

function resetSubmittedInputHistoryNavigation() {
  submittedInputHistoryIndex = -1;
  submittedInputHistoryDraft = "";
}

function commitSubmittedInputHistory(text) {
  const value = typeof text === "string" ? text.replace(/\r\n/g, "\n").replace(/\r/g, "\n") : "";
  if (!/\S/.test(value)) {
    resetSubmittedInputHistoryNavigation();
    return;
  }

  submittedInputHistory.push(value);
  if (submittedInputHistory.length > MAX_INPUT_HISTORY_ITEMS) {
    submittedInputHistory = submittedInputHistory.slice(
      submittedInputHistory.length - MAX_INPUT_HISTORY_ITEMS
    );
  }
  resetSubmittedInputHistoryNavigation();
}

function browseSubmittedInputHistory(direction) {
  if (!Array.isArray(submittedInputHistory) || submittedInputHistory.length === 0) {
    return false;
  }

  if (direction < 0) {
    if (submittedInputHistoryIndex === -1) {
      submittedInputHistoryDraft = input;
      submittedInputHistoryIndex = submittedInputHistory.length - 1;
    } else if (submittedInputHistoryIndex > 0) {
      submittedInputHistoryIndex -= 1;
    } else {
      return false;
    }
  } else if (direction > 0) {
    if (submittedInputHistoryIndex === -1) {
      return false;
    }
    if (submittedInputHistoryIndex < submittedInputHistory.length - 1) {
      submittedInputHistoryIndex += 1;
    } else {
      submittedInputHistoryIndex = -1;
      input = submittedInputHistoryDraft;
      submittedInputHistoryDraft = "";
      inputCursorIndex = input.length;
      updateCommandMenuState();
      return true;
    }
  } else {
    return false;
  }

  input = submittedInputHistory[submittedInputHistoryIndex] || "";
  inputCursorIndex = input.length;
  updateCommandMenuState();
  return true;
}

function breakSubmittedInputHistoryNavigation() {
  if (submittedInputHistoryIndex !== -1) {
    resetSubmittedInputHistoryNavigation();
  }
}

function submit() {
  if (!input || input.length === 0) {
    return false;
  }

  const submittedInput = input;
  const resolvedContent = resolvePastedPlaceholders(input)
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n");
  if (!/\S/.test(resolvedContent)) {
    return false;
  }

  ensureSystemMessageAtTop();
  messages.push({ role: "user", content: resolvedContent });
  appendHistoryEntry("user", resolvedContent);
  commitSubmittedInputHistory(submittedInput);
  input = "";
  inputCursorIndex = 0;
  commandMenuDismissed = false;
  commandMenuSelected = 0;
  commandMenuScroll = 0;
  syncImagePasteCounter();
  scrollChatToBottom();
  return true;
}

function appendText(chunk) {
  const normalized = chunk.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  const now = Date.now();

  if (now < suppressIncomingUntil) {
    if (normalized.length > 0 && (normalized.length > 1 || normalized.includes("\n"))) {
      appendToActiveBlockedPastePayload(normalized);
      suppressIncomingUntil = now + PASTE_BURST_BLOCK_MS;
    }
    return;
  }
  activeBlockedPastePayloadIndex = -1;

  if (looksLikeImagePaste(normalized)) {
    breakSubmittedInputHistoryNavigation();
    const imagePayload = extractImagePayloadFromText(normalized);
    insertImagePlaceholder(imagePayload);
    suppressIncomingUntil = now + PASTE_BURST_BLOCK_MS;
    return;
  }

  if (shouldBlockPastedInput(normalized)) {
    breakSubmittedInputHistoryNavigation();
    activeBlockedPastePayloadIndex = insertPastePlaceholderFromText(normalized);
    suppressIncomingUntil = now + PASTE_BURST_BLOCK_MS;
    return;
  }

  if (now - burstWindowStartAt > PASTE_BURST_WINDOW_MS) {
    burstWindowStartAt = now;
    burstWindowChars = 0;
    burstWindowNewlines = 0;
    burstWindowEvents = 0;
    burstWindowContent = "";
    burstSnapshotInput = input;
    burstSnapshotCursor = inputCursorIndex;
  }

  burstWindowEvents += 1;
  burstWindowChars += normalized.length;
  burstWindowNewlines += (normalized.match(/\n/g) || []).length;
  burstWindowContent += normalized;
  const rapidMultilineBurst =
    burstWindowEvents >= PASTE_BURST_EVENT_THRESHOLD &&
    burstWindowNewlines >= 2 &&
    burstWindowChars >= PASTE_BURST_MIN_CHARS_RAPID_MULTILINE;
  const looksLikeBurstPaste =
    burstWindowChars >= PASTE_BURST_CHAR_THRESHOLD ||
    rapidMultilineBurst ||
    (burstWindowNewlines >= PASTE_BURST_NEWLINE_THRESHOLD &&
      burstWindowChars >= PASTE_BURST_MIN_CHARS_WITH_NEWLINES);

  if (looksLikeBurstPaste) {
    breakSubmittedInputHistoryNavigation();
    input = burstSnapshotInput;
    inputCursorIndex = burstSnapshotCursor;
    if (looksLikeImagePaste(burstWindowContent)) {
      const imagePayload = extractImagePayloadFromText(burstWindowContent);
      insertImagePlaceholder(imagePayload);
      activeBlockedPastePayloadIndex = -1;
    } else {
      activeBlockedPastePayloadIndex = insertPastePlaceholderByCount(
        burstWindowChars,
        burstWindowContent
      );
    }
    suppressIncomingUntil = now + PASTE_BURST_BLOCK_MS;
    burstWindowEvents = 0;
    burstWindowChars = 0;
    burstWindowNewlines = 0;
    burstWindowContent = "";
    updateCommandMenuState();
    return;
  }

  breakSubmittedInputHistoryNavigation();
  input = `${input.slice(0, inputCursorIndex)}${normalized}${input.slice(inputCursorIndex)}`;
  inputCursorIndex += normalized.length;
  updateCommandMenuState();
}

function applyBracketedPaste(text) {
  const normalized = text.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  const now = Date.now();
  const menuWasVisible = isCommandMenuVisible();
  const noCommandsWasVisible = isNoCommandsState();
  activeBlockedPastePayloadIndex = -1;

  if (looksLikeImagePaste(normalized)) {
    breakSubmittedInputHistoryNavigation();
    const imagePayload = extractImagePayloadFromText(normalized);
    insertImagePlaceholder(imagePayload);
    suppressIncomingUntil = now + PASTE_BURST_BLOCK_MS;
    scheduleInputRender(menuWasVisible, noCommandsWasVisible);
    return;
  }

  if (shouldBlockPastedInput(normalized)) {
    breakSubmittedInputHistoryNavigation();
    activeBlockedPastePayloadIndex = insertPastePlaceholderFromText(normalized);
    suppressIncomingUntil = now + PASTE_BURST_BLOCK_MS;
    scheduleInputRender(menuWasVisible, noCommandsWasVisible);
    return;
  }

  breakSubmittedInputHistoryNavigation();
  input = `${input.slice(0, inputCursorIndex)}${normalized}${input.slice(inputCursorIndex)}`;
  inputCursorIndex += normalized.length;
  updateCommandMenuState();
  scheduleInputRender(menuWasVisible, noCommandsWasVisible);
}

function backspace() {
  if (!input.length || inputCursorIndex === 0) {
    return;
  }

  const targetIndex = inputCursorIndex - 1;
  const tokenRange = findAtomicTokenRangeAtIndex(input, targetIndex);
  if (tokenRange) {
    breakSubmittedInputHistoryNavigation();
    input = `${input.slice(0, tokenRange.start)}${input.slice(tokenRange.end)}`;
    inputCursorIndex = tokenRange.start;
    syncImagePasteCounter();
    updateCommandMenuState();
    return;
  }

  breakSubmittedInputHistoryNavigation();
  input = `${input.slice(0, targetIndex)}${input.slice(inputCursorIndex)}`;
  inputCursorIndex -= 1;
  updateCommandMenuState();
}

function moveCursorLeft() {
  if (inputCursorIndex > 0) {
    inputCursorIndex -= 1;
  }
}

function moveCursorRight() {
  if (inputCursorIndex < input.length) {
    inputCursorIndex += 1;
  }
}

function moveCursorToStart() {
  inputCursorIndex = 0;
}

function moveCursorToEnd() {
  inputCursorIndex = input.length;
}

function moveCursorWordLeft() {
  if (inputCursorIndex === 0) {
    return;
  }

  let i = inputCursorIndex;
  while (i > 0 && /\s/.test(input[i - 1])) {
    i -= 1;
  }
  while (i > 0 && !/\s/.test(input[i - 1])) {
    i -= 1;
  }
  inputCursorIndex = i;
}

function moveCursorWordRight() {
  if (inputCursorIndex >= input.length) {
    return;
  }

  let i = inputCursorIndex;
  while (i < input.length && /\s/.test(input[i])) {
    i += 1;
  }
  while (i < input.length && !/\s/.test(input[i])) {
    i += 1;
  }
  inputCursorIndex = i;
}

function deleteWordBackward() {
  if (inputCursorIndex === 0) {
    return;
  }

  let start = inputCursorIndex;
  while (start > 0 && /\s/.test(input[start - 1])) {
    start -= 1;
  }
  while (start > 0 && !/\s/.test(input[start - 1])) {
    start -= 1;
  }

  breakSubmittedInputHistoryNavigation();
  input = `${input.slice(0, start)}${input.slice(inputCursorIndex)}`;
  inputCursorIndex = start;
  updateCommandMenuState();
}

function findAtomicTokenRangeAtIndex(text, index) {
  if (typeof text !== "string" || index < 0 || index >= text.length) {
    return null;
  }

  const tokenRe = /\[(?:Image #\d+|Pasted Content \d+ chars)\]/g;
  let match;
  while ((match = tokenRe.exec(text)) !== null) {
    const start = match.index;
    const end = start + match[0].length;
    if (index >= start && index < end) {
      return { start, end };
    }
  }

  return null;
}

function deleteAtCursor() {
  if (inputCursorIndex >= input.length) {
    return;
  }

  const tokenRange = findAtomicTokenRangeAtIndex(input, inputCursorIndex);
  if (tokenRange) {
    breakSubmittedInputHistoryNavigation();
    input = `${input.slice(0, tokenRange.start)}${input.slice(tokenRange.end)}`;
    inputCursorIndex = tokenRange.start;
    syncImagePasteCounter();
    updateCommandMenuState();
    return;
  }

  breakSubmittedInputHistoryNavigation();
  input = `${input.slice(0, inputCursorIndex)}${input.slice(inputCursorIndex + 1)}`;
  updateCommandMenuState();
}

function handleChunk(chunk) {
  if (Date.now() < suppressMouseNoiseUntil && isMouseNoiseCharFragment(chunk)) {
    return;
  }

  if (isMouseNoiseFragment(chunk)) {
    return;
  }

  if (Date.now() < suppressMouseNoiseUntil && isMouseNoiseFragment(chunk)) {
    return;
  }

  if (isStandaloneMouseSequence(chunk)) {
    return;
  }

  if (chunk === "\u0003") {
    process.stdout.write("\n");
    process.exit(0);
  }

  if (chunk === "\n") {
    return;
  }

  if (chunk === "\r") {
    submit();
    return;
  }

  if (chunk === "\u0008" || chunk === "\u007f") {
    backspace();
    return;
  }

  // Ignore escape sequences we are not explicitly handling (arrows, function keys, etc.).
  if (chunk.startsWith("\u001b")) {
    return;
  }

  appendText(chunk);
}

function runAppendSelfTest() {
  const out = process.stdout.write.bind(process.stdout);
  try {
    input = "";
    inputCursorIndex = 0;
    messages.length = 0;
    activeBuffer = "main";
    chatScrollOffset = 0;
    printedMessageCount = 0;
    forceTranscriptReplay = true;
    lastFrameTop = null;
    lastFrameHeight = 0;
    lastChatAreaHeight = null;
    lastMenuTop = null;
    lastMenuHeight = 0;
    lastFooterTop = null;
    lastStatusTop = null;
    lastStatusHeight = 0;
    lastMenuRenderedLines = [];
    ensureSystemMessageAtTop();
    messages.push({ role: "user", content: "hello self test" });

    if (APPEND_CHAT_TO_SCROLLBACK) {
      const originalWrite = process.stdout.write.bind(process.stdout);
      let captured = "";
      try {
        process.stdout.write = (chunk, encoding, callback) => {
          captured += String(chunk ?? "");
          if (typeof callback === "function") {
            callback();
          }
          return true;
        };
        appendTranscriptNow({ replay: true });
      } finally {
        process.stdout.write = originalWrite;
      }

      if (!/hello self test/.test(captured)) {
        out("SELFTEST_FAIL\n");
        return 1;
      }
    } else {
      const lines = buildChatVisualLines(80).map((line) => stripAnsiSgr(line.text));
      if (!lines.some((line) => line.includes("hello self test"))) {
        out("SELFTEST_FAIL\n");
        return 1;
      }
    }

    out("SELFTEST_OK\n");
    return 0;
  } catch {
    out("SELFTEST_FAIL\n");
    return 1;
  }
}

function runFormatSelfTest() {
  const out = process.stdout.write.bind(process.stdout);
  try {
    const multilineUser = buildTranscriptLinesForEntry(
      { role: "user", content: "first line\nsecond line" },
      80
    ).map(stripAnsiSgr);
    if (multilineUser.length < 2) {
      out("FORMAT_FAIL: multiline user did not produce 2 lines\n");
      return 1;
    }

    const promptPrefixRe = new RegExp(
      `^\\s*${PROMPT_PREFIX.replace(/[.*+?^${}()|[\]\\]/g, "\\\\$&")}`
    );
    if (!promptPrefixRe.test(multilineUser[0]) || promptPrefixRe.test(multilineUser[1])) {
      out("FORMAT_FAIL: multiline user should render prefix only on first line\n");
      return 1;
    }

    const singleUser = buildTranscriptLinesForEntry(
      { role: "user", content: "single line" },
      80
    ).map(stripAnsiSgr);
    if (singleUser.length === 0 || !promptPrefixRe.test(singleUser[0])) {
      out("FORMAT_FAIL: single-line user should render prompt prefix\n");
      return 1;
    }

    const preservedMultiline = buildTranscriptLinesForEntry(
      { role: "user", content: ">\n\n\n\n\nhello" },
      80
    ).map(stripAnsiSgr);
    if (preservedMultiline.length < 3) {
      out("FORMAT_FAIL: multiline user spacing collapsed unexpectedly\n");
      return 1;
    }
    if (!promptPrefixRe.test(preservedMultiline[0])) {
      out("FORMAT_FAIL: preserved multiline first line should include prompt prefix\n");
      return 1;
    }
    const firstLineBody = preservedMultiline[0].replace(promptPrefixRe, "");
    if (firstLineBody !== ">") {
      out("FORMAT_FAIL: preserved multiline first line content mismatch\n");
      return 1;
    }
    const helloIndex = preservedMultiline.lastIndexOf("hello");
    if (helloIndex <= 1) {
      out("FORMAT_FAIL: preserved multiline final content line mismatch\n");
      return 1;
    }
    for (let i = 1; i < helloIndex; i += 1) {
      if (preservedMultiline[i] !== "") {
        out("FORMAT_FAIL: preserved multiline blank lines should stay blank\n");
        return 1;
      }
    }

    // Diff detection: a real unified diff should be detected, plain tool
    // text starting with "-" must NOT be treated as a diff hunk.
    const realDiff = [
      "diff --git a/index.js b/index.js",
      "index abc123..def456 100644",
      "--- a/index.js",
      "+++ b/index.js",
      "@@ -10,3 +10,4 @@ async function start() {",
      " console.log(\"start\");",
      "-console.log(\"removed\");",
      "+console.log(\"added\");",
      " console.log(\"end\");",
    ].join("\n");
    if (!isUnifiedDiffText(realDiff)) {
      out("FORMAT_FAIL: real unified diff should be detected");
      return 1;
    }
    if (isUnifiedDiffText("- some bullet text\nnothing else")) {
      out("FORMAT_FAIL: plain tool text starting with '-' must not be a diff");
      return 1;
    }

    // Rendering: only lines inside a genuine diff get diff backgrounds;
    // "- something" from ordinary tool output must stay plain.
    const plainToolLines = buildTranscriptLinesForEntry(
      { role: "tool", content: "- some bullet text\nnormal line" },
      80
    );
    const plainToolJoined = plainToolLines.join("\n");
    if (plainToolJoined.includes(DIFF_REMOVE_BG_COLOR) || plainToolJoined.includes(DIFF_ADD_BG_COLOR)) {
      out("FORMAT_FAIL: plain tool text should not get diff background");
      return 1;
    }

    const diffToolLines = buildTranscriptLinesForEntry({ role: "tool", content: realDiff }, 80);
    const diffToolJoined = diffToolLines.join("\n");
    if (!diffToolJoined.includes(DIFF_REMOVE_BG_COLOR) || !diffToolJoined.includes(DIFF_ADD_BG_COLOR)) {
      out("FORMAT_FAIL: real diff lines should get diff backgrounds");
      return 1;
    }

    out("FORMAT_OK\n");
    return 0;
  } catch (error) {
    out(`FORMAT_FAIL: ${String(error?.message || error)}\n`);
    return 1;
  }
}

// ---------------------------------------------------------------------------
// Compaction self-test: exercises token estimation, the tool-output cap, and
// summary detection without needing a live LLM call.
// ---------------------------------------------------------------------------
function runCompactionSelfTest() {
  const out = (s) => process.stdout.write(s);
  try {
    // Token estimation
    if (estimateTokensForText("") !== 1) {
      out("COMPACT_FAIL: empty text should estimate to 1 token\n");
      return 1;
    }
    if (estimateTokensForText("abcd") !== 1) {
      out("COMPACT_FAIL: 4 chars should estimate to 1 token\n");
      return 1;
    }
    if (estimateTokensForText("abcdefghijklmnop") !== 4) {
      out("COMPACT_FAIL: 16 chars should estimate to 4 tokens\n");
      return 1;
    }

    // Tool output cap
    const short = capToolHistoryText("hello world", 16000);
    if (short !== "hello world") {
      out("COMPACT_FAIL: short text should pass through unchanged\n");
      return 1;
    }
    const big = capToolHistoryText("x".repeat(10000), 500); // 500 tokens => 2000 chars
    if (big.length >= 10000 || !big.includes("tool result truncated")) {
      out("COMPACT_FAIL: oversized tool output should be capped with a marker\n");
      return 1;
    }
    if (big.length < 1500 || big.length > 2600) {
      // head 1000 + marker + tail 1000 = ~2100
      out(`COMPACT_FAIL: capped output wrong size: ${big.length}\n`);
      return 1;
    }

    // Summary detection
    if (!isCompactionSummaryEntry({ role: "user", content: "_summary\nhandoff text" })) {
      out("COMPACT_FAIL: _summary-prefixed user entry should be detected\n");
      return 1;
    }
    if (isCompactionSummaryEntry({ role: "assistant", content: "_summary\nhandoff" })) {
      out("COMPACT_FAIL: assistant entries should never be summaries\n");
      return 1;
    }
    if (isCompactionSummaryEntry({ role: "user", content: "normal user text" })) {
      out("COMPACT_FAIL: normal user text should not be a summary\n");
      return 1;
    }

    // Threshold math (without touching live config)
    if (getCompactionThreshold() < 1) {
      out("COMPACT_FAIL: compaction threshold must be positive\n");
      return 1;
    }
    if (getToolOutputTokenLimit() < 1) {
      out("COMPACT_FAIL: tool output limit must be positive\n");
      return 1;
    }

    out("COMPACT_OK\n");
    return 0;
  } catch (error) {
    out(`COMPACT_FAIL: ${String(error?.message || error)}\n`);
    return 1;
  }
}

if (process.argv.includes("--self-test-compact")) {
  const code = runCompactionSelfTest();
  process.exit(code);
}

// ---------------------------------------------------------------------------
// MCP end-to-end self-test: launches a tiny in-process stdio MCP server,
// starts the real bridge, calls it via the bridge handler, and verifies.
// ---------------------------------------------------------------------------
async function runMcpSelfTest() {
  const out = (s) => process.stdout.write(s);
  try {
    const { spawn: spawnProc } = require("node:child_process");

    // Script for a minimal stdio MCP server: responds to initialize,
    // tools/list, and tools/call with a static "ping" tool.
    const serverScript = [
      "function frame(msg) {",
      "  const body = JSON.stringify(msg);",
      "  const crlf = String.fromCharCode(13, 10);",
      "  process.stdout.write('Content-Length: ' + Buffer.byteLength(body, 'utf8') + crlf + crlf + body);",
      "}",
      "let buf = Buffer.alloc(0);",
      "const CRLFCRLF = Buffer.from([13, 10, 13, 10]);",
      "process.stdin.on('data', (chunk) => {",
      "  buf = Buffer.concat([buf, chunk]);",
      "  for (;;) {",
      "    const idx = buf.indexOf(CRLFCRLF);",
      "    if (idx === -1) return;",
      "    const header = buf.slice(0, idx).toString('utf8');",
      "    const m = /Content-Length: *(\\d+)/i.exec(header);",
      "    if (!m) return;",
      "    const len = Number(m[1]);",
      "    if (buf.length < idx + 4 + len) return;",
      "    const raw = buf.slice(idx + 4, idx + 4 + len).toString('utf8');",
      "    buf = buf.slice(idx + 4 + len);",
      "    const msg = JSON.parse(raw);",
      "    if (msg.method === 'initialize') {",
      "      frame({ jsonrpc: '2.0', id: msg.id, result: { protocolVersion: '2025-03-26', capabilities: { tools: {} }, serverInfo: { name: 'mock', version: '1.0.0' } } });",
      "    } else if (msg.method === 'tools/list') {",
      "      frame({ jsonrpc: '2.0', id: msg.id, result: { tools: [{ name: 'ping', description: 'Ping test tool', inputSchema: { type: 'object', properties: { value: { type: 'string' } } } }] } });",
      "    } else if (msg.method === 'tools/call') {",
      "      const args = msg.params && msg.params.arguments || {};",
      "      frame({ jsonrpc: '2.0', id: msg.id, result: { content: [{ type: 'text', text: 'pong:' + (args.value || '') }] } });",
      "    } else if (msg.jsonrpc && msg.id !== undefined) {",
      "      frame({ jsonrpc: '2.0', id: msg.id, result: {} });",
      "    }",
      "  }",
      "});",
    ].join(String.fromCharCode(10));

    const scriptPath = path.join(os.tmpdir(), `nexus-mcp-mock-${process.pid}.js`);
    fsSync.writeFileSync(scriptPath, serverScript, "utf8");

    // When running as a SEA binary, process.execPath is sea.exe, which cannot
    // execute a JS script as an MCP server. Resolve a real node executable.
    // Never use a SEA binary (sea.exe) as the mock runner: it cannot execute
    // a JS script. Only accept process.execPath when it is an actual node
    // binary (running the source tree); otherwise prefer a sibling node.exe,
    // the standard install path, or PATH lookup.
    const execBasename = path.basename(process.execPath).toLowerCase();
    const looksLikeNode = execBasename === "node.exe" || execBasename === "node";
    const mockNodeCandidates = [
      path.join(path.dirname(process.execPath), "node.exe"),
      "C:/Program Files/nodejs/node.exe",
      "node",
      ...(looksLikeNode ? [process.execPath] : []),
    ].filter(Boolean);
    let mockNode = "";
    for (const candidate of mockNodeCandidates) {
      if (candidate === "node") {
        mockNode = "node";
        break;
      }
      try {
        if (fsSync.existsSync(candidate)) {
          mockNode = candidate;
          break;
        }
      } catch {
        // continue
      }
    }
    if (!mockNode) {
      out("MCP_FAIL: could not resolve a node executable for the mock server\n");
      return 1;
    }

    // Temporarily set an mcp config pointing at the mock server
    const configPath = getMcpConfigPath();
    const origConfig = fsSync.existsSync(configPath)
      ? fsSync.readFileSync(configPath, "utf8")
      : null;
    const mockConfig = {
      mcpServers: {
        mock: { command: mockNode, args: [scriptPath] },
      },
    };
    fsSync.writeFileSync(configPath, JSON.stringify(mockConfig, null, 2), "utf8");

    try {
      await startMcpServers();
      await refreshMcpDescriptions();
      await startMcpBridgeServer();

      const serverEntry = mcpServers.find((e) => e.name === "mock");
      if (!serverEntry || !serverEntry.client || serverEntry.tools.length !== 1) {
        const stderrTail = serverEntry?.client?.stderrTail || "";
        const childInfo = serverEntry?.client?.child
          ? `exitCode=${serverEntry.client.child.exitCode} signal=${serverEntry.client.child.signalCode} killed=${serverEntry.client.child.killed}`
          : "no-child";
        const pendingInfo = serverEntry?.client?.pending
          ? [...serverEntry.client.pending.keys()].join(",")
          : "";
        out(`MCP_FAIL: mock server not discovered (tools=${serverEntry?.tools?.length ?? 0}, error="${serverEntry?.error || ""}", stderr="${stderrTail}", ${childInfo}, pending=[${pendingInfo}])\n`);
        return 1;
      }
      if (serverEntry.tools[0].name !== "ping") {
        out(`MCP_FAIL: expected tool "ping", got "${serverEntry.tools[0].name}"
`);
        return 1;
      }

      const bridgeResp = await handleMcpBridgeRequest({
        method: "call",
        server: "mock",
        tool: "ping",
        arguments: { value: "hello" },
      });
      if (!bridgeResp.ok || bridgeResp.text !== "pong:hello") {
        out(`MCP_FAIL: bridge call returned ${JSON.stringify(bridgeResp)}
`);
        return 1;
      }

      const descKeys = Object.keys(mcpDescriptions);
      if (descKeys.length !== 1 || !descKeys[0].includes("ping")) {
        out(`MCP_FAIL: expected 1 description with "ping", got ${JSON.stringify(descKeys)}
`);
        return 1;
      }

      // Verify the python-side helper can reach the bridge too.
      const pyScript = [
        "import json, sys",
        "sys.path.insert(0, " + JSON.stringify(process.cwd()) + ")",
        "import tools",
        "res = tools.mcp_call('mock', 'ping', {'value': 'py'})",
        "print(json.dumps(res))",
      ].join(String.fromCharCode(10));
      let pythonOut = "";
      try {
        // Use the source tools.py (not the possibly-stale bundled tools.exe)
        // so the bridge helpers are exercised on the current code.
        const { stdout } = await execFileAsync("python", ["-c", pyScript], {
          cwd: process.cwd(),
          timeout: 30000,
          maxBuffer: 512 * 1024,
        });
        pythonOut = String(stdout || "").trim();
      } catch (error) {
        pythonOut = "PYERR:" + String(error?.message || error);
      }
      try {
        const parsed = JSON.parse(pythonOut);
        if (!parsed?.ok || parsed?.text !== "pong:py") {
          out(`MCP_FAIL: python bridge call failed: ${pythonOut}
`);
          return 1;
        }
      } catch {
        out(`MCP_FAIL: python bridge call failed (unparseable): ${pythonOut}
`);
        return 1;
      }

      out("MCP_OK\n");
      return 0;
    } finally {
      await stopMcpServers();
      if (mcpBridgeServer) {
        try {
          mcpBridgeServer.close();
        } catch {
          // ignore
        }
        mcpBridgeServer = null;
      }
      mcpBridgeState = "";
      mcpBridgePort = 0;
      fsSync.rmSync(scriptPath, { force: true });
      if (origConfig !== null) {
        fsSync.writeFileSync(configPath, origConfig, "utf8");
      } else {
        fsSync.rmSync(configPath, { force: true });
      }
    }
  } catch (error) {
    out(`MCP_FAIL: ${String(error?.message || error)}\n`);
    return 1;
  }
}

if (process.argv.includes("--self-test-append")) {
  const code = runAppendSelfTest();
  process.exit(code);
}

if (process.argv.includes("--self-test-format")) {
  const code = runFormatSelfTest();
  process.exit(code);
}

if (process.argv.includes("--self-test-mcp")) {
  runMcpSelfTest().then((code) => process.exit(code));
  return;
}

readline.emitKeypressEvents(process.stdin);

if (process.stdin.isTTY) {
  process.stdin.setRawMode(true);
  process.stdout.write(ENABLE_BRACKETED_PASTE);
  bracketedPasteModeEnabled = true;
  setMouseTrackingEnabled(APP_MOUSE_TRACKING_ENABLED);
}

process.stdin.setEncoding("utf8");
process.stdin.on("data", (rawChunk) => {
  const chunk = mouseTrackingEnabled ? stripMouseSequences(rawChunk) : rawChunk;
  if (!chunk) {
    return;
  }

  if (mouseTrackingEnabled && isMouseNoiseFragment(chunk)) {
    return;
  }

  if (activeBuffer === "command" && chunk === "\u001b") {
    closeCommandBuffer();
  } else if (activeBuffer === "model" && chunk === "\u001b") {
    closeModelBuffer();
  } else if (activeBuffer === "sessions" && chunk === "\u001b") {
    closeSessionsBuffer();
  } else if (activeBuffer === "providers" && chunk === "\u001b") {
    closeProvidersBuffer();
  } else if (activeBuffer === "provider_editor" && chunk === "\u001b") {
    ignoreNextProvidersEscape = true;
    suppressKeypressUntil = Date.now() + 200;
    cancelProviderEditorChanges({ immediate: true }).catch(() => {});
  } else if (activeBuffer === "main") {
    pasteParserBuffer += chunk;

    while (pasteParserBuffer.length > 0) {
      if (!isBracketedPasteActive) {
        const startIndex = pasteParserBuffer.indexOf(BRACKETED_PASTE_START);
        if (startIndex === -1) {
          const keep = BRACKETED_PASTE_START.length - 1;
          if (pasteParserBuffer.length > keep) {
            pasteParserBuffer = pasteParserBuffer.slice(-keep);
          }
          break;
        }

        pasteParserBuffer = pasteParserBuffer.slice(startIndex + BRACKETED_PASTE_START.length);
        isBracketedPasteActive = true;
        bracketedPasteBuffer = "";
        continue;
      }

      const endIndex = pasteParserBuffer.indexOf(BRACKETED_PASTE_END);
      if (endIndex === -1) {
        const keep = BRACKETED_PASTE_END.length - 1;
        if (pasteParserBuffer.length > keep) {
          bracketedPasteBuffer += pasteParserBuffer.slice(0, pasteParserBuffer.length - keep);
          pasteParserBuffer = pasteParserBuffer.slice(-keep);
        }
        break;
      }

      bracketedPasteBuffer += pasteParserBuffer.slice(0, endIndex);
      applyBracketedPaste(bracketedPasteBuffer);
      bracketedPasteBuffer = "";
      isBracketedPasteActive = false;
      suppressKeypressUntil = Date.now() + PASTE_BURST_BLOCK_MS;
      pasteParserBuffer = pasteParserBuffer.slice(endIndex + BRACKETED_PASTE_END.length);
    }
  }
});

process.stdin.on("keypress", async (str, key) => {
  const seq = typeof key?.sequence === "string" ? key.sequence : "";
  const hasMouseNoise =
    isStandaloneMouseSequence(str) ||
    isStandaloneMouseSequence(seq) ||
    isMouseNoiseFragment(str) ||
    isMouseNoiseFragment(seq);
  if (hasMouseNoise) {
    return;
  }

  if (mouseTrackingEnabled && Date.now() < suppressMouseNoiseUntil) {
    if (isMouseNoiseCharFragment(str) || isMouseNoiseCharFragment(seq)) {
      return;
    }

    const hasMouseNoise =
      isStandaloneMouseSequence(str) ||
      isStandaloneMouseSequence(seq) ||
      isMouseNoiseFragment(str) ||
      isMouseNoiseFragment(seq);
    if (hasMouseNoise) {
      return;
    }
  }

  if (mouseTrackingEnabled && (isStandaloneMouseSequence(str) || isStandaloneMouseSequence(key?.sequence))) {
    return;
  }

  const menuWasVisible = isCommandMenuVisible();
  const noCommandsWasVisible = isNoCommandsState();

  if (key?.ctrl && key.name === "c") {
    cleanupTerminal({ clearScreen: true });
    process.exit(0);
  }

  const isMainBufferEscape =
    activeBuffer === "main" &&
    (key?.name === "escape" || key?.sequence === "\u001b" || str === "\u001b");
  if (isMainBufferEscape) {
    if (isAssistantThinking()) {
      handleStopRequest();
      return;
    }
    if (input.length > 0) {
      input = "";
      inputCursorIndex = 0;
      markDirty();
      renderFrame(true);
    }
    return;
  }

  if (mouseSelectionMode) {
    exitMouseSelectionMode();
  }

  const isToggleMouseCapture =
    activeBuffer === "main" &&
    ((key?.meta && key?.name === "m") || key?.sequence === "\u001bm");
  if (isToggleMouseCapture) {
    clearMouseSelectionTimer();
    mouseSelectionMode = false;
    setMouseTrackingEnabled(!mouseTrackingEnabled);
    suppressMouseNoiseUntil = 0;
    markDirty();
    renderFrame(true);
    return;
  }

  if (isBracketedPasteActive || Date.now() < suppressKeypressUntil) {
    return;
  }

  if (activeBuffer === "model") {
    if (key?.ctrl) {
      return;
    }

    if (
      key?.name === "escape" ||
      key?.sequence === "\u001b" ||
      str === "\u001b"
    ) {
      closeModelBuffer();
      return;
    }

    if (key?.name === "up" || key?.name === "down") {
      const models = getFilteredModels();
      if (models.length > 0) {
        if (key.name === "up") {
          modelSelected = Math.max(0, modelSelected - 1);
        } else {
          modelSelected = Math.min(models.length - 1, modelSelected + 1);
        }

        if (modelSelected < modelScroll) {
          modelScroll = modelSelected;
        } else {
          const visibleCount = getModelVisibleCount();
          if (modelSelected >= modelScroll + visibleCount) {
            modelScroll = modelSelected - visibleCount + 1;
          }
        }
      }

      markDirty();
      renderFrame(true);
      return;
    }

    if (key?.name === "backspace") {
      if (modelSearch.length > 0) {
        modelSearch = modelSearch.slice(0, -1);
        updateModelSelectionState();
      }
      markDirty();
      renderFrame(true);
      return;
    }

    if (key?.sequence === "\r" || key?.name === "return" || key?.name === "enter") {
      const models = getFilteredModels();
      if (models.length > 0) {
        selectedModel = models[modelSelected].id;
        await rewriteSessionWithCurrentMessages().catch(() => {});
      }
      closeModelBuffer();
      return;
    }

    if (!key?.ctrl && !key?.meta && str && !str.startsWith("\u001b")) {
      if (shouldBlockPastedInput(str)) {
        return;
      }

      modelSearch += str;
      modelSelected = 0;
      modelScroll = 0;
      updateModelSelectionState();
      markDirty();
      renderFrame(true);
      return;
    }

    return;
  }

  if (activeBuffer === "sessions") {
    if (key?.ctrl) {
      return;
    }

    if (
      key?.name === "escape" ||
      key?.sequence === "\u001b" ||
      str === "\u001b"
    ) {
      closeSessionsBuffer();
      return;
    }

    if (key?.name === "up" || key?.name === "down") {
      if (sessionFiles.length > 0) {
        if (key.name === "up") {
          sessionsSelected = Math.max(0, sessionsSelected - 1);
        } else {
          sessionsSelected = Math.min(sessionFiles.length - 1, sessionsSelected + 1);
        }

        if (sessionsSelected < sessionsScroll) {
          sessionsScroll = sessionsSelected;
        } else {
          const visibleCount = getSessionsVisibleCount();
          if (sessionsSelected >= sessionsScroll + visibleCount) {
            sessionsScroll = sessionsSelected - visibleCount + 1;
          }
        }
      }

      markDirty();
      renderFrame(true);
      return;
    }

    if (key?.sequence === "\r" || key?.name === "return" || key?.name === "enter") {
      await loadSelectedSessionIntoChat();
      closeSessionsBuffer();
      return;
    }

    return;
  }

  if (activeBuffer === "providers") {
    if (key?.ctrl) {
      return;
    }

    if (
      key?.name === "escape" ||
      key?.sequence === "\u001b" ||
      str === "\u001b"
    ) {
      if (ignoreNextProvidersEscape) {
        ignoreNextProvidersEscape = false;
        return;
      }
      closeProvidersBuffer();
      return;
    }

    if (key?.name === "up" || key?.name === "down") {
      if (providers.length > 0) {
        if (key.name === "up") {
          providersSelected = Math.max(0, providersSelected - 1);
        } else {
          providersSelected = Math.min(providers.length - 1, providersSelected + 1);
        }

        if (providersSelected < providersScroll) {
          providersScroll = providersSelected;
        } else {
          const visibleCount = getProvidersVisibleCount();
          if (providersSelected >= providersScroll + visibleCount) {
            providersScroll = providersSelected - visibleCount + 1;
          }
        }
      }

      markDirty();
      renderFrame(true);
      return;
    }

    if (key?.name === "f1") {
      try {
        await createProviderAndOpenEditor();
      } catch {
        providersLoadError = "Could not create provider";
        markDirty();
        renderFrame(true);
      }
      return;
    }

    if (key?.name === "f2") {
      if (providers.length > 0) {
        openProviderEditorBuffer("edit", providersSelected);
      }
      return;
    }

    if (key?.name === "delete") {
      if (providers.length > 0) {
        const removed = providers[providersSelected];
        providers.splice(providersSelected, 1);
        try {
          await saveProvidersToFile();
          if (removed?.name && selectedProviderName === removed.name) {
            await ensureSelectedProviderIsValid();
          }
        } catch {
          providersLoadError = "Could not delete provider";
        }
        updateProvidersSelectionState();
      }
      markDirty();
      renderFrame(true);
      return;
    }

    if (key?.sequence === "\r" || key?.name === "return" || key?.name === "enter") {
      if (providers.length > 0) {
        try {
          await selectProviderByIndex(providersSelected);
          providersLoadError = "";
        } catch {
          providersLoadError = "Could not select provider";
        }
        markDirty();
        renderFrame(true);
      }
      return;
    }

    return;
  }

  if (activeBuffer === "provider_editor") {
    if (key?.ctrl) {
      return;
    }

    if (
      key?.name === "escape" ||
      key?.sequence === "\u001b" ||
      str === "\u001b"
    ) {
      const cancelPromise = cancelProviderEditorChanges({ immediate: true });
      cancelPromise.catch(() => {});
      return;
    }

    if (key?.name === "up" || key?.name === "down") {
      const maxFieldIndex = Math.max(0, getProviderEditorFields().length - 1);
      if (key.name === "up") {
        providerEditorFieldIndex = Math.max(0, providerEditorFieldIndex - 1);
      } else {
        providerEditorFieldIndex = Math.min(maxFieldIndex, providerEditorFieldIndex + 1);
      }
      markDirty();
      renderFrame(true);
      return;
    }

    if (key?.name === "f1") {
      try {
        await saveProviderEditorChanges();
      } catch {
        providersLoadError = "Could not save provider";
        closeProviderEditorToProviders();
      }
      return;
    }

    if (key?.name === "backspace") {
      backspaceProviderEditorField();
      markDirty();
      renderFrame(true);
      return;
    }

    if (!key?.meta && str && !str.startsWith("\u001b")) {
      if (shouldBlockPastedInput(str)) {
        return;
      }
      appendToProviderEditorField(str);
      markDirty();
      renderFrame(true);
      return;
    }

    return;
  }

  if (activeBuffer === "command") {
    if (key?.ctrl) {
      return;
    }

    if (
      key?.name === "escape" ||
      key?.sequence === "\u001b" ||
      str === "\u001b"
    ) {
      closeCommandBuffer();
      return;
    }

    if (key?.name === "up" || key?.name === "down") {
      const commands = getFilteredCommandBufferCommands();
      const visibleCount = getCommandBufferVisibleCount();
      if (commands.length > 0) {
        if (key.name === "up") {
          commandMenuSelected = Math.max(0, commandMenuSelected - 1);
        } else {
          commandMenuSelected = Math.min(commands.length - 1, commandMenuSelected + 1);
        }

        if (commandMenuSelected < commandMenuScroll) {
          commandMenuScroll = commandMenuSelected;
        } else if (commandMenuSelected >= commandMenuScroll + visibleCount) {
          commandMenuScroll = commandMenuSelected - visibleCount + 1;
        }

        const selectedCommand = commands[commandMenuSelected];
        if (selectedCommand?.name) {
          commandBufferQuery = selectedCommand.name.replace(/^\/+/, "");
        }
      }

      markDirty();
      renderFrame(true);
      return;
    }

    if (key?.name === "backspace") {
      if (commandBufferQuery.length > 0) {
        commandBufferQuery = commandBufferQuery.slice(0, -1);
        updateCommandBufferSelectionState();
      }
      markDirty();
      renderFrame(true);
      return;
    }

    if (key?.sequence === "\r" || key?.name === "return" || key?.name === "enter") {
      const typedQuery = commandBufferQuery.trim();
      if (typedQuery.length > 0) {
        const normalizedTyped = typedQuery.startsWith("/") ? typedQuery : `/${typedQuery}`;
        const typedCommand = normalizedTyped.split(/\s+/)[0].toLowerCase();
        const typedArgs = normalizedTyped.slice(typedCommand.length).trim();
        const isKnownTypedCommand =
          typedCommand === "/model" ||
          typedCommand === "/thinking" ||
          COMMANDS.some((command) => command.name === typedCommand);
        if (isKnownTypedCommand) {
          closeCommandBuffer();
          const handled = await runSlashCommand(typedCommand, typedArgs);
          if (!handled) {
            input = normalizedTyped;
            inputCursorIndex = input.length;
            markDirty();
            renderFrame(true);
          }
          return;
        }
      }

      const selectedCommand = getSelectedCommand();
      if (!selectedCommand) {
        const restoreInput = commandBufferQuery.length > 0 ? `/${commandBufferQuery}` : "";
        closeCommandBuffer({ restoreInput });
        return;
      }

      closeCommandBuffer();
      const handled = await runSlashCommand(selectedCommand.name);
      if (!handled) {
        input = selectedCommand.name;
        inputCursorIndex = input.length;
        markDirty();
        renderFrame(true);
      }
      return;
    }

    if (!key?.ctrl && !key?.meta && str && !str.startsWith("\u001b")) {
      if (shouldBlockPastedInput(str)) {
        return;
      }

      commandBufferQuery += str;
      commandMenuSelected = 0;
      commandMenuScroll = 0;
      updateCommandBufferSelectionState();
      markDirty();
      renderFrame(true);
      return;
    }

    return;
  }

  if (
    !key?.ctrl &&
    !key?.meta &&
    str === "/" &&
    input.length === 0 &&
    inputCursorIndex === 0
  ) {
    openCommandBuffer("");
    return;
  }

  const isAltV =
    (key?.meta && key?.name === "v") ||
    key?.sequence === "\u001bv";
  if (isAltV) {
    const inserted = await pasteImageFromClipboard();
    if (inserted) {
      scheduleInputRender(menuWasVisible, noCommandsWasVisible);
    }
    return;
  }

  if (key?.ctrl && key.name === "a") {
    moveCursorToStart();
    scheduleInputRender(menuWasVisible, noCommandsWasVisible);
    return;
  }

  if (key?.ctrl && key.name === "e") {
    moveCursorToEnd();
    scheduleInputRender(menuWasVisible, noCommandsWasVisible);
    return;
  }

  if (key?.ctrl && key.name === "w") {
    deleteWordBackward();
    scheduleInputRender(menuWasVisible, noCommandsWasVisible);
    return;
  }

  if (key?.ctrl && key.name === "left") {
    moveCursorWordLeft();
    scheduleInputRender(menuWasVisible, noCommandsWasVisible);
    return;
  }

  if (key?.ctrl && key.name === "right") {
    moveCursorWordRight();
    scheduleInputRender(menuWasVisible, noCommandsWasVisible);
    return;
  }

  if (key?.name === "pageup" || key?.name === "pagedown") {
    const rows = process.stdout.rows || 24;
    const chunk = Math.max(1, Math.floor(rows / 2));
    const changed =
      key.name === "pageup" ? scrollChatBy(chunk) : scrollChatBy(-chunk);

    if (changed) {
      cancelIdleFlush();
      burstMode = false;
      markDirty();
      renderFrame(true);
    }
    return;
  }

  if (key?.name === "home" || key?.name === "end") {
    const changed = key.name === "home" ? scrollChatToTop() : scrollChatToBottom();
    if (changed) {
      cancelIdleFlush();
      burstMode = false;
      markDirty();
      renderFrame(true);
    }
    return;
  }

  const isCtrlJ =
    (key?.ctrl && key?.name === "j") ||
    key?.name === "linefeed" ||
    key?.sequence === "\n" ||
    str === "\n";
  const isCtrlEnter =
    (key?.ctrl && (key?.name === "enter" || key?.name === "return")) ||
    key?.sequence === "\u001b[13;5u" ||
    key?.sequence === "\u001b[27;5;13~";
  if (isCtrlJ || isCtrlEnter) {
    appendText("\n");
    scheduleInputRender(menuWasVisible, noCommandsWasVisible);
    return;
  }

  if (key?.ctrl) {
    return;
  }

  if (key?.name === "left") {
    moveCursorLeft();
    scheduleInputRender(menuWasVisible, noCommandsWasVisible);
    return;
  }

  if (key?.name === "right") {
    moveCursorRight();
    scheduleInputRender(menuWasVisible, noCommandsWasVisible);
    return;
  }

  if (key?.name === "delete") {
    deleteAtCursor();
    scheduleInputRender(menuWasVisible, noCommandsWasVisible);
    return;
  }

  if (key?.name === "up" || key?.name === "down") {
    const changed = browseSubmittedInputHistory(key.name === "up" ? -1 : 1);
    if (changed) {
      scheduleInputRender(menuWasVisible, noCommandsWasVisible);
    }
    return;
  }

  if (key?.sequence === "\r" || key?.name === "return" || key?.name === "enter") {
    const trimmedInput = input.trim();
    if (trimmedInput.startsWith("/") && !trimmedInput.includes("\n")) {
      const commandName = trimmedInput.split(/\s+/)[0].toLowerCase();
      const isKnownCommand =
        commandName === "/model" ||
        commandName === "/thinking" ||
        COMMANDS.some((command) => command.name === commandName);
      if (isKnownCommand) {
        input = "";
        inputCursorIndex = 0;
        pendingPastedPayloads = [];
        activeBlockedPastePayloadIndex = -1;
        const commandArgs = trimmedInput.slice(commandName.length).trim();
        const handled = await runSlashCommand(commandName, commandArgs);
        if (handled) {
          return;
        }
      }
    }

    cancelIdleFlush();
    burstMode = false;
    const modelAtSubmit = selectedModel;
    const didAppend = submit();
    if (didAppend) {
      if (!APPEND_CHAT_TO_SCROLLBACK) {
        forceFullClearOnNextRender = true;
      }
      if (APPEND_CHAT_TO_SCROLLBACK) {
        appendTranscriptNow();
      }
      queueAssistantReply(modelAtSubmit);
    }
    markDirty();
    renderFrame(true);
    if (didAppend && !APPEND_CHAT_TO_SCROLLBACK) {
      scheduleViewportMainRefresh();
    }
    if (didAppend && APPEND_CHAT_TO_SCROLLBACK) {
      markDirty();
      renderFrame(false);
    }
    return;
  }

  if (key?.name === "backspace") {
    backspace();
    scheduleInputRender(menuWasVisible, noCommandsWasVisible);
    return;
  }

  if (key?.sequence) {
    handleChunk(key.sequence);
  } else if (str) {
    appendText(str);
  }

  scheduleInputRender(menuWasVisible, noCommandsWasVisible);
});

process.stdout.on("resize", () => {
  markDirty();
  renderFrame(true);
});
process.on("SIGINT", () => {
  cleanupTerminal({ clearScreen: true });
  process.exit(0);
});
process.on("exit", cleanupTerminal);

async function initializeApp() {
  // Launch MCP servers and the bridge in parallel with the rest of startup.
  // The bridge becomes reachable whenever the HTTP listener binds; startup
  // continues regardless so a broken server config never blocks the TUI.
  // Show a "Starting MCP Servers..." status bar while servers spin up.
  const mcpConfigServers = loadMcpConfig()?.mcpServers || {};
  mcpStartupHasConfig = Object.keys(mcpConfigServers).length > 0;
  if (mcpStartupHasConfig) {
    mcpStartupActive = true;
  }
  initMcp()
    .catch(() => {})
    .finally(() => {
      if (mcpStartupHasConfig) {
        mcpStartupActive = false;
        markDirty();
        renderFrame(false);
      }
    });

  await ensureSystemPromptReady();
  await ensureSessionFileReady();
  await loadSkillsCatalog();
  await loadNexusConfig();
  await loadProvidersFromFile();
  await ensureSelectedProviderIsValid();
  await loadModelsFromProvider();
  ensureSystemMessageAtTop();
  resetLlmClient();
  sessionPersistenceInitialized = false;
  renderFrame(true);
}

initializeApp();

