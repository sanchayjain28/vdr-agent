-- V7: Allow NULL reasoning in fitment_results.
--
-- Phase 7 decision: when a topic's Bedrock call fails, we upsert
-- status='failed' with reasoning=NULL. V5 defined reasoning TEXT NOT NULL,
-- which would raise NotNullViolation on any failed-topic upsert.
-- This migration removes that constraint before Phase 7 code is deployed.

SET search_path TO vdr_agent, public;

ALTER TABLE vdr_agent.fitment_results
    ALTER COLUMN reasoning DROP NOT NULL;
