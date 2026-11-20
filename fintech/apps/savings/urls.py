from django.urls import path

from .views import (GoalContributionsView, SavingsActivityView, SavingsGoalDetailView, SavingsGoalListCreateView,
                    SavingsRecommendationView, SavingsScheduleDetailView, SavingsScheduleListCreateView)

urlpatterns = [
    path("goals/", SavingsGoalListCreateView.as_view(), name="savings-goals"),
    path("goals/<uuid:id>/", SavingsGoalDetailView.as_view(), name="savings-goal-detail"),
    path("goals/<uuid:goal_id>/contributions/", GoalContributionsView.as_view(), name="savings-contributions"),
    path("schedules/", SavingsScheduleListCreateView.as_view(), name="savings-schedules"),
    path("schedules/<uuid:id>/", SavingsScheduleDetailView.as_view(), name="savings-schedule-detail"),
    path("activity/", SavingsActivityView.as_view(), name="savings-activity"),
    path("recommendations/", SavingsRecommendationView.as_view(), name="savings-recommendation"),
]
