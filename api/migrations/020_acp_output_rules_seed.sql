-- =============================================================================
-- Migration 020 — acp_output_rules seed: S4 content quality rules
-- AA-79: 22 rules derived from compiled_writer_rules.json (Ms. Thư, v2.0)
-- Source: docs/AI-gent-for automation works/stage-4_.../rules/compiled_writer_rules.json
--
-- GROUP 1 (18 rules): rule_type='block' — hard forbidden output + forbidden patterns
-- GROUP 2 (4 rules):  rule_type='flag'  — sanitization/DB leak patterns (substring form)
--
-- All rules: stage=NULL (global — stage column is smallint, NULL=applies to all stages)
-- ON CONFLICT DO NOTHING — safe to re-run
-- =============================================================================

-- GROUP 1: hard_forbidden_output (from compiled_writer_rules.json .hard_forbidden_output)
INSERT INTO acp_shared.acp_output_rules
  (tenant_id, stage, rule_type, pattern, action_value, error_message, source_type, is_active)
VALUES
  (NULL, NULL, 'block', 'this section follows the calendar brief', NULL,
   'Scaffolding leak: calendar brief language must not appear in rendered output', 'system', TRUE)
ON CONFLICT DO NOTHING;

INSERT INTO acp_shared.acp_output_rules
  (tenant_id, stage, rule_type, pattern, action_value, error_message, source_type, is_active)
VALUES
  (NULL, NULL, 'block', 'operational note', NULL,
   'Scaffolding leak: operational notes must not appear in rendered output', 'system', TRUE)
ON CONFLICT DO NOTHING;

INSERT INTO acp_shared.acp_output_rules
  (tenant_id, stage, rule_type, pattern, action_value, error_message, source_type, is_active)
VALUES
  (NULL, NULL, 'block', 'verify provider details', NULL,
   'Scaffolding leak: provider verification notes must not appear in rendered output', 'system', TRUE)
ON CONFLICT DO NOTHING;

-- GROUP 1: forbidden_patterns (from compiled_writer_rules.json .forbidden_patterns)
INSERT INTO acp_shared.acp_output_rules
  (tenant_id, stage, rule_type, pattern, action_value, error_message, source_type, is_active)
VALUES
  (NULL, NULL, 'block', 'trip of a lifetime', NULL,
   'Forbidden pattern: fabricated urgency/cliché — violates AA brand voice', 'system', TRUE)
ON CONFLICT DO NOTHING;

INSERT INTO acp_shared.acp_output_rules
  (tenant_id, stage, rule_type, pattern, action_value, error_message, source_type, is_active)
VALUES
  (NULL, NULL, 'block', 'once in a lifetime', NULL,
   'Forbidden pattern: fabricated urgency/cliché — violates AA brand voice', 'system', TRUE)
ON CONFLICT DO NOTHING;

INSERT INTO acp_shared.acp_output_rules
  (tenant_id, stage, rule_type, pattern, action_value, error_message, source_type, is_active)
VALUES
  (NULL, NULL, 'block', 'hidden gem', NULL,
   'Forbidden pattern: generic tourism cliché — violates AA brand voice', 'system', TRUE)
ON CONFLICT DO NOTHING;

INSERT INTO acp_shared.acp_output_rules
  (tenant_id, stage, rule_type, pattern, action_value, error_message, source_type, is_active)
VALUES
  (NULL, NULL, 'block', 'don''t miss out', NULL,
   'Forbidden pattern: fabricated urgency — violates AA brand voice', 'system', TRUE)
ON CONFLICT DO NOTHING;

INSERT INTO acp_shared.acp_output_rules
  (tenant_id, stage, rule_type, pattern, action_value, error_message, source_type, is_active)
VALUES
  (NULL, NULL, 'block', 'ultimate adventure', NULL,
   'Forbidden pattern: generic tourism cliché — violates AA brand voice', 'system', TRUE)
ON CONFLICT DO NOTHING;

-- GROUP 1: AI filler terms (maps to brand voice must_not_feel_like: AI filler, SEO sludge)
INSERT INTO acp_shared.acp_output_rules
  (tenant_id, stage, rule_type, pattern, action_value, error_message, source_type, is_active)
VALUES
  (NULL, NULL, 'block', 'stunning', NULL,
   'AI filler term: use specific descriptive language instead', 'system', TRUE)
ON CONFLICT DO NOTHING;

INSERT INTO acp_shared.acp_output_rules
  (tenant_id, stage, rule_type, pattern, action_value, error_message, source_type, is_active)
VALUES
  (NULL, NULL, 'block', 'breathtaking', NULL,
   'AI filler term: use specific descriptive language instead', 'system', TRUE)
