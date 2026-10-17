"""add study plans and study plan sessions tables

Revision ID: s1_tudy_plans_001
Revises: a55a2d6c605e_add_chat_conversation_history_tables
Create Date: 2026-10-17 05:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 's1_tudy_plans_001'
down_revision: Union[str, None] = 'a55a2d6c605e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('study_plans',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.String(length=255), nullable=False),
    sa.Column('title', sa.String(length=500), nullable=False),
    sa.Column('exam_title', sa.String(length=300), nullable=True),
    sa.Column('exam_date', sa.DateTime(timezone=True), nullable=True),
    sa.Column('syllabus', sa.Text(), nullable=True),
    sa.Column('topics', sa.Text(), nullable=True),
    sa.Column('preferences', sa.Text(), nullable=True),
    sa.Column('stats', sa.Text(), nullable=True),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_study_plans_id'), 'study_plans', ['id'], unique=False)
    op.create_index(op.f('ix_study_plans_user_id'), 'study_plans', ['user_id'], unique=False)
    op.create_table('study_plan_sessions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('plan_id', sa.Integer(), nullable=False),
    sa.Column('session_date', sa.DateTime(timezone=True), nullable=False),
    sa.Column('session_type', sa.String(length=20), nullable=False),
    sa.Column('topic', sa.String(length=500), nullable=False),
    sa.Column('duration_minutes', sa.Integer(), nullable=False),
    sa.Column('order_index', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['plan_id'], ['study_plans.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_study_plan_sessions_id'), 'study_plan_sessions', ['id'], unique=False)
    op.create_index(op.f('ix_study_plan_sessions_plan_id'), 'study_plan_sessions', ['plan_id'], unique=False)
    op.create_index(op.f('ix_study_plan_sessions_session_date'), 'study_plan_sessions', ['session_date'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_study_plan_sessions_session_date'), table_name='study_plan_sessions')
    op.drop_index(op.f('ix_study_plan_sessions_plan_id'), table_name='study_plan_sessions')
    op.drop_index(op.f('ix_study_plan_sessions_id'), table_name='study_plan_sessions')
    op.drop_table('study_plan_sessions')
    op.drop_index(op.f('ix_study_plans_user_id'), table_name='study_plans')
    op.drop_index(op.f('ix_study_plans_id'), table_name='study_plans')
    op.drop_table('study_plans')
