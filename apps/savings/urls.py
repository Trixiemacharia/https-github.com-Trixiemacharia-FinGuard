from django.urls import path

from .views import SavingsGoalDetailView, SavingsGoalListCreateView, SavingsScheduleDetailView, SavingsScheduleListCreateView

urlpatterns = [
    path("goals/", SavingsGoalListCreateView.as_view(), name="savings-goals"),
    path("goals/<uuid:id>/", SavingsGoalDetailView.as_view(), name="savings-goal-detail"),
    path("schedules/", SavingsScheduleListCreateView.as_view(), name="savings-schedules"),
    path("schedules/<uuid:id>/", SavingsScheduleDetailView.as_view(), name="savings-schedule-detail"),
]
