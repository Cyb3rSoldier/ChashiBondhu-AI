-- 006: Marketplace Phase B1 — saved items (wishlist / save for later), favourite farmers,
--      opt-in restock + price-drop alerts, verified-purchase reviews.
-- Safe to re-run. Nothing existing is deleted. Rollback block at the end.
BEGIN;

-- 1) saved items (wishlist; "save for later" from the cart lands here too) ----------------------
CREATE TABLE IF NOT EXISTS saved_items (
  customer_id bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  listing_id  bigint NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
  created_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (customer_id, listing_id)
);

-- 2) favourite farmers ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS favourite_farmers (
  customer_id bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  farmer_id   bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (customer_id, farmer_id),
  CHECK (customer_id <> farmer_id)
);
CREATE INDEX IF NOT EXISTS ix_favourite_farmers_farmer ON favourite_farmers (farmer_id);

-- 3) opt-in product alerts --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS product_alerts (
  customer_id   bigint  NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  listing_id    bigint  NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
  on_restock    boolean NOT NULL DEFAULT false,
  on_price_drop boolean NOT NULL DEFAULT false,
  created_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (customer_id, listing_id),
  CHECK (on_restock OR on_price_drop)
);
CREATE INDEX IF NOT EXISTS ix_product_alerts_listing ON product_alerts (listing_id);

-- 4) reviews: verified purchase only, admin can hide later -------------------------------------------
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS order_item_id bigint REFERENCES order_items(id) ON DELETE SET NULL;
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'visible';
ALTER TABLE reviews ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'reviews_status_check') THEN
    ALTER TABLE reviews ADD CONSTRAINT reviews_status_check CHECK (status IN ('visible', 'hidden'));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'reviews_comment_len') THEN
    ALTER TABLE reviews ADD CONSTRAINT reviews_comment_len CHECK (comment IS NULL OR length(comment) <= 1000);
  END IF;
END $$;
CREATE INDEX IF NOT EXISTS ix_reviews_listing ON reviews (listing_id, status, created_at DESC);

CREATE OR REPLACE FUNCTION reviews_require_purchase() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE item bigint;
BEGIN
  SELECT i.id INTO item FROM order_items i JOIN orders o ON o.id = i.order_id
   WHERE o.customer_id = NEW.customer_id AND i.listing_id = NEW.listing_id
     AND o.status = 'delivered' AND i.farmer_status <> 'rejected'
   ORDER BY o.created_at DESC LIMIT 1;
  IF item IS NULL THEN
    RAISE EXCEPTION 'review needs a delivered purchase of this product' USING ERRCODE = '23514';
  END IF;
  NEW.order_item_id := item;
  NEW.updated_at := now();
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_reviews_require_purchase ON reviews;
CREATE TRIGGER trg_reviews_require_purchase BEFORE INSERT OR UPDATE OF listing_id, customer_id, rating, comment
  ON reviews FOR EACH ROW EXECUTE FUNCTION reviews_require_purchase();

-- 5) notifications from listing changes (deduplicated, customers only) ----------------------------------
CREATE OR REPLACE FUNCTION listings_notify_watchers() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  new_price numeric := COALESCE(NEW.discount_price, NEW.price_per_unit);
  old_price numeric;
  can_buy_now boolean := NEW.status = 'active' AND NEW.listing_type = 'available' AND NEW.quantity >= NEW.min_order;
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF NEW.status = 'active' THEN                        -- new product from a favourite farmer
      INSERT INTO notifications (user_id, kind, title, body, link, dedupe_key)
      SELECT f.customer_id, 'market', 'প্রিয় কৃষকের নতুন পণ্য / New product from a favourite farmer',
             NEW.title, '/market/' || NEW.id, 'newlisting:' || NEW.id
        FROM favourite_farmers f JOIN users u ON u.id = f.customer_id
       WHERE f.farmer_id = NEW.farmer_id AND u.role = 'customer' AND u.status = 'active'
      ON CONFLICT (user_id, dedupe_key) WHERE dedupe_key IS NOT NULL DO NOTHING;
    END IF;
    RETURN NEW;
  END IF;

  old_price := COALESCE(OLD.discount_price, OLD.price_per_unit);
  -- back in stock (was not buyable, now is): at most one per product per customer per day
  IF can_buy_now AND NOT (OLD.status = 'active' AND OLD.listing_type = 'available' AND OLD.quantity >= OLD.min_order) THEN
    INSERT INTO notifications (user_id, kind, title, body, link, dedupe_key)
    SELECT a.customer_id, 'market', 'আবার পাওয়া যাচ্ছে / Back in stock', NEW.title, '/market/' || NEW.id,
           'restock:' || NEW.id || ':' || to_char(now() AT TIME ZONE 'Asia/Dhaka', 'YYYYMMDD')
      FROM product_alerts a JOIN users u ON u.id = a.customer_id
     WHERE a.listing_id = NEW.id AND a.on_restock AND u.role = 'customer' AND u.status = 'active'
    ON CONFLICT (user_id, dedupe_key) WHERE dedupe_key IS NOT NULL DO NOTHING;
  END IF;
  -- price dropped: one per product per new price
  IF NEW.status = 'active' AND new_price < old_price THEN
    INSERT INTO notifications (user_id, kind, title, body, link, dedupe_key)
    SELECT a.customer_id, 'market', 'দাম কমেছে / Price dropped',
           NEW.title || ': ৳' || trim(to_char(old_price, 'FM999999990.##')) || ' → ৳'
             || trim(to_char(new_price, 'FM999999990.##')),
           '/market/' || NEW.id, 'price:' || NEW.id || ':' || new_price::text
      FROM product_alerts a JOIN users u ON u.id = a.customer_id
     WHERE a.listing_id = NEW.id AND a.on_price_drop AND u.role = 'customer' AND u.status = 'active'
    ON CONFLICT (user_id, dedupe_key) WHERE dedupe_key IS NOT NULL DO NOTHING;
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS trg_listings_notify_watchers ON listings;
CREATE TRIGGER trg_listings_notify_watchers AFTER INSERT OR UPDATE OF status, quantity, min_order, listing_type,
  price_per_unit, discount_price ON listings FOR EACH ROW EXECUTE FUNCTION listings_notify_watchers();

-- 6) record the migration ------------------------------------------------------------------------
DO $$ BEGIN
  IF (SELECT data_type FROM information_schema.columns WHERE table_schema = 'public'
      AND table_name = 'schema_migrations' AND column_name = 'version') IN ('integer', 'bigint', 'smallint') THEN
    EXECUTE 'INSERT INTO schema_migrations (version) SELECT 6 WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version = 6)';
  ELSE
    EXECUTE 'INSERT INTO schema_migrations (version) SELECT ''006_marketplace_b1'' WHERE NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version::text = ''006_marketplace_b1'')';
  END IF;
END $$;

COMMIT;

/* ROLLBACK (by hand only):
BEGIN;
DROP TRIGGER IF EXISTS trg_listings_notify_watchers ON listings; DROP FUNCTION IF EXISTS listings_notify_watchers();
DROP TRIGGER IF EXISTS trg_reviews_require_purchase ON reviews;  DROP FUNCTION IF EXISTS reviews_require_purchase();
DROP TABLE IF EXISTS product_alerts, favourite_farmers, saved_items;
ALTER TABLE reviews DROP CONSTRAINT IF EXISTS reviews_status_check, DROP CONSTRAINT IF EXISTS reviews_comment_len;
DELETE FROM schema_migrations WHERE version::text IN ('6', '006_marketplace_b1');
COMMIT;
*/
