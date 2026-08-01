-- The Car Vault v0.2.0
-- Run this once in Supabase SQL Editor before deploying the updated app.

create extension if not exists pgcrypto;

create table if not exists public.vault_profiles (
    id uuid primary key default gen_random_uuid(),
    display_name text not null,
    profile_name text not null,
    profile_name_key text not null unique,
    pin_hash text not null,
    created_at timestamptz not null default now()
);

create table if not exists public.vault_collections (
    id uuid primary key default gen_random_uuid(),
    profile_id uuid not null references public.vault_profiles(id) on delete cascade,
    collection_name text not null,
    description text not null default '',
    is_default boolean not null default false,
    created_at timestamptz not null default now(),
    unique(profile_id, collection_name)
);

create table if not exists public.vault_items (
    id uuid primary key default gen_random_uuid(),
    profile_id uuid not null references public.vault_profiles(id) on delete cascade,
    collection_id uuid references public.vault_collections(id) on delete set null,
    vehicle_name text not null,
    vehicle_year integer,
    advertised_price numeric(14,2) not null default 0,
    currency_symbol text not null default '€',
    mileage_text text not null default '',
    vehicle_location text not null default '',
    seller_type text not null default 'Private',
    advert_url text not null default '',
    source_website text not null default '',
    source_image_url text not null default '',
    image_path text,
    advert_description text not null default '',
    personal_notes text not null default '',
    tags text[] not null default '{}',
    item_status text not null default 'Saved',
    import_status text not null default 'manual',
    first_seen_at timestamptz not null default now(),
    last_checked_at timestamptz,
    is_archived boolean not null default false,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists vault_items_profile_idx
    on public.vault_items(profile_id, created_at desc);

create index if not exists vault_items_collection_idx
    on public.vault_items(collection_id);

create index if not exists vault_items_tags_idx
    on public.vault_items using gin(tags);

alter table public.vault_profiles enable row level security;
alter table public.vault_collections enable row level security;
alter table public.vault_items enable row level security;

-- The Streamlit app currently uses the Supabase service role server-side.
-- No anonymous/client write policies are created at this prototype stage.
