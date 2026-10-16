from django.shortcuts import get_object_or_404
from rest_framework import filters, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from administrator.permission import IsAdmin, IsTeacher

from .models import TeacherProfile
from .serializers import TeacherProfileSerializer


class TeacherViewSet(viewsets.ModelViewSet):
    queryset = TeacherProfile.objects.select_related("user")
    serializer_class = TeacherProfileSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["user__first_name", "user__last_name", "staff_id"]
    ordering_fields = ["staff_id", "date_hired", "user__last_name"]

    def get_permissions(self):
        if self.action == "me":
            return [IsTeacher()]
        return [IsAdmin()]

    @action(detail=False, methods=["get"])
    def me(self, request):
        profile = get_object_or_404(self.get_queryset(), user=request.user)
        return Response(self.get_serializer(profile).data)
