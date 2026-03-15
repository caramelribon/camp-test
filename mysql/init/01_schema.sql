-- キャンペーンパイプライン用スキーマ

CREATE TABLE IF NOT EXISTS points (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    point_name VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_point_name (point_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS payment_methods (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    type ENUM('card', 'qrCode') NOT NULL,
    name VARCHAR(255) NOT NULL,
    point_id BIGINT,
    campaign_list_url VARCHAR(2048),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_name (name),
    FOREIGN KEY fk_point (point_id) REFERENCES points(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS campaigns (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    point_id BIGINT NOT NULL,
    title VARCHAR(512) NOT NULL,
    period_text VARCHAR(512),
    reward_rate_text VARCHAR(512),
    entry_required BOOLEAN,
    target_stores VARCHAR(1024),
    detail_url VARCHAR(2048) NOT NULL,
    source_list_url VARCHAR(2048),
    is_show BOOLEAN NOT NULL DEFAULT TRUE,
    is_validated BOOLEAN DEFAULT NULL,
    content_hash VARCHAR(64),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_detail_url (detail_url(768)),
    FOREIGN KEY fk_point (point_id) REFERENCES points(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS crawl_logs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    execution_id VARCHAR(36) NOT NULL,
    url VARCHAR(2048) NOT NULL,
    label ENUM('campaign_detail', 'campaign_list', 'not_campaign', 'uncertain') NOT NULL,
    detail_score INT,
    list_score INT,
    not_campaign_score INT,
    is_detail_saveable BOOLEAN,
    used_llm BOOLEAN DEFAULT FALSE,
    confidence_type VARCHAR(50),
    reason TEXT,
    campaign_id BIGINT,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_execution_id (execution_id),
    INDEX idx_label (label),
    INDEX idx_url (url(768))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS execution_runs (
    id VARCHAR(36) PRIMARY KEY,
    service_name VARCHAR(255) NOT NULL,
    seed_urls JSON NOT NULL,
    status ENUM('running', 'completed', 'failed') DEFAULT 'running',
    total_urls INT DEFAULT 0,
    processed_urls INT DEFAULT 0,
    saved_campaigns INT DEFAULT 0,
    errors INT DEFAULT 0,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP NULL,
    INDEX idx_service_name (service_name),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