ON CONFLICT DO NOTHING;

INSERT INTO acp_shared.acp_output_rules
  (tenant_id, stage, rule_type, pattern, action_value, error_message, source_type, is_active)
VALUES
  (NULL, NULL, 'block', 'unforgettable', NULL,
   'AI filler term: use specific descriptive language instead', 'system', TRUE)
ON CONFLICT DO NOTHING;

INSERT INTO acp_shared.acp_output_rules
  (tenant_id, stage, rule_type, pattern, action_value, error_message, source_type, is_active)
VALUES
  (NULL, NULL, 'block', 'world-class', NULL,
   'AI filler term: unverifiable claim — violates AA operator authority rules', 'system', TRUE)
ON CONFLICT DO NOTHING;

INSERT INTO acp_shared.acp_output_rules
  (tenant_id, stage, rule_type, pattern, action_value, error_message, source_type, is_active)
VALUES
  (NULL, NULL, 'block', 'iconic', NULL,
   'AI filler term: use specific named references instead', 'system', TRUE)
ON CONFLICT DO NOTHING;

INSERT INTO acp_shared.acp_output_rules
  (tenant_id, stage, rule_type, pattern, action_value, error_message, source_type, is_active)
VALUES
  (NULL, NULL, 'block', 'epic', NULL,
   'AI filler term: use specific descriptive language instead', 'system', TRUE)
ON CONFLICT DO NOTHING;

-- GROUP 1: remaining hard_forbidden_output
INSERT INTO acp_shared.acp_output_rules
  (tenant_id, stage, rule_type, pattern, action_value, error_message, source_type, is_active)
VALUES
  (NULL, NULL, 'block', 'calendar brief', NULL,
   'Scaffolding leak: calendar brief references must not appear in rendered output', 'system', TRUE)
ON CONFLICT DO NOTHING;

INSERT INTO acp_shared.acp_output_rules
  (tenant_id, stage, rule_type, pattern, action_value, error_message, source_type, is_active)
VALUES
  (NULL, NULL, 'block', 'brief outline', NULL,
   'Scaffolding leak: outline/brief language must not appear in rendered output', 'system', TRUE)
ON CONFLICT DO NOTHING;

INSERT INTO acp_shared.acp_output_rules
  (tenant_id, stage, rule_type, pattern, action_value, error_message, source_type, is_active)
VALUES
  (NULL, NULL, 'block', 'internal note', NULL,
   'Scaffolding leak: internal notes must not appear in rendered output', 'system', TRUE)
ON CONFLICT DO NOTHING;

INSERT INTO acp_shared.acp_output_rules
  (tenant_id, stage, rule_type, pattern, action_value, error_message, source_type, is_active)
VALUES
  (NULL, NULL, 'block', 'placeholder text', NULL,
   'Scaffolding leak: placeholder text must not appear in rendered output', 'system', TRUE)
ON CONFLICT DO NOTHING;

-- GROUP 2: sanitization_reject_patterns — DB field leaks + price quote (substring form)
-- Source: compiled_writer_rules.json .sanitization_reject_patterns
-- Note: JSON uses regex; simplified to representative substrings for post-processor compatibility

INSERT INTO acp_shared.acp_output_rules
  (tenant_id, stage, rule_type, pattern, action_value, error_message, source_type, is_active)
VALUES
  (NULL, NULL, 'flag', 'tour_id', NULL,
   'Possible raw DB field leak: tour_id should not appear in rendered blog content', 'system', TRUE)
ON CONFLICT DO NOTHING;

INSERT INTO acp_shared.acp_output_rules
  (tenant_id, stage, rule_type, pattern, action_value, error_message, source_type, is_active)
VALUES
  (NULL, NULL, 'flag', 'created_at', NULL,
   'Possible raw DB field leak: created_at should not appear in rendered blog content', 'system', TRUE)
ON CONFLICT DO NOTHING;

INSERT INTO acp_shared.acp_output_rules
  (tenant_id, stage, rule_type, pattern, action_value, error_message, source_type, is_active)
VALUES
  (NULL, NULL, 'flag', 'updated_at', NULL,
   'Possible raw DB field leak: updated_at should not appear in rendered blog content', 'system', TRUE)
ON CONFLICT DO NOTHING;

INSERT INTO acp_shared.acp_output_rules
  (tenant_id, stage, rule_type, pattern, action_value, error_message, source_type, is_active)
VALUES
  (NULL, NULL, 'flag', 'from $', NULL,
   'Price quote pattern: explicit pricing must not appear unless explicitly approved', 'system', TRUE)
ON CONFLICT DO NOTHING;
