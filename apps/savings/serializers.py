from django.utils import timezone
from rest_framework import serializers

from .models import SavingsContribution, SavingsGoal, SavingsSchedule


class SavingsGoalSerializer(serializers.ModelSerializer):
    progress_percent = serializers.SerializerMethodField()

    class Meta:
        model = SavingsGoal
        fields = ["id", "name", "target_amount", "saved_amount", "progress_percent", "target_date", "currency", "archived_at", "created_at", "updated_at"]
        read_only_fields = ["id", "saved_amount", "progress_percent", "currency", "archived_at", "created_at", "updated_at"]

    def get_progress_percent(self, goal):
        if not goal.target_amount:
            return 0
        return min(100, round(goal.saved_amount / goal.target_amount * 100, 2))


class SavingsScheduleSerializer(serializers.ModelSerializer):
    authorize = serializers.BooleanField(write_only=True, required=False, default=False)
    action = serializers.ChoiceField(choices=["pause", "cancel"], write_only=True, required=False)

    class Meta:
        model = SavingsSchedule
        fields = ["id", "goal", "amount", "cadence", "start_date", "status", "authorized_at", "next_run_date", "last_run_at", "last_run_status", "authorize", "action", "created_at", "updated_at"]
        read_only_fields = ["id", "status", "authorized_at", "next_run_date", "last_run_at", "last_run_status", "created_at", "updated_at"]

    def validate_goal(self, goal):
        request = self.context.get("request")
        if request and goal.user_id != request.user.pk:
            raise serializers.ValidationError("Select one of your own savings goals.")
        if goal.archived_at:
            raise serializers.ValidationError("Archived goals cannot have automatic schedules.")
        return goal

    def validate(self, attrs):
        authorize = attrs.pop("authorize", False)
        action = attrs.pop("action", None)
        if authorize and action:
            raise serializers.ValidationError("Choose either to authorize or update the rule action, not both.")
        if authorize and self.instance and self.instance.status == SavingsSchedule.Status.CANCELLED:
            raise serializers.ValidationError({"authorize": "Cancelled rules cannot be re-enabled; create a new rule instead."})
        if action:
            if self.instance is None:
                raise serializers.ValidationError({"action": "Actions are only valid for an existing schedule."})
            attrs["status"] = SavingsSchedule.Status.PAUSED if action == "pause" else SavingsSchedule.Status.CANCELLED
        material_fields = {"goal", "amount", "cadence", "start_date"}
        if (self.instance and self.instance.status == SavingsSchedule.Status.AUTHORIZED
                and material_fields.intersection(attrs) and not authorize and not action):
            raise serializers.ValidationError({"authorize": "Reconfirm authorization when changing an active schedule."})
        if authorize:
            goal = attrs.get("goal", self.instance.goal if self.instance else None)
            if goal is None or goal.archived_at:
                raise serializers.ValidationError({"goal": "Select an active savings goal before enabling an automatic rule."})
            attrs["status"] = SavingsSchedule.Status.AUTHORIZED
            attrs["authorized_at"] = timezone.now()
            attrs["next_run_date"] = attrs.get("start_date", self.instance.start_date if self.instance else None)
        return attrs

    def create(self, validated_data):
        validated_data.setdefault("status", SavingsSchedule.Status.DRAFT)
        return super().create(validated_data)


class SavingsContributionSerializer(serializers.ModelSerializer):
    goal_name = serializers.CharField(source="goal.name", read_only=True)

    class Meta:
        model = SavingsContribution
        fields = ["id", "goal", "goal_name", "direction", "amount", "created_at"]
        read_only_fields = fields
