from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import AttendanceViewSet, MyAttendanceSummaryView, MyAttendanceView

router = DefaultRouter()
router.register("records", AttendanceViewSet, basename="attendance")

urlpatterns = [
    path("my/", MyAttendanceView.as_view(), name="my-attendance"),
    path("my/summary/", MyAttendanceSummaryView.as_view(), name="my-attendance-summary"),
] + router.urls