# Role-based architecture

## Role mapping

- CUSTOMER -> customer-mobile
- RIDER -> rider-mobile
- RESTAURANT_OWNER -> business-web
- ADMIN -> business-web

## Shared backend

- One FastAPI backend remains the source of truth.
- One PostgreSQL database is shared by all clients.
- One user model and role enum are shared across the system.

## Scope

This repository intentionally contains a shared backend and role-specific frontends without creating separate backend apps or databases.

## Status

This is architecture-only work. Feature implementations are intentionally deferred.
