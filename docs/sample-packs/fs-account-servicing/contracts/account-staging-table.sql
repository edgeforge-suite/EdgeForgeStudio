-- Generated review copy. Edit the canonical project JSON, then regenerate this file.
CREATE TABLE account_staging (
    staging_row_id  VARCHAR(36)   NOT NULL PRIMARY KEY,
    run_id          VARCHAR(64)   NOT NULL,
    business_date   DATE          NOT NULL,
    staging_status  VARCHAR(16)   NOT NULL,
    created_at      TIMESTAMP     NOT NULL,
    account_id      VARCHAR(36)   NOT NULL,
    customer_id     VARCHAR(36)   NOT NULL,
    balance         DECIMAL(15,2) NOT NULL
);
