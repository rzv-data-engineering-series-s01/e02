CREATE OR REPLACE FUNCTION ${kimball}.UTM_CAMPAIGN_TO_PRODUCT (CAMPAIGN VARCHAR)
select kimball.utm_to_financial_channel(...)
