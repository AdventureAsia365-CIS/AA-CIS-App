-- AA-493 — persist stop_reason/finish_reason per LLM call, so a truncated (max_tokens) response
-- can finally be told apart from one that finished normally (end_turn/stop). Previously discarded
-- silently: shared/llm_client/client.py's Bedrock streaming parser read message_delta's
-- output_tokens but never its sibling `delta.stop_reason` field; _call_openai never read
-- `choices[0].finish_reason` at all.
--
-- STEP0 (confirmed before writing this migration, both against real code + the Anthropic/OpenAI
-- API docs — the field names/locations have not changed since the original AA-341 finding):
--   - Anthropic streaming (Bedrock native + satellite's invoke_model_with_response_stream):
--     stop_reason arrives on the message_delta event's `delta.stop_reason`, alongside that same
--     event's cumulative `usage.output_tokens` the existing code already reads.
--   - Anthropic non-streaming (bedrock_satellite.py::invoke_claude(), plain invoke_model()):
--     `stop_reason` is a top-level key on the response payload.
--   - OpenAI Chat Completions: `choices[0].finish_reason` ("stop" | "length" | "content_filter"
--     | "tool_calls").
--   - AWS Bedrock Converse API (services/acp_produce/judge_client.py's Nova Pro + GPT-5.6 Sol
--     backends): top-level `stopReason` (camelCase — different key name, same concept).
--
-- Destination: shared.llm_call_log (migration 137, AA-518/AA-505) — the "bảng log LLM call
-- chung" the issue asks to check for before creating a new table. Confirmed via
-- shared/llm_client/call_log.py::record_call()/record_call_with_pool(), the single write path
-- for all confirmed real call sites — adding one nullable column here reaches every one of them
-- through that shared function, no per-call-site table needed.

ALTER TABLE shared.llm_call_log ADD COLUMN IF NOT EXISTS stop_reason TEXT;

COMMENT ON COLUMN shared.llm_call_log.stop_reason IS
    'AA-493 — provider''s raw stop/finish reason for this call (Anthropic: end_turn/max_tokens/'
    'stop_sequence; OpenAI: stop/length/content_filter/tool_calls; Bedrock Converse: same values, '
    'camelCase stopReason field). NULL for any call site not yet threading it through, or Batch/'
    'legacy rows written before this column existed — never treat NULL as "finished normally", '
    'only a real end_turn/stop value means that.';

INSERT INTO shared.schema_versions (version, applied_at, description)
VALUES (141, now(), 'AA-493 — stop_reason column on shared.llm_call_log')
ON CONFLICT DO NOTHING;
