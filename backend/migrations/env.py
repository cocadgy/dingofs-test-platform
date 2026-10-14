from dingofs_platform.performance import models as performance_models  # noqa: F401
from dingofs_platform.tool_packages import models as tool_models  # noqa: F401
from dingofs_platform.mount_profiles import models as mount_profile_models  # noqa: F401
from dingofs_platform.cache_profiles import models as cache_profile_models  # noqa: F401
from dingofs_platform.storage import models as storage_models  # noqa: F401
from dingofs_platform.resources import models as resource_models  # noqa: F401
from dingofs_platform.remote import models as remote_models  # noqa: F401
from dingofs_platform.clusters import models as cluster_models  # noqa: F401
from alembic import context
from sqlalchemy import create_engine
from dingofs_platform.settings import Settings
from dingofs_platform.db import Base
from dingofs_platform.auth import models as auth  # noqa: F401 - register SQLAlchemy metadata
from dingofs_platform.inventory import models as inventory  # noqa: F401 - register SQLAlchemy metadata
from dingofs_platform.configuration import models as configuration  # noqa: F401 - register SQLAlchemy metadata
from dingofs_platform.audit import models as audit  # noqa: F401 - register SQLAlchemy metadata


def run():
    url = Settings().database_url
    if context.is_offline_mode():
        context.configure(url=url, target_metadata=Base.metadata, literal_binds=True)
        with context.begin_transaction():
            context.run_migrations()
    else:
        engine = create_engine(url)
        with engine.connect() as connection:
            context.configure(
                connection=connection, target_metadata=Base.metadata, compare_type=True
            )
            with context.begin_transaction():
                context.run_migrations()
        engine.dispose()


run()
