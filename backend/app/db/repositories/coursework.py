from sqlalchemy import func
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime
from app.db.models import (
    GoogleCredential, AgentRun, AgentEvent, Course, Assignment,
    AssignmentMaterial, AssignmentTemplate, AssignmentSolution, Submission, ClassSchedule,
    AttendanceRecord, Exam, Quiz, Announcement, ChangeEvent,
    Notification, DailyReport, Setting
)

class CourseRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_external_id(self, external_id: str, user_id: str = "legacy") -> Optional[Course]:
        course = self.db.query(Course).filter(Course.external_id == external_id, Course.user_id == user_id).first()
        if not course and user_id != "legacy":
            course = self.db.query(Course).filter(Course.external_id == external_id, Course.user_id == "legacy").first()
        return course

    def create_or_update(self, course_data: dict) -> Course:
        course = self.get_by_external_id(course_data["external_id"], course_data.get("user_id", "legacy"))
        if course:
            for key, value in course_data.items():
                setattr(course, key, value)
        else:
            course = Course(**course_data)
            self.db.add(course)
        self.db.commit()
        self.db.refresh(course)
        return course

    def create(self, course_data: dict) -> Course:
        course = Course(**course_data)
        self.db.add(course)
        self.db.commit()
        self.db.refresh(course)
        return course

    def get_all(self, user_id: str = "legacy") -> List[Course]:
        courses = self.db.query(Course).filter(Course.user_id == user_id).all()
        if not courses and user_id != "legacy":
            courses = self.db.query(Course).filter(Course.user_id == "legacy").all()
        return courses


class AssignmentRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_external_id(self, external_id: str, user_id: str = "legacy") -> Optional[Assignment]:
        return self.db.query(Assignment).filter(Assignment.external_id == external_id, Assignment.user_id == user_id).first()

    def get_by_id(self, assignment_id: int, user_id: str = "legacy") -> Optional[Assignment]:
        return self.db.query(Assignment).filter(Assignment.id == assignment_id, Assignment.user_id == user_id).first()

    def create(self, assignment_data: dict) -> Assignment:
        assignment = Assignment(**assignment_data)
        self.db.add(assignment)
        self.db.commit()
        self.db.refresh(assignment)
        return assignment

    def create_or_update(self, assignment_data: dict) -> Assignment:
        assignment = self.get_by_external_id(assignment_data["external_id"], assignment_data.get("user_id", "legacy"))
        if assignment:
            for key, value in assignment_data.items():
                setattr(assignment, key, value)
        else:
            assignment = Assignment(**assignment_data)
            self.db.add(assignment)
        self.db.commit()
        self.db.refresh(assignment)
        return assignment

    def get_pending_review(self) -> List[Assignment]:
        return self.db.query(Assignment).filter(Assignment.status == "ready_for_review").all()

    def get_by_status(self, status: str) -> List[Assignment]:
        return self.db.query(Assignment).filter(Assignment.status == status).all()

    def get_all(self, user_id: str = "legacy") -> List[Assignment]:
        return self.db.query(Assignment).filter(Assignment.user_id == user_id).order_by(Assignment.due_at.asc().nullslast()).all()


class AssignmentMaterialRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, material_data: dict) -> AssignmentMaterial:
        material = AssignmentMaterial(**material_data)
        self.db.add(material)
        self.db.commit()
        self.db.refresh(material)
        return material

    def get_by_assignment(self, assignment_id: int) -> List[AssignmentMaterial]:
        return self.db.query(AssignmentMaterial).filter(AssignmentMaterial.assignment_id == assignment_id).all()

    def delete_by_assignment(self, assignment_id: int):
        self.db.query(AssignmentMaterial).filter(AssignmentMaterial.assignment_id == assignment_id).delete()
        self.db.commit()


class AssignmentTemplateRepository:
    def __init__(self, db: Session, user_id: str = "legacy"):
        self.db = db
        self.user_id = user_id

    def get_all(self) -> List:
        from app.db.models import AssignmentTemplate
        return self.db.query(AssignmentTemplate).filter(
            AssignmentTemplate.user_id == self.user_id,
        ).all()

    def get_default(self):
        from app.db.models import AssignmentTemplate
        return self.db.query(AssignmentTemplate).filter(
            AssignmentTemplate.user_id == self.user_id,
            AssignmentTemplate.is_default == True,
        ).first()

    def get_by_id(self, template_id: int):
        from app.db.models import AssignmentTemplate
        return self.db.query(AssignmentTemplate).filter(
            AssignmentTemplate.id == template_id,
            AssignmentTemplate.user_id == self.user_id,
        ).first()

    def create(self, template_data: dict):
        from app.db.models import AssignmentTemplate
        template = AssignmentTemplate(user_id=self.user_id, **template_data)
        self.db.add(template)
        self.db.commit()
        self.db.refresh(template)
        return template

    def update(self, template_id: int, template_data: dict):
        from app.db.models import AssignmentTemplate
        template = self.get_by_id(template_id)
        if template:
            for key, value in template_data.items():
                setattr(template, key, value)
            self.db.commit()
            self.db.refresh(template)
        return template

    def delete(self, template_id: int):
        from app.db.models import AssignmentTemplate
        template = self.get_by_id(template_id)
        if template:
            self.db.delete(template)
            self.db.commit()
        return template

    def set_default(self, template_id: int):
        from app.db.models import AssignmentTemplate
        self.db.query(AssignmentTemplate).filter(
            AssignmentTemplate.user_id == self.user_id,
        ).update({AssignmentTemplate.is_default: False})
        template = self.get_by_id(template_id)
        if template:
            template.is_default = True
            self.db.commit()
            self.db.refresh(template)
        return template


class AssignmentSolutionRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_assignment(self, assignment_id: int) -> Optional[AssignmentSolution]:
        return self.db.query(AssignmentSolution).filter(AssignmentSolution.assignment_id == assignment_id).first()

    def create_or_update(self, solution_data: dict) -> AssignmentSolution:
        solution = self.get_by_assignment(solution_data["assignment_id"])
        if solution:
            for key, value in solution_data.items():
                setattr(solution, key, value)
        else:
            solution = AssignmentSolution(**solution_data)
            self.db.add(solution)
        self.db.commit()
        self.db.refresh(solution)
        return solution


class SubmissionRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_assignment(self, assignment_id: int) -> Optional[Submission]:
        return self.db.query(Submission).filter(Submission.assignment_id == assignment_id).first()

    def create_or_update(self, submission_data: dict) -> Submission:
        submission = self.get_by_assignment(submission_data["assignment_id"])
        if submission:
            for key, value in submission_data.items():
                setattr(submission, key, value)
        else:
            submission = Submission(**submission_data)
            self.db.add(submission)
        self.db.commit()
        self.db.refresh(submission)
        return submission
