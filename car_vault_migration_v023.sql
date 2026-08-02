-- The Car Vault v0.2.3
-- Run once in Supabase SQL Editor before deploying v0.2.3.

alter table public.vehicles
add column if not exists source_image_url text not null default '';

-- Backfill from matching shortlist records where possible.
update public.vehicles as v
set source_image_url = s.source_image_url
from public.shortlist_items as s
where v.game_id = s.game_id
  and v.player_id = s.player_id
  and v.advert_url = s.advert_url
  and coalesce(v.source_image_url, '') = ''
  and coalesce(s.source_image_url, '') <> '';
