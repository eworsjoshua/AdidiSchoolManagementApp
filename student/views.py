from django.shortcuts import get_object_or_404
from rest_framework import filters, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from administrator.permission import IsAdmin, IsStudent

from .models import StudentProfile
from .serializers import StudentProfileSerializer


class StudentViewSet(viewsets.ModelViewSet):
    queryset = StudentProfile.objects.select_related("user")
    serializer_class = StudentProfileSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["user__first_name", "user__last_name", "admission_number"]
    ordering_fields = ["admission_number", "date_admitted", "user__last_name"]

    def get_permissions(self):
        if self.action == "me":
            return [IsStudent()]
        return [IsAdmin()]

    @action(detail=False, methods=["get"])
    def me(self, request):
        profile = get_object_or_404(self.get_queryset(), user=request.user)
        return Response(self.get_serializer(profile).data)