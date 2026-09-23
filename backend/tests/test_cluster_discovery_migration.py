from dingofs_platform.inventory.models import Cluster
from dingofs_platform.clusters.models import ClusterOperation


def test_discovery_columns_and_duplicate_display_names(app):
    assert "binding_state" in Cluster.__table__.columns
    assert not Cluster.__table__.columns.name.unique
    assert not any("password" in c.name for c in ClusterOperation.__table__.columns)
