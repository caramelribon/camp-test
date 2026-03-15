-- ポイントの初期データ

INSERT INTO points (id, point_name) VALUES
(1, 'PayPayポイント'),
(2, '楽天ポイント'),
(3, 'nanacoポイント'),
(4, 'Pontaポイント'),
(5, 'Vポイント');

-- 決済手段の初期データ

INSERT INTO payment_methods (type, name, point_id, campaign_list_url) VALUES
('qrCode', 'PayPay', 1, 'https://paypay.ne.jp/event/'),
('card', 'Oliveカード', 5, 'https://www.smbc.co.jp/kojin/campaign/'),
('card', '楽天カード', 2, 'https://www.rakuten-card.co.jp/campaign/?l-id=corp_oo_gnav_campaign_responsive'),
('card', 'セブンプラスカード', 3, 'https://www.7card.co.jp/campaign/index.html#campaign'),
('qrCode', 'au Pay', 4, 'https://aupay.wallet.auone.jp/campaign/');
