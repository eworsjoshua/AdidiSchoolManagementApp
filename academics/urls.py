from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    AcademicSessionViewSet, EnrollmentViewSet, MyClassesView, MyEnrollmentView,
    SchoolClassViewSet, SubjectViewSet, TeachingAssignmentViewSet,
)

router = DefaultRouter()
router.register("sessions", AcademicSessionViewSet, basename="session")
router.register("classes", SchoolClassViewSet, basename="class")
router.register("subjects", SubjectViewSet, basename="subject")
router.register("teaching-assignments", TeachingAssignmentViewSet, basename="teaching-assignment")
router.register("enrollments", EnrollmentViewSet, basename="enrollment")

urlpatterns = [
    path("my-classes/", MyClassesView.as_view(), name="my-classes"),
    path("my-enrollment/", MyEnrollmentView.as_view(), name="my-enrollment"),
] + router.urls