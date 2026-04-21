CREATE TABLE IF NOT EXISTS shared.tenant_api_usage (
    id              UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id       UUID NOT NULL REFERENCES shared.tenants(tenant_id),
    endpoint        VARCHAR(100) NOT NULL,
    method          VARCHAR(10) NOT NULL,
    status_code     INTEGER NOT NULL,
    response_ms     INTEGER,
    called_at       TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_tenant_api_usage_tenant_id ON shared.tenant_api_usage(tenant_id);
CREATE INDEX IF NOT EXISTS idx_tenant_api_usage_called_at ON shared.tenant_api_usage(called_at);
CREATE OR REPLACE VIEW shared.v_tenant_monthly_usage AS
SELECT
    tenant_id,
    DATE_TRUNC('month', called_at) AS month,
    COUNT(*) AS total_calls,
    COUNT(*) FILTER (WHERE status_code < 400) AS successful_calls,
    COUNT(*) FILTER (WHERE status_code = 429) AS rate_limited_calls,
    AVG(response_ms)::INTEGER AS avg_response_ms,
    COUNT(DISTINCT endpoint) AS endpoints_used
FROM shared.tenant_api_usage
GROUP BY tenant_id, DATE_TRUNC('month', called_at);
