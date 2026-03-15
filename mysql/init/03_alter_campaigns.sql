-- Migration: Add target_stores column to campaigns table
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS target_stores VARCHAR(1024) AFTER entry_required;

-- Migration: Add is_show column to campaigns table
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS is_show BOOLEAN NOT NULL DEFAULT TRUE AFTER source_list_url;

-- Migration: Add is_validated column to campaigns table
-- NULL = 検証未実施/エラー、TRUE = 検証OK、FALSE = 検証失敗
ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS is_validated BOOLEAN DEFAULT NULL AFTER is_show;
