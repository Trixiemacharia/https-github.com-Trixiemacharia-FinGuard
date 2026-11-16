from rest_framework import generics
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated

from apps.users.models import wallet_access_allowed

from .models import SavingsGoal, SavingsSchedule
from .serializers import SavingsGoalSerializer, SavingsScheduleSerializer


class SavingsAccessMixin:
    permission_classes = [IsAuthenticated]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not wallet_access_allowed(request.user):
            raise PermissionDenied("Complete onboarding and receive account approval before using savings.")


class SavingsGoalListCreateView(SavingsAccessMixin, generics.ListCreateAPIView):
    serializer_class = SavingsGoalSerializer

    def get_queryset(self):
        return SavingsGoal.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class SavingsGoalDetailView(SavingsAccessMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = SavingsGoalSerializer
    lookup_field = "id"

    def get_queryset(self):
        return SavingsGoal.objects.filter(user=self.request.user)


class SavingsScheduleListCreateView(SavingsAccessMixin, generics.ListCreateAPIView):
    serializer_class = SavingsScheduleSerializer

    def get_queryset(self):
        return SavingsSchedule.objects.filter(user=self.request.user, goal__user=self.request.user).select_related("goal")

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class SavingsScheduleDetailView(SavingsAccessMixin, generics.RetrieveUpdateAPIView):
    serializer_class = SavingsScheduleSerializer
    lookup_field = "id"

    def get_queryset(self):
        return SavingsSchedule.objects.filter(user=self.request.user, goal__user=self.request.user).select_related("goal")
