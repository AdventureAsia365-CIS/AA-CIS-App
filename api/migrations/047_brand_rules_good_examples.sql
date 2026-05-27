-- AA-129: add good_examples column to tenant_brand_rules
ALTER TABLE shared.tenant_brand_rules ADD COLUMN IF NOT EXISTS good_examples TEXT;
