from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    ClassResultsView, ExamViewSet, MyResultView, MyScoresView, ScoreViewSet, StudentResultView,
)

router = DefaultRouter()
router.register("exams", ExamViewSet, basename="exam")
router.register("scores", ScoreViewSet, basename="score")

urlpatterns = [
    # keep these above router.urls so "scores/my/" isn't read as a score id
    path("scores/my/", MyScoresView.as_view(), name="my-scores"),
    path("results/class/", ClassResultsView.as_view(), name="class-results"),
    path("results/student/", StudentResultView.as_view(), name="student-result"),
    path("results/my/", MyResultView.as_view(), name="my-result"),
] + router.urls