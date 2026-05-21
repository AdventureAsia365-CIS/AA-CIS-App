-- =============================================================================
-- Migration 021: audit_actor_type enum — add B2B actor values
-- Project: AA-CIS (Adventure Asia Content Intelligence System)
-- Date: 21/05/2026
-- Ticket: AA-89 — B2B self-approval HITL
-- =============================================================================
-- Creates audit_actor_type in acp_shared schema if it does not exist,
-- then adds tenant_admin and tenant_reviewer values idempotently.
--
-- Note: ALTER TYPE ... ADD VALUE cannot run inside an explicit transaction.
-- Run this script outside a BEGIN/COMMIT block (asyncpg autocommit is fine).
-- =============================================================================

-- Create the enum if it doesn't already exist (hitl_reviewer is the original value)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_type t
    JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE t.typname = 'audit_actor_type'
      AND n.nspname = 'acp_shared'
  ) THEN
    CREATE TYPE acp_shared.audit_actor_type AS ENUM (
      'hitl_reviewer',
      'tenant_admin',
      'tenant_reviewer'
    );
  END IF;
END $$;

-- Idempotent value additions (safe to re-run)
ALTER TYPE acp_shared.audit_actor_type ADD VALUE IF NOT EXISTS 'tenant_admin';
ALTER TYPE acp_shared.audit_actor_type ADD VALUE IF NOT EXISTS 'tenant_reviewer';
