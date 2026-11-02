"""Scope Classroom schedule uniqueness to each user."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "m6_schedule_user_unique"
down_revision: Union[str, Sequence[str], None] = "343253623f7c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "class_schedules" not in inspector.get_table_names():
        return

    indexes = {index["name"]: index for index in inspector.get_indexes("class_schedules")}
    unique_constraints = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("class_schedules")
    }

    with op.batch_alter_table("class_schedules") as batch:
        legacy_index = indexes.get("ix_class_schedules_external_id")
        if legacy_index and legacy_index.get("unique"):
            batch.drop_index("ix_class_schedules_external_id")
        if "uq_class_schedules_user_external_id" not in unique_constraints:
            batch.create_unique_constraint(
                "uq_class_schedules_user_external_id",
                ["user_id", "external_id"],
            )

    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("class_schedules")}
    if "ix_class_schedules_external_id" not in indexes:
        op.create_index(
            "ix_class_schedules_external_id",
            "class_schedules",
            ["external_id"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "class_schedules" not in inspector.get_table_names():
        return

    duplicate = bind.execute(
        sa.text(
            "SELECT external_id FROM class_schedules "
            "GROUP BY external_id HAVING COUNT(*) > 1 LIMIT 1"
        )
    ).first()
    if duplicate:
        raise RuntimeError(
            "Cannot restore global class schedule external_id uniqueness while "
            "multiple users have matching external IDs."
        )

    constraints = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("class_schedules")
    }
    indexes = {index["name"]: index for index in inspector.get_indexes("class_schedules")}
    with op.batch_alter_table("class_schedules") as batch:
        if "uq_class_schedules_user_external_id" in constraints:
            batch.drop_constraint("uq_class_schedules_user_external_id", type_="unique")
        if "ix_class_schedules_external_id" in indexes:
            batch.drop_index("ix_class_schedules_external_id")
            batch.create_index(
                "ix_class_schedules_external_id",
                ["external_id"],
                unique=True,
            )
