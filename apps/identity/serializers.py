import re
from datetime import date
from decimal import Decimal

from rest_framework import serializers

from .services import minimum_birth_date

COUNTRIES = {"KE": "Kenya", "UG": "Uganda", "TZ": "Tanzania", "RW": "Rwanda"}
NAME_PATTERN = re.compile(r"^[^\W\d_]+(?:[ '\-][^\W\d_]+)*$")


class PersonalDetailsSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=150, trim_whitespace=True)
    last_name = serializers.CharField(max_length=150, trim_whitespace=True)
    date_of_birth = serializers.DateField()
    country = serializers.ChoiceField(choices=list(COUNTRIES.items()))
    residential_address = serializers.CharField(max_length=250, trim_whitespace=True)
    county = serializers.CharField(max_length=80, trim_whitespace=True)
    town = serializers.CharField(max_length=80, trim_whitespace=True)
    occupation = serializers.CharField(max_length=100, trim_whitespace=True)
    monthly_income = serializers.DecimalField(max_digits=14, decimal_places=2, min_value=Decimal("0.00"))

    def _name(self, value, label):
        if not NAME_PATTERN.match(value):
            raise serializers.ValidationError(f"Enter your {label} using letters, spaces, hyphens or apostrophes.")
        return value

    def validate_first_name(self, value):
        return self._name(value, "first name")

    def validate_last_name(self, value):
        return self._name(value, "last name")

    def validate_date_of_birth(self, value):
        if value > minimum_birth_date():
            raise serializers.ValidationError("You must be at least 18 years old to open a FinGuard account.")
        if value < date(1900, 1, 1):
            raise serializers.ValidationError("Enter a valid date of birth.")
        return value
