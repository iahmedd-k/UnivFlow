"""Persist Classroom file cache metadata and object-storage keys."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "m4_course_file_cache"
down_revision: Union[str, Sequence[str], None] = (
    "add_fk_and_soft_deletes",
    "s1_tudy_plans_001",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if "assignment_materials" not in sa.inspect(bind).get_table_names():
        return
    columns = {column["name"] for column in sa.inspect(bind).get_columns("assignment_materials")}
    additions = {
        "storage_key": sa.Column("storage_key", sa.String(length=512), nullable=True),
        "drive_modified_time": sa.Column("drive_modified_time", sa.DateTime(timezone=True), nullable=True),
        "drive_checksum": sa.Column("drive_checksum", sa.String(length=128), nullable=True),
        "file_size": sa.Column("file_size", sa.Integer(), nullable=True),
    }
    for name, column in additions.items():
        if name not in columns:
            op.add_column("assignment_materials", column)


def downgrade() -> None:
    bind = op.get_bind()
    if "assignment_materials" not in sa.inspect(bind).get_table_names():
        return
    columns = {column["name"] for column in sa.inspect(bind).get_columns("assignment_materials")}
    for name in ("file_size", "drive_checksum", "drive_modified_time", "storage_key"):
        if name in columns:
            op.drop_column("assignment_materials", name)
