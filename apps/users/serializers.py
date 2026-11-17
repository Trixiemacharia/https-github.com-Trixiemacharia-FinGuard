import re
from django.contrib.auth import get_user_model, password_validation
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

User = get_user_model()


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, style={"input_type": "password"})

    class Meta:
        model = User
        fields = ["username", "email", "password"]

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value

    def validate_username(self, value):
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("That username is taken.")
        return value

    def validate(self, attrs):
        candidate_user = User(username=attrs.get("username", ""), email=attrs.get("email", ""))
        try:
            password_validation.validate_password(attrs["password"], user=candidate_user)
        except DjangoValidationError as exc:
            # A password policy failure belongs to the password field, rather
            # than being presented as a serializer-wide validation error.
            raise serializers.ValidationError({"password": exc.messages}) from exc
        return attrs

    def create(self, validated_data):
        return User.objects.create_user(
            username=validated_data["username"],
            email=validated_data["email"],
            password=validated_data["password"],
        )


class LoginSerializer(serializers.Serializer):
    """
    Field-presence validation only — the actual credential check (and its
    401/lockout handling) lives in the view via
    apps.users.services.authenticate_identifier, so the view controls the
    response status code precisely.
    """

    identifier = serializers.CharField()
    password = serializers.CharField(write_only=True, style={"input_type": "password"})


class MfaVerifySerializer(serializers.Serializer):
    mfa_token = serializers.CharField()
    otp_code = serializers.CharField(min_length=1, max_length=12)


class OnboardingDetailsSerializer(serializers.Serializer):
    residential_address = serializers.CharField(max_length=250, trim_whitespace=True)
    county = serializers.CharField(max_length=80, trim_whitespace=True)
    town = serializers.CharField(max_length=80, trim_whitespace=True)
    occupation = serializers.CharField(max_length=100, trim_whitespace=True)
    monthly_income = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=0, max_value=100_000_000)

    PLACE = re.compile(r"^[^\W\d_]+(?:[ '.\-][^\W\d_]+)*$")
    TEXT_WITH_LETTERS = re.compile(r"[^\W\d_]{2,}")

    def validate_residential_address(self, value):
        if not value:
            raise serializers.ValidationError("Enter a residential address.")
        if len(value) < 5 or not self.TEXT_WITH_LETTERS.search(value):
            raise serializers.ValidationError("Enter your full residential address, e.g. house or building, street and area.")
        return value

    def validate_county(self, value):
        if not value:
            raise serializers.ValidationError("Enter a county or region.")
        if len(value) < 2 or not self.PLACE.match(value):
            raise serializers.ValidationError("Use letters only for the county or region.")
        return value

    def validate_town(self, value):
        if not value:
            raise serializers.ValidationError("Enter a town.")
        if len(value) < 2 or not self.PLACE.match(value):
            raise serializers.ValidationError("Use letters only for the town.")
        return value

    def validate_occupation(self, value):
        if not value:
            raise serializers.ValidationError("Enter an occupation.")
        if len(value) < 2 or not self.TEXT_WITH_LETTERS.search(value):
            raise serializers.ValidationError("Describe your occupation in words, e.g. Teacher or Self-employed.")
        return value
