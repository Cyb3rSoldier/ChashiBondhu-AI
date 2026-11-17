-- ChashiBondhu migration 004 - Marketplace + customer side (Phase A)
-- Run AFTER 003: Supabase Dashboard -> SQL Editor -> New query -> paste this whole file -> Run.
-- Safe to run again. One transaction.
--
-- * listings: 'tools_equipment' category, optional farmer discount price (must be lower than the price)
-- * pg_trgm + index: typo-tolerant product search
-- * notifications: kind + dedupe_key (the same event never creates two notifications)
-- * trigger: the customer is notified when a farmer moves an order item or an order changes status

BEGIN;

CREATE EXTENSION IF NOT EXISTS pg_trgm;

ALTER TABLE listings DROP CONSTRAINT IF EXISTS listings_category_check;
ALTER TABLE listings ADD  CONSTRAINT listings_category_check CHECK (category IN (
  'vegetable', 'fruit', 'grain', 'pulse', 'oilseed', 'spice', 'fish', 'meat_poultry', 'dairy', 'eggs',
  'seeds_inputs', 'tools_equipment', 'other'));

ALTER TABLE listings ADD COLUMN IF NOT EXISTS discount_price NUMERIC(10,2);
ALTER TABLE listings DROP CONSTRAINT IF EXISTS listings_discount_check;
ALTER TABLE listings ADD  CONSTRAINT listings_discount_check
  CHECK (discount_price IS NULL OR (discount_price > 0 AND discount_price < price_per_unit));

CREATE INDEX IF NOT EXISTS idx_listings_title_trgm ON listings USING gin (lower(title) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_listings_market ON listings (status, category, district_code);
CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders (customer_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items (order_id);

ALTER TABLE notifications ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'general';
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS dedupe_key TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS uq_notifications_dedupe ON notifications (user_id, dedupe_key) WHERE dedupe_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications (user_id, created_at DESC);

CREATE OR REPLACE FUNCTION notify_item_status() RETURNS trigger AS $$
DECLARE o RECORD; bn TEXT; en TEXT;
BEGIN
  IF NEW.farmer_status = OLD.farmer_status THEN RETURN NEW; END IF;
  SELECT id, order_number, customer_id INTO o FROM orders WHERE id = NEW.order_id;
  bn := CASE NEW.farmer_status WHEN 'accepted' THEN 'কৃষক অর্ডার নিশ্চিত করেছেন'
                               WHEN 'packed' THEN 'পণ্য ডেলিভারির জন্য প্রস্তুত'
                               WHEN 'handed_over' THEN 'পণ্য পাঠানো হয়েছে'
                               WHEN 'rejected' THEN 'কৃষক এই পণ্যটি দিতে পারছেন না' ELSE NULL END;
  en := CASE NEW.farmer_status WHEN 'accepted' THEN 'The farmer confirmed your order'
                               WHEN 'packed' THEN 'Ready for delivery'
                               WHEN 'handed_over' THEN 'Out for delivery'
                               WHEN 'rejected' THEN 'The farmer cannot supply this item' ELSE NULL END;
  IF bn IS NOT NULL THEN
    INSERT INTO notifications (user_id, kind, title, body, link, dedupe_key)
    VALUES (o.customer_id, 'order', bn || ' / ' || en, NEW.title || ' · ' || o.order_number,
            '/customer/orders/' || o.order_number, 'item:' || NEW.id || ':' || NEW.farmer_status)
    ON CONFLICT (user_id, dedupe_key) WHERE dedupe_key IS NOT NULL DO NOTHING;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_items_notify ON order_items;
CREATE TRIGGER trg_items_notify AFTER UPDATE OF farmer_status ON order_items
  FOR EACH ROW EXECUTE FUNCTION notify_item_status();

CREATE OR REPLACE FUNCTION notify_order_status() RETURNS trigger AS $$
DECLARE bn TEXT; en TEXT;
BEGIN
  IF NEW.status = OLD.status THEN RETURN NEW; END IF;
  bn := CASE NEW.status WHEN 'delivered' THEN 'অর্ডার ডেলিভারি হয়েছে' WHEN 'cancelled' THEN 'অর্ডার বাতিল হয়েছে'
                        WHEN 'shipped' THEN 'অর্ডার পাঠানো হয়েছে' WHEN 'confirmed' THEN 'অর্ডার নিশ্চিত হয়েছে' ELSE NULL END;
  en := CASE NEW.status WHEN 'delivered' THEN 'Order delivered' WHEN 'cancelled' THEN 'Order cancelled'
                        WHEN 'shipped' THEN 'Order shipped' WHEN 'confirmed' THEN 'Order confirmed' ELSE NULL END;
  IF bn IS NOT NULL THEN
    INSERT INTO notifications (user_id, kind, title, body, link, dedupe_key)
    VALUES (NEW.customer_id, 'order', bn || ' / ' || en, NEW.order_number, '/customer/orders/' || NEW.order_number,
            'order:' || NEW.id || ':' || NEW.status)
    ON CONFLICT (user_id, dedupe_key) WHERE dedupe_key IS NOT NULL DO NOTHING;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_orders_notify ON orders;
CREATE TRIGGER trg_orders_notify AFTER UPDATE OF status ON orders
  FOR EACH ROW EXECUTE FUNCTION notify_order_status();

INSERT INTO schema_migrations (version) VALUES ('004_marketplace') ON CONFLICT DO NOTHING;

COMMIT;
