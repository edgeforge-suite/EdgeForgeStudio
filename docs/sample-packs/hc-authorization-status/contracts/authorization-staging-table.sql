-- Generated review copy. Edit the canonical project JSON, then regenerate this file.
CREATE TABLE authorization_staging (
    staging_row_id   VARCHAR(36)   NOT NULL PRIMARY KEY,
    run_id           VARCHAR(64)   NOT NULL,
    business_date    DATE          NOT NULL,
    staging_status   VARCHAR(16)   NOT NULL,
    created_at       TIMESTAMP     NOT NULL,
    authorization_id VARCHAR(36)   NOT NULL,
    member_id        VARCHAR(36)   NOT NULL,
    service_units    DECIMAL(13,2) NOT NULL
);
