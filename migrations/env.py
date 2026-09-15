"""Explicit migration entry point; the application never creates tables."""

import os

from alembic import context

from reliability_intelligence.serving.database import make_engine, metadata

config = context.config
engine = make_engine(config.attributes.get("database_url") or os.environ["RIP_DATABASE_URL"])
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()
engine.dispose()
